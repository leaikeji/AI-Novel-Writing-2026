from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TypeVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    MediaAsset,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationManifest,
    NarrationRenderAsset,
    NarrationRequest,
    NarrationRequestSource,
    NarrationScript,
    NarrationScriptIssue,
    NarrationSegment,
    NarrationSegmentRender,
    Novel,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.services import content_hash
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NarrationRequestScope,
    ReviewIssue,
    ReviewIssueSeverity,
)
from backend.narration.digest_keyring import (
    DigestKeyring,
    DigestKeyringError,
    HmacDigestKey,
)
from backend.narration.editions import (
    CreateEdition,
    EditionSegmentInput,
    advance_edition_segment_state,
    create_edition,
)
from backend.narration.manifest import (
    BufferPolicy,
    INITIAL_BUFFER_POLICY,
    ManifestFailure,
    ManifestSegmentInput,
    PublishManifest,
    publish_manifest,
)
from backend.narration.progress import SavePlaybackProgress, save_playback_progress
from backend.narration.progress import switch_document_edition
from backend.narration.jobs import JobFence, JobLease, PublicationFenceContext
from backend.narration.resource_locks import ResourceFence, ResourceLease
from backend.narration.renders import (
    CreateRender,
    LEGACY_RENDER_CANONICAL_INPUT_VERSION,
    LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION,
    SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION,
    compute_render_fingerprint,
    create_or_reuse_render,
    derive_render_identity,
    publish_render_ready,
    render_job_input_hash,
)
from backend.narration import synthesis_policy
from backend.narration.requests import (
    CreateNarrationRequest,
    RequestSource,
    advance_request_state,
    create_request,
)
from backend.narration.script_versions import (
    CreateScriptDraft,
    ScriptSegmentInput,
    approve_script_version,
    create_script_draft,
    derive_script_status,
)
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    ManifestRevisionCollision,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationServiceError,
    StaleNarrationInput,
    VoiceRightsUnavailable,
    canonical_sha256,
)
from backend.narration.settings import NarrationSettingsUpdate, update_settings
from backend.narration.snapshots import (
    CreateSettingsSnapshot,
    CreateTtsSnapshot,
    create_settings_snapshot,
    create_tts_snapshot,
)
from tests.narration.digest_fixtures import TEST_DIGEST_KEY, TEST_DIGEST_KEYRING


T = TypeVar("T")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
NOW = datetime(2026, 8, 26, 0, 0, tzinfo=UTC)


class MemoryNarrationStore:
    """Transaction-shaped fake; it never opens a database or performs I/O."""

    def __init__(self) -> None:
        self.rows: dict[type[object], list[object]] = defaultdict(list)
        self.flush_count = 0
        self.resource_fences: dict[UUID, ResourceFence] = {}

    def add(self, row: object) -> None:
        if (
            isinstance(row, NarrationScriptIssue)
            and row.segment_id is not None
            and self.get(NarrationSegment, row.segment_id) is None
        ):
            raise AssertionError("test fake enforces issue->segment insertion order")
        self.rows[type(row)].append(row)

    def flush(self) -> None:
        self.flush_count += 1
        for row in self.rows[NarrationRequest]:
            row.allows_edition = row.intent != "analyze_only"
            row.allows_render = row.intent != "analyze_only"
        from backend.models import NarrationScriptVersion

        for row in self.rows[NarrationScriptVersion]:
            row.is_approved = row.state == "approved"

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None:
        del for_update
        return next(
            (
                row
                for row in self.rows[model]
                if getattr(row, "id", getattr(row, "edition_id", None)) == row_id
            ),
            None,
        )  # type: ignore[return-value]

    def find_one(
        self, model: type[T], *, for_update: bool = False, **filters: object
    ) -> T | None:
        del for_update
        return next(
            (
                row
                for row in self.rows[model]
                if all(getattr(row, key) == value for key, value in filters.items())
            ),
            None,
        )  # type: ignore[return-value]

    def find_all(
        self,
        model: type[T],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[T]:
        del for_update
        result = [
            row
            for row in self.rows[model]
            if all(getattr(row, key) == value for key, value in filters.items())
        ]
        if order_by:
            result.sort(key=lambda row: tuple(getattr(row, key) for key in order_by))
        return result  # type: ignore[return-value]

    def consume_render_publication_context(
        self,
        *,
        publication_context: PublicationFenceContext,
        source_job_id: UUID,
        request_id: UUID,
        novel_id: UUID,
        actual_result_digest: str,
    ) -> None:
        if type(publication_context) is not PublicationFenceContext:
            raise InvalidNarrationState("stale render result fence")
        job_fence = publication_context.job_lease.fence
        resource_fence = publication_context.resource_lease.fence
        job = self.get(BackgroundJob, source_job_id)
        attempt = self.get(BackgroundJobAttempt, job_fence.attempt_id)
        if (
            job is None
            or attempt is None
            or job_fence.job_id != source_job_id
            or attempt.job_id != job.id
            or attempt.lease_token != job_fence.lease_token
            or attempt.lease_generation != job_fence.lease_generation
            or type(resource_fence) is not ResourceFence
            or resource_fence != self.resource_fences.get(job.id)
            or resource_fence.resource_key != "moss-nano:inference"
            or attempt.completed_at is not None
            or job.state != "running"
            or job.request_id != request_id
            or job.novel_id != novel_id
            or attempt.lease_until <= NOW
        ):
            raise InvalidNarrationState("stale render result fence")
        attempt.completed_at = NOW
        attempt.actual_result_digest = actual_result_digest
        job.state = "succeeded"


def _novel(novel_id: UUID | None = None) -> Novel:
    return Novel(
        id=novel_id or uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        title="book",
        author_name="author",
        description="",
        writing_type="novel",
        audience="general",
        genre="fiction",
        subgenre="",
        idea="",
        template_name="",
        template_data={},
        cover_mode="none",
        cover_image_data="",
        outline_target_chapters=0,
        highlight="",
        background="",
        main_plot="",
        story_ledger_version=1,
        version=1,
    )


def _seed_document(store: MemoryNarrationStore, novel: Novel, marker: str = "a") -> tuple[Document, DocumentRevision]:
    document = Document(
        id=uuid4(), novel_id=novel.id, kind="chapter", title="chapter", position=1,
        status="draft", version=1,
    )
    revision = DocumentRevision(
        id=uuid4(), document_id=document.id, revision_number=1,
        content_markdown="text", content_text="text", content_hash=marker * 64,
        source="manual",
    )
    store.add(document)
    store.add(revision)
    return document, revision


def test_tts_snapshot_reuses_exact_revision_and_never_advances_working_copy() -> None:
    store = MemoryNarrationStore()
    novel = _novel()
    store.add(novel)
    document, revision = _seed_document(store, novel)
    revision.content_hash = content_hash(revision.content_markdown)
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=7,
        content_markdown=revision.content_markdown,
        content_hash=revision.content_hash,
    )
    store.add(working)
    command = CreateTtsSnapshot(
        novel_id=novel.id,
        document_id=document.id,
        expected_draft_version=7,
        expected_content_hash=revision.content_hash,
    )
    assert create_tts_snapshot(store, command) is revision
    assert len(store.rows[DocumentRevision]) == 1
    assert (working.base_revision_id, working.draft_version) == (revision.id, 7)

    working.content_markdown = "## 新正文\n\n第二段"
    working.content_hash = content_hash(working.content_markdown)
    command = replace(
        command,
        expected_draft_version=7,
        expected_content_hash=working.content_hash,
    )
    snapshot = create_tts_snapshot(store, command)
    assert snapshot.source == "tts_snapshot"
    assert snapshot.revision_number == 2
    assert snapshot.content_text == "新正文\n\n第二段"
    assert create_tts_snapshot(store, command) is snapshot
    assert len(store.rows[DocumentRevision]) == 2
    assert (working.base_revision_id, working.draft_version, working.content_hash) == (
        revision.id,
        7,
        content_hash(working.content_markdown),
    )

    with pytest.raises(NarrationCasConflict):
        create_tts_snapshot(store, replace(command, expected_draft_version=6))
    with pytest.raises(StaleNarrationInput):
        create_tts_snapshot(store, replace(command, expected_content_hash=SHA_B))

    working.content_markdown = "被绕过服务层篡改的正文"
    with pytest.raises(StaleNarrationInput):
        create_tts_snapshot(store, command)


