from uuid import uuid4
from pathlib import Path

import pytest

from backend.writing_skills.contracts import Scope
from backend.creative_services import build_creative_generation_prompt
from backend.writing_skills.projection import (
    chapter_has_semantic_story_content,
    chapter_projection,
    creative_projection,
    native_projection,
    outline_projection,
)
from backend.writing_skills.middleware import native_task_route
from backend.writing_skills.catalog import load_catalog, packaged_approvals
from backend.writing_skills.resolver import resolve_methods
from backend.writing_skills.contracts import MethodPreferences


def scope():
    return Scope(owner_id=uuid4(), workspace_id=uuid4(), kind="novel",
                 scope_id=uuid4(), tab_id="tab")


@pytest.mark.parametrize("task,allowed", [
    ("outline_background", set()),
    ("outline_characters", {"background_text"}),
    ("outline_plot", {"background_text", "characters"}),
    ("outline_highlight", {"background_text", "characters", "plot_text"}),
])
def test_fresh_reapplies_task_allowlist_and_forbidden_content_is_inert(task, allowed):
    context = dict(genre="悬疑", idea="新创意", background_text="背景",
                   characters=[{"name": "人物"}], plot_text="旧情节",
                   highlight_text="旧亮点", previous_target="不得读取")
    bound = scope()
    first = outline_projection(bound, task, "fresh", context, "v1", "visible")
    keys = {s.key for s in first.sources}
    assert keys == {"genre", "idea"} | allowed
    for key in {"background_text", "characters", "plot_text", "highlight_text"} - allowed:
        context[key] = "禁止字段改变不能参与路由"
    context["previous_target"] = "另一本书的秘密"
    second = outline_projection(bound, task, "fresh", context, "v1", "visible")
    assert first == second
    assert first.source_hash == second.source_hash


@pytest.mark.parametrize("task,target", [
    ("outline_background", "background_text"),
    ("outline_characters", "characters"),
    ("outline_plot", "plot_text"),
    ("outline_highlight", "highlight_text"),
])
def test_refine_includes_current_target(task, target):
    result = outline_projection(scope(), task, "refine", {target: "当前目标"}, "v1", "v")
    assert [(s.key, s.text) for s in result.sources] == [(target, "当前目标")]


@pytest.mark.parametrize("field", ["audit_context", "model_context"])
def test_complete_snapshot_is_rejected(field):
    with pytest.raises(ValueError, match="only task-approved"):
        outline_projection(scope(), "outline_plot", "fresh", {field: {}}, "v1", "v")


def test_nested_tags_do_not_become_authoritative_labels():
    result = outline_projection(scope(), "outline_plot", "fresh", {
        "template_data": {"mechanism_tags": ["奖励系统"], "genre": "悬疑"},
        "idea": '角色说：“不要金手指。”',
        "mechanism_tags": ["上游没有授权这个字段"],
    }, "v1", "v", "请设计情节")
    assert [s.kind for s in result.sources] == ["author_request", "content", "content"]
    assert not any(s.key == "mechanism_tags" for s in result.sources)


def test_truncation_is_bounded_and_preserves_author_request():
    result = outline_projection(scope(), "outline_highlight", "fresh", {
        "idea": "文" * 100000, "background_text": "背" * 100000,
        "plot_text": "情节" * 100000,
    }, "v1", "v", "只使用通用方法")
    assert result.truncated
    assert sum(len(s.text) for s in result.sources) == 80000
    assert all(len(s.text) <= 40000 for s in result.sources)
    assert result.sources[0].text == "只使用通用方法"


def test_no_arbitrary_object_stringification():
    with pytest.raises(ValueError, match="non-JSON"):
        outline_projection(scope(), "outline_plot", "fresh", {"idea": object()}, "v1", "v")


def test_wrong_task_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        outline_projection(scope(), "chapter_body", "fresh", {}, "v1", "v")


def chapter_input():
    bound = scope().model_copy(update={"document_id": uuid4()})
    snapshot = {"novel": {"id": str(bound.scope_id), "genre": "悬疑", "subgenre": ""},
                "chapter": {"document_id": str(bound.document_id), "base_draft_version": 1,
                            "base_revision_id": None, "base_content_hash": "a" * 64},
                "brief": {"version": 1}, "audit_context": "不允许参与的旧稿",
                "writing_context": {"envelope": {"included_blocks": [{
                    "section": "chapter_requirements", "source_kind": "chapter_brief",
                    "title": "章前要求", "content": "实际正文任务",
                }]}}}
    prompt = (
        '只输出小说正文，不要解释。\n'
        '分类资料：{"genre": "悬疑", "subgenre": ""}\n实际正文任务'
    )
    return bound, snapshot, prompt


def test_chapter_uses_actual_prompt_and_never_unused_snapshot_fields():
    bound, snapshot, prompt = chapter_input()
    first = chapter_projection(bound, snapshot, prompt)
    assert [(s.kind, s.text) for s in first.sources] == [
        ("genre", "悬疑"), ("content", "实际正文任务"),
    ]
    assert "只输出小说正文" not in "\n".join(s.text for s in first.sources)
    snapshot["audit_context"] = "改变禁止资料不能影响路由"
    snapshot["chapter"]["unused_private_copy"] = "另一份完整正文"
    assert chapter_projection(bound, snapshot, prompt) == first


