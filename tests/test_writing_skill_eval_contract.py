import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "writing_skill_eval" / "cases.json"
EXPECTED_CATEGORIES = {
    "closed-fact-continuation",
    "scene-progression",
    "character-voice",
    "dialogue-subtext",
    "cross-chapter-continuity",
    "genre-promise",
}
EXPECTED_GENRES = {
    "年代/重生情感",
    "东方玄幻",
    "近未来悬疑",
}
EXPECTED_RUBRIC = [
    "吸引力",
    "人物可信度",
    "场景推进",
    "语言自然度",
    "类型满足度",
    "可继续修改性",
]
EXPECTED_SKILLS = {
    "novel-direction",
    "story-foundation",
    "character-craft",
    "chapter-outline",
    "scene-craft",
    "dialogue-craft",
    "prose-writing",
    "continuity-check",
    "style-review",
}


def load_suite() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_writing_eval_freezes_same_model_blind_ab_protocol() -> None:
    suite = load_suite()
    protocol = suite["comparison_protocol"]

    assert suite["schema_version"] == "1.0"
    assert suite["suite_id"] == "writing-skill-eval-0.4.0"
    assert suite["rights_basis"] == "project-synthetic"
    assert protocol["candidate_versions"] == ["0.3.0", "0.4.0"]
    assert protocol["same_model"] is True
    assert protocol["attempts_per_version"] == 2
    assert protocol["blind_order"] is True
    assert protocol["model_and_parameters_must_be_recorded"] is True
    assert suite["rubric_dimensions"] == EXPECTED_RUBRIC


def test_writing_eval_has_balanced_unique_cases_and_synthetic_rights() -> None:
    cases = load_suite()["cases"]
    ids = [case["id"] for case in cases]
    category_counts = Counter(case["category"] for case in cases)
    genre_counts = Counter(case["genre"] for case in cases)

    assert len(cases) == 12
    assert len(ids) == len(set(ids))
    assert set(category_counts) == EXPECTED_CATEGORIES
    assert set(category_counts.values()) == {2}
    assert set(genre_counts) == EXPECTED_GENRES
    assert set(genre_counts.values()) == {4}
    assert all(case["rights_basis"] == "project-synthetic" for case in cases)
    assert all("http://" not in case["source_text"] for case in cases)
    assert all("https://" not in case["source_text"] for case in cases)


def test_each_writing_eval_case_is_runnable_and_auditable() -> None:
    for case in load_suite()["cases"]:
        constraints = case["hard_constraints"]
        char_range = constraints["target_chars"]

        assert case["title"].strip()
        assert len(case["source_text"]) >= 80
        assert "只输出正文" in case["request"]
        assert set(case["primary_skills"]).issubset(EXPECTED_SKILLS)
        assert case["primary_skills"]
        assert constraints["pov"].strip()
        assert 300 <= char_range["min"] < char_range["max"] <= 1000
        assert len(constraints["required_anchors"]) >= 3
        assert len(constraints["forbidden_additions"]) >= 3
        assert len(constraints["knowledge_boundaries"]) >= 2
        assert len(constraints["required_state_changes"]) >= 1
        assert constraints["speaker_ids"]
        assert set(case["blind_review_focus"]).issubset(EXPECTED_RUBRIC)
        assert len(case["blind_review_focus"]) >= 3


def test_voice_and_subtext_cases_exercise_multiple_speakers() -> None:
    for case in load_suite()["cases"]:
        if case["category"] in {"character-voice", "dialogue-subtext"}:
            assert len(case["hard_constraints"]["speaker_ids"]) >= 2