def _seed_voice(store: MemoryNarrationStore, novel: Novel) -> tuple[VoiceProfile, VoiceProfileVersion, VoiceRightsRecord]:
    rights = VoiceRightsRecord(
        id=uuid4(), owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id, source_kind="owned_recording", source_identifier="private-ref",
        notice_version="rights/1", purpose="narration", commercial_use=True,
        redistribution=False, voice_cloning=True, confirmed_actor="owner",
        confirmed_at=NOW, expires_at=NOW + timedelta(days=365), risk_flags_json={},
    )
    profile = VoiceProfile(
        id=uuid4(), owner_id=LOCAL_OWNER_ID, workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel.id, name="voice", status="active", version=1,
    )
    version = VoiceProfileVersion(
        id=uuid4(), profile_id=profile.id, owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID, version_number=1, source_type="uploaded",
        state="locked", rights_record_id=rights.id, language="zh-CN", parameters_json={},
        fingerprint=SHA_B, quality_state="accepted",
        activation_basis="preview_confirmed", validation_basis="human_accepted",
        locked_actor="owner", locked_at=NOW,
        seed=7,
    )
    profile.current_version_id = version.id
    store.add(rights)
    store.add(profile)
    store.add(version)
    return profile, version, rights


def _request_command(
    novel: Novel,
    document: Document,
    revision: DocumentRevision,
    settings_fingerprint: str,
    *,
    key: str = "request-1",
    force_review: bool = False,
) -> CreateNarrationRequest:
    return CreateNarrationRequest(
        novel_id=novel.id,
        document_id=document.id,
        source_revision_id=revision.id,
        source_content_hash=revision.content_hash,
        intent="create",
        idempotency_key=key,
        settings_fingerprint=settings_fingerprint,
        force_review=force_review,
        effective_policy="always_review" if force_review else "blockers_only",
        explicit_generation_intent_at=NOW,
        explicit_generation_actor="owner",
    )


def test_request_replay_scope_and_analyze_only_are_fail_closed() -> None:
    store = MemoryNarrationStore()
    novel_a, novel_b = _novel(), _novel()
    store.add(novel_a)
    store.add(novel_b)
    doc_a, rev_a = _seed_document(store, novel_a)
    command = _request_command(novel_a, doc_a, rev_a, SHA_A)
    first = create_request(store, command)
    assert create_request(store, command) is first
    assert len(store.rows[NarrationRequest]) == 1
    with pytest.raises(IdempotencyConflict):
        create_request(store, replace(command, settings_fingerprint=SHA_B))
    with pytest.raises(NarrationScopeMismatch):
        create_request(store, _request_command(novel_b, doc_a, rev_a, SHA_A, key="cross"))

    analyze = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel_a.id,
            document_id=doc_a.id,
            source_revision_id=rev_a.id,
            source_content_hash=rev_a.content_hash,
            intent="analyze_only",
            idempotency_key="scan",
            settings_fingerprint=SHA_A,
        ),
    )
    assert analyze.intent == "analyze_only"
    assert analyze.allows_edition is False and analyze.allows_render is False
    with pytest.raises(NarrationServiceError):
        create_request(
            store,
            CreateNarrationRequest(
                novel_id=novel_a.id,
                document_id=doc_a.id,
                intent="analyze_only",
                idempotency_key="scan-unbound",
                settings_fingerprint=SHA_A,
            ),
        )
    doc_b, rev_b = _seed_document(store, novel_a, "b")
    scan_all = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel_a.id,
            intent="analyze_only",
            idempotency_key="scan-all",
            settings_fingerprint=SHA_A,
            sources=(
                RequestSource(doc_a.id, rev_a.id, rev_a.content_hash, 0),
                RequestSource(doc_b.id, rev_b.id, rev_b.content_hash, 1),
            ),
        ),
    )
    assert len(store.find_all(NarrationRequestSource, request_id=scan_all.id)) == 2
    edition_count = len(store.rows[NarrationEdition])
    with pytest.raises(InvalidNarrationState):
        create_edition(
            store,
            CreateEdition(
                novel_id=novel_a.id,
                document_id=doc_a.id,
                request_id=analyze.id,
                script_version_id=uuid4(),
                settings_snapshot_id=uuid4(),
                tts_fingerprint=SHA_A,
                tokenizer_fingerprint=SHA_A,
                normalizer_fingerprint=SHA_A,
                postprocess_fingerprint=SHA_A,
                buffer_policy_version=INITIAL_BUFFER_POLICY.version,
                created_actor="owner",
                segments=(),
                digest_keyring=TEST_DIGEST_KEYRING,
            ),
        )
    assert len(store.rows[NarrationEdition]) == edition_count


