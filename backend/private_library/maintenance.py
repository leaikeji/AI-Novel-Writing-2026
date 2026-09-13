"""Durable, scope-bound Plan 74 private-library maintenance decisions.

This module never commits.  The HTTP/tool integration owns the transaction;
the durable request row is the idempotency, receipt, and undo authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import LibraryChangeRequest, PrivateAssetVersion
from ..models import PrivateAsset
from ..novel_lifecycle import lock_active_novel
from .access_context import LibraryAccessEvidence
from .contracts import UsagePolicy, VersionSelection
from .errors import (
    PrivateLibraryConflictError,
    PrivateLibraryIdempotencyConflict,
    PrivateLibraryNotFoundError,
    PrivateLibraryValidationError,
)
from .hashing import canonical_hash, canonical_json
from .lexicon_contracts import LexiconEntry
from .lexicon_service import (
    ScopedAssetPage,
    create_novel_lexicon_copy,
    get_scoped_asset_view,
    get_or_create_collection_pack,
    lexicon_pack_from_version,
    list_scoped_assets,
    merge_lexicon_entries,
    remove_lexicon_entries,
    require_asset_scope,
    save_lexicon_pack,
)
from .maintenance_contracts import (
    MAX_CHANGE_REQUEST_BYTES,
    LibraryCaptureSource,
    LibraryChangeAction,
    LibraryChangeOperation,
    LibraryChangeProposal,
    LibraryScope,
    LibraryScopeKind,
)
from .service import (
    create_asset,
    get_asset,
    list_novel_bindings,
    replace_novel_bindings,
    restore_asset,
    update_asset,
)


MAX_QUERY_LIMIT = 100
MAX_CHANGE_QUERY_LIMIT = 50
PROTECTED_AUTHORITY_FIELDS = frozenset({
    "authorized",
    "write_authorized",
    "session_id",
    "request_id",
    "author_text_hash",
    "author_text_sha256",
    "scope_kind",
    "scope_novel_id",
    "novel_id",
})


class AuthorMaintenanceIntent(str, Enum):
    DIRECT = "direct"
    CONSULTATION = "consultation"
    AMBIGUOUS = "ambiguous"
    ACCEPT_PROPOSAL = "accept_proposal"
    UNDO = "undo"


class UnsupportedLibraryChange(PrivateLibraryValidationError):
    pass


@dataclass(frozen=True, slots=True)
class AppliedAction:
    operation: str
    changed: bool
    target: dict[str, Any]
    undo_action: LibraryChangeAction | None
    undo_actions: tuple[LibraryChangeAction, ...] = ()


class ChangeRequestStore(Protocol):
    def get(self, proposal_id: UUID, *, for_update: bool = False) -> Any | None: ...

    def by_request_id(self, request_id: UUID) -> Any | None: ...

    def by_idempotency_key(self, idempotency_key: str) -> Any | None: ...

    def find_undo(self, original_id: UUID) -> Any | None: ...

    def add(self, row: Any) -> None: ...

    def flush(self) -> None: ...

    def action_savepoint(self) -> AbstractContextManager[Any]: ...

    def list_assets(
        self,
        scope: LibraryScope,
        *,
        asset_type: str | None,
        include_archived: bool,
        search: str | None,
        limit: int,
        offset: int,
        scope_filter: str,
        enabled_filter: str,
        projection: str,
    ) -> ScopedAssetPage: ...

    def list_changes(
        self,
        scope: LibraryScope,
        *,
        session_id: str,
        limit: int,
    ) -> Sequence[Any]: ...

    def get_asset_details(
        self,
        scope: LibraryScope,
        *,
        asset_id: UUID,
        include_archived: bool,
    ) -> Mapping[str, Any] | None: ...

    def list_binding_details(
        self,
        scope: LibraryScope,
    ) -> Sequence[Mapping[str, Any]]: ...


class SqlAlchemyChangeRequestStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, proposal_id: UUID, *, for_update: bool = False
    ) -> LibraryChangeRequest | None:
        statement = select(LibraryChangeRequest).where(
            LibraryChangeRequest.id == proposal_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def by_request_id(self, request_id: UUID) -> LibraryChangeRequest | None:
        return self.session.scalar(
            select(LibraryChangeRequest).where(
                LibraryChangeRequest.request_id == request_id
            )
        )

    def by_idempotency_key(
        self, idempotency_key: str
    ) -> LibraryChangeRequest | None:
        return self.session.scalar(
            select(LibraryChangeRequest).where(
                LibraryChangeRequest.idempotency_key == idempotency_key
            )
        )

    def find_undo(self, original_id: UUID) -> LibraryChangeRequest | None:
        return self.session.scalar(
            select(LibraryChangeRequest)
            .where(LibraryChangeRequest.undo_of_id == original_id)
            .order_by(LibraryChangeRequest.created_at.desc())
            .limit(1)
        )

    def add(self, row: LibraryChangeRequest) -> None:
        self.session.add(row)

    def flush(self) -> None:
        self.session.flush()

    def action_savepoint(self) -> AbstractContextManager[Any]:
        return self.session.begin_nested()

    def list_assets(
        self,
        scope: LibraryScope,
        *,
        asset_type: str | None,
        include_archived: bool,
        search: str | None,
        limit: int,
        offset: int = 0,
        scope_filter: str = "all",
        enabled_filter: str = "all",
        projection: str = "summary",
    ) -> ScopedAssetPage:
        return list_scoped_assets(
            self.session,
            novel_id=scope.novel_id,
            asset_type=asset_type,
            query=search or "",
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            scope_filter=scope_filter,
            enabled_filter=enabled_filter,
            projection=projection,
        )

    def get_asset_details(
        self,
        scope: LibraryScope,
        *,
        asset_id: UUID,
        include_archived: bool,
    ) -> Mapping[str, Any] | None:
        asset = self.session.get(PrivateAsset, asset_id)
        if asset is None or (asset.archived and not include_archived):
            return None
        result = _query_asset_view(get_scoped_asset_view(
            self.session, asset_id, novel_id=scope.novel_id,
        ))
        result["bound_version"] = None
        if scope.novel_id is not None:
            bound = next((view for view in list_novel_bindings(
                self.session, scope.novel_id
            ) if view.asset.id == asset_id), None)
            if bound is not None:
                result["bound_version"] = {
                    "asset_version_id": str(bound.asset_version.id),
                    "binding_version": int(bound.binding.version),
                    "usage_policy": str(bound.binding.usage_policy),
                    "position": int(bound.binding.position),
                    "lexicon_pack": (
                        lexicon_pack_from_version(bound.asset_version).model_dump(mode="json")
                        if asset.asset_type == "vocabulary" else None
                    ),
                }
        return result

    def list_binding_details(
        self,
        scope: LibraryScope,
    ) -> Sequence[Mapping[str, Any]]:
        if scope.kind is not LibraryScopeKind.NOVEL or scope.novel_id is None:
            raise PrivateLibraryValidationError(
                "trusted novel scope is required for binding queries"
            )
        return tuple({
            "asset_id": str(view.asset.id),
            "asset_title": str(view.asset_version.title),
            "asset_version_id": str(view.asset_version.id),
            "usage_policy": str(view.binding.usage_policy),
            "position": int(view.binding.position),
            "binding_version": int(view.binding.version),
            "asset_scope": str(view.asset.scope_kind),
            "update_available": bool(view.update_available),
        } for view in list_novel_bindings(self.session, scope.novel_id))

    def list_changes(
        self,
        scope: LibraryScope,
        *,
        session_id: str,
        limit: int,
    ) -> Sequence[LibraryChangeRequest]:
        statement = select(LibraryChangeRequest).where(
            LibraryChangeRequest.scope_kind == scope.kind.value,
            LibraryChangeRequest.scope_novel_id.is_(None)
            if scope.novel_id is None
            else LibraryChangeRequest.scope_novel_id == scope.novel_id,
            LibraryChangeRequest.session_id == session_id,
        )
        return tuple(
            self.session.scalars(
                statement.order_by(
                    LibraryChangeRequest.created_at.desc(),
                    LibraryChangeRequest.id.desc(),
                ).limit(limit)
            ).all()
        )


def scope_from_access(access: LibraryAccessEvidence) -> LibraryScope:
    if access.scope_kind == "library":
        if access.novel_id is not None:
            raise PrivateLibraryValidationError("library access carried a novel id")
        return LibraryScope(kind=LibraryScopeKind.LIBRARY)
    if access.scope_kind != "novel" or access.novel_id is None:
        raise PrivateLibraryValidationError("maintenance scope is unavailable")
    try:
        novel_id = UUID(str(access.novel_id))
    except (TypeError, ValueError) as error:
        raise PrivateLibraryValidationError("maintenance novel scope is invalid") from error
    return LibraryScope(kind=LibraryScopeKind.NOVEL, novel_id=novel_id)


def _strip_quoted_material(text: str) -> str:
    without_fences = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    return re.sub(r"[‘’“”'\"].*?[‘’“”'\"]", "目标", without_fences)


def _strip_safe_scope_constraints(text: str) -> str:
    """Remove only complete trailing clauses that narrow an earlier write."""

    explicit_write = re.search(
        r"(?:^|[，。；：,:;])(?:请)?(?:把|将).+"
        r"(?:设为|改(?:成|为)|归档|恢复|停用|启用|分类|合并|收藏)"
        r"|(?:^|[，。；：,:;])(?:请)?(?:仅)?(?:修改|更改).+(?:为|成).+"
        r"|(?:^|[，。；：,:;])(?:新增|添加|加上|收藏|归档|恢复|停用|启用|更新).+",
        text,
    )
    if explicit_write is None:
        return text
    scope_target = r"(?:通用源包|其他(?:包|词包|词项|词条|资料)|其余(?:包|词包|词项|词条|资料))"
    protected_prefix = text[: explicit_write.start()]
    write_and_constraints = text[explicit_write.start() :]
    return protected_prefix + re.sub(
        rf"(^|[，。；,;])\s*(?:请)?(?:不要|无需|不必)(?:再)?\s*"
        rf"(?:修改|更改|更新|改动|改|动)\s*{scope_target}"
        rf"(?:[\s、和及或与]+{scope_target})*\s*(?=$|[，。；,;])",
        r"\1",
        write_and_constraints,
    )


def classify_author_intent(text: str) -> AuthorMaintenanceIntent:
    """Conservative intent gate over the trusted current author message only."""

    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return AuthorMaintenanceIntent.AMBIGUOUS
    if re.search(
        r"(?:^|[\s，。；,;])(?:引用(?:材料|原文|内容)?)\s*[：:‘“'\"]"
        r"|(?:^|[\s，。；,;])(?:原文|材料|例句|示例|文档|资料)"
        r"(?:中|里)?(?:写着|提到|内容是|[：:])"
        r"|(?:^|[\s，。；,;])(?:例如|比如|譬如)\s*[：:‘“'\"]?"
        r"|(?:他说|她说|对方说|有人说)\s*[：:,，]?[\s‘’“”'\"]",
        normalized,
    ):
        return AuthorMaintenanceIntent.CONSULTATION
    command_text = _strip_quoted_material(normalized)
    if (
        "？" in command_text
        or "?" in command_text
        or re.search(
            r"(?:应不应该|要不要|能不能|是否(?:应该|适合|可以|需要|要|接受|撤销|执行|应用|采纳)|建议怎么|怎么看|合不合适)",
            command_text,
        )
    ):
        return AuthorMaintenanceIntent.CONSULTATION
    if re.match(
        r"^(?:请)?(?:分析|阅读|看看|检查|评估|讨论|解释)(?:以下|这段|这个)?(?:材料|内容|资料|例句)",
        command_text,
    ):
        return AuthorMaintenanceIntent.CONSULTATION
    mutation_words = r"(?:把|将|修改|更改|新增|添加|收藏|归档|恢复|撤销|取消|停用|启用|更新|执行|接受|应用|采纳)"
    authorization_text = _strip_safe_scope_constraints(command_text)
    non_authorizing_patterns = (
        # A negated mutation is an instruction not to write, not a direct write.
        rf"(?:不要|请勿|勿|别|不必|无需|暂不|先不|不能|不可|禁止)\s*(?:再|去)?\s*{mutation_words}",
        rf"(?:没有|未)(?:要求|让|叫).{{0,20}}{mutation_words}",
        # Hypothetical and advisory clauses remain discussion even when they
        # contain an otherwise imperative-looking example.
        rf"(?:^|[\s，。；：,:;])(?:如果|假如|假设|倘若|若是|要是).{{0,200}}{mutation_words}",
        rf"(?:^|[\s，。；：,:;])(?:我)?(?:建议|提议|推荐|最好|不妨|可以考虑).{{0,80}}{mutation_words}",
        # Commands quoted as source material never grant maintenance authority.
        rf"(?:引用材料|原文|材料|例句|示例|文档|资料)(?:中|里)?(?:写着|提到|内容是|[：:]).{{0,200}}{mutation_words}",
        rf"(?:他说|她说|对方说|有人说).{{0,200}}{mutation_words}",
    )
    if any(re.search(pattern, authorization_text) for pattern in non_authorizing_patterns):
        return AuthorMaintenanceIntent.CONSULTATION
    if re.search(r"(?:撤销|取消|恢复)(?:刚才|上次|这个|该)?(?:的)?(?:修改|变更|操作|提案)", authorization_text):
        return AuthorMaintenanceIntent.UNDO
    # A receipt is also an explicit undo target. Only accept an imperative at
    # the start of the trusted message, after all non-authorizing checks above.
    # The actual receipt, scope and version are still checked by the undo path.
    if re.match(
        r"^(?:请)?(?:直接)?撤销(?:刚才|上次|这个|该)?(?:已应用)?(?:的)?回执\s*"
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        r"(?=$|[\s（(，。；,;])",
        authorization_text,
    ):
        return AuthorMaintenanceIntent.UNDO
    if re.search(
        r"(?:执行|接受|应用|采纳)(?:刚才|上次|这个|该|前面)?(?:的)?(?:方案|提案|建议|变更)",
        authorization_text,
    ):
        return AuthorMaintenanceIntent.ACCEPT_PROPOSAL
    direct_patterns = (
        r"(?:^|[，。；：,:;])(?:请)?(?:把|将).+(?:设为|改(?:成|为)|归档|恢复|停用|启用|分类|合并|收藏)",
        r"(?:^|[，。；：,:;])(?:请)?(?:仅)?(?:修改|更改).+(?:为|成).+",
        r"(?:新增|添加|加上|收藏|归档|恢复|停用|启用|更新).+",
        r".+(?:只收藏|保存并用于本书|用于本书)",
        r"(?:这几个词|这些词|指定词项).+(?:分类|整理)",
    )
    if any(re.search(pattern, authorization_text) for pattern in direct_patterns):
        return AuthorMaintenanceIntent.DIRECT
    return AuthorMaintenanceIntent.AMBIGUOUS


def _contains_protected_authority(value: Any) -> bool:
    if isinstance(value, Mapping):
        if PROTECTED_AUTHORITY_FIELDS.intersection(value):
            return True
        return any(_contains_protected_authority(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_protected_authority(item) for item in value)
    return False


def _validate_actions(
    actions: Sequence[LibraryChangeAction], scope: LibraryScope
) -> tuple[LibraryChangeAction, ...]:
    if not actions:
        raise PrivateLibraryValidationError("at least one maintenance action is required")
    result = tuple(actions)
    if len(result) != 1 and any(
        action.operation is LibraryChangeOperation.UPSERT_AND_USE_LEXICON_ENTRIES
        for action in result
    ):
        raise PrivateLibraryValidationError("atomic save-and-use must be the only proposal action")
    for action in result:
        if _contains_protected_authority(action.payload):
            raise PrivateLibraryValidationError(
                "action payload cannot provide authorization or trusted scope"
            )
        if (
            action.operation
            in {
                LibraryChangeOperation.SET_NOVEL_BINDING,
                LibraryChangeOperation.CREATE_NOVEL_COPY,
                LibraryChangeOperation.UPSERT_AND_USE_LEXICON_ENTRIES,
            }
            and scope.kind is not LibraryScopeKind.NOVEL
        ):
            raise PrivateLibraryValidationError(
                "this action requires a trusted current novel"
            )
    return result


def _request_matches_access(row: Any, access: LibraryAccessEvidence) -> bool:
    scope = scope_from_access(access)
    return (
        row.session_id == access.session_id
        and row.scope_kind == scope.kind.value
        and row.scope_novel_id == scope.novel_id
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _receipt(row: Any, *, replayed: bool = False) -> dict[str, Any]:
    result = dict(row.result_json or {})
    return {
        "proposal_id": str(row.id),
        "request_id": str(row.request_id),
        "state": row.state,
        "version": int(row.version),
        "scope": {
            "kind": row.scope_kind,
            "novel_id": str(row.scope_novel_id) if row.scope_novel_id else None,
        },
        "requires_review": bool(
            (row.source_json or {}).get("_maintenance", {}).get("requires_review")
        ),
        "counts": result.get(
            "counts", {"changed": 0, "unchanged": 0, "unsupported": 0}
        ),
        "error": result.get("error"),
        "targets": result.get("targets", []),
        "operations": result.get("operations", []),
        "undo_available": bool(
            row.state == "applied" and result.get("undo_actions")
        ),
        "applied_at": _iso(row.applied_at),
        "replayed": replayed,
    }


def _query_asset_view(asset: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve the tool's legacy scope field without duplicating domain queries."""
    result = dict(asset)
    result["scope"] = {
        "kind": asset["scope_kind"], "novel_id": asset.get("scope_novel_id"),
    }
    for key in ("created_at", "updated_at"):
        if isinstance(result.get(key), datetime):
            result[key] = _iso(result[key])
    return result


