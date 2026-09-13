"""Scoped structured-lexicon services built on immutable private assets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID, uuid5

from sqlalchemy import Text, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import Session

from ..creative_data_models import NovelAssetBinding, PrivateAssetVersion
from ..models import PrivateAsset
from ..novel_lifecycle import lock_active_novel, require_active_novel
from .errors import (
    PrivateLibraryConflictError,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
)
from .hashing import canonical_hash, canonical_json
from .lexicon_contracts import (
    MAX_EFFECTIVE_RULES,
    MAX_LEXICON_METADATA_BYTES,
    LexiconAction,
    LexiconEntry,
    LexiconPack,
)
from .service import create_asset, update_asset


COLLECTION_NAMESPACE = UUID("8c984259-301b-54f7-b6b3-91010f1a973a")
LIBRARY_COLLECTION_KEY = "author-vocabulary"
NOVEL_COLLECTION_KEY = "novel-vocabulary"
COLLECTION_TITLES = {
    LIBRARY_COLLECTION_KEY: "我的收藏用词",
    NOVEL_COLLECTION_KEY: "本书用词",
}


@dataclass(frozen=True, slots=True)
class EffectiveLexiconRule:
    asset_id: UUID
    asset_version_id: UUID
    entry: LexiconEntry
    position: int


@dataclass(frozen=True, slots=True)
class EffectiveLexiconPolicy:
    novel_id: UUID
    rules: tuple[EffectiveLexiconRule, ...]
    conflicts: tuple[dict[str, object], ...]
    rules_hash: str


@dataclass(frozen=True, slots=True)
class ScopedAssetPage:
    items: tuple[dict[str, object], ...]
    offset: int
    limit: int
    total: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @property
    def next_offset(self) -> int | None:
        return self.offset + len(self.items) if self.has_more else None


def effective_policy_snapshot(policy: EffectiveLexiconPolicy) -> dict[str, object]:
    return {
        "schema_version": "effective-lexicon-policy/1",
        "novel_id": str(policy.novel_id),
        "rules_hash": policy.rules_hash,
        "rules": [
            {
                "asset_id": str(item.asset_id),
                "asset_version_id": str(item.asset_version_id),
                "position": item.position,
                "entry": item.entry.model_dump(mode="json"),
            }
            for item in policy.rules
        ],
        "conflicts": list(policy.conflicts),
    }


def effective_policy_from_snapshot(
    novel_id: UUID,
    snapshot: object,
) -> EffectiveLexiconPolicy:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != (
        "effective-lexicon-policy/1"
    ):
        raise PrivateLibraryValidationError("effective lexicon snapshot is invalid")
    if snapshot.get("novel_id") != str(novel_id):
        raise PrivateLibraryNotFoundError("effective lexicon snapshot is outside the novel")
    raw_rules = snapshot.get("rules")
    raw_conflicts = snapshot.get("conflicts")
    if not isinstance(raw_rules, list) or not isinstance(raw_conflicts, list):
        raise PrivateLibraryValidationError("effective lexicon snapshot is incomplete")
    if len(raw_rules) > MAX_EFFECTIVE_RULES:
        raise PrivateLibraryValidationError("effective lexicon snapshot exceeds its budget")
    rules: list[EffectiveLexiconRule] = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise PrivateLibraryValidationError("effective lexicon rule is invalid")
        try:
            rule = EffectiveLexiconRule(
                asset_id=UUID(str(raw["asset_id"])),
                asset_version_id=UUID(str(raw["asset_version_id"])),
                entry=LexiconEntry.model_validate(raw["entry"]),
                position=int(raw["position"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PrivateLibraryValidationError(
                "effective lexicon rule is invalid"
            ) from error
        rules.append(rule)
    payload = [
        {
            "asset_id": item.asset_id,
            "asset_version_id": item.asset_version_id,
            "entry": item.entry.model_dump(mode="json"),
        }
        for item in rules
    ]
    actual_hash = canonical_hash(payload)
    if snapshot.get("rules_hash") != actual_hash:
        raise PrivateLibraryConflictError(
            "effective_lexicon_snapshot_hash_mismatch",
            current={"rules_hash": actual_hash},
        )
    conflicts = tuple(item for item in raw_conflicts if isinstance(item, dict))
    if len(conflicts) != len(raw_conflicts):
        raise PrivateLibraryValidationError("effective lexicon conflicts are invalid")
    return EffectiveLexiconPolicy(
        novel_id=novel_id,
        rules=tuple(rules),
        conflicts=conflicts,
        rules_hash=actual_hash,
    )


def _scope_tuple(asset: PrivateAsset) -> tuple[str, UUID | None]:
    return str(asset.scope_kind), asset.scope_novel_id


def require_asset_scope(
    asset: PrivateAsset,
    *,
    novel_id: UUID | None,
    allow_library: bool = True,
) -> None:
    scope_kind, scope_novel_id = _scope_tuple(asset)
    if scope_kind == "library" and scope_novel_id is None and allow_library:
        return
    if scope_kind == "novel" and novel_id is not None and scope_novel_id == novel_id:
        return
    raise PrivateLibraryNotFoundError("private asset is outside the trusted scope")


def _scope_filter(novel_id: UUID | None):
    library = (
        (PrivateAsset.scope_kind == "library")
        & PrivateAsset.scope_novel_id.is_(None)
    )
    if novel_id is None:
        return library
    return or_(
        library,
        (PrivateAsset.scope_kind == "novel")
        & (PrivateAsset.scope_novel_id == novel_id),
    )


def _asset_view(
    session: Session,
    asset: PrivateAsset,
    *,
    novel_id: UUID | None,
) -> dict[str, object]:
    if asset.current_version_id is None:
        raise PrivateLibraryConflictError(
            "asset_current_version_missing", current={"asset_id": str(asset.id)}
        )
    version = session.get(PrivateAssetVersion, asset.current_version_id)
    if version is None or version.asset_id != asset.id:
        raise PrivateLibraryConflictError(
            "asset_current_version_invalid", current={"asset_id": str(asset.id)}
        )
    binding_count = int(session.scalar(
        select(func.count(NovelAssetBinding.id)).where(
            NovelAssetBinding.asset_id == asset.id,
            NovelAssetBinding.lifecycle_state == "active",
        )
    ) or 0)
    enabled = False
    binding_version: int | None = None
    if novel_id is not None:
        binding = session.scalar(
            select(NovelAssetBinding).where(
                NovelAssetBinding.novel_id == novel_id,
                NovelAssetBinding.asset_id == asset.id,
                NovelAssetBinding.lifecycle_state == "active",
            ).limit(1)
        )
        enabled = binding is not None and binding.usage_policy != "prohibited"
        binding_version = int(binding.version) if binding is not None else None
    metadata = dict(version.metadata_json or {})
    return {
        "id": str(asset.id),
        "asset_type": asset.asset_type,
        "title": version.title,
        "content": version.content,
        "summary": version.content[:500],
        "version": int(asset.version),
        "current_version_id": str(version.id),
        "archived": bool(asset.archived),
        "scope_kind": asset.scope_kind,
        "scope_novel_id": (
            str(asset.scope_novel_id) if asset.scope_novel_id else None
        ),
        "collection_key": asset.collection_key,
        "source_asset_id": str(asset.source_asset_id) if asset.source_asset_id else None,
        "source_version_id": (
            str(asset.source_version_id) if asset.source_version_id else None
        ),
        "tags": list(asset.tags_json or []),
        "binding_count": binding_count,
        "enabled": enabled,
        "binding_version": binding_version,
        "metadata": metadata,
        "lexicon": metadata if metadata.get("schema_version") == "lexicon-pack/1" else None,
        "entry_count": len(metadata.get("entries", []))
        if metadata.get("schema_version") == "lexicon-pack/1" else 0,
        "detail_loaded": True,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }


def list_scoped_assets(
    session: Session,
    *,
    novel_id: UUID | None = None,
    asset_type: str | None = None,
    query: str = "",
    include_archived: bool = False,
    offset: int = 0,
    limit: int = 50,
    scope_filter: str = "all",
    enabled_filter: str = "all",
    projection: str = "full",
) -> ScopedAssetPage:
    if asset_type is not None and (not isinstance(asset_type, str) or asset_type not in {
        "plot", "writing_style", "vocabulary", "idea",
    }):
        raise PrivateLibraryValidationError("asset type is not supported")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PrivateLibraryValidationError("offset must be non-negative")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise PrivateLibraryValidationError("limit must be between 1 and 100")
    if not isinstance(query, str) or len(query) > 200:
        raise PrivateLibraryValidationError("query is too long")
    if not isinstance(include_archived, bool):
        raise PrivateLibraryValidationError("include_archived must be a boolean")
    if not isinstance(scope_filter, str) or scope_filter not in {"all", "library", "novel"}:
        raise PrivateLibraryValidationError("scope_filter is not supported")
    if not isinstance(enabled_filter, str) or enabled_filter not in {"all", "enabled", "disabled"}:
        raise PrivateLibraryValidationError("enabled_filter is not supported")
    if not isinstance(projection, str) or projection not in {"full", "summary"}:
        raise PrivateLibraryValidationError("projection is not supported")
    if novel_id is None and (scope_filter == "novel" or enabled_filter != "all"):
        raise PrivateLibraryValidationError("trusted novel scope is required for these filters")
    if novel_id is not None:
        require_active_novel(session, novel_id)
    conditions = [_scope_filter(novel_id)]
    if scope_filter != "all":
        conditions.append(PrivateAsset.scope_kind == scope_filter)
    if asset_type is not None:
        conditions.append(PrivateAsset.asset_type == asset_type)
    if not include_archived:
        conditions.append(PrivateAsset.archived.is_(False))
    if enabled_filter != "all":
        enabled = select(NovelAssetBinding.id).where(
            NovelAssetBinding.asset_id == PrivateAsset.id,
            NovelAssetBinding.novel_id == novel_id,
            NovelAssetBinding.lifecycle_state == "active",
            NovelAssetBinding.usage_policy != "prohibited",
        ).exists()
        conditions.append(enabled if enabled_filter == "enabled" else ~enabled)
    normalized = query.strip()
    if normalized:
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        searchable_columns = [
            PrivateAssetVersion.title,
            PrivateAssetVersion.content,
            cast(PrivateAsset.tags_json, Text),
            *[
                cast(func.jsonb_path_query_array(
                    PrivateAssetVersion.metadata_json, cast(path, JSONPATH),
                ), Text)
                for path in (
                    "$.entries[*].term", "$.entries[*].note",
                    "$.entries[*].variants[*]", "$.entries[*].categories[*]",
                    "$.entries[*].replacement_hint",
                )
            ],
        ]
        conditions.append(or_(*[
            column.ilike(f"%{escaped}%", escape="\\")
            for column in searchable_columns
        ]))
    version_join = (
        (PrivateAssetVersion.id == PrivateAsset.current_version_id)
        & (PrivateAssetVersion.asset_id == PrivateAsset.id)
    )
    total = int(session.scalar(
        select(func.count(PrivateAsset.id))
        .outerjoin(PrivateAssetVersion, version_join)
        .where(*conditions)
    ) or 0)
    # Column projection is deliberate: summary pages never load complete packs
    # into Python, even when the ORM identity map does not contain them yet.
    columns = [
        PrivateAsset.id, PrivateAsset.asset_type, PrivateAsset.version,
        PrivateAsset.current_version_id, PrivateAsset.archived,
        PrivateAsset.scope_kind, PrivateAsset.scope_novel_id,
        PrivateAsset.collection_key, PrivateAsset.source_asset_id,
        PrivateAsset.source_version_id, PrivateAsset.tags_json.label("tags"),
        PrivateAsset.created_at, PrivateAsset.updated_at,
        PrivateAssetVersion.id.label("resolved_version_id"),
        PrivateAssetVersion.title,
        func.substr(PrivateAssetVersion.content, 1, 500).label("summary"),
        case(
            ((PrivateAssetVersion.metadata_json["schema_version"].astext == "lexicon-pack/1")
             & (func.jsonb_typeof(PrivateAssetVersion.metadata_json["entries"]) == "array"),
             func.jsonb_array_length(PrivateAssetVersion.metadata_json["entries"])),
            else_=0,
        ).label("entry_count"),
    ]
    if projection == "full":
        columns.extend([
            PrivateAssetVersion.content,
            PrivateAssetVersion.metadata_json.label("metadata"),
        ])
    rows = session.execute(
        select(*columns)
        .outerjoin(PrivateAssetVersion, version_join)
        .where(*conditions)
        .order_by(PrivateAsset.updated_at.desc(), PrivateAsset.id)
        .offset(offset)
        .limit(limit)
    ).mappings().all()
    binding_stats = {}
    if rows:
        stats = session.execute(
            select(
                NovelAssetBinding.asset_id,
                func.count(NovelAssetBinding.id).label("binding_count"),
                func.max(case((
                    NovelAssetBinding.novel_id == novel_id,
                    NovelAssetBinding.version,
                ), else_=None)).label("binding_version"),
                func.max(case((
                    (NovelAssetBinding.novel_id == novel_id)
                    & (NovelAssetBinding.usage_policy != "prohibited"),
                    1,
                ), else_=0)).label("enabled"),
            ).where(
                NovelAssetBinding.asset_id.in_([row["id"] for row in rows]),
                NovelAssetBinding.lifecycle_state == "active",
            ).group_by(NovelAssetBinding.asset_id)
        ).mappings().all()
        binding_stats = {row["asset_id"]: row for row in stats}
    items: list[dict[str, object]] = []
    for row in rows:
        if row["resolved_version_id"] is None:
            raise PrivateLibraryConflictError(
                "asset_current_version_invalid", current={"asset_id": str(row["id"])}
            )
        item = dict(row)
        del item["resolved_version_id"]
        for key in (
            "id", "current_version_id", "scope_novel_id", "source_asset_id", "source_version_id",
        ):
            item[key] = str(item[key]) if item[key] is not None else None
        stat = binding_stats.get(row["id"], {})
        binding_version = stat.get("binding_version")
        item.update({
            "tags": list(item["tags"] or []),
            "entry_count": int(item["entry_count"] or 0),
            "binding_count": int(stat.get("binding_count", 0)),
            "enabled": bool(stat.get("enabled", False)),
            "binding_version": int(binding_version) if binding_version is not None else None,
            "detail_loaded": projection == "full",
        })
        if projection == "full":
            metadata = dict(item["metadata"] or {})
            item["metadata"] = metadata
            item["lexicon"] = metadata if metadata.get("schema_version") == "lexicon-pack/1" else None
        items.append(item)
    return ScopedAssetPage(
        items=tuple(items),
        offset=offset,
        limit=limit,
        total=total,
    )


def get_scoped_asset_view(
    session: Session,
    asset_id: UUID,
    *,
    novel_id: UUID | None = None,
) -> dict[str, object]:
    asset = session.get(PrivateAsset, asset_id)
    if asset is None:
        raise PrivateLibraryNotFoundError("private asset not found")
    require_asset_scope(asset, novel_id=novel_id)
    return _asset_view(session, asset, novel_id=novel_id)


def lexicon_pack_from_version(version: PrivateAssetVersion) -> LexiconPack:
    metadata = version.metadata_json
    if not isinstance(metadata, dict) or metadata.get("schema_version") != "lexicon-pack/1":
        raise PrivateLibraryValidationError("asset version is not a structured lexicon pack")
    pack = LexiconPack.model_validate(metadata)
    validate_lexicon_pack_budget(pack)
    return pack


def validate_lexicon_pack_budget(pack: LexiconPack) -> None:
    """Enforce the frozen canonical UTF-8 metadata budget at every boundary."""

    size = len(canonical_json(pack.model_dump(mode="json")).encode("utf-8"))
    if size > MAX_LEXICON_METADATA_BYTES:
        raise PrivateLibraryValidationError(
            f"lexicon metadata exceeds {MAX_LEXICON_METADATA_BYTES} bytes"
        )


def _collection_asset_id(scope_kind: str, novel_id: UUID | None, key: str) -> UUID:
    scope = "library" if scope_kind == "library" else f"novel:{novel_id}"
    return uuid5(COLLECTION_NAMESPACE, f"{scope}:{key}")


def get_or_create_collection_pack(
    session: Session,
    *,
    novel_id: UUID | None,
    operation_key: str,
) -> tuple[PrivateAsset, PrivateAssetVersion, bool]:
    """Resolve one stable default collection without pre-populating empty packs."""

    scope_kind = "novel" if novel_id is not None else "library"
    collection_key = NOVEL_COLLECTION_KEY if novel_id is not None else LIBRARY_COLLECTION_KEY
    if novel_id is not None:
        lock_active_novel(session, novel_id)
    existing = session.scalar(
        select(PrivateAsset).where(
            PrivateAsset.scope_kind == scope_kind,
            PrivateAsset.scope_novel_id.is_(None)
            if novel_id is None
            else PrivateAsset.scope_novel_id == novel_id,
            PrivateAsset.collection_key == collection_key,
        ).with_for_update()
    )
    if existing is not None:
        if existing.current_version_id is None:
            raise PrivateLibraryConflictError(
                "collection_current_version_missing",
                current={"asset_id": str(existing.id)},
            )
        version = session.get(PrivateAssetVersion, existing.current_version_id)
        if version is None or version.asset_id != existing.id:
            raise PrivateLibraryConflictError(
                "collection_current_version_invalid",
                current={"asset_id": str(existing.id)},
            )
        return existing, version, False

    empty_pack = LexiconPack()
    stable_id = _collection_asset_id(scope_kind, novel_id, collection_key)
    result = create_asset(
        session,
        asset_id=stable_id,
        asset_type="vocabulary",
        title=COLLECTION_TITLES[collection_key],
        content="暂无词项",
        metadata=empty_pack.model_dump(mode="json"),
        operation_key=operation_key,
        tags=["待整理"],
        source={"kind": "author_collection"},
        rights={"usage": "private_author_material"},
    )
    result.asset.scope_kind = scope_kind
    result.asset.scope_novel_id = novel_id
    result.asset.collection_key = collection_key
    session.flush()
    return result.asset, result.asset_version, not result.replayed


def merge_lexicon_entries(
    pack: LexiconPack,
    entries: Iterable[LexiconEntry],
) -> LexiconPack:
    """Apply exact entry-id replacements while preserving unrelated entries."""

    replacement: dict[str, LexiconEntry] = {}
    for entry in entries:
        if entry.entry_id in replacement:
            raise PrivateLibraryValidationError("entry update contains duplicate ids")
        replacement[entry.entry_id] = entry
    existing_ids = {entry.entry_id for entry in pack.entries}
    merged = [replacement.pop(entry.entry_id, entry) for entry in pack.entries]
    merged.extend(replacement[key] for key in sorted(replacement))
    del existing_ids
    return LexiconPack(entries=merged)


def remove_lexicon_entries(pack: LexiconPack, entry_ids: Sequence[str]) -> LexiconPack:
    requested = set(entry_ids)
    if not requested or len(requested) != len(entry_ids):
        raise PrivateLibraryValidationError("entry ids must be non-empty and unique")
    existing = {entry.entry_id for entry in pack.entries}
    missing = requested - existing
    if missing:
        raise PrivateLibraryNotFoundError("one or more lexicon entries were not found")
    return LexiconPack(entries=[
        entry for entry in pack.entries if entry.entry_id not in requested
    ])


def save_lexicon_pack(
    session: Session,
    *,
    asset_id: UUID,
    expected_root_version: int,
    pack: LexiconPack,
    operation_key: str,
    novel_id: UUID | None,
) -> tuple[PrivateAsset, PrivateAssetVersion, bool]:
    validate_lexicon_pack_budget(pack)
    asset = session.get(PrivateAsset, asset_id)
    if asset is None or asset.asset_type != "vocabulary":
        raise PrivateLibraryNotFoundError("vocabulary asset not found")
    require_asset_scope(asset, novel_id=novel_id)
    from .lexicon_renderer import render_lexicon_pack

    rendered = render_lexicon_pack(pack)
    result = update_asset(
        session,
        asset_id,
        expected_root_version=expected_root_version,
        operation_key=operation_key,
        title=asset.title,
        content=rendered.content,
        tags=asset.tags_json,
        metadata=pack.model_dump(mode="json"),
    )
    return result.asset, result.asset_version, result.replayed


def create_novel_lexicon_copy(
    session: Session,
    *,
    novel_id: UUID,
    source_asset_id: UUID,
    source_version_id: UUID,
    operation_key: str,
) -> tuple[PrivateAsset, PrivateAssetVersion, bool]:
    lock_active_novel(session, novel_id)
    source_asset = session.get(PrivateAsset, source_asset_id)
    source_version = session.get(PrivateAssetVersion, source_version_id)
    if (
        source_asset is None
        or source_asset.asset_type != "vocabulary"
        or source_version is None
        or source_version.asset_id != source_asset_id
    ):
        raise PrivateLibraryNotFoundError("source lexicon version not found")
    require_asset_scope(source_asset, novel_id=novel_id)
    existing = session.scalar(
        select(PrivateAsset).where(
            PrivateAsset.scope_kind == "novel",
            PrivateAsset.scope_novel_id == novel_id,
            PrivateAsset.source_asset_id == source_asset_id,
        ).with_for_update()
    )
    if existing is not None:
        if existing.current_version_id is None:
            raise PrivateLibraryConflictError(
                "novel_copy_current_version_missing",
                current={"asset_id": str(existing.id)},
            )
        current = session.get(PrivateAssetVersion, existing.current_version_id)
        if current is None:
            raise PrivateLibraryConflictError(
                "novel_copy_current_version_invalid",
                current={"asset_id": str(existing.id)},
            )
        return existing, current, False

    pack = lexicon_pack_from_version(source_version)
    from .lexicon_renderer import render_lexicon_pack

    rendered = render_lexicon_pack(pack)
    stable_id = uuid5(COLLECTION_NAMESPACE, f"novel-copy:{novel_id}:{source_asset_id}")
    result = create_asset(
        session,
        asset_id=stable_id,
        asset_type="vocabulary",
        title=f"{source_version.title}（本书）",
        content=rendered.content,
        metadata=pack.model_dump(mode="json"),
        operation_key=operation_key,
        tags=source_asset.tags_json,
        source={
            "kind": "novel_copy",
            "source_asset_id": str(source_asset_id),
            "source_version_id": str(source_version_id),
        },
        rights=source_version.rights_json,
    )
    result.asset.scope_kind = "novel"
    result.asset.scope_novel_id = novel_id
    result.asset.source_asset_id = source_asset_id
    result.asset.source_version_id = source_version_id
    session.flush()
    return result.asset, result.asset_version, not result.replayed


def resolve_effective_lexicon_policy(
    session: Session,
    novel_id: UUID,
    *,
    lock: bool = True,
) -> EffectiveLexiconPolicy:
    """Resolve fixed binding versions with deterministic conflict precedence."""

    if lock:
        lock_active_novel(session, novel_id)
    else:
        require_active_novel(session, novel_id)
    rows = session.scalars(
        select(NovelAssetBinding).where(
            NovelAssetBinding.novel_id == novel_id,
            NovelAssetBinding.lifecycle_state == "active",
            NovelAssetBinding.usage_policy != "prohibited",
        ).order_by(NovelAssetBinding.position, NovelAssetBinding.id)
    ).all()
    candidates: list[EffectiveLexiconRule] = []
    for row in rows:
        asset = session.get(PrivateAsset, row.asset_id)
        version = session.get(PrivateAssetVersion, row.asset_version_id)
        if asset is None or version is None or asset.asset_type != "vocabulary":
            continue
        require_asset_scope(asset, novel_id=novel_id)
        for entry in lexicon_pack_from_version(version).entries:
            if entry.state.value == "active":
                candidates.append(EffectiveLexiconRule(
                    asset_id=asset.id,
                    asset_version_id=version.id,
                    entry=entry,
                    position=int(row.position),
                ))
    if len(candidates) > MAX_EFFECTIVE_RULES:
        raise PrivateLibraryValidationError(
            "effective lexicon exceeds the complete-rule budget"
        )

    precedence = {
        LexiconAction.RECOMMEND: 0,
        LexiconAction.WATCH: 1,
        LexiconAction.FORBID: 2,
    }
    # Resolve at the actual candidate-string level.  A losing variant must not
    # discard unrelated terms from the same entry, and two case-sensitive
    # spellings remain independent unless an insensitive rule bridges them.
    buckets: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for index, rule in enumerate(candidates):
        seen: set[str] = set()
        for candidate in (rule.entry.term, *rule.entry.variants):
            if candidate in seen:
                continue
            seen.add(candidate)
            buckets.setdefault(
                (rule.entry.match_mode.value, candidate.casefold()), []
            ).append((index, candidate))
    won: dict[int, list[str]] = {index: [] for index in range(len(candidates))}
    conflicts: list[dict[str, object]] = []
    for (match_mode, folded), records in sorted(buckets.items()):
        groups: list[list[tuple[int, str]]]
        if any(not candidates[index].entry.case_sensitive for index, _ in records):
            groups = [records]
        else:
            exact: dict[str, list[tuple[int, str]]] = {}
            for record in records:
                exact.setdefault(record[1], []).append(record)
            groups = [exact[key] for key in sorted(exact)]
        for records_group in groups:
            unique_indexes = sorted({index for index, _ in records_group})
            ordered_indexes = sorted(
                unique_indexes,
                key=lambda index: (
                    -precedence[candidates[index].entry.action],
                    candidates[index].position,
                    str(candidates[index].asset_id),
                    candidates[index].entry.entry_id,
                ),
            )
            winner_index = ordered_indexes[0]
            winner_candidates = [
                value for index, value in records_group if index == winner_index
            ]
            for value in winner_candidates:
                if value not in won[winner_index]:
                    won[winner_index].append(value)
            actions = sorted({
                candidates[index].entry.action.value for index in unique_indexes
            })
            if len(actions) > 1:
                winner = candidates[winner_index]
                conflicts.append({
                    "term": records_group[0][1] if len(groups) > 1 else folded,
                    "match_mode": match_mode,
                    "actions": actions,
                    "winner": winner.entry.action.value,
                    "sources": [
                        {
                            "asset_id": str(candidates[index].asset_id),
                            "asset_version_id": str(candidates[index].asset_version_id),
                            "entry_id": candidates[index].entry.entry_id,
                        }
                        for index in ordered_indexes
                    ],
                })
    resolved: list[EffectiveLexiconRule] = []
    for index, rule in enumerate(candidates):
        retained = won[index]
        if not retained:
            continue
        entry = rule.entry.model_copy(update={
            "term": retained[0],
            "variants": retained[1:],
        })
        resolved.append(EffectiveLexiconRule(
            asset_id=rule.asset_id,
            asset_version_id=rule.asset_version_id,
            entry=entry,
            position=rule.position,
        ))
    resolved.sort(key=lambda item: (
        -precedence[item.entry.action],
        item.position,
        str(item.asset_id),
        item.entry.entry_id,
    ))
    payload = [
        {
            "asset_id": item.asset_id,
            "asset_version_id": item.asset_version_id,
            "entry": item.entry.model_dump(mode="json"),
        }
        for item in resolved
    ]
    return EffectiveLexiconPolicy(
        novel_id=novel_id,
        rules=tuple(resolved),
        conflicts=tuple(conflicts),
        rules_hash=canonical_hash(payload),
    )


__all__ = [
    "EffectiveLexiconPolicy",
    "EffectiveLexiconRule",
    "ScopedAssetPage",
    "get_or_create_collection_pack",
    "create_novel_lexicon_copy",
    "effective_policy_from_snapshot",
    "effective_policy_snapshot",
    "lexicon_pack_from_version",
    "list_scoped_assets",
    "merge_lexicon_entries",
    "remove_lexicon_entries",
    "require_asset_scope",
    "get_scoped_asset_view",
    "resolve_effective_lexicon_policy",
    "save_lexicon_pack",
    "validate_lexicon_pack_budget",
]
