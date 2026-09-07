import hashlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.creative_schemas import StartCreativeGenerationRequest


def _action():
    return {"action_id": str(uuid4()), "tab_id": "schema-test"}


def test_managed_creation_requires_scope_version_and_strict_fields():
    base = {
        "scope_type": "novel_creation",
        "scope_id": uuid4(),
        "kind": "novel_naming",
        "input_snapshot": {"audience": "女频", "genre": "悬疑"},
        "writing_action": _action(),
    }
    with pytest.raises(ValidationError, match="当前草稿版本"):
        StartCreativeGenerationRequest.model_validate(base)
    with pytest.raises(ValidationError, match="未允许字段"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "expected_scope_version": 1,
            "input_snapshot": {**base["input_snapshot"], "private_extra": "no"},
        })
    accepted = StartCreativeGenerationRequest.model_validate({
        **base,
        "expected_scope_version": 2,
    })
    assert accepted.expected_scope_version == 2


def test_legacy_creation_request_remains_compatible_without_new_fields():
    request = StartCreativeGenerationRequest(
        scope_type="novel_creation",
        scope_id=uuid4(),
        kind="novel_template",
        input_snapshot={"audience": "男频", "idea": "远行"},
        force_new=True,
    )
    assert request.writing_action is None
    assert request.expected_scope_version is None


def test_managed_outline_requires_matching_scope_and_snapshot_version():
    base = {
        "scope_type": "outline",
        "scope_id": uuid4(),
        "novel_id": uuid4(),
        "kind": "outline_background",
        "expected_scope_version": 3,
        "input_snapshot": {
            "schema_version": "outline-generation-request-v1",
            "intent": "fresh",
            "expected_outline_version": 3,
        },
        "writing_action": _action(),
    }
    accepted = StartCreativeGenerationRequest.model_validate(base)
    assert accepted.expected_scope_version == 3
    with pytest.raises(ValidationError, match="当前大纲版本"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "expected_scope_version": 4,
        })
    with pytest.raises(ValidationError, match="受管大纲生成范围无效"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "scope_type": "novel",
        })


@pytest.mark.parametrize(
    ("kind", "input_snapshot"),
    [
        ("chapter_storyline_recommendation", {}),
        ("chapter_outline", {"rewrite_attempt": 1}),
    ],
)
def test_managed_chapter_helpers_require_exact_draft_scope_and_fields(
    kind,
    input_snapshot,
):
    base = {
        "scope_type": "chapter_creation",
        "scope_id": uuid4(),
        "novel_id": uuid4(),
        "kind": kind,
        "expected_scope_version": 4,
        "force_new": True,
        "input_snapshot": input_snapshot,
        "writing_action": _action(),
    }
    accepted = StartCreativeGenerationRequest.model_validate(base)
    assert accepted.expected_scope_version == 4
    with pytest.raises(ValidationError, match="受管章节辅助生成范围无效"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "expected_scope_version": None,
        })
    with pytest.raises(ValidationError, match="不接受浏览器资料|只接受重写次数"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "input_snapshot": {**input_snapshot, "private_extra": "no"},
        })
    with pytest.raises(ValidationError, match="受管章节辅助生成范围无效"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "scope_type": "novel",
        })


def test_managed_review_requires_exact_document_version_hash_and_fields():
    document_id = uuid4()
    snapshot = {
        "novel_title": "雾宅来信",
        "genre": "悬疑",
        "subgenre": "刑侦",
        "chapter_title": "第1章 死者来信",
        "visible_character_count": 1200,
        "outline_text": "核对来信与卷宗。",
        "expectation_text": "保持证据链清楚。",
        "content_markdown": "林澈打开卷宗。",
        "draft_version": 7,
        "content_hash": "a" * 64,
    }
    base = {
        "scope_type": "document",
        "scope_id": document_id,
        "novel_id": uuid4(),
        "document_id": document_id,
        "kind": "review",
        "expected_scope_version": 7,
        "force_new": True,
        "input_snapshot": snapshot,
        "writing_action": _action(),
    }
    accepted = StartCreativeGenerationRequest.model_validate(base)
    assert accepted.expected_scope_version == 7
    with pytest.raises(ValidationError, match="当前正文草稿版本"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "expected_scope_version": 8,
        })
    with pytest.raises(ValidationError, match="字段不完整或包含未知字段"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "input_snapshot": {**snapshot, "private_extra": "no"},
        })
    with pytest.raises(ValidationError, match="正文哈希无效"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "input_snapshot": {**snapshot, "content_hash": "not-a-hash"},
        })


def test_managed_selection_accepts_only_exact_chapter_body_draft():
    novel_id = uuid4()
    document_id = uuid4()
    selection_id = uuid4()
    snapshot = {
        "schema_version": 1,
        "selection_id": selection_id,
        "operation": "polish",
        "custom_instruction": None,
        "use_novel_context": False,
        "target": {
            "novel_id": novel_id,
            "document_id": document_id,
            "entity_type": "document",
            "entity_id": document_id,
            "field_id": "chapter.body",
            "field_label": "正文",
            "persistence": "autosave",
            "context_revision": 3,
        },
        "base": {
            "field_value_sha256": "a" * 64,
            "persistence_version_kind": "draft",
            "persistence_version": 5,
            "start_utf16": 0,
            "end_utf16": 2,
            "selection_text": "林澈",
            "selection_text_sha256": hashlib.sha256("林澈".encode()).hexdigest(),
            "before": "",
            "after": "打开卷宗。",
        },
    }
    base = {
        "scope_type": "document",
        "scope_id": document_id,
        "novel_id": novel_id,
        "document_id": document_id,
        "kind": "selection_edit",
        "expected_scope_version": 5,
        "input_snapshot": snapshot,
        "writing_action": _action(),
    }
    accepted = StartCreativeGenerationRequest.model_validate(base)
    assert accepted.expected_scope_version == 5
    with pytest.raises(ValidationError, match="当前章节正文草稿"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "expected_scope_version": 6,
        })
    with pytest.raises(ValidationError, match="当前章节正文草稿"):
        StartCreativeGenerationRequest.model_validate({
            **base,
            "input_snapshot": {
                **snapshot,
                "target": {
                    **snapshot["target"],
                    "field_id": "chapter.title",
                    "persistence": "explicit-save",
                },
                "base": {
                    **snapshot["base"],
                    "persistence_version_kind": "entity",
                },
            },
        })


def test_legacy_non_body_selection_remains_compatible():
    novel_id = uuid4()
    snapshot = {
        "schema_version": 1,
        "selection_id": uuid4(),
        "operation": "review",
        "custom_instruction": None,
        "use_novel_context": False,
        "target": {
            "novel_id": novel_id,
            "document_id": None,
            "entity_type": "setting",
            "entity_id": novel_id,
            "field_id": "settings.idea",
            "field_label": "创作思路",
            "persistence": "explicit-save",
            "context_revision": 4,
        },
        "base": {
            "field_value_sha256": "a" * 64,
            "persistence_version_kind": "entity",
            "persistence_version": 2,
            "start_utf16": 0,
            "end_utf16": 2,
            "selection_text": "旧案",
            "selection_text_sha256": hashlib.sha256("旧案".encode()).hexdigest(),
            "before": "",
            "after": "重查",
        },
    }
    request = StartCreativeGenerationRequest.model_validate({
        "scope_type": "novel",
        "scope_id": novel_id,
        "novel_id": novel_id,
        "kind": "selection_edit",
        "input_snapshot": snapshot,
    })
    assert request.writing_action is None
