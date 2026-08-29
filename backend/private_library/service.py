"""Transactional private-library version, binding and snapshot services.

Writes only flush the caller-owned transaction; API integration decides when
to commit.  Every read function is side-effect free.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import NovelAssetBinding, PrivateAssetVersion
from ..models import AssetPreset, AssetPresetItem, Novel, PrivateAsset

from .contracts import (
    PRIVATE_ASSET_SNAPSHOT_VERSION,
    AssetWriteResult,
    BindingSetResult,
    BindingView,
    DirectAssetSelection,
    UsagePolicy,
    VersionSelection,
)
from .errors import (
    PrivateLibraryConflictError,
    PrivateLibraryIdempotencyConflict,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
)
from .hashing import canonical_hash


PRIVATE_ASSET_TYPES = frozenset({"plot", "writing_style", "vocabulary", "idea"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(value: str, *, field: str, maximum: int) -> str:
    normalized = str(value).strip()
    if not normalized or len(normalized) > maximum:
        raise PrivateLibraryValidationError(
            f"{field} must contain 1 to {maximum} characters"
        )
    return normalized


def _json_dict(value: dict[str, Any] | None, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PrivateLibraryValidationError(f"{field} must be an object")
    copied = deepcopy(value)
    canonical_hash(copied)
    return copied


def _tags(value: Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        tag = _required_text(item, field="tag", maximum=80)
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    if len(result) > 100:
        raise PrivateLibraryValidationError("tags cannot contain more than 100 items")
    return result


def _asset_content(
    *,
    title: str,
    content: str,
    metadata: dict[str, Any] | None,
    source: dict[str, Any] | None,
    rights: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = {
        "title": _required_text(title, field="title", maximum=240),
        "content": str(content).strip(),
        "metadata": _json_dict(metadata, field="metadata"),
        "source": _json_dict(source, field="source"),
        "rights": _json_dict(rights, field="rights"),
    }
    canonical_hash(normalized)
    return normalized


def _operation_key(value: str) -> str:
    return _required_text(value, field="operation_key", maximum=160)


def _usage_policy(value: UsagePolicy | str) -> UsagePolicy:
    try:
        return value if isinstance(value, UsagePolicy) else UsagePolicy(value)
    except ValueError as error:
        raise PrivateLibraryValidationError("usage_policy is not supported") from error


def _asset_current(asset: PrivateAsset) -> dict[str, Any]:
    return {
        "asset_id": str(asset.id),
        "root_version": int(asset.version),
        "current_version_id": (
            str(asset.current_version_id) if asset.current_version_id else None
        ),
        "archived": bool(asset.archived),
    }


def _lock_asset(session: Session, asset_id: UUID) -> PrivateAsset:
    asset = session.scalar(
        select(PrivateAsset).where(PrivateAsset.id == asset_id).with_for_update()
    )
    if asset is None:
        raise PrivateLibraryNotFoundError(f"private asset {asset_id} not found")
    return asset


def _idempotent_asset_version(
    session: Session, asset_id: UUID, operation_key: str
) -> PrivateAssetVersion | None:
    return session.scalar(
        select(PrivateAssetVersion).where(
            PrivateAssetVersion.asset_id == asset_id,
            PrivateAssetVersion.operation_key == operation_key,
        )
    )


def _current_asset_version(
    session: Session, asset: PrivateAsset
) -> PrivateAssetVersion:
    if asset.current_version_id is None:
        raise PrivateLibraryConflictError(
            "asset_current_version_missing", current=_asset_current(asset)
        )
    version = session.get(PrivateAssetVersion, asset.current_version_id)
    if version is None or version.asset_id != asset.id:
        raise PrivateLibraryConflictError(
            "asset_current_version_invalid", current=_asset_current(asset)
        )
    return version


def _new_asset_version(
    *,
    asset_id: UUID,
    version_number: int,
    operation_key: str,
    operation_hash: str,
    content: dict[str, Any],
    now: datetime,
) -> PrivateAssetVersion:
    return PrivateAssetVersion(
        id=uuid4(),
        asset_id=asset_id,
        version_number=version_number,
        title=content["title"],
        content=content["content"],
        metadata_json=deepcopy(content["metadata"]),
        source_json=deepcopy(content["source"]),
        rights_json=deepcopy(content["rights"]),
        content_hash=canonical_hash(content),
        operation_key=operation_key,
        operation_hash=operation_hash,
        created_at=now,
    )


def create_asset(
    session: Session,
    *,
    asset_type: str,
    title: str,
    content: str,
    operation_key: str,
    asset_id: UUID | None = None,
    tags: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    rights: dict[str, Any] | None = None,
) -> AssetWriteResult:
    """Create a stable root and its first immutable version in one transaction."""

    if asset_type not in PRIVATE_ASSET_TYPES:
        raise PrivateLibraryValidationError("asset_type is not supported")
    stable_id = asset_id or uuid4()
    key = _operation_key(operation_key)
    normalized_tags = _tags(tags)
    normalized_content = _asset_content(
        title=title,
        content=content,
        metadata=metadata,
        source=source,
        rights=rights,
    )
    operation_hash = canonical_hash(
        {
            "operation": "create",
            "asset_id": stable_id,
            "asset_type": asset_type,
            "tags": normalized_tags,
            "content": normalized_content,
        }
    )
    existing = session.scalar(
        select(PrivateAsset).where(PrivateAsset.id == stable_id).with_for_update()
    )
    if existing is not None:
        prior = _idempotent_asset_version(session, stable_id, key)
        if prior is not None and prior.operation_hash == operation_hash:
            return AssetWriteResult(existing, prior, True)
        if prior is not None:
            raise PrivateLibraryIdempotencyConflict(key)
        raise PrivateLibraryConflictError(
            "asset_already_exists", current=_asset_current(existing)
        )

    now = _now()
    version = _new_asset_version(
        asset_id=stable_id,
        version_number=1,
        operation_key=key,
        operation_hash=operation_hash,
        content=normalized_content,
        now=now,
    )
    asset = PrivateAsset(
        id=stable_id,
        asset_type=asset_type,
        title=version.title,
        content=version.content,
        version=1,
        archived=False,
        current_version_id=None,
        tags_json=normalized_tags,
        source_json=deepcopy(version.source_json),
        rights_json=deepcopy(version.rights_json),
        created_at=now,
        updated_at=now,
    )
    # The stable root and its first immutable version form a deliberate FK
    # cycle. Insert the nullable root pointer first, then the version, and only
    # then advance the pointer; the transaction is never committed in a
    # partially initialized state.
    session.add(asset)
    session.flush()
    session.add(version)
    session.flush()
    asset.current_version_id = version.id
    session.flush()
    return AssetWriteResult(asset, version, False)


def update_asset(
    session: Session,
    asset_id: UUID,
    *,
    expected_root_version: int,
    operation_key: str,
    title: str,
    content: str,
    tags: Iterable[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    rights: dict[str, Any] | None = None,
) -> AssetWriteResult:
    """Append a version and atomically advance the root's current pointer."""

    if isinstance(expected_root_version, bool) or expected_root_version <= 0:
        raise PrivateLibraryValidationError("expected_root_version must be positive")
    key = _operation_key(operation_key)
    operation_hash = canonical_hash(
        {
            "operation": "update",
            "asset_id": asset_id,
            "title": str(title).strip(),
            "content": str(content).strip(),
            "tags": list(tags) if tags is not None else None,
            "metadata": metadata,
            "source": source,
            "rights": rights,
        }
    )
    asset = _lock_asset(session, asset_id)
    prior = _idempotent_asset_version(session, asset_id, key)
    if prior is not None:
        if prior.operation_hash != operation_hash:
            raise PrivateLibraryIdempotencyConflict(key)
        return AssetWriteResult(asset, prior, True)
    if int(asset.version) != expected_root_version:
        raise PrivateLibraryConflictError(
            "asset_root_version_conflict", current=_asset_current(asset)
        )
    current = _current_asset_version(session, asset)
    normalized_tags = (
        _tags(tags) if tags is not None else deepcopy(asset.tags_json or [])
    )
    normalized_content = _asset_content(
        title=title,
        content=content,
        metadata=(metadata if metadata is not None else current.metadata_json),
        source=(source if source is not None else current.source_json),
        rights=(rights if rights is not None else current.rights_json),
    )
    now = _now()
    version = _new_asset_version(
        asset_id=asset.id,
        version_number=int(current.version_number) + 1,
        operation_key=key,
        operation_hash=operation_hash,
        content=normalized_content,
        now=now,
    )
    session.add(version)
    asset.title = version.title
    asset.content = version.content
    asset.current_version_id = version.id
    asset.tags_json = normalized_tags
    asset.source_json = deepcopy(version.source_json)
    asset.rights_json = deepcopy(version.rights_json)
    asset.version = int(asset.version) + 1
    asset.updated_at = now
    session.flush()
    return AssetWriteResult(asset, version, False)


