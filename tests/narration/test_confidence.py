from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.narration.confidence import (
    AnchorUniquenessEvidence,
    ConfidenceRuleError,
    InheritanceAuditStamp,
    ManualOverrideSource,
    ModelConsistency,
    OverrideInheritanceAuthority,
    OverrideInheritanceReason,
    OverrideInheritanceTarget,
    SpeakerConfidenceSignals,
    assess_speaker_confidence,
    decide_override_inheritance,
)
from backend.narration.contracts import ConfidenceLevel, ReviewIssueSeverity
from backend.narration.expression import (
    EXPRESSION_RULESET_VERSION,
    ExpressionContext,
    ExpressionRuleError,
    classify_expression,
)
from backend.narration.script_contracts import (
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    Delivery,
    Emotion,
    OverrideKind,
    OverrideProvenance,
    ScriptVersionState,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
)

NOVEL_ID = UUID("99000000-0000-4000-8000-000000000001")
OTHER_NOVEL_ID = UUID("99000000-0000-4000-8000-000000000002")
SOURCE_VERSION_ID = UUID("99000000-0000-4000-8000-000000000003")
TARGET_VERSION_ID = UUID("99000000-0000-4000-8000-000000000004")
SOURCE_SEGMENT_ID = UUID("99000000-0000-4000-8000-000000000005")
TARGET_SEGMENT_ID = UUID("99000000-0000-4000-8000-000000000006")
ACTION_ID = UUID("99000000-0000-4000-8000-000000000007")
PROFILE_ID = UUID("99000000-0000-4000-8000-000000000008")
OTHER_PROFILE_ID = UUID("99000000-0000-4000-8000-000000000009")

LOCAL_HASH = "1" * 64
BEFORE_HASH = "2" * 64
AFTER_HASH = "3" * 64
IMMUTABLE_HASH = "4" * 64
OTHER_HASH = "5" * 64
OWNER_ACTOR_ID = "local-owner"
RECORDED_AT = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)


def _speaker() -> SpeakerRef:
    return SpeakerRef(kind=SpeakerKind.NARRATOR)


def _unknown_speaker() -> SpeakerRef:
    return SpeakerRef(kind=SpeakerKind.UNKNOWN)


def _casting(profile_id: UUID = PROFILE_ID) -> CastingDecision:
    target = CastingTargetRef(
        kind=CastingTargetKind.PROFILE,
        profile_id=profile_id,
    )
    return CastingDecision(
        candidate_targets=(target,),
        final_target=target,
        origin=CastingDecisionOrigin.NARRATOR_SETTING,
    )


def _manual_provenance(
    *,
    local_hash: str = LOCAL_HASH,
    before_hash: str | None = BEFORE_HASH,
    after_hash: str | None = AFTER_HASH,
    casting: CastingDecision | None = None,
) -> OverrideProvenance:
    selected_casting = casting or _casting()
    return OverrideProvenance(
        kind=OverrideKind.MANUAL_CURRENT,
        action_id=ACTION_ID,
        owner_actor_id=OWNER_ACTOR_ID,
        recorded_at=RECORDED_AT,
        source_local_hash=local_hash,
        source_anchor_before_hash=before_hash,
        source_anchor_after_hash=after_hash,
        speaker_target_hash=speaker_target_hash(_speaker(), selected_casting),
    )


def _source(
    *,
    novel_id: UUID = NOVEL_ID,
    script_state: ScriptVersionState = ScriptVersionState.APPROVED,
    local_hash: str = LOCAL_HASH,
    before_hash: str | None = BEFORE_HASH,
    after_hash: str | None = AFTER_HASH,
    casting: CastingDecision | None = None,
) -> ManualOverrideSource:
    selected_casting = casting or _casting()
    return ManualOverrideSource(
        novel_id=novel_id,
        script_version_id=SOURCE_VERSION_ID,
        segment_id=SOURCE_SEGMENT_ID,
        script_immutable_hash=IMMUTABLE_HASH,
        script_state=script_state,
        local_hash=local_hash,
        anchor_before_hash=before_hash,
        anchor_after_hash=after_hash,
        speaker=_speaker(),
        casting=selected_casting,
        attribution_origin=AttributionOrigin.MANUAL_OVERRIDE,
        manual_override=True,
        provenance=_manual_provenance(
            local_hash=local_hash,
            before_hash=before_hash,
            after_hash=after_hash,
            casting=selected_casting,
        ),
    )


