from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from backend.narration import schemas as wire
from backend.narration.aliases import (
    AliasContractError,
    AliasSource,
    CharacterAliasRecord,
    build_character_alias_index,
)
from backend.narration.casting import (
    CastingAttributes,
    CastingInventory,
    CastingRequest,
    CharacterBindingSnapshot,
    VoiceVersionSnapshot,
    resolve_casting,
)
from backend.narration.cloud_analysis import (
    BoundSpeakerCandidate,
    CloudAnalysisFailure,
    CloudAnalysisFailureCode,
    CloudAnalysisScope,
    CloudConsentSnapshot,
    CloudSourceSegment,
    HmacDigestKey,
    analyze_cloud_window,
    build_minimal_cloud_windows,
    cloud_request_for_window,
)
from backend.narration.confidence import (
    SpeakerConfidenceSignals,
    assess_speaker_confidence,
)
from backend.narration.contracts import ConfidenceLevel
from backend.narration.expression import ExpressionContext, classify_expression
from backend.narration.script_contracts import (
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    Delivery,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
    text_sha256,
)
from backend.narration.segmentation import SourceFormat, segment_source
from backend.narration.speaker_model import (
    ModelIdentity,
    SpeakerEvidenceCode,
    SpeakerModelCandidate,
    SpeakerModelDecision,
    TrustedSpeakerModelReply,
    speaker_model_decision_to_json,
    speaker_model_request_to_json,
    speaker_model_request_to_payload,
)
from backend.narration.speaker_rules import (
    SpeakerRuleContext,
    SpeakerRuleError,
    attribute_speaker_local,
)


def _uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://example.invalid/t3-i/{label}")


SCRIPT_VERSION_ID = _uuid("script-version")
NOVEL_ID = _uuid("novel")
DOCUMENT_ID = _uuid("document")
REVISION_ID = _uuid("revision")
CHAPTER_ID = _uuid("chapter")
VOLUME_ID = _uuid("volume")
SCENE_ID = _uuid("scene")
CONSENT_ID = _uuid("consent")
MODEL_RUN_ID = _uuid("model-run")
MODEL_FINGERPRINT = hashlib.sha256(b"t3-i-fake-speaker-model").hexdigest()

# T3-I 的准确率样本是项目自造、固定且不含用户正文的短句。
# 这里以 10 个明确姓名 × 10 种常见说话标记组成 100 条独立预期。
NAMED_CHARACTERS: tuple[tuple[str, UUID], ...] = tuple(
    (name, _uuid(f"character-{index}"))
    for index, name in enumerate(
        (
            "林晚",
            "沈川",
            "顾宁",
            "苏槿",
            "陆遥",
            "程野",
            "周岚",
            "唐月",
            "许舟",
            "白露",
        ),
        start=1,
    )
)

SPEECH_SAMPLE_TEMPLATES: tuple[str, ...] = (
    "{name}说道：“天亮了。”",
    "{name}问道：“现在出发吗？”",
    "{name}回答：“我准备好了。”",
    "{name}轻声说：“别惊动他们。”",
    "{name}低声说道：“门外有人。”",
    "{name}喊道：“快回来！”",
    "{name}答道：“我明白。”",
    "{name}缓缓说道：“先看看地图。”",
    "“雨停了。”{name}说道。",
    "“我会回来。”{name}轻声说道。",
)


def _aliases():
    return build_character_alias_index(
        tuple(
            CharacterAliasRecord(
                character_id=character_id,
                alias=name,
                source=AliasSource.CANONICAL_NAME,
            )
            for name, character_id in NAMED_CHARACTERS
        ),
        allowed_character_ids=frozenset(
            character_id for _, character_id in NAMED_CHARACTERS
        ),
    )


def _voice_snapshot(character_id: UUID) -> VoiceVersionSnapshot:
    profile_id = _uuid(f"profile-{character_id}")
    version_id = _uuid(f"voice-version-{character_id}")
    return VoiceVersionSnapshot(
        profile_id=profile_id,
        version_id=version_id,
        version_number=3,
        fingerprint=hashlib.sha256(str(version_id).encode("ascii")).hexdigest(),
        profile_novel_id=NOVEL_ID,
        profile_status=wire.VoiceProfileStatus.ACTIVE,
        source_type=wire.VoiceSourceType.PRESET,
        version_state=wire.VoiceVersionState.LOCKED,
        quality_state=wire.VoiceQualityState.ACCEPTED,
        rights_record_id=_uuid(f"rights-{character_id}"),
        rights_state=wire.VoiceRightsState.ACTIVE,
        voice_cloning_permitted=True,
    )


