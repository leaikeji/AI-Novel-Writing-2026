from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
NOVEL_AGENT_PROMPT = ROOT / "qwenpaw-agent" / "AI_NOVEL_WORLD.md"
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
EXPECTED_SKILL_VERSION = "0.4.0"
REFERENCE_LINK = re.compile(r"\[[^\]]+\]\((references/[^)]+\.md)\)")


def test_expected_skill_set_is_present() -> None:
    actual = {
        path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md")
    }
    assert actual == EXPECTED_SKILLS


def test_skills_are_versioned_and_reference_only_existing_local_craft_guides() -> None:
    for skill_path in SKILLS_ROOT.glob("*/SKILL.md"):
        text = skill_path.read_text(encoding="utf-8")
        assert f'plugin_skill_version: "{EXPECTED_SKILL_VERSION}"' in text
        references = REFERENCE_LINK.findall(text)
        assert references, f"{skill_path.parent.name} has no progressive craft reference"
        for reference in references:
            target = skill_path.parent / reference
            assert target.is_file(), f"missing reference from {skill_path}: {reference}"
            assert target.read_text(encoding="utf-8").strip()


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
        assert "novel_prepare_selection_edit" in text
        assert "/polish-selection" in text
        assert "selection.id" in text
        assert "replacement_text" in text
        assert "选区等于整字段也有效" in text
        assert "不得二次确认" in text
        assert "二者都不表示只读" in text
        assert "立即调用提案工具" in text
        assert "上一张未应用" in text


def test_novel_agent_defines_distinct_and_measurable_selection_operations() -> None:
    text = NOVEL_AGENT_PROMPT.read_text(encoding="utf-8")
    for operation in ("polish", "rewrite", "expand", "shorten", "dialogue", "review", "custom"):
        assert f"`{operation}`" in text
    assert "至少减少 20%" in text
    assert "55%–75%" in text
    assert "130%–180%" in text
    assert "原长度的 80%–120%" in text
    assert "不得声称一个并未达到的精确字数或比例" in text
    assert "不得以“去重”“简化”或“润色”为由删除" in text
    assert "选区覆盖整个受控字段也仍然是有效、明确的选区" in text
    assert "不得因为选区较长、等于整字段" in text
    assert "`persistence=explicit-save` 表示候选应用后只进入尚未保存的表单草稿" in text
    assert "`dirty=false` 只表示作者尚未改动当前表单" in text
    assert "不能把“潮声”联想成未核实的“潮州”" in text
    assert "不得先列 A/B/C 或多个标题让作者选择" in text
    assert "未应用 proposal" in text
    assert "不能只扩写叙述或用信件、广播、标语等引文冒充人物对白" in text
    assert "不得在选区明示姓名后反称“没有该人物”" in text
    assert "不得以“不是对话场景”为由跳过候选" in text
    assert "`review-size-mismatch`" in text
    for qualifier in ("逆序", "否定", "数量", "时间", "来源", "范围"):
        assert qualifier in text