def _script_segments(count: int = 2) -> tuple[ScriptSegmentInput, ...]:
    return tuple(
        ScriptSegmentInput(
            segment_id=uuid4(),
            ordinal=ordinal,
            segment_kind="narration",
            paragraph_ordinal=ordinal,
            source_block_key=f"block-{ordinal}",
            source_start_utf16=ordinal * 5,
            source_end_utf16=ordinal * 5 + 4,
            source_text=f"text-{ordinal}",
            spoken_text=f"segment-{ordinal}",
            local_hash=str(ordinal) * 64,
            speaker_kind="narrator",
            casting_json={"source": "narrator"},
            evidence_json={},
            confidence="high",
            pause_before_ms=0,
            pause_after_ms=0,
            manual_override=False,
        )
        for ordinal in range(count)
    )


def _approved_foundation(
    store: MemoryNarrationStore, *, force_review: bool = False, with_warning: bool = False
) -> tuple[
    Novel,
    Document,
    DocumentRevision,
    object,
    NarrationRequest,
    NarrationScript,
    object,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
]:
    novel = _novel()
    store.add(novel)
    document, revision = _seed_document(store, novel)
    profile, voice, rights = _seed_voice(store, novel)
    settings = update_settings(
        store,
        NarrationSettingsUpdate(
            novel_id=novel.id,
            script_review_policy="always_review" if force_review else "blockers_only",
            analysis_mode="local_rules_only",
            settings_json={"language": "zh-CN"},
            expected_version=0,
        ),
    )
    snapshot = create_settings_snapshot(
        store,
        CreateSettingsSnapshot(
            novel_id=novel.id,
            settings_version=settings.version,
        ),
    )
    request = create_request(
        store,
        _request_command(
            novel, document, revision, snapshot.fingerprint, force_review=force_review
        ),
    )
    frozen_segments = _script_segments()
    issues = (
        ReviewIssue(
            code="W_GENERIC_VOICE_FALLBACK",
            severity=ReviewIssueSeverity.WARNING,
            evidence_digest=SHA_C,
            segment_id=frozen_segments[0].segment_id,
        ),
    ) if with_warning else ()
    version = create_script_draft(
        store,
        CreateScriptDraft(
            novel_id=novel.id,
            document_id=document.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            settings_fingerprint=snapshot.fingerprint,
            analyzer_fingerprint=SHA_A,
            rules_fingerprint=SHA_B,
            idempotency_key="script-1",
            effective_policy="always_review" if force_review else "blockers_only",
            segments=frozen_segments,
            issues=issues,
        ),
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="analyzing",
        novel_id=novel.id,
        actor="analyzer",
    )
    if version.state == "review_required":
        request = advance_request_state(
            store,
            request.id,
            expected_version=request.version,
            new_state="review_required",
            novel_id=novel.id,
            actor="analyzer",
        )
    script = store.get(NarrationScript, version.script_id)
    assert script is not None
    return (
        novel, document, revision, snapshot, request, script, version, profile, voice, rights
    )


def test_settings_snapshot_approval_terminal_and_stale_derivation() -> None:
    store = MemoryNarrationStore()
    novel, _doc, revision, snapshot, request, _script, version, *_ = _approved_foundation(
        store, force_review=True
    )
    assert create_settings_snapshot(
        store,
        CreateSettingsSnapshot(
            novel_id=novel.id,
            settings_version=1,
        ),
    ) is snapshot
    with pytest.raises(NarrationCasConflict):
        update_settings(
            store,
            NarrationSettingsUpdate(
                novel_id=novel.id,
                script_review_policy="blockers_only",
                analysis_mode="local_rules_only",
                settings_json={},
                expected_version=0,
            ),
        )
    with pytest.raises(InvalidNarrationState):
        approve_script_version(
            store, version.id, request_id=request.id, actor_type="system", actor_id="rules-v1"
        )
    approved = approve_script_version(
        store, version.id, request_id=request.id, actor_type="owner", actor_id="owner"
    )
    assert approved.state == "approved" and approved.approval_kind == "manual_after_review"
    other_request = create_request(
        store,
        _request_command(novel, _doc, revision, snapshot.fingerprint, key="request-2", force_review=True),
    )
    with pytest.raises(InvalidNarrationState):
        approve_script_version(
            store, version.id, request_id=other_request.id, actor_type="owner", actor_id="owner"
        )
    assert derive_script_status(
        store,
        version.id,
        current_revision_id=revision.id,
        current_content_hash=SHA_C,
        current_settings_fingerprint=snapshot.fingerprint,
    ) == "working_copy_diverged"
    assert derive_script_status(
        store,
        version.id,
        current_revision_id=revision.id,
        current_content_hash=revision.content_hash,
        current_settings_fingerprint=SHA_C,
    ) == "superseded"


def test_script_children_are_frozen_and_issue_fk_order_is_safe() -> None:
    store = MemoryNarrationStore()
    _novel_row, _document, _revision, _snapshot, request, _script, version, *_ = (
        _approved_foundation(store, with_warning=True)
    )
    issues = store.find_all(NarrationScriptIssue, script_version_id=version.id)
    assert len(issues) == 1 and issues[0].segment_id is not None
    assert store.get(NarrationSegment, issues[0].segment_id) is not None
    issues[0].evidence_digest = SHA_A
    with pytest.raises(StaleNarrationInput, match="immutable hash"):
        approve_script_version(
            store,
            version.id,
            request_id=request.id,
            actor_type="system",
            actor_id="rules-v1",
        )
    assert version.state == "analyzed"


def test_edition_requires_complete_script_and_exact_segment_types() -> None:
    store = MemoryNarrationStore()
    novel, document, _revision, snapshot, request, _script, version, profile, voice, _rights = (
        _approved_foundation(store)
    )
    approve_script_version(
        store, version.id, request_id=request.id, actor_type="system", actor_id="rules-v1"
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="orchestrator",
    )
    segments = store.find_all(
        NarrationSegment, script_version_id=version.id, order_by=("ordinal",)
    )
    base = CreateEdition(
        novel_id=novel.id,
        document_id=document.id,
        request_id=request.id,
        script_version_id=version.id,
        settings_snapshot_id=snapshot.id,
        tts_fingerprint=SHA_A,
        tokenizer_fingerprint=SHA_B,
        normalizer_fingerprint=SHA_C,
        postprocess_fingerprint="d" * 64,
        buffer_policy_version=INITIAL_BUFFER_POLICY.version,
        created_actor="owner",
        digest_keyring=TEST_DIGEST_KEYRING,
        segments=(
            EditionSegmentInput(
                segment_id=segments[0].id,
                ordinal=0,
                profile_id=profile.id,
                voice_version_id=voice.id,
                resolution_json={"source": "narrator"},
            ),
        ),
    )
    with pytest.raises(InvalidNarrationState, match="cover every"):
        create_edition(store, base)
    with pytest.raises(NarrationServiceError, match="exact integer"):
        create_edition(
            store,
            replace(
                base,
                segments=tuple(
                    EditionSegmentInput(
                        segment_id=segment.id,
                        ordinal=ordinal,
                        profile_id=profile.id,
                        voice_version_id=voice.id,
                        resolution_json={"source": "narrator"},
                        gap_after_ms=True if ordinal == 0 else 0,  # type: ignore[arg-type]
                    )
                    for ordinal, segment in enumerate(segments)
                ),
            ),
        )


