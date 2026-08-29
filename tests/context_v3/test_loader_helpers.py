from __future__ import annotations

from types import SimpleNamespace

from backend.context_v3_loader import _merge_story_times


def _segment(**story_time: object) -> SimpleNamespace:
    return SimpleNamespace(story_time_json=story_time)


def test_merge_story_times_keeps_one_mapping_and_combines_comparable_ranges() -> None:
    single = _merge_story_times(
        [
            _segment(
                schema_version="story-time/1",
                label="2017",
                calendar_id="gregorian",
                lower_bound=2017,
                upper_bound=2017,
                precision="exact",
            )
        ]
    )
    assert single is not None
    assert single.label == "2017"
    assert single.precision == "exact"

    combined = _merge_story_times(
        [
            _segment(label="2017", calendar_id="gregorian", lower_bound=2017, upper_bound=2017, precision="exact"),
            _segment(label="2018", calendar_id="gregorian", lower_bound=2018, upper_bound=2018, precision="exact"),
        ]
    )
    assert combined is not None
    assert (combined.lower_bound, combined.upper_bound, combined.precision) == (2017, 2018, "range")


def test_merge_story_times_does_not_guess_across_unbounded_or_different_calendars() -> None:
    assert _merge_story_times(
        [
            _segment(label="春季", calendar_id="gregorian", precision="unknown"),
            _segment(label="夏季", calendar_id="gregorian", precision="unknown"),
        ]
    ) is None
    assert _merge_story_times(
        [
            _segment(calendar_id="gregorian", lower_bound=2017, upper_bound=2017, precision="exact"),
            _segment(calendar_id="fictional", lower_bound=9, upper_bound=9, precision="exact"),
        ]
    ) is None
