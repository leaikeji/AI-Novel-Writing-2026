"""T4-A request-to-Edition orchestration and recovery projections.

The pure orchestration function assumes a caller-owned short transaction.  The
SQLAlchemy service below supplies that unit of work.  Every operation in this
module is database/local-rule work; Nano, FFmpeg, files, and network calls are
strictly outside this boundary.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..models import (
    AnonymousSpeaker,
    BackgroundJob,
    CharacterVoiceBinding,
    Document,
    GenericVoicePool,
    GenericVoiceSlot,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationRequest,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    NarrationSettingsSnapshot,
    PronunciationProfile,
    VoiceProfile,
    VoiceProfileVersion,
)

from .contracts import NarrationRequestScope
from .authority_locks import (
    VoiceAuthorityLock,
    lock_request_document_mutex,
    lock_voice_authorities,
    require_voice_authority_lock,
)
from .digest_keyring import DigestKeyring
from .editions import CreateEdition, EditionSegmentInput, create_edition
from .manifest import BUFFER_POLICIES, INITIAL_BUFFER_POLICY
from .render_cache import (
    RenderJobQueue,
    SqlAlchemyRenderJobQueue,
    plan_edition_renders,
)
from .regeneration import finalize_ready_cache_only_edition
from .requests import (
    CreateNarrationRequest,
    advance_request_state,
    create_request,
)
from .script_analysis import AnalyzeNarrationScript, analyze_narration_script
from .script_contracts import (
    CastingDecisionOrigin,
    CastingTargetKind,
    NarrationScriptContract,
    SegmentContract,
    ScriptVersionState,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    SqlAlchemyNarrationStore,
    StaleNarrationInput,
    canonical_payload,
    canonical_sha256,
    require_exact_bool,
    require_exact_int,
    require_fixed_scope,
    require_local_novel,
    require_nonempty,
    require_row,
    require_sha256,
    utc_now,
)
from .snapshots import (
    CreateSettingsSnapshot,
    CreateTtsSnapshot,
    SETTINGS_SNAPSHOT_SCHEMA_VERSION,
    create_settings_snapshot,
    create_tts_snapshot,
)


NARRATION_EDITION_RESOLUTION_VERSION = "narration-edition-resolution/2"
LEGACY_NARRATION_EDITION_RESOLUTION_VERSION = "narration-edition-resolution/1"
T4_REQUEST_INTENTS = frozenset({"create", "update", "analyze_only"})


@dataclass(frozen=True, slots=True)
class NarrationProductionPolicy:
    """Server-owned production inputs; none are accepted from HTTP clients."""

    tts_fingerprint: str
    tokenizer_fingerprint: str
    normalizer_fingerprint: str
    postprocess_fingerprint: str
    digest_keyring: DigestKeyring = field(repr=False)
    buffer_policy_version: str = INITIAL_BUFFER_POLICY.version
    base_priority: int = 0
    max_attempts: int = 3
    created_actor: str = "narration-production-orchestrator"

    def __post_init__(self) -> None:
        if type(self.digest_keyring) is not DigestKeyring:
            raise InvalidNarrationState("production policy requires a digest keyring")
        for field_name, value in (
            ("tts_fingerprint", self.tts_fingerprint),
            ("tokenizer_fingerprint", self.tokenizer_fingerprint),
            ("normalizer_fingerprint", self.normalizer_fingerprint),
            ("postprocess_fingerprint", self.postprocess_fingerprint),
        ):
            require_sha256(value, field=field_name)
        if self.buffer_policy_version not in BUFFER_POLICIES:
            raise InvalidNarrationState("unsupported server buffer policy")
        require_exact_int(self.base_priority, field="base_priority", minimum=-1000)
        require_exact_int(self.max_attempts, field="max_attempts", minimum=1)
        require_nonempty(self.created_actor, field="created_actor")


@dataclass(frozen=True, slots=True)
class StartNarrationWorkflow:
    document_id: UUID
    intent: str
    expected_draft_version: int
    expected_content_hash: str
    expected_settings_version: int
    force_review: bool
    idempotency_key: str
    explicitly_requested: bool
    actor: str = "local-owner"
    requested_at: datetime | None = None
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local()


@dataclass(frozen=True, slots=True)
class NarrationWorkflowProjection:
    request_id: UUID
    intent: str
    request_version: int
    workflow_state: str
    source_revision_id: UUID
    source_content_hash: str
    settings_fingerprint: str
    warning_count: int
    blocker_count: int
    script_version_id: UUID | None
    edition_id: UUID | None
    current_manifest_revision: int | None
    job_ids: tuple[UUID, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class NarrationEditionProjection:
    edition_id: UUID
    request_id: UUID
    novel_id: UUID
    document_id: UUID
    script_version_id: UUID
    settings_fingerprint: str
    edition_fingerprint: str
    state: str
    segment_count: int
    pending_segment_count: int
    queued_segment_count: int
    rendering_segment_count: int
    ready_segment_count: int
    failed_segment_count: int
    current_manifest_revision: int | None
    job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class NarrationEditionVoiceIdentityProjection:
    profile_id: UUID
    voice_version_id: UUID
    display_name: str
    source_type: str | None
    preset_id: str | None
    resolution_contract_version: str
    legacy_fallback: bool


def _project_frozen_voice_identity(
    segment: NarrationEditionSegment,
) -> NarrationEditionVoiceIdentityProjection:
    resolution = segment.resolution_json
    if type(resolution) is dict and resolution.get("contract_version") == NARRATION_EDITION_RESOLUTION_VERSION:
        identity = resolution.get("voice_identity")
        if type(identity) is not dict:
            raise InvalidNarrationState("Edition v2 resolution has no frozen voice identity")
        if identity.get("profile_id") != str(segment.profile_id) or identity.get(
            "voice_version_id"
        ) != str(segment.voice_version_id):
            raise InvalidNarrationState("Edition frozen voice identity differs from segment identity")
        display_name = identity.get("display_name")
        source_type = identity.get("source_type")
        preset_id = identity.get("preset_id")
        if type(display_name) is not str or not display_name.strip():
            raise InvalidNarrationState("Edition frozen voice display name is invalid")
        if source_type not in {"preset", "uploaded", "generated"}:
            raise InvalidNarrationState("Edition frozen voice source type is invalid")
        if preset_id is not None and type(preset_id) is not str:
            raise InvalidNarrationState("Edition frozen preset identity is invalid")
        if (source_type == "preset") != (preset_id is not None):
            raise InvalidNarrationState("Edition frozen preset identity has an invalid shape")
        return NarrationEditionVoiceIdentityProjection(
            profile_id=segment.profile_id,
            voice_version_id=segment.voice_version_id,
            display_name=display_name,
            source_type=source_type,
            preset_id=preset_id,
            resolution_contract_version=NARRATION_EDITION_RESOLUTION_VERSION,
            legacy_fallback=False,
        )
    return NarrationEditionVoiceIdentityProjection(
        profile_id=segment.profile_id,
        voice_version_id=segment.voice_version_id,
        display_name="旧版未保存名称",
        source_type=None,
        preset_id=None,
        resolution_contract_version=LEGACY_NARRATION_EDITION_RESOLUTION_VERSION,
        legacy_fallback=True,
    )


def project_edition_voice_identities(
    store: NarrationStore,
    edition: NarrationEdition,
) -> tuple[NarrationEditionVoiceIdentityProjection, ...]:
    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    if not segments or [item.ordinal for item in segments] != list(range(len(segments))):
        raise InvalidNarrationState("Edition has an incomplete voice identity projection")
    identities_by_version: dict[UUID, NarrationEditionVoiceIdentityProjection] = {}
    for segment in segments:
        identity = _project_frozen_voice_identity(segment)
        existing_identity = identities_by_version.get(identity.voice_version_id)
        if existing_identity is not None and existing_identity != identity:
            raise InvalidNarrationState("Edition repeats one voice version with conflicting identity")
        identities_by_version[identity.voice_version_id] = identity
    return tuple(
        identities_by_version[key]
        for key in sorted(identities_by_version, key=str)
    )


def _validate_start(command: StartNarrationWorkflow) -> None:
    if type(command) is not StartNarrationWorkflow:
        raise NarrationServiceError("command must be StartNarrationWorkflow")
    require_fixed_scope(command.scope)
    if command.intent not in T4_REQUEST_INTENTS:
        raise InvalidNarrationState("T4 only accepts create, update, or analyze_only")
    require_exact_int(
        command.expected_draft_version,
        field="expected_draft_version",
        minimum=1,
    )
    require_sha256(command.expected_content_hash, field="expected_content_hash")
    require_exact_int(
        command.expected_settings_version,
        field="expected_settings_version",
        minimum=1,
    )
    require_exact_bool(command.force_review, field="force_review")
    if require_exact_bool(
        command.explicitly_requested,
        field="explicitly_requested",
    ) is not True:
        raise InvalidNarrationState(
            "narration workflow requires an explicit author action"
        )
    require_nonempty(command.idempotency_key, field="idempotency_key")
    require_nonempty(command.actor, field="actor")
    if command.requested_at is not None and (
        type(command.requested_at) is not datetime
        or command.requested_at.tzinfo is None
    ):
        raise NarrationServiceError("requested_at must be timezone-aware")


def _snapshot_policy(snapshot: NarrationSettingsSnapshot) -> str:
    payload = snapshot.snapshot_json
    if (
        type(payload) is not dict
        or payload.get("schema_version") != SETTINGS_SNAPSHOT_SCHEMA_VERSION
        or type(payload.get("resolved_settings")) is not dict
    ):
        raise InvalidNarrationState("narration settings snapshot is malformed")
    policy = payload["resolved_settings"].get("script_review_policy")
    if policy not in {"blockers_only", "always_review"}:
        raise InvalidNarrationState("narration review policy is unknown")
    return str(policy)


def _tighten_review_snapshot(
    store: NarrationStore,
    snapshot: NarrationSettingsSnapshot,
    *,
    force_review: bool,
    scope: NarrationRequestScope,
) -> NarrationSettingsSnapshot:
    """Create an immutable request-local strict-policy view when necessary.

    ``force_review`` may only tighten blockers_only to always_review.  The
    underlying settings row and its version are never mutated.
    """

    policy = _snapshot_policy(snapshot)
    if not force_review or policy == "always_review":
        return snapshot
    payload = canonical_payload(deepcopy(snapshot.snapshot_json))
    resolved = payload["resolved_settings"]
    assert isinstance(resolved, dict)
    resolved["script_review_policy"] = "always_review"
    fingerprint = canonical_sha256(payload)
    existing = store.find_one(
        NarrationSettingsSnapshot,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        fingerprint=fingerprint,
    )
    if existing is not None:
        if existing.novel_id != snapshot.novel_id or existing.snapshot_json != payload:
            raise IdempotencyConflict("forced-review settings fingerprint collision")
        return existing
    row = NarrationSettingsSnapshot(
        id=uuid4(),
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        novel_id=snapshot.novel_id,
        schema_version=snapshot.schema_version,
        taxonomy_version=snapshot.taxonomy_version,
        fingerprint=fingerprint,
        snapshot_json=payload,
    )
    store.add(row)
    store.flush()
    return row


def _analysis_action_key(request: NarrationRequest) -> str:
    return "production-" + canonical_sha256(
        {
            "schema_version": "narration-production-analysis-action/1",
            "request_id": str(request.id),
            "request_idempotency_key": request.idempotency_key,
        }
    )


def _stored_analysis_version_key(request: NarrationRequest) -> str:
    return "analysis-" + canonical_sha256(
        {
            "request_id": str(request.id),
            "idempotency_key": _analysis_action_key(request),
        }
    )


def _version_for_request(
    store: NarrationStore,
    request: NarrationRequest,
) -> NarrationScriptVersion | None:
    if (
        request.review_script_id is None
        and request.current_review_version_id is not None
    ) or (
        request.review_script_id is not None
        and request.current_review_version_id is None
    ):
        raise InvalidNarrationState(
            "narration request review candidate pointer is incomplete"
        )
    if request.current_review_version_id is not None:
        current = require_row(
            store.get(NarrationScriptVersion, request.current_review_version_id),
            label="request review script version",
        )
        script = require_row(
            store.get(NarrationScript, current.script_id),
            label="request review script",
        )
        if (
            current.script_id != request.review_script_id
            or script.document_id != request.document_id
            or script.revision_id != request.source_revision_id
            or script.content_hash != request.source_content_hash
            or current.settings_fingerprint != request.settings_fingerprint
        ):
            raise NarrationScopeMismatch(
                "narration request review candidate provenance is inconsistent"
            )
        return current
    if request.state == "review_required":
        raise InvalidNarrationState(
            "legacy review request has no provable current script candidate"
        )
    approved = store.find_all(
        NarrationScriptVersion,
        approval_request_id=request.id,
        order_by=("version_number",),
    )
    if approved:
        return approved[-1]
    if request.document_id is None or request.source_revision_id is None:
        return None
    script = store.find_one(
        NarrationScript,
        document_id=request.document_id,
        revision_id=request.source_revision_id,
    )
    if script is None:
        return None
    return store.find_one(
        NarrationScriptVersion,
        script_id=script.id,
        idempotency_key=_stored_analysis_version_key(request),
    )


def _editions_for_request(
    store: NarrationStore,
    request_id: UUID,
) -> list[NarrationEdition]:
    rows = store.find_all(
        NarrationEdition,
        request_id=request_id,
        order_by=("id",),
    )
    if len(rows) > 1:
        raise InvalidNarrationState("one narration request unexpectedly owns multiple Editions")
    return rows


def project_workflow(
    store: NarrationStore,
    request: NarrationRequest,
    *,
    replayed: bool,
) -> NarrationWorkflowProjection:
    if request.document_id is None or request.source_revision_id is None:
        raise InvalidNarrationState("T4 workflow projection requires one document source")
    require_sha256(request.source_content_hash or "", field="source_content_hash")
    version = _version_for_request(store, request)
    editions = _editions_for_request(store, request.id)
    edition = editions[0] if editions else None
    edition_state = (
        None
        if edition is None
        else store.find_one(NarrationEditionState, edition_id=edition.id)
    )
    jobs = store.find_all(
        BackgroundJob,
        request_id=request.id,
        order_by=("id",),
    )
    if request.intent == "analyze_only" and (edition is not None or jobs):
        raise InvalidNarrationState("analyze_only acquired forbidden production rows")
    return NarrationWorkflowProjection(
        request_id=request.id,
        intent=request.intent,
        request_version=request.version,
        workflow_state=request.state,
        source_revision_id=request.source_revision_id,
        source_content_hash=request.source_content_hash or "",
        settings_fingerprint=request.settings_fingerprint,
        warning_count=(version.warning_count if version is not None else 0),
        blocker_count=(version.blocker_count if version is not None else 0),
        script_version_id=(version.id if version is not None else None),
        edition_id=(edition.id if edition is not None else None),
        current_manifest_revision=(
            edition_state.current_manifest_revision
            if edition_state is not None
            else None
        ),
        job_ids=tuple(job.id for job in jobs),
        replayed=replayed,
    )


def project_edition(
    store: NarrationStore,
    edition: NarrationEdition,
) -> NarrationEditionProjection:
    snapshot = require_row(
        store.get(NarrationSettingsSnapshot, edition.settings_snapshot_id),
        label="Edition settings snapshot",
    )
    segments = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    if not segments or [item.ordinal for item in segments] != list(range(len(segments))):
        raise InvalidNarrationState("Edition has an incomplete segment projection")
    state = store.find_one(NarrationEditionState, edition_id=edition.id)
    jobs = store.find_all(
        BackgroundJob,
        request_id=edition.request_id,
        order_by=("id",),
    )
    counts = {
        name: sum(item.render_state == name for item in segments)
        for name in ("pending", "queued", "rendering", "ready", "failed")
    }
    return NarrationEditionProjection(
        edition_id=edition.id,
        request_id=edition.request_id,
        novel_id=edition.novel_id,
        document_id=edition.document_id,
        script_version_id=edition.script_version_id,
        settings_fingerprint=snapshot.fingerprint,
        edition_fingerprint=edition.edition_fingerprint,
        state=edition.state,
        segment_count=len(segments),
        pending_segment_count=counts["pending"],
        queued_segment_count=counts["queued"],
        rendering_segment_count=counts["rendering"],
        ready_segment_count=counts["ready"],
        failed_segment_count=counts["failed"],
        current_manifest_revision=(
            state.current_manifest_revision if state is not None else None
        ),
        job_ids=tuple(job.id for job in jobs),
    )


def _voice_resolution(
    store: NarrationStore,
    *,
    novel_id: UUID,
    segment: NarrationSegment,
    contract_segment: SegmentContract,
    settings_snapshot: NarrationSettingsSnapshot,
) -> EditionSegmentInput:
    casting = contract_segment.casting
    target = casting.final_target
    if target is None or casting.origin is CastingDecisionOrigin.NOT_APPLICABLE:
        raise InvalidNarrationState(
            "a production Edition segment requires one resolved voice target"
        )

    slot_id: UUID | None = None
    authority: dict[str, object]
    if target.kind is CastingTargetKind.PROFILE:
        resolved = settings_snapshot.snapshot_json.get("resolved_settings")
        if type(resolved) is not dict:
            raise InvalidNarrationState("settings narrator authority is malformed")
        raw_profile_id = resolved.get("narrator_profile_id")
        raw_version_id = resolved.get("narrator_version_id")
        if raw_profile_id is None or raw_version_id is None:
            raise InvalidNarrationState("narrator voice is not configured")
        try:
            profile_id = UUID(str(raw_profile_id))
            voice_version_id = UUID(str(raw_version_id))
        except ValueError as error:
            raise InvalidNarrationState("narrator voice identity is invalid") from error
        if target.profile_id != profile_id:
            raise NarrationScopeMismatch("script narrator differs from frozen settings")
        authority = {
            "kind": "narrator_setting",
            "settings_fingerprint": settings_snapshot.fingerprint,
        }
    elif target.kind is CastingTargetKind.CHARACTER_BINDING:
        binding = require_row(
            store.get(CharacterVoiceBinding, target.binding_id, for_update=True),
            label="character voice binding",
        )
        if (
            binding.novel_id != novel_id
            or binding.character_id != target.character_id
            or binding.profile_id is None
            or binding.voice_version_id is None
            or binding.binding_policy not in {"dedicated", "inherited"}
        ):
            raise NarrationScopeMismatch("character voice binding is no longer usable")
        profile_id = binding.profile_id
        voice_version_id = binding.voice_version_id
        authority = {
            "kind": "character_binding",
            "binding_id": str(binding.id),
            "binding_version": binding.version,
        }
    elif target.kind is CastingTargetKind.ANONYMOUS_BINDING:
        anonymous = require_row(
            store.get(AnonymousSpeaker, target.anonymous_speaker_id, for_update=True),
            label="anonymous speaker",
        )
        if (
            anonymous.novel_id != novel_id
            or anonymous.lifecycle_state != "active"
            or anonymous.voice_version_id is None
        ):
            raise NarrationScopeMismatch("anonymous speaker voice is no longer usable")
        voice_version_id = anonymous.voice_version_id
        voice = require_row(
            store.get(VoiceProfileVersion, voice_version_id, for_update=True),
            label="anonymous speaker voice version",
        )
        profile_id = voice.profile_id
        slot_id = anonymous.slot_id
        authority = {
            "kind": "anonymous_binding",
            "anonymous_speaker_id": str(anonymous.id),
        }
    elif target.kind is CastingTargetKind.GENERIC_SLOT:
        slot = require_row(
            store.get(GenericVoiceSlot, target.slot_id, for_update=True),
            label="generic voice slot",
        )
        pool = require_row(
            store.get(GenericVoicePool, target.pool_id, for_update=True),
            label="generic voice pool",
        )
        if (
            slot.pool_id != pool.id
            or pool.novel_id != novel_id
            or pool.status != "active"
            or type(slot.enabled) is not bool
            or not slot.enabled
        ):
            raise NarrationScopeMismatch("generic voice slot is no longer usable")
        voice_version_id = slot.voice_version_id
        voice = require_row(
            store.get(VoiceProfileVersion, voice_version_id, for_update=True),
            label="generic slot voice version",
        )
        profile_id = voice.profile_id
        slot_id = slot.id
        authority = {
            "kind": "generic_slot",
            "pool_id": str(pool.id),
            "pool_version": pool.version_number,
            "slot_id": str(slot.id),
        }
    else:  # pragma: no cover - enum exhaustiveness guard
        raise InvalidNarrationState("unsupported casting target")

    voice = require_row(
        store.get(VoiceProfileVersion, voice_version_id, for_update=True),
        label="resolved voice version",
    )
    if voice.profile_id != profile_id:
        raise NarrationScopeMismatch("resolved profile/version relation changed")
    profile = require_row(
        store.get(VoiceProfile, profile_id, for_update=True),
        label="resolved voice profile",
    )
    if profile.novel_id != novel_id:
        raise NarrationScopeMismatch("resolved voice profile belongs to another novel")
    resolution = {
        "contract_version": NARRATION_EDITION_RESOLUTION_VERSION,
        "casting": canonical_payload(segment.casting_json),
        "profile_id": str(profile_id),
        "voice_version_id": str(voice_version_id),
        "slot_id": str(slot_id) if slot_id else None,
        "authority": authority,
        "voice_identity": {
            "profile_id": str(profile_id),
            "voice_version_id": str(voice_version_id),
            "display_name": profile.name,
            "source_type": voice.source_type,
            "preset_id": voice.preset_key if voice.source_type == "preset" else None,
        },
    }
    return EditionSegmentInput(
        segment_id=segment.id,
        ordinal=segment.ordinal,
        profile_id=profile_id,
        voice_version_id=voice_version_id,
        slot_id=slot_id,
        resolution_json=resolution,
        gap_after_ms=segment.pause_after_ms,
    )


def _edition_inputs(
    store: NarrationStore,
    *,
    contract: NarrationScriptContract,
    settings_snapshot: NarrationSettingsSnapshot,
    authority_lock: VoiceAuthorityLock,
    request_id: UUID,
) -> tuple[EditionSegmentInput, ...]:
    require_voice_authority_lock(
        authority_lock,
        request_id=request_id,
        contract_version_id=contract.script_version_id,
    )
    rows = store.find_all(
        NarrationSegment,
        script_version_id=contract.script_version_id,
        order_by=("ordinal",),
        for_update=True,
    )
    if [row.id for row in rows] != [item.segment_id for item in contract.segments]:
        raise InvalidNarrationState("approved script segment rows changed")
    return tuple(
        _voice_resolution(
            store,
            novel_id=contract.novel_id,
            segment=row,
            contract_segment=contract_segment,
            settings_snapshot=settings_snapshot,
        )
        for row, contract_segment in zip(rows, contract.segments, strict=True)
    )


def _latest_pronunciation_profile(
    store: NarrationStore,
    *,
    novel_id: UUID,
) -> PronunciationProfile | None:
    rows = store.find_all(
        PronunciationProfile,
        novel_id=novel_id,
        order_by=("version_number",),
        for_update=True,
    )
    return rows[-1] if rows else None


def _replay_request(
    store: NarrationStore,
    existing: NarrationRequest,
    command: StartNarrationWorkflow,
) -> NarrationRequest:
    if (
        existing.document_id != command.document_id
        or existing.intent != command.intent
        or existing.source_revision_id is None
        or existing.source_content_hash != command.expected_content_hash
        or existing.force_review is not command.force_review
    ):
        raise IdempotencyConflict("idempotency key was already used for another request")
    return create_request(
        store,
        CreateNarrationRequest(
            novel_id=existing.novel_id,
            document_id=existing.document_id,
            source_revision_id=existing.source_revision_id,
            source_content_hash=existing.source_content_hash,
            intent=existing.intent,
            idempotency_key=existing.idempotency_key,
            settings_fingerprint=existing.settings_fingerprint,
            force_review=existing.force_review,
            effective_policy=existing.effective_policy,
            expected_draft_version=command.expected_draft_version,
            expected_settings_version=command.expected_settings_version,
            explicit_generation_intent_at=existing.explicit_generation_intent_at,
            explicit_generation_actor=existing.explicit_generation_actor,
            scope=command.scope,
        ),
    )


def _continue_request(
    store: NarrationStore,
    queue: RenderJobQueue,
    *,
    request: NarrationRequest,
    settings_snapshot: NarrationSettingsSnapshot,
    command: StartNarrationWorkflow,
    policy: NarrationProductionPolicy,
    replayed: bool,
) -> NarrationWorkflowProjection:
    if request.state in {
        "queued",
        "rendering",
        "partial_ready",
        "ready",
        "cancel_requested",
        "cancelled",
        "failed",
        "review_required",
    }:
        return project_workflow(store, request, replayed=replayed)

    if request.source_revision_id is None:
        raise InvalidNarrationState("request source revision identity is missing")
    contract = analyze_narration_script(
        store,
        AnalyzeNarrationScript(
            request_id=request.id,
            document_id=command.document_id,
            revision_id=request.source_revision_id,
            content_hash=request.source_content_hash or "",
            idempotency_key=_analysis_action_key(request),
        ),
    )
    request = require_row(
        store.get(NarrationRequest, request.id, for_update=True),
        label="narration request",
    )
    if request.intent == "analyze_only":
        return project_workflow(store, request, replayed=replayed)
    if contract.state is not ScriptVersionState.APPROVED:
        return project_workflow(store, request, replayed=replayed)
    return produce_approved_request(
        store,
        queue,
        request=request,
        contract=contract,
        settings_snapshot=settings_snapshot,
        policy=policy,
        replayed=replayed,
        scope=command.scope,
    )


def produce_approved_request(
    store: NarrationStore,
    queue: RenderJobQueue,
    *,
    request: NarrationRequest,
    contract: NarrationScriptContract,
    settings_snapshot: NarrationSettingsSnapshot,
    policy: NarrationProductionPolicy,
    replayed: bool,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> NarrationWorkflowProjection:
    """Create the unique production graph for an already-approved candidate.

    The caller owns one short database transaction.  This function performs no
    model, network, file, Sidecar, or FFmpeg call and is shared by automatic
    approval and the explicit owner-review path.
    """

    require_fixed_scope(scope)
    if type(contract) is not NarrationScriptContract:
        raise NarrationServiceError("approved production requires a typed script")
    if type(policy) is not NarrationProductionPolicy:
        raise NarrationServiceError("approved production requires a frozen policy")
    if contract.state is not ScriptVersionState.APPROVED:
        raise InvalidNarrationState("production script is not approved")
    expected_request = (
        request.id,
        request.version,
        request.document_id,
        request.novel_id,
        request.review_script_id,
        request.current_review_version_id,
        request.state,
    )
    request, _document, mutex = lock_request_document_mutex(
        store,
        request.id,
        expected_document_id=contract.document_id,
        expected_novel_id=contract.novel_id,
    )
    locked_request = (
        request.id,
        request.version,
        request.document_id,
        request.novel_id,
        request.review_script_id,
        request.current_review_version_id,
        request.state,
    )
    if locked_request != expected_request:
        raise StaleNarrationInput(
            "approved request changed before production locks were acquired"
        )
    version = require_row(
        store.get(
            NarrationScriptVersion,
            contract.script_version_id,
            for_update=True,
        ),
        label="script version",
    )
    if (
        version.script_id != contract.script_id
        or version.version_number != contract.version_number
        or version.state != contract.state.value
        or version.immutable_hash != contract.immutable_hash
        or version.settings_fingerprint != contract.settings_fingerprint
    ):
        raise StaleNarrationInput(
            "approved script version changed before production"
        )
    if request.intent == "analyze_only" or not request.allows_edition:
        raise InvalidNarrationState("analyze_only request cannot continue production")
    if request.state not in {"analyzed", "review_required"}:
        existing = _editions_for_request(store, request.id)
        if request.state in {
            "queued",
            "rendering",
            "partial_ready",
            "ready",
            "cancel_requested",
            "cancelled",
            "failed",
        } and existing:
            return project_workflow(store, request, replayed=True)
        raise InvalidNarrationState(
            "approved generation request is not ready to enter production"
        )
    if (
        request.review_script_id != contract.script_id
        or request.current_review_version_id != contract.script_version_id
        or request.document_id != contract.document_id
        or request.source_revision_id != contract.revision_id
        or request.source_content_hash != contract.source_content_hash
        or request.settings_fingerprint != contract.settings_fingerprint
        or request.novel_id != contract.novel_id
    ):
        raise NarrationScopeMismatch(
            "approved script is not the request current review candidate"
        )
    if (
        settings_snapshot.owner_id != scope.owner_id
        or settings_snapshot.workspace_id != scope.workspace_id
        or settings_snapshot.novel_id != request.novel_id
        or settings_snapshot.fingerprint != request.settings_fingerprint
    ):
        raise NarrationScopeMismatch(
            "approved request settings snapshot provenance is inconsistent"
        )
    if _editions_for_request(store, request.id):
        raise InvalidNarrationState(
            "reviewable request already owns an Edition"
        )

    authority_lock = lock_voice_authorities(
        store,
        mutex=mutex,
        contract=contract,
        settings_snapshot=settings_snapshot,
        include_narrator=any(
            segment.casting.final_target is not None
            and segment.casting.final_target.kind is CastingTargetKind.PROFILE
            for segment in contract.segments
        ),
    )

    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=request.novel_id,
        actor=policy.created_actor,
        scope=scope,
    )
    pronunciation = _latest_pronunciation_profile(store, novel_id=request.novel_id)
    edition = create_edition(
        store,
        CreateEdition(
            novel_id=request.novel_id,
            document_id=contract.document_id,
            request_id=request.id,
            script_version_id=contract.script_version_id,
            settings_snapshot_id=settings_snapshot.id,
            pronunciation_profile_id=(pronunciation.id if pronunciation else None),
            tts_fingerprint=policy.tts_fingerprint,
            tokenizer_fingerprint=policy.tokenizer_fingerprint,
            normalizer_fingerprint=policy.normalizer_fingerprint,
            postprocess_fingerprint=policy.postprocess_fingerprint,
            buffer_policy_version=policy.buffer_policy_version,
            created_actor=policy.created_actor,
            digest_keyring=policy.digest_keyring,
            segments=_edition_inputs(
                store,
                contract=contract,
                settings_snapshot=settings_snapshot,
                authority_lock=authority_lock,
                request_id=request.id,
            ),
        ),
    )
    render_plan = plan_edition_renders(
        store,
        queue,
        edition_id=edition.id,
        digest_keyring=policy.digest_keyring,
        base_priority=policy.base_priority,
        max_attempts=policy.max_attempts,
    )
    if not render_plan.job_ids:
        finalize_ready_cache_only_edition(
            store,
            edition_id=edition.id,
            request_id=request.id,
            expected_request_version=request.version,
            expected_manifest_revision=0,
            expected_manifest_state_version=0,
            actor=policy.created_actor,
            scope=scope,
            digest_keyring=policy.digest_keyring,
        )
    return project_workflow(store, request, replayed=replayed)


def orchestrate_narration_request(
    store: NarrationStore,
    queue: RenderJobQueue,
    command: StartNarrationWorkflow,
    policy: NarrationProductionPolicy,
) -> NarrationWorkflowProjection:
    """Execute the frozen T4-A sequence in the caller's current transaction."""

    _validate_start(command)
    if type(policy) is not NarrationProductionPolicy:
        raise NarrationServiceError("policy must be NarrationProductionPolicy")
    existing = store.find_one(
        NarrationRequest,
        owner_id=command.scope.owner_id,
        workspace_id=command.scope.workspace_id,
        idempotency_key=command.idempotency_key,
        for_update=True,
    )
    if existing is not None:
        request = _replay_request(store, existing, command)
        settings_snapshot = require_row(
            store.find_one(
                NarrationSettingsSnapshot,
                owner_id=command.scope.owner_id,
                workspace_id=command.scope.workspace_id,
                fingerprint=request.settings_fingerprint,
            ),
            label="request settings snapshot",
        )
        return _continue_request(
            store,
            queue,
            request=request,
            settings_snapshot=settings_snapshot,
            command=command,
            policy=policy,
            replayed=True,
        )

    document = require_row(store.get(Document, command.document_id), label="document")
    require_local_novel(store, document.novel_id)
    source = create_tts_snapshot(
        store,
        CreateTtsSnapshot(
            novel_id=document.novel_id,
            document_id=document.id,
            expected_draft_version=command.expected_draft_version,
            expected_content_hash=command.expected_content_hash,
            scope=command.scope,
        ),
    )
    base_snapshot = create_settings_snapshot(
        store,
        CreateSettingsSnapshot(
            novel_id=document.novel_id,
            settings_version=command.expected_settings_version,
            scope=command.scope,
        ),
    )
    settings_snapshot = _tighten_review_snapshot(
        store,
        base_snapshot,
        force_review=command.force_review,
        scope=command.scope,
    )
    effective_policy = _snapshot_policy(settings_snapshot)
    generation = command.intent != "analyze_only"
    request = create_request(
        store,
        CreateNarrationRequest(
            novel_id=document.novel_id,
            document_id=document.id,
            source_revision_id=source.id,
            source_content_hash=source.content_hash,
            intent=command.intent,
            idempotency_key=command.idempotency_key,
            settings_fingerprint=settings_snapshot.fingerprint,
            force_review=command.force_review,
            effective_policy=effective_policy,
            expected_draft_version=command.expected_draft_version,
            expected_settings_version=command.expected_settings_version,
            explicit_generation_intent_at=(
                (command.requested_at or utc_now()) if generation else None
            ),
            explicit_generation_actor=(command.actor if generation else None),
            scope=command.scope,
        ),
    )
    return _continue_request(
        store,
        queue,
        request=request,
        settings_snapshot=settings_snapshot,
        command=command,
        policy=policy,
        replayed=False,
    )


