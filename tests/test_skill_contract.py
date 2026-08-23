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


def test_skills_are_manual_adoption_only() -> None:
    for skill_path in SKILLS_ROOT.glob("*/SKILL.md"):
        text = skill_path.read_text(encoding="utf-8")
        assert "不得声称已经保存或修改正文" in text
        assert "novel_get_context" in text
