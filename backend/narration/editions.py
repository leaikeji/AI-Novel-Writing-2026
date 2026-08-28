"""Immutable Edition creation with full request/script/settings/voice provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from ..models import (
    GenericVoicePool,
    GenericVoiceSlot,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    NarrationSegmentRender,
    NarrationSettingsSnapshot,
    PronunciationProfile,
)

from .fingerprints import edition_fingerprint
from .digest_keyring import DigestKeyring
from .manifest import BUFFER_POLICIES
from .renders import derive_render_identity
from .requests import require_generation_request
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationStore,
    StaleNarrationInput,
    canonical_payload,
    require_exact_int,
    require_nonempty,
    require_row,
    require_same_novel,
    require_sha256,
    require_usable_voice,
)


EDITION_SEGMENT_TRANSITIONS = {
    "pending": frozenset({"queued", "rendering", "ready", "failed", "cancelled", "quarantined"}),
    "queued": frozenset({"rendering", "ready", "failed", "cancelled", "quarantined"}),
    "rendering": frozenset({"ready", "failed", "cancelled", "quarantined"}),
    "failed": frozenset({"queued"}),
}


@dataclass(frozen=True, slots=True)
class EditionSegmentInput:
    segment_id: UUID
    ordinal: int
    profile_id: UUID
    voice_version_id: UUID
    resolution_json: dict[str, object]
    gap_after_ms: int = 0
    slot_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateEdition:
    novel_id: UUID
    document_id: UUID
    request_id: UUID
    script_version_id: UUID
    settings_snapshot_id: UUID
    tts_fingerprint: str
    tokenizer_fingerprint: str
    normalizer_fingerprint: str
    postprocess_fingerprint: str
    buffer_policy_version: str
    created_actor: str
    segments: tuple[EditionSegmentInput, ...]
    digest_keyring: DigestKeyring = field(repr=False)
    pronunciation_profile_id: UUID | None = None


def create_edition(store: NarrationStore, command: CreateEdition) -> NarrationEdition:
    if type(command.digest_keyring) is not DigestKeyring:
        raise InvalidNarrationState("Edition creation requires a digest keyring")
    request = require_generation_request(
        store, command.request_id, novel_id=command.novel_id, for_update=True
    )
    if request.state != "queued":
        raise InvalidNarrationState("Edition creation requires a queued generation request")
    if request.document_id not in {None, command.document_id} and request.intent != "batch":
        raise NarrationScopeMismatch("request belongs to another document")
    version = require_row(
        store.get(NarrationScriptVersion, command.script_version_id), label="script version"
    )
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    if script.novel_id != command.novel_id or script.document_id != command.document_id:
        raise NarrationScopeMismatch("approved script belongs to another document or novel")
    if version.state != "approved" or version.approval_request_id != request.id:
        raise InvalidNarrationState("Edition requires approval by the same generation request")
    if version.effective_policy != request.effective_policy:
        raise InvalidNarrationState("request/script approval policy mismatch")
    snapshot = require_row(
        store.get(NarrationSettingsSnapshot, command.settings_snapshot_id),
        label="settings snapshot",
    )
    require_same_novel(snapshot.novel_id, command.novel_id, label="settings snapshot")
    if snapshot.owner_id != request.owner_id or snapshot.workspace_id != request.workspace_id:
        raise NarrationScopeMismatch("settings snapshot scope mismatch")
    if snapshot.fingerprint != version.settings_fingerprint:
        raise StaleNarrationInput("Edition settings snapshot differs from approved script")
    if command.pronunciation_profile_id:
        pronunciation = require_row(
            store.get(PronunciationProfile, command.pronunciation_profile_id),
            label="pronunciation profile",
        )
        require_same_novel(
            pronunciation.novel_id, command.novel_id, label="pronunciation profile"
        )
    for field, value in (
        ("tts_fingerprint", command.tts_fingerprint),
        ("tokenizer_fingerprint", command.tokenizer_fingerprint),
        ("normalizer_fingerprint", command.normalizer_fingerprint),
        ("postprocess_fingerprint", command.postprocess_fingerprint),
    ):
        require_sha256(value, field=field)
    require_nonempty(command.buffer_policy_version, field="buffer_policy_version")
    if command.buffer_policy_version not in BUFFER_POLICIES:
        raise InvalidNarrationState("unsupported server buffer policy version")
    require_nonempty(command.created_actor, field="created_actor")
    if type(command.segments) is not tuple or not all(
        type(item) is EditionSegmentInput for item in command.segments
    ):
        raise InvalidNarrationState("Edition segments must be frozen EditionSegmentInput values")
    if not command.segments:
        raise InvalidNarrationState("Edition requires at least one segment")
    if [item.ordinal for item in command.segments] != list(range(len(command.segments))):
        raise InvalidNarrationState("Edition segment ordinals must be contiguous from zero")

    script_segments = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
        for_update=True,
    )
    if (
        [row.ordinal for row in script_segments] != list(range(len(script_segments)))
        or [(item.segment_id, item.ordinal) for item in command.segments]
        != [(row.id, row.ordinal) for row in script_segments]
    ):
        raise InvalidNarrationState(
            "Edition must cover every approved script segment exactly once"
        )
    script_segment_by_id = {row.id: row for row in script_segments}

    # Acquire every voice authority chain in a stable order before deriving any
    # segment.  Rights revocation uses the same parent locks, so no Edition can
    # commit from a mixture of pre- and post-revocation observations.
    usable_voices = {
        voice_id: require_usable_voice(
            store,
            voice_id,
            novel_id=command.novel_id,
        )
        for voice_id in sorted(
            {item.voice_version_id for item in command.segments},
            key=str,
        )
    }

    segment_payload: list[dict[str, object]] = []
    render_fingerprints: dict[UUID, str] = {}
    render_digest_key_ids: dict[UUID, str] = {}
    for item in command.segments:
        require_exact_int(item.ordinal, field="Edition segment ordinal", minimum=0)
        require_exact_int(item.gap_after_ms, field="segment gap", minimum=0)
        if type(item.resolution_json) is not dict:
            raise InvalidNarrationState("Edition resolution must be an object")
        segment = script_segment_by_id[item.segment_id]
        if segment.script_version_id != version.id or segment.ordinal != item.ordinal:
            raise NarrationScopeMismatch("Edition segment is outside the approved script")
        profile, voice, _rights = usable_voices[item.voice_version_id]
        if profile.id != item.profile_id or voice.profile_id != item.profile_id:
            raise NarrationScopeMismatch("Edition profile and voice version mismatch")
        if item.slot_id is not None:
            slot = require_row(store.get(GenericVoiceSlot, item.slot_id), label="voice slot")
            pool = require_row(store.get(GenericVoicePool, slot.pool_id), label="voice pool")
            if (
                pool.novel_id != command.novel_id
                or pool.status != "active"
                or type(slot.enabled) is not bool
                or not slot.enabled
                or slot.voice_version_id != voice.id
            ):
                raise NarrationScopeMismatch("Edition voice slot does not resolve to this voice")
        render_fingerprint_value, _canonical_input = derive_render_identity(
            store,
            novel_id=command.novel_id,
            segment=segment,
            voice_version_id=item.voice_version_id,
            pronunciation_profile_id=command.pronunciation_profile_id,
            tts_fingerprint=command.tts_fingerprint,
            tokenizer_fingerprint=command.tokenizer_fingerprint,
            normalizer_fingerprint=command.normalizer_fingerprint,
            postprocess_fingerprint=command.postprocess_fingerprint,
            digest_key=command.digest_keyring.active,
        )
        render_fingerprints[item.segment_id] = render_fingerprint_value
        render_digest_key_ids[item.segment_id] = command.digest_keyring.active_key_id
        segment_payload.append(
            {
                "segment_id": str(item.segment_id),
                "ordinal": item.ordinal,
                "slot_id": str(item.slot_id) if item.slot_id else None,
                "profile_id": str(item.profile_id),
                "voice_version_id": str(item.voice_version_id),
                "render_fingerprint": render_fingerprint_value,
                "render_digest_key_id": command.digest_keyring.active_key_id,
                "resolution": canonical_payload(item.resolution_json),
                "gap_after_ms": item.gap_after_ms,
            }
        )

    fingerprint_payload = {
        "owner_id": str(request.owner_id),
        "workspace_id": str(request.workspace_id),
        "novel_id": str(command.novel_id),
        "document_id": str(command.document_id),
        "request_id": str(request.id),
        "script_version_id": str(version.id),
        "script_immutable_hash": version.immutable_hash,
        "settings_snapshot_fingerprint": snapshot.fingerprint,
        "pronunciation_profile_id": (
            str(command.pronunciation_profile_id) if command.pronunciation_profile_id else None
        ),
        "tts_fingerprint": command.tts_fingerprint,
        "tokenizer_fingerprint": command.tokenizer_fingerprint,
        "normalizer_fingerprint": command.normalizer_fingerprint,
        "postprocess_fingerprint": command.postprocess_fingerprint,
        "context_mode": "independent_segment",
        "buffer_policy_version": command.buffer_policy_version,
        "segments": segment_payload,
    }
    fingerprint = edition_fingerprint(fingerprint_payload)
    existing = store.find_one(
        NarrationEdition,
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        edition_fingerprint=fingerprint,
    )
    if existing is not None:
        if (
            existing.novel_id != command.novel_id
            or existing.request_id != request.id
            or existing.script_version_id != version.id
        ):
            raise IdempotencyConflict("Edition fingerprint collision")
        existing_segments = store.find_all(
            NarrationEditionSegment,
            edition_id=existing.id,
            order_by=("ordinal",),
            for_update=True,
        )
        expected_children = [
            (
                item.segment_id,
                item.ordinal,
                item.slot_id,
                item.profile_id,
                item.voice_version_id,
                canonical_payload(item.resolution_json),
                render_fingerprints[item.segment_id],
                render_digest_key_ids[item.segment_id],
                item.gap_after_ms,
            )
            for item in command.segments
        ]
        actual_children = [
            (
                item.segment_id,
                item.ordinal,
                item.slot_id,
                item.profile_id,
                item.voice_version_id,
                item.resolution_json,
                item.render_fingerprint,
                item.render_digest_key_id,
                item.gap_after_ms,
            )
            for item in existing_segments
        ]
        if actual_children != expected_children:
            raise IdempotencyConflict("persisted Edition segments differ from its fingerprint")
        return existing

    edition = NarrationEdition(
        id=uuid4(),
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        novel_id=command.novel_id,
        document_id=command.document_id,
        request_id=request.id,
        request_allows_edition=True,
        script_version_id=version.id,
        script_is_approved=True,
        settings_snapshot_id=snapshot.id,
        pronunciation_profile_id=command.pronunciation_profile_id,
        tts_fingerprint=command.tts_fingerprint,
        tokenizer_fingerprint=command.tokenizer_fingerprint,
        normalizer_fingerprint=command.normalizer_fingerprint,
        postprocess_fingerprint=command.postprocess_fingerprint,
        context_mode="independent_segment",
        buffer_policy_version=command.buffer_policy_version,
        edition_fingerprint=fingerprint,
        state="created",
        created_actor=command.created_actor,
    )
    store.add(edition)
    store.flush()
    for item in command.segments:
        store.add(
            NarrationEditionSegment(
                id=uuid4(),
                edition_id=edition.id,
                script_version_id=version.id,
                segment_id=item.segment_id,
                ordinal=item.ordinal,
                slot_id=item.slot_id,
                profile_id=item.profile_id,
                voice_version_id=item.voice_version_id,
                resolution_json=canonical_payload(item.resolution_json),
                render_fingerprint=render_fingerprints[item.segment_id],
                render_digest_key_id=render_digest_key_ids[item.segment_id],
                render_state="pending",
                gap_after_ms=item.gap_after_ms,
            )
        )
    store.flush()
    return edition


def advance_edition_segment_state(
    store: NarrationStore,
    edition_segment_id: UUID,
    *,
    new_state: str,
    failure_code: str | None = None,
) -> NarrationEditionSegment:
    row = require_row(
        store.get(NarrationEditionSegment, edition_segment_id, for_update=True),
        label="Edition segment",
    )
    if new_state == row.render_state:
        return row
    if new_state not in EDITION_SEGMENT_TRANSITIONS.get(row.render_state, frozenset()):
        raise InvalidNarrationState(
            f"invalid Edition segment transition {row.render_state}->{new_state}"
        )
    edition = require_row(store.get(NarrationEdition, row.edition_id), label="Edition")
    if new_state == "ready":
        render = store.find_one(
            NarrationSegmentRender,
            owner_id=edition.owner_id,
            workspace_id=edition.workspace_id,
            render_fingerprint=row.render_fingerprint,
        )
        if (
            render is None
            or render.novel_id != edition.novel_id
            or render.state != "ready"
            or render.voice_version_id != row.voice_version_id
        ):
            raise InvalidNarrationState("Edition segment has no matching ready render")
        require_usable_voice(store, row.voice_version_id, novel_id=edition.novel_id)
        failure_code = None
    elif new_state == "failed":
        require_nonempty(failure_code or "", field="failure_code")
    elif failure_code is not None:
        raise InvalidNarrationState("failure_code is only valid for failed state")
    row.render_state = new_state
    row.failure_code = failure_code
    store.flush()
    return row


__all__ = [
    "CreateEdition",
    "EditionSegmentInput",
    "advance_edition_segment_state",
    "create_edition",
]
