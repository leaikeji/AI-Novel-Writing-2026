"""Deterministic authority locks for narration review and production.

The public entry points deliberately separate the request/document mutex from
the voice graph.  Callers therefore cannot enter any voice authority lock
without first acquiring the request row and its document row in that order.
The voice graph is collected without locks, locked by one global type/UUID
order, and collected again for a fail-closed CAS before it may be consumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ..models import (
    AnonymousSpeaker,
    CharacterVoiceBinding,
    Document,
    GenericVoicePool,
    GenericVoiceSlot,
    NarrationRequest,
    NarrationSettingsSnapshot,
    Novel,
    NovelCharacter,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .script_contracts import (
    CastingDecisionOrigin,
    CastingTargetKind,
    NarrationScriptContract,
    SpeakerKind,
)
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    require_row,
)


_MUTEX_SEAL = object()
_AUTHORITY_SEAL = object()


@dataclass(frozen=True, slots=True)
class RequestDocumentMutex:
    """Opaque proof that request -> document -> novel was locked."""

    request_id: UUID
    document_id: UUID
    novel_id: UUID
    request_version: int
    current_review_version_id: UUID | None
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class VoiceAuthorityLock:
    """Opaque proof that the exact contract voice graph passed its lock CAS."""

    request_id: UUID
    contract_version_id: UUID
    resource_ids: tuple[tuple[str, tuple[UUID, ...]], ...]
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _AuthoritySelection:
    character_ids: frozenset[UUID]
    anonymous_ids: frozenset[UUID]
    include_narrator: bool


@dataclass(frozen=True, slots=True)
class _CollectedGraph:
    rows: tuple[tuple[type[Any], tuple[UUID, ...]], ...]
    signatures: tuple[tuple[str, UUID, tuple[tuple[str, object], ...]], ...]


# This is the sole voice-resource acquisition order.  NovelCharacter is first;
# rights events are last and ordered by their own UUID.  A rights parent lock
# precedes its events, so a concurrent FK-backed revocation insertion cannot
# enter between the final graph CAS and the protected write.
_RESOURCE_ORDER: tuple[type[Any], ...] = (
    NovelCharacter,
    CharacterVoiceBinding,
    AnonymousSpeaker,
    GenericVoicePool,
    GenericVoiceSlot,
    VoiceProfileVersion,
    VoiceProfile,
    VoiceRightsRecord,
    VoiceRightsEvent,
)


def lock_request_document_mutex(
    store: NarrationStore,
    request_id: UUID,
    *,
    expected_document_id: UUID | None = None,
    expected_novel_id: UUID | None = None,
) -> tuple[NarrationRequest, Document, RequestDocumentMutex]:
    """Lock request -> document -> novel, in that exact order.

    Document fixes the source-identity/structural lock order.  Novel is the
    aggregate mutex shared by settings and scope-override writers; autosave
    joins the same commit order when ``save_draft`` updates ``Novel.updated_at``
    after its working-copy write.  The subsequent source/settings fingerprint
    decision is therefore linearized by Novel through this transaction.
    """

    request = require_row(
        store.get(NarrationRequest, request_id, for_update=True),
        label="narration request",
    )
    if request.document_id is None:
        raise InvalidNarrationState("narration request has no document mutex")
    if (
        request.owner_id != LOCAL_OWNER_ID
        or request.workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationScopeMismatch(
            "narration request is outside the fixed local scope"
        )
    if expected_document_id is not None and request.document_id != expected_document_id:
        raise NarrationCasConflict("narration request document changed")
    if expected_novel_id is not None and request.novel_id != expected_novel_id:
        raise NarrationScopeMismatch("narration request novel changed")
    document = require_row(
        store.get(Document, request.document_id, for_update=True),
        label="document",
    )
    if document.novel_id != request.novel_id:
        raise NarrationScopeMismatch("request/document novel relation changed")
    novel = require_row(
        store.get(Novel, request.novel_id, for_update=True),
        label="novel",
    )
    if (
        novel.owner_id != request.owner_id
        or novel.workspace_id != request.workspace_id
    ):
        raise NarrationScopeMismatch("request/novel local scope changed")
    return (
        request,
        document,
        RequestDocumentMutex(
            request_id=request.id,
            document_id=document.id,
            novel_id=request.novel_id,
            request_version=request.version,
            current_review_version_id=request.current_review_version_id,
            _seal=_MUTEX_SEAL,
        ),
    )


def lock_voice_authorities(
    store: NarrationStore,
    *,
    mutex: RequestDocumentMutex,
    contract: NarrationScriptContract,
    settings_snapshot: NarrationSettingsSnapshot,
    extra_character_ids: frozenset[UUID] = frozenset(),
    extra_anonymous_ids: frozenset[UUID] = frozenset(),
    include_narrator: bool = False,
) -> VoiceAuthorityLock:
    """Lock and CAS every authority reachable by the selected contract graph."""

    if type(mutex) is not RequestDocumentMutex or mutex._seal is not _MUTEX_SEAL:
        raise InvalidNarrationState(
            "voice authority requires a verified request/document mutex"
        )
    if type(contract) is not NarrationScriptContract:
        raise InvalidNarrationState("voice authority requires a typed script")
    if (
        contract.document_id != mutex.document_id
        or contract.novel_id != mutex.novel_id
        or contract.script_version_id != mutex.current_review_version_id
    ):
        raise NarrationCasConflict(
            "voice authority contract is not the request current pointer"
        )
    if (
        settings_snapshot.novel_id != mutex.novel_id
        or settings_snapshot.fingerprint != contract.settings_fingerprint
    ):
        raise NarrationScopeMismatch(
            "voice authority settings snapshot differs from the contract"
        )
    contract_requires_narrator = any(
        segment.casting.origin is CastingDecisionOrigin.NARRATOR_SETTING
        and (
            segment.casting.final_target is not None
            and segment.casting.final_target.kind is CastingTargetKind.PROFILE
        )
        for segment in contract.segments
    )
    selection = _AuthoritySelection(
        character_ids=frozenset(extra_character_ids),
        anonymous_ids=frozenset(extra_anonymous_ids),
        include_narrator=include_narrator or contract_requires_narrator,
    )
    before = _collect_graph(
        store,
        contract=contract,
        settings_snapshot=settings_snapshot,
        selection=selection,
    )
    for model, identifiers in before.rows:
        for identifier in identifiers:
            require_row(
                store.get(model, identifier, for_update=True),
                label=model.__tablename__,
            )
    after = _collect_graph(
        store,
        contract=contract,
        settings_snapshot=settings_snapshot,
        selection=selection,
    )
    if after != before:
        raise NarrationCasConflict(
            "voice authority graph changed while deterministic locks were acquired"
        )
    return VoiceAuthorityLock(
        request_id=mutex.request_id,
        contract_version_id=contract.script_version_id,
        resource_ids=tuple(
            (model.__tablename__, identifiers)
            for model, identifiers in before.rows
        ),
        _seal=_AUTHORITY_SEAL,
    )


def require_voice_authority_lock(
    authority: VoiceAuthorityLock,
    *,
    request_id: UUID,
    contract_version_id: UUID,
) -> None:
    if (
        type(authority) is not VoiceAuthorityLock
        or authority._seal is not _AUTHORITY_SEAL
        or authority.request_id != request_id
        or authority.contract_version_id != contract_version_id
    ):
        raise InvalidNarrationState("voice authority lock proof is invalid")


def _collect_graph(
    store: NarrationStore,
    *,
    contract: NarrationScriptContract,
    settings_snapshot: NarrationSettingsSnapshot,
    selection: _AuthoritySelection,
) -> _CollectedGraph:
    ids: dict[type[Any], set[UUID]] = {model: set() for model in _RESOURCE_ORDER}
    ids[NovelCharacter].update(selection.character_ids)
    ids[AnonymousSpeaker].update(selection.anonymous_ids)

    direct_profile_ids: set[UUID] = set()
    for segment in contract.segments:
        if segment.speaker.kind is SpeakerKind.CHARACTER:
            assert segment.speaker.character_id is not None
            ids[NovelCharacter].add(segment.speaker.character_id)
        elif segment.speaker.kind is SpeakerKind.ANONYMOUS:
            assert segment.speaker.anonymous_speaker_id is not None
            ids[AnonymousSpeaker].add(segment.speaker.anonymous_speaker_id)
        for target in (*segment.casting.candidate_targets,):
            _collect_target(ids, direct_profile_ids, target)
        if segment.casting.final_target is not None:
            _collect_target(ids, direct_profile_ids, segment.casting.final_target)
    ids[AnonymousSpeaker].update(
        identity.anonymous_speaker_id for identity in contract.anonymous_speakers
    )

    if selection.include_narrator:
        profile_id, version_id = _snapshot_narrator(settings_snapshot)
        direct_profile_ids.add(profile_id)
        ids[VoiceProfileVersion].add(version_id)

    # Selected character corrections identify a character, not a binding.  The
    # current binding is collected without FOR UPDATE and becomes part of the
    # one fixed lock plan below.
    for character_id in sorted(selection.character_ids, key=str):
        binding = require_row(
            store.find_one(CharacterVoiceBinding, character_id=character_id),
            label="character voice binding",
        )
        ids[CharacterVoiceBinding].add(binding.id)

    # First-level rows expose the remaining pool/slot and voice-version edges.
    for binding_id in sorted(ids[CharacterVoiceBinding], key=str):
        binding = require_row(
            store.get(CharacterVoiceBinding, binding_id),
            label="character voice binding",
        )
        ids[NovelCharacter].add(binding.character_id)
        if binding.profile_id is not None:
            direct_profile_ids.add(binding.profile_id)
        if binding.voice_version_id is not None:
            ids[VoiceProfileVersion].add(binding.voice_version_id)
    for anonymous_id in sorted(ids[AnonymousSpeaker], key=str):
        anonymous = require_row(
            store.get(AnonymousSpeaker, anonymous_id),
            label="anonymous speaker",
        )
        if anonymous.promoted_character_id is not None:
            ids[NovelCharacter].add(anonymous.promoted_character_id)
        if anonymous.slot_id is not None:
            ids[GenericVoiceSlot].add(anonymous.slot_id)
        if anonymous.voice_version_id is not None:
            ids[VoiceProfileVersion].add(anonymous.voice_version_id)
    for slot_id in sorted(ids[GenericVoiceSlot], key=str):
        slot = require_row(store.get(GenericVoiceSlot, slot_id), label="generic slot")
        ids[GenericVoicePool].add(slot.pool_id)
        ids[VoiceProfileVersion].add(slot.voice_version_id)

    # Direct PROFILE targets resolve through the profile's current immutable
    # version.  Narrator settings also carry an exact frozen version, already
    # included above.
    ids[VoiceProfile].update(direct_profile_ids)
    for profile_id in sorted(direct_profile_ids, key=str):
        profile = require_row(store.get(VoiceProfile, profile_id), label="voice profile")
        if profile.current_version_id is not None:
            ids[VoiceProfileVersion].add(profile.current_version_id)
    for version_id in sorted(ids[VoiceProfileVersion], key=str):
        version = require_row(
            store.get(VoiceProfileVersion, version_id),
            label="voice version",
        )
        ids[VoiceProfile].add(version.profile_id)
        ids[VoiceRightsRecord].add(version.rights_record_id)
    for rights_id in sorted(ids[VoiceRightsRecord], key=str):
        events = store.find_all(
            VoiceRightsEvent,
            rights_record_id=rights_id,
            order_by=("id",),
        )
        ids[VoiceRightsEvent].update(event.id for event in events)

    rows = tuple(
        (model, tuple(sorted(ids[model], key=str))) for model in _RESOURCE_ORDER
    )
    signatures: list[tuple[str, UUID, tuple[tuple[str, object], ...]]] = []
    for model, identifiers in rows:
        for identifier in identifiers:
            row = require_row(store.get(model, identifier), label=model.__tablename__)
            signatures.append((model.__tablename__, identifier, _row_signature(row)))
    return _CollectedGraph(rows=rows, signatures=tuple(signatures))


def _collect_target(
    ids: dict[type[Any], set[UUID]],
    direct_profile_ids: set[UUID],
    target: object,
) -> None:
    kind = getattr(target, "kind", None)
    if kind is CastingTargetKind.CHARACTER_BINDING:
        ids[CharacterVoiceBinding].add(target.binding_id)
        ids[NovelCharacter].add(target.character_id)
    elif kind is CastingTargetKind.ANONYMOUS_BINDING:
        ids[AnonymousSpeaker].add(target.anonymous_speaker_id)
    elif kind is CastingTargetKind.GENERIC_SLOT:
        ids[GenericVoicePool].add(target.pool_id)
        ids[GenericVoiceSlot].add(target.slot_id)
    elif kind is CastingTargetKind.PROFILE:
        direct_profile_ids.add(target.profile_id)
    else:  # pragma: no cover - contract enum exhaustiveness
        raise InvalidNarrationState("unsupported casting target in lock plan")


def _snapshot_narrator(snapshot: NarrationSettingsSnapshot) -> tuple[UUID, UUID]:
    payload = snapshot.snapshot_json
    resolved = payload.get("resolved_settings") if type(payload) is dict else None
    if type(resolved) is not dict:
        raise InvalidNarrationState("settings narrator authority is malformed")
    try:
        profile_id = UUID(str(resolved["narrator_profile_id"]))
        version_id = UUID(str(resolved["narrator_version_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidNarrationState("narrator voice is not configured") from error
    return profile_id, version_id


def _row_signature(row: object) -> tuple[tuple[str, object], ...]:
    return tuple(
        (column.name, _stable_value(getattr(row, column.name)))
        for column in row.__table__.columns
    )


def _stable_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return tuple(
            (str(key), _stable_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_stable_value(item) for item in value)
    return value


__all__ = [
    "RequestDocumentMutex",
    "VoiceAuthorityLock",
    "lock_request_document_mutex",
    "lock_voice_authorities",
    "require_voice_authority_lock",
]
