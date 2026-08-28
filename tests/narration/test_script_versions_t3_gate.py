from __future__ import annotations

import hashlib
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest

from backend.models import (
    Document,
    DocumentRevision,
    NarrationEdition,
    NarrationScript,
    NarrationScriptIssue,
    NarrationScene,
    NarrationSettingsSnapshot,
    NarrationSegment,
    NovelNarrationSettings,
)
from backend.narration.contracts import (
    LOCAL_OWNER_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    ConfidenceLevel,
    ReviewIssueSeverity,
)
from backend.narration.fingerprints import canonical_json_bytes
from backend.narration.requests import (
    CreateNarrationRequest,
    advance_request_state,
    create_request,
)
from backend.narration.privacy import (
    _storage_settings,
    default_narration_settings_values,
)
from backend.narration.script_contracts import (
    NARRATION_SCRIPT_CONTRACT_VERSION,
    ApprovalActorType,
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    Delivery,
    Emotion,
    NarrationScriptContract,
    SceneBoundarySource,
    SceneContract,
    ScriptIssueContract,
    ScriptApproval,
    ScriptApprovalKind,
    ScriptReviewPolicy,
    ScriptVersionState,
    SegmentContract,
    SegmentKind,
    SourceBlockKind,
    SpeakerKind,
    SpeakerRef,
    Utf16Range,
    derive_scene_id,
    derive_segment_id,
    derive_source_block_key,
    script_contract_to_dict,
    script_immutable_payload,
    text_sha256,
    utf16_length,
)
from backend.narration.script_versions import (
    SCRIPT_ANALYZER_FINGERPRINT,
    SCRIPT_RULES_FINGERPRINT,
    CreateScriptDraft,
    LegacyScriptVersionRead,
    ParentReviewClassification,
    ReserveScriptIdentity,
    ScriptSegmentInput,
    ScriptVersionAllocation,
    _persisted_version_hash,
    approve_script_version,
    classify_parent_review,
    freeze_script_version,
    create_script_draft,
    load_script_contract,
    load_script_version_for_read,
    persist_script_contract,
    reserve_script_identity,
)
from backend.narration.services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationServiceError,
    StaleNarrationInput,
    canonical_sha256,
)
from backend.narration.snapshots import (
    CreateSettingsSnapshot,
    create_settings_snapshot,
    snapshot_payload,
)
from tests.narration.test_domain_services import MemoryNarrationStore, _novel


NOW = datetime(2026, 8, 27, 1, 2, 3, tzinfo=UTC)


def _settings_fingerprint(novel_id: UUID) -> str:
    values = default_narration_settings_values()
    command = CreateSettingsSnapshot(novel_id=novel_id, settings_version=1)
    settings = SimpleNamespace(
        script_review_policy=values.script_review_policy.value,
        analysis_mode=values.analysis_mode.value,
        narrator_profile_id=None,
        narrator_version_id=None,
        settings_json=_storage_settings(values),
    )
    return canonical_sha256(snapshot_payload(command, settings, []))


def _seed_source(source: str) -> tuple[
    MemoryNarrationStore,
    object,
    Document,
    DocumentRevision,
]:
    store = MemoryNarrationStore()
    novel = _novel()
    document = Document(
        id=uuid4(),
        novel_id=novel.id,
        kind="chapter",
        title="第一章",
        position=1,
        status="draft",
        version=1,
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown=source,
        content_text=source,
        content_hash=text_sha256(source),
        source="manual",
    )
    store.add(novel)
    store.add(document)
    store.add(revision)
    values = default_narration_settings_values()
    store.add(
        NovelNarrationSettings(
            id=uuid4(),
            novel_id=novel.id,
            narrator_profile_id=None,
            narrator_version_id=None,
            script_review_policy=values.script_review_policy.value,
            analysis_mode=values.analysis_mode.value,
            settings_json=_storage_settings(values),
            version=1,
        )
    )
    snapshot = create_settings_snapshot(
        store,
        CreateSettingsSnapshot(novel_id=novel.id, settings_version=1),
    )
    assert snapshot.fingerprint == _settings_fingerprint(novel.id)
    return store, novel, document, revision


