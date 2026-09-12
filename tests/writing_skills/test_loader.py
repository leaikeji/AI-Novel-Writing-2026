import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from backend.writing_skills.catalog import create_approval_record
from backend.writing_skills.contracts import ApprovedAsset
from backend.writing_skills.loader import (
    CatalogError, MAX_ASSET_BYTES, inspect_release_candidate, load_capability, load_primary_blocks,
)

PROJECT = Path(__file__).resolve().parents[2]
SKILL_ID = "suspense-writing"
CURRENT_CAPABILITY_VERSION = "1.0.1"
CURRENT_APPROVAL_REF = "plan70-routing-boundary-20260912"


def test_primary_blocks_include_exact_explicit_dependencies_once():
    paths = ("references/narrative-craft.md", "references/genre-promises.md")
    blocks = load_primary_blocks(PROJECT / "skills", "prose-writing", paths)
    assert [block.path for block in blocks] == ["SKILL.md", *paths]
    for block in blocks:
        raw = (PROJECT / "skills" / "prose-writing" / block.path).read_bytes()
        assert block.text.encode() == raw
        assert block.sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("paths", [
    ("../outside.md",), ("/tmp/outside.md",), ("routing.json",),
    ("references/narrative-craft.md", "references/narrative-craft.md"),
])
def test_primary_blocks_reject_invalid_or_duplicate_dependencies(paths):
    with pytest.raises(CatalogError):
        load_primary_blocks(PROJECT / "skills", "prose-writing", paths)


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "skills"
    module = root / SKILL_ID
    shutil.copytree(PROJECT / "skills" / SKILL_ID, module)
    candidate = inspect_release_candidate(root, SKILL_ID)
    approval = create_approval_record(candidate,
                                     approval_ref=CURRENT_APPROVAL_REF,
                                     capability_version=CURRENT_CAPABILITY_VERSION)
    return root, module, approval


def test_loads_approved_exact_bytes_and_reference_hashes(package):
    root, module, approval = package
    loaded = load_capability(root, SKILL_ID, approval)
    assert loaded.body.text.encode() == (module / "SKILL.md").read_bytes()
    assert loaded.body.sha256 == next(asset.sha256 for asset in approval.assets if asset.path == "SKILL.md")
    assert {ref.path for ref in loaded.references} == {
        rule.path for rule in loaded.declaration.reference_rules
    }
    for ref in loaded.references:
        assert ref.sha256 == hashlib.sha256((module / ref.path).read_bytes()).hexdigest()


@pytest.mark.parametrize("asset", ["SKILL.md", "references/mystery-mechanisms.md", "routing.json"])
def test_post_approval_tampering_is_rejected(package, asset):
    root, module, approval = package
    path = module / asset
    path.write_bytes(path.read_bytes() + b"\n ")
    with pytest.raises(CatalogError, match="approval.*mismatch"):
        load_capability(root, SKILL_ID, approval)


@pytest.mark.parametrize("field,value", [
    ("skill_id", "other-skill"), ("capability_version", "1.1.0"),
    ("approval_ref", "different-approval"), ("routing_hash", "a" * 64),
])
def test_approval_identity_must_match(package, field, value):
    root, _, approval = package
    with pytest.raises(CatalogError, match="approval_mismatch"):
        load_capability(root, SKILL_ID, approval.model_copy(update={field: value}))


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "traversal"])
def test_approval_assets_are_exact_set(package, change):
    root, _, approval = package
    assets = approval.assets
    if change == "missing":
        assets = assets[:-1]
    elif change == "extra":
        assets += (ApprovedAsset(path="references/extra.md", sha256="b" * 64),)
    elif change == "duplicate":
        assets += assets[:1]
    else:
        assets = (ApprovedAsset(path="../outside.md", sha256=assets[0].sha256), *assets[1:])
    with pytest.raises(CatalogError, match="approval_assets_mismatch"):
        load_capability(root, SKILL_ID, approval.model_copy(update={"assets": assets}))


@pytest.mark.parametrize("path", ["../outside.md", "references/../outside.md", "/tmp/outside.md", "references//a.md"])
def test_reference_traversal_is_rejected(package, path):
    root, module, approval = package
    declaration = json.loads((module / "routing.json").read_text())
    declaration["reference_rules"][0]["path"] = path
    (module / "routing.json").write_text(json.dumps(declaration))
    with pytest.raises(CatalogError, match="invalid_declaration"):
        load_capability(root, SKILL_ID, approval)


