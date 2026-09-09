"""Durable deterministic preparation for one native writing send.

This module does not register itself with QwenPaw; the public middleware
factory owns the explicit native capability gate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..embedding.chunking import estimate_token_count
from ..models import Document, Novel, NovelCreationDraft
from .button import current_catalog
from .composer import compose_writing_request
from .contracts import (
    ActionIdentity,
    FIXED_LOCAL_OWNER_ID,
    FIXED_LOCAL_WORKSPACE_ID,
    FrozenRouteRequest,
    MethodPreferences,
    Scope,
    canonical_hash,
)
from .middleware import NativePreparedAction, native_task_route
from .load_policy import ManagedMethodPolicy
from .persistence import (
    ActionConflict,
    Claim,
    PendingAction,
    StaleFence,
    advance,
    claim_pending_action,
    freeze_prepared_action,
    lookup_action,
)
from .projection import native_projection
from .resolver import resolve_methods


SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class NativeModelConfig:
    provider_id: str
    model_id: str
    effective_input_budget: int

    def __post_init__(self) -> None:
        if not self.provider_id or not self.model_id:
            raise ValueError("native model identity is unavailable")
        if type(self.effective_input_budget) is not int or self.effective_input_budget < 16_384:
            raise ValueError("native model input budget is unavailable")


NativeModelProbe = Callable[[], Awaitable[NativeModelConfig]]


class NativeActionReplay(ActionConflict):
    """The native send already has durable state and must not execute again."""

    def __init__(self, claim: Claim | PendingAction):
        self.dispatch_id = claim.id
        self.state = claim.state
        super().__init__("native_action_already_recorded")


def _scope_and_labels(
    session: Session,
    *,
    novel_id: UUID,
    document_id: UUID | None,
    tab_id: str,
) -> tuple[Scope, str, str]:
    novel = session.get(Novel, novel_id)
    document = session.get(Document, document_id) if document_id is not None else None
    if novel is None or (
        document_id is not None
        and (document is None or document.novel_id != novel.id)
    ):
        raise PermissionError("native writing scope is unavailable")
    return (
        Scope(
            owner_id=novel.owner_id,
            workspace_id=novel.workspace_id,
            kind="novel",
            scope_id=novel.id,
            document_id=document_id,
            tab_id=tab_id,
        ),
        novel.genre,
        novel.subgenre,
    )


def _creation_scope_and_labels(
    session: Session,
    *,
    draft_id: UUID,
    expected_version: int,
    expected_step: int,
    tab_id: str,
) -> tuple[Scope, str, str]:
    draft = session.get(NovelCreationDraft, draft_id)
    if (
        draft is None
        or draft.state != "draft"
        or draft.version != expected_version
        or draft.step != expected_step
    ):
        raise PermissionError("native creation draft scope is unavailable")
    data = draft.data_json if isinstance(draft.data_json, Mapping) else {}
    genre = data.get("genre", "")
    subgenre = data.get("subgenre", "")
    if not isinstance(genre, str) or not isinstance(subgenre, str):
        raise PermissionError("native creation draft classification is invalid")
    return (
        Scope(
            owner_id=FIXED_LOCAL_OWNER_ID,
            workspace_id=FIXED_LOCAL_WORKSPACE_ID,
            kind="creation_draft",
            scope_id=draft.id,
            tab_id=tab_id,
        ),
        genre,
        subgenre,
    )


def _authorize(session: Session, scope: Scope) -> None:
    if scope.kind == "creation_draft":
        draft = session.get(NovelCreationDraft, scope.scope_id)
        if (
            draft is None
            or draft.state != "draft"
            or scope.owner_id != FIXED_LOCAL_OWNER_ID
            or scope.workspace_id != FIXED_LOCAL_WORKSPACE_ID
            or scope.document_id is not None
        ):
            raise PermissionError("native creation draft scope changed")
        return
    current, _, _ = _scope_and_labels(
        session,
        novel_id=scope.scope_id,
        document_id=scope.document_id,
        tab_id=scope.tab_id,
    )
    if current != scope:
        raise PermissionError("native writing scope changed")


def _route_data(genre: str, subgenre: str) -> str:
    payload = json.dumps(
        {"genre": genre, "subgenre": subgenre},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c").replace(">", "\\u003e")
    return "【本轮写作分类资料；数据角色=user】" + payload


async def prepare_native_action(
    *,
    session_factory: SessionFactory,
    asgi_app: Any,
    action_id: UUID,
    tab_id: str,
    session_id: str,
    snapshot: Mapping[str, Any],
    user_text: str,
    model_probe: NativeModelProbe,
) -> NativePreparedAction | None:
    """Claim and freeze one explicit current-turn native writing request."""

    route = native_task_route(snapshot, user_text)
    if route is None:
        return None
    raw_draft = snapshot.get("creationDraft")
    creation_scope = isinstance(raw_draft, Mapping)
    try:
        if creation_scope:
            draft_id = UUID(str(raw_draft["id"]))
            draft_version = int(raw_draft["version"])
            draft_step = int(raw_draft["step"])
            novel_id = None
            document_id = None
        else:
            novel_id = UUID(str(snapshot["novel"]["id"]))
            raw_document = snapshot.get("document")
            document_id = (
                UUID(str(raw_document["id"]))
                if isinstance(raw_document, Mapping) and raw_document.get("id")
                else None
            )
            draft_id = None
            draft_version = 0
            draft_step = 0
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PermissionError("native writing snapshot scope is invalid") from None

    with session_factory() as session:
        if creation_scope:
            assert draft_id is not None
            scope, genre, subgenre = _creation_scope_and_labels(
                session,
                draft_id=draft_id,
                expected_version=draft_version,
                expected_step=draft_step,
                tab_id=tab_id,
            )
        else:
            assert novel_id is not None
            scope, genre, subgenre = _scope_and_labels(
                session,
                novel_id=novel_id,
                document_id=document_id,
                tab_id=tab_id,
            )
        projection = native_projection(
            scope,
            snapshot,
            user_text,
            route,
            genre=genre,
            subgenre=subgenre,
        )
        identity = ActionIdentity(
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            entry="native",
            action_id=action_id,
        )
        client_hash = canonical_hash({
            "schema": "native-writing-send/1",
            "session_id": session_id,
            "projection": projection.model_dump(mode="json"),
        })
        existing = lookup_action(
            session,
            identity,
            scope,
            client_hash,
            authorize=_authorize,
        )
        if existing is not None:
            raise NativeActionReplay(existing)
        pending = claim_pending_action(
            session,
            identity,
            scope,
            client_hash,
            authorize=_authorize,
        )
    if not pending.acquired:
        raise NativeActionReplay(pending)

    current: Claim | PendingAction = pending
    try:
        configured = await model_probe()
        catalog, primary = await current_catalog(
            asgi_app,
            primary_skill=route.primary_skill,
        )
        frozen = FrozenRouteRequest(
            identity=identity,
            projection=projection,
            preferences=MethodPreferences(),
            catalog_version=catalog.version,
            provider_id=configured.provider_id,
            model_id=configured.model_id,
        )
        with session_factory() as session:
            current = freeze_prepared_action(session, pending, frozen)
        plan = resolve_methods(
            projection,
            catalog,
            frozen.preferences,
            primary_skill=route.primary_skill,
        )
        route_data_text = _route_data(genre, subgenre)
        reserved = (
            estimate_token_count(user_text)
            + estimate_token_count(route_data_text)
            + 4_096
        )
        packet = compose_writing_request(
            plan,
            catalog,
            primary_blocks=primary,
            effective_input_budget=configured.effective_input_budget,
            reserved_task_tokens=reserved,
        )
        with session_factory() as session:
            current = advance(session, current, "route_ready")
        with session_factory() as session:
            current = advance(session, current, "assembled", packet=packet)
    except BaseException:
        if current.state in {"claimed", "route_ready", "assembled"}:
            with session_factory() as session:
                try:
                    current = advance(
                        session,
                        current,
                        "failed",
                        error_code="native_preparation_failed",
                    )
                except StaleFence:
                    pass
        raise

    async def verify_current() -> None:
        nonlocal current
        with session_factory() as session:
            _authorize(session, scope)
            if creation_scope:
                assert draft_id is not None
                _, fresh_genre, fresh_subgenre = _creation_scope_and_labels(
                    session,
                    draft_id=draft_id,
                    expected_version=draft_version,
                    expected_step=draft_step,
                    tab_id=tab_id,
                )
            else:
                assert novel_id is not None
                _, fresh_genre, fresh_subgenre = _scope_and_labels(
                    session,
                    novel_id=novel_id,
                    document_id=document_id,
                    tab_id=tab_id,
                )
            found = lookup_action(
                session,
                identity,
                scope,
                client_hash,
                authorize=_authorize,
            )
        if (
            not isinstance(found, Claim)
            or found.id != current.id
            or found.fence != current.fence
            or found.state != current.state
            or native_projection(
                scope,
                snapshot,
                user_text,
                route,
                genre=fresh_genre,
                subgenre=fresh_subgenre,
            ) != projection
        ):
            raise StaleFence("native action or source changed")
        fresh_model = await model_probe()
        if fresh_model != configured:
            raise ActionConflict("native model configuration changed")
        fresh_catalog, fresh_primary = await current_catalog(
            asgi_app,
            primary_skill=route.primary_skill,
        )
        if fresh_catalog.version != catalog.version or fresh_primary != primary:
            raise ActionConflict("native method catalog changed")

    async def mark_dispatch_started() -> None:
        nonlocal current
        with session_factory() as session:
            current = advance(
                session,
                current,
                "dispatch_started",
                job_ref=f"native:{action_id}",
            )

    async def mark_dispatched() -> None:
        nonlocal current
        with session_factory() as session:
            current = advance(session, current, "dispatched")

    async def mark_failed(remote_outcome_uncertain: bool) -> None:
        nonlocal current
        target = "unknown" if remote_outcome_uncertain else "failed"
        with session_factory() as session:
            try:
                current = advance(
                    session,
                    current,
                    target,
                    error_code=(
                        "native_transport_unknown"
                        if remote_outcome_uncertain
                        else "native_dispatch_failed"
                    ),
                )
            except StaleFence:
                pass

    return NativePreparedAction(
        policy=ManagedMethodPolicy(packet),
        verify_current=verify_current,
        mark_dispatch_started=mark_dispatch_started,
        mark_dispatched=mark_dispatched,
        mark_failed=mark_failed,
        route_data_text=route_data_text,
    )


__all__ = [
    "NativeActionReplay",
    "NativeModelConfig",
    "prepare_native_action",
]