def _reserve(
    store: MemoryNarrationStore,
    novel: object,
    document: Document,
    revision: DocumentRevision,
    *,
    key: str,
    parent_version_id: UUID | None = None,
) -> ScriptVersionAllocation:
    return reserve_script_identity(
        store,
        ReserveScriptIdentity(
            novel_id=novel.id,
            document_id=document.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            idempotency_key=key,
            parent_version_id=parent_version_id,
        ),
    )


def _immutable_hash_for(candidate: object) -> str:
    return hashlib.sha256(
        canonical_json_bytes(script_immutable_payload(candidate))
    ).hexdigest()


def _replace_and_rehash(
    contract: NarrationScriptContract, **changes: object
) -> NarrationScriptContract:
    values = {field.name: getattr(contract, field.name) for field in fields(contract)}
    values.update(changes)
    values["immutable_hash"] = _immutable_hash_for(SimpleNamespace(**values))
    return NarrationScriptContract(**values)


def _contract(
    allocation: ScriptVersionAllocation,
    source: str,
    *,
    extra_blocker: bool = False,
    force_review_required: bool = False,
    rules_fingerprint: str = SCRIPT_RULES_FINGERPRINT,
) -> NarrationScriptContract:
    source_hash = text_sha256(source)
    source_range = Utf16Range(0, utf16_length(source)) if source else None
    scene = SceneContract(
        scene_id=derive_scene_id(
            script_version_id=allocation.script_version_id,
            ordinal=0,
            source_range=source_range,
            local_hash=source_hash,
        ),
        ordinal=0,
        source_range_utf16=source_range,
        boundary_source=SceneBoundarySource.DOCUMENT_START,
        local_hash=source_hash,
    )
    attribution = AttributionEvidence(
        AttributionOrigin.LOCAL_RULE,
        ("speaker.local.fixture",),
    )
    issue_specs: list[tuple[str, str | None, str | None]] = []
    if source:
        block_kind = SourceBlockKind.PARAGRAPH
        paragraph_ordinal = 0
        segment_kind = SegmentKind.NARRATION
        speaker = SpeakerRef(SpeakerKind.UNKNOWN)
        casting = CastingDecision(
            candidate_targets=(),
            final_target=None,
            origin=CastingDecisionOrigin.UNRESOLVED,
        )
        confidence = ConfidenceLevel.UNKNOWN
        spoken_text = source
        pause_after_ms = 0
        issue_specs.extend(
            [
                ("B_CASTING_TARGET_UNRESOLVED", None, None),
                ("B_SPEAKER_LOW_CONFIDENCE", None, None),
                (
                    "B_SPEAKER_UNKNOWN",
                    "本地规则无法唯一确定说话人。",
                    "d" * 64,
                ),
            ]
        )
    else:
        block_kind = SourceBlockKind.SYNTHETIC
        paragraph_ordinal = None
        segment_kind = SegmentKind.SYNTHETIC_PAUSE
        speaker = SpeakerRef(SpeakerKind.NARRATOR)
        casting = CastingDecision(
            candidate_targets=(),
            final_target=None,
            origin=CastingDecisionOrigin.NOT_APPLICABLE,
        )
        confidence = ConfidenceLevel.HIGH
        spoken_text = ""
        pause_after_ms = 320
    block_key = derive_source_block_key(
        script_version_id=allocation.script_version_id,
        block_kind=block_kind,
        paragraph_ordinal=paragraph_ordinal,
        block_hash=source_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    segment = SegmentContract(
        segment_id=derive_segment_id(
            script_version_id=allocation.script_version_id,
            ordinal=0,
            source_block_key=block_key,
            segment_ordinal_in_block=0,
            local_hash=source_hash,
        ),
        ordinal=0,
        scene_id=scene.scene_id,
        segment_kind=segment_kind,
        source_block_kind=block_kind,
        paragraph_ordinal=paragraph_ordinal,
        segment_ordinal_in_block=0,
        source_block_key=block_key,
        source_block_hash=source_hash,
        source_range_utf16=source_range,
        source_text=source,
        spoken_text=spoken_text,
        local_hash=source_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
        inheritance_anchor_before_hash=None,
        inheritance_anchor_after_hash=None,
        speaker=speaker,
        casting=casting,
        confidence=confidence,
        emotion=Emotion.NEUTRAL,
        emotion_confidence=ConfidenceLevel.HIGH,
        delivery=Delivery.NORMAL,
        attribution=attribution,
        pause_after_ms=pause_after_ms,
    )
    if extra_blocker:
        issue_specs.append(
            ("B_VOICE_MISSING", "父版本仍缺少可用音色。", "e" * 64)
        )
    issues = tuple(
        sorted(
            (
                ScriptIssueContract(
                    code=code,
                    severity=ReviewIssueSeverity.BLOCKER,
                    segment_id=segment.segment_id,
                    evidence_summary=summary,
                    evidence_digest=digest,
                )
                for code, summary, digest in issue_specs
            ),
            key=lambda item: (
                item.code,
                str(item.segment_id or ""),
                item.evidence_digest or "",
            ),
        )
    )
    state = (
        ScriptVersionState.REVIEW_REQUIRED
        if issues or force_review_required
        else ScriptVersionState.ANALYZED
    )
    base = dict(
        script_id=allocation.script_id,
        script_version_id=allocation.script_version_id,
        novel_id=allocation.novel_id,
        document_id=allocation.document_id,
        revision_id=allocation.revision_id,
        source_content_hash=allocation.content_hash,
        source_length_utf16=utf16_length(source),
        version_number=allocation.version_number,
        parent_version_id=allocation.parent_version_id,
        state=state,
        effective_policy=ScriptReviewPolicy.BLOCKERS_ONLY,
        analyzer_fingerprint=SCRIPT_ANALYZER_FINGERPRINT,
        rules_fingerprint=rules_fingerprint,
        settings_fingerprint=_settings_fingerprint(allocation.novel_id),
        requested_model_fingerprint=None,
        actual_model_fingerprint=None,
        anonymous_speakers=(),
        scenes=(scene,),
        segments=(segment,),
        issues=issues,
        warning_count=0,
        blocker_count=len(issues),
        approval=None,
        schema_version=NARRATION_SCRIPT_CONTRACT_VERSION,
        taxonomy_version=NARRATION_REVIEW_TAXONOMY_VERSION,
    )
    return NarrationScriptContract(
        **base,
        immutable_hash=_immutable_hash_for(SimpleNamespace(**base)),
    )


def _generation_request(
    store: MemoryNarrationStore,
    novel: object,
    document: Document,
    revision: DocumentRevision,
    *,
    key: str,
):
    request = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel.id,
            document_id=document.id,
            intent="create",
            idempotency_key=key,
            settings_fingerprint=_settings_fingerprint(novel.id),
            effective_policy="blockers_only",
            source_revision_id=revision.id,
            source_content_hash=revision.content_hash,
            explicit_generation_intent_at=NOW,
            explicit_generation_actor="owner",
        ),
    )
    return advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state="analyzing",
        novel_id=novel.id,
        actor="analyzer",
    )


