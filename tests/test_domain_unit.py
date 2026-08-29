import pytest
from uuid import uuid4

from backend.creative_services import (
    _canonical_relationship_endpoints,
    _normalize_relationship_label,
    _relationship_character_key,
    _relationship_pair_key,
)
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


def test_undirected_relationships_have_canonical_endpoints_and_pair_keys() -> None:
    left = uuid4()
    right = uuid4()
    first, second = _canonical_relationship_endpoints(left, right, "undirected")

    assert str(first) < str(second)
    assert _relationship_pair_key(left, right) == _relationship_pair_key(right, left)
    assert _relationship_pair_key(first, second) == f"{first}:{second}"


def test_directed_relationships_preserve_direction_and_reject_self_edges() -> None:
    source = uuid4()
    target = uuid4()

    assert _canonical_relationship_endpoints(source, target, "directed") == (
        source,
        target,
    )
    with pytest.raises(ValidationError, match="自己建立关系"):
        _canonical_relationship_endpoints(source, source, "directed")


def test_relationship_labels_normalize_whitespace_and_case() -> None:
    assert _normalize_relationship_label("  Old   FRIEND  ") == "old friend"


def test_relationship_model_keys_are_stable_and_do_not_depend_on_names() -> None:
    character_id = uuid4()

    first = _relationship_character_key(character_id)
    renamed = _relationship_character_key(character_id)

    assert first == renamed
    assert first.startswith("character_")
    assert str(character_id) not in first


def test_clean_model_candidate_removes_only_final_agent_status_capsule() -> None:
    prose = "门内传来一声轻响。\n\n⟦ 第3章正文候选｜已完成；禁区检查通过｜待作者审阅 ⟧"
    continuation = "雨声盖住了铃响。\n\n⟧ 第一章续写候选｜约2000字｜锚点：招工通知 ⟧"
    workflow_tail = (
        "沈青禾把两只旧表并排放好。\n\n"
        "⟦ 准考证与磁带｜完成：证件闭环；下一步：等作者反馈是否进入下一章或修订本稿 ⟧"
    )
    generated_summary_tail = (
        "雾号替那句晚安轻轻应了一声。\n\n"
        "⟦ 潮声替你晚安｜已生成 6 段正文；阴谋线收束；外婆晚安重响青石巷。 ⟧"
    )

    assert _clean_model_candidate(prose) == "门内传来一声轻响。"
    assert _clean_model_candidate(continuation) == "雨声盖住了铃响。"
    assert _clean_model_candidate(workflow_tail) == "沈青禾把两只旧表并排放好。"
    assert _clean_model_candidate(generated_summary_tail) == "雾号替那句晚安轻轻应了一声。"
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
