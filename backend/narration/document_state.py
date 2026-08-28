"""Chapter narration compatibility projections and explicit author actions.

Working-copy edits are compared with immutable Edition source snapshots at
query time and never trigger a write.  Edition creation remains owned by the
existing production workflow.  A confirmed Edition switch delegates to the
existing progress and document-pointer services inside the caller-owned
transaction; this module never opens or commits a transaction itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ..models import (
    Document,
    DocumentNarrationState,
    DocumentWorkingCopy,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationManifest,
    NarrationPlaybackProgress,
    NarrationScript,
    NarrationScriptVersion,
)

from .contracts import NarrationRequestScope
from .regeneration import (
    DocumentEditionHistoryProjection,
    EditionHistoryItem,
    project_document_edition_history,
)
from .progress import (
    SavePlaybackProgress,
    restore_playback_progress,
    save_playback_progress,
    switch_document_edition,
)
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    StaleNarrationInput,
    require_exact_bool,
    require_exact_int,
    require_fixed_scope,
    require_local_novel,
    require_nonempty,
    require_row,
    require_sha256,
)


DOCUMENT_NARRATION_CONTEXT_VERSION = "document-narration-context/1"

DocumentNarrationCompatibility = Literal[
    "no_current_edition",
    "current",
    "working_copy_diverged",
    "superseded",
    "unavailable",
]
EditorTimelineMode = Literal[
    "none",
    "exact_working_copy",
    "immutable_edition_only",
]
SourceNoticeCode = Literal[
    "NO_CURRENT_EDITION",
    "CURRENT_SOURCE_SNAPSHOT",
    "OLD_SOURCE_SNAPSHOT",
    "HISTORICAL_EDITION",
    "EDITION_UNAVAILABLE",
]


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


@dataclass(frozen=True, slots=True)
class NarrationSourceSnapshotProjection:
    revision_id: UUID
    content_hash: str
    matches_working_copy: bool


@dataclass(frozen=True, slots=True)
class DocumentNarrationContextProjection:
    contract_version: str
    document_id: UUID
    novel_id: UUID
    pointer_version: int
    current_script_version_id: UUID | None
    current_edition_id: UUID | None
    active_edition_id: UUID | None
    active_is_current: bool
    working_copy_draft_version: int
    working_copy_content_hash: str
    source_snapshot: NarrationSourceSnapshotProjection | None
    compatibility: DocumentNarrationCompatibility
    source_notice_code: SourceNoticeCode
    editor_timeline_mode: EditorTimelineMode
    old_draft_subtitle_required: bool
    explicit_update_required: bool
    can_request_update: bool
    available_current_source_edition_ids: tuple[UUID, ...]
    edition_history: DocumentEditionHistoryProjection


@dataclass(frozen=True, slots=True)
class ExplicitNarrationUpdateIntent:
    """A validated input for the existing ``narration-requests`` endpoint.

    Constructing this object has no side effects.  The production endpoint must
    repeat the working-copy CAS check before it creates/reuses a source snapshot.
    """

    document_id: UUID
    intent: Literal["update"]
    expected_draft_version: int
    expected_content_hash: str
    expected_settings_version: int
    force_review: bool
    idempotency_key: str
    prior_current_edition_id: UUID
    expected_pointer_version: int
    explicitly_requested: Literal[True]


@dataclass(frozen=True, slots=True)
class EditionSwitchConfirmationProjection:
    """Read-only target shown before the existing CAS pointer switch command."""

    document_id: UUID
    target_edition_id: UUID
    current_edition_id: UUID | None
    expected_pointer_version: int
    source_revision_id: UUID
    source_content_hash: str
    source_status: Literal["current", "working_copy_diverged", "superseded"]
    old_draft_subtitle_required: bool
    default_start_ready: bool
    resume_available: bool
    explicit_start_segment_id: UUID | None
    confirmation_required: Literal[True]


@dataclass(frozen=True, slots=True)
class ExplicitEditionSwitchResult:
    document_id: UUID
    current_edition_id: UUID
    pointer_version: int
    switch_mode: Literal["immediate", "next_playback"]
    start_segment_id: UUID | None
    manifest_revision: int
    playback_progress_id: UUID | None


def _pointer(
    store: NarrationStore,
    *,
    document_id: UUID,
    scope: NarrationRequestScope,
    for_update: bool = False,
) -> DocumentNarrationState | None:
    return store.find_one(
        DocumentNarrationState,
        for_update=for_update,
        owner_id=scope.owner_id,
        workspace_id=scope.workspace_id,
        document_id=document_id,
    )


def _history_item(
    history: DocumentEditionHistoryProjection,
    edition_id: UUID,
) -> EditionHistoryItem:
    item = next(
        (candidate for candidate in history.editions if candidate.edition_id == edition_id),
        None,
    )
    if item is None:
        raise NarrationScopeMismatch("active Edition is outside this document history")
    return item


def _compatibility(
    item: EditionHistoryItem | None,
    *,
    current_edition_id: UUID | None,
    working_copy_content_hash: str,
) -> tuple[DocumentNarrationCompatibility, SourceNoticeCode]:
    if item is None:
        return "no_current_edition", "NO_CURRENT_EDITION"
    if not item.playable or item.state == "unavailable":
        return "unavailable", "EDITION_UNAVAILABLE"
    if item.edition_id != current_edition_id:
        return "superseded", "HISTORICAL_EDITION"
    if item.source_content_hash != working_copy_content_hash:
        return "working_copy_diverged", "OLD_SOURCE_SNAPSHOT"
    return "current", "CURRENT_SOURCE_SNAPSHOT"


def project_document_narration_context(
    store: NarrationStore,
    *,
    document_id: UUID,
    active_edition_id: UUID | None = None,
    profile_id: str | None = None,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> DocumentNarrationContextProjection:
    """Project current/old-source state without mutating any authority row.

    ``active_edition_id`` represents an explicit historical selection or an
    already-bound playback session.  When omitted, it follows the persisted
    current pointer.  A document with no current pointer stays unbound even if
    historical Editions exist; this prevents a query from silently selecting
    one on the author's behalf.
    """

    require_fixed_scope(scope)
    document = require_row(store.get(Document, document_id), label="document")
    require_local_novel(store, document.novel_id)
    working = require_row(
        store.find_one(DocumentWorkingCopy, document_id=document.id),
        label="document working copy",
    )
    require_exact_int(working.draft_version, field="working copy draft_version", minimum=1)
    require_sha256(working.content_hash, field="working copy content_hash")
    history = project_document_edition_history(
        store,
        document_id=document.id,
        profile_id=profile_id,
        scope=scope,
    )
    pointer = _pointer(store, document_id=document.id, scope=scope)
    if (history.pointer_version != (pointer.version if pointer else 0)):
        raise InvalidNarrationState("document narration history pointer drifted")
    if history.current_edition_id != (pointer.current_edition_id if pointer else None):
        raise InvalidNarrationState("document narration history selected another current Edition")
    if pointer is not None and pointer.current_edition_id is not None:
        current_edition = require_row(
            store.get(NarrationEdition, pointer.current_edition_id),
            label="current Edition",
        )
        current_version = require_row(
            store.get(NarrationScriptVersion, current_edition.script_version_id),
            label="current script version",
        )
        current_script = require_row(
            store.get(NarrationScript, current_version.script_id),
            label="current script",
        )
        if (
            current_edition.document_id != document.id
            or current_edition.script_version_id != pointer.current_script_version_id
            or current_script.id != pointer.script_id
            or current_script.document_id != document.id
        ):
            raise NarrationScopeMismatch(
                "document narration pointer provenance is inconsistent"
            )

    resolved_active_id = (
        active_edition_id
        if active_edition_id is not None
        else history.current_edition_id
    )
    active = (
        _history_item(history, resolved_active_id)
        if resolved_active_id is not None
        else None
    )
    compatibility, notice = _compatibility(
        active,
        current_edition_id=history.current_edition_id,
        working_copy_content_hash=working.content_hash,
    )
    source_matches = (
        active is not None and active.source_content_hash == working.content_hash
    )
    source_snapshot = (
        NarrationSourceSnapshotProjection(
            revision_id=active.source_revision_id,
            content_hash=active.source_content_hash,
            matches_working_copy=source_matches,
        )
        if active is not None
        else None
    )
    exact_source_candidates = tuple(
        item.edition_id
        for item in history.editions
        if item.edition_id != history.current_edition_id
        and item.source_content_hash == working.content_hash
        and item.playable
        and item.switch_allowed
    )
    return DocumentNarrationContextProjection(
        contract_version=DOCUMENT_NARRATION_CONTEXT_VERSION,
        document_id=document.id,
        novel_id=document.novel_id,
        pointer_version=history.pointer_version,
        current_script_version_id=(
            pointer.current_script_version_id if pointer is not None else None
        ),
        current_edition_id=history.current_edition_id,
        active_edition_id=(active.edition_id if active is not None else None),
        active_is_current=(active is not None and active.is_current),
        working_copy_draft_version=working.draft_version,
        working_copy_content_hash=working.content_hash,
        source_snapshot=source_snapshot,
        compatibility=compatibility,
        source_notice_code=notice,
        editor_timeline_mode=(
            "none"
            if active is None
            else "exact_working_copy"
            if source_matches
            else "immutable_edition_only"
        ),
        old_draft_subtitle_required=(active is not None and not source_matches),
        explicit_update_required=(
            history.current_edition_id is not None
            and next(
                item
                for item in history.editions
                if item.edition_id == history.current_edition_id
            ).source_content_hash
            != working.content_hash
        ),
        can_request_update=history.current_edition_id is not None,
        available_current_source_edition_ids=exact_source_candidates,
        edition_history=history,
    )


def create_explicit_narration_update_intent(
    store: NarrationStore,
    *,
    document_id: UUID,
    expected_draft_version: int,
    expected_content_hash: str,
    expected_settings_version: int,
    force_review: bool,
    idempotency_key: str,
    explicitly_requested: bool,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> ExplicitNarrationUpdateIntent:
    """Validate an author-triggered update after the editor save barrier.

    Autosave and ordinary input must never call this function.  It intentionally
    returns an intent rather than invoking the production workflow.
    """

    require_fixed_scope(scope)
    if require_exact_bool(explicitly_requested, field="explicitly_requested") is not True:
        raise InvalidNarrationState("updating narration requires an explicit author action")
    require_exact_int(expected_draft_version, field="expected_draft_version", minimum=1)
    require_sha256(expected_content_hash, field="expected_content_hash")
    require_exact_int(
        expected_settings_version,
        field="expected_settings_version",
        minimum=1,
    )
    require_exact_bool(force_review, field="force_review")
    require_nonempty(idempotency_key, field="idempotency_key")
    if _IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
        raise InvalidNarrationState("idempotency_key does not match the production contract")

    document = require_row(store.get(Document, document_id), label="document")
    require_local_novel(store, document.novel_id)
    working = require_row(
        store.find_one(
            DocumentWorkingCopy,
            document_id=document.id,
            for_update=True,
        ),
        label="document working copy",
    )
    if working.draft_version != expected_draft_version:
        raise StaleNarrationInput("working copy draft_version changed before update")
    if working.content_hash != expected_content_hash:
        raise StaleNarrationInput("working copy content_hash changed before update")
    pointer = _pointer(
        store,
        document_id=document.id,
        scope=scope,
        for_update=True,
    )
    if pointer is None or pointer.current_edition_id is None:
        raise InvalidNarrationState("update narration requires a current Edition")
    return ExplicitNarrationUpdateIntent(
        document_id=document.id,
        intent="update",
        expected_draft_version=working.draft_version,
        expected_content_hash=working.content_hash,
        expected_settings_version=expected_settings_version,
        force_review=force_review,
        idempotency_key=idempotency_key,
        prior_current_edition_id=pointer.current_edition_id,
        expected_pointer_version=pointer.version,
        explicitly_requested=True,
    )


def project_edition_switch_confirmation(
    store: NarrationStore,
    *,
    document_id: UUID,
    target_edition_id: UUID,
    profile_id: str | None = None,
    explicit_start_segment_id: UUID | None = None,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> EditionSwitchConfirmationProjection:
    """Validate a history selection, but never update the current pointer."""

    context = project_document_narration_context(
        store,
        document_id=document_id,
        active_edition_id=target_edition_id,
        profile_id=profile_id,
        scope=scope,
    )
    target = _history_item(context.edition_history, target_edition_id)
    if target.is_current:
        raise InvalidNarrationState("selected Edition is already current")
    if not target.switch_allowed:
        if not target.playable or explicit_start_segment_id is None:
            raise InvalidNarrationState("selected Edition has no legal playable switch target")
        edition = require_row(
            store.get(NarrationEdition, target.edition_id),
            label="selected Edition",
        )
        manifest = _current_manifest(store, edition=edition)
        _legal_immediate_start(
            store,
            edition=edition,
            manifest=manifest,
            requested_segment_id=explicit_start_segment_id,
        )
    return EditionSwitchConfirmationProjection(
        document_id=context.document_id,
        target_edition_id=target.edition_id,
        current_edition_id=context.current_edition_id,
        expected_pointer_version=context.pointer_version,
        source_revision_id=target.source_revision_id,
        source_content_hash=target.source_content_hash,
        source_status=target.source_status,
        old_draft_subtitle_required=(
            target.source_content_hash != context.working_copy_content_hash
        ),
        default_start_ready=target.default_start_ready,
        resume_available=target.resume_available,
        explicit_start_segment_id=explicit_start_segment_id,
        confirmation_required=True,
    )


def _current_manifest(
    store: NarrationStore,
    *,
    edition: NarrationEdition,
) -> NarrationManifest:
    state = require_row(
        store.find_one(
            NarrationEditionState,
            edition_id=edition.id,
            for_update=True,
        ),
        label="Edition Manifest pointer",
    )
    if state.current_manifest_id is None or state.current_manifest_revision is None:
        raise InvalidNarrationState("selected Edition has no current Manifest")
    manifest = require_row(
        store.get(NarrationManifest, state.current_manifest_id),
        label="current Manifest",
    )
    if (
        manifest.edition_id != edition.id
        or manifest.manifest_revision != state.current_manifest_revision
        or manifest.status not in {"partial_ready", "ready"}
    ):
        raise InvalidNarrationState("selected Edition current Manifest is not playable")
    return manifest


def _legal_immediate_start(
    store: NarrationStore,
    *,
    edition: NarrationEdition,
    manifest: NarrationManifest,
    requested_segment_id: UUID | None,
) -> NarrationEditionSegment:
    payload = manifest.canonical_json
    if type(payload) is not dict:
        raise InvalidNarrationState("selected Edition Manifest payload is malformed")
    public_segments = payload.get("segments")
    ready_ranges = payload.get("ready_ranges")
    if type(public_segments) is not list or type(ready_ranges) is not list:
        raise InvalidNarrationState("selected Edition Manifest indexes are malformed")
    target_public: dict[str, object] | None = None
    if requested_segment_id is None:
        if payload.get("default_start_ready") is not True:
            raise InvalidNarrationState(
                "immediate switch requires an explicit legal start segment"
            )
        target_public = next(
            (
                item
                for item in public_segments
                if type(item) is dict and item.get("ordinal") == 0
            ),
            None,
        )
    else:
        target_public = next(
            (
                item
                for item in public_segments
                if type(item) is dict
                and item.get("segment_id") == str(requested_segment_id)
            ),
            None,
        )
    if (
        target_public is None
        or target_public.get("render_status") != "ready"
        or type(target_public.get("ordinal")) is not int
        or type(target_public.get("segment_id")) is not str
    ):
        raise InvalidNarrationState("immediate switch start segment is not ready")
    ordinal = target_public["ordinal"]
    ready_range = next(
        (
            item
            for item in ready_ranges
            if type(item) is dict
            and type(item.get("start_ordinal")) is int
            and type(item.get("end_ordinal_exclusive")) is int
            and type(item.get("last_playable_start_ordinal")) is int
            and item["start_ordinal"] <= ordinal < item["end_ordinal_exclusive"]
            and ordinal <= item["last_playable_start_ordinal"]
        ),
        None,
    )
    if ready_range is None:
        raise InvalidNarrationState("immediate switch start has no legal ready window")
    try:
        segment_id = UUID(target_public["segment_id"])
    except (TypeError, ValueError) as error:
        raise InvalidNarrationState(
            "immediate switch Manifest segment identity is malformed"
        ) from error
    row = require_row(
        store.find_one(
            NarrationEditionSegment,
            edition_id=edition.id,
            segment_id=segment_id,
        ),
        label="Edition start segment",
    )
    if row.ordinal != ordinal or row.render_state != "ready":
        raise InvalidNarrationState("Edition start segment differs from its Manifest")
    return row


def switch_document_narration_edition_explicitly(
    store: NarrationStore,
    *,
    document_id: UUID,
    target_edition_id: UUID,
    expected_pointer_version: int,
    switch_mode: Literal["immediate", "next_playback"],
    start_segment_id: UUID | None,
    profile_id: str,
    playback_rate_millis: int,
    actor: str,
    confirmed: bool,
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local(),
) -> ExplicitEditionSwitchResult:
    """Apply the author's confirmed CAS switch in the caller's transaction.

    Immediate switching stores a precise zero-offset progress row for a legal
    ready start before moving the pointer.  ``next_playback`` preserves an
    existing legal resume or relies on a ready chapter start.  Any exception is
    expected to roll back with the caller-owned transaction.
    """

    require_fixed_scope(scope)
    if require_exact_bool(confirmed, field="confirmed") is not True:
        raise InvalidNarrationState("Edition switching requires explicit confirmation")
    require_exact_int(
        expected_pointer_version,
        field="expected_pointer_version",
        minimum=0,
    )
    require_exact_int(
        playback_rate_millis,
        field="playback_rate_millis",
        minimum=250,
        maximum=4000,
    )
    require_nonempty(profile_id, field="profile_id")
    require_nonempty(actor, field="actor")
    if switch_mode not in {"immediate", "next_playback"}:
        raise InvalidNarrationState("unsupported Edition switch mode")
    if switch_mode == "next_playback" and start_segment_id is not None:
        raise InvalidNarrationState("next_playback cannot name an immediate start")

    document = require_row(
        store.get(Document, document_id, for_update=True), label="document"
    )
    require_local_novel(store, document.novel_id)
    pointer = _pointer(
        store,
        document_id=document.id,
        scope=scope,
        for_update=True,
    )
    actual_pointer_version = pointer.version if pointer is not None else 0
    if actual_pointer_version != expected_pointer_version:
        raise NarrationCasConflict("document narration pointer changed before confirmation")
    if pointer is not None and pointer.current_edition_id == target_edition_id:
        raise InvalidNarrationState("selected Edition is already current")

    confirmation = project_edition_switch_confirmation(
        store,
        document_id=document.id,
        target_edition_id=target_edition_id,
        profile_id=profile_id,
        explicit_start_segment_id=(
            start_segment_id if switch_mode == "immediate" else None
        ),
        scope=scope,
    )
    if confirmation.expected_pointer_version != expected_pointer_version:
        raise NarrationCasConflict("Edition confirmation used a stale pointer")
    edition = require_row(
        store.get(NarrationEdition, target_edition_id, for_update=True),
        label="selected Edition",
    )
    if edition.document_id != document.id:
        raise NarrationScopeMismatch("selected Edition belongs to another document")
    manifest = _current_manifest(store, edition=edition)

    progress: NarrationPlaybackProgress | None = None
    resolved_start_segment_id: UUID | None = None
    if switch_mode == "immediate":
        start = _legal_immediate_start(
            store,
            edition=edition,
            manifest=manifest,
            requested_segment_id=start_segment_id,
        )
        prior_progress = store.find_one(
            NarrationPlaybackProgress,
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            profile_id=profile_id,
            edition_id=edition.id,
            for_update=True,
        )
        progress = save_playback_progress(
            store,
            SavePlaybackProgress(
                profile_id=profile_id,
                edition_id=edition.id,
                manifest_revision=manifest.manifest_revision,
                edition_segment_id=start.id,
                offset_ms=0,
                last_legal_start_ordinal=start.ordinal,
                playback_rate_millis=playback_rate_millis,
                expected_updated_at=(
                    prior_progress.updated_at if prior_progress is not None else None
                ),
                scope=scope,
            ),
        )
        resolved_start_segment_id = start.segment_id
    else:
        payload = manifest.canonical_json
        if type(payload) is not dict:
            raise InvalidNarrationState("selected Edition Manifest payload is malformed")
        if payload.get("default_start_ready") is not True and restore_playback_progress(
            store,
            profile_id=profile_id,
            edition_id=edition.id,
            scope=scope,
        ) is None:
            raise InvalidNarrationState(
                "next_playback requires a ready chapter start or legal resume"
            )

    updated = switch_document_edition(
        store,
        document_id=document.id,
        edition_id=edition.id,
        expected_version=expected_pointer_version,
        actor=actor,
        scope=scope,
    )
    return ExplicitEditionSwitchResult(
        document_id=document.id,
        current_edition_id=edition.id,
        pointer_version=updated.version,
        switch_mode=switch_mode,
        start_segment_id=resolved_start_segment_id,
        manifest_revision=manifest.manifest_revision,
        playback_progress_id=(progress.id if progress is not None else None),
    )
__all__ = [
    "DOCUMENT_NARRATION_CONTEXT_VERSION",
    "DocumentNarrationCompatibility",
    "DocumentNarrationContextProjection",
    "EditionSwitchConfirmationProjection",
    "EditorTimelineMode",
    "ExplicitNarrationUpdateIntent",
    "ExplicitEditionSwitchResult",
    "NarrationSourceSnapshotProjection",
    "SourceNoticeCode",
    "create_explicit_narration_update_intent",
    "project_document_narration_context",
    "project_edition_switch_confirmation",
    "switch_document_narration_edition_explicitly",
]