def test_typed_write_reload_preserves_emoji_partition_hash_and_issue_summary() -> None:
    source = "她说：‘晚安🌙。’\n"
    store, novel, document, revision = _seed_source(source)
    allocation = _reserve(
        store, novel, document, revision, key="typed-emoji-v1"
    )
    contract = _contract(allocation, source)

    row = persist_script_contract(store, allocation, contract)
    loaded = load_script_contract(store, row.id)

    assert script_contract_to_dict(loaded) == script_contract_to_dict(contract)
    assert loaded.immutable_hash == contract.immutable_hash
    assert loaded.source_length_utf16 == utf16_length(source)
    issue_rows = store.find_all(
        NarrationScriptIssue, script_version_id=row.id
    )
    assert any(item.evidence_summary for item in issue_rows)
    assert "voice_version_id" not in str(script_contract_to_dict(loaded))
    assert store.find_all(NarrationEdition) == []


def test_synthetic_pause_roundtrip_and_freeze_replay_keep_original_audit() -> None:
    store, novel, document, revision = _seed_source("")
    command_key = "typed-pause-v1"
    allocation = _reserve(
        store, novel, document, revision, key=command_key
    )
    contract = _contract(allocation, "")
    row = persist_script_contract(store, allocation, contract)
    loaded = load_script_contract(store, row.id)
    assert loaded.segments[0].spoken_text == ""
    assert loaded.segments[0].pause_after_ms == 320

    request = _generation_request(
        store, novel, document, revision, key="typed-pause-request"
    )
    approved = freeze_script_version(
        store,
        row.id,
        request_id=request.id,
        actor_type="service",
        actor_id="narration-orchestrator",
        approved_at=NOW,
    )
    original_audit = (approved.approved_at, approved.approval_kind)

    replay_allocation = _reserve(
        store, novel, document, revision, key=command_key
    )
    assert replay_allocation.existing is True
    assert replay_allocation.script_version_id == row.id
    assert persist_script_contract(store, replay_allocation, contract) is row
    replay = freeze_script_version(
        store,
        row.id,
        request_id=request.id,
        actor_type="service",
        actor_id="narration-orchestrator",
        approved_at=NOW + timedelta(hours=1),
    )
    assert (replay.approved_at, replay.approval_kind) == original_audit
    assert store.find_all(NarrationEdition) == []

    request.effective_policy = "always_review"
    request.force_review = True
    with pytest.raises(
        (InvalidNarrationState, StaleNarrationInput),
        match="approval|policy|authority",
    ):
        load_script_contract(store, row.id)
    request.effective_policy = "blockers_only"
    request.force_review = False

    segment = store.find_one(NarrationSegment, script_version_id=row.id)
    assert segment is not None
    segment.pause_after_ms = 999
    with pytest.raises(StaleNarrationInput, match="immutable hash"):
        freeze_script_version(
            store,
            row.id,
            request_id=request.id,
            actor_type="service",
            actor_id="narration-orchestrator",
            approved_at=NOW + timedelta(hours=2),
        )


