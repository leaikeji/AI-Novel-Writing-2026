from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from backend.narration.aliases import (
    AliasContractError,
    AliasResolutionKind,
    AliasSource,
    CharacterAliasIndex,
    CharacterAliasRecord,
    build_character_alias_index,
    normalize_character_alias,
)
from backend.narration.contracts import ConfidenceLevel, ReviewIssueSeverity
from backend.narration.scenes import (
    SceneBoundaryHint,
    SceneRuleError,
    build_scene_contracts,
    scan_scene_boundary_hints,
    scene_ids_for_source_ranges,
)
from backend.narration.script_contracts import (
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    Delivery,
    Emotion,
    SceneBoundarySource,
    SceneContract,
    SegmentContract,
    SegmentKind,
    SourceBlockKind,
    SpeakerKind,
    SpeakerRef,
    Utf16Range,
    derive_segment_id,
    derive_source_block_key,
    text_sha256,
    utf16_length,
    utf16_slice,
)
from backend.narration.speaker_rules import (
    ResolvedSpeakerLabel,
    SpeakerRuleContext,
    SpeakerRuleError,
    attribute_speaker_local,
    build_resolved_speaker_index,
)


CHARACTER_LIN = UUID("11111111-1111-4111-8111-111111111111")
CHARACTER_SHEN = UUID("22222222-2222-4222-8222-222222222222")
CHARACTER_OTHER = UUID("33333333-3333-4333-8333-333333333333")
SCRIPT_VERSION_ID = UUID("44444444-4444-4444-8444-444444444444")
ANONYMOUS_ID = UUID("55555555-5555-4555-8555-555555555555")
ANONYMOUS_ID_2 = UUID("66666666-6666-4666-8666-666666666666")
GROUP_KEY = "grp1_" + "7" * 64


def _alias_record(
    character_id: UUID,
    alias: str,
    *,
    active: bool = True,
    source: AliasSource = AliasSource.CANONICAL_NAME,
) -> CharacterAliasRecord:
    return CharacterAliasRecord(
        character_id=character_id,
        alias=alias,
        source=source,
        active=active,
    )


def _aliases(*records: CharacterAliasRecord) -> CharacterAliasIndex:
    return build_character_alias_index(
        records,
        allowed_character_ids=frozenset(
            {CHARACTER_LIN, CHARACTER_SHEN, CHARACTER_OTHER}
        ),
    )


def _standard_aliases() -> CharacterAliasIndex:
    return _aliases(
        _alias_record(CHARACTER_LIN, "林晚"),
        _alias_record(
            CHARACTER_LIN,
            "阿晚",
            source=AliasSource.AUTHOR_DEFINED,
        ),
        _alias_record(CHARACTER_SHEN, "沈川"),
    )


def _empty_resolved_index():
    return build_resolved_speaker_index((), allowed_speakers=frozenset())


def test_alias_normalization_is_nfkc_casefold_and_exact_not_fuzzy() -> None:
    assert normalize_character_alias("ＡＬＩＣＥ") == "alice"
    assert normalize_character_alias("王　小明") == "王 小明"
    assert normalize_character_alias("林晚") != normalize_character_alias("林晚晚")


def test_alias_index_deduplicates_same_character_but_reports_cross_character_conflict() -> None:
    unique = _aliases(
        _alias_record(CHARACTER_LIN, "阿晚"),
        _alias_record(
            CHARACTER_LIN,
            "阿晚",
            source=AliasSource.AUTHOR_DEFINED,
        ),
    ).resolve("阿晚")
    assert unique.kind is AliasResolutionKind.UNIQUE
    assert unique.character_id == CHARACTER_LIN

    index = _aliases(
        _alias_record(CHARACTER_LIN, "阿宁"),
        _alias_record(CHARACTER_SHEN, "阿宁"),
    )
    conflict = index.resolve("阿宁")
    assert conflict.kind is AliasResolutionKind.CONFLICT
    assert conflict.character_ids == tuple(sorted((CHARACTER_LIN, CHARACTER_SHEN), key=str))
    assert index.conflicts == (conflict,)