def query_library(
    store: ChangeRequestStore,
    access: LibraryAccessEvidence,
    query: Mapping[str, Any],
) -> dict[str, Any]:
    """Bounded, side-effect-free library and receipt lookup."""

    scope = scope_from_access(access)
    if PROTECTED_AUTHORITY_FIELDS.intersection(query) or "scope" in query:
        raise PrivateLibraryValidationError("query cannot provide trusted scope or authority")
    kind = str(query.get("kind", "assets"))
    if kind == "change":
        try:
            proposal_id = UUID(str(query["proposal_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise PrivateLibraryValidationError("proposal_id is required") from error
        row = store.get(proposal_id)
        if row is None or not _request_matches_access(row, access):
            raise PrivateLibraryNotFoundError("maintenance proposal not found")
        return {"kind": kind, "change": _receipt(row)}
    if kind == "recent_changes":
        limit = _bounded_limit(query.get("limit", 20), MAX_CHANGE_QUERY_LIMIT)
        rows = store.list_changes(scope, session_id=access.session_id, limit=limit)
        return {
            "kind": kind,
            "items": [_receipt(row) for row in rows],
            "limit": limit,
        }
    if kind == "bindings":
        if scope.kind is not LibraryScopeKind.NOVEL:
            raise PrivateLibraryValidationError(
                "trusted novel scope is required for binding queries"
            )
        return {
            "kind": kind,
            "items": [dict(item) for item in store.list_binding_details(scope)],
            "scope": scope.model_dump(mode="json"),
        }
    include_archived = query.get("include_archived", False)
    if not isinstance(include_archived, bool):
        raise PrivateLibraryValidationError("include_archived must be a boolean")
    if kind == "asset":
        try:
            asset_id = UUID(str(query["asset_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise PrivateLibraryValidationError("asset_id is required") from error
        asset = store.get_asset_details(
            scope,
            asset_id=asset_id,
            include_archived=include_archived,
        )
        if asset is None:
            raise PrivateLibraryNotFoundError("private asset not found")
        return {"kind": kind, "asset": dict(asset)}
    if kind != "assets":
        raise PrivateLibraryValidationError("query kind is not supported")
    limit = _bounded_limit(query.get("limit", 50), MAX_QUERY_LIMIT)
    asset_type = query.get("asset_type")
    if asset_type is not None and (not isinstance(asset_type, str) or asset_type not in {
        "plot", "writing_style", "vocabulary", "idea"
    }):
        raise PrivateLibraryValidationError("asset_type is not supported")
    search = query.get("search")
    if search is not None:
        search = str(search).strip()
        if not search or len(search) > 200:
            raise PrivateLibraryValidationError("search must contain 1 to 200 characters")
    offset = query.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PrivateLibraryValidationError("offset must be a non-negative integer")
    scope_filter = query.get("scope_filter", "all")
    enabled_filter = query.get("enabled_filter", "all")
    projection = query.get("projection", "summary")
    if not isinstance(scope_filter, str) or scope_filter not in {"all", "library", "novel"}:
        raise PrivateLibraryValidationError("scope_filter is not supported")
    if not isinstance(enabled_filter, str) or enabled_filter not in {"all", "enabled", "disabled"}:
        raise PrivateLibraryValidationError("enabled_filter is not supported")
    if not isinstance(projection, str) or projection not in {"summary", "full"}:
        raise PrivateLibraryValidationError("projection is not supported")
    if scope.novel_id is None and (scope_filter == "novel" or enabled_filter != "all"):
        raise PrivateLibraryValidationError("trusted novel scope is required for these filters")
    page = store.list_assets(
        scope,
        asset_type=asset_type,
        include_archived=include_archived,
        search=search,
        limit=limit,
        offset=offset,
        scope_filter=scope_filter,
        enabled_filter=enabled_filter,
        projection=projection,
    )
    return {
        "kind": kind,
        "items": [_query_asset_view(asset) for asset in page.items],
        "limit": page.limit,
        "offset": page.offset,
        "total": page.total,
        "has_more": page.has_more,
        "next_offset": page.next_offset,
        "scope": scope.model_dump(mode="json"),
    }


def _bounded_limit(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PrivateLibraryValidationError("limit must be an integer")
    limit = value
    if not 1 <= limit <= maximum:
        raise PrivateLibraryValidationError(f"limit must be between 1 and {maximum}")
    return limit


def prepare_library_change(
    store: ChangeRequestStore,
    access: LibraryAccessEvidence,
    *,
    actions: Sequence[LibraryChangeAction],
    intent: AuthorMaintenanceIntent,
    idempotency_key: str | None = None,
    source: LibraryCaptureSource | None = None,
) -> dict[str, Any]:
    """Persist an exact proposal; intent comes from trusted author text."""

    if intent in {
        AuthorMaintenanceIntent.CONSULTATION,
        AuthorMaintenanceIntent.ACCEPT_PROPOSAL,
        AuthorMaintenanceIntent.UNDO,
    }:
        raise PrivateLibraryValidationError(
            "this author intent cannot create a new maintenance proposal"
        )
    scope = scope_from_access(access)
    validated_actions = _validate_actions(actions, scope)
    key = (idempotency_key or f"library-change:{access.request_id}").strip()
    if not 8 <= len(key) <= 160:
        raise PrivateLibraryValidationError(
            "idempotency_key must contain 8 to 160 characters"
        )
    requires_review = intent is AuthorMaintenanceIntent.AMBIGUOUS
    source_payload = source.model_dump(mode="json") if source else {}
    content_payload = {
        "scope": scope.model_dump(mode="json"),
        "source": source_payload,
        "actions": [action.model_dump(mode="json") for action in validated_actions],
        "requires_review": requires_review,
    }
    encoded = canonical_json(content_payload).encode("utf-8")
    if len(encoded) > MAX_CHANGE_REQUEST_BYTES:
        raise PrivateLibraryValidationError("maintenance proposal is too large")
    content_hash = canonical_hash(content_payload)
    proposal = LibraryChangeProposal(
        request_id=access.request_id,
        session_id=access.session_id,
        author_text_sha256=access.author_text_hash,
        scope=scope,
        source=source,
        actions=list(validated_actions),
        idempotency_key=key,
        content_sha256=content_hash,
        requires_review=requires_review,
    )
    by_request = store.by_request_id(access.request_id)
    by_key = store.by_idempotency_key(key)
    existing = by_request or by_key
    if existing is not None:
        if (
            (
                by_request is not None
                and by_key is not None
                and by_request.id != by_key.id
            )
            or existing.request_id != access.request_id
            or existing.idempotency_key != key
            or existing.content_hash != content_hash
            or existing.author_text_hash != access.author_text_hash
            or not _request_matches_access(existing, access)
        ):
            raise PrivateLibraryIdempotencyConflict(key)
        return {"proposal": _receipt(existing, replayed=True)}

    row = LibraryChangeRequest(
        id=uuid4(),
        request_id=proposal.request_id,
        scope_kind=scope.kind.value,
        scope_novel_id=scope.novel_id,
        session_id=proposal.session_id,
        author_text_hash=proposal.author_text_sha256,
        source_json={
            "capture": source_payload,
            "_maintenance": {
                "requires_review": requires_review,
                "intent": intent.value,
            },
        },
        actions_json=[action.model_dump(mode="json") for action in validated_actions],
        content_hash=proposal.content_sha256,
        idempotency_key=proposal.idempotency_key,
        state="proposed",
        version=1,
        result_json={},
        undo_of_id=None,
        applied_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    store.add(row)
    store.flush()
    return {"proposal": _receipt(row)}


class MaintenanceActionExecutor(Protocol):
    def apply(
        self,
        request: Any,
        action: LibraryChangeAction,
        *,
        action_index: int,
    ) -> AppliedAction: ...


class P1MaintenanceActionExecutor:
    """Narrow executor for Plan 74 P1; unsupported actions fail closed."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _scope(self, request: Any) -> LibraryScope:
        return LibraryScope(
            kind=LibraryScopeKind(request.scope_kind),
            novel_id=request.scope_novel_id,
        )

    def _key(self, request: Any, index: int, suffix: str) -> str:
        return f"l74:{request.id}:{index}:{suffix}"[:160]

    def _asset(self, request: Any, asset_id: UUID) -> tuple[Any, Any]:
        asset, version = get_asset(self.session, asset_id)
        scope = self._scope(request)
        require_asset_scope(asset, novel_id=scope.novel_id)
        return asset, version

    @staticmethod
    def _expected(action: LibraryChangeAction) -> int:
        if action.expected_root_version is None:
            raise PrivateLibraryValidationError("expected_root_version is required")
        return action.expected_root_version

    def apply(
        self,
        request: Any,
        action: LibraryChangeAction,
        *,
        action_index: int,
    ) -> AppliedAction:
        method = getattr(self, f"_apply_{action.operation.value}", None)
        if method is None:
            raise UnsupportedLibraryChange(
                f"unsupported maintenance operation: {action.operation.value}"
            )
        return method(request, action, action_index)

    def _apply_create_asset(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        payload = action.payload
        allowed = {
            "asset_type", "title", "content", "tags", "metadata", "source", "rights"
        }
        _require_payload_keys(payload, required={"asset_type", "title"}, allowed=allowed)
        result = create_asset(
            self.session,
            asset_id=action.asset_id,
            asset_type=str(payload["asset_type"]),
            title=str(payload["title"]),
            content=str(payload.get("content", "")),
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
            source=payload.get("source"),
            rights=payload.get("rights"),
            operation_key=self._key(request, index, "create"),
        )
        scope = self._scope(request)
        result.asset.scope_kind = scope.kind.value
        result.asset.scope_novel_id = scope.novel_id
        self.session.flush()
        undo = LibraryChangeAction(
            operation=LibraryChangeOperation.ARCHIVE_ASSET,
            asset_id=result.asset.id,
            expected_root_version=int(result.asset.version),
        )
        return AppliedAction(
            "create_asset",
            not result.replayed,
            _target(result.asset, result.asset_version),
            undo,
        )

    def _apply_update_asset(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        asset_id = _required_asset_id(action)
        before_asset, before_version = self._asset(request, asset_id)
        payload = action.payload
        allowed = {"title", "content", "tags", "metadata", "source", "rights"}
        _require_payload_keys(payload, required=set(), allowed=allowed)
        result = update_asset(
            self.session,
            asset_id,
            expected_root_version=self._expected(action),
            operation_key=self._key(request, index, "update"),
            title=str(payload.get("title", before_version.title)),
            content=str(payload.get("content", before_version.content)),
            tags=payload.get("tags"),
            metadata=payload.get("metadata"),
            source=payload.get("source"),
            rights=payload.get("rights"),
        )
        undo = _restore_version_action(result.asset, before_version.id)
        return AppliedAction(
            "update_asset", not result.replayed,
            _target(result.asset, result.asset_version), undo,
        )

    def _apply_archive_asset(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        del index
        asset_id = _required_asset_id(action)
        asset, _ = self._asset(request, asset_id)
        expected = self._expected(action)
        if int(asset.version) != expected:
            raise PrivateLibraryConflictError(
                "asset_root_version_conflict", current={
                    "asset_id": str(asset.id), "root_version": int(asset.version)
                }
            )
        changed = not bool(asset.archived)
        if changed:
            asset.archived = True
            asset.version = int(asset.version) + 1
            asset.updated_at = datetime.now(timezone.utc)
            self.session.flush()
        undo = (
            LibraryChangeAction(
                operation=LibraryChangeOperation.RESTORE_ASSET,
                asset_id=asset.id,
                expected_root_version=int(asset.version),
                payload={"unarchive": True},
            )
            if changed
            else None
        )
        return AppliedAction("archive_asset", changed, _target(asset, None), undo)

    def _apply_restore_asset(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        asset_id = _required_asset_id(action)
        asset, before_version = self._asset(request, asset_id)
        payload = action.payload
        _require_payload_keys(
            payload,
            required=set(),
            allowed={"target_version_id", "unarchive"},
        )
        if payload.get("unarchive") is True:
            expected = self._expected(action)
            if int(asset.version) != expected:
                raise PrivateLibraryConflictError(
                    "asset_root_version_conflict", current={
                        "asset_id": str(asset.id), "root_version": int(asset.version)
                    }
                )
            changed = bool(asset.archived)
            if changed:
                asset.archived = False
                asset.version = int(asset.version) + 1
                asset.updated_at = datetime.now(timezone.utc)
                self.session.flush()
            undo = (
                LibraryChangeAction(
                    operation=LibraryChangeOperation.ARCHIVE_ASSET,
                    asset_id=asset.id,
                    expected_root_version=int(asset.version),
                )
                if changed
                else None
            )
            return AppliedAction(
                "restore_asset", changed, _target(asset, before_version), undo
            )
        try:
            target_version_id = UUID(str(payload["target_version_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise PrivateLibraryValidationError(
                "target_version_id or unarchive=true is required"
            ) from error
        result = restore_asset(
            self.session,
            asset_id,
            target_version_id,
            expected_root_version=self._expected(action),
            operation_key=self._key(request, index, "restore"),
        )
        undo = _restore_version_action(result.asset, before_version.id)
        return AppliedAction(
            "restore_asset", not result.replayed,
            _target(result.asset, result.asset_version), undo,
        )

    def _apply_upsert_lexicon_entries(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        payload = action.payload
        _require_payload_keys(payload, required={"entries"}, allowed={"entries"})
        raw_entries = payload["entries"]
        if not isinstance(raw_entries, list):
            raise PrivateLibraryValidationError("entries must be a list")
        try:
            entries = tuple(LexiconEntry.model_validate(item) for item in raw_entries)
        except Exception as error:
            raise PrivateLibraryValidationError("lexicon entries are invalid") from error
        scope = self._scope(request)
        if action.asset_id is None:
            asset, before_version, _ = get_or_create_collection_pack(
                self.session,
                novel_id=scope.novel_id,
                operation_key=self._key(request, index, "collection"),
            )
            expected = int(asset.version)
        else:
            asset, before_version = self._asset(request, action.asset_id)
            expected = self._expected(action)
        merged = merge_lexicon_entries(
            lexicon_pack_from_version(before_version), entries
        )
        result_asset, result_version, replayed = save_lexicon_pack(
            self.session,
            asset_id=asset.id,
            expected_root_version=expected,
            pack=merged,
            operation_key=self._key(request, index, "upsert"),
            novel_id=scope.novel_id,
        )
        undo = _restore_version_action(result_asset, before_version.id)
        return AppliedAction(
            "upsert_lexicon_entries", not replayed,
            _target(result_asset, result_version), undo,
        )

    def _apply_upsert_and_use_lexicon_entries(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        scope = self._scope(request)
        if scope.novel_id is None:
            raise PrivateLibraryValidationError("trusted novel scope is required")
        payload = action.payload
        _require_payload_keys(
            payload, required={"entries", "expected_binding_versions"},
            allowed={"entries", "expected_binding_versions", "copy_to_novel"},
        )
        if not isinstance(payload["entries"], list) or not payload["entries"]:
            raise PrivateLibraryValidationError("entries must be a non-empty list")
        copy_to_novel = payload.get("copy_to_novel", False)
        if not isinstance(copy_to_novel, bool):
            raise PrivateLibraryValidationError("copy_to_novel must be a boolean")
        try:
            entries = tuple(LexiconEntry.model_validate(item) for item in payload["entries"])
        except Exception as error:
            raise PrivateLibraryValidationError("lexicon entries are invalid") from error
        expected = _binding_versions(payload["expected_binding_versions"])
        create_collection = all(value is None for value in (
            action.asset_id, action.asset_version_id, action.expected_root_version
        ))
        if create_collection:
            if copy_to_novel:
                raise PrivateLibraryValidationError("collection creation cannot copy a source")
        elif any(value is None for value in (
            action.asset_id, action.asset_version_id, action.expected_root_version
        )):
            raise PrivateLibraryValidationError("asset id, base version and root CAS are required together")

        # Membership and root changes share the same lock order and savepoint.
        lock_active_novel(self.session, scope.novel_id)
        before = list_novel_bindings(self.session, scope.novel_id)
        inverse_selections = _binding_selections(before)
        if expected != {view.asset.id: int(view.binding.version) for view in before}:
            raise PrivateLibraryConflictError("novel_asset_bindings_conflict", current={})
        asset_id = action.asset_id
        target_binding = next((view for view in before if view.asset.id == asset_id), None)
        if create_collection:
            asset, base, created = get_or_create_collection_pack(
                self.session, novel_id=scope.novel_id,
                operation_key=self._key(request, index, "atomic-collection"),
            )
            if not created:
                raise PrivateLibraryConflictError(
                    "collection_already_exists", current={"asset_id": str(asset.id)}
                )
        else:
            asset = self.session.scalar(
                select(PrivateAsset).where(PrivateAsset.id == asset_id)
                .with_for_update().execution_options(populate_existing=True)
            )
            if asset is None or asset.archived or asset.asset_type != "vocabulary":
                raise PrivateLibraryNotFoundError("active lexicon asset not found")
            require_asset_scope(asset, novel_id=scope.novel_id)
            if int(asset.version) != self._expected(action):
                raise PrivateLibraryConflictError(
                    "asset_root_version_conflict",
                    current={"asset_id": str(asset.id), "root_version": int(asset.version)},
                )
            required_base_id = (
                target_binding.asset_version.id if target_binding else asset.current_version_id
            )
            if action.asset_version_id != required_base_id:
                raise PrivateLibraryConflictError(
                    "lexicon_binding_base_conflict",
                    current={"asset_version_id": str(required_base_id)},
                )
            base = self.session.get(PrivateAssetVersion, action.asset_version_id)
            if base is None or base.asset_id != asset_id:
                raise PrivateLibraryNotFoundError("lexicon base version not found")
        old_root_id = asset.current_version_id
        is_copy = asset.scope_kind == "library"
        if is_copy != copy_to_novel:
            raise PrivateLibraryValidationError(
                "library sources require copy_to_novel=true; novel assets must be edited directly"
            )
        merged = merge_lexicon_entries(lexicon_pack_from_version(base), entries)
        if is_copy:
            asset, _, created = create_novel_lexicon_copy(
                self.session, novel_id=scope.novel_id,
                source_asset_id=asset_id, source_version_id=base.id,
                operation_key=self._key(request, index, "atomic-copy"),
            )
            if not created:
                raise PrivateLibraryConflictError(
                    "novel_copy_already_exists", current={"asset_id": str(asset.id)}
                )
        result_asset, result_version, replayed = save_lexicon_pack(
            self.session, asset_id=asset.id,
            expected_root_version=int(asset.version), pack=merged,
            operation_key=self._key(request, index, "atomic-upsert"),
            novel_id=scope.novel_id,
        )
        selections = [
            _selection(value) for value in inverse_selections
            if value["asset_id"] != str(asset_id)
        ]
        selections.append(VersionSelection(
            asset_id=result_asset.id, asset_version_id=result_version.id,
            usage_policy=(
                UsagePolicy(target_binding.binding.usage_policy)
                if target_binding and target_binding.binding.usage_policy != "prohibited"
                else UsagePolicy.PREFERRED
            ),
            position=(
                int(target_binding.binding.position) if target_binding else
                max((int(view.binding.position) for view in before), default=-1) + 1
            ),
        ))
        bindings = replace_novel_bindings(
            self.session, scope.novel_id, expected_binding_versions=expected,
            selections=selections, operation_key=self._key(request, index, "atomic-use"),
        )
        binding_undo = LibraryChangeAction(
            operation=LibraryChangeOperation.SET_NOVEL_BINDING,
            payload={
                "expected_binding_versions": {
                    str(view.asset.id): int(view.binding.version) for view in bindings.bindings
                },
                "selections": inverse_selections,
            },
        )
        asset_undo = (
            LibraryChangeAction(
                operation=LibraryChangeOperation.ARCHIVE_ASSET,
                asset_id=result_asset.id, expected_root_version=int(result_asset.version),
            ) if is_copy or create_collection else _restore_version_action(result_asset, old_root_id)
        )
        actual_binding = next(view for view in bindings.bindings if view.asset.id == result_asset.id)
        target = _target(result_asset, result_version)
        target.update({
            "binding_version": int(actual_binding.binding.version),
            "bound_asset_version_id": str(actual_binding.asset_version.id),
            "used_by_current_novel": actual_binding.binding.usage_policy != "prohibited",
        })
        return AppliedAction(
            "upsert_and_use_lexicon_entries", not replayed or bindings.changed,
            target, None, (binding_undo, asset_undo),
        )

    def _apply_remove_lexicon_entries(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        asset_id = _required_asset_id(action)
        asset, before_version = self._asset(request, asset_id)
        payload = action.payload
        _require_payload_keys(payload, required={"entry_ids"}, allowed={"entry_ids"})
        if not isinstance(payload["entry_ids"], list):
            raise PrivateLibraryValidationError("entry_ids must be a list")
        pack = remove_lexicon_entries(
            lexicon_pack_from_version(before_version),
            [str(value) for value in payload["entry_ids"]],
        )
        scope = self._scope(request)
        result_asset, result_version, replayed = save_lexicon_pack(
            self.session,
            asset_id=asset.id,
            expected_root_version=self._expected(action),
            pack=pack,
            operation_key=self._key(request, index, "remove"),
            novel_id=scope.novel_id,
        )
        undo = _restore_version_action(result_asset, before_version.id)
        return AppliedAction(
            "remove_lexicon_entries", not replayed,
            _target(result_asset, result_version), undo,
        )

    def _apply_set_novel_binding(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        scope = self._scope(request)
        if scope.novel_id is None:
            raise PrivateLibraryValidationError("trusted novel scope is required")
        payload = action.payload
        _require_payload_keys(
            payload,
            required={"expected_binding_versions", "selections"},
            allowed={"expected_binding_versions", "selections"},
        )
        before = list_novel_bindings(self.session, scope.novel_id)
        inverse_selections = _binding_selections(before)
        if not isinstance(payload["selections"], list):
            raise PrivateLibraryValidationError("binding payload is invalid")
        selections = tuple(_selection(item) for item in payload["selections"])
        expected = _binding_versions(payload["expected_binding_versions"])
        result = replace_novel_bindings(
            self.session,
            scope.novel_id,
            expected_binding_versions=expected,
            selections=selections,
            operation_key=self._key(request, index, "bindings"),
        )
        inverse_expected = {
            str(view.binding.asset_id): int(view.binding.version)
            for view in result.bindings
        }
        undo = (
            LibraryChangeAction(
                operation=LibraryChangeOperation.SET_NOVEL_BINDING,
                payload={
                    "expected_binding_versions": inverse_expected,
                    "selections": inverse_selections,
                },
            )
            if result.changed
            else None
        )
        return AppliedAction(
            "set_novel_binding",
            bool(result.changed),
            {"novel_id": str(scope.novel_id), "binding_count": len(result.bindings)},
            undo,
        )

    def _apply_create_novel_copy(
        self, request: Any, action: LibraryChangeAction, index: int
    ) -> AppliedAction:
        scope = self._scope(request)
        if scope.novel_id is None:
            raise PrivateLibraryValidationError("trusted novel scope is required")
        source_asset_id = _required_asset_id(action)
        if action.asset_version_id is None:
            raise PrivateLibraryValidationError("source asset_version_id is required")
        _require_payload_keys(action.payload, required=set(), allowed=set())
        asset, version, created = create_novel_lexicon_copy(
            self.session,
            novel_id=scope.novel_id,
            source_asset_id=source_asset_id,
            source_version_id=action.asset_version_id,
            operation_key=self._key(request, index, "novel-copy"),
        )
        undo = (
            LibraryChangeAction(
                operation=LibraryChangeOperation.ARCHIVE_ASSET,
                asset_id=asset.id,
                expected_root_version=int(asset.version),
            )
            if created
            else None
        )
        return AppliedAction(
            "create_novel_copy", created, _target(asset, version), undo
        )


def _required_asset_id(action: LibraryChangeAction) -> UUID:
    if action.asset_id is None:
        raise PrivateLibraryValidationError("asset_id is required")
    return action.asset_id


def _require_payload_keys(
    payload: Mapping[str, Any], *, required: set[str], allowed: set[str]
) -> None:
    missing = required - set(payload)
    extra = set(payload) - allowed
    if missing:
        raise PrivateLibraryValidationError(
            "missing action payload fields: " + ",".join(sorted(missing))
        )
    if extra:
        raise PrivateLibraryValidationError(
            "unsupported action payload fields: " + ",".join(sorted(extra))
        )


def _target(asset: Any, version: Any | None) -> dict[str, Any]:
    return {
        "asset_id": str(asset.id),
        "root_version": int(asset.version),
        "asset_version_id": str(version.id) if version is not None else None,
        "archived": bool(asset.archived),
    }


def _restore_version_action(asset: Any, version_id: UUID) -> LibraryChangeAction:
    return LibraryChangeAction(
        operation=LibraryChangeOperation.RESTORE_ASSET,
        asset_id=asset.id,
        expected_root_version=int(asset.version),
        payload={"target_version_id": str(version_id)},
    )


def _binding_selections(views: Sequence[Any]) -> list[dict[str, Any]]:
    # Freeze scalar values before replace_novel_bindings mutates ORM rows.
    return [{
        "asset_id": str(view.asset.id),
        "asset_version_id": str(view.asset_version.id),
        "usage_policy": str(view.binding.usage_policy),
        "position": int(view.binding.position),
    } for view in views]


def _binding_versions(value: Any) -> dict[UUID, int]:
    if not isinstance(value, Mapping):
        raise PrivateLibraryValidationError("binding versions must be an object")
    try:
        return {
            UUID(str(key)): _positive_integer(version, field="binding version")
            for key, version in value.items()
        }
    except (TypeError, ValueError) as error:
        raise PrivateLibraryValidationError("binding versions are invalid") from error


def _selection(value: Mapping[str, Any]) -> VersionSelection:
    if not isinstance(value, Mapping):
        raise PrivateLibraryValidationError("binding selection is invalid")
    try:
        return VersionSelection(
            asset_id=UUID(str(value["asset_id"])),
            asset_version_id=UUID(str(value["asset_version_id"])),
            usage_policy=UsagePolicy(str(value.get("usage_policy", "preferred"))),
            position=_non_negative_integer(
                value.get("position", 0), field="binding position"
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PrivateLibraryValidationError("binding selection is invalid") from error


def _positive_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PrivateLibraryValidationError(f"{field} must be a positive integer")
    return value


def _non_negative_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrivateLibraryValidationError(f"{field} must be a non-negative integer")
    return value


def _actions_from_row(row: Any) -> tuple[LibraryChangeAction, ...]:
    try:
        return tuple(LibraryChangeAction.model_validate(item) for item in row.actions_json)
    except Exception as error:
        raise PrivateLibraryConflictError(
            "maintenance_actions_invalid", current={"proposal_id": str(row.id)}
        ) from error


def _mark_conflict(store: ChangeRequestStore, row: Any, error: Exception) -> dict[str, Any]:
    code = (
        error.code
        if isinstance(error, PrivateLibraryConflictError)
        else "unsupported_change"
        if isinstance(error, UnsupportedLibraryChange)
        else "invalid_change"
    )
    row.state = "conflict"
    row.version = int(row.version) + 1
    row.result_json = {
        "counts": {
            "changed": 0,
            "unchanged": 0,
            "unsupported": int(isinstance(error, UnsupportedLibraryChange)),
        },
        "error": {"code": code, "message": str(error)},
    }
    row.updated_at = datetime.now(timezone.utc)
    store.flush()
    return {"receipt": _receipt(row)}


def apply_library_change(
    store: ChangeRequestStore,
    executor: MaintenanceActionExecutor,
    access: LibraryAccessEvidence,
    *,
    proposal_id: UUID,
    expected_version: int,
    intent: AuthorMaintenanceIntent,
) -> dict[str, Any]:
    """Apply one exact current proposal and persist its server receipt."""

    row = store.get(proposal_id, for_update=True)
    if row is None or not _request_matches_access(row, access):
        raise PrivateLibraryNotFoundError("maintenance proposal not found")
    if row.state == "applied":
        return {"receipt": _receipt(row, replayed=True)}
    if row.state != "proposed":
        return {"receipt": _receipt(row, replayed=True)}
    if isinstance(expected_version, bool) or int(row.version) != expected_version:
        raise PrivateLibraryConflictError(
            "maintenance_proposal_version_conflict",
            current={"proposal_id": str(row.id), "version": int(row.version)},
        )
    requires_review = bool(
        (row.source_json or {}).get("_maintenance", {}).get("requires_review")
    )
    same_author_request = (
        row.request_id == access.request_id
        and row.author_text_hash == access.author_text_hash
    )
    if requires_review:
        if intent is not AuthorMaintenanceIntent.ACCEPT_PROPOSAL:
            raise PrivateLibraryValidationError(
                "reviewed proposal requires explicit author acceptance"
            )
    elif not (
        same_author_request and intent is AuthorMaintenanceIntent.DIRECT
    ) and intent is not AuthorMaintenanceIntent.ACCEPT_PROPOSAL:
        raise PrivateLibraryValidationError(
            "proposal is not authorized by this author message"
        )

    outcomes: list[AppliedAction] = []
    try:
        with store.action_savepoint():
            for index, action in enumerate(_actions_from_row(row)):
                outcomes.append(
                    executor.apply(row, action, action_index=index)
                )
    except (
        PrivateLibraryConflictError,
        PrivateLibraryNotFoundError,
        PrivateLibraryValidationError,
        UnsupportedLibraryChange,
    ) as error:
        return _mark_conflict(store, row, error)

    now = datetime.now(timezone.utc)
    changed = sum(item.changed for item in outcomes)
    row.state = "applied"
    row.version = int(row.version) + 1
    row.result_json = {
        "counts": {
            "changed": changed,
            "unchanged": len(outcomes) - changed,
            "unsupported": 0,
        },
        "targets": [item.target for item in outcomes],
        "operations": [item.operation for item in outcomes],
        "undo_actions": [
            inverse.model_dump(mode="json")
            for item in reversed(outcomes)
            for inverse in (
                item.undo_actions or ((item.undo_action,) if item.undo_action is not None else ())
            )
        ],
        "authorization": {
            "kind": (
                "accepted_proposal"
                if intent is AuthorMaintenanceIntent.ACCEPT_PROPOSAL
                else "direct_author_command"
            ),
            "author_text_hash": access.author_text_hash,
            "proposal_version": expected_version,
        },
    }
    row.applied_at = now
    row.updated_at = now
    store.flush()
    return {"receipt": _receipt(row)}


def undo_library_change(
    store: ChangeRequestStore,
    executor: MaintenanceActionExecutor,
    access: LibraryAccessEvidence,
    *,
    proposal_id: UUID,
    expected_version: int,
    intent: AuthorMaintenanceIntent,
) -> dict[str, Any]:
    """Create and apply a compensation request; never rewrite old history."""

    if intent is not AuthorMaintenanceIntent.UNDO:
        raise PrivateLibraryValidationError("undo requires an explicit author command")
    original = store.get(proposal_id, for_update=True)
    if original is None or not _request_matches_access(original, access):
        raise PrivateLibraryNotFoundError("maintenance receipt not found")
    if original.state != "applied" or int(original.version) != expected_version:
        raise PrivateLibraryConflictError(
            "maintenance_undo_receipt_conflict",
            current={
                "proposal_id": str(original.id),
                "state": original.state,
                "version": int(original.version),
            },
        )
    prior_undo = store.find_undo(original.id)
    if prior_undo is not None:
        if not _request_matches_access(prior_undo, access):
            raise PrivateLibraryNotFoundError("maintenance undo receipt not found")
        return {"receipt": _receipt(prior_undo, replayed=True)}
    undo_payloads = (original.result_json or {}).get("undo_actions")
    if not isinstance(undo_payloads, list) or not undo_payloads:
        raise UnsupportedLibraryChange("this receipt has no compensating action")
    undo_actions = tuple(
        LibraryChangeAction.model_validate(item) for item in undo_payloads
    )
    scope = scope_from_access(access)
    content_payload = {
        "scope": scope.model_dump(mode="json"),
        "undo_of_id": str(original.id),
        "actions": [action.model_dump(mode="json") for action in undo_actions],
    }
    now = datetime.now(timezone.utc)
    undo = LibraryChangeRequest(
        id=uuid4(),
        request_id=access.request_id,
        scope_kind=scope.kind.value,
        scope_novel_id=scope.novel_id,
        session_id=access.session_id,
        author_text_hash=access.author_text_hash,
        source_json={
            "capture": {},
            "_maintenance": {
                "requires_review": False,
                "intent": AuthorMaintenanceIntent.UNDO.value,
            },
        },
        actions_json=[action.model_dump(mode="json") for action in undo_actions],
        content_hash=canonical_hash(content_payload),
        idempotency_key=f"library-undo:{original.id}:{access.request_id}"[:160],
        state="proposed",
        version=1,
        result_json={},
        undo_of_id=original.id,
        applied_at=None,
        created_at=now,
        updated_at=now,
    )
    store.add(undo)
    store.flush()
    outcomes: list[AppliedAction] = []
    try:
        with store.action_savepoint():
            for index, action in enumerate(undo_actions):
                outcomes.append(executor.apply(undo, action, action_index=index))
    except (
        PrivateLibraryConflictError,
        PrivateLibraryNotFoundError,
        PrivateLibraryValidationError,
        UnsupportedLibraryChange,
    ) as error:
        return _mark_conflict(store, undo, error)

    changed = sum(item.changed for item in outcomes)
    undo.state = "applied"
    undo.version = 2
    undo.applied_at = now
    undo.updated_at = now
    undo.result_json = {
        "counts": {
            "changed": changed,
            "unchanged": len(outcomes) - changed,
            "unsupported": 0,
        },
        "targets": [item.target for item in outcomes],
        "operations": [item.operation for item in outcomes],
        "undo_actions": [],
        "compensates": str(original.id),
        "authorization": {
            "kind": "undo_author_command",
            "author_text_hash": access.author_text_hash,
            "receipt_version": expected_version,
        },
    }
    store.flush()
    return {"receipt": _receipt(undo)}


__all__ = [
    "AppliedAction",
    "AuthorMaintenanceIntent",
    "ChangeRequestStore",
    "MaintenanceActionExecutor",
    "P1MaintenanceActionExecutor",
    "SqlAlchemyChangeRequestStore",
    "UnsupportedLibraryChange",
    "apply_library_change",
    "classify_author_intent",
    "prepare_library_change",
    "query_library",
    "scope_from_access",
    "undo_library_change",
]
