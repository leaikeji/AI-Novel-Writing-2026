"""Persistent narration request creation, replay protection, and state CAS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..models import Document, DocumentRevision, NarrationRequest, NarrationRequestSource

from .contracts import NarrationRequestScope
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    canonical_sha256,
    require_exact_bool,
    require_fixed_scope,
    require_exact_int,
    require_local_novel,
    require_nonempty,
    require_row,
    require_same_novel,
    require_sha256,
)


REQUEST_INTENTS = frozenset({"analyze_only", "create", "update", "batch"})
REQUEST_TRANSITIONS = {
    "created": frozenset({"analyzing", "cancel_requested"}),
    "analyzing": frozenset({"analyzed", "review_required", "queued", "cancel_requested", "failed"}),
    "analyzed": frozenset({"queued", "cancel_requested", "failed"}),
    "review_required": frozenset({"analyzing", "queued", "cancel_requested", "failed"}),
    "queued": frozenset({"rendering", "cancel_requested", "failed"}),
    "rendering": frozenset({"partial_ready", "ready", "cancel_requested", "failed"}),
    "partial_ready": frozenset({"ready", "cancel_requested", "failed"}),
    "cancel_requested": frozenset({"cancelled"}),
    "failed": frozenset({"queued"}),
}


@dataclass(frozen=True, slots=True)
class RequestSource:
    document_id: UUID
    revision_id: UUID
    content_hash: str
    position: int


@dataclass(frozen=True, slots=True)
class CreateNarrationRequest:
    novel_id: UUID
    intent: str
    idempotency_key: str
    settings_fingerprint: str
    force_review: bool = False
    effective_policy: str = "blockers_only"
    document_id: UUID | None = None
    source_revision_id: UUID | None = None
    source_content_hash: str | None = None
    sources: tuple[RequestSource, ...] = ()
    # T4 HTTP idempotency binds the optimistic save/settings barriers as well
    # as the resulting immutable snapshot identities.  Older internal callers
    # may omit these fields; production orchestration always supplies both.
    expected_draft_version: int | None = None
    expected_settings_version: int | None = None
    explicit_generation_intent_at: datetime | None = None
    explicit_generation_actor: str | None = None
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local()


def _validate_source(
    store: NarrationStore, *, novel_id: UUID, source: RequestSource
) -> None:
    document = require_row(store.get(Document, source.document_id), label="source document")
    require_same_novel(document.novel_id, novel_id, label="source document")
    revision = require_row(store.get(DocumentRevision, source.revision_id), label="source revision")
    if revision.document_id != source.document_id:
        raise NarrationScopeMismatch("source revision belongs to another document")
    require_sha256(source.content_hash, field="source content hash")
    if revision.content_hash != source.content_hash:
        raise NarrationServiceError("source content hash does not match immutable revision")
    require_exact_int(source.position, field="source position", minimum=0)


def request_hash(command: CreateNarrationRequest) -> str:
    """Hash every canonical request input, including explicit generation proof."""

    payload: dict[str, object] = {
        "owner_id": str(command.scope.owner_id),
        "workspace_id": str(command.scope.workspace_id),
        "novel_id": str(command.novel_id),
        "document_id": str(command.document_id) if command.document_id else None,
        "intent": command.intent,
        "settings_fingerprint": command.settings_fingerprint,
        "force_review": command.force_review,
        "effective_policy": command.effective_policy,
        "source_revision_id": (
            str(command.source_revision_id) if command.source_revision_id else None
        ),
        "source_content_hash": command.source_content_hash,
        "sources": [
            {
                "document_id": str(source.document_id),
                "revision_id": str(source.revision_id),
                "content_hash": source.content_hash,
                "position": source.position,
            }
            for source in sorted(command.sources, key=lambda item: item.position)
        ],
        "explicit_generation_intent_at": (
            command.explicit_generation_intent_at.astimezone(UTC).isoformat()
            if command.explicit_generation_intent_at
            else None
        ),
        "explicit_generation_actor": command.explicit_generation_actor,
    }
    # Preserve pre-T4 hashes for internal callers that do not participate in
    # the HTTP save/settings barrier contract.  T4 always supplies both values.
    if (
        command.expected_draft_version is not None
        or command.expected_settings_version is not None
    ):
        payload.update(
            {
                "expected_draft_version": command.expected_draft_version,
                "expected_settings_version": command.expected_settings_version,
            }
        )
    return canonical_sha256(payload)


def source_set_hash(sources: tuple[RequestSource, ...]) -> str:
    """Fingerprint the exact ordered child-source manifest."""

    return canonical_sha256(
        [
            {
                "document_id": str(source.document_id),
                "revision_id": str(source.revision_id),
                "content_hash": source.content_hash,
                "position": source.position,
            }
            for source in sorted(sources, key=lambda item: item.position)
        ]
    )


def _stored_sources(
    store: NarrationStore, request: NarrationRequest
) -> tuple[RequestSource, ...]:
    return tuple(
        RequestSource(
            document_id=row.document_id,
            revision_id=row.revision_id,
            content_hash=row.content_hash,
            position=row.position,
        )
        for row in store.find_all(
            NarrationRequestSource,
            request_id=request.id,
            order_by=("position",),
            for_update=True,
        )
    )


def _require_sealed_source_manifest(
    store: NarrationStore,
    request: NarrationRequest,
    *,
    expected_sources: tuple[RequestSource, ...] | None = None,
) -> tuple[RequestSource, ...]:
    actual_sources = _stored_sources(store, request)
    if request.sources_sealed_at is None:
        raise IdempotencyConflict("narration request source manifest is not sealed")
    if request.source_count != len(actual_sources):
        raise IdempotencyConflict("narration request source count drifted")
    if request.source_set_hash != source_set_hash(actual_sources):
        raise IdempotencyConflict("narration request source manifest hash drifted")
    if expected_sources is not None and actual_sources != tuple(
        sorted(expected_sources, key=lambda item: item.position)
    ):
        raise IdempotencyConflict("idempotent replay source manifest differs")
    return actual_sources


def create_request(store: NarrationStore, command: CreateNarrationRequest) -> NarrationRequest:
    require_fixed_scope(command.scope)
    # The novel is the stable parent mutex for first-write idempotency keys.
    require_local_novel(store, command.novel_id, for_update=True)
    require_nonempty(command.idempotency_key, field="idempotency_key")
    require_sha256(command.settings_fingerprint, field="settings_fingerprint")
    require_exact_bool(command.force_review, field="force_review")
    if (command.expected_draft_version is None) != (
        command.expected_settings_version is None
    ):
        raise NarrationServiceError(
            "draft/settings idempotency barriers must be supplied together"
        )
    if command.expected_draft_version is not None:
        require_exact_int(
            command.expected_draft_version,
            field="expected_draft_version",
            minimum=1,
        )
    if command.expected_settings_version is not None:
        require_exact_int(
            command.expected_settings_version,
            field="expected_settings_version",
            minimum=1,
        )
    if command.intent not in REQUEST_INTENTS:
        raise NarrationServiceError("unsupported narration request intent")
    if command.effective_policy not in {"blockers_only", "always_review"}:
        raise NarrationServiceError("unsupported effective review policy")
    if command.force_review and command.effective_policy != "always_review":
        raise NarrationServiceError("force_review requires always_review policy")
    if command.intent == "analyze_only":
        if command.explicit_generation_intent_at or command.explicit_generation_actor:
            raise NarrationServiceError("analyze_only cannot carry generation intent")
    elif not command.explicit_generation_intent_at or not command.explicit_generation_actor:
        raise NarrationServiceError("generation requests require actor and timestamp")
    elif type(command.explicit_generation_intent_at) is not datetime:
        raise NarrationServiceError("generation intent timestamp must be a datetime")
    elif command.explicit_generation_intent_at.tzinfo is None:
        raise NarrationServiceError("generation intent timestamp must be timezone-aware")
    else:
        require_nonempty(
            command.explicit_generation_actor, field="explicit_generation_actor"
        )

    frozen_sources: tuple[RequestSource, ...]
    uses_source_rows = False
    if command.intent in {"create", "update"}:
        if not command.document_id or not command.source_revision_id or not command.source_content_hash:
            raise NarrationServiceError("create/update requires one immutable document revision")
        if command.sources:
            raise NarrationServiceError("create/update cannot also carry batch sources")
        frozen_sources = (
            RequestSource(
                document_id=command.document_id,
                revision_id=command.source_revision_id,
                content_hash=command.source_content_hash,
                position=0,
            ),
        )
    elif command.intent in {"batch", "analyze_only"} and command.sources:
        if command.document_id or command.source_revision_id or command.source_content_hash:
            raise NarrationServiceError("multi-document sources must use the frozen source list")
        positions = [source.position for source in command.sources]
        if sorted(positions) != list(range(len(command.sources))):
            raise NarrationServiceError("request source positions must be contiguous from zero")
        if len({source.document_id for source in command.sources}) != len(command.sources):
            raise NarrationServiceError("request source documents must be unique")
        frozen_sources = command.sources
        uses_source_rows = True
    elif command.intent == "batch":
        raise NarrationServiceError("batch request requires at least one frozen source")
    else:
        if not command.document_id or not command.source_revision_id or not command.source_content_hash:
            raise NarrationServiceError(
                "single-document analyze_only requires one immutable document revision"
            )
        frozen_sources = (
            RequestSource(
                document_id=command.document_id,
                revision_id=command.source_revision_id,
                content_hash=command.source_content_hash,
                position=0,
            ),
        )

    for source in frozen_sources:
        _validate_source(store, novel_id=command.novel_id, source=source)

    digest = request_hash(command)
    child_sources = tuple(
        sorted(frozen_sources, key=lambda item: item.position)
    ) if uses_source_rows else ()
    child_source_hash = source_set_hash(child_sources)
    existing = store.find_one(
        NarrationRequest,
        for_update=True,
        owner_id=command.scope.owner_id,
        workspace_id=command.scope.workspace_id,
        idempotency_key=command.idempotency_key,
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise IdempotencyConflict("idempotency key was already used for another request")
        _require_sealed_source_manifest(
            store,
            existing,
            expected_sources=child_sources,
        )
        return existing

    row = NarrationRequest(
        id=uuid4(),
        owner_id=command.scope.owner_id,
        workspace_id=command.scope.workspace_id,
        novel_id=command.novel_id,
        document_id=command.document_id,
        intent=command.intent,
        request_hash=digest,
        idempotency_key=command.idempotency_key,
        source_revision_id=command.source_revision_id,
        source_content_hash=command.source_content_hash,
        source_count=len(child_sources),
        source_set_hash=child_source_hash,
        sources_sealed_at=(None if uses_source_rows else datetime.now(UTC)),
        settings_fingerprint=command.settings_fingerprint,
        force_review=command.force_review,
        effective_policy=command.effective_policy,
        state="created",
        version=1,
        explicit_generation_intent_at=command.explicit_generation_intent_at,
        explicit_generation_actor=command.explicit_generation_actor,
    )
    store.add(row)
    store.flush()
    if uses_source_rows:
        for source in child_sources:
            store.add(
                NarrationRequestSource(
                    id=uuid4(),
                    request_id=row.id,
                    novel_id=command.novel_id,
                    document_id=source.document_id,
                    revision_id=source.revision_id,
                    content_hash=source.content_hash,
                    position=source.position,
                )
            )
        store.flush()
        # PostgreSQL replaces this marker with its authoritative clock in the
        # sealing trigger after it verifies the complete ordered child set.
        row.sources_sealed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        store.flush()
    # Reload through the locking persistence boundary so callers observe the
    # database-authoritative seal timestamp installed by the trigger instead
    # of the client-side marker used to request sealing.
    return require_row(
        store.get(NarrationRequest, row.id, for_update=True),
        label="narration request",
    )


def require_generation_request(
    store: NarrationStore, request_id: UUID, *, novel_id: UUID, for_update: bool = False
) -> NarrationRequest:
    request = require_row(
        store.get(NarrationRequest, request_id, for_update=for_update), label="narration request"
    )
    require_same_novel(request.novel_id, novel_id, label="narration request")
    if request.intent == "analyze_only":
        raise InvalidNarrationState("analyze_only can never create Edition or render")
    if request.explicit_generation_intent_at is None or not request.explicit_generation_actor:
        raise InvalidNarrationState("request has no explicit generation proof")
    return request


def advance_request_state(
    store: NarrationStore,
    request_id: UUID,
    *,
    expected_version: int,
    new_state: str,
    novel_id: UUID,
    actor: str,
    reason_code: str | None = None,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> NarrationRequest:
    require_fixed_scope(scope)
    require_exact_int(expected_version, field="expected_version", minimum=1)
    require_nonempty(actor, field="actor")
    request = require_row(
        store.get(NarrationRequest, request_id, for_update=True), label="narration request"
    )
    if request.owner_id != scope.owner_id or request.workspace_id != scope.workspace_id:
        raise NarrationScopeMismatch("narration request is outside fixed local scope")
    require_same_novel(request.novel_id, novel_id, label="narration request")
    if request.version != expected_version:
        raise NarrationCasConflict("narration request version changed")
    source_rows = _require_sealed_source_manifest(store, request)
    if new_state not in REQUEST_TRANSITIONS.get(request.state, frozenset()):
        raise InvalidNarrationState(f"invalid request transition {request.state}->{new_state}")
    if request.state == "created" and new_state == "analyzing":
        has_direct_source = bool(request.source_revision_id and request.source_content_hash)
        has_source_rows = bool(source_rows)
        if not has_direct_source and not has_source_rows:
            raise InvalidNarrationState("narration request has no frozen source")
    if request.intent == "analyze_only" and new_state in {
        "queued", "rendering", "partial_ready", "ready"
    }:
        raise InvalidNarrationState("analyze_only cannot enter generation states")
    previous_state = request.state
    request.state = new_state
    request.version = expected_version + 1
    now = datetime.now(UTC)
    request.updated_at = now
    if new_state == "cancel_requested":
        require_nonempty(reason_code or "", field="cancel_reason_code")
        request.cancel_requested_at = now
        request.cancel_actor = actor
        request.cancel_reason_code = reason_code
    elif new_state == "failed":
        require_nonempty(reason_code or "", field="failure_code")
        request.failure_code = reason_code
        request.completed_at = now
    elif new_state == "queued":
        if reason_code is not None:
            raise NarrationServiceError(
                "reason_code is only valid for cancel/failure transitions"
            )
        # T3 marks ``analyzed`` complete because analysis itself is terminal.
        # A generation request resuming into T4 production is active again and
        # must not retain the completed timestamp from that earlier phase.
        request.completed_at = None
        if previous_state == "failed":
            request.failure_code = None
    elif new_state in {"analyzed", "cancelled", "ready"}:
        if reason_code is not None:
            raise NarrationServiceError("reason_code is only valid for cancel/failure transitions")
        request.completed_at = now
    elif reason_code is not None:
        raise NarrationServiceError("reason_code is only valid for cancel/failure transitions")
    store.flush()
    return request


__all__ = [
    "CreateNarrationRequest",
    "RequestSource",
    "advance_request_state",
    "create_request",
    "request_hash",
    "require_generation_request",
    "source_set_hash",
]
