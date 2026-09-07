import json
from pathlib import Path
import shutil

import pytest

from backend.writing_skills.catalog import (
    asset_inventory, create_approval_record, load_catalog,
)
from backend.writing_skills.loader import CatalogError, inspect_release_candidate

PROJECT = Path(__file__).resolve().parents[2]
FORMAL_IDS = frozenset({"suspense-writing", "golden-finger-writing"})


def approve(root, skill_id):
    candidate = inspect_release_candidate(root, skill_id)
    return create_approval_record(candidate,
                                 approval_ref=candidate.declaration.approval_ref,
                                 capability_version=candidate.declaration.capability_version)


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "skills"
    for skill_id in FORMAL_IDS:
        shutil.copytree(PROJECT / "skills" / skill_id, root / skill_id)
    return root, tuple(approve(root, skill_id) for skill_id in sorted(FORMAL_IDS))


def ids(catalog):
    return {item.declaration.skill_id for item in catalog.capabilities}


def test_only_approved_enabled_formal_modules_are_discovered(package):
    root, approvals = package
    generic = root / "prose-writing"
    generic.mkdir()
    (generic / "SKILL.md").write_text("No routing declaration.")
    # Nested copies are not discovered through recursion.
    shutil.copytree(root / "suspense-writing", generic / "nested")
    result = load_catalog(root, approvals, FORMAL_IDS)
    assert ids(result) == FORMAL_IDS
    assert result.rejected == ()
    assert [c.declaration.skill_id for c in result.capabilities] == sorted(FORMAL_IDS)
    assert result.version == load_catalog(root, tuple(reversed(approvals)), FORMAL_IDS).version


def test_module_cannot_self_approve_even_with_local_index(package):
    root, _ = package
    (root / "suspense-writing/approval.json").write_text('{"approved": true}')
    result = load_catalog(root, (), FORMAL_IDS)
    assert not result.capabilities
    assert all(reason.endswith(":not_approved") for reason in result.rejected)


def test_public_disable_wins_over_approval(package):
    root, approvals = package
    both = load_catalog(root, approvals, FORMAL_IDS)
    result = load_catalog(root, approvals, frozenset({"golden-finger-writing"}))
    assert ids(result) == {"golden-finger-writing"}
    assert result.rejected == ("suspense-writing:disabled",)
    assert result.version != both.version


def test_future_third_module_requires_no_catalog_code_change(package):
    root, approvals = package
    third_id = "future-space-writing"
    third = root / third_id
    shutil.copytree(root / "suspense-writing", third)
    body = third / "SKILL.md"
    body.write_text(body.read_text().replace("name: suspense-writing", f"name: {third_id}"))
    routing = third / "routing.json"
    declaration = json.loads(routing.read_text())
    declaration.update(skill_id=third_id, display_name="测试太空", genre_aliases=["测试太空"],
                       approval_ref="test-only-approved-space")
    routing.write_text(json.dumps(declaration))
    before = load_catalog(root, approvals, FORMAL_IDS | {third_id})
    assert ids(before) == FORMAL_IDS
    assert f"{third_id}:not_approved" in before.rejected
    after = load_catalog(root, (*approvals, approve(root, third_id)), FORMAL_IDS | {third_id})
    assert ids(after) == FORMAL_IDS | {third_id}
    assert after.rejected == ()
    assert before.version != after.version


def test_duplicate_declared_id_rejects_all_conflicting_directories(package):
    root, approvals = package
    shutil.copytree(root / "suspense-writing", root / "duplicate-copy")
    result = load_catalog(root, approvals, FORMAL_IDS)
    assert ids(result) == {"golden-finger-writing"}
    assert "suspense-writing:duplicate_skill_id" in result.rejected
    assert "duplicate-copy:duplicate_skill_id" in result.rejected


def test_duplicate_approval_is_not_resolved_by_last_write(package):
    root, approvals = package
    result = load_catalog(root, (*approvals, approvals[0]), FORMAL_IDS)
    assert approvals[0].skill_id not in ids(result)
    assert f"{approvals[0].skill_id}:duplicate_approval" in result.rejected


def test_one_bad_module_does_not_hide_another_valid_module(package):
    root, approvals = package
    (root / "suspense-writing/SKILL.md").write_text("no frontmatter")
    result = load_catalog(root, approvals, FORMAL_IDS)
    assert ids(result) == {"golden-finger-writing"}
    assert result.rejected == ("suspense-writing:missing_frontmatter",)


def test_unsafe_module_path_never_enters_discovery(package, tmp_path):
    root, approvals = package
    module = root / "suspense-writing"
    target = tmp_path / "outside-module"
    module.rename(target)
    module.symlink_to(target, target_is_directory=True)
    result = load_catalog(root, approvals, FORMAL_IDS)
    assert ids(result) == {"golden-finger-writing"}
    assert result.rejected == ("suspense-writing:unsafe_module_path",)


@pytest.mark.parametrize("kind", ["wrong_name", "missing", "file", "link"])
def test_untrusted_root_fails_instead_of_scanning_parent(tmp_path, kind):
    root = tmp_path / "skills"
    if kind == "wrong_name":
        root = tmp_path
    elif kind == "file":
        root.write_text("not a directory")
    elif kind == "link":
        target = tmp_path / "target"
        target.mkdir()
        root.symlink_to(target, target_is_directory=True)
    with pytest.raises(CatalogError, match="invalid_skills_root"):
        load_catalog(root, (), frozenset())


def test_unknown_relation_is_rejected_but_disabled_registered_target_is_valid(package):
    root, approvals = package
    path = root / "suspense-writing/routing.json"
    declaration = json.loads(path.read_text())
    declaration["conflicts_with"] = ["golden-finger-writing"]
    path.write_text(json.dumps(declaration))
    approvals = tuple(a for a in approvals if a.skill_id != "suspense-writing") + (
        approve(root, "suspense-writing"),
    )
    assert ids(load_catalog(root, approvals, frozenset({"suspense-writing"}))) == {"suspense-writing"}
    declaration["conflicts_with"] = ["nonexistent-writing"]
    path.write_text(json.dumps(declaration))
    approvals = tuple(a for a in approvals if a.skill_id != "suspense-writing") + (
        approve(root, "suspense-writing"),
    )
    result = load_catalog(root, approvals, FORMAL_IDS)
    assert "suspense-writing:unknown_relation" in result.rejected


def test_release_helper_requires_matching_external_decision(package):
    root, _ = package
    candidate = inspect_release_candidate(root, "suspense-writing")
    with pytest.raises(CatalogError, match="release_decision_mismatch"):
        create_approval_record(candidate, approval_ref="unrelated", capability_version="1.0.0")
    assert [asset.path for asset in asset_inventory(candidate)] == sorted(
        [candidate.body.path, *(r.path for r in candidate.references)]
    )