def restore_asset(
    session: Session,
    asset_id: UUID,
    target_version_id: UUID,
    *,
    expected_root_version: int,
    operation_key: str,
) -> AssetWriteResult:
    """Restore by appending a copy; neither the target nor history is mutated."""

    if isinstance(expected_root_version, bool) or expected_root_version <= 0:
        raise PrivateLibraryValidationError("expected_root_version must be positive")
    key = _operation_key(operation_key)
    asset = _lock_asset(session, asset_id)
    target = session.get(PrivateAssetVersion, target_version_id)
    if target is None or target.asset_id != asset_id:
        raise PrivateLibraryNotFoundError(
            f"private asset version {target_version_id} not found"
        )
    restored_content = _asset_content(
        title=target.title,
        content=target.content,
        metadata=target.metadata_json,
        source=target.source_json,
        rights=target.rights_json,
    )
    if canonical_hash(restored_content) != target.content_hash:
        raise PrivateLibraryConflictError(
            "asset_version_hash_mismatch",
            current={
                "asset_id": str(asset.id),
                "asset_version_id": str(target.id),
            },
        )
    operation_hash = canonical_hash(
        {
            "operation": "restore",
            "asset_id": asset_id,
            "target_version_id": target.id,
            "target_content_hash": target.content_hash,
        }
    )
    prior = _idempotent_asset_version(session, asset_id, key)
    if prior is not None:
        if prior.operation_hash != operation_hash:
            raise PrivateLibraryIdempotencyConflict(key)
        return AssetWriteResult(asset, prior, True, target.id)
    if int(asset.version) != expected_root_version:
        raise PrivateLibraryConflictError(
            "asset_root_version_conflict", current=_asset_current(asset)
        )
    current = _current_asset_version(session, asset)
    now = _now()
    version = _new_asset_version(
        asset_id=asset.id,
        version_number=int(current.version_number) + 1,
        operation_key=key,
        operation_hash=operation_hash,
        content=restored_content,
        now=now,
    )
    session.add(version)
    asset.title = version.title
    asset.content = version.content
    asset.current_version_id = version.id
    asset.source_json = deepcopy(version.source_json)
    asset.rights_json = deepcopy(version.rights_json)
    asset.version = int(asset.version) + 1
    asset.updated_at = now
    session.flush()
    return AssetWriteResult(asset, version, False, target.id)