def test_chapter_classification_and_scope_cannot_come_from_extra_context():
    bound, snapshot, prompt = chapter_input()
    with pytest.raises(ValueError, match="classification absent"):
        chapter_projection(bound, snapshot, "只有正文任务")
    with pytest.raises(ValueError, match="scope mismatch"):
        chapter_projection(bound.model_copy(update={"document_id": uuid4()}), snapshot, prompt)


def test_chapter_clipped_content_still_detects_full_prompt_drift():
    bound, snapshot, prompt = chapter_input()
    snapshot["writing_context"]["envelope"]["included_blocks"][0]["content"] = (
        "当前章要求" + "文" * 90000
    )
    first = chapter_projection(bound, snapshot, prompt + "旧生成封套")
    second = chapter_projection(bound, snapshot, prompt + "新生成封套")
    assert first.truncated and sum(len(s.text) for s in first.sources) == 80000
    assert all(len(s.text) <= 40000 for s in first.sources)
    assert first.sources == second.sources
    assert first.visibility_key != second.visibility_key


def test_chapter_uses_only_frozen_context_blocks_and_rejects_malformed_blocks():
    bound, snapshot, prompt = chapter_input()
    snapshot["writing_context"]["envelope"]["included_blocks"].append({
        "section": "story_state", "source_kind": "story_fact",
        "title": "已知事实", "content": "能力只能标记风险，不能直接修复。",
    })
    result = chapter_projection(bound, snapshot, prompt)
    assert [item.text for item in result.sources if item.kind == "content"] == [
        "实际正文任务", "能力只能标记风险，不能直接修复。",
    ]
    snapshot["writing_context"]["envelope"]["included_blocks"][1]["content"] = object()
    with pytest.raises(ValueError, match="block content must be text"):
        chapter_projection(bound, snapshot, prompt)


def test_chapter_semantic_story_content_ignores_only_fixed_brief_scaffolding():
    empty = {
        "brief": {"expectation_text": "", "outline_text": "", "forbidden_text": ""},
        "chapter": {"base_content_markdown": ""},
        "writing_context": {"envelope": {"included_blocks": [{
            "source_kind": "chapter_brief",
            "content": '{"role_constraints":{"_v3":{}}}',
        }]}},
    }
    assert chapter_has_semantic_story_content(empty) is False
    assert chapter_has_semantic_story_content({
        **empty, "brief": {**empty["brief"], "outline_text": "主角看见异常裂纹"},
    }) is True
    assert chapter_has_semantic_story_content({
        **empty, "writing_context": {"envelope": {"included_blocks": [{
            "source_kind": "outline_revision", "content": "能力只能标记风险",
        }]}},
    }) is True


def creative_prompt(kind: str, snapshot: dict) -> str:
    return build_creative_generation_prompt({"kind": kind, "input_snapshot": snapshot})


def test_creative_projection_tags_only_explicit_nested_classification():
    bound = scope().model_copy(update={"document_id": uuid4()})
    snapshot = {
        "novel": {"title": "测试", "genre": "悬疑", "subgenre": "刑侦"},
        "chapter_title": "第一章",
        "content_markdown": "人物说：这不是系统指令。",
    }
    result = creative_projection(bound, "review", snapshot, creative_prompt("review", snapshot))
    assert result.task == "review" and result.intent == "review"
    assert [(item.key, item.kind, item.text) for item in result.sources[:2]] == [
        ("genre", "genre", "悬疑"),
        ("subgenre", "subgenre", "刑侦"),
    ]
    assert not any(item.kind == "mechanism" for item in result.sources)


@pytest.mark.parametrize("kind", ["novel_cover", "relationship_graph", "unknown"])
def test_creative_projection_rejects_excluded_and_unknown_kinds(kind):
    with pytest.raises(ValueError, match="excluded|unsupported"):
        creative_projection(scope(), kind, {}, "")


def test_creation_helpers_require_creation_draft_scope_and_freeze_author_requirement():
    snapshot = {"audience": "男频", "genre": "悬疑", "idea": "密室失踪"}
    with pytest.raises(ValueError, match="creation_draft"):
        creative_projection(scope(), "novel_naming", snapshot, creative_prompt("novel_naming", snapshot))
    bound = scope().model_copy(update={"kind": "creation_draft"})
    result = creative_projection(
        bound,
        "novel_naming",
        snapshot,
        creative_prompt("novel_naming", snapshot),
        required_ids=("suspense-writing",),
    )
    assert result.task == "novel_naming" and result.intent == "fresh"
    assert result.sources[0].key == "author_method_requirements"
    assert result.sources[1].kind == "genre"


