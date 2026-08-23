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

    assert _clean_model_candidate(prose) == "门内传来一声轻响。"
    assert _clean_model_candidate("他在纸上写下⟧不要回头⟧。") == "他在纸上写下⟧不要回头⟧。"


def test_clean_model_candidate_rejects_embedded_agent_status_capsule() -> None:
    with pytest.raises(ValidationError, match="系统状态说明"):
        _clean_model_candidate(
            "门内传来一声轻响。\n⟦ 状态：正文候选已生成 ⟧\n他继续向前。"
        )