class SqlAlchemyNarrationWorkflowService:
    """Request-scoped unit-of-work adapter used by the HTTP facade."""

    def __init__(self, session: Session, policy: NarrationProductionPolicy) -> None:
        if not isinstance(session, Session):
            raise TypeError("narration workflow service requires a SQLAlchemy Session")
        if type(policy) is not NarrationProductionPolicy:
            raise TypeError("narration workflow service requires a production policy")
        self.session = session
        self.store = SqlAlchemyNarrationStore(session)
        self.queue = SqlAlchemyRenderJobQueue(session)
        self.policy = policy

    def start(self, command: StartNarrationWorkflow) -> NarrationWorkflowProjection:
        if self.session.in_transaction():
            raise RuntimeError("narration workflow received a pre-opened transaction")
        with self.session.begin():
            if command.intent == "update":
                from .document_state import create_explicit_narration_update_intent

                create_explicit_narration_update_intent(
                    self.store,
                    document_id=command.document_id,
                    expected_draft_version=command.expected_draft_version,
                    expected_content_hash=command.expected_content_hash,
                    expected_settings_version=command.expected_settings_version,
                    force_review=command.force_review,
                    idempotency_key=command.idempotency_key,
                    explicitly_requested=command.explicitly_requested,
                    scope=command.scope,
                )
            return orchestrate_narration_request(
                self.store,
                self.queue,
                command,
                self.policy,
            )

    def get_request(self, request_id: UUID) -> NarrationWorkflowProjection:
        if self.session.in_transaction():
            raise RuntimeError("narration request read received a pre-opened transaction")
        with self.session.begin():
            request = require_row(
                self.store.get(NarrationRequest, request_id),
                label="narration request",
            )
            scope = NarrationRequestScope.fixed_local()
            if request.owner_id != scope.owner_id or request.workspace_id != scope.workspace_id:
                raise NarrationScopeMismatch("narration request is outside fixed scope")
            require_local_novel(self.store, request.novel_id)
            return project_workflow(self.store, request, replayed=False)

    def get_edition(self, edition_id: UUID) -> NarrationEditionProjection:
        if self.session.in_transaction():
            raise RuntimeError("narration Edition read received a pre-opened transaction")
        with self.session.begin():
            edition = require_row(
                self.store.get(NarrationEdition, edition_id),
                label="narration Edition",
            )
            scope = NarrationRequestScope.fixed_local()
            if edition.owner_id != scope.owner_id or edition.workspace_id != scope.workspace_id:
                raise NarrationScopeMismatch("narration Edition is outside fixed scope")
            require_local_novel(self.store, edition.novel_id)
            return project_edition(self.store, edition)

    def get_edition_voice_identities(
        self,
        edition_id: UUID,
    ) -> tuple[NarrationEditionVoiceIdentityProjection, ...]:
        if self.session.in_transaction():
            raise RuntimeError("narration Edition identity read received a pre-opened transaction")
        with self.session.begin():
            edition = require_row(
                self.store.get(NarrationEdition, edition_id),
                label="narration Edition",
            )
            scope = NarrationRequestScope.fixed_local()
            if edition.owner_id != scope.owner_id or edition.workspace_id != scope.workspace_id:
                raise NarrationScopeMismatch("narration Edition is outside fixed scope")
            require_local_novel(self.store, edition.novel_id)
            return project_edition_voice_identities(self.store, edition)


__all__ = [
    "NARRATION_EDITION_RESOLUTION_VERSION",
    "NarrationEditionProjection",
    "NarrationEditionVoiceIdentityProjection",
    "NarrationProductionPolicy",
    "NarrationWorkflowProjection",
    "SqlAlchemyNarrationWorkflowService",
    "StartNarrationWorkflow",
    "orchestrate_narration_request",
    "produce_approved_request",
    "project_edition",
    "project_edition_voice_identities",
    "project_workflow",
]
