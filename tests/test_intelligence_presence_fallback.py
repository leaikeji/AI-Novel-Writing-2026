from backend.services import _fallback_character_presence_candidates


def test_presence_fallback_uses_only_exact_catalog_names_found_in_source() -> None:
    content = (
        "沈砚把三段声音铺在同一条时间轴上。"
        "许棠核对证据编号后关闭了直播。"
    )
    candidates = _fallback_character_presence_candidates(
        content,
        {
            "character_1": {"label": "沈砚", "character_id": "root-1"},
            "character_2": {"label": "许棠", "character_id": "root-2"},
            "character_3": {"label": "罗岑", "character_id": "root-3"},
        },
        [{"timeline_id": "timeline-1", "source_start": 0, "source_end": len(content)}],
        4,
    )

    assert [item["subject"] for item in candidates] == ["沈砚", "许棠"]
    assert all(item["predicate"] == "在本章正文中出现" for item in candidates)
    assert all(item["dimension"] == "presence" for item in candidates)
    assert all(item["source_text"] in content for item in candidates)
    assert all(item["story_sequence"] == 4 for item in candidates)


def test_presence_fallback_respects_timeline_segment_boundaries() -> None:
    content = "沈砚在段落末尾"
    candidates = _fallback_character_presence_candidates(
        content,
        {"character_1": {"label": "沈砚"}},
        [{"timeline_id": "timeline-1", "source_start": 5, "source_end": len(content)}],
        1,
    )

    assert candidates == []
