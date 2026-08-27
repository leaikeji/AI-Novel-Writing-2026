from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.creative_schemas import StartCreativeGenerationRequest
from backend.creative_services import (
    EntityConflictError,
    apply_outline_generation_candidate,
    build_creative_generation_prompt,
    build_outline_generation_snapshot,
    outline_candidate_review,
)
from backend.models import Novel, OutlineDraft


def _records() -> tuple[Novel, OutlineDraft]:
    novel_id = uuid4()
    novel = Novel(
        id=novel_id,
        title="旧港回声",
        author_name="作者",
        audience="女频",
        genre="现实",
        subgenre="悬疑",
        idea="失踪录音带牵出旧港往事",
        template_name="现实生活",
        template_data={"core_conflict": "追查真相与保护家人"},
    )
    draft = OutlineDraft(
        id=uuid4(),
        novel_id=novel_id,
        version=7,
        target_chapter_count=80,
        background_text="绝不能进入背景 fresh 提示词的旧背景。",
        characters_json=[
            {
                "character_id": str(uuid4()),
                "name": "旧角色甲",
                "role_type": "main",
                "description": "旧角色描述",
                "details": {"gender": "女", "personality": "谨慎", "private_marker": "不得发送"},
            }
        ],
        plot_text="绝不能进入情节 fresh 提示词的旧情节。",
        highlight_text="绝不能进入亮点 fresh 提示词的旧亮点。",
    )
    return novel, draft


def _request(intent: str = "fresh") -> dict[str, object]:
    return {
        "schema_version": "outline-generation-request-v1",
        "intent": intent,
        "expected_outline_version": 7,
    }


@pytest.mark.parametrize(
    ("kind", "included", "excluded"),
    [
        ("outline_background", set(), {"background_text", "characters", "plot_text", "highlight_text"}),
        ("outline_characters", {"background_text"}, {"characters", "plot_text", "highlight_text"}),
        ("outline_plot", {"background_text", "characters"}, {"plot_text", "highlight_text"}),
        ("outline_highlight", {"background_text", "characters", "plot_text"}, {"highlight_text"}),
    ],
)
def test_fresh_outline_context_uses_server_allowlist(
    kind: str,
    included: set[str],
    excluded: set[str],
) -> None:
    novel, draft = _records()

    snapshot = build_outline_generation_snapshot(
        novel,
        draft,
        kind=kind,
        request_snapshot=_request(),
    )

    assert included <= set(snapshot["model_context"])
    assert excluded.isdisjoint(snapshot["model_context"])
    assert snapshot["audit_context"]["previous_target"]


def test_fresh_prompt_serializes_only_model_context() -> None:
    novel, draft = _records()
    snapshot = build_outline_generation_snapshot(
        novel,
        draft,
        kind="outline_background",
        request_snapshot=_request(),
    )

    prompt = build_creative_generation_prompt(
        {"kind": "outline_background", "input_snapshot": snapshot}
    )

    assert "旧背景" not in prompt
    assert "previous_target" not in prompt
    assert "失踪录音带" in prompt
    assert "不得猜测、复原或沿用" in prompt


def test_fresh_prompt_uses_job_specific_variation_without_old_target() -> None:
    novel, draft = _records()
    snapshot = build_outline_generation_snapshot(
        novel,
        draft,
        kind="outline_background",
        request_snapshot=_request(),
    )

    first = build_creative_generation_prompt(
        {"id": uuid4(), "kind": "outline_background", "input_snapshot": snapshot}
    )
    second = build_creative_generation_prompt(
        {"id": uuid4(), "kind": "outline_background", "input_snapshot": snapshot}
    )

    assert first != second
    assert "创作变化标识" in first
    assert "旧背景" not in first


def test_refine_prompt_includes_only_current_target_and_upstream_context() -> None:
    novel, draft = _records()
    snapshot = build_outline_generation_snapshot(
        novel,
        draft,
        kind="outline_plot",
        request_snapshot=_request("refine"),
    )

    assert snapshot["model_context"]["plot_text"] == draft.plot_text
    assert "highlight_text" not in snapshot["model_context"]


def test_character_context_removes_internal_ids_and_unapproved_details() -> None:
    novel, draft = _records()
    snapshot = build_outline_generation_snapshot(
        novel,
        draft,
        kind="outline_plot",
        request_snapshot=_request(),
    )

    character = snapshot["model_context"]["characters"][0]
    assert "character_id" not in character
    assert "private_marker" not in character["details"]


def test_outline_request_rejects_client_supplied_story_fields() -> None:
    with pytest.raises(PydanticValidationError):
        StartCreativeGenerationRequest(
            scope_type="outline",
            scope_id=uuid4(),
            novel_id=uuid4(),
            kind="outline_background",
            input_snapshot={**_request(), "background_text": "客户端夹带旧内容"},
        )