def get_asset(
    session: Session, asset_id: UUID
) -> tuple[PrivateAsset, PrivateAssetVersion]:
    asset = session.get(PrivateAsset, asset_id)
    if asset is None:
        raise PrivateLibraryNotFoundError(f"private asset {asset_id} not found")
    return asset, _current_asset_version(session, asset)


def list_asset_history(
    session: Session,
    asset_id: UUID,
    *,
    before_version_number: int | None = None,
    limit: int = 100,
) -> list[PrivateAssetVersion]:
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise PrivateLibraryValidationError("limit must be between 1 and 500")
    statement = select(PrivateAssetVersion).where(
        PrivateAssetVersion.asset_id == asset_id
    )
    if before_version_number is not None:
        statement = statement.where(
            PrivateAssetVersion.version_number < before_version_number
        )
    return list(
        session.scalars(
            statement.order_by(PrivateAssetVersion.version_number.desc()).limit(limit)
        ).all()
    )


def _lock_preset(session: Session, preset_id: UUID) -> AssetPreset:
    preset = session.scalar(
        select(AssetPreset).where(AssetPreset.id == preset_id).with_for_update()
    )
    if preset is None or preset.archived:
        raise PrivateLibraryNotFoundError(f"asset preset {preset_id} not found")
    return preset