def _uniqueness(
    *,
    local_count: int = 1,
    before_count: int = 1,
    after_count: int = 1,
    combined_count: int = 1,
    at_start: bool = False,
    at_end: bool = False,
) -> AnchorUniquenessEvidence:
    return AnchorUniquenessEvidence(
        local_hash_match_count=local_count,
        before_anchor_match_count=before_count,
        after_anchor_match_count=after_count,
        combined_match_count=combined_count,
        target_at_document_start=at_start,
        target_at_document_end=at_end,
    )


def _target(
    *,
    novel_id: UUID = NOVEL_ID,
    script_version_id: UUID = TARGET_VERSION_ID,
    local_hash: str = LOCAL_HASH,
    before_hash: str | None = BEFORE_HASH,
    after_hash: str | None = AFTER_HASH,
    casting: CastingDecision | None = None,
    uniqueness: AnchorUniquenessEvidence | None = None,
) -> OverrideInheritanceTarget:
    return OverrideInheritanceTarget(
        novel_id=novel_id,
        script_version_id=script_version_id,
        segment_id=TARGET_SEGMENT_ID,
        local_hash=local_hash,
        anchor_before_hash=before_hash,
        anchor_after_hash=after_hash,
        speaker=_speaker(),
        casting=casting or _casting(),
        uniqueness=uniqueness or _uniqueness(),
    )


def _authority(source: ManualOverrideSource) -> OverrideInheritanceAuthority:
    return OverrideInheritanceAuthority(
        novel_id=source.novel_id,
        owner_actor_id=OWNER_ACTOR_ID,
        authorized_sources=frozenset({source}),
    )


def _audit(owner_actor_id: str = OWNER_ACTOR_ID) -> InheritanceAuditStamp:
    return InheritanceAuditStamp(
        action_id=UUID("99000000-0000-4000-8000-000000000010"),
        owner_actor_id=owner_actor_id,
        recorded_at=RECORDED_AT,
    )


def _decision(
    source: ManualOverrideSource | None = None,
    target: OverrideInheritanceTarget | None = None,
    authority: OverrideInheritanceAuthority | None = None,
    audit: InheritanceAuditStamp | None = None,
):
    selected_source = source or _source()
    return decide_override_inheritance(
        source=selected_source,
        target=target or _target(),
        authority=authority or _authority(selected_source),
        audit=audit or _audit(),
    )


def test_expression_defaults_to_neutral_normal_with_high_rule_certainty() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.NARRATION,
            source_text="暮色落在长街上。",
            spoken_text="暮色落在长街上。",
        )
    )

    assert decision.emotion is Emotion.NEUTRAL
    assert decision.emotion_confidence is ConfidenceLevel.HIGH
    assert decision.delivery is Delivery.NORMAL
    assert decision.emotion_rule_codes == ("expression.emotion.default_neutral",)
    assert decision.delivery_rule_codes == ("expression.delivery.default_normal",)
    assert not decision.has_conflict


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("她微笑着说。", Emotion.HAPPY),
        ("他哽咽着回答。", Emotion.SAD),
        ("她愤怒地转身。", Emotion.ANGRY),
        ("他恐惧地后退。", Emotion.FEARFUL),
        ("她警惕地望向门口。", Emotion.TENSE),
    ],
)
def test_expression_single_emotion_signal_is_medium(
    text: str, expected: Emotion
) -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text=text,
            spoken_text=text,
        )
    )

    assert decision.emotion is expected
    assert decision.emotion_confidence is ConfidenceLevel.MEDIUM
    assert f"expression.emotion.signal.{expected.value}" in decision.rule_codes


def test_expression_two_same_family_signals_are_high() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="她欣喜地微笑着说。",
            spoken_text="她欣喜地微笑着说。",
        )
    )

    assert decision.emotion is Emotion.HAPPY
    assert decision.emotion_confidence is ConfidenceLevel.HIGH
    assert "expression.emotion.corroborated" in decision.rule_codes