def test_loader_rejects_child_tamper_and_unknown_evidence_version() -> None:
    source = "🌙"
    store, novel, document, revision = _seed_source(source)
    allocation = _reserve(store, novel, document, revision, key="typed-tamper-v1")
    row = persist_script_contract(store, allocation, _contract(allocation, source))
    segment = store.find_one(NarrationSegment, script_version_id=row.id)
    assert segment is not None
    segment.spoken_text = "被篡改"
    with pytest.raises(StaleNarrationInput, match="immutable hash"):
        load_script_contract(store, row.id)

    store2, novel2, document2, revision2 = _seed_source(source)
    allocation2 = _reserve(
        store2, novel2, document2, revision2, key="typed-version-v1"
    )
    row2 = persist_script_contract(
        store2, allocation2, _contract(allocation2, source)
    )
    segment2 = store2.find_one(NarrationSegment, script_version_id=row2.id)
    assert segment2 is not None
    segment2.evidence_json["contract_version"] = "narration-segment-evidence/999"
    # Recompute the existing single immutable hash as an attacker would need to;
    # the closed-schema version check must still reject the row.
    root2 = store2.get(NarrationScript, row2.script_id)
    assert root2 is not None
    row2.immutable_hash = _persisted_version_hash(
        store2, row2, root2, for_update=False
    )[0]
    with pytest.raises(InvalidNarrationState, match="unknown.*evidence"):
        load_script_contract(store2, row2.id)
    with pytest.raises(InvalidNarrationState, match="unknown or mixed"):
        approve_script_version(
            store2,
            row2.id,
            request_id=uuid4(),
            actor_type="service",
            actor_id="must-not-downgrade-to-legacy",
        )
    with pytest.raises(InvalidNarrationState, match="unknown or mixed"):
        classify_parent_review(store2, row2.script_id, row2.id)

    store3, novel3, document3, revision3 = _seed_source("")
    allocation3 = _reserve(
        store3, novel3, document3, revision3, key="typed-stripped-v1"
    )
    row3 = persist_script_contract(
        store3, allocation3, _contract(allocation3, "")
    )
    segment3 = store3.find_one(NarrationSegment, script_version_id=row3.id)
    root3 = store3.get(NarrationScript, row3.script_id)
    assert segment3 is not None and root3 is not None
    segment3.casting_json = {}
    segment3.evidence_json = {}
    row3.immutable_hash = _persisted_version_hash(
        store3, row3, root3, for_update=False
    )[0]
    with pytest.raises(InvalidNarrationState, match="unknown or mixed"):
        approve_script_version(
            store3,
            row3.id,
            request_id=uuid4(),
            actor_type="service",
            actor_id="stripped-typed-row-must-not-be-legacy",
        )

    store3.rows[NarrationSegment].remove(segment3)
    with pytest.raises(InvalidNarrationState, match="unknown or mixed"):
        classify_parent_review(store3, row3.script_id, row3.id)


