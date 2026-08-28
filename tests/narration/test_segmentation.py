from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from backend.narration.script_contracts import (
    SegmentKind,
    SourceBlockKind,
    Utf16Range,
    derive_segment_id,
    derive_source_block_key,
    text_sha256,
    utf16_slice,
)
from backend.narration.segmentation import (
    SegmentationError,
    SourceFormat,
    segment_source,
    spoken_text_for_source,
    validate_segmentation_result,
)
from backend.narration.source_mapping import (
    SourceIndexMap,
    SourceMappingError,
    validate_complete_utf16_partition,
)


SCRIPT_VERSION_ID = UUID("11111111-1111-4111-8111-111111111111")


def _segment(source: str, source_format: SourceFormat = SourceFormat.MARKDOWN):
    return segment_source(
        script_version_id=SCRIPT_VERSION_ID,
        source_text=source,
        source_format=source_format,
    )


def test_source_index_map_round_trips_utf16_emoji_and_combining_text() -> None:
    source = "A🌙e\u0301。"
    index = SourceIndexMap(source)

    assert index.python_length == 5
    assert index.utf16_length == 6
    assert [index.to_utf16_offset(value) for value in range(6)] == [0, 1, 3, 4, 5, 6]
    assert [index.to_python_index(value) for value in (0, 1, 3, 4, 5, 6)] == [
        0,
        1,
        2,
        3,
        4,
        5,
    ]
    source_range = index.to_utf16_range(1, 4)
    assert source_range == Utf16Range(1, 5)
    assert index.to_python_range(source_range) == (1, 4)
    assert index.slice(source_range) == "🌙e\u0301"


def test_source_index_map_rejects_surrogate_split_bool_and_unpaired_surrogate() -> None:
    index = SourceIndexMap("🌙")

    with pytest.raises(SourceMappingError, match="surrogate pair"):
        index.to_python_index(1)
    with pytest.raises(SourceMappingError, match="python_index"):
        index.to_utf16_offset(True)  # type: ignore[arg-type]
    with pytest.raises(SourceMappingError, match="non-empty"):
        index.to_utf16_range(0, 0)
    with pytest.raises(ValueError, match="surrogate"):
        SourceIndexMap("\ud800")


def test_complete_partition_accepts_empty_and_rejects_gap_overlap_and_tail() -> None:
    validate_complete_utf16_partition("", [])
    validate_complete_utf16_partition("A🌙B", [Utf16Range(0, 1), Utf16Range(1, 3), Utf16Range(3, 4)])

    with pytest.raises(SourceMappingError, match="partition"):
        validate_complete_utf16_partition("ABC", [Utf16Range(0, 1), Utf16Range(2, 3)])
    with pytest.raises(SourceMappingError, match="partition"):
        validate_complete_utf16_partition("ABC", [Utf16Range(0, 2), Utf16Range(1, 3)])
    with pytest.raises(SourceMappingError, match="partition"):
        validate_complete_utf16_partition("ABC", [Utf16Range(0, 2)])


def test_empty_source_has_vacuous_complete_materialization() -> None:
    result = _segment("")

    assert result.blocks == ()
    assert result.segments == ()
    assert result.source_length_utf16 == 0
    assert result.source_content_hash == text_sha256("")


def test_plain_text_paragraphs_cover_crlf_and_emoji_exactly() -> None:
    source = "A🌙。\r\n\r\nB。"
    result = _segment(source, SourceFormat.PLAIN_TEXT)

    assert [block.block_kind for block in result.blocks] == [
        SourceBlockKind.PARAGRAPH,
        SourceBlockKind.PARAGRAPH,
    ]
    assert [segment.source_text for segment in result.segments] == [
        "A🌙。\r\n\r\n",
        "B。",
    ]
    assert [segment.source_range_utf16 for segment in result.segments] == [
        Utf16Range(0, 8),
        Utf16Range(8, 10),
    ]
    assert "".join(segment.source_text for segment in result.segments) == source


def test_markdown_heading_and_paragraph_materialize_distinct_block_kinds() -> None:
    source = "\n# 第一章 🌙 #\n\n夜色。"
    result = _segment(source)

    assert [block.block_kind for block in result.blocks] == [
        SourceBlockKind.HEADING,
        SourceBlockKind.PARAGRAPH,
    ]
    assert result.segments[0].segment_kind is SegmentKind.NARRATION
    assert result.segments[0].spoken_text == "第一章 🌙"
    assert result.blocks[0].source_text == "\n# 第一章 🌙 #\n\n"
    assert "".join(block.source_text for block in result.blocks) == source


def test_setext_heading_is_one_source_block_without_fabricated_title_segment() -> None:
    result = _segment("章节名\n===\n正文。")

    assert [block.block_kind for block in result.blocks] == [
        SourceBlockKind.HEADING,
        SourceBlockKind.PARAGRAPH,
    ]
    assert result.segments[0].segment_kind is SegmentKind.NARRATION
    assert result.segments[0].spoken_text == "章节名"