def test_expression_overlapping_phrase_is_one_signal_not_false_corroboration() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.NARRATION,
            source_text="他的呼吸急促。",
            spoken_text="他的呼吸急促。",
        )
    )

    assert decision.emotion is Emotion.TENSE
    assert decision.emotion_confidence is ConfidenceLevel.MEDIUM


def test_expression_competing_emotions_with_unique_leader_are_low() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="她欣喜地微笑，眼里却含泪。",
            spoken_text="她欣喜地微笑，眼里却含泪。",
        )
    )

    assert decision.emotion is Emotion.HAPPY
    assert decision.emotion_confidence is ConfidenceLevel.LOW
    assert decision.conflict_codes == ("expression.conflict.emotion_competing",)


def test_expression_tied_emotions_fail_closed_to_unknown_neutral() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="她微笑着，眼里却含泪。",
            spoken_text="她微笑着，眼里却含泪。",
        )
    )

    assert decision.emotion is Emotion.NEUTRAL
    assert decision.emotion_confidence is ConfidenceLevel.UNKNOWN
    assert decision.conflict_codes == ("expression.conflict.emotion_tie",)


@pytest.mark.parametrize(
    ("text", "expected", "rule"),
    [
        ("她压低声音说。", Delivery.WHISPER, "expression.delivery.signal.whisper"),
        ("他大声喊道。", Delivery.SHOUT, "expression.delivery.signal.shout"),
    ],
)
def test_expression_delivery_markers(
    text: str, expected: Delivery, rule: str
) -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text=text,
            spoken_text=text,
        )
    )
    assert decision.delivery is expected
    assert rule in decision.rule_codes


def test_expression_delivery_conflict_returns_safe_normal_and_evidence() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="她先轻声耳语，随后大声喊道。",
            spoken_text="她先轻声耳语，随后大声喊道。",
        )
    )

    assert decision.delivery is Delivery.NORMAL
    assert decision.conflict_codes == ("expression.conflict.delivery_competing",)


def test_inner_monologue_structure_dominates_lexical_delivery_cues() -> None:
    decision = classify_expression(
        ExpressionContext(
            segment_kind=SegmentKind.INNER_MONOLOGUE,
            source_text="我在心里大声喊道：不能回头。",
            spoken_text="我在心里大声喊道：不能回头。",
        )
    )

    assert decision.delivery is Delivery.INNER_MONOLOGUE
    assert decision.delivery_rule_codes == (
        "expression.delivery.segment_inner_monologue",
    )
    assert "expression.conflict.delivery_competing" not in decision.conflict_codes


def test_expression_uses_bounded_adjacent_cue_without_mutating_text() -> None:
    context = ExpressionContext(
        segment_kind=SegmentKind.DIALOGUE,
        source_text="“别动。”",
        spoken_text="别动。",
        cue_before="她恐惧地压低声音，",
    )
    decision = classify_expression(context)

    assert decision.emotion is Emotion.FEARFUL
    assert decision.delivery is Delivery.WHISPER
    assert context.source_text == "“别动。”"
    assert context.spoken_text == "别动。"


def test_expression_normalizes_evidence_without_mutating_input() -> None:
    context = ExpressionContext(
        segment_kind=SegmentKind.NARRATION,
        source_text="Cafe\u0301",
        spoken_text="Cafe\u0301",
    )
    first = classify_expression(context)
    second = classify_expression(context)

    assert context.source_text == "Cafe\u0301"
    assert context.spoken_text == "Cafe\u0301"
    assert first == second
    assert first.rule_codes == tuple(sorted(set(first.rule_codes)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"segment_kind": "dialogue", "source_text": "x", "spoken_text": "x"},
        {
            "segment_kind": SegmentKind.DIALOGUE,
            "source_text": "x",
            "spoken_text": "x",
            "ruleset_version": "future",
        },
        {
            "segment_kind": SegmentKind.DIALOGUE,
            "source_text": "x" * 20_001,
            "spoken_text": "x",
        },
    ],
)
def test_expression_rejects_malformed_or_unknown_policy_input(kwargs: dict) -> None:
    with pytest.raises(ExpressionRuleError):
        ExpressionContext(**kwargs)


def test_expression_rejects_non_context_call() -> None:
    with pytest.raises(ExpressionRuleError, match="ExpressionContext"):
        classify_expression(object())


