"""Read an immutable capability from the trusted package, without following links.

``root`` is the installed package's ``skills`` directory, supplied by the host
adapter, never a path taken from a novel, request, or capability declaration.
Inspection does not grant approval; ``load_capability`` also checks the separate
release record before returning content for dispatch.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from pydantic import ValidationError

from .contracts import (
    ApprovalRecord, CapabilityDeclaration, LoadedCapability, MethodBlock,
)

MAX_ASSET_BYTES = 256_000
MAX_ROUTING_BYTES = 64_000
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_KEY = re.compile(r"[a-zA-Z_][a-zA-Z0-9_-]*\Z")


class CatalogError(ValueError):
    """A bounded error code; never embeds the rejected file's contents."""


def trusted_skills_root(root: Path) -> Path:
    root = Path(root)
    if root.name != "skills" or root.is_symlink():
        raise CatalogError("invalid_skills_root")
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CatalogError("invalid_skills_root") from exc
    if not resolved.is_dir():
        raise CatalogError("invalid_skills_root")
    return resolved


def _read_file(root: Path, skill_id: str, relative: str, *, limit: int) -> bytes:
    """Walk every component using directory fds; reject even in-package links.

    Besides preventing traversal, O_NOFOLLOW prevents a checked reference from
    being swapped for a symlink between path validation and the actual read.
    """
    if not _ID.fullmatch(skill_id):
        raise CatalogError("invalid_skill_id")
    parts = relative.split("/")
    if any(not p or p in (".", "..") or "\\" in p for p in parts):
        raise CatalogError("invalid_asset_path")
    descriptors: list[int] = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(root, flags))
        for part in (skill_id, *parts[:-1]):
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        # O_NONBLOCK makes a hostile FIFO reject immediately rather than hang.
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=descriptors[-1])
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CatalogError("asset_not_regular")
        if info.st_size > limit:
            raise CatalogError("asset_too_large")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) > limit:
            raise CatalogError("asset_too_large")
        return value
    except OSError as exc:
        raise CatalogError("asset_missing_or_unsafe") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogError("asset_not_utf8") from exc


def load_primary_blocks(root: Path, skill_id: str, references: tuple[str, ...] = ()) -> tuple[MethodBlock, ...]:
    """Trusted task adapter's explicit dependencies, never client-supplied paths."""
    root = trusted_skills_root(root)
    paths = ("SKILL.md", *references)
    if len(set(paths)) != len(paths):
        raise CatalogError("duplicate_primary_dependency")
    blocks = []
    for path in paths:
        if path != "SKILL.md" and not (path.startswith("references/") and path.endswith(".md")):
            raise CatalogError("invalid_primary_dependency")
        raw = _read_file(root, skill_id, path, limit=MAX_ASSET_BYTES)
        blocks.append(MethodBlock(skill_id=skill_id, path=path, text=_decode(raw),
                                  sha256=hashlib.sha256(raw).hexdigest()))
    if _frontmatter(blocks[0].text).get(("name",)) != skill_id:
        raise CatalogError("primary_name_mismatch")
    return tuple(blocks)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("duplicate_json_key")
        result[key] = value
    return result


def read_declaration(root: Path, skill_id: str) -> tuple[CapabilityDeclaration, str]:
    root = trusted_skills_root(root)
    raw = _read_file(root, skill_id, "routing.json", limit=MAX_ROUTING_BYTES)
    try:
        text = _decode(raw)
        json.loads(text, object_pairs_hook=_unique_object)
        declaration = CapabilityDeclaration.model_validate_json(text, strict=True)
    except (ValidationError, ValueError, RecursionError) as exc:
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError("invalid_declaration") from exc
    # The shared DTO permits tuples; reject ambiguous or blank metadata here.
    for values in (
        declaration.genre_aliases, declaration.mechanism_tags,
        declaration.applicable_tasks, declaration.excluded_tasks,
        declaration.semantic_criteria, declaration.negative_examples,
        declaration.conflicts_with, declaration.supersedes,
    ):
        if any(not value.strip() for value in values) or len(set(values)) != len(values):
            raise CatalogError("ambiguous_declaration")
    for rule in declaration.reference_rules:
        if not set(rule.tasks) <= set(declaration.applicable_tasks):
            raise CatalogError("reference_task_not_applicable")
    return declaration, hashlib.sha256(raw).hexdigest()