def test_fenced_markdown_stays_one_source_block_and_strips_fence_lines() -> None:
    source = "```text\nhello.world\n```\n\n后文。"
    result = _segment(source)

    assert result.blocks[0].block_kind is SourceBlockKind.PARAGRAPH
    assert result.blocks[0].source_text == "```text\nhello.world\n```\n\n"
    assert result.blocks[0].segments[0].spoken_text == "hello.world"


def test_source_block_key_hash_anchors_and_segment_ids_use_frozen_derivation() -> None:
    result = _segment("甲。\n\n乙。")
    first, second = result.blocks

    assert first.source_block_hash == text_sha256("甲。\n\n")
    assert second.source_block_hash == text_sha256("乙。")
    assert first.anchor_before_hash is None
    assert first.anchor_after_hash == second.source_block_hash
    assert second.anchor_before_hash == first.source_block_hash
    assert second.anchor_after_hash is None
    assert first.source_block_key == derive_source_block_key(
        script_version_id=SCRIPT_VERSION_ID,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        block_hash=first.source_block_hash,
        anchor_before_hash=None,
        anchor_after_hash=second.source_block_hash,
    )
    segment = result.segments[0]
    assert segment.segment_id == derive_segment_id(
        script_version_id=SCRIPT_VERSION_ID,
        ordinal=0,
        source_block_key=first.source_block_key,
        segment_ordinal_in_block=0,
        local_hash=segment.local_hash,
    )


def test_segmentation_is_deterministic_and_ids_are_version_scoped() -> None:
    source = "林晚说道：“你终于来了。”"
    first = _segment(source)
    repeated = _segment(source)
    other_version = segment_source(
        script_version_id=uuid4(),
        source_text=source,
        source_format=SourceFormat.MARKDOWN,
    )

    assert first == repeated
    assert [item.segment_id for item in first.segments] != [
        item.segment_id for item in other_version.segments
    ]
    assert [item.source_block_key for item in first.blocks] != [
        item.source_block_key for item in other_version.blocks
    ]


def test_forward_dialogue_prompt_is_split_without_speaker_inference() -> None:
    result = _segment("林晚说道：“你终于来了。”")

    assert [(item.segment_kind, item.source_text) for item in result.segments] == [
        (SegmentKind.NARRATION, "林晚说道："),
        (SegmentKind.DIALOGUE, "“你终于来了。”"),
    ]


def test_postposed_dialogue_prompt_is_split_in_source_order() -> None:
    result = _segment("“你终于来了。”林晚轻声说道。")

    assert [(item.segment_kind, item.source_text) for item in result.segments] == [
        (SegmentKind.DIALOGUE, "“你终于来了。”"),
        (SegmentKind.NARRATION, "林晚轻声说道。"),
    ]


def test_nested_chinese_quotes_remain_one_display_dialogue_segment() -> None:
    source = "「她说：『不。别走！』我听见了。」"
    result = _segment(source)

    assert len(result.segments) == 1
    assert result.segments[0].segment_kind is SegmentKind.DIALOGUE
    assert result.segments[0].source_text == source


def test_balanced_english_quotes_are_dialogue_but_unbalanced_quote_is_narration() -> None:
    balanced = _segment('He said: "Stay. Please!" Then left.')
    unbalanced = _segment('He said: "Stay.')

    assert [item.segment_kind for item in balanced.segments] == [
        SegmentKind.NARRATION,
        SegmentKind.DIALOGUE,
        SegmentKind.NARRATION,
    ]
    assert all(item.segment_kind is SegmentKind.NARRATION for item in unbalanced.segments)


def test_inner_monologue_cue_classifies_only_the_quoted_unit() -> None:
    result = _segment("沈川心想：“不能回头。”他加快脚步。")

    assert [item.segment_kind for item in result.segments] == [
        SegmentKind.NARRATION,
        SegmentKind.INNER_MONOLOGUE,
        SegmentKind.NARRATION,
    ]


def test_explicit_inner_monologue_block_classifies_all_spoken_units() -> None:
    result = _segment("【内心】：我不能回头。可为什么？")

    assert [item.segment_kind for item in result.segments] == [
        SegmentKind.INNER_MONOLOGUE,
        SegmentKind.INNER_MONOLOGUE,
    ]
    assert result.segments[0].spoken_text == "我不能回头。"