@pytest.mark.parametrize(
    (
        "speaker",
        "signals",
        "expected_level",
        "expected_issues",
        "expected_evidence",
    ),
    [
        (
            _unknown_speaker(),
            SpeakerConfidenceSignals(0, False, 0, 0),
            ConfidenceLevel.UNKNOWN,
            ("B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"),
            "confidence.identity.unknown",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(1, True, 3, 0, identity_conflict=True),
            ConfidenceLevel.LOW,
            ("B_SPEAKER_LOW_CONFIDENCE",),
            "confidence.identity.conflict",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(0, False, 0, 0),
            ConfidenceLevel.LOW,
            ("B_SPEAKER_LOW_CONFIDENCE",),
            "confidence.identity.candidate_count_not_one",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(2, True, 3, 0),
            ConfidenceLevel.LOW,
            ("B_SPEAKER_LOW_CONFIDENCE",),
            "confidence.identity.candidate_count_not_one",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(
                1,
                True,
                3,
                0,
                model_consistency=ModelConsistency.CONFLICTING,
            ),
            ConfidenceLevel.LOW,
            ("B_SPEAKER_LOW_CONFIDENCE",),
            "confidence.corroboration.conflicting",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(1, True, 0, 0),
            ConfidenceLevel.HIGH,
            (),
            "confidence.identity.direct_unique",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(1, False, 2, 0),
            ConfidenceLevel.HIGH,
            (),
            "confidence.local_rules.corroborated",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(
                1,
                False,
                1,
                0,
                model_consistency=ModelConsistency.CONSISTENT,
            ),
            ConfidenceLevel.HIGH,
            (),
            "confidence.corroboration.consistent",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(1, False, 1, 0),
            ConfidenceLevel.MEDIUM,
            ("W_SPEAKER_MEDIUM_CONFIDENCE",),
            "confidence.local_rule.single",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(1, False, 0, 1),
            ConfidenceLevel.MEDIUM,
            ("W_SPEAKER_MEDIUM_CONFIDENCE",),
            "confidence.context.unique",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(
                1,
                False,
                0,
                0,
                model_consistency=ModelConsistency.CONSISTENT,
            ),
            ConfidenceLevel.MEDIUM,
            ("W_SPEAKER_MEDIUM_CONFIDENCE",),
            "confidence.corroboration.only",
        ),
        (
            _speaker(),
            SpeakerConfidenceSignals(1, False, 0, 0),
            ConfidenceLevel.LOW,
            ("B_SPEAKER_LOW_CONFIDENCE",),
            "confidence.evidence.insufficient",
        ),
    ],
)
def test_speaker_confidence_calibration_matrix(
    speaker: SpeakerRef,
    signals: SpeakerConfidenceSignals,
    expected_level: ConfidenceLevel,
    expected_issues: tuple[str, ...],
    expected_evidence: str,
) -> None:
    decision = assess_speaker_confidence(speaker=speaker, signals=signals)

    assert decision.level is expected_level
    assert decision.issue_codes == expected_issues
    assert expected_evidence in decision.evidence_codes


def test_unknown_speaker_dominates_positive_and_conflicting_signals() -> None:
    decision = assess_speaker_confidence(
        speaker=_unknown_speaker(),
        signals=SpeakerConfidenceSignals(
            1,
            True,
            16,
            16,
            identity_conflict=True,
            model_consistency=ModelConsistency.CONSISTENT,
        ),
    )
    assert decision.level is ConfidenceLevel.UNKNOWN
    assert "confidence.identity.conflict" in decision.evidence_codes