def test_inactive_alias_does_not_match_or_create_a_character() -> None:
    index = _aliases(_alias_record(CHARACTER_LIN, "旧名", active=False))
    assert index.resolve("旧名").kind is AliasResolutionKind.NOT_FOUND


def test_alias_index_rejects_unauthorized_character_and_noncanonical_direct_input() -> None:
    unauthorized = _alias_record(uuid4(), "越界人物")
    with pytest.raises(AliasContractError, match="outside server authority"):
        build_character_alias_index(
            (unauthorized,),
            allowed_character_ids=frozenset({CHARACTER_LIN}),
        )

    record_a = _alias_record(CHARACTER_LIN, "B")
    record_b = _alias_record(CHARACTER_LIN, "A")
    with pytest.raises(AliasContractError, match="canonical order"):
        CharacterAliasIndex(
            allowed_character_ids=frozenset({CHARACTER_LIN}),
            records=(record_a, record_b),
        )


@pytest.mark.parametrize("alias", ["", "a\nname", "\ud800"])
def test_alias_rejects_empty_control_and_unpaired_surrogate(alias: str) -> None:
    with pytest.raises(AliasContractError):
        normalize_character_alias(alias)


def test_scene_fallback_is_one_typed_chapter_wide_contract() -> None:
    source = "夜🌙。\n风起了。"
    scenes = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
    )
    assert len(scenes) == 1
    scene = scenes[0]
    assert type(scene) is SceneContract
    assert scene.boundary_source is SceneBoundarySource.DOCUMENT_START
    assert scene.source_range_utf16 == Utf16Range(0, utf16_length(source))
    assert scene.local_hash == text_sha256(source)
    assert utf16_slice(source, scene.source_range_utf16) == source


def test_scene_detector_coalesces_separator_followed_by_heading() -> None:
    source = "# 第一幕\n夜色。\n\n***\n\n## 第二幕\n天亮。"
    scenes = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
    )
    assert [scene.boundary_source for scene in scenes] == [
        SceneBoundarySource.DOCUMENT_START,
        SceneBoundarySource.SCENE_SEPARATOR,
    ]
    assert [scene.title for scene in scenes] == ["第一幕", "第二幕"]
    assert scenes[0].source_range_utf16.end_exclusive == scenes[1].source_range_utf16.start
    assert scenes[1].source_range_utf16.end_exclusive == utf16_length(source)


def test_scene_separator_aligns_forward_to_complete_source_segment_boundary() -> None:
    source = "# 第一幕\n夜色。\n\n***\n\n## 第二幕\n天亮。"
    segment_ranges = (
        Utf16Range(0, 6),
        Utf16Range(6, 16),
        Utf16Range(16, 23),
        Utf16Range(23, 26),
    )
    scenes = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        source_segment_ranges_utf16=segment_ranges,
    )
    assert [scene.source_range_utf16 for scene in scenes] == [
        Utf16Range(0, 16),
        Utf16Range(16, 26),
    ]
    assert scenes[1].boundary_source is SceneBoundarySource.SCENE_SEPARATOR
    assert scenes[1].title == "第二幕"
    assert scene_ids_for_source_ranges(
        scenes=scenes,
        source_ranges_utf16=segment_ranges,
    ) == (
        scenes[0].scene_id,
        scenes[0].scene_id,
        scenes[1].scene_id,
        scenes[1].scene_id,
    )


def test_manual_boundary_cannot_split_source_segment_and_partition_must_be_complete() -> None:
    source = "第一段。\n第二段。"
    source_length = utf16_length(source)
    with pytest.raises(SceneRuleError, match="cannot split"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            boundary_hints=(
                SceneBoundaryHint(2, SceneBoundarySource.MANUAL),
            ),
            detect_document_structure=False,
            source_segment_ranges_utf16=(Utf16Range(0, source_length),),
        )
    with pytest.raises(SceneRuleError, match="complete"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            source_segment_ranges_utf16=(Utf16Range(0, source_length - 1),),
        )