@pytest.mark.parametrize("identity_case", ["uuid4", "empty_key"])
def test_current_typed_markers_require_server_derived_version_identity(
    identity_case: str,
) -> None:
    store, novel, document, revision = _seed_source("")
    allocation = _reserve(
        store,
        novel,
        document,
        revision,
        key=f"typed-identity-{identity_case}-v1",
    )
    row = persist_script_contract(
        store,
        allocation,
        _contract(allocation, ""),
    )
    old_id = row.id
    if identity_case == "empty_key":
        row.idempotency_key = ""
        forged_id = uuid5(
            row.script_id,
            "narration-script-version:",
        )
    else:
        forged_id = uuid4()
    row.id = forged_id
    for scene in store.find_all(NarrationScene, script_version_id=old_id):
        scene.script_version_id = forged_id
    for segment in store.find_all(NarrationSegment, script_version_id=old_id):
        segment.script_version_id = forged_id

    for loader in (load_script_contract, load_script_version_for_read):
        with pytest.raises(InvalidNarrationState, match="unknown or mixed"):
            loader(store, forged_id)


@pytest.mark.parametrize("partial_value", [False, True])
def test_non_approved_typed_row_rejects_partial_edition_approval_audit(
    partial_value: bool,
) -> None:
    store, novel, document, revision = _seed_source("")
    allocation = _reserve(
        store,
        novel,
        document,
        revision,
        key=f"typed-partial-audit-{str(partial_value).lower()}",
    )
    row = persist_script_contract(
        store,
        allocation,
        _contract(allocation, ""),
    )
    row.approval_request_allows_edition = partial_value

    with pytest.raises(InvalidNarrationState, match="approval audit fields"):
        load_script_contract(store, row.id)


def test_blocker_parent_is_manual_only_and_parent_classification_is_exhaustive() -> None:
    store, novel, document, revision = _seed_source("")
    parent_allocation = _reserve(
        store, novel, document, revision, key="typed-parent-v1"
    )
    parent = persist_script_contract(
        store,
        parent_allocation,
        _contract(parent_allocation, "", extra_blocker=True),
    )
    assert classify_parent_review(
        store, parent.script_id, parent.id
    ) == ParentReviewClassification(parent.id, True, False)

    child_allocation = _reserve(
        store,
        novel,
        document,
        revision,
        key="typed-child-v1",
        parent_version_id=parent.id,
    )
    child = persist_script_contract(
        store,
        child_allocation,
        _contract(child_allocation, "", force_review_required=True),
    )
    request = _generation_request(
        store, novel, document, revision, key="typed-child-request"
    )
    with pytest.raises(InvalidNarrationState, match="manual|eligible"):
        freeze_script_version(
            store,
            child.id,
            request_id=request.id,
            actor_type="service",
            actor_id="automatic-freezer",
            approved_at=NOW,
        )
    approved = freeze_script_version(
        store,
        child.id,
        request_id=request.id,
        actor_type="owner",
        actor_id=str(LOCAL_OWNER_ID),
        approved_at=NOW,
    )
    assert approved.approval_kind == "manual_after_review"
    assert classify_parent_review(store, child.script_id, None) == (
        ParentReviewClassification(None, False, False)
    )


def test_same_key_different_immutable_contract_is_rejected() -> None:
    store, novel, document, revision = _seed_source("")
    allocation = _reserve(
        store, novel, document, revision, key="typed-conflict-v1"
    )
    persist_script_contract(store, allocation, _contract(allocation, ""))
    replay = _reserve(
        store, novel, document, revision, key="typed-conflict-v1"
    )
    conflicting = _contract(
        replay,
        "",
        rules_fingerprint="f" * 64,
    )
    with pytest.raises(IdempotencyConflict, match="canonical input"):
        persist_script_contract(store, replay, conflicting)