def test_speaker_confidence_materializes_exact_frozen_issue_severity() -> None:
    medium = assess_speaker_confidence(
        speaker=_speaker(),
        signals=SpeakerConfidenceSignals(1, False, 1, 0),
    )
    low = assess_speaker_confidence(
        speaker=_speaker(),
        signals=SpeakerConfidenceSignals(1, False, 0, 0),
    )

    assert medium.to_script_issues(segment_id=TARGET_SEGMENT_ID)[0].severity is (
        ReviewIssueSeverity.WARNING
    )
    assert low.to_script_issues(segment_id=TARGET_SEGMENT_ID)[0].severity is (
        ReviewIssueSeverity.BLOCKER
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "identity_candidate_count": 33,
            "direct_identity_match": False,
            "supporting_rule_count": 0,
            "contextual_rule_count": 0,
        },
        {
            "identity_candidate_count": 1,
            "direct_identity_match": 1,
            "supporting_rule_count": 0,
            "contextual_rule_count": 0,
        },
        {
            "identity_candidate_count": 1,
            "direct_identity_match": False,
            "supporting_rule_count": 17,
            "contextual_rule_count": 0,
        },
        {
            "identity_candidate_count": 1,
            "direct_identity_match": False,
            "supporting_rule_count": 0,
            "contextual_rule_count": 17,
        },
        {
            "identity_candidate_count": 1,
            "direct_identity_match": False,
            "supporting_rule_count": 0,
            "contextual_rule_count": 0,
            "model_consistency": "consistent",
        },
    ],
)
def test_speaker_confidence_rejects_out_of_contract_signal_boundaries(
    kwargs: dict,
) -> None:
    with pytest.raises(ConfidenceRuleError):
        SpeakerConfidenceSignals(**kwargs)


def test_speaker_confidence_accepts_frozen_maximum_counts() -> None:
    decision = assess_speaker_confidence(
        speaker=_speaker(),
        signals=SpeakerConfidenceSignals(1, False, 16, 16),
    )
    assert decision.level is ConfidenceLevel.HIGH


def test_speaker_confidence_rejects_non_contract_arguments() -> None:
    with pytest.raises(ConfidenceRuleError, match="SpeakerRef"):
        assess_speaker_confidence(
            speaker=object(),
            signals=SpeakerConfidenceSignals(1, False, 1, 0),
        )
    with pytest.raises(ConfidenceRuleError, match="SpeakerConfidenceSignals"):
        assess_speaker_confidence(speaker=_speaker(), signals=object())


def test_override_inheritance_emits_exact_provenance_attribution_and_warning() -> None:
    source = _source()
    decision = _decision(source=source)

    assert decision.eligible
    assert decision.reason is OverrideInheritanceReason.ELIGIBLE
    assert decision.provenance is not None
    assert decision.provenance.kind is OverrideKind.INHERITED
    assert decision.provenance.source_script_version_id == source.script_version_id
    assert decision.provenance.source_segment_id == source.segment_id
    assert decision.provenance.source_immutable_hash == source.script_immutable_hash
    assert decision.provenance.source_local_hash == LOCAL_HASH
    assert decision.provenance.source_anchor_before_hash == BEFORE_HASH
    assert decision.provenance.source_anchor_after_hash == AFTER_HASH
    assert decision.provenance.speaker_target_hash == speaker_target_hash(
        _speaker(), _casting()
    )
    attribution = decision.to_attribution()
    assert attribution is not None
    assert attribution.origin is AttributionOrigin.INHERITED_OVERRIDE
    issue = decision.to_script_issues(segment_id=TARGET_SEGMENT_ID)
    assert len(issue) == 1
    assert issue[0].code == "W_MANUAL_OVERRIDE_INHERITED"
    assert issue[0].severity is ReviewIssueSeverity.WARNING


def test_override_inheritance_accepts_exact_approved_inherited_source_chain() -> None:
    source = _source()
    inherited_provenance = OverrideProvenance(
        kind=OverrideKind.INHERITED,
        action_id=ACTION_ID,
        owner_actor_id=OWNER_ACTOR_ID,
        recorded_at=RECORDED_AT,
        source_local_hash=LOCAL_HASH,
        source_anchor_before_hash=BEFORE_HASH,
        source_anchor_after_hash=AFTER_HASH,
        speaker_target_hash=speaker_target_hash(_speaker(), _casting()),
        source_script_version_id=UUID(
            "99000000-0000-4000-8000-000000000011"
        ),
        source_segment_id=UUID("99000000-0000-4000-8000-000000000012"),
        source_immutable_hash="6" * 64,
    )
    source = replace(
        source,
        attribution_origin=AttributionOrigin.INHERITED_OVERRIDE,
        provenance=inherited_provenance,
    )

    assert _decision(source=source).eligible


def test_override_inheritance_rejects_cross_novel() -> None:
    decision = _decision(target=_target(novel_id=OTHER_NOVEL_ID))
    assert not decision.eligible
    assert decision.reason is OverrideInheritanceReason.CROSS_NOVEL