@pytest.mark.parametrize(
    ("source", "block_kind", "segment_kind", "spoken"),
    [
        ("【短信】：别迟到。", SourceBlockKind.MESSAGE, SegmentKind.MESSAGE, "别迟到。"),
        ("【信件】：展信佳。", SourceBlockKind.LETTER, SegmentKind.LETTER, "展信佳。"),
        ("【广播】：请注意。", SourceBlockKind.BROADCAST, SegmentKind.BROADCAST, "请注意。"),
        ("【电话】：喂？", SourceBlockKind.PHONE, SegmentKind.PHONE, "喂？"),
    ],
)
def test_explicit_semantic_blocks_materialize_frozen_kinds(
    source: str,
    block_kind: SourceBlockKind,
    segment_kind: SegmentKind,
    spoken: str,
) -> None:
    result = _segment(source)

    assert result.blocks[0].block_kind is block_kind
    assert result.segments[0].segment_kind is segment_kind
    assert result.segments[0].spoken_text == spoken


def test_markdown_spoken_text_removes_markup_url_html_and_newlines_only() -> None:
    source = "> **你好** [月亮](https://example.com/a.b)\n> <em>世界</em>。"
    result = _segment(source)

    assert "".join(item.source_text for item in result.segments) == source
    assert " ".join(item.spoken_text for item in result.segments) == "你好 月亮 世界。"
    assert "https" not in " ".join(item.spoken_text for item in result.segments)


def test_plain_text_preserves_markdown_characters_but_collapses_newline() -> None:
    source = "**原样**\n下一行"

    assert spoken_text_for_source(source, SourceFormat.PLAIN_TEXT) == "**原样** 下一行"
    assert spoken_text_for_source(source, SourceFormat.MARKDOWN) == "原样 下一行"


def test_no_read_region_is_suppressed_without_source_coverage_gap() -> None:
    source = "前文。\n\n<!-- tts:skip -->秘密。<!-- /tts:skip -->\n\n后文。"
    result = _segment(source)

    assert "".join(item.source_text for item in result.segments) == source
    spoken = " ".join(item.spoken_text for item in result.segments)
    assert spoken == "前文。 后文。"
    assert "秘密" not in spoken
    assert len(result.blocks) == 2


def test_no_read_region_crossing_blank_lines_is_never_split_or_spoken() -> None:
    source = (
        "前文。<!-- tts:skip -->秘密一。\n\n"
        "# 秘密二\n\n秘密三。<!-- /tts:skip -->后文。"
    )
    result = _segment(source)

    assert "".join(item.source_text for item in result.segments) == source
    spoken = " ".join(item.spoken_text for item in result.segments)
    assert spoken == "前文。 后文。"
    assert "秘密" not in spoken


def test_multiline_html_comment_is_hidden_without_breaking_partition() -> None:
    source = "前文。<!-- 注释。\n\n# 仍是注释\n-->后文。"
    result = _segment(source)

    assert "".join(item.source_text for item in result.segments) == source
    assert " ".join(item.spoken_text for item in result.segments) == "前文。 后文。"


@pytest.mark.parametrize(
    "source",
    [
        "前文。<noread>秘密。</noread>后文。",
        "前文。[不朗读]秘密。[/不朗读]后文。",
    ],
)
def test_supported_no_read_marker_forms_are_source_preserving(source: str) -> None:
    result = _segment(source)

    assert "".join(item.source_text for item in result.segments) == source
    assert "秘密" not in " ".join(item.spoken_text for item in result.segments)


@pytest.mark.parametrize(
    "source",
    [
        "<!-- tts:skip -->未闭合",
        "<!-- /tts:skip -->",
        "<noread>A[不朗读]B[/不朗读]</noread>",
        "<noread>A<!-- tts:skip -->B</noread><!-- /tts:skip -->",
    ],
)
def test_unbalanced_nested_or_crossed_no_read_markers_fail_closed(source: str) -> None:
    with pytest.raises(SegmentationError, match="no-read marker"):
        _segment(source)


def test_unclosed_markdown_html_comment_fails_closed() -> None:
    with pytest.raises(SegmentationError, match="unclosed Markdown HTML comment"):
        _segment("前文。<!-- 未闭合注释")


def test_sentence_boundaries_keep_decimal_and_split_terminal_punctuation() -> None:
    result = _segment("价格是 3.14 元。真的吗？是！")

    assert [item.source_text for item in result.segments] == [
        "价格是 3.14 元。",
        "真的吗？",
        "是！",
    ]


def test_markdown_link_and_emphasis_markup_stay_attached_to_sentence() -> None:
    source = "**Hello.** [Moon.](https://example.com/a.b) Next."
    result = _segment(source)

    assert [item.source_text for item in result.segments] == [
        "**Hello.** ",
        "[Moon.](https://example.com/a.b) ",
        "Next.",
    ]
    assert [item.spoken_text for item in result.segments] == [
        "Hello.",
        "Moon.",
        "Next.",
    ]