def test_missing_optional_reference_is_still_invalid(package):
    root, module, approval = package
    (module / "references/mystery-mechanisms.md").unlink()
    with pytest.raises(CatalogError, match="asset_missing_or_unsafe"):
        load_capability(root, SKILL_ID, approval)


@pytest.mark.parametrize("part", ["SKILL.md", "references/mystery-mechanisms.md", "references"])
def test_file_and_parent_directory_symlinks_are_rejected(package, tmp_path, part):
    root, module, approval = package
    original = module / part
    outside = tmp_path / "outside"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=outside.is_dir())
    with pytest.raises(CatalogError, match="asset_missing_or_unsafe"):
        load_capability(root, SKILL_ID, approval)


def test_in_package_symlink_is_also_rejected(package):
    root, module, approval = package
    ref = module / "references/mystery-mechanisms.md"
    ref.rename(module / "references/renamed.md")
    ref.symlink_to("renamed.md")
    with pytest.raises(CatalogError, match="asset_missing_or_unsafe"):
        load_capability(root, SKILL_ID, approval)


@pytest.mark.parametrize("before,after,error", [
    ('capability_version: "1.0.1"', 'capability_version: "1.1.0"', "frontmatter_mismatch"),
    ("name: suspense-writing", "name: other-skill", "frontmatter_mismatch"),
    ("release_status: author_approved", "release_status: draft", "frontmatter_mismatch"),
    ("name: suspense-writing", "name: suspense-writing\nname: suspense-writing", "duplicate_frontmatter_key"),
    ('capability_version: "1.0.1"', 'capability_version: &version "1.0.1"', "unsupported_frontmatter"),
])
def test_frontmatter_contract_not_just_routing_self_assertion(package, before, after, error):
    root, module, approval = package
    body = module / "SKILL.md"
    body.write_text(body.read_text().replace(before, after))
    with pytest.raises(CatalogError, match=error):
        load_capability(root, SKILL_ID, approval)


@pytest.mark.parametrize("change,error", [
    ("unknown", "invalid_declaration"), ("schema", "invalid_declaration"),
    ("boolean_string", "invalid_declaration"), ("duplicate", "duplicate_json_key"),
    ("empty_tag", "ambiguous_declaration"), ("reference_task", "reference_task_not_applicable"),
])
def test_invalid_declarations_fail_closed(package, change, error):
    root, module, approval = package
    path = module / "routing.json"
    obj = json.loads(path.read_text())
    if change == "unknown":
        obj["execute"] = "arbitrary.py"
    elif change == "schema":
        obj["routing_schema_version"] = "writing-capability/99"
    elif change == "boolean_string":
        obj["auto_eligible"] = "true"
    elif change == "empty_tag":
        obj["genre_aliases"] = [" "]
    elif change == "reference_task":
        obj["reference_rules"][0]["tasks"] = ["mechanical"]
    raw = json.dumps(obj)
    if change == "duplicate":
        raw = raw.replace('"skill_id":', '"skill_id": "other", "skill_id":', 1)
    path.write_text(raw)
    with pytest.raises(CatalogError, match=error):
        load_capability(root, SKILL_ID, approval)


@pytest.mark.parametrize("kind", ["oversized", "fifo", "invalid_utf8"])
def test_assets_are_bounded_regular_utf8_files(package, kind):
    root, module, approval = package
    ref = module / "references/mystery-mechanisms.md"
    if kind == "oversized":
        ref.write_bytes(b"x" * (MAX_ASSET_BYTES + 1))
        error = "asset_too_large"
    elif kind == "fifo":
        ref.unlink()
        os.mkfifo(ref)
        error = "asset_not_regular"
    else:
        ref.write_bytes(b"\xff")
        error = "asset_not_utf8"
    with pytest.raises(CatalogError, match=error):
        load_capability(root, SKILL_ID, approval)


def test_crlf_bytes_are_not_normalized_before_hashing(package):
    root, module, _ = package
    path = module / "SKILL.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    candidate = inspect_release_candidate(root, SKILL_ID)
    approval = create_approval_record(candidate, approval_ref=candidate.declaration.approval_ref,
                                     capability_version=candidate.declaration.capability_version)
    assert load_capability(root, SKILL_ID, approval).body.text.encode() == path.read_bytes()


def test_deeply_nested_json_is_a_bounded_declaration_error(package):
    root, module, approval = package
    (module / "routing.json").write_text("[" * 2000 + "0" + "]" * 2000)
    with pytest.raises(CatalogError, match="invalid_declaration"):
        load_capability(root, SKILL_ID, approval)
