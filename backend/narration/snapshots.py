"""Immutable source/settings snapshots used by narration pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from ..models import (
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    NarrationScopeOverride,
    NarrationSettingsSnapshot,
    NovelNarrationSettings,
)
from ..services import content_hash as document_content_hash
from ..services import markdown_to_text

from .contracts import (
    NARRATION_REVIEW_TAXONOMY_VERSION,
    NarrationRequestScope,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    SqlAlchemyNarrationStore,
    StaleNarrationInput,
    canonical_payload,
    canonical_sha256,
    require_exact_int,
    require_fixed_scope,
    require_local_novel,
    require_sha256,
    require_row,
)


SETTINGS_SNAPSHOT_SCHEMA_VERSION = "narration-settings/1"
TTS_SNAPSHOT_SOURCE = "tts_snapshot"


def _insert_tts_snapshot_or_get(
    store: SqlAlchemyNarrationStore, candidate: DocumentRevision
) -> DocumentRevision:
    """Insert one hidden snapshot or reload the partial-unique winner safely."""

    if candidate.source != TTS_SNAPSHOT_SOURCE:
        raise InvalidNarrationState("snapshot persistence requires tts_snapshot source")
    session = store.session
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise InvalidNarrationState(
            "atomic TTS snapshot persistence requires PostgreSQL"
        )
    if session.connection().get_isolation_level().upper() != "READ COMMITTED":
        raise InvalidNarrationState(
            "atomic TTS snapshot loser replay requires READ COMMITTED"
        )
    statement = (
        postgresql_insert(DocumentRevision)
        .values(
            id=candidate.id,
            document_id=candidate.document_id,
            revision_number=candidate.revision_number,
            parent_revision_id=candidate.parent_revision_id,
            restored_from_revision_id=candidate.restored_from_revision_id,
            content_markdown=candidate.content_markdown,
            content_text=candidate.content_text,
            content_hash=candidate.content_hash,
            source=candidate.source,
        )
        .on_conflict_do_nothing(
            index_elements=(
                DocumentRevision.document_id,
                DocumentRevision.content_hash,
                DocumentRevision.source,
            ),
            # Keep the fixed predicate literal so PostgreSQL can infer the
            # partial unique index even through prepared statements.
            index_where=text("source='tts_snapshot'"),
        )
        .returning(DocumentRevision)
    )
    inserted = session.scalars(statement).one_or_none()
    if inserted is not None:
        return inserted

    # Under READ COMMITTED this statement runs after any speculative-insert
    # wait and sees the committed winner without rolling back caller work.
    winner = session.scalar(
        select(DocumentRevision)
        .where(
            DocumentRevision.document_id == candidate.document_id,
            DocumentRevision.content_hash == candidate.content_hash,
            DocumentRevision.source == TTS_SNAPSHOT_SOURCE,
        )
        .execution_options(populate_existing=True)
    )
    if winner is None:
        raise IdempotencyConflict(
            "TTS snapshot conflict winner is not visible in this transaction"
        )
    if (winner.content_markdown, winner.content_text) != (
        candidate.content_markdown,
        candidate.content_text,
    ):
        raise IdempotencyConflict(
            "TTS snapshot hash collision has different immutable content"
        )
    return winner


@dataclass(frozen=True, slots=True)
class CreateTtsSnapshot:
    """Freeze the saved working copy without advancing its author baseline."""

    novel_id: UUID
    document_id: UUID
    expected_draft_version: int
    expected_content_hash: str
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local()


def create_tts_snapshot(
    store: NarrationStore, command: CreateTtsSnapshot
) -> DocumentRevision:
    """Reuse an exact revision or create one hidden, idempotent TTS revision.

    The working-copy row is locked before revision-number allocation.  The
    operation deliberately never changes ``base_revision_id`` or
    ``draft_version``; callers own the surrounding transaction.
    """

    require_fixed_scope(command.scope)
    require_exact_int(
        command.expected_draft_version,
        field="expected_draft_version",
        minimum=1,
    )
    expected_hash = require_sha256(
        command.expected_content_hash,
        field="expected_content_hash",
    )
    # Document -> working-copy matches delete/cascade order.  Do not lock Novel:
    # autosave holds the working row before updating Novel.updated_at, so a
    # Novel lock here would create the inverse edge and a PostgreSQL deadlock.
    document = require_row(
        store.get(Document, command.document_id, for_update=True),
        label="document",
    )
    working = require_row(
        store.find_one(
            DocumentWorkingCopy,
            document_id=command.document_id,
            for_update=True,
        ),
        label="document working copy",
    )
    if document.novel_id != command.novel_id:
        raise NarrationScopeMismatch("document belongs to another novel")
    require_local_novel(store, command.novel_id)
    if working.draft_version != command.expected_draft_version:
        raise NarrationCasConflict("working copy draft version changed")
    actual_hash = document_content_hash(working.content_markdown)
    if working.content_hash != expected_hash or actual_hash != expected_hash:
        raise StaleNarrationInput("working copy content hash changed")

    revisions = store.find_all(
        DocumentRevision,
        document_id=command.document_id,
        order_by=("revision_number",),
    )
    matching = [row for row in revisions if row.content_hash == expected_hash]
    if matching:
        return matching[-1]

    baseline = (working.base_revision_id, working.draft_version, working.content_hash)
    revision = DocumentRevision(
        id=uuid4(),
        document_id=command.document_id,
        revision_number=(revisions[-1].revision_number + 1) if revisions else 1,
        parent_revision_id=working.base_revision_id,
        content_markdown=working.content_markdown,
        content_text=markdown_to_text(working.content_markdown),
        content_hash=expected_hash,
        source=TTS_SNAPSHOT_SOURCE,
    )
    if isinstance(store, SqlAlchemyNarrationStore):
        revision = _insert_tts_snapshot_or_get(store, revision)
    else:
        # Unit fakes model the already-serialized path; PostgreSQL production
        # uses the partial-index upsert above for a non-poisoning loser replay.
        store.add(revision)
        store.flush()
    if (working.base_revision_id, working.draft_version, working.content_hash) != baseline:
        raise StaleNarrationInput("TTS snapshot unexpectedly changed the working copy")
    return revision


@dataclass(frozen=True, slots=True)
class CreateSettingsSnapshot:
    novel_id: UUID
    settings_version: int
    scope: NarrationRequestScope = NarrationRequestScope.fixed_local()


def snapshot_payload(
    command: CreateSettingsSnapshot,
    settings: NovelNarrationSettings,
    overrides: list[NarrationScopeOverride],
) -> dict[str, object]:
    return {
        "schema_version": SETTINGS_SNAPSHOT_SCHEMA_VERSION,
        "taxonomy_version": NARRATION_REVIEW_TAXONOMY_VERSION,
        "novel_id": str(command.novel_id),
        "settings_version": command.settings_version,
        "resolved_settings": {
            "script_review_policy": settings.script_review_policy,
            "analysis_mode": settings.analysis_mode,
            "narrator_profile_id": (
                str(settings.narrator_profile_id) if settings.narrator_profile_id else None
            ),
            "narrator_version_id": (
                str(settings.narrator_version_id) if settings.narrator_version_id else None
            ),
            "settings": canonical_payload(settings.settings_json),
            "scope_overrides": [
                {
                    "scope_kind": row.scope_kind,
                    "scope_id": str(row.scope_id),
                    "version": row.version,
                    "settings": canonical_payload(row.settings_json),
                }
                for row in overrides
            ],
        },
    }


def create_settings_snapshot(
    store: NarrationStore, command: CreateSettingsSnapshot
) -> NarrationSettingsSnapshot:
    require_fixed_scope(command.scope)
    require_local_novel(store, command.novel_id, for_update=True)
    require_exact_int(command.settings_version, field="settings_version", minimum=1)
    settings = require_row(
        store.find_one(
            NovelNarrationSettings, novel_id=command.novel_id, for_update=True
        ),
        label="narration settings",
    )
    if settings.version != command.settings_version:
        raise IdempotencyConflict("settings changed before snapshot creation")
    overrides = store.find_all(
        NarrationScopeOverride,
        novel_id=command.novel_id,
        order_by=("scope_kind", "scope_id"),
        for_update=True,
    )
    payload = snapshot_payload(command, settings, overrides)
    fingerprint = canonical_sha256(payload)
    existing = store.find_one(
        NarrationSettingsSnapshot,
        owner_id=command.scope.owner_id,
        workspace_id=command.scope.workspace_id,
        fingerprint=fingerprint,
    )
    if existing is not None:
        if existing.novel_id != command.novel_id or existing.snapshot_json != payload:
            raise IdempotencyConflict("settings snapshot fingerprint collision")
        return existing
    row = NarrationSettingsSnapshot(
        id=uuid4(),
        owner_id=command.scope.owner_id,
        workspace_id=command.scope.workspace_id,
        novel_id=command.novel_id,
        schema_version=SETTINGS_SNAPSHOT_SCHEMA_VERSION,
        taxonomy_version=NARRATION_REVIEW_TAXONOMY_VERSION,
        fingerprint=fingerprint,
        snapshot_json=payload,
    )
    store.add(row)
    store.flush()
    return row


__all__ = [
    "CreateSettingsSnapshot",
    "CreateTtsSnapshot",
    "SETTINGS_SNAPSHOT_SCHEMA_VERSION",
    "TTS_SNAPSHOT_SOURCE",
    "create_settings_snapshot",
    "create_tts_snapshot",
    "snapshot_payload",
]
