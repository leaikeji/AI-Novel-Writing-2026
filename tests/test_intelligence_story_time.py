from backend.services import _normalize_story_time_value, _story_time_invents_calendar_year


def test_story_time_string_is_wrapped_in_the_versioned_contract() -> None:
    assert _normalize_story_time_value("午夜零点") == {
        "schema_version": "story-time/1",
        "label": "午夜零点",
        "precision": "unknown",
    }


def test_story_time_mapping_gets_safe_contract_defaults() -> None:
    assert _normalize_story_time_value({"label": "1992 年夏", "precision": "approximate"}) == {
        "schema_version": "story-time/1",
        "label": "1992 年夏",
        "precision": "approximate",
    }


def test_story_time_commit_guard_rejects_an_unsupported_year() -> None:
    assert _story_time_invents_calendar_year(
        "零点零分，旧广播电台的频率忽然亮了一下。",
        {
            "object": "2000-01-01T00:00:00",
            "details": {"to_time": "2000-01-01T00:00:00"},
        },
    )
    assert not _story_time_invents_calendar_year(
        "1992 年夏，旧广播电台仍在播音。",
        {
            "object": "1992 年夏",
            "details": {"to_time": {"label": "1992 年夏"}},
        },
    )
