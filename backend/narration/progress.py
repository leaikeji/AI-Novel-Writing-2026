"""Playback progress plus explicit and initial document pointer CAS updates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from ..models import (
    Document,
    DocumentNarrationState,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationManifest,
    NarrationPlaybackProgress,
    NarrationRequest,
    NarrationScript,
    NarrationScriptVersion,
)

from .contracts import NarrationRequestScope
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    require_exact_int,
    require_fixed_scope,
    require_nonempty,
    require_row,
    require_sha256,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class SavePlaybackProgress:
    profile_id: str
    edition_id: UUID
    manifest_revision: int
    edition_segment_id: UUID
    offset_ms: int
    last_legal_start_ordinal: int
    playback_rate_millis: int
    expected_updated_at: datetime | None
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local()


@dataclass(frozen=True, slots=True)
class PlaybackResumeProjection:
    """Read-only resume target resolved against the current Manifest pointer."""

    profile_id: str
    edition_id: UUID
    manifest_revision: int
    manifest_etag: str
    edition_segment_id: UUID
    segment_id: UUID
    ordinal: int
    offset_ms: int
    last_legal_start_ordinal: int
    playback_rate_millis: int
    manifest_advanced: bool
    progress_updated_at: datetime


def save_playback_progress(
    store: NarrationStore, command: SavePlaybackProgress
) -> NarrationPlaybackProgress:
    require_fixed_scope(command.scope)
    require_nonempty(command.profile_id, field="profile_id")
    require_exact_int(command.manifest_revision, field="manifest_revision", minimum=1)
    require_exact_int(command.offset_ms, field="offset_ms", minimum=0)
    require_exact_int(
        command.last_legal_start_ordinal,
        field="last_legal_start_ordinal",
        minimum=0,
    )
    require_exact_int(
        command.playback_rate_millis,
        field="playback_rate_millis",
        minimum=250,
        maximum=4000,
    )
    if command.expected_updated_at is not None and (
        type(command.expected_updated_at) is not datetime
        or command.expected_updated_at.tzinfo is None
        or command.expected_updated_at.utcoffset() is None
    ):
        raise InvalidNarrationState("playback progress CAS token must be timezone-aware")
    edition = require_row(
        store.get(NarrationEdition, command.edition_id, for_update=True), label="Edition"
    )
    if edition.owner_id != command.scope.owner_id or edition.workspace_id != command.scope.workspace_id:
        raise NarrationScopeMismatch("Edition is outside fixed local scope")
    manifest = require_row(
        store.find_one(
            NarrationManifest,
            edition_id=edition.id,
            manifest_revision=command.manifest_revision,
        ),
        label="Manifest revision",
    )
    segment = require_row(
        store.get(NarrationEditionSegment, command.edition_segment_id),
        label="Edition segment",
    )
    if segment.edition_id != edition.id:
        raise NarrationScopeMismatch("playback segment belongs to another Edition")
    public_segment = next(
        (
            item
            for item in manifest.canonical_json["segments"]
            if item["ordinal"] == segment.ordinal and item["segment_id"] == str(segment.segment_id)
        ),
        None,
    )
    if public_segment is None or public_segment["render_status"] != "ready":
        raise InvalidNarrationState("playback progress must point to a ready Manifest segment")
    audio = public_segment["audio"]
    if not isinstance(audio, dict) or command.offset_ms > int(audio["duration_ms"]):
        raise InvalidNarrationState("playback offset exceeds the ready segment")
    manifest_last = manifest.canonical_json["last_playable_start_ordinal"]
    if manifest_last is None or command.last_legal_start_ordinal > manifest_last:
        raise InvalidNarrationState("saved legal start is outside the Manifest ready window")
    ranges = manifest.canonical_json.get("ready_ranges")
    if not isinstance(ranges, list):
        raise InvalidNarrationState("Manifest ready_ranges are unavailable")
    segment_range = next(
        (
            item
            for item in ranges
            if type(item) is dict
            and type(item.get("start_ordinal")) is int
            and type(item.get("end_ordinal_exclusive")) is int
            and item["start_ordinal"] <= segment.ordinal < item["end_ordinal_exclusive"]
        ),
        None,
    )
    legal_range = next(
        (
            item
            for item in ranges
            if type(item) is dict
            and type(item.get("start_ordinal")) is int
            and type(item.get("end_ordinal_exclusive")) is int
            and type(item.get("last_playable_start_ordinal")) is int
            and item["start_ordinal"] <= command.last_legal_start_ordinal
            < item["end_ordinal_exclusive"]
            and command.last_legal_start_ordinal
            <= item["last_playable_start_ordinal"]
        ),
        None,
    )
    if segment_range is None or legal_range is None:
        raise InvalidNarrationState("playback progress is outside a concrete ready range")
    if (
        segment_range["start_ordinal"] != legal_range["start_ordinal"]
        or segment_range["end_ordinal_exclusive"]
        != legal_range["end_ordinal_exclusive"]
    ):
        raise InvalidNarrationState(
            "saved legal start belongs to another disconnected ready range"
        )
    if command.last_legal_start_ordinal > segment.ordinal:
        raise InvalidNarrationState("saved legal start cannot be after playback position")

    row = store.find_one(
        NarrationPlaybackProgress,
        owner_id=command.scope.owner_id,
        workspace_id=command.scope.workspace_id,
        profile_id=command.profile_id,
        edition_id=edition.id,
        for_update=True,
    )
    now = utc_now()
    if row is None:
        if command.expected_updated_at is not None:
            raise NarrationCasConflict("playback progress does not exist at expected token")
        row = NarrationPlaybackProgress(
            id=uuid4(),
            owner_id=command.scope.owner_id,
            workspace_id=command.scope.workspace_id,
            profile_id=command.profile_id,
            edition_id=edition.id,
            manifest_revision=manifest.manifest_revision,
            edition_segment_id=segment.id,
            offset_ms=command.offset_ms,
            last_legal_start_ordinal=command.last_legal_start_ordinal,
            playback_rate_millis=command.playback_rate_millis,
            updated_at=now,
        )
        store.add(row)
    else:
        if row.updated_at != command.expected_updated_at:
            raise NarrationCasConflict("playback progress changed")
        # Preserve CAS semantics even if the application/database clock is coarse.
        if now <= row.updated_at:
            now = row.updated_at + timedelta(microseconds=1)
        row.manifest_revision = manifest.manifest_revision
        row.edition_segment_id = segment.id
        row.offset_ms = command.offset_ms
        row.last_legal_start_ordinal = command.last_legal_start_ordinal
        row.playback_rate_millis = command.playback_rate_millis
        row.updated_at = now
    store.flush()
    return row


def restore_playback_progress(
    store: NarrationStore,
    *,
    profile_id: str,
    edition_id: UUID,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> PlaybackResumeProjection | None:
    """Resolve saved progress without guessing across Editions or source text.

    Progress may safely follow a newer Manifest revision of the *same* Edition
    when the exact EditionSegment is still ready and its saved legal start is
    still inside the same concrete ready range.  No row is mutated here; the
    next explicit progress save advances the persisted revision with CAS.
    """

    require_fixed_scope(scope)
    require_nonempty(profile_id, field="profile_id")
    edition = require_row(store.get(NarrationEdition, edition_id), label="Edition")
    if edition.owner_id != scope.owner_id or edition.workspace_id != scope.workspace_id:
        raise NarrationScopeMismatch("Edition is outside fixed local scope")
    progress = store.find_one(
        NarrationPlaybackProgress,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        profile_id=profile_id,
        edition_id=edition.id,
    )
    if progress is None:
        return None
    saved_manifest = require_row(
        store.find_one(
            NarrationManifest,
            edition_id=edition.id,
            manifest_revision=progress.manifest_revision,
        ),
        label="saved Manifest revision",
    )
    state = require_row(
        store.find_one(NarrationEditionState, edition_id=edition.id),
        label="Edition Manifest pointer",
    )
    if state.current_manifest_id is None or state.current_manifest_revision is None:
        raise InvalidNarrationState("Edition has no current Manifest")
    current = require_row(
        store.get(NarrationManifest, state.current_manifest_id),
        label="current Manifest",
    )
    if (
        current.edition_id != edition.id
        or current.manifest_revision != state.current_manifest_revision
        or current.manifest_revision < saved_manifest.manifest_revision
        or current.status not in {"partial_ready", "ready"}
    ):
        raise InvalidNarrationState("current Manifest cannot restore saved progress")
    edition_segment = require_row(
        store.get(NarrationEditionSegment, progress.edition_segment_id),
        label="Edition segment",
    )
    if edition_segment.edition_id != edition.id:
        raise NarrationScopeMismatch("saved progress belongs to another Edition")
    segments = current.canonical_json.get("segments")
    ranges = current.canonical_json.get("ready_ranges")
    if type(segments) is not list or type(ranges) is not list:
        raise InvalidNarrationState("current Manifest progress indexes are malformed")
    public_segment = next(
        (
            item
            for item in segments
            if type(item) is dict
            and item.get("ordinal") == edition_segment.ordinal
            and item.get("segment_id") == str(edition_segment.segment_id)
        ),
        None,
    )
    if public_segment is None or public_segment.get("render_status") != "ready":
        raise InvalidNarrationState("saved segment is not ready in the current Manifest")
    audio = public_segment.get("audio")
    if type(audio) is not dict or type(audio.get("duration_ms")) is not int:
        raise InvalidNarrationState("saved segment has no authoritative audio duration")
    if progress.offset_ms > audio["duration_ms"]:
        raise InvalidNarrationState("saved offset exceeds current segment audio")
    ready_range = next(
        (
            item
            for item in ranges
            if type(item) is dict
            and type(item.get("start_ordinal")) is int
            and type(item.get("end_ordinal_exclusive")) is int
            and type(item.get("last_playable_start_ordinal")) is int
            and item["start_ordinal"] <= edition_segment.ordinal
            < item["end_ordinal_exclusive"]
        ),
        None,
    )
    if (
        ready_range is None
        or not ready_range["start_ordinal"]
        <= progress.last_legal_start_ordinal
        < ready_range["end_ordinal_exclusive"]
        or progress.last_legal_start_ordinal
        > ready_range["last_playable_start_ordinal"]
        or progress.last_legal_start_ordinal > edition_segment.ordinal
    ):
        raise InvalidNarrationState("saved legal start is unavailable in current ready range")
    return PlaybackResumeProjection(
        profile_id=progress.profile_id,
        edition_id=edition.id,
        manifest_revision=current.manifest_revision,
        manifest_etag=f'"{current.etag_sha256}"',
        edition_segment_id=edition_segment.id,
        segment_id=edition_segment.segment_id,
        ordinal=edition_segment.ordinal,
        offset_ms=progress.offset_ms,
        last_legal_start_ordinal=progress.last_legal_start_ordinal,
        playback_rate_millis=progress.playback_rate_millis,
        manifest_advanced=current.manifest_revision != progress.manifest_revision,
        progress_updated_at=progress.updated_at,
    )


def initialize_initial_document_edition(
    store: NarrationStore,
    *,
    request_id: UUID,
    document_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> DocumentNarrationState | None:
    """Install only the first explicit-create pointer from a playable Manifest.

    The request is the caller's leading mutex.  The document graph then uses
    the global order Document -> WorkingCopy -> DocumentNarrationState ->
    Edition.  A worker may already hold these rows; PostgreSQL row locks are
    transaction-reentrant, so the same order remains safe at publication.
    """

    require_fixed_scope(scope)
    request = require_row(
        store.get(NarrationRequest, request_id, for_update=True),
        label="narration request",
    )
    if (
        request.owner_id != scope.owner_id
        or request.workspace_id != scope.workspace_id
    ):
        raise NarrationScopeMismatch(
            "narration request is outside fixed local scope"
        )
    if request.intent != "create":
        return None

    document = require_row(
        store.get(Document, document_id, for_update=True),
        label="document",
    )
    if request.document_id != document.id or document.novel_id != request.novel_id:
        raise NarrationScopeMismatch(
            "initial narration request belongs to another document"
        )
    working = store.find_one(
        DocumentWorkingCopy,
        document_id=document.id,
        for_update=True,
    )
    if working is None:
        return None
    pointer = store.find_one(
        DocumentNarrationState,
        document_id=document.id,
        for_update=True,
    )
    if pointer is not None:
        if (
            pointer.owner_id != scope.owner_id
            or pointer.workspace_id != scope.workspace_id
        ):
            raise NarrationScopeMismatch(
                "document narration pointer is outside fixed local scope"
            )
        if pointer.current_edition_id is not None:
            return None

    edition = require_row(
        store.get(NarrationEdition, edition_id, for_update=True),
        label="Edition",
    )
    if (
        edition.owner_id != scope.owner_id
        or edition.workspace_id != scope.workspace_id
        or edition.novel_id != request.novel_id
        or edition.document_id != document.id
        or edition.request_id != request.id
    ):
        raise NarrationScopeMismatch(
            "initial Edition provenance differs from its create request"
        )
    if request.state not in {"partial_ready", "ready"} or edition.state not in {
        "partial_ready",
        "ready",
    }:
        raise InvalidNarrationState(
            "initial document pointer requires a playable request and Edition"
        )
    if (
        request.explicit_generation_intent_at is None
        or type(request.explicit_generation_intent_at) is not datetime
        or request.explicit_generation_intent_at.tzinfo is None
        or request.explicit_generation_intent_at.utcoffset() is None
        or not request.explicit_generation_actor
        or request.source_revision_id is None
        or request.source_content_hash is None
    ):
        raise InvalidNarrationState(
            "initial create request has no explicit generation/source evidence"
        )
    require_nonempty(
        request.explicit_generation_actor,
        field="explicit_generation_actor",
    )
    require_sha256(request.source_content_hash, field="source_content_hash")

    edition_state = require_row(
        store.find_one(
            NarrationEditionState,
            edition_id=edition.id,
            for_update=True,
        ),
        label="Edition Manifest pointer",
    )
    manifest = require_row(
        store.get(NarrationManifest, manifest_id),
        label="current Manifest",
    )
    if (
        edition_state.current_manifest_id != manifest.id
        or edition_state.current_manifest_revision != manifest.manifest_revision
        or manifest.edition_id != edition.id
    ):
        raise InvalidNarrationState(
            "initial pointer Manifest is not the Edition current revision"
        )
    payload = manifest.canonical_json
    if type(payload) is not dict:
        raise InvalidNarrationState("initial pointer Manifest payload is malformed")
    ready_ranges = payload.get("ready_ranges")
    last_playable = payload.get("last_playable_start_ordinal")
    if (
        manifest.status not in {"partial_ready", "ready"}
        or type(ready_ranges) is not list
        or not ready_ranges
        or type(last_playable) is not int
    ):
        return None
    if manifest.ready_ranges_json != ready_ranges:
        raise InvalidNarrationState(
            "initial pointer Manifest ready ranges changed"
        )

    version = require_row(
        store.get(NarrationScriptVersion, edition.script_version_id),
        label="script version",
    )
    script = require_row(
        store.get(NarrationScript, version.script_id),
        label="script",
    )
    if (
        version.state != "approved"
        or version.approval_request_id != request.id
        or script.id != version.script_id
        or script.novel_id != request.novel_id
        or script.document_id != document.id
        or script.revision_id != request.source_revision_id
        or script.content_hash != request.source_content_hash
        or payload.get("chapter_id") != str(document.id)
        or payload.get("source_revision_id") != str(request.source_revision_id)
        or payload.get("source_sha256") != request.source_content_hash
    ):
        raise NarrationScopeMismatch(
            "initial Edition source revision/hash provenance changed"
        )
    if working.content_hash != request.source_content_hash:
        return None

    now = utc_now()
    if pointer is None:
        pointer = DocumentNarrationState(
            id=uuid4(),
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            document_id=document.id,
            script_id=script.id,
            current_script_version_id=version.id,
            current_edition_id=edition.id,
            version=1,
            switched_actor=request.explicit_generation_actor,
            switched_at=now,
        )
        store.add(pointer)
    else:
        require_exact_int(pointer.version, field="pointer version", minimum=1)
        pointer.script_id = script.id
        pointer.current_script_version_id = version.id
        pointer.current_edition_id = edition.id
        pointer.version += 1
        pointer.switched_actor = request.explicit_generation_actor
        pointer.switched_at = now
    store.flush()
    return pointer


def switch_document_edition(
    store: NarrationStore,
    *,
    document_id: UUID,
    edition_id: UUID,
    expected_version: int,
    actor: str,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> DocumentNarrationState:
    require_fixed_scope(scope)
    require_nonempty(actor, field="actor")
    require_exact_int(expected_version, field="expected_version", minimum=0)
    document = require_row(store.get(Document, document_id, for_update=True), label="document")
    edition = require_row(store.get(NarrationEdition, edition_id), label="Edition")
    if edition.document_id != document.id:
        raise NarrationScopeMismatch("Edition/document/script pointer mismatch")
    if edition.owner_id != scope.owner_id or edition.workspace_id != scope.workspace_id:
        raise NarrationScopeMismatch("Edition is outside fixed local scope")
    if edition.state not in {"partial_ready", "ready"}:
        raise InvalidNarrationState("document pointer requires a playable Edition")
    edition_state = require_row(
        store.find_one(NarrationEditionState, edition_id=edition.id),
        label="Edition Manifest pointer",
    )
    if edition_state.current_manifest_id is None:
        raise InvalidNarrationState("playable Edition has no current Manifest")
    manifest = require_row(
        store.get(NarrationManifest, edition_state.current_manifest_id),
        label="current Manifest",
    )
    if (
        manifest.edition_id != edition.id
        or manifest.manifest_revision != edition_state.current_manifest_revision
        or manifest.status not in {"partial_ready", "ready"}
    ):
        raise InvalidNarrationState("Edition current Manifest is not playable")
    version = require_row(
        store.get(NarrationScriptVersion, edition.script_version_id), label="script version"
    )
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    if script.document_id != document.id:
        raise NarrationScopeMismatch("Edition script belongs to another document")
    script_id = script.id
    script_version_id = version.id
    row = store.find_one(
        DocumentNarrationState,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        document_id=document.id,
        for_update=True,
    )
    now = utc_now()
    if row is None:
        if expected_version != 0:
            raise NarrationCasConflict("document narration pointer does not exist")
        row = DocumentNarrationState(
            id=uuid4(),
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            document_id=document.id,
            script_id=script_id,
            current_script_version_id=script_version_id,
            current_edition_id=edition.id,
            version=1,
            switched_actor=actor,
            switched_at=now,
        )
        store.add(row)
    else:
        if row.version != expected_version:
            raise NarrationCasConflict("document narration pointer changed")
        row.script_id = script_id
        row.current_script_version_id = script_version_id
        row.current_edition_id = edition.id
        row.version = expected_version + 1
        row.switched_actor = actor
        row.switched_at = now
    store.flush()
    return row


__all__ = [
    "PlaybackResumeProjection",
    "SavePlaybackProgress",
    "initialize_initial_document_edition",
    "restore_playback_progress",
    "save_playback_progress",
    "switch_document_edition",
]