def _cloud_candidate(character_id: UUID) -> BoundSpeakerCandidate:
    speaker = SpeakerRef(SpeakerKind.CHARACTER, character_id=character_id)
    target = CastingTargetRef(
        CastingTargetKind.CHARACTER_BINDING,
        binding_id=_uuid(f"cloud-binding-{character_id}"),
        character_id=character_id,
    )
    return BoundSpeakerCandidate(
        model_candidate=SpeakerModelCandidate(
            speaker=speaker,
            display_name="林晚",
            aliases=("小林",),
            role_hint="当前场景人物",
        ),
        casting=CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        ),
    )


def _cloud_segment(
    ordinal: int,
    text: str,
    *,
    uncertain: bool,
    character_id: UUID,
) -> CloudSourceSegment:
    return CloudSourceSegment(
        segment_id=_uuid(f"cloud-segment-{ordinal}"),
        ordinal=ordinal,
        source_text=text,
        source_local_hash=text_sha256(text),
        needs_cloud_analysis=uncertain,
        candidates=(_cloud_candidate(character_id),) if uncertain else (),
        scene_hint="雨夜门廊" if uncertain else None,
        previous_speaker=SpeakerRef(SpeakerKind.NARRATOR) if uncertain else None,
    )


def test_fixed_named_speech_tag_accuracy_is_at_least_98_percent() -> None:
    aliases = _aliases()
    samples = tuple(
        (template.format(name=name), character_id)
        for name, character_id in NAMED_CHARACTERS
        for template in SPEECH_SAMPLE_TEMPLATES
    )

    correct = 0
    returned_character_ids: set[UUID] = set()
    assert len({source_text for source_text, _ in samples}) == 100
    for source_text, expected_character_id in samples:
        decision = attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.DIALOGUE,
                source_text=source_text,
                scene_character_ids=aliases.allowed_character_ids,
            ),
            aliases=aliases,
        )
        if decision.speaker.character_id is not None:
            returned_character_ids.add(decision.speaker.character_id)
        assessment = assess_speaker_confidence(
            speaker=decision.speaker,
            signals=SpeakerConfidenceSignals(
                identity_candidate_count=1,
                direct_identity_match=True,
                supporting_rule_count=1,
                contextual_rule_count=0,
            ),
        )
        if (
            decision.speaker
            == SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=expected_character_id,
            )
            and decision.confidence is ConfidenceLevel.HIGH
            and assessment.level is ConfidenceLevel.HIGH
            and decision.attribution.candidate_character_ids
            == (expected_character_id,)
            and decision.issue_codes == ()
        ):
            correct += 1

    total = len(samples)
    assert total == 100
    assert correct / total >= 0.98, f"named speech-tag accuracy: {correct}/{total}"
    assert returned_character_ids.issubset(aliases.allowed_character_ids)


def test_segmentation_attribution_expression_and_ids_repeat_exactly() -> None:
    source = (
        "林晚轻声说：“先别开门。”\n"
        "沈川喊道：“快离开！”\n"
        "雨声盖过了脚步。"
    )
    first = segment_source(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        source_format=SourceFormat.PLAIN_TEXT,
    )
    second = segment_source(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        source_format=SourceFormat.PLAIN_TEXT,
    )

    assert first == second
    assert tuple(segment.segment_id for segment in first.segments) == tuple(
        segment.segment_id for segment in second.segments
    )
    dialogue = tuple(
        segment for segment in first.segments if segment.segment_kind is SegmentKind.DIALOGUE
    )
    assert len(dialogue) == 2

    outputs = []
    for segment in dialogue:
        cue_before = first.segments[segment.ordinal - 1].source_text
        speaker = attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=segment.segment_kind,
                source_text=segment.source_text,
                cue_before=cue_before,
            ),
            aliases=_aliases(),
        )
        expression = classify_expression(
            ExpressionContext(
                segment_kind=segment.segment_kind,
                source_text=segment.source_text,
                spoken_text=segment.spoken_text,
                cue_before=cue_before,
            )
        )
        outputs.append((speaker, expression))

    repeated_outputs = []
    for segment in second.segments:
        if segment.segment_kind is not SegmentKind.DIALOGUE:
            continue
        cue_before = second.segments[segment.ordinal - 1].source_text
        repeated_outputs.append(
            (
                attribute_speaker_local(
                    SpeakerRuleContext(
                        segment_kind=segment.segment_kind,
                        source_text=segment.source_text,
                        cue_before=cue_before,
                    ),
                    aliases=_aliases(),
                ),
                classify_expression(
                    ExpressionContext(
                        segment_kind=segment.segment_kind,
                        source_text=segment.source_text,
                        spoken_text=segment.spoken_text,
                        cue_before=cue_before,
                    )
                ),
            )
        )

    assert outputs == repeated_outputs
    assert [item[0].speaker.character_id for item in outputs] == [
        NAMED_CHARACTERS[0][1],
        NAMED_CHARACTERS[1][1],
    ]
    assert [item[1].delivery for item in outputs] == [
        Delivery.WHISPER,
        Delivery.SHOUT,
    ]