def _validate_version_selections(
    session: Session,
    selections: Sequence[VersionSelection],
    *,
    require_active_root: bool,
) -> dict[UUID, tuple[PrivateAsset, PrivateAssetVersion]]:
    by_asset: dict[UUID, VersionSelection] = {}
    positions: set[int] = set()
    for selection in selections:
        _usage_policy(selection.usage_policy)
        if selection.asset_id in by_asset:
            raise PrivateLibraryValidationError("asset selection contains duplicate roots")
        if isinstance(selection.position, bool) or selection.position < 0:
            raise PrivateLibraryValidationError("selection position must be non-negative")
        if selection.position in positions:
            raise PrivateLibraryValidationError("asset selection contains duplicate positions")
        by_asset[selection.asset_id] = selection
        positions.add(selection.position)

    result: dict[UUID, tuple[PrivateAsset, PrivateAssetVersion]] = {}
    for asset_id, selection in by_asset.items():
        asset = session.get(PrivateAsset, asset_id)
        version = session.get(PrivateAssetVersion, selection.asset_version_id)
        if asset is None or (require_active_root and asset.archived):
            raise PrivateLibraryNotFoundError(f"private asset {asset_id} not found")
        if version is None or version.asset_id != asset_id:
            raise PrivateLibraryValidationError(
                "asset_version_id does not belong to the selected asset"
            )
        result[asset_id] = (asset, version)
    return result


def replace_preset_items(
    session: Session,
    preset_id: UUID,
    *,
    expected_preset_version: int,
    selections: Sequence[VersionSelection],
) -> tuple[AssetPresetItem, ...]:
    """Replace current preset membership; every new item pins an exact version."""

    if isinstance(expected_preset_version, bool) or expected_preset_version <= 0:
        raise PrivateLibraryValidationError("expected_preset_version must be positive")
    preset = _lock_preset(session, preset_id)
    if int(preset.version) != expected_preset_version:
        raise PrivateLibraryConflictError(
            "asset_preset_version_conflict",
            current={"preset_id": str(preset.id), "version": int(preset.version)},
        )
    _validate_version_selections(session, selections, require_active_root=True)
    existing = session.scalars(
        select(AssetPresetItem).where(AssetPresetItem.preset_id == preset_id)
    ).all()
    for item in existing:
        session.delete(item)
    session.flush()
    rows = tuple(
        AssetPresetItem(
            id=uuid4(),
            preset_id=preset_id,
            asset_id=selection.asset_id,
            asset_version_id=selection.asset_version_id,
            usage_policy=_usage_policy(selection.usage_policy).value,
            position=selection.position,
        )
        for selection in sorted(selections, key=lambda item: item.position)
    )
    session.add_all(rows)
    preset.version = int(preset.version) + 1
    preset.updated_at = _now()
    session.flush()
    return rows


def _lock_novel(session: Session, novel_id: UUID) -> Novel:
    novel = session.scalar(select(Novel).where(Novel.id == novel_id).with_for_update())
    if novel is None:
        raise PrivateLibraryNotFoundError(f"novel {novel_id} not found")
    return novel


def _active_bindings(session: Session, novel_id: UUID) -> list[NovelAssetBinding]:
    return list(
        session.scalars(
            select(NovelAssetBinding)
            .where(
                NovelAssetBinding.novel_id == novel_id,
                NovelAssetBinding.lifecycle_state == "active",
            )
            .order_by(NovelAssetBinding.position, NovelAssetBinding.id)
        ).all()
    )


def _binding_current(rows: Sequence[NovelAssetBinding]) -> dict[str, int]:
    return {str(row.asset_id): int(row.version) for row in rows}


