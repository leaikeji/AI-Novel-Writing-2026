from uuid import uuid4

import pytest

from backend.narration import schemas as wire
from backend.narration.casting import (
    AnonymousBindingSnapshot,
    CastingAttributes,
    CastingInventory,
    CastingRequest,
    CastingResolutionSource,
    CastingRuleAction,
    CastingRuleSnapshot,
    CastingScopeKind,
    CharacterBindingSnapshot,
    NarratorSelectionSnapshot,
    VoiceVersionSnapshot,
    resolve_casting,
)
from backend.narration.script_contracts import (
    CastingDecisionOrigin,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
)


def _voice(*, novel_id=None) -> VoiceVersionSnapshot:
    return VoiceVersionSnapshot(
        profile_id=uuid4(),
        version_id=uuid4(),
        version_number=1,
        fingerprint="a" * 64,
        profile_novel_id=novel_id,
        profile_status=wire.VoiceProfileStatus.ACTIVE,
        source_type=wire.VoiceSourceType.PRESET,
        version_state=wire.VoiceVersionState.LOCKED,
        quality_state=wire.VoiceQualityState.PENDING,
        activation_evidence_usable=True,
        rights_record_id=uuid4(),
        rights_state=wire.VoiceRightsState.ACTIVE,
        voice_cloning_permitted=False,
    )


def _request(*, novel_id, speaker, used=frozenset()) -> CastingRequest:
    return CastingRequest(
        novel_id=novel_id,
        segment_id=uuid4(),
        source_local_hash="b" * 64,
        segment_kind=SegmentKind.DIALOGUE,
        speaker=speaker,
        chapter_id=uuid4(),
        volume_id=uuid4(),
        scene_id=uuid4(),
        attributes=CastingAttributes(),
        same_scene_voice_deduplication=True,
        used_voice_version_ids=used,
    )


def test_narrator_uses_most_specific_direct_voice() -> None:
    novel_id = uuid4()
    request = _request(novel_id=novel_id, speaker=SpeakerRef(kind=SpeakerKind.NARRATOR))
    novel_voice = _voice(novel_id=novel_id)
    chapter_voice = _voice(novel_id=novel_id)
    inventory = CastingInventory(
        narrator_selections=(
            NarratorSelectionSnapshot(
                novel_id=novel_id,
                scope_kind=CastingScopeKind.NOVEL,
                scope_id=novel_id,
                profile_id=novel_voice.profile_id,
                version_id=novel_voice.version_id,
                voice=novel_voice,
            ),
            NarratorSelectionSnapshot(
                novel_id=novel_id,
                scope_kind=CastingScopeKind.CHAPTER,
                scope_id=request.chapter_id,
                profile_id=chapter_voice.profile_id,
                version_id=chapter_voice.version_id,
                voice=chapter_voice,
            ),
        )
    )
    result = resolve_casting(request, inventory)
    assert result.source is CastingResolutionSource.CHAPTER_NARRATOR
    assert result.resolved_voice.version_id == chapter_voice.version_id
    assert result.warning_codes == ()


@pytest.mark.parametrize(
    ("policy", "source"),
    [
        (wire.CharacterVoiceBindingPolicy.DEDICATED, CastingResolutionSource.CHARACTER_DEDICATED),
        (wire.CharacterVoiceBindingPolicy.INHERITED, CastingResolutionSource.CHARACTER_INHERITED),
    ],
)
def test_character_qwen_binding_is_preserved(policy, source) -> None:
    novel_id, character_id, binding_id = uuid4(), uuid4(), uuid4()
    voice = _voice(novel_id=novel_id)
    result = resolve_casting(
        _request(
            novel_id=novel_id,
            speaker=SpeakerRef(kind=SpeakerKind.CHARACTER, character_id=character_id),
        ),
        CastingInventory(
            character_bindings=(
                CharacterBindingSnapshot(
                    novel_id=novel_id,
                    binding_id=binding_id,
                    character_id=character_id,
                    policy=policy,
                    profile_id=voice.profile_id,
                    version_id=voice.version_id,
                    voice=voice,
                ),
            )
        ),
    )
    assert result.source is source
    assert result.resolved_voice.version_id == voice.version_id


def test_anonymous_requires_its_own_direct_usable_voice() -> None:
    novel_id, anonymous_id = uuid4(), uuid4()
    voice = _voice(novel_id=novel_id)
    speaker = SpeakerRef(kind=SpeakerKind.ANONYMOUS, anonymous_speaker_id=anonymous_id)
    direct = resolve_casting(
        _request(novel_id=novel_id, speaker=speaker),
        CastingInventory(
            anonymous_bindings=(
                AnonymousBindingSnapshot(
                    novel_id=novel_id,
                    anonymous_speaker_id=anonymous_id,
                    profile_id=voice.profile_id,
                    version_id=voice.version_id,
                    voice=voice,
                ),
            )
        ),
    )
    assert direct.source is CastingResolutionSource.ANONYMOUS_BINDING
    assert direct.resolved_voice.version_id == voice.version_id

    missing = resolve_casting(
        _request(novel_id=novel_id, speaker=speaker), CastingInventory()
    )
    assert missing.decision.origin is CastingDecisionOrigin.UNRESOLVED
    assert "B_VOICE_MISSING" in missing.blocker_codes


def test_group_does_not_fall_back_to_narrator_or_generic_voice() -> None:
    novel_id = uuid4()
    narrator = _voice(novel_id=novel_id)
    result = resolve_casting(
        _request(
            novel_id=novel_id,
            speaker=SpeakerRef(kind=SpeakerKind.GROUP, group_key="grp1_" + "c" * 64),
        ),
        CastingInventory(
            narrator_selections=(
                NarratorSelectionSnapshot(
                    novel_id=novel_id,
                    scope_kind=CastingScopeKind.NOVEL,
                    scope_id=novel_id,
                    profile_id=narrator.profile_id,
                    version_id=narrator.version_id,
                    voice=narrator,
                ),
            )
        ),
    )
    assert result.decision.origin is CastingDecisionOrigin.UNRESOLVED
    assert result.resolved_voice is None
    assert "B_VOICE_MISSING" in result.blocker_codes
    assert result.warning_codes == ()


def test_explicit_direct_rule_remains_supported() -> None:
    novel_id = uuid4()
    voice = _voice(novel_id=novel_id)
    request = _request(
        novel_id=novel_id,
        speaker=SpeakerRef(kind=SpeakerKind.GROUP, group_key="grp1_" + "c" * 64),
    )
    rule = CastingRuleSnapshot(
        novel_id=novel_id,
        rule_id=uuid4(),
        version=1,
        priority=10,
        enabled=True,
        condition=wire.VoiceCastingCondition(
            speaker_kinds=[wire.CastingSpeakerKind.GROUP],
            genders=[],
            age_bands=[],
            context_kinds=[],
            role_tags=[],
        ),
        action=CastingRuleAction.VOICE_VERSION,
        profile_id=voice.profile_id,
        version_id=voice.version_id,
        voice=voice,
    )
    result = resolve_casting(request, CastingInventory(rules=(rule,)))
    assert result.decision.origin is CastingDecisionOrigin.CASTING_RULE
    assert result.decision.final_target.profile_id == voice.profile_id
    assert result.warning_codes == ()


def test_current_contract_has_no_generic_pool_exports_or_actions() -> None:
    import backend.narration.casting as casting

    assert "GenericPoolSnapshot" not in casting.__all__
    assert "GenericSlotSnapshot" not in casting.__all__
    assert {action.value for action in CastingRuleAction} == {
        "voice_version",
        "require_review",
    }
