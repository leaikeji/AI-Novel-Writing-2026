from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.models import (
    CharacterAlias,
    CharacterVoiceBinding,
    Document,
    DocumentRevision,
    NarrationEdition,
    NarrationScriptVersion,
    NovelCharacter,
    NovelNarrationSettings,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration import schemas as wire
from backend.narration.privacy import (
    _storage_settings,
    default_narration_settings_values,
)
from backend.narration.requests import CreateNarrationRequest, create_request
from backend.narration.script_analysis import (
    AnalyzeNarrationScript,
    analyze_narration_script,
)
from backend.narration.script_contracts import (
    CastingDecisionOrigin,
    ScriptVersionState,
    SpeakerKind,
    script_contract_to_dict,
    text_sha256,
)
from backend.narration.script_versions import load_script_contract
from backend.narration.services import (
    InvalidNarrationState,
    NarrationScopeMismatch,
    StaleNarrationInput,
)
from backend.narration.snapshots import CreateSettingsSnapshot, create_settings_snapshot
from tests.narration.test_domain_services import MemoryNarrationStore, _novel


NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


def _voice(
    store: MemoryNarrationStore,
    novel_id,
    *,
    name: str,
) -> tuple[VoiceProfile, VoiceProfileVersion]:
    rights = VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        source_kind="licensed_preset",
        source_identifier=f"preset:{name}",
        notice_version="voice-rights/1",
        purpose="narration",
        commercial_use=True,
        redistribution=False,
        voice_cloning=True,
        confirmed_actor="owner",
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=365),
        risk_flags_json=[],
    )
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        name=name,
        status="active",
        version=1,
    )
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type="preset",
        state="locked",
        preset_key=name,
        rights_record_id=rights.id,
        language="zh-CN",
        parameters_json={},
        fingerprint=text_sha256(name),
        quality_state="accepted",
        activation_basis="preview_confirmed",
        validation_basis="human_accepted",
        locked_actor="owner",
        locked_at=NOW,
    )
    profile.current_version_id = version.id
    store.add(rights)
    store.add(profile)
    store.add(version)
    return profile, version


def _seed(
    source: str,
    *,
    intent: str = "analyze_only",
    include_character_voice: bool = True,
):
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
    character = NovelCharacter(
        id=uuid4(),
        novel_id=novel.id,
        role_type="protagonist",
        name="林晚",
        description="",
        details={},
        lifecycle_state="active",
        position=0,
        version=1,
    )
    store.add(novel)
    store.add(document)
    store.add(revision)
    store.add(character)
    narrator_profile, narrator_version = _voice(
        store, novel.id, name="narrator"
    )
    if include_character_voice:
        character_profile, character_version = _voice(
            store, novel.id, name="character"
        )
        store.add(
            CharacterVoiceBinding(
                id=uuid4(),
                novel_id=novel.id,
                character_id=character.id,
                profile_id=character_profile.id,
                voice_version_id=character_version.id,
                binding_policy="dedicated",
                language="zh-CN",
                parameters_json={},
                version=1,
            )
        )
    values = default_narration_settings_values().model_copy(
        update={
            "narrator": wire.NarratorVoiceSelection(
                profile_id=narrator_profile.id,
                version_id=narrator_version.id,
            )
        }
    )
    settings = NovelNarrationSettings(
        id=uuid4(),
        novel_id=novel.id,
        narrator_profile_id=narrator_profile.id,
        narrator_version_id=narrator_version.id,
        script_review_policy=values.script_review_policy.value,
        analysis_mode=values.analysis_mode.value,
        settings_json=_storage_settings(values),
        version=1,
    )
    store.add(settings)
    snapshot = create_settings_snapshot(
        store,
        CreateSettingsSnapshot(novel_id=novel.id, settings_version=1),
    )
    request = create_request(
        store,
        CreateNarrationRequest(
            novel_id=novel.id,
            document_id=document.id,
            source_revision_id=revision.id,
            source_content_hash=revision.content_hash,
            intent=intent,
            idempotency_key=f"request-{intent}-0001",
            settings_fingerprint=snapshot.fingerprint,
            effective_policy="blockers_only",
            explicit_generation_intent_at=(None if intent == "analyze_only" else NOW),
            explicit_generation_actor=(None if intent == "analyze_only" else "owner"),
        ),
    )
    command = AnalyzeNarrationScript(
        request_id=request.id,
        document_id=document.id,
        revision_id=revision.id,
        content_hash=revision.content_hash,
        idempotency_key="analyze-action-0001",
    )
    return store, novel, document, revision, character, request, command