def test_scene_heading_and_explicit_paragraph_rule_are_version_scoped_and_deterministic() -> None:
    source = "第一段。\n\n第二段。"
    start = utf16_length("第一段。\n\n")
    hint = SceneBoundaryHint(
        start_utf16=start,
        boundary_source=SceneBoundarySource.PARAGRAPH_RULE,
        title="第二场",
    )
    first = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        boundary_hints=(hint,),
        detect_document_structure=False,
    )
    second = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        boundary_hints=(hint,),
        detect_document_structure=False,
    )
    assert first == second
    assert first[1].boundary_source is SceneBoundarySource.PARAGRAPH_RULE
    assert first[1].title == "第二场"
    assert first[0].scene_id != first[1].scene_id


def test_scene_manual_hint_normalizes_title_to_nfc() -> None:
    source = "A\nB"
    scenes = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        boundary_hints=(
            SceneBoundaryHint(
                start_utf16=2,
                boundary_source=SceneBoundarySource.MANUAL,
                title="e\u0301",
            ),
        ),
        detect_document_structure=False,
    )
    assert scenes[1].title == "é"


def test_scene_detector_does_not_misclassify_setext_underline_as_separator() -> None:
    source = "标题\n---\n正文"
    hints = scan_scene_boundary_hints(source)
    assert hints == ()
    assert len(
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
        )
    ) == 1


def test_trailing_separator_does_not_fabricate_an_empty_following_scene() -> None:
    source = "正文。\n\n***\n"
    scenes = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
    )
    assert len(scenes) == 1
    assert scenes[0].source_range_utf16 == Utf16Range(0, utf16_length(source))


def test_scene_boundaries_reject_conflicts_surrogate_splits_and_end_offset() -> None:
    source = "🌙A"
    with pytest.raises(SceneRuleError, match="surrogate pair"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            boundary_hints=(
                SceneBoundaryHint(1, SceneBoundarySource.MANUAL),
            ),
            detect_document_structure=False,
        )
    with pytest.raises(SceneRuleError, match="inside"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            boundary_hints=(
                SceneBoundaryHint(utf16_length(source), SceneBoundarySource.MANUAL),
            ),
            detect_document_structure=False,
        )
    with pytest.raises(SceneRuleError, match="conflicting"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            boundary_hints=(
                SceneBoundaryHint(2, SceneBoundarySource.MANUAL),
                SceneBoundaryHint(2, SceneBoundarySource.PARAGRAPH_RULE),
            ),
            detect_document_structure=False,
        )
    with pytest.raises(SceneRuleError, match="offset zero"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            boundary_hints=(
                SceneBoundaryHint(2, SceneBoundarySource.DOCUMENT_START),
            ),
            detect_document_structure=False,
        )
    with pytest.raises(SceneRuleError, match="surrogate pair"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text=source,
            source_segment_ranges_utf16=(
                Utf16Range(0, 1),
                Utf16Range(1, utf16_length(source)),
            ),
        )


def test_empty_source_has_no_fabricated_scene_or_boundary() -> None:
    assert build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text="",
    ) == ()
    with pytest.raises(SceneRuleError, match="empty"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text="",
            boundary_hints=(
                SceneBoundaryHint(0, SceneBoundarySource.MANUAL),
            ),
        )
    with pytest.raises(SceneRuleError, match="source segment ranges"):
        build_scene_contracts(
            script_version_id=SCRIPT_VERSION_ID,
            source_text="",
            source_segment_ranges_utf16=(Utf16Range(0, 1),),
        )


def test_v1_scene_rules_never_emit_cloud_assisted_boundary() -> None:
    source = "# 章\n一\n\n***\n\n二"
    scenes = build_scene_contracts(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
    )
    assert {scene.boundary_source.value for scene in scenes} <= {
        "document_start",
        "markdown_heading",
        "scene_separator",
        "paragraph_rule",
        "manual",
    }


@pytest.mark.parametrize(
    ("source", "expected_character", "expected_rule_fragment"),
    [
        ("林晚说道：“你终于来了。”", CHARACTER_LIN, "prefix"),
        ("“你终于来了。”林晚轻声说道。", CHARACTER_LIN, "suffix"),
        ("沈川皱眉。“我没有骗你。”", CHARACTER_SHEN, "action_before_dialogue"),
    ],
)
def test_explicit_local_cues_resolve_exact_character(
    source: str,
    expected_character: UUID,
    expected_rule_fragment: str,
) -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text=source,
            scene_character_ids=frozenset({CHARACTER_LIN, CHARACTER_SHEN}),
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker == SpeakerRef(
        SpeakerKind.CHARACTER,
        character_id=expected_character,
    )
    assert decision.confidence is ConfidenceLevel.HIGH
    assert decision.attribution.origin is AttributionOrigin.LOCAL_RULE
    assert decision.attribution.candidate_character_ids == (expected_character,)
    assert any(expected_rule_fragment in code for code in decision.attribution.rule_codes)
    assert decision.issue_codes == ()