def test_combining_tail_is_not_cut_from_preceding_visible_grapheme() -> None:
    source = "好。\u0301再见。"
    result = _segment(source)

    assert [item.source_text for item in result.segments] == ["好。\u0301", "再见。"]
    assert "".join(item.source_text for item in result.segments) == source


def test_spoken_text_normalizes_to_nfc_without_changing_source_slice() -> None:
    source = "Cafe\u0301。"
    result = _segment(source)

    assert result.segments[0].source_text == source
    assert result.segments[0].spoken_text == "Café。"
    assert result.segments[0].local_hash == text_sha256(source)


def test_markdown_structural_only_source_is_rejected_but_plain_text_is_speakable() -> None:
    with pytest.raises(SegmentationError, match="no speakable text"):
        _segment("---\n\n<!-- comment -->")

    plain = _segment("---", SourceFormat.PLAIN_TEXT)
    assert plain.segments[0].spoken_text == "---"


def test_whitespace_only_nonempty_source_is_rejected() -> None:
    with pytest.raises(SegmentationError, match="no speakable text"):
        _segment(" \r\n\t")


def test_source_format_and_uuid_inputs_are_exact_and_fail_closed() -> None:
    with pytest.raises(SegmentationError, match="source_format"):
        segment_source(
            script_version_id=SCRIPT_VERSION_ID,
            source_text="A",
            source_format="markdown",  # type: ignore[arg-type]
        )
    with pytest.raises(SegmentationError, match="script_version_id"):
        segment_source(
            script_version_id="11111111-1111-4111-8111-111111111111",  # type: ignore[arg-type]
            source_text="A",
            source_format=SourceFormat.MARKDOWN,
        )


def test_validator_rejects_source_hash_block_anchor_and_segment_id_tampering() -> None:
    source = "甲。\n\n乙。"
    result = _segment(source)

    with pytest.raises(SegmentationError, match="source_content_hash"):
        validate_segmentation_result(
            source,
            replace(result, source_content_hash="0" * 64),
        )

    bad_spoken = replace(result.segments[0], spoken_text="被篡改。")
    bad_spoken_block = replace(
        result.blocks[0],
        segments=(bad_spoken, *result.blocks[0].segments[1:]),
    )
    with pytest.raises(SegmentationError, match="spoken_text"):
        validate_segmentation_result(
            source,
            replace(
                result,
                blocks=(bad_spoken_block, *result.blocks[1:]),
                segments=(bad_spoken, *result.segments[1:]),
            ),
        )

    first = result.blocks[0]
    bad_anchor = replace(first, anchor_after_hash=None)
    with pytest.raises(SegmentationError, match="neighbor anchors"):
        validate_segmentation_result(
            source,
            replace(result, blocks=(bad_anchor, *result.blocks[1:])),
        )

    first_segment = result.segments[0]
    bad_segment = replace(first_segment, segment_id=uuid4())
    bad_first_block = replace(
        first,
        segments=(bad_segment, *first.segments[1:]),
    )
    with pytest.raises(SegmentationError, match="segment_id"):
        validate_segmentation_result(
            source,
            replace(
                result,
                blocks=(bad_first_block, *result.blocks[1:]),
                segments=(bad_segment, *result.segments[1:]),
            ),
        )


def test_validator_rejects_partial_segment_partition_and_source_slice_drift() -> None:
    source = "甲。乙。"
    result = _segment(source)
    first, second = result.segments
    shifted_second = replace(
        second,
        source_range_utf16=Utf16Range(
            second.source_range_utf16.start + 1,
            second.source_range_utf16.end_exclusive,
        ),
    )
    shifted_block = replace(result.blocks[0], segments=(first, shifted_second))

    with pytest.raises((SegmentationError, SourceMappingError), match="partition"):
        validate_segmentation_result(
            source,
            replace(
                result,
                blocks=(shifted_block,),
                segments=(first, shifted_second),
            ),
        )

    assert all(
        utf16_slice(source, item.source_range_utf16) == item.source_text
        for item in result.segments
    )


def test_materialized_segments_only_use_frozen_source_bound_kinds() -> None:
    source = (
        "旁白。\n\n“对话。”\n\n【内心】想法。\n\n"
        "【短信】消息。\n\n【信件】信。\n\n"
        "【广播】播报。\n\n【电话】通话。"
    )
    result = _segment(source)

    assert {item.segment_kind for item in result.segments} == {
        SegmentKind.NARRATION,
        SegmentKind.DIALOGUE,
        SegmentKind.INNER_MONOLOGUE,
        SegmentKind.MESSAGE,
        SegmentKind.LETTER,
        SegmentKind.BROADCAST,
        SegmentKind.PHONE,
    }
    assert all(item.source_range_utf16 is not None for item in result.segments)
    assert all(item.source_block_kind is not SourceBlockKind.SYNTHETIC for item in result.segments)