def test_override_inheritance_rejects_non_approved_source() -> None:
    source = _source(script_state=ScriptVersionState.REVIEW_REQUIRED)
    decision = _decision(source=source, authority=_authority(_source()))
    assert decision.reason is OverrideInheritanceReason.SOURCE_NOT_APPROVED


def test_override_inheritance_rejects_non_manual_source() -> None:
    source = replace(
        _source(),
        attribution_origin=AttributionOrigin.LOCAL_RULE,
        manual_override=False,
        provenance=None,
    )
    decision = _decision(source=source, authority=_authority(_source()))
    assert decision.reason is OverrideInheritanceReason.SOURCE_NOT_MANUAL


def test_override_inheritance_rejects_source_provenance_mismatch() -> None:
    source = replace(_source(), provenance=_manual_provenance(local_hash=OTHER_HASH))
    decision = _decision(source=source, authority=_authority(_source()))
    assert decision.reason is OverrideInheritanceReason.SOURCE_PROVENANCE_INVALID


def test_override_inheritance_rejects_structurally_valid_but_unauthorized_source() -> None:
    authorized = _source()
    untrusted = replace(
        authorized,
        segment_id=UUID("99000000-0000-4000-8000-000000000013"),
    )
    decision = _decision(
        source=untrusted,
        authority=_authority(authorized),
    )
    assert decision.reason is OverrideInheritanceReason.SOURCE_NOT_AUTHORIZED


def test_override_inheritance_rejects_same_script_version() -> None:
    decision = _decision(
        target=_target(script_version_id=SOURCE_VERSION_ID),
    )
    assert decision.reason is OverrideInheritanceReason.SAME_SCRIPT_VERSION


def test_override_inheritance_rejects_unauthorized_audit_actor() -> None:
    decision = _decision(audit=_audit("other-owner"))
    assert decision.reason is OverrideInheritanceReason.AUDIT_ACTOR_UNAUTHORIZED


def test_override_inheritance_rejects_reused_action_id() -> None:
    decision = _decision(
        audit=InheritanceAuditStamp(
            action_id=ACTION_ID,
            owner_actor_id=OWNER_ACTOR_ID,
            recorded_at=RECORDED_AT,
        )
    )
    assert decision.reason is OverrideInheritanceReason.AUDIT_ACTION_REUSED


def test_override_inheritance_rejects_audit_time_before_source() -> None:
    decision = _decision(
        audit=InheritanceAuditStamp(
            action_id=UUID("99000000-0000-4000-8000-000000000014"),
            owner_actor_id=OWNER_ACTOR_ID,
            recorded_at=datetime(2026, 8, 26, 7, 59, tzinfo=timezone.utc),
        )
    )
    assert decision.reason is OverrideInheritanceReason.AUDIT_TIME_INVALID


def test_override_inheritance_rejects_local_hash_mismatch() -> None:
    decision = _decision(target=_target(local_hash=OTHER_HASH))
    assert decision.reason is OverrideInheritanceReason.LOCAL_HASH_MISMATCH


@pytest.mark.parametrize(
    "target",
    [
        _target(before_hash=OTHER_HASH),
        _target(after_hash=OTHER_HASH),
    ],
)
def test_override_inheritance_rejects_anchor_value_mismatch(
    target: OverrideInheritanceTarget,
) -> None:
    decision = _decision(target=target)
    assert decision.reason is OverrideInheritanceReason.ANCHOR_VALUE_MISMATCH


@pytest.mark.parametrize(
    "proof",
    [
        _uniqueness(local_count=0),
        _uniqueness(local_count=2),
        _uniqueness(before_count=0),
        _uniqueness(before_count=2),
        _uniqueness(after_count=0),
        _uniqueness(after_count=2),
        _uniqueness(combined_count=0),
        _uniqueness(combined_count=2),
        _uniqueness(at_start=True),
        _uniqueness(at_end=True),
    ],
)
def test_override_inheritance_rejects_ambiguous_or_inconsistent_anchor_proof(
    proof: AnchorUniquenessEvidence,
) -> None:
    decision = _decision(target=_target(uniqueness=proof))
    assert decision.reason is OverrideInheritanceReason.ANCHOR_NOT_UNIQUE