def test_local_analysis_recognizes_character_and_uses_configured_voices() -> None:
    store, _novel_row, _document, _revision, character, request, command = _seed(
        "林晚说道：“你终于来了。”"
    )

    script = analyze_narration_script(store, command)

    dialogue = next(
        segment for segment in script.segments if segment.speaker.kind is SpeakerKind.CHARACTER
    )
    assert dialogue.speaker.character_id == character.id
    assert dialogue.casting.origin is CastingDecisionOrigin.CHARACTER_BINDING
    assert any(
        segment.speaker.kind is SpeakerKind.NARRATOR
        and segment.casting.origin is CastingDecisionOrigin.NARRATOR_SETTING
        for segment in script.segments
    )
    assert script.state is ScriptVersionState.ANALYZED
    assert script.blocker_count == 0
    assert request.state == "analyzed"
    assert store.rows[NarrationEdition] == []


def test_local_analysis_accepts_plan36_character_authority_aliases() -> None:
    store, novel, _document, _revision, character, request, command = _seed(
        "林队说道：“按人物卡里的正式别名识别我。”"
    )
    store.add(
        CharacterAlias(
            id=uuid4(),
            novel_id=novel.id,
            character_id=character.id,
            alias="林队",
            normalized_alias="林队",
            alias_kind="former_name",
            identity_layer="public",
            source="character_authority",
            lifecycle_state="active",
        )
    )

    script = analyze_narration_script(store, command)

    dialogue = next(
        segment for segment in script.segments if segment.speaker.kind is SpeakerKind.CHARACTER
    )
    assert dialogue.speaker.character_id == character.id
    assert dialogue.casting.origin is CastingDecisionOrigin.CHARACTER_BINDING
    assert script.blocker_count == 0
    assert request.state == "analyzed"


def test_local_analysis_never_uses_next_paragraph_cue_for_previous_dialogue() -> None:
    store, _novel_row, _document, _revision, character, _request, command = _seed(
        "“这句没有说话提示。”\n\n林晚说道：“这句才属于林晚。”"
    )

    script = analyze_narration_script(store, command)

    dialogues = [
        segment for segment in script.segments if segment.segment_kind.value == "dialogue"
    ]
    assert len(dialogues) == 2
    assert dialogues[0].speaker.kind is SpeakerKind.UNKNOWN
    assert dialogues[1].speaker.character_id == character.id


def test_unknown_speaker_keeps_both_speaker_blockers_and_casting_blocker() -> None:
    store, _novel_row, _document, _revision, _character, request, command = _seed(
        "“没有任何说话提示。”"
    )

    script = analyze_narration_script(store, command)

    segment = script.segments[0]
    codes = {issue.code for issue in script.issues if issue.segment_id == segment.segment_id}
    assert segment.speaker.kind is SpeakerKind.UNKNOWN
    assert {
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_SPEAKER_UNKNOWN",
        "B_CASTING_TARGET_UNRESOLVED",
    }.issubset(codes)
    assert script.state is ScriptVersionState.REVIEW_REQUIRED
    assert request.state == "review_required"
    assert store.rows[NarrationEdition] == []