def test_adjacent_cue_context_resolves_without_copying_or_changing_source_text() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="“来了。”",
            cue_before="林晚说道：",
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.character_id == CHARACTER_LIN
    assert any("context_before" in code for code in decision.attribution.rule_codes)


@pytest.mark.parametrize(
    ("source_text", "cue_before", "cue_after", "expected_character"),
    [
        ("“你终于来了。”", "林晚说道：", "", CHARACTER_LIN),
        ("“你终于来了。”", "", "林晚轻声说道。", CHARACTER_LIN),
        ("“我没有骗你。”", "沈川皱眉。", "", CHARACTER_SHEN),
    ],
)
def test_split_adjacent_cues_match_t3b_materialized_segment_shape(
    source_text: str,
    cue_before: str,
    cue_after: str,
    expected_character: UUID,
) -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text=source_text,
            cue_before=cue_before,
            cue_after=cue_after,
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.character_id == expected_character
    assert decision.issue_codes == ()


def test_alias_with_internal_space_and_bare_dao_cue_resolves_exactly() -> None:
    aliases = _aliases(_alias_record(CHARACTER_LIN, "王 小明"))
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="王 小明道：“到了。”",
        ),
        aliases=aliases,
    )
    assert decision.speaker.character_id == CHARACTER_LIN


def test_narration_title_and_pause_are_always_typed_narrator_local_rules() -> None:
    for kind in (
        SegmentKind.NARRATION,
        SegmentKind.CHAPTER_TITLE,
        SegmentKind.SYNTHETIC_PAUSE,
    ):
        decision = attribute_speaker_local(
            SpeakerRuleContext(segment_kind=kind, source_text=""),
            aliases=_standard_aliases(),
        )
        assert decision.speaker == SpeakerRef(SpeakerKind.NARRATOR)
        assert decision.confidence is ConfidenceLevel.HIGH
        assert decision.issue_codes == ()


def test_alias_conflict_is_unknown_and_blocking_even_if_scene_has_one_candidate() -> None:
    index = _aliases(
        _alias_record(CHARACTER_LIN, "阿宁"),
        _alias_record(CHARACTER_SHEN, "阿宁"),
    )
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="阿宁说道：“别猜。”",
            scene_character_ids=frozenset({CHARACTER_LIN}),
        ),
        aliases=index,
    )
    assert decision.speaker.kind is SpeakerKind.UNKNOWN
    assert decision.attribution.candidate_character_ids == tuple(
        sorted((CHARACTER_LIN, CHARACTER_SHEN), key=str)
    )
    assert {
        "B_CHARACTER_ALIAS_CONFLICT",
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_SPEAKER_UNKNOWN",
    }.issubset(decision.issue_codes)


def test_scene_singleton_and_previous_turn_are_not_guessed_without_continuation_evidence() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="“没有提示语。”",
            scene_character_ids=frozenset({CHARACTER_LIN}),
            previous_speaker=SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=CHARACTER_LIN,
            ),
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.kind is SpeakerKind.UNKNOWN
    assert decision.issue_codes == (
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_SPEAKER_UNKNOWN",
    )


def test_same_paragraph_continuation_is_medium_visible_and_auditable() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="“第二句。”",
            previous_speaker=SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=CHARACTER_LIN,
            ),
            same_paragraph_continuation=True,
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.character_id == CHARACTER_LIN
    assert decision.confidence is ConfidenceLevel.MEDIUM
    assert decision.issue_codes == ("W_SPEAKER_MEDIUM_CONFIDENCE",)
    assert decision.attribution.rule_codes == (
        "speaker.continuation.same_paragraph",
    )