def test_override_inheritance_accepts_unique_document_start_boundary() -> None:
    source = _source(before_hash=None)
    target = _target(
        before_hash=None,
        uniqueness=_uniqueness(before_count=0, at_start=True),
    )
    assert _decision(source=source, target=target).eligible


def test_override_inheritance_accepts_unique_document_end_boundary() -> None:
    source = _source(after_hash=None)
    target = _target(
        after_hash=None,
        uniqueness=_uniqueness(after_count=0, at_end=True),
    )
    assert _decision(source=source, target=target).eligible


def test_override_inheritance_accepts_single_segment_document_boundary() -> None:
    source = _source(before_hash=None, after_hash=None)
    target = _target(
        before_hash=None,
        after_hash=None,
        uniqueness=_uniqueness(
            before_count=0,
            after_count=0,
            at_start=True,
            at_end=True,
        ),
    )
    assert _decision(source=source, target=target).eligible


def test_override_inheritance_rejects_missing_boundary_position_proof() -> None:
    source = _source(before_hash=None)
    target = _target(
        before_hash=None,
        uniqueness=_uniqueness(before_count=0, at_start=False),
    )
    decision = _decision(source=source, target=target)
    assert decision.reason is OverrideInheritanceReason.ANCHOR_NOT_UNIQUE


def test_override_inheritance_rejects_speaker_casting_digest_change() -> None:
    decision = _decision(target=_target(casting=_casting(OTHER_PROFILE_ID)))
    assert decision.reason is OverrideInheritanceReason.SPEAKER_TARGET_MISMATCH


def test_rejected_override_never_materializes_attribution_or_warning() -> None:
    decision = _decision(target=_target(local_hash=OTHER_HASH))
    assert decision.to_attribution() is None
    assert decision.to_script_issues(segment_id=TARGET_SEGMENT_ID) == ()


def test_override_authority_rejects_cross_novel_or_non_approved_records() -> None:
    with pytest.raises(ConfidenceRuleError, match="another novel"):
        OverrideInheritanceAuthority(
            novel_id=NOVEL_ID,
            owner_actor_id=OWNER_ACTOR_ID,
            authorized_sources=frozenset({_source(novel_id=OTHER_NOVEL_ID)}),
        )
    with pytest.raises(ConfidenceRuleError, match="approved"):
        OverrideInheritanceAuthority(
            novel_id=NOVEL_ID,
            owner_actor_id=OWNER_ACTOR_ID,
            authorized_sources=frozenset(
                {_source(script_state=ScriptVersionState.DRAFT)}
            ),
        )


def test_override_authority_rejects_source_owned_by_another_actor() -> None:
    source = _source()
    other_owner_provenance = replace(
        source.provenance,
        owner_actor_id="other-owner",
    )
    with pytest.raises(ConfidenceRuleError, match="owner"):
        OverrideInheritanceAuthority(
            novel_id=NOVEL_ID,
            owner_actor_id=OWNER_ACTOR_ID,
            authorized_sources=frozenset(
                {replace(source, provenance=other_owner_provenance)}
            ),
        )


def test_override_audit_stamp_requires_exact_utc() -> None:
    with pytest.raises(ConfidenceRuleError, match="UTC"):
        InheritanceAuditStamp(
            action_id=ACTION_ID,
            owner_actor_id=OWNER_ACTOR_ID,
            recorded_at=datetime(2026, 8, 26, 8, 0),
        )


def test_anchor_evidence_rejects_bool_and_negative_counts() -> None:
    with pytest.raises(ConfidenceRuleError):
        AnchorUniquenessEvidence(True, 1, 1, 1, False, False)
    with pytest.raises(ConfidenceRuleError):
        AnchorUniquenessEvidence(-1, 1, 1, 1, False, False)


def test_policy_versions_fail_closed() -> None:
    with pytest.raises(ConfidenceRuleError, match="policy version"):
        SpeakerConfidenceSignals(
            1,
            False,
            1,
            0,
            policy_version="future",
        )
    with pytest.raises(ExpressionRuleError, match="ruleset"):
        ExpressionContext(
            segment_kind=SegmentKind.NARRATION,
            source_text="x",
            spoken_text="x",
            ruleset_version=EXPRESSION_RULESET_VERSION + ".future",
        )