def test_approved_generation_request_can_continue_from_analyzed_to_queued() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, _snapshot, request, _script, version, *_ = (
        _approved_foundation(store)
    )
    approve_script_version(
        store,
        version.id,
        request_id=request.id,
        actor_type="system",
        actor_id="rules-v1",
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="analyzed",
        novel_id=novel.id,
        actor="analyzer",
    )

    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="orchestrator",
    )

    assert request.state == "queued"


def _publication_context(
    job_fence: JobFence,
    resource_fence: ResourceFence,
    *,
    lease_until: datetime,
) -> PublicationFenceContext:
    session = Session()
    transaction = session.begin()
    return PublicationFenceContext(
        scope=NarrationRequestScope.fixed_local(),
        job_lease=JobLease(
            fence=job_fence,
            attempt_number=1,
            retry_kind="initial",
            lease_owner="worker-1",
            lease_until=lease_until,
        ),
        resource_lease=ResourceLease(
            fence=resource_fence,
            lease_until=lease_until,
        ),
        resource_class="moss-nano",
        checked_at=NOW,
        _session=session,
        _transaction=transaction,
    )


def _seed_render_job(
    store: MemoryNarrationStore,
    *,
    request: NarrationRequest,
    marker: int,
    edition_segment: NarrationEditionSegment,
) -> tuple[BackgroundJob, PublicationFenceContext]:
    job = BackgroundJob(
        id=uuid4(),
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        novel_id=request.novel_id,
        request_id=request.id,
        request_allows_render=True,
        job_kind="narration.segment_render",
        input_hash=render_job_input_hash(
            edition_segment_id=edition_segment.id,
            render_fingerprint=edition_segment.render_fingerprint,
        ),
        idempotency_key=f"render-job-{marker}-{uuid4()}",
        resource_class="moss-nano",
        base_priority=0,
        state="running",
        max_attempts=3,
        attempt_count=1,
        progress_current=0,
    )
    attempt = BackgroundJobAttempt(
        id=uuid4(),
        job_id=job.id,
        attempt_number=1,
        retry_kind="initial",
        lease_owner="worker-1",
        lease_token=uuid4(),
        lease_generation=1,
        lease_until=NOW + timedelta(days=1),
        started_at=NOW,
    )
    store.add(job)
    store.add(attempt)
    resource_fence = ResourceFence(
        resource_key="moss-nano:inference",
        lease_owner="worker-1",
        lease_token=uuid4(),
        lease_generation=marker + 1,
    )
    store.resource_fences[job.id] = resource_fence
    job_fence = JobFence(
        job_id=job.id,
        attempt_id=attempt.id,
        lease_token=attempt.lease_token,
        lease_generation=attempt.lease_generation,
    )
    return job, _publication_context(
        job_fence,
        resource_fence,
        lease_until=attempt.lease_until,
    )


def _seed_render_assets(
    store: MemoryNarrationStore,
    *,
    novel: Novel,
    render: object,
    marker: int,
) -> None:
    playback_hash = ("e" if marker % 2 == 0 else "f") * 64
    for role, digest, kind in (
        ("master", SHA_C, "narration_segment_master"),
        ("playback", playback_hash, "narration_segment_playback"),
    ):
        asset = MediaAsset(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=novel.id,
            kind=kind,
            asset_class=f"segment_{role}",
            mime_type="audio/wav" if role == "master" else "audio/ogg",
            byte_size=1024 + marker,
            duration_ms=1200,
            sample_rate=48000,
            channels=1,
            storage_backend="local",
            state="ready",
            retention_policy="narration",
            checksum_algorithm="sha256",
            validation_json={"validated": True},
            verified_at=NOW,
            gc_generation=0,
            storage_path=f"narration/test/{marker}/{role}",
            content_hash=digest,
            metadata_json={},
        )
        store.add(asset)
        store.add(
            NarrationRenderAsset(
                id=uuid4(),
                render_id=render.id,
                asset_id=asset.id,
                role=role,
                actual_sha256=digest,
            )
        )


def _edition_with_ready_renders(store: MemoryNarrationStore):
    novel, document, revision, snapshot, request, script, version, profile, voice, rights = (
        _approved_foundation(store)
    )
    approve_script_version(
        store, version.id, request_id=request.id, actor_type="system", actor_id="rules-v1"
    )
    request = advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="queued",
        novel_id=novel.id,
        actor="orchestrator",
    )
    segment_rows = store.find_all(
        NarrationSegment, script_version_id=version.id, order_by=("ordinal",)
    )
    edition = create_edition(
        store,
        CreateEdition(
            novel_id=novel.id,
            document_id=document.id,
            request_id=request.id,
            script_version_id=version.id,
            settings_snapshot_id=snapshot.id,
            tts_fingerprint=SHA_A,
            tokenizer_fingerprint=SHA_B,
            normalizer_fingerprint=SHA_C,
            postprocess_fingerprint="d" * 64,
            buffer_policy_version=INITIAL_BUFFER_POLICY.version,
            created_actor="owner",
            digest_keyring=TEST_DIGEST_KEYRING,
            segments=tuple(
                EditionSegmentInput(
                    segment_id=segment.id,
                    ordinal=ordinal,
                    profile_id=profile.id,
                    voice_version_id=voice.id,
                    resolution_json={"source": "narrator"},
                    gap_after_ms=100,
                )
                for ordinal, segment in enumerate(segment_rows)
            ),
        ),
    )
    edition_segments = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    renders = []
    for ordinal, edition_segment in enumerate(edition_segments):
        job, publication_context = _seed_render_job(
            store,
            request=request,
            marker=ordinal,
            edition_segment=edition_segment,
        )
        render, reused = create_or_reuse_render(
            store,
            CreateRender(
                edition_segment_id=edition_segment.id,
                digest_keyring=TEST_DIGEST_KEYRING,
                source_job_id=job.id,
            ),
        )
        assert not reused
        _seed_render_assets(store, novel=novel, render=render, marker=ordinal)
        publish_render_ready(
            store,
            render.id,
            publication_context=publication_context,
        )
        advance_edition_segment_state(store, edition_segment.id, new_state="ready")
        renders.append(render)
    return novel, document, revision, request, edition, segment_rows, renders, voice, rights


