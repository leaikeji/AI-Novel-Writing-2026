from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from backend.private_library.lexicon_contracts import LexiconEntry, LexiconPack
from backend.private_library.lexicon_matcher import (
    LexiconRuleSource,
    extract_markdown_visible_text,
    match_lexicon,
)
from backend.private_library.lexicon_renderer import render_lexicon_pack


ASSET_A = UUID("10000000-0000-0000-0000-000000000001")
ASSET_B = UUID("10000000-0000-0000-0000-000000000002")
VERSION_A = UUID("20000000-0000-0000-0000-000000000001")
VERSION_B = UUID("20000000-0000-0000-0000-000000000002")


def _entry(
    entry_id: str,
    term: str,
    action: str = "forbid",
    **updates: object,
) -> LexiconEntry:
    return LexiconEntry.model_validate({
        "entry_id": entry_id,
        "term": term,
        "action": action,
        **updates,
    })


def _rule(
    entry: LexiconEntry,
    *,
    asset_id: UUID = ASSET_A,
    version_id: UUID = VERSION_A,
    priority: int = 0,
) -> LexiconRuleSource:
    return LexiconRuleSource(
        asset_id=asset_id,
        asset_version_id=version_id,
        entry=entry,
        priority=priority,
    )


def _slice_utf16(source: str, start: int, end: int) -> str:
    payload = source.encode("utf-16-le")
    return payload[start * 2:end * 2].decode("utf-16-le")


def test_renderer_is_deterministic_versioned_and_hashes_exact_content() -> None:
    pack = LexiconPack(entries=[
        _entry(
            "entry_0001",
            "眼底闪过",
            "watch",
            variants=["眸光微动"],
            categories=["表情"],
            note="避免人物反应同质化",
        ),
        _entry("entry_0002", "basically", match_mode="ascii_word"),
    ])

    first = render_lexicon_pack(pack)
    second = render_lexicon_pack(pack.model_copy(deep=True))

    assert first == second
    assert first.entry_count == 2
    assert first.renderer_version == "lexicon-renderer/1"
    assert first.content_sha256 == hashlib.sha256(first.content.encode()).hexdigest()
    assert "## 慎用" in first.content
    assert "连续 1000 个可见字符内至少 3 次" in first.content
    assert "## 禁用" in first.content


def test_renderer_escapes_markdown_and_handles_an_empty_pack() -> None:
    rendered = render_lexicon_pack(LexiconPack(entries=[
        _entry("entry_0001", "**不是标题**", note="[说明](地址)"),
    ]))
    assert r"\*\*不是标题\*\*" in rendered.content
    assert r"\[说明\]\(地址\)" in rendered.content
    assert render_lexicon_pack(LexiconPack()).content == "# 用词包\n\n暂无词项。\n"


def test_visible_text_removes_markers_and_destinations_but_keeps_labels_and_code() -> None:
    source = (
        "# 标题\n\n**眼底**闪过 [纸条](https://example.test/眼底闪过) 🙂\n"
        "> 对白里的`**星号**`和正文。\n"
        "裸地址 https://example.test/正文 不参与扫描。"
    )
    visible = extract_markdown_visible_text(source)

    assert visible.text == (
        "标题\n\n眼底闪过 纸条 🙂\n"
        "对白里的**星号**和正文。\n"
        "裸地址  不参与扫描。"
    )
    assert len(visible.source_utf16_offsets) == (
        len(visible.text.encode("utf-16-le")) // 2 + 1
    )
    assert tuple(sorted(visible.source_utf16_offsets)) == visible.source_utf16_offsets


def test_visible_text_decodes_entities_and_maps_emoji_utf16_boundaries() -> None:
    source = "前🙂**后** &amp; 尾"
    visible = extract_markdown_visible_text(source)
    assert visible.text == "前🙂后 & 尾"
    assert len(visible.source_utf16_offsets) == 9
    emoji_start = len("前".encode("utf-16-le")) // 2
    assert visible.source_utf16_offsets[1:3] == (emoji_start, emoji_start + 1)


def test_reference_link_keeps_label_but_hides_definition_and_destination() -> None:
    visible = extract_markdown_visible_text(
        "线索见[旧纸条][archive]。\n\n[archive]: https://example.test/禁词"
    )
    assert visible.text == "线索见旧纸条。\n\n"


def test_chinese_phrase_and_explicit_variant_match_with_source_utf16_ranges() -> None:
    source = "🙂他**眼底**闪过犹疑，随后眸光微动。"
    rule = _rule(_entry(
        "entry_0001",
        "眼底闪过",
        variants=["眸光微动"],
        note="作者不希望反复出现",
    ))

    report = match_lexicon(source, [rule])

    assert report.status == "complete"
    assert [hit.matched_text for hit in report.hits] == ["眼底闪过", "眸光微动"]
    assert report.hits[0].start_utf16 == 5
    assert _slice_utf16(
        source, report.hits[0].start_utf16, report.hits[0].end_utf16
    ) == "眼底**闪过"
    assert all(hit.count == 2 for hit in report.hits)
    assert report.hits[0].hit_id == match_lexicon(source, [rule]).hits[0].hit_id