def test_dialogue_cannot_use_explicit_speaker_to_bypass_cue_conflicts() -> None:
    with pytest.raises(SpeakerRuleError, match="non-dialogue forms"):
        attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.DIALOGUE,
                source_text="沈川说道：“我来了。”",
                explicit_speaker=SpeakerRef(
                    SpeakerKind.CHARACTER,
                    character_id=CHARACTER_LIN,
                ),
            ),
            aliases=_standard_aliases(),
        )


def test_narrator_is_not_carried_into_uncued_dialogue() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="“这不是旁白。”",
            previous_speaker=SpeakerRef(SpeakerKind.NARRATOR),
            same_paragraph_continuation=True,
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.kind is SpeakerKind.UNKNOWN
    assert "B_SPEAKER_UNKNOWN" in decision.issue_codes


def test_unresolved_anonymous_label_is_a_hint_not_a_fabricated_identity() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="一个年轻女人喊道：“别动！”",
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker == SpeakerRef(SpeakerKind.UNKNOWN)
    assert decision.unresolved_kind is SpeakerKind.ANONYMOUS
    assert decision.unresolved_label == "一个年轻女人"
    assert "W_NEW_ANONYMOUS_SPEAKER" in decision.issue_codes
    assert decision.attribution.candidate_character_ids == ()


def test_server_authorized_anonymous_and_group_labels_resolve_to_typed_refs() -> None:
    anonymous = SpeakerRef(
        SpeakerKind.ANONYMOUS,
        anonymous_speaker_id=ANONYMOUS_ID,
    )
    group = SpeakerRef(SpeakerKind.GROUP, group_key=GROUP_KEY)
    resolved = build_resolved_speaker_index(
        (
            ResolvedSpeakerLabel("一个年轻女人", anonymous),
            ResolvedSpeakerLabel("众人", group),
        ),
        allowed_speakers=frozenset({anonymous, group}),
    )
    anonymous_decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="一个年轻女人喊道：“别动！”",
        ),
        aliases=_standard_aliases(),
        resolved_speakers=resolved,
    )
    group_decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="众人齐声喊道：“好！”",
        ),
        aliases=_standard_aliases(),
        resolved_speakers=resolved,
    )
    assert anonymous_decision.speaker == anonymous
    assert group_decision.speaker == group
    assert anonymous_decision.issue_codes == group_decision.issue_codes == ()


def test_resolved_non_character_collision_blocks_instead_of_choosing_first() -> None:
    first = SpeakerRef(
        SpeakerKind.ANONYMOUS,
        anonymous_speaker_id=ANONYMOUS_ID,
    )
    second = SpeakerRef(
        SpeakerKind.ANONYMOUS,
        anonymous_speaker_id=ANONYMOUS_ID_2,
    )
    resolved = build_resolved_speaker_index(
        (
            ResolvedSpeakerLabel("掌柜", first),
            ResolvedSpeakerLabel("掌柜", second),
        ),
        allowed_speakers=frozenset({first, second}),
    )
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="掌柜说道：“客官请。”",
        ),
        aliases=_standard_aliases(),
        resolved_speakers=resolved,
    )
    assert decision.speaker.kind is SpeakerKind.UNKNOWN
    assert "B_ANONYMOUS_IDENTITY_CONFLICT" in decision.issue_codes


def test_multiple_different_explicit_cues_block_instead_of_using_text_order() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="林晚说道：“来。”沈川说道。",
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.kind is SpeakerKind.UNKNOWN
    assert decision.attribution.candidate_character_ids == tuple(
        sorted((CHARACTER_LIN, CHARACTER_SHEN), key=str)
    )
    assert "speaker.cue.multiple_targets" in decision.attribution.rule_codes


def test_explicit_inner_monologue_character_must_be_authorized() -> None:
    valid = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.INNER_MONOLOGUE,
            source_text="我不能回头。",
            explicit_speaker=SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=CHARACTER_LIN,
            ),
        ),
        aliases=_standard_aliases(),
    )
    assert valid.speaker.character_id == CHARACTER_LIN
    assert valid.attribution.candidate_character_ids == (CHARACTER_LIN,)

    invalid = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.INNER_MONOLOGUE,
            source_text="越界。",
            explicit_speaker=SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=uuid4(),
            ),
        ),
        aliases=_standard_aliases(),
    )
    assert invalid.speaker.kind is SpeakerKind.UNKNOWN
    assert "B_CHARACTER_REFERENCE_INVALID" in invalid.issue_codes