def test_character_duplicate_review_is_local_and_blocks_exact_copy() -> None:
    _, draft = _records()
    snapshot = {
        "audit_context": {"previous_target": draft.characters_json},
    }

    review = outline_candidate_review(
        "outline_characters",
        snapshot,
        {"characters": list(draft.characters_json)},
    )

    assert review["exact_duplicate"] is True
    assert review["similarity_level"] == "exact"


def test_character_duplicate_review_ignores_order_and_internal_ids() -> None:
    _, draft = _records()
    second = {
        "character_id": str(uuid4()),
        "name": "旧角色乙",
        "role_type": "supporting",
        "description": "配角描述",
        "details": {"gender": "男", "personality": "冲动"},
    }
    draft.characters_json = [*draft.characters_json, second]
    candidate = [
        {
            key: value
            for key, value in item.items()
            if key != "character_id"
        }
        for item in reversed(draft.characters_json)
    ]

    review = outline_candidate_review(
        "outline_characters",
        {"audit_context": {"previous_target": draft.characters_json}},
        {"characters": candidate},
    )

    assert review["exact_duplicate"] is True


def test_apply_candidate_uses_generation_source_version(monkeypatch) -> None:
    novel, draft = _records()
    job = SimpleNamespace(
        id=uuid4(),
        kind="outline_background",
        scope_type="outline",
        scope_id=draft.id,
        novel_id=novel.id,
        state="ready",
        input_snapshot={
            "audit_context": {
                "source_outline_version": 7,
                "previous_target": draft.background_text,
            }
        },
        output_json={
            "background_text": "新的背景候选。",
            "candidate_review": {"exact_duplicate": False},
        },
    )

    class FakeSession:
        def scalar(self, _statement):
            return job

        def get(self, model, identity):
            assert model is OutlineDraft
            assert identity == draft.id
            return draft

    applied: list[dict[str, object]] = []

    def update(_session, novel_id, **kwargs):
        applied.append({"novel_id": novel_id, **kwargs})
        return {"version": 8, "step": 2}

    monkeypatch.setattr("backend.creative_services.update_outline_draft", update)

    result = apply_outline_generation_candidate(FakeSession(), job.id, expected_version=7)

    assert result == {"version": 8, "step": 2}
    assert applied[0]["background_text"] == "新的背景候选。"
    with pytest.raises(EntityConflictError):
        apply_outline_generation_candidate(FakeSession(), job.id, expected_version=6)


def test_apply_candidate_recomputes_and_rejects_exact_duplicate() -> None:
    novel, draft = _records()
    job = SimpleNamespace(
        id=uuid4(),
        kind="outline_background",
        scope_type="outline",
        scope_id=draft.id,
        novel_id=novel.id,
        state="ready",
        input_snapshot={
            "audit_context": {
                "source_outline_version": 7,
                "previous_target": draft.background_text,
            }
        },
        output_json={
            "background_text": draft.background_text,
            "candidate_review": {"exact_duplicate": False},
        },
    )

    class FakeSession:
        def scalar(self, _statement):
            return job

        def get(self, _model, _identity):
            return draft

    with pytest.raises(Exception, match="完全相同"):
        apply_outline_generation_candidate(FakeSession(), job.id, expected_version=7)


@pytest.mark.parametrize(
    ("kind", "previous_target", "output_json", "message"),
    [
        ("outline_background", "旧背景", {"background_text": ""}, "背景候选内容无效"),
        (
            "outline_characters",
            [{"name": "旧主角", "role_type": "main"}],
            {"characters": [{"name": "只有配角", "role_type": "supporting"}]},
            "角色候选结构无效",
        ),
        ("outline_plot", "旧情节", {"plot_text": ""}, "情节候选内容无效"),
        (
            "outline_highlight",
            "旧亮点",
            {"highlight_text": "新" * 201},
            "亮点候选内容无效",
        ),
    ],
)
def test_apply_candidate_rejects_invalid_ready_job_output(
    kind: str,
    previous_target: object,
    output_json: dict[str, object],
    message: str,
) -> None:
    novel, draft = _records()
    job = SimpleNamespace(
        id=uuid4(),
        kind=kind,
        scope_type="outline",
        scope_id=draft.id,
        novel_id=novel.id,
        state="ready",
        input_snapshot={
            "audit_context": {
                "source_outline_version": 7,
                "previous_target": previous_target,
            }
        },
        output_json=output_json,
    )

    class FakeSession:
        def scalar(self, _statement):
            return job

        def get(self, _model, _identity):
            return draft

    with pytest.raises(Exception, match=message):
        apply_outline_generation_candidate(FakeSession(), job.id, expected_version=7)