def test_edition_render_cache_scope_and_rights_recheck() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, request, edition, _segments, renders, voice, rights = (
        _edition_with_ready_renders(store)
    )
    assert isinstance(edition, NarrationEdition)
    first_edition_segment = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )[0]
    same_command = CreateRender(
        edition_segment_id=first_edition_segment.id,
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    cached, reused = create_or_reuse_render(store, same_command)
    assert reused and cached is renders[0]
    store.add(
        VoiceRightsEvent(
            id=uuid4(), rights_record_id=rights.id, event_key="revoke-1",
            event_type="revoked", actor="owner", occurred_at=NOW,
        )
    )
    with pytest.raises(VoiceRightsUnavailable):
        create_or_reuse_render(store, same_command)
    store.rows[VoiceRightsEvent].clear()
    foreign_novel = _novel()
    store.add(foreign_novel)
    cached.novel_id = foreign_novel.id
    with pytest.raises(NarrationScopeMismatch):
        create_or_reuse_render(store, same_command)
    cached.novel_id = novel.id


def test_render_input_v3_reuses_audio_across_segment_identity_and_timeline_changes() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, _request, edition, segments, _renders, voice, _rights = (
        _edition_with_ready_renders(store)
    )
    segment = segments[0]
    identity = {
        "novel_id": novel.id,
        "segment": segment,
        "voice_version_id": voice.id,
        "pronunciation_profile_id": edition.pronunciation_profile_id,
        "tts_fingerprint": edition.tts_fingerprint,
        "tokenizer_fingerprint": edition.tokenizer_fingerprint,
        "normalizer_fingerprint": edition.normalizer_fingerprint,
        "postprocess_fingerprint": edition.postprocess_fingerprint,
        "digest_key": TEST_DIGEST_KEY,
    }
    first_fingerprint, first_payload = derive_render_identity(store, **identity)

    segment.id = uuid4()
    segment.local_hash = "1" * 64
    segment.pause_before_ms += 125
    segment.pause_after_ms += 250
    timeline_only_fingerprint, timeline_only_payload = derive_render_identity(
        store, **identity
    )

    assert timeline_only_fingerprint == first_fingerprint
    assert timeline_only_payload == first_payload
    assert first_payload["schema_version"] == "narration-render-input/3"
    assert {
        "segment_id",
        "source_local_hash",
        "canonical_spoken_text_hash",
        "pause_before_ms",
        "pause_after_ms",
    }.isdisjoint(first_payload)
    assert first_payload["canonical_spoken_text_digest_key_id"] == TEST_DIGEST_KEY.key_id
    assert len(str(first_payload["canonical_spoken_text_hmac_sha256"])) == 64

    segment.spoken_text += "不同"
    changed_fingerprint, _changed_payload = derive_render_identity(store, **identity)
    assert changed_fingerprint != first_fingerprint


def test_short_attribution_policy_uses_v4_without_invalidating_normal_v3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, _request, edition, segments, _renders, voice, _rights = (
        _edition_with_ready_renders(store)
    )
    segment = segments[0]
    voice.preset_key = "onnx.Zhiming"
    voice.seed = 0
    voice.parameters_json = {"sample_mode": "fixed", "max_new_frames": 375}
    identity = {
        "novel_id": novel.id,
        "segment": segment,
        "voice_version_id": voice.id,
        "pronunciation_profile_id": edition.pronunciation_profile_id,
        "tts_fingerprint": edition.tts_fingerprint,
        "tokenizer_fingerprint": edition.tokenizer_fingerprint,
        "normalizer_fingerprint": edition.normalizer_fingerprint,
        "postprocess_fingerprint": edition.postprocess_fingerprint,
        "digest_key": TEST_DIGEST_KEY,
    }

    segment.spoken_text = "林晚说道："
    monkeypatch.setattr(
        synthesis_policy,
        "ACTIVE_SHORT_ATTRIBUTION_STRATEGY",
        "disabled",
    )
    old_fingerprint, old_payload = derive_render_identity(store, **identity)
    assert old_payload["schema_version"] == "narration-render-input/3"

    monkeypatch.setattr(
        synthesis_policy,
        "ACTIVE_SHORT_ATTRIBUTION_STRATEGY",
        "fixed_seed_1",
    )
    fixed_fingerprint, fixed_payload = derive_render_identity(store, **identity)

    assert fixed_fingerprint != old_fingerprint
    assert fixed_payload["schema_version"] == SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION
    assert fixed_payload["deterministic_seed"] == 1
    assert fixed_payload["synthesis_style_and_parameters"][
        "effective_synthesis_policy"
    ]["strategy"] == "fixed_seed_1"
    assert derive_render_identity(
        store,
        **identity,
        canonical_input_version="narration-render-input/3",
    ) == (old_fingerprint, old_payload)

    segment.spoken_text = "沈川说道。"
    period_fingerprint, period_payload = derive_render_identity(store, **identity)
    assert period_fingerprint not in {old_fingerprint, fixed_fingerprint}
    assert period_payload["schema_version"] == (
        SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION
    )
    assert period_payload["synthesis_style_and_parameters"][
        "effective_synthesis_policy"
    ]["trigger_kind"] == "zh_narrator_said_period"

    segment.spoken_text = "站台上的灯忽然闪了一次，四周仍然没有人影。"
    active_normal = derive_render_identity(store, **identity)
    monkeypatch.setattr(
        synthesis_policy,
        "ACTIVE_SHORT_ATTRIBUTION_STRATEGY",
        "disabled",
    )
    disabled_normal = derive_render_identity(store, **identity)
    assert active_normal == disabled_normal
    assert active_normal[1]["schema_version"] == "narration-render-input/3"


def test_historical_v3_short_render_is_readable_but_cannot_be_resynthesized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, request, edition, segments, renders, voice, _rights = (
        _edition_with_ready_renders(store)
    )
    segment = segments[0]
    edition_segment = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )[0]
    voice.preset_key = "onnx.Zhiming"
    voice.seed = 0
    voice.parameters_json = {"sample_mode": "fixed", "max_new_frames": 375}
    segment.spoken_text = "沈川说道："
    old_fingerprint, old_payload = derive_render_identity(
        store,
        novel_id=novel.id,
        segment=segment,
        voice_version_id=voice.id,
        pronunciation_profile_id=edition.pronunciation_profile_id,
        tts_fingerprint=edition.tts_fingerprint,
        tokenizer_fingerprint=edition.tokenizer_fingerprint,
        normalizer_fingerprint=edition.normalizer_fingerprint,
        postprocess_fingerprint=edition.postprocess_fingerprint,
        canonical_input_version="narration-render-input/3",
        digest_key=TEST_DIGEST_KEY,
    )
    edition_segment.render_fingerprint = old_fingerprint
    renders[0].render_fingerprint = old_fingerprint
    renders[0].canonical_input_json = old_payload
    monkeypatch.setattr(
        synthesis_policy,
        "ACTIVE_SHORT_ATTRIBUTION_STRATEGY",
        "fixed_seed_1",
    )
    command = CreateRender(
        edition_segment_id=edition_segment.id,
        digest_keyring=TEST_DIGEST_KEYRING,
    )

    assert compute_render_fingerprint(store, command) == old_fingerprint
    cached, reused = create_or_reuse_render(store, command)
    assert cached is renders[0] and reused is True

    store.rows[NarrationSegmentRender].remove(renders[0])
    job, _context = _seed_render_job(
        store,
        request=request,
        marker=221,
        edition_segment=edition_segment,
    )
    with pytest.raises(InvalidNarrationState, match="cannot be newly synthesized"):
        create_or_reuse_render(
            store,
            replace(command, source_job_id=job.id),
        )


