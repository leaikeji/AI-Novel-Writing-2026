"""Persistent, request-scoped owner actions for narration script review.

The caller owns the surrounding transaction.  This module performs no model,
network, media, Edition, or commit operation.  A segment correction creates a
new immutable typed script version, records one immutable action ledger row,
and advances only the request's current-review pointer/version CAS.

Partial reanalysis deliberately remains fail-closed: the shared analyzer does
not yet expose a replayable, subset-scoped authority boundary.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, fields, replace
from datetime import datetime
from types import SimpleNamespace
from uuid import RFC_4122, UUID, uuid4, uuid5

from ..models import (
    AnonymousSpeaker,
    CharacterVoiceBinding,
    Document,
    DocumentRevision,
    GenericVoiceSlot,
    NarrationRequest,
    NarrationScene,
    NarrationScript,
    NarrationScriptIssue,
    NarrationScriptReviewActionRecord,
    NarrationScriptVersion,
    NarrationSegment,
    NovelCharacter,
    VoiceProfile,
)

from .contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    SPEAKER_CORRECTION_ISSUE_CODES,
    ConfidenceLevel,
    ReviewIssueSeverity,
)
from .confidence import (
    InheritanceAuditStamp,
    OverrideInheritanceAuthority,
    OverrideInheritanceTarget,
    decide_override_inheritance,
    manual_override_source,
    segment_anchor_uniqueness,
    segment_inheritance_anchors,
)
from .script_contracts import (
    SOURCE_BOUND_SEGMENT_KINDS,
    AnonymousScopeKind,
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    NarrationScriptContract,
    OverrideKind,
    OverrideProvenance,
    SceneContract,
    ScriptAuthorityContext,
    ScriptContractError,
    ScriptApprovalKind,
    ScriptVersionState,
    SegmentContract,
    SpeakerKind,
    SpeakerRef,
    derive_scene_id,
    derive_segment_id,
    derive_source_block_key,
    script_contract_from_dict,
    script_contract_to_dict,
    script_immutable_hash,
    script_immutable_payload,
    speaker_target_hash,
)
from .script_versions import (
    SCRIPT_ANALYZER_FINGERPRINT,
    SCRIPT_RULES_FINGERPRINT,
    ScriptVersionAllocation,
    _has_deterministic_typed_identity,
    _persisted_version_hash,
    _settings_snapshot_authority,
    _typed_contract_payload_from_rows,
    _verify_casting_target,
)
from .requests import advance_request_state
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    StaleNarrationInput,
    canonical_payload,
    canonical_sha256,
    require_exact_int,
    require_local_novel,
    require_nonempty,
    require_row,
    require_sha256,
    require_usable_voice,
    utc_now,
)


REVIEW_ACTION_REQUEST_VERSION = "narration-review-action-request/1"
INHERITED_ANALYSIS_ACTION_VERSION = "narration-inherited-analysis-action/1"

@dataclass(frozen=True, slots=True)
class CorrectReviewSegment:
    """Trusted internal command after server-side speaker/casting resolution.

    ``speaker`` and ``casting`` are not client authority.  The HTTP adapter
    must derive and authorize both against current project rows before it
    constructs this command.
    """

    request_id: UUID
    script_version_id: UUID
    segment_id: UUID
    expected_request_version: int
    expected_version_number: int
    expected_immutable_hash: str
    expected_local_hash: str
    idempotency_key: str
    actor_id: str
    speaker: SpeakerRef
    casting: CastingDecision
    spoken_text: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReviewSegmentCorrectionResult:
    action_id: UUID
    request_id: UUID
    request_hash: str
    request_version_before: int
    request_version_after: int
    script_id: UUID
    parent_version_id: UUID
    result_version_id: UUID
    contract: NarrationScriptContract
    replayed: bool


@dataclass(frozen=True, slots=True)
class ReanalyzeReviewSegments:
    request_id: UUID
    script_version_id: UUID
    segment_ids: tuple[UUID, ...]
    expected_request_version: int
    expected_version_number: int
    expected_immutable_hash: str
    idempotency_key: str
    actor_id: str


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if (
        type(value) is not UUID
        or value.variant != RFC_4122
        or value.version not in {1, 2, 3, 4, 5}
    ):
        raise NarrationServiceError(
            f"{field_name} must be an RFC-4122 UUID v1-v5"
        )
    return value


def _require_nfc_text(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> str:
    if type(value) is not str or len(value) < minimum:
        raise NarrationServiceError(f"{field_name} has an invalid length")
    if maximum is not None and len(value) > maximum:
        raise NarrationServiceError(f"{field_name} exceeds {maximum} characters")
    if value != unicodedata.normalize("NFC", value):
        raise NarrationServiceError(f"{field_name} must be Unicode NFC")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise NarrationServiceError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


def _casting_target_payload(target: CastingTargetRef) -> dict[str, object]:
    return {
        "kind": target.kind.value,
        "binding_id": str(target.binding_id) if target.binding_id else None,
        "character_id": str(target.character_id) if target.character_id else None,
        "anonymous_speaker_id": (
            str(target.anonymous_speaker_id)
            if target.anonymous_speaker_id
            else None
        ),
        "pool_id": str(target.pool_id) if target.pool_id else None,
        "slot_id": str(target.slot_id) if target.slot_id else None,
        "profile_id": str(target.profile_id) if target.profile_id else None,
    }


def _speaker_payload(speaker: SpeakerRef) -> dict[str, object]:
    return {
        "kind": speaker.kind.value,
        "character_id": str(speaker.character_id) if speaker.character_id else None,
        "anonymous_speaker_id": (
            str(speaker.anonymous_speaker_id)
            if speaker.anonymous_speaker_id
            else None
        ),
        "group_key": speaker.group_key,
    }


def _casting_payload(casting: CastingDecision) -> dict[str, object]:
    return {
        "candidate_targets": [
            _casting_target_payload(target)
            for target in casting.candidate_targets
        ],
        "final_target": (
            _casting_target_payload(casting.final_target)
            if casting.final_target is not None
            else None
        ),
        "origin": casting.origin.value,
        "rule_id": str(casting.rule_id) if casting.rule_id else None,
        "rule_version": casting.rule_version,
    }


def _validate_correction(command: CorrectReviewSegment) -> tuple[str, str, str]:
    if type(command) is not CorrectReviewSegment:
        raise NarrationServiceError("command must be CorrectReviewSegment")
    for field_name, value in (
        ("request_id", command.request_id),
        ("script_version_id", command.script_version_id),
        ("segment_id", command.segment_id),
    ):
        _require_uuid(value, field_name=field_name)
    require_exact_int(
        command.expected_request_version,
        field="expected_request_version",
        minimum=1,
    )
    require_exact_int(
        command.expected_version_number,
        field="expected_version_number",
        minimum=1,
    )
    require_sha256(
        command.expected_immutable_hash,
        field="expected_immutable_hash",
    )
    require_sha256(command.expected_local_hash, field="expected_local_hash")
    key = require_nonempty(command.idempotency_key, field="idempotency_key")
    if len(key) > 128:
        raise NarrationServiceError("idempotency_key exceeds 128 characters")
    actor_id = _require_nfc_text(
        require_nonempty(command.actor_id, field="actor_id"),
        field_name="actor_id",
        minimum=1,
        maximum=120,
    )
    reason = _require_nfc_text(
        require_nonempty(command.reason, field="reason"),
        field_name="reason",
        minimum=1,
        maximum=400,
    )
    spoken_text = _require_nfc_text(
        command.spoken_text,
        field_name="spoken_text",
        maximum=4000,
    )
    if type(command.speaker) is not SpeakerRef:
        raise NarrationServiceError("speaker must be SpeakerRef")
    if command.speaker.kind is SpeakerKind.UNKNOWN:
        raise InvalidNarrationState("manual correction cannot select unknown speaker")
    if type(command.casting) is not CastingDecision:
        raise NarrationServiceError("casting must be CastingDecision")
    if (
        command.casting.final_target is None
        or command.casting.origin
        in {
            CastingDecisionOrigin.UNRESOLVED,
            CastingDecisionOrigin.NOT_APPLICABLE,
            CastingDecisionOrigin.CASTING_RULE,
        }
    ):
        raise InvalidNarrationState(
            "manual correction requires a replayable resolved casting target"
        )
    return key, actor_id, reason


def _request_hash(
    command: CorrectReviewSegment,
    *,
    actor_id: str,
    reason: str,
) -> str:
    return canonical_sha256(
        {
            "contract_version": REVIEW_ACTION_REQUEST_VERSION,
            "action_kind": "patch_segment",
            "request_id": str(command.request_id),
            "script_version_id": str(command.script_version_id),
            "segment_id": str(command.segment_id),
            "expected_request_version": command.expected_request_version,
            "expected_version_number": command.expected_version_number,
            "expected_immutable_hash": command.expected_immutable_hash,
            "expected_local_hash": command.expected_local_hash,
            "actor_id": actor_id,
            "speaker": _speaker_payload(command.speaker),
            "casting": _casting_payload(command.casting),
            "spoken_text": command.spoken_text,
            "reason": reason,
        }
    )


def _action_id(idempotency_key: str) -> UUID:
    return uuid5(
        LOCAL_WORKSPACE_ID,
        f"narration-review-action:{LOCAL_OWNER_ID}:{idempotency_key}",
    )


def inherited_analysis_action_identity(
    *, request_id: UUID, analysis_idempotency_key: str
) -> tuple[str, UUID]:
    """Derive the stable ledger key/id before inheritance provenance is built."""

    _require_uuid(request_id, field_name="request_id")
    analysis_key = require_nonempty(
        analysis_idempotency_key,
        field="analysis_idempotency_key",
    )
    key = "analysis-inherit-" + canonical_sha256(
        {
            "contract_version": INHERITED_ANALYSIS_ACTION_VERSION,
            "request_id": str(request_id),
            "analysis_idempotency_key": analysis_key,
        }
    )
    return key, _action_id(key)


def _inherited_analysis_request_hash(
    *,
    request_id: UUID,
    script_id: UUID,
    source_version_id: UUID,
    result_version_id: UUID,
    result_immutable_hash: str,
    action_key: str,
    actor_id: str,
    provenances: frozenset[OverrideProvenance],
) -> str:
    def provenance_payload(provenance: OverrideProvenance) -> dict[str, object]:
        return {
            "contract_version": provenance.contract_version,
            "kind": provenance.kind.value,
            "action_id": str(provenance.action_id),
            "owner_actor_id": provenance.owner_actor_id,
            "recorded_at": provenance.recorded_at.isoformat(),
            "source_script_version_id": str(
                provenance.source_script_version_id
            ),
            "source_segment_id": str(provenance.source_segment_id),
            "source_immutable_hash": provenance.source_immutable_hash,
            "source_local_hash": provenance.source_local_hash,
            "source_anchor_before_hash": provenance.source_anchor_before_hash,
            "source_anchor_after_hash": provenance.source_anchor_after_hash,
            "speaker_target_hash": provenance.speaker_target_hash,
        }

    return canonical_sha256(
        {
            "contract_version": INHERITED_ANALYSIS_ACTION_VERSION,
            "request_id": str(request_id),
            "script_id": str(script_id),
            "source_version_id": str(source_version_id),
            "result_version_id": str(result_version_id),
            "result_immutable_hash": result_immutable_hash,
            "action_key": action_key,
            "actor_id": actor_id,
            "provenances": sorted(
                canonical_sha256(provenance_payload(provenance))
                for provenance in provenances
            ),
        }
    )


def _lineage_rows(
    store: NarrationStore,
    *,
    script_id: UUID,
    current_version_id: UUID,
    parent_version_id: UUID | None,
) -> tuple[set[UUID], set[UUID]]:
    version_ids = {current_version_id}
    ancestor_scene_ids: set[UUID] = set()
    cursor = parent_version_id
    while cursor is not None:
        if cursor in version_ids:
            raise InvalidNarrationState("script version lineage contains a cycle")
        version_ids.add(cursor)
        row = require_row(
            store.get(NarrationScriptVersion, cursor),
            label="script version ancestor",
        )
        if row.script_id != script_id:
            raise NarrationScopeMismatch(
                "script version ancestor belongs to another script"
            )
        ancestor_scene_ids.update(
            scene.id
            for scene in store.find_all(
                NarrationScene,
                script_version_id=row.id,
            )
        )
        cursor = row.parent_version_id
    return version_ids, ancestor_scene_ids


def _require_final_voice_usable(
    store: NarrationStore,
    *,
    novel_id: UUID,
    casting: CastingDecision,
    resolved_settings: dict[str, object],
) -> None:
    target = casting.final_target
    if target is None:
        return
    voice_version_id: UUID | None
    if target.kind is CastingTargetKind.CHARACTER_BINDING:
        binding = require_row(
            store.get(CharacterVoiceBinding, target.binding_id),
            label="character voice binding",
        )
        voice_version_id = binding.voice_version_id
    elif target.kind is CastingTargetKind.ANONYMOUS_BINDING:
        anonymous = require_row(
            store.get(AnonymousSpeaker, target.anonymous_speaker_id),
            label="anonymous speaker binding",
        )
        voice_version_id = anonymous.voice_version_id
    elif target.kind is CastingTargetKind.GENERIC_SLOT:
        slot = require_row(
            store.get(GenericVoiceSlot, target.slot_id),
            label="generic voice slot",
        )
        voice_version_id = slot.voice_version_id
    else:
        profile = require_row(
            store.get(VoiceProfile, target.profile_id),
            label="voice profile",
        )
        if casting.origin is CastingDecisionOrigin.NARRATOR_SETTING:
            raw_version_id = resolved_settings["narrator_version_id"]
            try:
                voice_version_id = UUID(str(raw_version_id))
            except (TypeError, ValueError) as error:
                raise InvalidNarrationState(
                    "settings narrator voice version identity is invalid"
                ) from error
        else:
            voice_version_id = profile.current_version_id
    if voice_version_id is None:
        raise InvalidNarrationState(
            "resolved manual casting target has no voice version"
        )
    require_usable_voice(
        store,
        voice_version_id,
        novel_id=novel_id,
    )


def _review_authority(
    store: NarrationStore,
    candidate: object,
    *,
    pending_provenances: frozenset[OverrideProvenance] = frozenset(),
    require_current_voices: bool = False,
) -> ScriptAuthorityContext:
    """Rebuild the narrow manual-review authority from persisted rows."""

    require_local_novel(store, candidate.novel_id)
    if (
        candidate.analyzer_fingerprint != SCRIPT_ANALYZER_FINGERPRINT
        or candidate.rules_fingerprint != SCRIPT_RULES_FINGERPRINT
        or candidate.requested_model_fingerprint is not None
        or candidate.actual_model_fingerprint is not None
    ):
        raise InvalidNarrationState(
            "manual review only supports the frozen local analyzer authority"
        )
    if candidate.state is ScriptVersionState.REVIEW_REQUIRED:
        if candidate.approval is not None:
            raise InvalidNarrationState(
                "unapproved manual review script carries approval evidence"
            )
    elif candidate.state is ScriptVersionState.APPROVED:
        if (
            candidate.approval is None
            or candidate.approval.kind is not ScriptApprovalKind.MANUAL_AFTER_REVIEW
            or candidate.approval.actor_type.value != "owner"
        ):
            raise InvalidNarrationState(
                "approved manual review script lacks owner approval authority"
            )
    else:
        raise InvalidNarrationState(
            "manual review authority only supports review_required or approved scripts"
        )
    resolved_settings = _settings_snapshot_authority(
        store,
        novel_id=candidate.novel_id,
        settings_fingerprint=candidate.settings_fingerprint,
        effective_policy=candidate.effective_policy,
        historical_read=not require_current_voices,
    )
    script = require_row(
        store.get(NarrationScript, candidate.script_id),
        label="narration script",
    )
    document = require_row(
        store.get(Document, candidate.document_id),
        label="script document",
    )
    revision = require_row(
        store.get(DocumentRevision, candidate.revision_id),
        label="script revision",
    )
    if (
        script.novel_id != candidate.novel_id
        or script.document_id != candidate.document_id
        or script.revision_id != candidate.revision_id
        or script.content_hash != candidate.source_content_hash
        or document.novel_id != candidate.novel_id
        or revision.document_id != candidate.document_id
        or revision.content_hash != candidate.source_content_hash
    ):
        raise StaleNarrationInput("manual review script source guard changed")

    parent_ids: frozenset[UUID] = frozenset()
    manual_parent_ids: frozenset[UUID] = frozenset()
    if candidate.parent_version_id is not None:
        inherited_source_ids = {
            provenance.source_script_version_id
            for segment in candidate.segments
            if (
                (provenance := segment.attribution.override_provenance)
                is not None
                and provenance.kind is OverrideKind.INHERITED
                and provenance.source_script_version_id is not None
            )
        }
        parent = require_row(
            store.get(NarrationScriptVersion, candidate.parent_version_id),
            label="manual review parent version",
        )
        if parent.script_id != candidate.script_id:
            raise NarrationScopeMismatch(
                "manual review parent belongs to another script"
            )
        is_manual_correction_parent = parent.state == "review_required"
        is_inheritance_parent = (
            parent.state == "approved" and parent.id in inherited_source_ids
        )
        if not (is_manual_correction_parent or is_inheritance_parent):
            raise InvalidNarrationState(
                "manual review parent is neither a correction source nor an "
                "approved inheritance source"
            )
        parent_ids = frozenset({parent.id})
        manual_parent_ids = parent_ids

    lineage_ids, ancestor_scene_ids = _lineage_rows(
        store,
        script_id=candidate.script_id,
        current_version_id=candidate.script_version_id,
        parent_version_id=candidate.parent_version_id,
    )
    current_scene_ids = {scene.scene_id for scene in candidate.scenes}
    historical_anonymous_ids: set[UUID] = set()
    for identity in candidate.anonymous_speakers:
        row = require_row(
            store.get(AnonymousSpeaker, identity.anonymous_speaker_id),
            label="anonymous speaker",
        )
        if (
            row.novel_id != candidate.novel_id
            or row.stable_key_algorithm != identity.stable_key_algorithm
            or row.stable_key != identity.stable_key
            or row.scope_kind != identity.scope_kind.value
            or row.scope_id != identity.scope_id
            or row.display_name != identity.display_name
            or row.confidence != identity.confidence.value
        ):
            raise NarrationScopeMismatch(
                "anonymous identity snapshot is outside manual-review authority"
            )
        if (
            identity.scope_kind is AnonymousScopeKind.SCENE
            and identity.scope_id not in current_scene_ids
        ):
            if identity.scope_id not in ancestor_scene_ids:
                raise NarrationScopeMismatch(
                    "scene-scoped anonymous identity has no verified ancestor"
                )
            historical_anonymous_ids.add(identity.anonymous_speaker_id)

    character_ids: set[UUID] = set()
    group_keys: set[str] = set()
    casting_targets: set[CastingTargetRef] = set()
    provenances: set[OverrideProvenance] = set(pending_provenances)
    for segment_index, segment in enumerate(candidate.segments):
        speaker = segment.speaker
        if speaker.character_id is not None:
            character_ids.add(speaker.character_id)
        if speaker.group_key is not None:
            group_keys.add(speaker.group_key)
        character_ids.update(segment.attribution.candidate_character_ids)
        if segment.attribution.origin is AttributionOrigin.CLOUD_ASSISTED:
            raise InvalidNarrationState(
                "cloud-assisted manual review remains fail-closed"
            )
        if segment.casting.origin is CastingDecisionOrigin.CASTING_RULE:
            raise InvalidNarrationState(
                "casting-rule manual review lacks replayable rule authority"
            )
        for target in segment.casting.candidate_targets:
            _verify_casting_target(
                store,
                novel_id=candidate.novel_id,
                target=target,
                historical_read=not require_current_voices,
            )
            casting_targets.add(target)
        if segment.casting.origin is CastingDecisionOrigin.NARRATOR_SETTING:
            profile_id = resolved_settings["narrator_profile_id"]
            if (
                segment.casting.final_target is None
                or segment.casting.final_target.kind is not CastingTargetKind.PROFILE
                or str(segment.casting.final_target.profile_id) != profile_id
            ):
                raise NarrationScopeMismatch(
                    "narrator casting differs from the frozen settings snapshot"
                )
        if require_current_voices:
            _require_final_voice_usable(
                store,
                novel_id=candidate.novel_id,
                casting=segment.casting,
                resolved_settings=resolved_settings,
            )
        provenance = segment.attribution.override_provenance
        if provenance is None:
            continue
        if provenance in pending_provenances:
            provenances.add(provenance)
            continue
        if provenance.kind is OverrideKind.INHERITED:
            action = require_row(
                store.get(
                    NarrationScriptReviewActionRecord,
                    provenance.action_id,
                ),
                label="inherited review action provenance",
            )
            action_request = require_row(
                store.get(NarrationRequest, action.request_id),
                label="inherited review action request",
            )
            result_version = require_row(
                store.get(NarrationScriptVersion, action.result_version_id),
                label="inherited review action result version",
            )
            source_version_id = provenance.source_script_version_id
            if source_version_id is None:
                raise InvalidNarrationState(
                    "inherited override lacks its source version"
                )
            source_version = require_row(
                store.get(NarrationScriptVersion, source_version_id),
                label="inherited override source version",
            )
            action_provenances = frozenset(
                item_provenance
                for item in candidate.segments
                if (
                    (item_provenance := item.attribution.override_provenance)
                    is not None
                    and item_provenance.action_id == action.id
                )
            )
            expected_request_hash = _inherited_analysis_request_hash(
                request_id=action.request_id,
                script_id=candidate.script_id,
                source_version_id=source_version_id,
                result_version_id=candidate.script_version_id,
                result_immutable_hash=candidate.immutable_hash,
                action_key=action.idempotency_key,
                actor_id=action.actor_id,
                provenances=action_provenances,
            )
            if (
                action.owner_id != LOCAL_OWNER_ID
                or action.workspace_id != LOCAL_WORKSPACE_ID
                or action.novel_id != candidate.novel_id
                or action.request_allows_render is not True
                or action.script_id != candidate.script_id
                or action.action_kind != "reanalyze_segments"
                or action.parent_version_id != source_version_id
                or action.result_version_id != candidate.script_version_id
                or action.result_edition_id is not None
                or candidate.parent_version_id != source_version_id
                or result_version.script_id != action.script_id
                or result_version.parent_version_id != source_version_id
                or source_version.script_id != candidate.script_id
                or source_version.state != "approved"
                or source_version.immutable_hash
                != provenance.source_immutable_hash
                or action.actor_type != "owner"
                or action.actor_id != provenance.owner_actor_id
                or action.created_at != provenance.recorded_at
                or action.request_version_after
                != action.request_version_before + 1
                or action.request_hash != expected_request_hash
                or action_request.owner_id != action.owner_id
                or action_request.workspace_id != action.workspace_id
                or action_request.novel_id != action.novel_id
                or action_request.review_script_id != action.script_id
                or action_request.current_review_version_id
                != candidate.script_version_id
                or action_request.intent == "analyze_only"
                or action_request.explicit_generation_intent_at is None
                or action_request.explicit_generation_actor != action.actor_id
                or action_request.version < action.request_version_after
            ):
                raise InvalidNarrationState(
                    "inherited override provenance differs from its action ledger"
                )
            source_contract = load_review_script_contract(
                store,
                source_version_id,
            )
            source_segment = next(
                (
                    item
                    for item in source_contract.segments
                    if item.segment_id == provenance.source_segment_id
                ),
                None,
            )
            if source_segment is None:
                raise InvalidNarrationState(
                    "inherited override source segment is unavailable"
                )
            before_hash, after_hash = segment_inheritance_anchors(
                candidate.segments,
                segment_index,
            )
            if (
                segment.inheritance_anchor_before_hash != before_hash
                or segment.inheritance_anchor_after_hash != after_hash
            ):
                raise InvalidNarrationState(
                    "inherited override anchors differ from the current script"
                )
            source_snapshot = manual_override_source(
                source_contract,
                source_segment,
            )
            decision = decide_override_inheritance(
                source=source_snapshot,
                target=OverrideInheritanceTarget(
                    novel_id=candidate.novel_id,
                    script_version_id=candidate.script_version_id,
                    segment_id=segment.segment_id,
                    local_hash=segment.local_hash,
                    anchor_before_hash=before_hash,
                    anchor_after_hash=after_hash,
                    speaker=segment.speaker,
                    casting=segment.casting,
                    uniqueness=segment_anchor_uniqueness(
                        candidate.segments,
                        segment_index,
                    ),
                ),
                authority=OverrideInheritanceAuthority(
                    novel_id=candidate.novel_id,
                    owner_actor_id=action.actor_id,
                    authorized_sources=frozenset({source_snapshot}),
                ),
                audit=InheritanceAuditStamp(
                    action_id=action.id,
                    owner_actor_id=action.actor_id,
                    recorded_at=action.created_at,
                ),
            )
            if not decision.eligible or decision.provenance != provenance:
                raise InvalidNarrationState(
                    "inherited override no longer satisfies the frozen policy"
                )
            provenances.add(provenance)
            continue
        if provenance.kind is not OverrideKind.MANUAL_CURRENT:
            raise InvalidNarrationState(
                "inherited override replay remains fail-closed"
            )
        action = require_row(
            store.get(NarrationScriptReviewActionRecord, provenance.action_id),
            label="manual review action provenance",
        )
        action_request = require_row(
            store.get(NarrationRequest, action.request_id),
            label="manual review action request",
        )
        result_version = require_row(
            store.get(NarrationScriptVersion, action.result_version_id),
            label="manual review action result version",
        )
        if (
            action.owner_id != LOCAL_OWNER_ID
            or action.workspace_id != LOCAL_WORKSPACE_ID
            or action.novel_id != candidate.novel_id
            or action.request_allows_render is not True
            or action.script_id != candidate.script_id
            or action.action_kind != "patch_segment"
            or action.result_edition_id is not None
            or action.result_version_id not in lineage_ids
            or result_version.script_id != action.script_id
            or result_version.parent_version_id != action.parent_version_id
            or action.actor_type != "owner"
            or action.actor_id != provenance.owner_actor_id
            or action.created_at != provenance.recorded_at
            or action.request_version_after != action.request_version_before + 1
            or action_request.owner_id != action.owner_id
            or action_request.workspace_id != action.workspace_id
            or action_request.novel_id != action.novel_id
            or action_request.review_script_id != action.script_id
            or action_request.intent == "analyze_only"
            or action_request.explicit_generation_intent_at is None
            or not action_request.explicit_generation_actor
            or action_request.version < action.request_version_after
        ):
            raise InvalidNarrationState(
                "manual override provenance differs from its immutable action ledger"
            )
        require_sha256(action.request_hash, field="review action request_hash")
        provenances.add(provenance)

    for character_id in character_ids:
        character = require_row(
            store.get(NovelCharacter, character_id),
            label="manual review character",
        )
        if character.novel_id != candidate.novel_id:
            raise NarrationScopeMismatch(
                "manual review character belongs to another novel"
            )
        if require_current_voices and character.lifecycle_state != "active":
            raise NarrationScopeMismatch(
                "manual review character is outside the active novel scope"
            )

    approval = candidate.approval
    if approval is not None:
        approval_request = require_row(
            store.get(NarrationRequest, approval.request_id),
            label="manual approval request",
        )
        if (
            approval_request.owner_id != LOCAL_OWNER_ID
            or approval_request.workspace_id != LOCAL_WORKSPACE_ID
            or approval_request.novel_id != candidate.novel_id
            or approval_request.intent == "analyze_only"
            or approval_request.allows_render is not True
            or approval_request.review_script_id != candidate.script_id
            or approval_request.current_review_version_id
            != candidate.script_version_id
            or approval_request.settings_fingerprint
            != candidate.settings_fingerprint
            or approval_request.document_id != candidate.document_id
            or approval_request.source_revision_id != candidate.revision_id
            or approval_request.source_content_hash
            != candidate.source_content_hash
        ):
            raise NarrationScopeMismatch(
                "manual approval request differs from the current review authority"
            )

    return ScriptAuthorityContext(
        novel_id=candidate.novel_id,
        document_id=candidate.document_id,
        revision_id=candidate.revision_id,
        script_id=candidate.script_id,
        script_version_id=candidate.script_version_id,
        version_number=candidate.version_number,
        state=candidate.state,
        effective_policy=candidate.effective_policy,
        analyzer_fingerprint=candidate.analyzer_fingerprint,
        rules_fingerprint=candidate.rules_fingerprint,
        settings_fingerprint=candidate.settings_fingerprint,
        requested_model_fingerprint=candidate.requested_model_fingerprint,
        actual_model_fingerprint=candidate.actual_model_fingerprint,
        approval=approval,
        parent_version_ids=parent_ids,
        manual_review_parent_ids=manual_parent_ids,
        non_review_parent_ids=frozenset(),
        character_ids=frozenset(character_ids),
        anonymous_speakers=frozenset(candidate.anonymous_speakers),
        verified_historical_anonymous_ids=frozenset(historical_anonymous_ids),
        group_keys=frozenset(group_keys),
        casting_targets=frozenset(casting_targets),
        casting_rule_records=frozenset(),
        cloud_records=frozenset(),
        override_provenances=frozenset(provenances),
    )


def load_review_script_contract(
    store: NarrationStore,
    version_id: UUID,
    *,
    for_update: bool = False,
) -> NarrationScriptContract:
    """Load a ledger-backed manual review version without weakening authority."""

    version = require_row(
        store.get(NarrationScriptVersion, version_id, for_update=for_update),
        label="script version",
    )
    if not _has_deterministic_typed_identity(version):
        raise InvalidNarrationState(
            "script contains an unknown or mixed typed storage contract"
        )
    script = require_row(
        store.get(NarrationScript, version.script_id),
        label="narration script",
    )
    persisted_hash, _issues = _persisted_version_hash(
        store,
        version,
        script,
        for_update=for_update,
    )
    if persisted_hash != version.immutable_hash:
        raise StaleNarrationInput(
            "script children differ from the frozen immutable hash"
        )
    payload, candidate = _typed_contract_payload_from_rows(
        store,
        version=version,
        script=script,
    )
    authority = _review_authority(store, candidate)
    revision = require_row(
        store.get(DocumentRevision, script.revision_id),
        label="script revision",
    )
    try:
        return script_contract_from_dict(
            payload,
            authority=authority,
            source_text=revision.content_markdown,
        )
    except ScriptContractError as error:
        raise InvalidNarrationState(
            "persisted manual review script violates the frozen typed contract"
        ) from error


def _replacement_contract(
    parent: NarrationScriptContract,
    *,
    script_version_id: UUID,
    version_number: int,
    idempotency_action_id: UUID,
    actor_id: str,
    recorded_at: datetime,
    target_segment_id: UUID,
    speaker: SpeakerRef,
    casting: CastingDecision,
    spoken_text: str,
) -> tuple[NarrationScriptContract, OverrideProvenance]:
    scene_id_map: dict[UUID, UUID] = {}
    scenes: list[SceneContract] = []
    for scene in parent.scenes:
        new_id = derive_scene_id(
            script_version_id=script_version_id,
            ordinal=scene.ordinal,
            source_range=scene.source_range_utf16,
            local_hash=scene.local_hash,
        )
        scene_id_map[scene.scene_id] = new_id
        scenes.append(replace(scene, scene_id=new_id))

    target = next(
        (
            segment
            for segment in parent.segments
            if segment.segment_id == target_segment_id
        ),
        None,
    )
    if target is None:
        raise StaleNarrationInput("review segment is not in the current script")
    if target.segment_kind not in SOURCE_BOUND_SEGMENT_KINDS:
        raise InvalidNarrationState(
            "synthetic/title segments cannot be manually corrected"
        )
    target_index = next(
        index
        for index, segment in enumerate(parent.segments)
        if segment.segment_id == target.segment_id
    )
    inheritance_anchor_before_hash, inheritance_anchor_after_hash = (
        segment_inheritance_anchors(parent.segments, target_index)
    )
    provenance = OverrideProvenance(
        kind=OverrideKind.MANUAL_CURRENT,
        action_id=idempotency_action_id,
        owner_actor_id=actor_id,
        recorded_at=recorded_at,
        source_local_hash=target.local_hash,
        source_anchor_before_hash=inheritance_anchor_before_hash,
        source_anchor_after_hash=inheritance_anchor_after_hash,
        speaker_target_hash=speaker_target_hash(speaker, casting),
    )
    attribution = AttributionEvidence(
        origin=AttributionOrigin.MANUAL_OVERRIDE,
        candidate_character_ids=(
            (speaker.character_id,)
            if speaker.kind is SpeakerKind.CHARACTER
            and speaker.character_id is not None
            else ()
        ),
        override_provenance=provenance,
    )

    segment_id_map: dict[UUID, UUID] = {}
    segments: list[SegmentContract] = []
    for segment in parent.segments:
        source_block_key = derive_source_block_key(
            script_version_id=script_version_id,
            block_kind=segment.source_block_kind,
            paragraph_ordinal=segment.paragraph_ordinal,
            block_hash=segment.source_block_hash,
            anchor_before_hash=segment.anchor_before_hash,
            anchor_after_hash=segment.anchor_after_hash,
        )
        segment_id = derive_segment_id(
            script_version_id=script_version_id,
            ordinal=segment.ordinal,
            source_block_key=source_block_key,
            segment_ordinal_in_block=segment.segment_ordinal_in_block,
            local_hash=segment.local_hash,
        )
        segment_id_map[segment.segment_id] = segment_id
        changes: dict[str, object] = {
            "segment_id": segment_id,
            "scene_id": (
                scene_id_map[segment.scene_id]
                if segment.scene_id is not None
                else None
            ),
            "source_block_key": source_block_key,
        }
        if segment.segment_id == target.segment_id:
            changes.update(
                {
                    "spoken_text": spoken_text,
                    "inheritance_anchor_before_hash": (
                        inheritance_anchor_before_hash
                    ),
                    "inheritance_anchor_after_hash": (
                        inheritance_anchor_after_hash
                    ),
                    "speaker": speaker,
                    "casting": casting,
                    "confidence": ConfidenceLevel.HIGH,
                    "attribution": attribution,
                    "manual_override": True,
                }
            )
        segments.append(replace(segment, **changes))

    issues = tuple(
        sorted(
            (
                replace(
                    issue,
                    segment_id=(
                        segment_id_map[issue.segment_id]
                        if issue.segment_id is not None
                        else None
                    ),
                )
                for issue in parent.issues
                if not (
                    issue.segment_id == target.segment_id
                    and issue.code in SPEAKER_CORRECTION_ISSUE_CODES
                )
            ),
            key=lambda item: (
                item.code,
                str(item.segment_id) if item.segment_id else "",
                item.evidence_digest or "",
            ),
        )
    )
    values = {
        field.name: getattr(parent, field.name)
        for field in fields(NarrationScriptContract)
    }
    values.update(
        {
            "script_version_id": script_version_id,
            "version_number": version_number,
            "parent_version_id": parent.script_version_id,
            "state": ScriptVersionState.REVIEW_REQUIRED,
            "scenes": tuple(scenes),
            "segments": tuple(segments),
            "issues": issues,
            "warning_count": sum(
                issue.severity is ReviewIssueSeverity.WARNING for issue in issues
            ),
            "blocker_count": sum(
                issue.severity is ReviewIssueSeverity.BLOCKER for issue in issues
            ),
            "approval": None,
        }
    )
    values["immutable_hash"] = script_immutable_hash(SimpleNamespace(**values))
    return NarrationScriptContract(**values), provenance


def _persist_review_contract(
    store: NarrationStore,
    contract: NarrationScriptContract,
    *,
    idempotency_key: str,
    pending_provenances: frozenset[OverrideProvenance],
) -> NarrationScriptVersion:
    if store.get(NarrationScriptVersion, contract.script_version_id) is not None:
        raise IdempotencyConflict(
            "manual review result identity is already occupied"
        )
    if store.find_one(
        NarrationScriptVersion,
        script_id=contract.script_id,
        idempotency_key=idempotency_key,
    ) is not None:
        raise IdempotencyConflict(
            "manual review version key is already occupied"
        )
    revision = require_row(
        store.get(DocumentRevision, contract.revision_id),
        label="script revision",
    )
    authority = _review_authority(
        store,
        contract,
        pending_provenances=pending_provenances,
        require_current_voices=True,
    )
    try:
        validated = script_contract_from_dict(
            script_contract_to_dict(contract),
            authority=authority,
            source_text=revision.content_markdown,
        )
    except ScriptContractError as error:
        raise InvalidNarrationState(
            "manual review child failed server authority validation"
        ) from error
    if validated.immutable_hash != script_immutable_hash(validated):
        raise StaleNarrationInput("manual review child immutable hash changed")

    projection = script_immutable_payload(validated)
    row = NarrationScriptVersion(
        id=validated.script_version_id,
        script_id=validated.script_id,
        version_number=validated.version_number,
        parent_version_id=validated.parent_version_id,
        state=validated.state.value,
        analyzer_fingerprint=validated.analyzer_fingerprint,
        rules_fingerprint=validated.rules_fingerprint,
        settings_fingerprint=validated.settings_fingerprint,
        requested_model_fingerprint=validated.requested_model_fingerprint,
        actual_model_fingerprint=validated.actual_model_fingerprint,
        taxonomy_version=validated.taxonomy_version,
        immutable_hash=validated.immutable_hash,
        idempotency_key=idempotency_key,
        warning_count=validated.warning_count,
        blocker_count=validated.blocker_count,
        effective_policy=validated.effective_policy.value,
        approval_kind=None,
        approval_request_id=None,
        approval_request_allows_edition=None,
        approved_actor_type=None,
        approved_actor_id=None,
        approved_at=None,
    )
    store.add(row)
    store.flush()
    scene_payloads = projection["scenes"]
    segment_payloads = projection["segments"]
    if type(scene_payloads) is not list or type(segment_payloads) is not list:
        raise InvalidNarrationState("manual review projection is not materialized")
    for item in scene_payloads:
        if type(item) is not dict:
            raise InvalidNarrationState("manual review scene projection is invalid")
        store.add(
            NarrationScene(
                id=UUID(str(item["scene_id"])),
                script_version_id=row.id,
                ordinal=item["ordinal"],
                source_start=item["source_start"],
                source_end=item["source_end"],
                boundary_source=item["boundary_source"],
                local_hash=item["local_hash"],
                title=item["title"],
            )
        )
    for item in segment_payloads:
        if type(item) is not dict:
            raise InvalidNarrationState(
                "manual review segment projection is invalid"
            )
        store.add(
            NarrationSegment(
                id=UUID(str(item["segment_id"])),
                script_version_id=row.id,
                scene_id=(
                    UUID(str(item["scene_id"])) if item["scene_id"] else None
                ),
                ordinal=item["ordinal"],
                segment_kind=item["segment_kind"],
                paragraph_ordinal=item["paragraph_ordinal"],
                source_block_key=item["source_block_key"],
                source_start_utf16=item["source_start_utf16"],
                source_end_utf16=item["source_end_utf16"],
                source_text=item["source_text"],
                spoken_text=item["spoken_text"],
                local_hash=item["local_hash"],
                anchor_before_hash=item["anchor_before_hash"],
                anchor_after_hash=item["anchor_after_hash"],
                speaker_kind=item["speaker_kind"],
                character_id=(
                    UUID(str(item["character_id"]))
                    if item["character_id"]
                    else None
                ),
                anonymous_speaker_id=(
                    UUID(str(item["anonymous_speaker_id"]))
                    if item["anonymous_speaker_id"]
                    else None
                ),
                casting_json=canonical_payload(item["casting"]),
                evidence_json=canonical_payload(item["evidence"]),
                confidence=item["confidence"],
                emotion=item["emotion"],
                expression=item["expression"],
                pause_before_ms=item["pause_before_ms"],
                pause_after_ms=item["pause_after_ms"],
                manual_override=item["manual_override"],
            )
        )
    store.flush()
    for issue in validated.issues:
        store.add(
            NarrationScriptIssue(
                id=uuid4(),
                script_version_id=row.id,
                segment_id=issue.segment_id,
                taxonomy_version=NARRATION_REVIEW_TAXONOMY_VERSION,
                code=issue.code,
                severity=issue.severity.value,
                evidence_summary=issue.evidence_summary,
                evidence_digest=issue.evidence_digest,
            )
        )
    store.flush()
    return row


def persist_inherited_analysis_result(
    store: NarrationStore,
    *,
    request: NarrationRequest,
    allocation: ScriptVersionAllocation,
    contract: NarrationScriptContract,
    source_version_id: UUID,
    action_key: str,
    actor_id: str,
    pending_provenances: frozenset[OverrideProvenance],
) -> NarrationScriptVersion:
    """Persist one exact inherited candidate plus its immutable action ledger."""

    key = require_nonempty(action_key, field="action_key")
    owner_actor = _require_nfc_text(
        require_nonempty(actor_id, field="actor_id"),
        field_name="actor_id",
        minimum=1,
        maximum=120,
    )
    if type(allocation) is not ScriptVersionAllocation:
        raise NarrationServiceError("allocation must be ScriptVersionAllocation")
    if type(contract) is not NarrationScriptContract:
        raise NarrationServiceError("contract must be NarrationScriptContract")
    if type(pending_provenances) is not frozenset or not pending_provenances:
        raise NarrationServiceError(
            "inherited analysis requires a non-empty provenance set"
        )
    action_id = _action_id(key)
    recorded_at_values = {
        provenance.recorded_at for provenance in pending_provenances
    }
    if (
        any(
            provenance.kind is not OverrideKind.INHERITED
            or provenance.action_id != action_id
            or provenance.owner_actor_id != owner_actor
            or provenance.source_script_version_id != source_version_id
            for provenance in pending_provenances
        )
        or len(recorded_at_values) != 1
    ):
        raise InvalidNarrationState(
            "inherited analysis provenances differ from their ledger identity"
        )
    recorded_at = next(iter(recorded_at_values))
    source_version = require_row(
        store.get(NarrationScriptVersion, source_version_id),
        label="inherited analysis source version",
    )
    if (
        request.owner_id != LOCAL_OWNER_ID
        or request.workspace_id != LOCAL_WORKSPACE_ID
        or request.intent == "analyze_only"
        or request.state != "analyzing"
        or request.explicit_generation_intent_at is None
        or request.explicit_generation_actor != owner_actor
        or request.review_script_id is not None
        or request.current_review_version_id is not None
        or source_version.script_id != allocation.script_id
        or source_version.state != "approved"
        or allocation.parent_version_id != source_version_id
        or contract.parent_version_id != source_version_id
        or contract.script_version_id != allocation.script_version_id
        or contract.state is not ScriptVersionState.REVIEW_REQUIRED
    ):
        raise InvalidNarrationState(
            "inherited analysis request/source/result relation is invalid"
        )
    if store.find_one(
        NarrationScriptReviewActionRecord,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        idempotency_key=key,
        for_update=True,
    ) is not None:
        raise IdempotencyConflict(
            "inherited analysis action already exists without its script replay"
        )

    row = _persist_review_contract(
        store,
        contract,
        idempotency_key=allocation.idempotency_key,
        pending_provenances=pending_provenances,
    )
    request.review_script_id = contract.script_id
    request.current_review_version_id = contract.script_version_id
    request.version += 1
    request.updated_at = recorded_at
    store.flush()

    request_version_before = request.version
    request_hash = _inherited_analysis_request_hash(
        request_id=request.id,
        script_id=contract.script_id,
        source_version_id=source_version_id,
        result_version_id=contract.script_version_id,
        result_immutable_hash=contract.immutable_hash,
        action_key=key,
        actor_id=owner_actor,
        provenances=pending_provenances,
    )
    store.add(
        NarrationScriptReviewActionRecord(
            id=action_id,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=request.novel_id,
            request_id=request.id,
            request_allows_render=True,
            script_id=contract.script_id,
            parent_version_id=source_version_id,
            result_version_id=contract.script_version_id,
            result_edition_id=None,
            action_kind="reanalyze_segments",
            request_hash=request_hash,
            idempotency_key=key,
            request_version_before=request_version_before,
            request_version_after=request_version_before + 1,
            actor_type="owner",
            actor_id=owner_actor,
            created_at=recorded_at,
        )
    )
    store.flush()
    advance_request_state(
        store,
        request.id,
        expected_version=request_version_before,
        new_state="review_required",
        novel_id=request.novel_id,
        actor="narration-script-analyzer",
    )
    return row


def _replay_result(
    store: NarrationStore,
    *,
    command: CorrectReviewSegment,
    action: NarrationScriptReviewActionRecord,
    request_hash: str,
) -> ReviewSegmentCorrectionResult:
    expected_action_id = _action_id(command.idempotency_key)
    if (
        action.id != expected_action_id
        or action.owner_id != LOCAL_OWNER_ID
        or action.workspace_id != LOCAL_WORKSPACE_ID
        or action.request_id != command.request_id
        or action.request_allows_render is not True
        or action.idempotency_key != command.idempotency_key
        or action.parent_version_id != command.script_version_id
        or action.action_kind != "patch_segment"
        or action.request_hash != request_hash
        or action.request_version_before != command.expected_request_version
        or action.request_version_after != action.request_version_before + 1
        or action.actor_type != "owner"
        or action.actor_id != command.actor_id
        or action.result_version_id == action.parent_version_id
        or action.result_edition_id is not None
    ):
        raise IdempotencyConflict(
            "review action idempotency key has another canonical input"
        )
    contract = load_review_script_contract(store, action.result_version_id)
    if (
        contract.script_id != action.script_id
        or contract.parent_version_id != action.parent_version_id
        or not any(
            segment.attribution.override_provenance is not None
            and segment.attribution.override_provenance.action_id == action.id
            for segment in contract.segments
        )
    ):
        raise InvalidNarrationState(
            "review action replay result differs from its immutable ledger"
        )
    return ReviewSegmentCorrectionResult(
        action_id=action.id,
        request_id=action.request_id,
        request_hash=action.request_hash,
        request_version_before=action.request_version_before,
        request_version_after=action.request_version_after,
        script_id=action.script_id,
        parent_version_id=action.parent_version_id,
        result_version_id=action.result_version_id,
        contract=contract,
        replayed=True,
    )


def correct_review_segment(
    store: NarrationStore,
    command: CorrectReviewSegment,
) -> ReviewSegmentCorrectionResult:
    """Create one immutable manual-correction child under request/pointer CAS."""

    key, actor_id, reason = _validate_correction(command)
    request_hash = _request_hash(command, actor_id=actor_id, reason=reason)
    existing = store.find_one(
        NarrationScriptReviewActionRecord,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        idempotency_key=key,
        for_update=True,
    )
    if existing is not None:
        return _replay_result(
            store,
            command=command,
            action=existing,
            request_hash=request_hash,
        )

    request = require_row(
        store.get(NarrationRequest, command.request_id, for_update=True),
        label="narration request",
    )
    if (
        request.owner_id != LOCAL_OWNER_ID
        or request.workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationScopeMismatch(
            "narration request is outside the fixed local scope"
        )
    if (
        request.intent == "analyze_only"
        or request.explicit_generation_intent_at is None
        or not request.explicit_generation_actor
        or not request.allows_render
    ):
        raise InvalidNarrationState(
            "manual correction requires an explicit generation request"
        )
    if request.state != "review_required":
        raise InvalidNarrationState(
            "manual correction requires request state review_required"
        )
    if request.version != command.expected_request_version:
        raise NarrationCasConflict("narration request version changed")
    if (
        request.review_script_id is None
        or request.current_review_version_id is None
    ):
        raise InvalidNarrationState(
            "review_required request has no complete current script pointer"
        )
    if request.current_review_version_id != command.script_version_id:
        raise NarrationCasConflict(
            "narration request current review version changed"
        )
    if (
        request.document_id is None
        or request.source_revision_id is None
        or request.source_content_hash is None
    ):
        raise InvalidNarrationState(
            "manual correction only supports one frozen document request"
        )
    document = require_row(
        store.get(Document, request.document_id, for_update=True),
        label="request document",
    )
    if document.novel_id != request.novel_id:
        raise NarrationScopeMismatch("request document belongs to another novel")
    # Recheck after acquiring the document allocation mutex.
    existing = store.find_one(
        NarrationScriptReviewActionRecord,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        idempotency_key=key,
        for_update=True,
    )
    if existing is not None:
        return _replay_result(
            store,
            command=command,
            action=existing,
            request_hash=request_hash,
        )

    parent = load_review_script_contract(
        store,
        command.script_version_id,
        for_update=True,
    )
    if (
        parent.script_id != request.review_script_id
        or parent.novel_id != request.novel_id
        or parent.document_id != request.document_id
        or parent.revision_id != request.source_revision_id
        or parent.source_content_hash != request.source_content_hash
        or parent.settings_fingerprint != request.settings_fingerprint
    ):
        raise NarrationScopeMismatch(
            "current review candidate is outside request provenance"
        )
    if parent.version_number != command.expected_version_number:
        raise StaleNarrationInput("script version number changed")
    if parent.immutable_hash != command.expected_immutable_hash:
        raise StaleNarrationInput("script immutable hash changed")
    target = next(
        (
            segment
            for segment in parent.segments
            if segment.segment_id == command.segment_id
        ),
        None,
    )
    if target is None:
        raise StaleNarrationInput("review segment is no longer current")
    if target.local_hash != command.expected_local_hash:
        raise StaleNarrationInput("review segment local hash changed")

    child_key = f"review-patch-{_action_id(key).hex}"
    if store.find_one(
        NarrationScriptVersion,
        script_id=parent.script_id,
        idempotency_key=child_key,
    ) is not None:
        raise InvalidNarrationState(
            "manual review child exists without its action ledger"
        )
    versions = store.find_all(
        NarrationScriptVersion,
        script_id=parent.script_id,
    )
    version_number = max(
        (version.version_number for version in versions),
        default=0,
    ) + 1
    child_version_id = uuid5(
        parent.script_id,
        f"narration-script-version:{child_key}",
    )
    action_id = _action_id(key)
    if store.get(NarrationScriptReviewActionRecord, action_id) is not None:
        raise IdempotencyConflict(
            "review action identity is already occupied"
        )
    recorded_at = utc_now()
    try:
        child, provenance = _replacement_contract(
            parent,
            script_version_id=child_version_id,
            version_number=version_number,
            idempotency_action_id=action_id,
            actor_id=actor_id,
            recorded_at=recorded_at,
            target_segment_id=command.segment_id,
            speaker=command.speaker,
            casting=command.casting,
            spoken_text=command.spoken_text,
        )
    except ScriptContractError as error:
        raise InvalidNarrationState(
            "manual correction speaker/casting shape is invalid"
        ) from error
    _persist_review_contract(
        store,
        child,
        idempotency_key=child_key,
        pending_provenances=frozenset({provenance}),
    )
    action = NarrationScriptReviewActionRecord(
        id=action_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=request.novel_id,
        request_id=request.id,
        request_allows_render=True,
        script_id=parent.script_id,
        parent_version_id=parent.script_version_id,
        result_version_id=child.script_version_id,
        result_edition_id=None,
        action_kind="patch_segment",
        request_hash=request_hash,
        idempotency_key=key,
        request_version_before=request.version,
        request_version_after=request.version + 1,
        actor_type="owner",
        actor_id=actor_id,
        created_at=recorded_at,
    )
    store.add(action)
    request.current_review_version_id = child.script_version_id
    request.version = command.expected_request_version + 1
    request.updated_at = recorded_at
    store.flush()
    reloaded = load_review_script_contract(store, child.script_version_id)
    if reloaded.immutable_hash != child.immutable_hash:
        raise StaleNarrationInput(
            "manual review child reload differs from its immutable projection"
        )
    return ReviewSegmentCorrectionResult(
        action_id=action.id,
        request_id=request.id,
        request_hash=request_hash,
        request_version_before=command.expected_request_version,
        request_version_after=request.version,
        script_id=child.script_id,
        parent_version_id=parent.script_version_id,
        result_version_id=child.script_version_id,
        contract=reloaded,
        replayed=False,
    )


def reanalyze_review_segments(
    store: NarrationStore,
    command: ReanalyzeReviewSegments,
) -> None:
    """Fail closed until the shared analyzer exposes subset replay authority."""

    del store
    if type(command) is not ReanalyzeReviewSegments:
        raise NarrationServiceError("command must be ReanalyzeReviewSegments")
    raise InvalidNarrationState(
        "partial segment reanalysis requires a shared analyzer adapter and "
        "remains unavailable"
    )


__all__ = [
    "CorrectReviewSegment",
    "INHERITED_ANALYSIS_ACTION_VERSION",
    "ReanalyzeReviewSegments",
    "ReviewSegmentCorrectionResult",
    "correct_review_segment",
    "inherited_analysis_action_identity",
    "load_review_script_contract",
    "persist_inherited_analysis_result",
    "reanalyze_review_segments",
]