def test_explicit_alias_outside_scene_is_an_audited_new_entry_not_scene_guessing() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="沈川说道：“我来了。”",
            scene_character_ids=frozenset({CHARACTER_LIN}),
        ),
        aliases=_standard_aliases(),
    )
    assert decision.speaker.character_id == CHARACTER_SHEN
    assert "speaker.scene.explicit_new_entry" in decision.attribution.rule_codes


def test_scene_authority_cannot_be_widened_by_rule_context() -> None:
    with pytest.raises(SpeakerRuleError, match="outside server authority"):
        attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.DIALOGUE,
                source_text="“话。”",
                scene_character_ids=frozenset({uuid4()}),
            ),
            aliases=_standard_aliases(),
        )


def test_decision_materializes_frozen_t3a_issue_rows() -> None:
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.PHONE,
            source_text="“无人可确定。”",
        ),
        aliases=_standard_aliases(),
    )
    segment_id = uuid4()
    issues = decision.to_script_issues(segment_id=segment_id)
    assert [issue.code for issue in issues] == [
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_SPEAKER_UNKNOWN",
    ]
    assert all(type(issue.severity) is ReviewIssueSeverity for issue in issues)
    assert all(issue.severity is ReviewIssueSeverity.BLOCKER for issue in issues)
    assert all(issue.segment_id == segment_id for issue in issues)


def test_character_decision_fields_assemble_directly_into_t3a_segment_contract() -> None:
    source = "林晚说道：“来。”"
    decision = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text=source,
        ),
        aliases=_standard_aliases(),
    )
    local_hash = text_sha256(source)
    source_block_key = derive_source_block_key(
        script_version_id=SCRIPT_VERSION_ID,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        block_hash=local_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    segment_id = derive_segment_id(
        script_version_id=SCRIPT_VERSION_ID,
        ordinal=0,
        source_block_key=source_block_key,
        segment_ordinal_in_block=0,
        local_hash=local_hash,
    )
    target = CastingTargetRef(
        kind=CastingTargetKind.CHARACTER_BINDING,
        binding_id=uuid4(),
        character_id=CHARACTER_LIN,
    )
    segment = SegmentContract(
        segment_id=segment_id,
        ordinal=0,
        scene_id=None,
        segment_kind=SegmentKind.DIALOGUE,
        source_block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        segment_ordinal_in_block=0,
        source_block_key=source_block_key,
        source_block_hash=local_hash,
        source_range_utf16=Utf16Range(0, utf16_length(source)),
        source_text=source,
        spoken_text="来。",
        local_hash=local_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
        inheritance_anchor_before_hash=None,
        inheritance_anchor_after_hash=None,
        speaker=decision.speaker,
        casting=CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        ),
        confidence=decision.confidence,
        emotion=Emotion.NEUTRAL,
        emotion_confidence=ConfidenceLevel.UNKNOWN,
        delivery=Delivery.NORMAL,
        attribution=decision.attribution,
    )
    assert type(segment.speaker) is SpeakerRef
    assert type(segment.attribution) is AttributionEvidence
    assert segment.attribution.origin is AttributionOrigin.LOCAL_RULE


def test_local_rules_never_emit_cloud_attribution() -> None:
    decisions = (
        attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.NARRATION,
                source_text="旁白。",
            ),
            aliases=_standard_aliases(),
        ),
        attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=SegmentKind.DIALOGUE,
                source_text="“未知。”",
            ),
            aliases=_standard_aliases(),
        ),
    )
    assert {decision.attribution.origin for decision in decisions} == {
        AttributionOrigin.LOCAL_RULE
    }


def test_resolved_label_index_cannot_bypass_formal_character_alias_authority() -> None:
    with pytest.raises(SpeakerRuleError, match="anonymous/group"):
        ResolvedSpeakerLabel(
            "伪造人物",
            SpeakerRef(SpeakerKind.CHARACTER, character_id=CHARACTER_LIN),
        )