def test_configured_character_voice_is_stable_across_multiple_segments() -> None:
    character_id = NAMED_CHARACTERS[0][1]
    voice = _voice_snapshot(character_id)
    binding = CharacterBindingSnapshot(
        novel_id=NOVEL_ID,
        binding_id=_uuid("character-binding"),
        character_id=character_id,
        policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
        profile_id=voice.profile_id,
        version_id=voice.version_id,
        voice=voice,
    )
    inventory = CastingInventory(character_bindings=(binding,))

    resolutions = []
    for index, source_text in enumerate(
        (
            "林晚说道：“先等一等。”",
            "林晚回答：“我还在这里。”",
        )
    ):
        attribution = attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.DIALOGUE,
                source_text=source_text,
            ),
            aliases=_aliases(),
        )
        resolution = resolve_casting(
            CastingRequest(
                novel_id=NOVEL_ID,
                segment_id=_uuid(f"cast-segment-{index}"),
                source_local_hash=text_sha256(source_text),
                segment_kind=SegmentKind.DIALOGUE,
                speaker=attribution.speaker,
                chapter_id=CHAPTER_ID,
                volume_id=VOLUME_ID,
                scene_id=SCENE_ID,
                attributes=CastingAttributes(
                    gender=wire.CastingGender.FEMALE,
                    age_band=wire.CastingAgeBand.YOUNG_ADULT,
                    context_kind=wire.CastingContextKind.DIALOGUE,
                ),
                same_scene_voice_deduplication=True,
                used_voice_version_ids=(
                    frozenset({voice.version_id}) if index else frozenset()
                ),
            ),
            inventory,
        )
        resolutions.append(resolution)

    assert all(item.resolved_voice is not None for item in resolutions)
    assert {item.resolved_voice.version_id for item in resolutions if item.resolved_voice} == {
        voice.version_id
    }
    assert all(item.issues == () for item in resolutions)
    assert all(
        item.decision.final_target is not None
        and item.decision.final_target.binding_id == binding.binding_id
        and item.decision.final_target.character_id == character_id
        for item in resolutions
    )


def test_unauthorized_character_ids_fail_closed_and_are_never_emitted() -> None:
    allowed_id = NAMED_CHARACTERS[0][1]
    unauthorized_id = _uuid("unauthorized-character")
    with pytest.raises(AliasContractError, match="outside server authority"):
        build_character_alias_index(
            (
                CharacterAliasRecord(
                    character_id=unauthorized_id,
                    alias="越界人物",
                    source=AliasSource.IMPORTED,
                ),
            ),
            allowed_character_ids=frozenset({allowed_id}),
        )

    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.INNER_MONOLOGUE,
            source_text="我应该回去。",
            explicit_speaker=SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=unauthorized_id,
            ),
        ),
        aliases=_aliases(),
    )
    assert decision.speaker == SpeakerRef(SpeakerKind.UNKNOWN)
    assert "B_CHARACTER_REFERENCE_INVALID" in decision.issue_codes
    assert decision.attribution.candidate_character_ids == ()

    with pytest.raises(SpeakerRuleError, match="outside server authority"):
        attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.DIALOGUE,
                source_text="“不应该猜测。”",
                scene_character_ids=frozenset({unauthorized_id}),
            ),
            aliases=_aliases(),
        )