def replace_novel_bindings(
    session: Session,
    novel_id: UUID,
    *,
    expected_binding_versions: dict[UUID, int],
    selections: Sequence[VersionSelection],
    operation_key: str,
) -> BindingSetResult:
    """CAS-replace a novel's active fixed-version binding set.

    Locking the novel root serializes membership changes, so an empty initial
    set cannot race another insertion.  Existing binding rows are retained when
    possible; changed versions always require an explicit caller selection.
    """

    key = _operation_key(operation_key)
    if any(
        isinstance(version, bool) or version <= 0
        for version in expected_binding_versions.values()
    ):
        raise PrivateLibraryValidationError("binding versions must be positive")
    _lock_novel(session, novel_id)
    existing_rows = _active_bindings(session, novel_id)
    existing = {row.asset_id: row for row in existing_rows}
    if expected_binding_versions != {
        asset_id: int(row.version) for asset_id, row in existing.items()
    }:
        raise PrivateLibraryConflictError(
            "novel_asset_bindings_conflict", current=_binding_current(existing_rows)
        )
    pairs = _validate_version_selections(
        session, selections, require_active_root=True
    )
    desired = {selection.asset_id: selection for selection in selections}
    global_hash = canonical_hash(
        {
            "operation": "replace_novel_bindings",
            "novel_id": novel_id,
            "selections": [
                {
                    "asset_id": item.asset_id,
                    "asset_version_id": item.asset_version_id,
                    "usage_policy": _usage_policy(item.usage_policy).value,
                    "position": item.position,
                }
                for item in sorted(selections, key=lambda value: value.position)
            ],
        }
    )
    changed_rows: list[NovelAssetBinding] = []
    removed_rows: list[NovelAssetBinding] = []
    unchanged_rows: list[NovelAssetBinding] = []
    now = _now()
    for asset_id, row in existing.items():
        selection = desired.get(asset_id)
        if selection is None:
            removed_rows.append(row)
            continue
        if (
            row.asset_version_id == selection.asset_version_id
            and row.usage_policy == _usage_policy(selection.usage_policy).value
            and int(row.position) == selection.position
        ):
            unchanged_rows.append(row)
        else:
            changed_rows.append(row)

    if not changed_rows and not removed_rows and len(existing) == len(desired):
        return BindingSetResult(
            tuple(_binding_views_from_rows(existing_rows, pairs)), False
        )

    for row in (*changed_rows, *removed_rows):
        row.lifecycle_state = "archived"
        row.version = int(row.version) + 1
        row.operation_key = key
        row.operation_hash = canonical_hash(
            {"set_hash": global_hash, "asset_id": row.asset_id, "state": "archived"}
        )
        row.updated_at = now
    if changed_rows or removed_rows:
        session.flush()

    active_rows = list(unchanged_rows)
    for asset_id, selection in desired.items():
        existing_row = existing.get(asset_id)
        if existing_row in unchanged_rows:
            continue
        row = existing_row
        if row is None:
            row = NovelAssetBinding(
                id=uuid4(),
                novel_id=novel_id,
                asset_id=asset_id,
                version=1,
                created_at=now,
            )
            session.add(row)
        row.asset_version_id = selection.asset_version_id
        row.usage_policy = _usage_policy(selection.usage_policy).value
        row.position = selection.position
        row.lifecycle_state = "active"
        row.operation_key = key
        row.operation_hash = canonical_hash(
            {
                "set_hash": global_hash,
                "asset_id": asset_id,
                "asset_version_id": selection.asset_version_id,
                "state": "active",
            }
        )
        row.updated_at = now
        active_rows.append(row)
    session.flush()
    from ..embedding.indexing import request_active_novel_refresh
    request_active_novel_refresh(session, novel_id)
    return BindingSetResult(
        tuple(_binding_views_from_rows(active_rows, pairs)), True
    )


def _binding_views_from_rows(
    rows: Sequence[NovelAssetBinding],
    pairs: dict[UUID, tuple[PrivateAsset, PrivateAssetVersion]],
) -> list[BindingView]:
    result: list[BindingView] = []
    for row in sorted(rows, key=lambda item: (item.position, str(item.id))):
        pair = pairs.get(row.asset_id)
        if pair is None:
            raise PrivateLibraryConflictError(
                "novel_asset_binding_target_missing",
                current={"binding_id": str(row.id)},
            )
        asset, version = pair
        if version.id != row.asset_version_id:
            raise PrivateLibraryConflictError(
                "novel_asset_binding_version_mismatch",
                current={"binding_id": str(row.id)},
            )
        result.append(
            BindingView(
                binding=row,
                asset=asset,
                asset_version=version,
                update_available=asset.current_version_id != row.asset_version_id,
            )
        )
    return result


def list_novel_bindings(session: Session, novel_id: UUID) -> list[BindingView]:
    """Return fixed bindings and update hints without changing any pointer."""

    if session.get(Novel, novel_id) is None:
        raise PrivateLibraryNotFoundError(f"novel {novel_id} not found")
    rows = _active_bindings(session, novel_id)
    selections = [
        VersionSelection(
            asset_id=row.asset_id,
            asset_version_id=row.asset_version_id,
            usage_policy=UsagePolicy(row.usage_policy),
            position=int(row.position),
        )
        for row in rows
    ]
    pairs = _validate_version_selections(
        session, selections, require_active_root=False
    )
    return _binding_views_from_rows(rows, pairs)