def test_ascii_word_honors_complete_word_boundaries_and_case_policy() -> None:
    insensitive = _rule(_entry(
        "entry_0001",
        "Basically",
        match_mode="ascii_word",
        case_sensitive=False,
    ))
    sensitive = _rule(
        _entry(
            "entry_0002",
            "AI",
            match_mode="ascii_word",
            case_sensitive=True,
        ),
        asset_id=ASSET_B,
        version_id=VERSION_B,
    )
    source = "basically BASICALLY basically_2 xbasically AI ai AIs"

    report = match_lexicon(source, [insensitive, sensitive])

    assert [hit.matched_text for hit in report.hits] == ["basically", "BASICALLY", "AI"]


def test_overlapping_rules_are_preserved_and_sorted_by_exact_source_range() -> None:
    short = _rule(_entry("entry_0001", "眼底"), priority=1)
    long = _rule(
        _entry("entry_0002", "眼底闪过"),
        asset_id=ASSET_B,
        version_id=VERSION_B,
    )

    report = match_lexicon("眼底闪过", [long, short])

    assert [(hit.entry_id, hit.start_utf16, hit.end_utf16) for hit in report.hits] == [
        ("entry_0001", 0, 2),
        ("entry_0002", 0, 4),
    ]
    assert len({hit.hit_id for hit in report.hits}) == 2


def test_watch_rule_reports_only_occurrences_that_reach_rolling_density() -> None:
    watch = _rule(_entry(
        "entry_0001",
        "仿佛",
        "watch",
        watch_threshold={"count": 3, "window_characters": 100},
    ))
    sparse = "仿佛" + "字" * 100 + "仿佛" + "字" * 100 + "仿佛"
    dense = "仿佛，他停下。仿佛，雨更急。仿佛，门开了。"

    assert match_lexicon(sparse, [watch]).hits == ()
    report = match_lexicon(dense, [watch])
    assert len(report.hits) == 3
    assert {hit.count for hit in report.hits} == {3}
    assert {hit.window for hit in report.hits} == {100}
    assert all("全文3次" in hit.reason for hit in report.hits)


def test_recommend_and_inactive_rules_never_create_check_hits() -> None:
    rules = [
        _rule(_entry("entry_0001", "雨", "recommend")),
        _rule(
            _entry("entry_0002", "风", state="inactive"),
            asset_id=ASSET_B,
            version_id=VERSION_B,
        ),
    ]
    report = match_lexicon("风雨", rules)
    assert report.hits == ()
    assert report.scanned_rule_count == 2
    assert report.status == "complete"


def test_rule_and_hit_budgets_fail_closed_with_deterministic_results() -> None:
    rules = [
        _rule(_entry("entry_0002", "乙"), asset_id=ASSET_B, version_id=VERSION_B),
        _rule(_entry("entry_0001", "甲"), priority=2),
    ]
    first = match_lexicon("甲甲甲乙", rules, max_rules=1, max_hits=2)
    second = match_lexicon("甲甲甲乙", list(reversed(rules)), max_rules=1, max_hits=2)

    assert first == second
    assert first.status == "incomplete"
    assert first.scanned_rule_count == 1
    assert first.omitted_rule_count == 1
    assert [hit.matched_text for hit in first.hits] == ["甲", "甲"]
    assert first.visible_character_count == 4


def test_zero_budgets_are_explicitly_incomplete_without_work() -> None:
    rule = _rule(_entry("entry_0001", "甲"))
    no_rules = match_lexicon("甲", [rule], max_rules=0)
    no_hits = match_lexicon("甲", [rule], max_hits=0)
    assert (no_rules.status, no_rules.scanned_rule_count, no_rules.omitted_rule_count) == (
        "incomplete", 0, 1,
    )
    assert no_hits.status == "incomplete"
    assert no_hits.hits == ()

    with pytest.raises(ValueError, match="max_rules"):
        match_lexicon("甲", [rule], max_rules=1_001)
    with pytest.raises(ValueError, match="max_hits"):
        match_lexicon("甲", [rule], max_hits=2_001)


def test_variant_overlap_within_one_entry_deduplicates_the_same_span() -> None:
    rule = _rule(_entry(
        "entry_0001",
        "AI",
        variants=["ai"],
        match_mode="ascii_word",
        case_sensitive=False,
    ))
    report = match_lexicon("AI", [rule])
    assert len(report.hits) == 1
    assert report.hits[0].matched_text == "AI"