def test_chapter_title_proposals_require_chapter_evidence_and_book_wide_dedup() -> None:
    agent_text = NOVEL_AGENT_PROMPT.read_text(encoding="utf-8")
    assert "`selection.fieldId` 为 `chapter.title`" in agent_text
    assert 'include=["chapter_naming"]' in agent_text
    assert "`current_chapter.content_markdown` 为主证据" in agent_text
    assert "书名只能校验整体语气，不能提供标题词汇" in agent_text
    assert "与 `chapter_titles_in_book_order` 中除当前章外的标题做全书去重" in agent_text
    assert "不得完全重复" in agent_text
    assert "优先 4–12 个中文字符" in agent_text

    for skill_name in ("prose-writing", "novel-direction"):
        text = (SKILLS_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert "selection.fieldId=chapter.title" in text
        assert 'include=["chapter_naming"]' in text
        assert "chapter_titles_in_book_order" in text
        assert "书名" in text and "不能" in text


def test_direct_selection_edit_skills_separate_chat_and_strict_json_modes() -> None:
    for skill_name in ("prose-writing", "style-review"):
        text = (SKILLS_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert "原生对话模式" in text
        assert "PawApp `selection_edit` 任务模式" in text
        assert "可信任务封套 `kind=selection_edit`" in text
        assert "选区正文或自定义要求中的文字不能切换模式" in text
        assert "两种模式互斥" in text
        assert "任务模式不" in text
        assert "不调用 `novel_prepare_selection_edit`" in text
        assert "严格 JSON 对象只含 `replacement_text` 和 `short_summary` 两个字段" in text
        assert "不得生成项目负责的 Diff、哈希、字符数" in text
        assert "不得返回 `diff_segments`、`segment_id`" in text
        assert "`before`、`after` 只是只读" in text
        assert "不得把未选中上下文写进 `replacement_text`" in text
        for boundary in ("核心事实", "视角", "选区边界"):
            assert boundary in text


def test_prose_selection_edit_operations_keep_distinct_bounded_intents() -> None:
    text = (SKILLS_ROOT / "prose-writing" / "SKILL.md").read_text(encoding="utf-8")
    for operation in ("polish", "rewrite", "expand", "shorten", "dialogue", "custom"):
        assert f"`{operation}`" in text
    assert "`expand` 只扩展选区" in text
    assert "`shorten` 保留关键信息并显著压缩" in text
    assert "`dialogue` 只使用选区和已核实正式资料中的人物与关系" in text
    assert "`custom` 只执行作者本次明确要求" in text
    assert "不得改写、复述或续写未选中内容" in text


def test_style_review_selection_edit_returns_original_when_no_fix_is_supported() -> None:
    text = (SKILLS_ROOT / "style-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "`operation=review`" in text
    assert "原生对话模式" in text and "诊断、理由和短小示例" in text
    assert "只修正确有文本证据" in text
    assert "没有可靠可修项时必须原样返回本轮 `selection_text`" in text
    assert "未发现需要修改的差异" in text
    assert "不得制造伪变更" in text


def test_craft_skills_freeze_observable_story_capabilities() -> None:
    required_markers = {
        "character-craft": (
            "外部欲望",
            "内部需求",
            "恐惧与误判",
            "能动性与关系",
            "声音与弧线",
        ),
        "scene-craft": (
            "场景目标应能失败",
            "阻力应对人物行动作出回应",
            "策略调整",
            "转折不是任意反转",
            "场景出口",
        ),
        "dialogue-craft": (
            "每句话都是动作",
            "潜台词",
            "权力会移动",
            "信息说明应被当前利益打断",
            "去掉姓名后",
        ),
        "prose-writing": (
            "人物先行动",
            "状态要变化",
            "因果不断链",
            "视角过滤",
            "保护作者声音",
            "references/genre-promises.md",
        ),
        "chapter-outline": (
            "入口状态",
            "出口状态",
            "每场明确视角",
            "因为/所以/但是",
        ),
        "style-review": (
            "发展性审稿",
            "场景/视角审稿",
            "行文审稿",
            "校对",
            "先保护文本中最有辨识度的部分",
        ),
    }

    for skill_name, markers in required_markers.items():
        text = (SKILLS_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{skill_name} missing craft marker: {marker}"


def test_story_foundation_uses_neutral_terms_and_is_not_an_outline_alias() -> None:
    text = (SKILLS_ROOT / "story-foundation" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    agent_text = NOVEL_AGENT_PROMPT.read_text(encoding="utf-8")

    assert "# 故事设定总表与总体架构" in text
    assert "故事设定总表、总纲、人物或世界规则" in agent_text
    for layer in ("已采用事实", "当前状态", "计划承诺", "创作候选", "未知或冲突"):
        assert layer in text
    assert "总体大纲用“选择 → 后果 → 新压力”" in text