def test_cloud_request_is_radius_one_privacy_minimal_and_repeatable() -> None:
    character_id = NAMED_CHARACTERS[0][1]
    segments = (
        _cloud_segment(0, "不可外发的章首资料。", uncertain=False, character_id=character_id),
        _cloud_segment(1, "门外雨声渐近。", uncertain=False, character_id=character_id),
        _cloud_segment(2, "“你终于来了。”", uncertain=True, character_id=character_id),
        _cloud_segment(3, "廊灯忽然熄灭。", uncertain=False, character_id=character_id),
        _cloud_segment(4, "不可外发的章尾资料。", uncertain=False, character_id=character_id),
    )

    windows = build_minimal_cloud_windows(segments)
    assert len(windows) == 1
    request = cloud_request_for_window(windows[0])
    payload = speaker_model_request_to_payload(request)
    first_json = speaker_model_request_to_json(request)
    second_json = speaker_model_request_to_json(
        cloud_request_for_window(build_minimal_cloud_windows(segments)[0])
    )

    assert first_json == second_json
    assert payload["target"]["text"] == segments[2].source_text
    assert [item["text"] for item in payload["context_before"]] == [
        segments[1].source_text
    ]
    assert [item["text"] for item in payload["context_after"]] == [
        segments[3].source_text
    ]
    assert "不可外发的章首资料" not in first_json
    assert "不可外发的章尾资料" not in first_json
    forbidden_fields = {
        "novel_id",
        "document_id",
        "revision_id",
        "consent_id",
        "model_run_id",
        "source_local_hash",
        "requested_model_fingerprint",
        "actual_model_fingerprint",
        "reference_audio",
        "full_character_card",
    }
    outbound = json.loads(first_json)
    assert forbidden_fields.isdisjoint(outbound)
    assert all(f'"{field}"' not in first_json for field in forbidden_fields)


class _FakeGuard:
    def consent_is_active(self, **_: object) -> bool:
        return True

    def source_is_current(self, **_: object) -> bool:
        return True


class _FakeAdapter:
    def __init__(self, reply: TrustedSpeakerModelReply) -> None:
        self.reply = reply
        self.calls: list[str] = []

    async def analyze_speaker(
        self,
        *,
        request_json: str,
        requested_identity: ModelIdentity,
    ) -> TrustedSpeakerModelReply:
        assert requested_identity == self.reply.actual_identity
        self.calls.append(request_json)
        return self.reply


@pytest.mark.asyncio
async def test_cloud_analysis_requires_active_work_scoped_consent_before_fake_call() -> None:
    character_id = NAMED_CHARACTERS[0][1]
    target = _cloud_segment(
        0,
        "“这里安全吗？”",
        uncertain=True,
        character_id=character_id,
    )
    window = build_minimal_cloud_windows((target,))[0]
    identity = ModelIdentity(
        provider_id="fake-provider",
        model_id="fake-speaker-model",
        fingerprint=MODEL_FINGERPRINT,
    )
    model_decision = SpeakerModelDecision(
        segment_id=target.segment_id,
        speaker=SpeakerRef(SpeakerKind.CHARACTER, character_id=character_id),
        confidence=ConfidenceLevel.HIGH,
        evidence_codes=(
            SpeakerEvidenceCode.ALIAS_MATCH,
            SpeakerEvidenceCode.EXPLICIT_SPEECH_TAG,
        ),
    )
    reply = TrustedSpeakerModelReply(
        actual_identity=identity,
        response_json=speaker_model_decision_to_json(model_decision),
    )
    scope = CloudAnalysisScope(NOVEL_ID, DOCUMENT_ID, REVISION_ID)
    active_consent = CloudConsentSnapshot(
        consent_id=CONSENT_ID,
        novel_id=NOVEL_ID,
        version=1,
        active=True,
        provider_id=identity.provider_id,
        model_id=identity.model_id,
    )
    digest_key = HmacDigestKey("t3-i-test-key", b"t3-i-cloud-digest-key-material-0001")

    active_adapter = _FakeAdapter(reply)
    result = await analyze_cloud_window(
        scope=scope,
        window=window,
        consent=active_consent,
        model_run_id=MODEL_RUN_ID,
        requested_identity=identity,
        digest_key=digest_key,
        guard=_FakeGuard(),
        adapter=active_adapter,
    )
    assert len(active_adapter.calls) == 1
    assert result.speaker.character_id == character_id
    assert result.attribution.consent_id == CONSENT_ID

    revoked_adapter = _FakeAdapter(reply)
    with pytest.raises(CloudAnalysisFailure) as error:
        await analyze_cloud_window(
            scope=scope,
            window=window,
            consent=CloudConsentSnapshot(
                consent_id=CONSENT_ID,
                novel_id=NOVEL_ID,
                version=2,
                active=False,
                provider_id=identity.provider_id,
                model_id=identity.model_id,
            ),
            model_run_id=MODEL_RUN_ID,
            requested_identity=identity,
            digest_key=digest_key,
            guard=_FakeGuard(),
            adapter=revoked_adapter,
        )
    assert error.value.code is CloudAnalysisFailureCode.CONSENT_REVOKED_BEFORE_CALL
    assert revoked_adapter.calls == []