def test_legacy_render_input_v1_remains_reproducible_without_cross_version_reuse() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, _request, edition, segments, renders, voice, _rights = (
        _edition_with_ready_renders(store)
    )
    segment = segments[0]
    edition_segment = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )[0]
    legacy_fingerprint, legacy_payload = derive_render_identity(
        store,
        novel_id=novel.id,
        segment=segment,
        voice_version_id=voice.id,
        pronunciation_profile_id=edition.pronunciation_profile_id,
        tts_fingerprint=edition.tts_fingerprint,
        tokenizer_fingerprint=edition.tokenizer_fingerprint,
        normalizer_fingerprint=edition.normalizer_fingerprint,
        postprocess_fingerprint=edition.postprocess_fingerprint,
        canonical_input_version=LEGACY_RENDER_CANONICAL_INPUT_VERSION,
    )
    assert legacy_fingerprint != edition_segment.render_fingerprint
    assert legacy_payload["schema_version"] == LEGACY_RENDER_CANONICAL_INPUT_VERSION
    assert legacy_payload["segment_id"] == str(segment.id)
    assert legacy_payload["source_local_hash"] == segment.local_hash

    # Simulate an immutable Edition/render persisted before the v2 correction.
    edition_segment.render_fingerprint = legacy_fingerprint
    edition_segment.render_digest_key_id = None
    renders[0].render_fingerprint = legacy_fingerprint
    renders[0].canonical_input_json = legacy_payload

    command = CreateRender(
        edition_segment_id=edition_segment.id,
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    assert compute_render_fingerprint(store, command) == legacy_fingerprint
    cached, reused = create_or_reuse_render(store, command)
    assert reused is True and cached is renders[0]


def test_legacy_render_input_v2_remains_read_only_and_reproducible() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, _request, edition, segments, renders, voice, _rights = (
        _edition_with_ready_renders(store)
    )
    segment = segments[0]
    edition_segment = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )[0]
    legacy_fingerprint, legacy_payload = derive_render_identity(
        store,
        novel_id=novel.id,
        segment=segment,
        voice_version_id=voice.id,
        pronunciation_profile_id=edition.pronunciation_profile_id,
        tts_fingerprint=edition.tts_fingerprint,
        tokenizer_fingerprint=edition.tokenizer_fingerprint,
        normalizer_fingerprint=edition.normalizer_fingerprint,
        postprocess_fingerprint=edition.postprocess_fingerprint,
        canonical_input_version=LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION,
    )
    assert legacy_payload["schema_version"] == LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION
    assert "canonical_spoken_text_hash" in legacy_payload
    assert "canonical_spoken_text_hmac_sha256" not in legacy_payload

    edition_segment.render_fingerprint = legacy_fingerprint
    edition_segment.render_digest_key_id = None
    renders[0].render_fingerprint = legacy_fingerprint
    renders[0].canonical_input_json = legacy_payload
    command = CreateRender(
        edition_segment_id=edition_segment.id,
        digest_keyring=TEST_DIGEST_KEYRING,
    )
    assert compute_render_fingerprint(store, command) == legacy_fingerprint
    cached, reused = create_or_reuse_render(store, command)
    assert reused is True and cached is renders[0]

    store.rows[NarrationSegmentRender].remove(renders[0])
    command_job, _context = _seed_render_job(
        store,
        request=_request,
        marker=212,
        edition_segment=edition_segment,
    )
    with pytest.raises(InvalidNarrationState, match="active digest key"):
        create_or_reuse_render(
            store,
            CreateRender(
                edition_segment_id=edition_segment.id,
                digest_keyring=TEST_DIGEST_KEYRING,
                source_job_id=command_job.id,
            ),
        )


def test_rotated_verify_only_key_can_validate_ready_v3_but_cannot_write() -> None:
    store = MemoryNarrationStore()
    _novel_row, _document, _revision, request, edition, _segments, renders, _voice, _rights = (
        _edition_with_ready_renders(store)
    )
    edition_segment = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )[0]
    historical = HmacDigestKey(
        key_id=TEST_DIGEST_KEY.key_id,
        secret=TEST_DIGEST_KEY.secret,
        status="verify_only",
    )
    current = HmacDigestKey(
        key_id="narration-test-active-v2",
        secret=b"narration-test-only-hmac-key-material-v2",
    )
    rotated = DigestKeyring(
        active_key_id=current.key_id,
        keys={historical.key_id: historical, current.key_id: current},
    )
    command = CreateRender(
        edition_segment_id=edition_segment.id,
        digest_keyring=rotated,
    )
    cached, reused = create_or_reuse_render(store, command)
    assert reused is True and cached is renders[0]

    missing_historical = DigestKeyring(
        active_key_id=current.key_id,
        keys={current.key_id: current},
    )
    with pytest.raises(DigestKeyringError) as missing_error:
        compute_render_fingerprint(
            store,
            CreateRender(
                edition_segment_id=edition_segment.id,
                digest_keyring=missing_historical,
            ),
        )
    assert missing_error.value.code == "DIGEST_KEY_UNAVAILABLE"

    store.rows[NarrationSegmentRender].remove(renders[0])
    command_job, _context = _seed_render_job(
        store,
        request=request,
        marker=213,
        edition_segment=edition_segment,
    )
    with pytest.raises(InvalidNarrationState, match="active digest key"):
        create_or_reuse_render(
            store,
            CreateRender(
                edition_segment_id=edition_segment.id,
                digest_keyring=rotated,
                source_job_id=command_job.id,
            ),
        )