def _frontmatter(text: str) -> dict[tuple[str, ...], str]:
    """Parse the package's deliberately narrow YAML string-mapping subset.

    No YAML objects, tags, anchors, aliases, lists or multiline scalars are
    interpreted. Full YAML is not a runtime dependency. Unknown scalar metadata
    is harmless, while duplicate keys or unsupported syntax fail closed.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise CatalogError("missing_frontmatter")
    result: dict[tuple[str, ...], str] = {}
    seen: set[tuple[str, ...]] = set()
    parents: list[str] = []
    for line in lines[1:]:
        if line == "---":
            return result
        if not line.strip():
            continue
        if "\t" in line:
            raise CatalogError("unsupported_frontmatter")
        spaces = len(line) - len(line.lstrip(" "))
        level = spaces // 2
        if spaces % 2 or level > len(parents):
            raise CatalogError("unsupported_frontmatter")
        key, sep, value = line.strip().partition(":")
        if not sep or not _KEY.fullmatch(key):
            raise CatalogError("unsupported_frontmatter")
        parents = parents[:level]
        path = (*parents, key)
        if path in seen:
            raise CatalogError("duplicate_frontmatter_key")
        seen.add(path)
        value = value.strip()
        if not value:
            parents.append(key)
            continue
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise CatalogError("unsupported_frontmatter") from exc
            if not isinstance(value, str):
                raise CatalogError("unsupported_frontmatter")
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise CatalogError("unsupported_frontmatter")
            value = value[1:-1].replace("''", "'")
        elif value[0] in "&*!|>{[" or " #" in value or ": " in value:
            raise CatalogError("unsupported_frontmatter")
        result[path] = value
    raise CatalogError("unterminated_frontmatter")


def inspect_release_candidate(root: Path, skill_id: str) -> LoadedCapability:
    """Read and validate release assets, WITHOUT approving them for runtime use.

    This is for trusted packaging tools. Runtime callers use ``load_catalog``
    with an independently supplied approval index and public enabled-ID set.
    """
    root = trusted_skills_root(root)
    declaration, routing_hash = read_declaration(root, skill_id)
    if declaration.skill_id != skill_id:
        raise CatalogError("directory_id_mismatch")
    raw = _read_file(root, skill_id, "SKILL.md", limit=MAX_ASSET_BYTES)
    text = _decode(raw)
    metadata = _frontmatter(text)
    expected = {
        ("name",): skill_id,
        ("metadata", "capability_version"): declaration.capability_version,
        ("metadata", "release_status"): declaration.release_status,
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise CatalogError("frontmatter_mismatch")
    body = MethodBlock(skill_id=skill_id, path="SKILL.md", text=text,
                       sha256=hashlib.sha256(raw).hexdigest())
    references: list[MethodBlock] = []
    for path in sorted({rule.path for rule in declaration.reference_rules}):
        raw = _read_file(root, skill_id, path, limit=MAX_ASSET_BYTES)
        references.append(MethodBlock(skill_id=skill_id, path=path,
                                      text=_decode(raw), sha256=hashlib.sha256(raw).hexdigest()))
    return LoadedCapability(declaration=declaration, routing_hash=routing_hash,
                            body=body, references=tuple(references))


def load_capability(root: Path, skill_id: str, approval: ApprovalRecord) -> LoadedCapability:
    candidate = inspect_release_candidate(root, skill_id)
    declaration = candidate.declaration
    if (approval.skill_id, approval.capability_version, approval.approval_ref,
        approval.routing_hash) != (
        skill_id, declaration.capability_version, declaration.approval_ref,
        candidate.routing_hash,
    ):
        raise CatalogError("approval_mismatch")
    expected = {block.path: block.sha256 for block in (candidate.body, *candidate.references)}
    actual = {asset.path: asset.sha256 for asset in approval.assets}
    if len(actual) != len(approval.assets) or actual != expected:
        raise CatalogError("approval_assets_mismatch")
    return candidate
