from __future__ import annotations

from types import SimpleNamespace

from backend.services import _candidate_length_validation_message


def test_candidate_length_error_uses_frozen_job_window_instead_of_legacy_range() -> None:
    job = SimpleNamespace(
        generation_context_snapshot={
            "acceptance": {
                "requested_visible_character_count": 2000,
                "minimum_visible_character_count": 1700,
                "maximum_visible_character_count": 2300,
            }
        },
        target_visible_character_count=1700,
        output_visible_character_count=1462,
    )

    assert _candidate_length_validation_message(job) == (
        "正文候选未通过1700—2300字验收范围（目标2000字，实际1462字），不能采用"
    )