def test_typed_persistence_requires_server_snapshot_registry_and_state() -> None:
    store, novel, document, revision = _seed_source("")
    allocation = _reserve(
        store, novel, document, revision, key="typed-authority-v1"
    )
    clean = _contract(allocation, "")

    forged_analyzer = _replace_and_rehash(
        clean, analyzer_fingerprint="f" * 64
    )
    with pytest.raises(InvalidNarrationState, match="analyzer fingerprint"):
        persist_script_contract(store, allocation, forged_analyzer)

    forged_model = _replace_and_rehash(
        clean,
        requested_model_fingerprint="e" * 64,
        actual_model_fingerprint="e" * 64,
    )
    with pytest.raises(InvalidNarrationState, match="model fingerprints"):
        persist_script_contract(store, allocation, forged_model)

    parent_row = persist_script_contract(store, allocation, clean)
    child_allocation = _reserve(
        store,
        novel,
        document,
        revision,
        key="typed-authority-child-v1",
        parent_version_id=parent_row.id,
    )
    child = _contract(child_allocation, "")
    forged_state = _replace_and_rehash(
        child, state=ScriptVersionState.REVIEW_REQUIRED
    )
    with pytest.raises(InvalidNarrationState, match="authority validation"):
        persist_script_contract(store, child_allocation, forged_state)

    snapshot = store.find_one(
        NarrationSettingsSnapshot,
        novel_id=novel.id,
        fingerprint=clean.settings_fingerprint,
    )
    assert snapshot is not None
    store.rows[NarrationSettingsSnapshot].remove(snapshot)
    with pytest.raises(NarrationServiceError, match="settings snapshot"):
        load_script_contract(store, parent_row.id)


def test_typed_persistence_rederives_allocation_identity_and_next_version() -> None:
    store, novel, document, revision = _seed_source("")
    allocation = _reserve(
        store, novel, document, revision, key="typed-allocation-v1"
    )

    forged_identity = replace(
        allocation,
        script_version_id=uuid4(),
        version_number=99,
        idempotency_key="caller-forged-allocation",
    )
    with pytest.raises(InvalidNarrationState, match="server-derived"):
        persist_script_contract(
            store,
            forged_identity,
            _contract(forged_identity, ""),
        )

    forged_number = replace(allocation, version_number=99)
    with pytest.raises(StaleNarrationInput, match="version number"):
        persist_script_contract(
            store,
            forged_number,
            _contract(forged_number, ""),
        )

    stale = allocation
    winner = _reserve(
        store, novel, document, revision, key="typed-allocation-winner-v1"
    )
    persist_script_contract(store, winner, _contract(winner, ""))
    with pytest.raises(StaleNarrationInput, match="version number"):
        persist_script_contract(store, stale, _contract(stale, ""))


def test_first_typed_materialization_cannot_insert_approved_audit_directly() -> None:
    store, novel, document, revision = _seed_source("")
    allocation = _reserve(
        store, novel, document, revision, key="typed-direct-approved-v1"
    )
    analyzed = _contract(allocation, "")
    forged = replace(
        analyzed,
        state=ScriptVersionState.APPROVED,
        approval=ScriptApproval(
            kind=ScriptApprovalKind.AUTO_NO_BLOCKERS,
            request_id=uuid4(),
            actor_type=ApprovalActorType.SERVICE,
            actor_id="caller-forged-approval",
            approved_at=NOW,
        ),
    )
    with pytest.raises(InvalidNarrationState, match="freeze service"):
        persist_script_contract(store, allocation, forged)


def test_clean_parent_is_explicitly_classified_as_non_review() -> None:
    store, novel, document, revision = _seed_source("")
    parent_allocation = _reserve(
        store, novel, document, revision, key="typed-clean-parent-v1"
    )
    parent = persist_script_contract(
        store, parent_allocation, _contract(parent_allocation, "")
    )
    assert classify_parent_review(store, parent.script_id, parent.id) == (
        ParentReviewClassification(parent.id, False, True)
    )
    child_allocation = _reserve(
        store,
        novel,
        document,
        revision,
        key="typed-clean-child-v1",
        parent_version_id=parent.id,
    )
    child = persist_script_contract(
        store,
        child_allocation,
        _contract(child_allocation, ""),
    )
    assert child.parent_version_id == parent.id