def test_generation_intent_clean_script_auto_freezes_without_creating_edition() -> None:
    store, _novel_row, _document, _revision, _character, request, command = _seed(
        "林晚说道：“走吧。”",
        intent="create",
    )

    script = analyze_narration_script(store, command)

    assert script.state is ScriptVersionState.APPROVED
    assert script.approval is not None
    assert script.approval.kind.value == "auto_no_blockers"
    assert script.approval.request_id == request.id
    assert request.state == "analyzed"
    assert store.rows[NarrationEdition] == []


def test_approved_script_remains_readable_after_character_rebind_archive_and_unset() -> None:
    store, _novel_row, _document, _revision, character, _request, command = _seed(
        "林晚说道：“走吧。”",
        intent="create",
    )
    approved = analyze_narration_script(store, command)
    binding = store.find_one(
        CharacterVoiceBinding,
        character_id=character.id,
    )
    assert binding is not None
    replacement_profile, replacement_version = _voice(
        store,
        character.novel_id,
        name="replacement-character",
    )
    binding.profile_id = replacement_profile.id
    binding.voice_version_id = replacement_version.id

    rebound = load_script_contract(store, approved.script_version_id)
    assert script_contract_to_dict(rebound) == script_contract_to_dict(approved)

    character.lifecycle_state = "archived"
    store.rows[CharacterVoiceBinding].remove(binding)
    historical = load_script_contract(store, approved.script_version_id)
    assert script_contract_to_dict(historical) == script_contract_to_dict(approved)
    assert historical.immutable_hash == approved.immutable_hash


def test_unapproved_script_still_rejects_revoked_character_authority() -> None:
    store, _novel_row, _document, _revision, character, _request, command = _seed(
        "林晚说道：“先别批准。”"
    )
    analyzed = analyze_narration_script(store, command)
    assert analyzed.state is ScriptVersionState.ANALYZED
    binding = store.find_one(
        CharacterVoiceBinding,
        character_id=character.id,
    )
    assert binding is not None
    character.lifecycle_state = "archived"
    store.rows[CharacterVoiceBinding].remove(binding)

    with pytest.raises(NarrationScopeMismatch, match="active novel scope"):
        load_script_contract(store, analyzed.script_version_id)


def test_analysis_replay_returns_same_version_and_never_duplicates_children() -> None:
    store, _novel_row, _document, _revision, _character, _request, command = _seed(
        "林晚说道：“重复也只能是一份。”"
    )

    first = analyze_narration_script(store, command)
    versions_before = len(store.rows[NarrationScriptVersion])
    second = analyze_narration_script(store, command)

    assert second.script_version_id == first.script_version_id
    assert second.immutable_hash == first.immutable_hash
    assert len(store.rows[NarrationScriptVersion]) == versions_before == 1


def test_completed_request_rejects_a_different_analysis_action_key() -> None:
    store, _novel_row, _document, _revision, _character, _request, command = _seed(
        "林晚说道：“不要重复建立版本。”"
    )
    analyze_narration_script(store, command)

    with pytest.raises(InvalidNarrationState, match="only replay"):
        analyze_narration_script(
            store,
            AnalyzeNarrationScript(
                request_id=command.request_id,
                document_id=command.document_id,
                revision_id=command.revision_id,
                content_hash=command.content_hash,
                idempotency_key="analyze-action-0002",
            ),
        )


def test_analysis_request_cannot_cross_document_scope() -> None:
    store, novel, _document, revision, _character, _request, command = _seed(
        "林晚说道：“范围必须正确。”"
    )
    foreign = Document(
        id=uuid4(),
        novel_id=novel.id,
        kind="chapter",
        title="第二章",
        position=2,
        status="draft",
        version=1,
    )
    store.add(foreign)

    with pytest.raises(
        (NarrationScopeMismatch, InvalidNarrationState, StaleNarrationInput)
    ):
        analyze_narration_script(
            store,
            AnalyzeNarrationScript(
                request_id=command.request_id,
                document_id=foreign.id,
                revision_id=revision.id,
                content_hash=revision.content_hash,
                idempotency_key=command.idempotency_key,
            ),
        )
