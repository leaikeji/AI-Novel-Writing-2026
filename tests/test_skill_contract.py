from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
EXPECTED_SKILLS = {
    "novel-direction",
    "story-bible",
    "chapter-outline",
    "prose-writing",
    "continuity-check",
    "style-review",
}


def test_expected_skill_set_is_present() -> None:
    actual = {
        path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md")
    }
    assert actual == EXPECTED_SKILLS


def test_skills_allow_controlled_candidates_but_not_authoritative_model_writes() -> None:
    for skill_path in SKILLS_ROOT.glob("*/SKILL.md"):
        text = skill_path.read_text(encoding="utf-8")
        assert "PawApp" in text
        assert any(
            marker in text
            for marker in ("不得声称", "不得自行声称", "不把建议或候选冒充")
        )
        assert "权威" in text or "正式故事事实" in text
        assert "novel_get_context" in text