def test_render_identity_job_binding_and_result_fence_fail_closed() -> None:
    store = MemoryNarrationStore()
    novel, _document, _revision, request, edition, segments, renders, _voice, _rights = (
        _edition_with_ready_renders(store)
    )
    edition_segment = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )[0]
    command_job, _ = _seed_render_job(
        store,
        request=request,
        marker=101,
        edition_segment=edition_segment,
    )
    command = CreateRender(
        edition_segment_id=edition_segment.id,
        digest_keyring=TEST_DIGEST_KEYRING,
        source_job_id=command_job.id,
    )
    assert compute_render_fingerprint(store, command) == edition_segment.render_fingerprint
    original_pause = segments[0].pause_after_ms
    segments[0].pause_after_ms = original_pause + 1
    # Timeline-only pauses no longer invalidate the v3 synthesized-audio key.
    assert compute_render_fingerprint(store, command) == edition_segment.render_fingerprint
    original_spoken_text = segments[0].spoken_text
    segments[0].spoken_text = original_spoken_text + "变更"
    with pytest.raises(InvalidNarrationState, match="server derivation"):
        compute_render_fingerprint(store, command)
    segments[0].spoken_text = original_spoken_text
    segments[0].pause_after_ms = original_pause

    render = renders[0]
    original_source_job_id = render.source_job_id
    source_job = store.get(BackgroundJob, render.source_job_id)
    assert source_job is not None
    attempt = store.find_one(BackgroundJobAttempt, job_id=source_job.id)
    assert attempt is not None
    render.state = "pending"
    render.duration_ms = None
    render.ready_at = None
    source_job.state = "running"
    attempt.completed_at = None
    attempt.actual_result_digest = None
    render.source_job_id = command_job.id
    command_job.input_hash = SHA_A
    with pytest.raises(NarrationScopeMismatch, match="source job"):
        create_or_reuse_render(store, command)
    render.source_job_id = original_source_job_id
    current = JobFence(
        job_id=source_job.id,
        attempt_id=attempt.id,
        lease_token=attempt.lease_token,
        lease_generation=attempt.lease_generation,
    )
    stale_resource = replace(
        store.resource_fences[source_job.id], lease_token=uuid4()
    )
    with pytest.raises(InvalidNarrationState, match="stale"):
        publish_render_ready(
            store,
            render.id,
            publication_context=_publication_context(
                current, stale_resource, lease_until=attempt.lease_until
            ),
        )
    assert render.state == "pending"
    stale = JobFence(
        job_id=source_job.id,
        attempt_id=attempt.id,
        lease_token=uuid4(),
        lease_generation=attempt.lease_generation,
    )
    with pytest.raises(InvalidNarrationState, match="stale"):
        publish_render_ready(
            store,
            render.id,
            publication_context=_publication_context(
                stale,
                store.resource_fences[source_job.id],
                lease_until=attempt.lease_until,
            ),
        )
    assert render.state == "pending"
    source_job.state = "cancel_requested"
    with pytest.raises(InvalidNarrationState, match="stale"):
        publish_render_ready(
            store,
            render.id,
            publication_context=_publication_context(
                current,
                store.resource_fences[source_job.id],
                lease_until=attempt.lease_until,
            ),
        )
    assert render.state == "pending" and attempt.actual_result_digest is None


def test_manifest_uses_authoritative_playback_asset_and_exact_wire_types() -> None:
    store = MemoryNarrationStore()
    _novel_row, _document, _revision, _request, edition, _segments, renders, _voice, _rights = (
        _edition_with_ready_renders(store)
    )
    edition_segments = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    inputs = tuple(
        ManifestSegmentInput(
            edition_segment_id=row.id,
            render_status="ready",
            render_id=renders[index].id,
        )
        for index, row in enumerate(edition_segments)
    )
    policy = INITIAL_BUFFER_POLICY
    playback_link = store.find_one(
        NarrationRenderAsset, render_id=renders[0].id, role="playback"
    )
    assert playback_link is not None
    actual_digest = playback_link.actual_sha256
    playback_link.actual_sha256 = SHA_A
    with pytest.raises(InvalidNarrationState, match="provenance"):
        publish_manifest(
            store,
            PublishManifest(
                edition_id=edition.id,
                expected_current_revision=0,
                expected_state_version=0,
                buffer_policy=policy,
                segments=inputs,
                updated_actor="worker",
            ),
        )
    assert not store.rows[NarrationManifest]
    playback_link.actual_sha256 = actual_digest
    with pytest.raises(NarrationServiceError, match="exact integer"):
        replace(policy, minimum_segments=True).payload()  # type: ignore[arg-type]
    with pytest.raises(NarrationServiceError, match="exact integer"):
        create_settings_snapshot(
            store,
            CreateSettingsSnapshot(
                novel_id=edition.novel_id,
                settings_version=True,  # type: ignore[arg-type]
            ),
        )