def _snapshot_item(
    *,
    asset: PrivateAsset,
    version: PrivateAssetVersion,
    usage_policy: UsagePolicy,
    source_kind: str,
    source_id: str,
    position: int,
) -> dict[str, Any]:
    content_payload = {
        "title": version.title,
        "content": version.content,
        "metadata": deepcopy(version.metadata_json or {}),
        "source": deepcopy(version.source_json or {}),
        "rights": deepcopy(version.rights_json or {}),
    }
    actual_hash = canonical_hash(content_payload)
    if actual_hash != version.content_hash:
        raise PrivateLibraryConflictError(
            "asset_version_hash_mismatch",
            current={
                "asset_id": str(asset.id),
                "asset_version_id": str(version.id),
            },
        )
    return {
        "snapshot_schema_version": PRIVATE_ASSET_SNAPSHOT_VERSION,
        "asset_id": str(asset.id),
        "asset_version_id": str(version.id),
        "version_number": int(version.version_number),
        "asset_type": asset.asset_type,
        "title": version.title,
        "content": version.content,
        "metadata": content_payload["metadata"],
        "source": content_payload["source"],
        "rights": content_payload["rights"],
        "content_hash": version.content_hash,
        "usage_policy": usage_policy.value,
        "selection_source": {
            "kind": source_kind,
            "source_id": source_id,
            "position": position,
        },
    }


def _version_pair(
    session: Session,
    asset_id: UUID,
    asset_version_id: UUID | None,
    *,
    require_active_root: bool,
) -> tuple[PrivateAsset, PrivateAssetVersion]:
    asset = session.get(PrivateAsset, asset_id)
    if asset is None or (require_active_root and asset.archived):
        raise PrivateLibraryNotFoundError(f"private asset {asset_id} not found")
    selected_version_id = asset_version_id or asset.current_version_id
    if selected_version_id is None:
        raise PrivateLibraryConflictError(
            "asset_current_version_missing", current=_asset_current(asset)
        )
    version = session.get(PrivateAssetVersion, selected_version_id)
    if version is None or version.asset_id != asset_id:
        raise PrivateLibraryValidationError(
            "asset_version_id does not belong to the selected asset"
        )
    return asset, version


def build_generation_asset_snapshot(
    session: Session,
    novel_id: UUID,
    *,
    direct_selections: Sequence[DirectAssetSelection] = (),
    preset_ids: Sequence[UUID] = (),
    include_novel_bindings: bool = True,
) -> list[dict[str, Any]]:
    """Copy immutable version content and provenance into a generation input.

    Direct selections may resolve the current pointer once, at snapshot time.
    Preset items and novel bindings must already contain exact version IDs.
    This function never adds, deletes, flushes or commits ORM rows.
    """

    if session.get(Novel, novel_id) is None:
        raise PrivateLibraryNotFoundError(f"novel {novel_id} not found")
    snapshot: list[dict[str, Any]] = []
    for ordinal, selection in enumerate(direct_selections):
        asset, version = _version_pair(
            session,
            selection.asset_id,
            selection.asset_version_id,
            require_active_root=True,
        )
        snapshot.append(
            _snapshot_item(
                asset=asset,
                version=version,
                usage_policy=_usage_policy(selection.usage_policy),
                source_kind="direct",
                source_id=selection.selection_key or f"direct:{ordinal}",
                position=ordinal,
            )
        )

    for preset_ordinal, preset_id in enumerate(preset_ids):
        preset = session.get(AssetPreset, preset_id)
        if preset is None or preset.archived:
            raise PrivateLibraryNotFoundError(f"asset preset {preset_id} not found")
        items = session.scalars(
            select(AssetPresetItem)
            .where(AssetPresetItem.preset_id == preset_id)
            .order_by(AssetPresetItem.position, AssetPresetItem.id)
        ).all()
        for item in items:
            if item.asset_version_id is None:
                raise PrivateLibraryConflictError(
                    "asset_preset_item_version_missing",
                    current={"preset_item_id": str(item.id)},
                )
            asset, version = _version_pair(
                session,
                item.asset_id,
                item.asset_version_id,
                require_active_root=False,
            )
            snapshot.append(
                _snapshot_item(
                    asset=asset,
                    version=version,
                    usage_policy=UsagePolicy(item.usage_policy),
                    source_kind="preset",
                    source_id=str(preset_id),
                    position=preset_ordinal * 1_000_000 + int(item.position),
                )
            )

    if include_novel_bindings:
        for view in list_novel_bindings(session, novel_id):
            snapshot.append(
                _snapshot_item(
                    asset=view.asset,
                    version=view.asset_version,
                    usage_policy=UsagePolicy(view.binding.usage_policy),
                    source_kind="novel_binding",
                    source_id=str(view.binding.id),
                    position=int(view.binding.position),
                )
            )
    return snapshot