def test_legacy_pause_is_allowed_but_model_fingerprint_mismatch_is_not() -> None:
    store, novel, document, revision = _seed_source("")
    pause = ScriptSegmentInput(
        segment_id=uuid4(),
        ordinal=0,
        segment_kind="synthetic_pause",
        source_block_key="legacy-pause",
        source_text="",
        spoken_text="",
        local_hash=text_sha256(""),
        speaker_kind="narrator",
        casting_json={},
        evidence_json={},
        confidence="high",
        pause_before_ms=0,
        pause_after_ms=250,
        manual_override=False,
    )
    row = create_script_draft(
        store,
        CreateScriptDraft(
            novel_id=novel.id,
            document_id=document.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            settings_fingerprint=_settings_fingerprint(novel.id),
            analyzer_fingerprint="a" * 64,
            rules_fingerprint="b" * 64,
            idempotency_key="legacy-pause-v1",
            effective_policy="blockers_only",
            segments=(pause,),
        ),
    )
    assert store.find_one(
        NarrationSegment, script_version_id=row.id
    ).spoken_text == ""
    stored_segment = store.find_one(NarrationSegment, script_version_id=row.id)
    assert stored_segment is not None
    before = (
        row.state,
        row.immutable_hash,
        row.version_number,
        stored_segment.source_block_key,
        stored_segment.spoken_text,
        dict(stored_segment.casting_json),
        dict(stored_segment.evidence_json),
    )
    compatibility = load_script_version_for_read(store, row.id)
    assert isinstance(compatibility, LegacyScriptVersionRead)
    assert compatibility.compatibility_status == "requires_reanalysis"
    assert compatibility.segments[0].spoken_text == ""
    assert compatibility.immutable_hash == row.immutable_hash
    assert before == (
        row.state,
        row.immutable_hash,
        row.version_number,
        stored_segment.source_block_key,
        stored_segment.spoken_text,
        dict(stored_segment.casting_json),
        dict(stored_segment.evidence_json),
    )

    with pytest.raises(NarrationServiceError, match="must match"):
        create_script_draft(
            store,
            CreateScriptDraft(
                novel_id=novel.id,
                document_id=document.id,
                revision_id=revision.id,
                content_hash=revision.content_hash,
                settings_fingerprint=_settings_fingerprint(novel.id),
                analyzer_fingerprint="a" * 64,
                rules_fingerprint="b" * 64,
                requested_model_fingerprint="1" * 64,
                actual_model_fingerprint="2" * 64,
                idempotency_key="legacy-model-mismatch-v1",
                effective_policy="blockers_only",
                segments=(pause,),
            ),
        )


def test_legacy_uuid4_script_root_accepts_a_typed_reanalysis_successor() -> None:
    store, novel, document, revision = _seed_source("")
    pause = ScriptSegmentInput(
        segment_id=uuid4(),
        ordinal=0,
        segment_kind="synthetic_pause",
        source_block_key="legacy-root-pause",
        source_text="",
        spoken_text="",
        local_hash=text_sha256(""),
        speaker_kind="narrator",
        casting_json={},
        evidence_json={},
        confidence="high",
        pause_before_ms=0,
        pause_after_ms=250,
        manual_override=False,
    )
    legacy = create_script_draft(
        store,
        CreateScriptDraft(
            novel_id=novel.id,
            document_id=document.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
            settings_fingerprint=_settings_fingerprint(novel.id),
            analyzer_fingerprint="a" * 64,
            rules_fingerprint="b" * 64,
            idempotency_key="legacy-root-v1",
            effective_policy="blockers_only",
            segments=(pause,),
        ),
    )
    assert legacy.script_id != uuid5(
        document.id,
        f"narration-script:{revision.id}",
    )

    allocation = _reserve(
        store,
        novel,
        document,
        revision,
        key="typed-successor-v2",
    )
    assert allocation.script_id == legacy.script_id
    typed = persist_script_contract(
        store,
        allocation,
        _contract(allocation, ""),
    )

    assert typed.version_number == 2
    assert load_script_contract(store, typed.id).script_id == legacy.script_id