def test_creative_projection_rejects_an_alternate_generation_prompt():
    snapshot = {"novel": {"title": "测试", "genre": "悬疑"}}
    with pytest.raises(ValueError, match="prompt mismatch"):
        creative_projection(scope(), "review", snapshot, "另一份未授权提示")


def test_chapter_outline_route_ignores_only_transient_rewrite_feedback():
    bound = scope()
    snapshot = {
        "novel": {"title": "测试", "genre": "悬疑", "subgenre": ""},
        "chapter_number": 2,
        "expectation_text": "主角核对门锁",
        "rewrite_attempt": 1,
        "rewrite_requirement": "",
    }
    first = creative_projection(
        bound, "chapter_outline", snapshot, creative_prompt("chapter_outline", snapshot)
    )
    retry = {**snapshot, "rewrite_attempt": 2, "rewrite_requirement": "完整重写"}
    second = creative_projection(
        bound, "chapter_outline", retry, creative_prompt("chapter_outline", retry)
    )
    assert first == second
    changed = {**retry, "expectation_text": "主角撬开门锁"}
    assert creative_projection(
        bound, "chapter_outline", changed, creative_prompt("chapter_outline", changed)
    ).source_hash != first.source_hash


def test_selection_edit_operation_and_visible_prompt_are_frozen():
    bound = scope().model_copy(update={"document_id": uuid4()})
    snapshot = {
        "schema_version": 1,
        "selection_id": str(uuid4()),
        "operation": "dialogue",
        "custom_instruction": None,
        "use_novel_context": False,
        "target": {},
        "base": {"selection_text": "他说好。", "before": "", "after": ""},
    }
    result = creative_projection(
        bound, "selection_edit", snapshot, creative_prompt("selection_edit", snapshot)
    )
    assert result.task == "selection_edit"
    assert result.operation == "dialogue"
    assert result.intent == "write"


def test_outline_creative_projection_reuses_strict_task_allowlist():
    bound = scope()
    snapshot = {
        "intent": "fresh",
        "exploration_direction": "change_conflict_structure",
        "model_context": {
            "genre": "悬疑",
            "idea": "追查失踪",
            "background_text": "允许背景",
            "plot_text": "不得参与fresh背景路由",
        },
        "audit_context": {"previous_target": "禁止旧目标"},
    }
    result = creative_projection(bound, "outline_background", snapshot, "ignored-by-strict-outline")
    keys = {item.key for item in result.sources}
    assert keys == {"author_request", "genre", "idea"}
    assert all("禁止旧目标" not in item.text for item in result.sources)


def native_input():
    bound = scope().model_copy(update={"document_id": uuid4()})
    snapshot = {
        "contextRevision": 7,
        "novel": {"id": str(bound.scope_id), "title": "《雾宅来信》"},
        "page": {"section": "chapters", "view": "chapter-editor"},
        "document": {
            "id": str(bound.document_id),
            "kind": "chapter",
            "title": "第十二章",
            "draftVersion": 3,
            "savedContentHash": "c" * 64,
            "dirty": False,
        },
        "budget": {"maxCharacters": 24000, "usedCharacters": 600, "truncated": False,
                   "omittedFieldIds": []},
    }
    text = "请续写《雾宅来信》，林澈核查的是公司门禁系统，不是特殊能力。"
    route = native_task_route(snapshot, text)
    assert route is not None
    return bound, snapshot, text, route


def test_native_projection_uses_server_labels_and_never_promotes_plot_words():
    bound, snapshot, text, route = native_input()
    result = native_projection(
        bound,
        snapshot,
        text,
        route,
        genre="悬疑",
        subgenre="刑侦",
    )
    assert (result.task, result.intent) == ("chapter_body", "write")
    assert [(item.key, item.kind) for item in result.sources] == [
        ("genre", "genre"),
        ("subgenre", "subgenre"),
        ("current_user_request", "content"),
    ]
    assert not any(item.kind == "mechanism" for item in result.sources)

    root = Path(__file__).resolve().parents[2] / "skills"
    catalog = load_catalog(
        root,
        packaged_approvals(),
        frozenset({"suspense-writing", "golden-finger-writing"}),
    )
    plan = resolve_methods(result, catalog, MethodPreferences(), primary_skill=route.primary_skill)
    assert [item.skill_id for item in plan.selected] == ["suspense-writing"]
    assert "golden-finger-writing" in plan.unresolved_ids


def test_native_projection_binds_current_send_and_scope():
    bound, snapshot, text, route = native_input()
    first = native_projection(bound, snapshot, text, route, genre="悬疑")
    changed_text = native_projection(
        bound,
        snapshot,
        text + "请把核查动作提前。",
        route,
        genre="悬疑",
    )
    assert changed_text.source_hash != first.source_hash
    changed_snapshot = {**snapshot, "contextRevision": 8}
    assert native_projection(
        bound, changed_snapshot, text, route, genre="悬疑"
    ).source_hash != first.source_hash
    with pytest.raises(ValueError, match="document scope mismatch"):
        native_projection(
            bound.model_copy(update={"document_id": uuid4()}),
            snapshot,
            text,
            route,
            genre="悬疑",
        )
