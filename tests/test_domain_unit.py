import pytest

from backend.services import (
    ValidationError,
    _clean_model_candidate,
    content_hash,
    markdown_to_text,
    visible_character_count,
)


def test_markdown_snapshots_are_separate_and_deterministic() -> None:
    markdown = "# 标题\n\n**江述**走进雨夜。\n\n[线索](https://example.com)"

    assert markdown_to_text(markdown) == "标题\n\n江述走进雨夜。\n\n线索"
    assert visible_character_count(markdown) == 11
    assert len(content_hash(markdown)) == 64


def test_content_hash_changes_with_author_text() -> None:
    assert content_hash("第一稿") != content_hash("第二稿")


def test_clean_model_candidate_removes_only_final_agent_status_capsule() -> None:
    prose = "门内传来一声轻响。\n\n⟦ 第3章正文候选｜已完成；禁区检查通过｜待作者审阅 ⟧"
    continuation = "雨声盖住了铃响。\n\n⟧ 第一章续写候选｜约2000字｜锚点：招工通知 ⟧"
    workflow_tail = (
        "沈青禾把两只旧表并排放好。\n\n"
        "⟦ 准考证与磁带｜完成：证件闭环；下一步：等作者反馈是否进入下一章或修订本稿 ⟧"
    )

    assert _clean_model_candidate(prose) == "门内传来一声轻响。"
    assert _clean_model_candidate(continuation) == "雨声盖住了铃响。"
    assert _clean_model_candidate(workflow_tail) == "沈青禾把两只旧表并排放好。"
    assert _clean_model_candidate("他在纸上写下⟧不要回头⟧。") == "他在纸上写下⟧不要回头⟧。"


def test_clean_model_candidate_rejects_embedded_agent_status_capsule() -> None:
    with pytest.raises(ValidationError, match="系统状态说明"):
        _clean_model_candidate(
            "门内传来一声轻响。\n⟦ 状态：正文候选已生成 ⟧\n他继续向前。"
        )
    with pytest.raises(ValidationError, match="系统状态说明"):
        _clean_model_candidate(
            "门内传来一声轻响。\n⟦ 下一步：等待作者反馈 ⟧\n他继续向前。"
        )


def test_clean_model_candidate_removes_attached_prose_skill_preamble() -> None:
    leaked = (
        "我需要先加载 prose-writing skill，了解本章正文生成的具体规范。"
        "沈青禾把木桌往墙根又推了一寸。"
    )

    assert _clean_model_candidate(leaked) == "沈青禾把木桌往墙根又推了一寸。"


def test_clean_model_candidate_rejects_embedded_prose_skill_work_note() -> None:
    with pytest.raises(ValidationError, match="Skill 工作语句"):
        _clean_model_candidate(
            "沈青禾走进屋里。\n我将先读取 prose-writing Skill 再继续。\n窗外开始下雨。"
        )