def test_manifest_revision_collision_derivation_and_progress_cas() -> None:
    store = MemoryNarrationStore()
    _novel_row, document, _revision, _request, edition, _segments, renders, _voice, _rights = (
        _edition_with_ready_renders(store)
    )
    edition_segments = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    inputs = tuple(
        ManifestSegmentInput(
            edition_segment_id=row.id,
            render_status="ready",
            render_id=renders[index].id,
        )
        for index, row in enumerate(edition_segments)
    )
    policy = INITIAL_BUFFER_POLICY
    first_command = PublishManifest(
        edition_id=edition.id,
        expected_current_revision=0,
        expected_state_version=0,
        buffer_policy=policy,
        segments=inputs,
        updated_actor="worker",
    )
    first = publish_manifest(store, first_command)
    assert first.manifest_revision == 1
    assert edition.state == "ready"
    assert set(first.canonical_json) == {
        "schema_version", "edition_id", "chapter_id", "source_revision_id",
        "source_sha256", "buffer_policy", "manifest_revision", "etag",
        "generated_at", "status", "ready_prefix_count", "default_start_ready",
        "last_playable_start_ordinal", "ready_ranges", "segments",
    }
    assert all(
        set(segment) == {
            "segment_id", "ordinal", "paragraph_ordinal", "source_block_key",
            "source_start_utf16", "source_end_utf16", "gap_after_ms",
            "render_status", "audio", "failure",
        }
        for segment in first.canonical_json["segments"]
    )
    assert all(
        "?" not in segment["audio"]["url"]
        and "token" not in segment["audio"]["url"].lower()
        for segment in first.canonical_json["segments"]
    )
    assert first.canonical_json["ready_prefix_count"] == 2
    assert first.canonical_json["ready_ranges"] == [{
        "start_ordinal": 0,
        "end_ordinal_exclusive": 2,
        "segment_count": 2,
        "duration_ms": 2500,
        "last_playable_start_ordinal": 1,
    }]
    assert first.etag_sha256 == first.canonical_json["etag"].strip('"')
    hash_input = dict(first.canonical_json)
    hash_input.pop("etag")
    assert canonical_sha256(hash_input) == first.etag_sha256
    assert publish_manifest(store, first_command) is first
    with pytest.raises(InvalidNarrationState, match="frozen server policy"):
        publish_manifest(
            store,
            PublishManifest(
                edition_id=edition.id,
                expected_current_revision=0,
                expected_state_version=0,
                buffer_policy=replace(policy, target_segments=3),
                segments=inputs,
                updated_actor="worker",
            ),
        )
    with pytest.raises(NarrationCasConflict):
        publish_manifest(
            store,
            PublishManifest(
                edition_id=edition.id,
                expected_current_revision=2,
                expected_state_version=2,
                buffer_policy=policy,
                segments=inputs,
                updated_actor="worker",
            ),
        )
    second = publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=1,
            expected_state_version=1,
            buffer_policy=policy,
            segments=inputs,
            updated_actor="worker",
        ),
    )
    assert second.manifest_revision == 2 and second.etag_sha256 != first.etag_sha256
    pointer = switch_document_edition(
        store,
        document_id=document.id,
        edition_id=edition.id,
        expected_version=0,
        actor="owner",
    )
    assert pointer.current_edition_id == edition.id
    assert pointer.current_script_version_id == edition.script_version_id

    progress = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=2,
            edition_segment_id=edition_segments[0].id,
            offset_ms=500,
            last_legal_start_ordinal=0,
            playback_rate_millis=1000,
            expected_updated_at=None,
        ),
    )
    stale_token = progress.updated_at
    progress = save_playback_progress(
        store,
        SavePlaybackProgress(
            profile_id="default",
            edition_id=edition.id,
            manifest_revision=2,
            edition_segment_id=edition_segments[1].id,
            offset_ms=200,
            last_legal_start_ordinal=1,
            playback_rate_millis=1250,
            expected_updated_at=stale_token,
        ),
    )
    assert progress.updated_at > stale_token
    with pytest.raises(NarrationCasConflict):
        save_playback_progress(
            store,
            SavePlaybackProgress(
                profile_id="default",
                edition_id=edition.id,
                manifest_revision=2,
                edition_segment_id=edition_segments[0].id,
                offset_ms=0,
                last_legal_start_ordinal=0,
                playback_rate_millis=1000,
                expected_updated_at=stale_token,
            ),
        )
    assert progress.edition_segment_id == edition_segments[1].id
    second.canonical_json["ready_ranges"] = [
        {
            "start_ordinal": 0,
            "end_ordinal_exclusive": 1,
            "segment_count": 1,
            "duration_ms": 1200,
            "last_playable_start_ordinal": 0,
        },
        {
            "start_ordinal": 1,
            "end_ordinal_exclusive": 2,
            "segment_count": 1,
            "duration_ms": 1200,
            "last_playable_start_ordinal": 1,
        },
    ]
    with pytest.raises(InvalidNarrationState, match="disconnected ready range"):
        save_playback_progress(
            store,
            SavePlaybackProgress(
                profile_id="default",
                edition_id=edition.id,
                manifest_revision=2,
                edition_segment_id=edition_segments[1].id,
                offset_ms=100,
                last_legal_start_ordinal=0,
                playback_rate_millis=1000,
                expected_updated_at=progress.updated_at,
            ),
        )
    with pytest.raises(InvalidNarrationState, match="timezone-aware"):
        save_playback_progress(
            store,
            SavePlaybackProgress(
                profile_id="default",
                edition_id=edition.id,
                manifest_revision=2,
                edition_segment_id=edition_segments[1].id,
                offset_ms=100,
                last_legal_start_ordinal=1,
                playback_rate_millis=1000,
                expected_updated_at=datetime(2026, 8, 26),
            ),
        )


@pytest.mark.parametrize(
    ("wire_status", "failure"),
    [
        ("failed", ManifestFailure(code="F_RENDER", retryable=True, message="retry")),
        ("cancelled", None),
    ],
)
def test_manifest_terminal_wire_status_has_explicit_unavailable_db_mapping(
    wire_status: str, failure: ManifestFailure | None
) -> None:
    store = MemoryNarrationStore()
    _novel_row, _document, _revision, _request, edition, _segments, _renders, _voice, _rights = (
        _edition_with_ready_renders(store)
    )
    edition_segments = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    for row in edition_segments:
        # Unit fixture rewinds the pre-publication aggregate only; the service then
        # exercises the frozen terminal transition and manifest mapping.
        row.render_state = "pending"
        advance_edition_segment_state(store, row.id, new_state=wire_status, failure_code=(
            failure.code if failure else None
        ))
    inputs = tuple(
        ManifestSegmentInput(
            edition_segment_id=row.id,
            render_status=wire_status,
            failure=failure,
        )
        for row in edition_segments
    )
    terminal_policy = INITIAL_BUFFER_POLICY
    if wire_status == "failed":
        with pytest.raises(InvalidNarrationState, match="failure code"):
            publish_manifest(
                store,
                PublishManifest(
                    edition_id=edition.id,
                    expected_current_revision=0,
                    expected_state_version=0,
                    buffer_policy=terminal_policy,
                    segments=tuple(
                        replace(
                            item,
                            failure=ManifestFailure(
                                code="F_OTHER", retryable=False, message="wrong source"
                            ),
                        )
                        for item in inputs
                    ),
                    updated_actor="worker",
                ),
            )
    manifest = publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=terminal_policy,
            segments=inputs,
            updated_actor="worker",
        ),
    )
    assert manifest.status == "unavailable"
    assert manifest.canonical_json["status"] == wire_status
    assert manifest.etag_sha256 == manifest.canonical_json["etag"].strip('"')


def test_manifest_pending_is_not_persisted() -> None:
    store = MemoryNarrationStore()
    _novel_row, _document, _revision, _request, edition, _segments, _renders, _voice, _rights = (
        _edition_with_ready_renders(store)
    )
    edition_segments = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    for row in edition_segments:
        row.render_state = "pending"
    before = len(store.rows[NarrationManifest])
    with pytest.raises(InvalidNarrationState, match="before any segment is ready"):
        publish_manifest(
            store,
            PublishManifest(
                edition_id=edition.id,
                expected_current_revision=0,
                expected_state_version=0,
                buffer_policy=INITIAL_BUFFER_POLICY,
                segments=tuple(
                    ManifestSegmentInput(edition_segment_id=row.id, render_status="pending")
                    for row in edition_segments
                ),
                updated_actor="worker",
            ),
        )
    assert len(store.rows[NarrationManifest]) == before
