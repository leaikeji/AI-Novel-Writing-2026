import math
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.creative_schemas import (
    SelectionEditInputSnapshot,
    StartCreativeGenerationRequest,
)
from backend.creative_services import (
    build_creative_generation_prompt,
    creative_generation_skill,
    list_creative_generations,
    start_creative_generation,
)
from backend.model_runtime import (
    ModelVerificationError,
    normalize_creative_generation_json,
)
from backend.models import CreativeGenerationJob, Novel
from backend.selection_edit_diff import (
    SelectionEditDiffError,
    build_selection_edit_diff,
    build_selection_edit_result,
    reconstruct_selection_edit_diff,
    validate_selection_edit_result,
)
from backend.services import ValidationError, content_hash


def _snapshot(
    *,
    novel_id: UUID | None = None,
    selection_id: UUID | None = None,
    operation: str = "polish",
    selection_text: str = "她在雨里停住脚步。",
    field_id: str = "settings.idea",
    field_value: str = "她在雨里停住脚步。远处传来钟声。",
    entity_type: str = "setting",
    entity_id: UUID | None = None,
    document_id: UUID | None = None,
    persistence: str = "explicit-save",
    persistence_version_kind: str = "entity",
    persistence_version: int | None = 1,
    custom_instruction: str | None = None,
) -> dict[str, object]:
    novel_id = novel_id or uuid4()
    if entity_type == "setting" and entity_id is None:
        entity_id = novel_id
    return {
        "schema_version": 1,
        "selection_id": str(selection_id or uuid4()),
        "operation": operation,
        "custom_instruction": custom_instruction,
        "target": {
            "novel_id": str(novel_id),
            "document_id": str(document_id) if document_id else None,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "field_id": field_id,
            "field_label": "创作思路",
            "persistence": persistence,
            "context_revision": 7,
        },
        "base": {
            "field_value_sha256": content_hash(field_value),
            "persistence_version_kind": persistence_version_kind,
            "persistence_version": persistence_version,
            "start_utf16": 0,
            "end_utf16": len(selection_text.encode("utf-16-le")) // 2,
            "selection_text": selection_text,
            "selection_text_sha256": content_hash(selection_text),
            "before": "",
            "after": "远处传来钟声。",
        },
    }


class _FakeBind:
    dialect = SimpleNamespace(name="sqlite")


class _ScalarRows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _GenerationSession:
    def __init__(self, novel_id: UUID) -> None:
        self.novel_id = novel_id
        self.current: CreativeGenerationJob | None = None
        self.rows: list[CreativeGenerationJob] = []
        self.commit_count = 0

    def get_bind(self):
        return _FakeBind()

    def get(self, model, entity_id):
        if model is Novel and entity_id == self.novel_id:
            return SimpleNamespace(id=entity_id)
        return None

    def scalar(self, _query):
        return self.current

    def scalars(self, _query):
        return _ScalarRows(self.rows)

    def add(self, job):
        self.current = job
        self.rows.insert(0, job)

    def commit(self):
        self.commit_count += 1


def test_diff_is_deterministic_and_reconstructs_both_sides() -> None:
    original = "雨落在旧站台。\n她没有回头，只把车票折进掌心。"
    candidate = "雨落在空荡的旧站台。\n她仍没有回头，把发软的车票折进掌心。"

    first = build_selection_edit_diff(original, candidate, job_id="job-001")
    second = build_selection_edit_diff(original, candidate, job_id="job-001")

    assert first == second
    assert reconstruct_selection_edit_diff(first, candidate=False) == original
    assert reconstruct_selection_edit_diff(first, candidate=True) == candidate
    assert len({item["segment_id"] for item in first}) == len(first)
    assert {item["kind"] for item in first} <= {
        "equal",
        "insert",
        "delete",
        "replace",
    }


def test_identical_candidate_has_no_fake_change_block() -> None:
    text = "门外的风铃轻轻响了一声。"

    segments = build_selection_edit_diff(text, text, job_id="job-same")

    assert segments == [
        {
            "segment_id": segments[0]["segment_id"],
            "kind": "equal",
            "text": text,
        }
    ]


def test_long_unaligned_change_safely_falls_back_to_one_replacement() -> None:
    original = "甲" * 2_000
    candidate = "乙" * 2_000

    segments = build_selection_edit_diff(original, candidate, job_id="job-fallback")

    assert segments == [
        {
            "segment_id": segments[0]["segment_id"],
            "kind": "replace",
            "original_text": original,
            "replacement_text": candidate,
        }
    ]


def test_result_contract_rejects_tampered_diff() -> None:
    result = build_selection_edit_result(
        job_id="job-result",
        selection_id="selection-1",
        operation="rewrite",
        original_text="旧句。",
        replacement_text="新句。",
        short_summary="调整表达。",
    )
    validate_selection_edit_result(
        result,
        expected_selection_id="selection-1",
        expected_operation="rewrite",
        expected_original_text="旧句。",
    )

    result["diff_segments"][0]["original_text"] = "被篡改的旧句。"
    with pytest.raises(SelectionEditDiffError, match="reconstruction"):
        validate_selection_edit_result(
            result,
            expected_selection_id="selection-1",
            expected_operation="rewrite",
            expected_original_text="旧句。",
        )


def test_selection_snapshot_validates_utf16_hash_scope_and_frozen_field() -> None:
    novel_id = uuid4()
    text = "她回头看见灯亮了🙂"
    snapshot = _snapshot(novel_id=novel_id, selection_text=text)

    parsed = SelectionEditInputSnapshot.model_validate(snapshot)
    request = StartCreativeGenerationRequest(
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        input_snapshot=snapshot,
        novel_id=novel_id,
    )

    assert parsed.base.end_utf16 == len(text.encode("utf-16-le")) // 2
    assert request.input_snapshot["target"]["document_id"] is None
    assert request.input_snapshot["custom_instruction"] is None

    invalid_range = _snapshot(novel_id=novel_id, selection_text=text)
    invalid_range["base"]["end_utf16"] = len(text)
    with pytest.raises(PydanticValidationError, match="UTF-16"):
        SelectionEditInputSnapshot.model_validate(invalid_range)

    invalid_field = _snapshot(novel_id=novel_id)
    invalid_field["target"]["field_id"] = "arbitrary.database.column"
    with pytest.raises(PydanticValidationError, match="受控选区字段"):
        SelectionEditInputSnapshot.model_validate(invalid_field)

    coerced_revision = _snapshot(novel_id=novel_id)
    coerced_revision["target"]["context_revision"] = "7"
    with pytest.raises(PydanticValidationError):
        SelectionEditInputSnapshot.model_validate(coerced_revision)


def test_custom_instruction_is_only_allowed_for_custom_operation() -> None:
    with pytest.raises(PydanticValidationError, match="必须提供"):
        SelectionEditInputSnapshot.model_validate(_snapshot(operation="custom"))
    with pytest.raises(PydanticValidationError, match="仅 custom"):
        SelectionEditInputSnapshot.model_validate(
            _snapshot(operation="polish", custom_instruction="改成冷峻语气")
        )
    parsed = SelectionEditInputSnapshot.model_validate(
        _snapshot(operation="custom", custom_instruction="  改成冷峻语气  ")
    )
    assert parsed.custom_instruction == "改成冷峻语气"


def test_explicit_save_version_kind_matches_persisted_or_temporary_entity() -> None:
    persisted_as_temporary = _snapshot(persistence_version_kind="none")
    persisted_as_temporary["base"]["persistence_version"] = None
    with pytest.raises(PydanticValidationError, match="entity_id"):
        SelectionEditInputSnapshot.model_validate(persisted_as_temporary)

    temporary_as_persisted = _snapshot(
        entity_type="character",
        entity_id=None,
        field_id="character.description",
        persistence_version_kind="entity",
    )
    with pytest.raises(PydanticValidationError, match="entity_id"):
        SelectionEditInputSnapshot.model_validate(temporary_as_persisted)

    temporary = _snapshot(
        entity_type="character",
        entity_id=None,
        field_id="character.description",
        persistence_version_kind="none",
        persistence_version=None,
    )
    assert (
        SelectionEditInputSnapshot.model_validate(temporary)
        .base.persistence_version_kind
        == "none"
    )


def test_model_normalizer_accepts_only_two_model_owned_fields() -> None:
    raw = (
        '{"replacement_text":"她在雨幕里停住脚步。",'
        '"short_summary":"改善画面感。"}'
    )
    normalized = normalize_creative_generation_json(
        "selection_edit",
        {
            "replacement_text": "她在雨幕里停住脚步。",
            "short_summary": "改善画面感。",
        },
        raw,
    )
    assert normalized == {
        "replacement_text": "她在雨幕里停住脚步。",
        "short_summary": "改善画面感。",
    }

    with pytest.raises(ModelVerificationError, match="只能包含"):
        normalize_creative_generation_json(
            "selection_edit",
            {
                **normalized,
                "diff_segments": [],
            },
            (
                '{"replacement_text":"她在雨幕里停住脚步。",'
                '"short_summary":"改善画面感。","diff_segments":[]}'
            ),
        )
    with pytest.raises(ModelVerificationError, match="状态胶囊"):
        normalize_creative_generation_json(
            "selection_edit",
            {
                "replacement_text": "她停住脚步。\n⟦ 状态：已完成 ⟧",
                "short_summary": "润色。",
            },
            (
                '{"replacement_text":"她停住脚步。\\n⟦ 状态：已完成 ⟧",'
                '"short_summary":"润色。"}'
            ),
        )

    with pytest.raises(ModelVerificationError, match="单一严格 JSON"):
        normalize_creative_generation_json(
            "selection_edit",
            normalized,
            f"```json\n{raw}\n```",
        )

    with pytest.raises(ModelVerificationError, match="单一严格 JSON"):
        normalize_creative_generation_json(
            "selection_edit",
            normalized,
            (
                '{"replacement_text":"第一版",'
                '"replacement_text":"她在雨幕里停住脚步。",'
                '"short_summary":"改善画面感。"}'
            ),
        )


@pytest.mark.parametrize(
    ("operation", "expected_skill"),
    [
        ("polish", "prose-writing"),
        ("rewrite", "prose-writing"),
        ("expand", "prose-writing"),
        ("shorten", "prose-writing"),
        ("dialogue", "prose-writing"),
        ("review", "style-review"),
        ("custom", "prose-writing"),
    ],
)
def test_operation_skill_mapping_and_prompt_contract(
    operation: str,
    expected_skill: str,
) -> None:
    custom_instruction = "变得更克制" if operation == "custom" else None
    job = {
        "kind": "selection_edit",
        "input_snapshot": _snapshot(
            operation=operation,
            custom_instruction=custom_instruction,
        ),
    }

    assert creative_generation_skill(job) == expected_skill
    prompt = build_creative_generation_prompt(job)
    assert "只能包含 replacement_text 与 short_summary" in prompt
    assert "before 与 after 只用于保持衔接" in prompt
    assert "diff_segments" in prompt


def test_service_reuses_ready_job_and_force_new_increments_attempt() -> None:
    novel_id = uuid4()
    snapshot = _snapshot(novel_id=novel_id)
    session = _GenerationSession(novel_id)
    arguments = {
        "scope_type": "novel",
        "scope_id": novel_id,
        "kind": "selection_edit",
        "input_snapshot": snapshot,
        "execution_agent_id": "ai-novel-writer",
        "requested_provider_id": "provider-a",
        "requested_model_id": "model-a",
        "generation_contract_version": "follow-agent-effective-v1",
        "novel_id": novel_id,
    }

    first = start_creative_generation(session, **arguments)
    assert first["attempt"] == 1
    session.current.state = "ready"

    reused = start_creative_generation(session, **arguments)
    regenerated = start_creative_generation(session, force_new=True, **arguments)

    assert reused["id"] == first["id"]
    assert reused["should_execute"] is False
    assert regenerated["id"] != first["id"]
    assert regenerated["attempt"] == 2
    assert regenerated["should_execute"] is True


def test_service_rejects_selection_hash_mismatch_without_creating_job() -> None:
    novel_id = uuid4()
    snapshot = _snapshot(novel_id=novel_id)
    snapshot["base"]["selection_text_sha256"] = "0" * 64
    session = _GenerationSession(novel_id)

    with pytest.raises(ValidationError, match="哈希"):
        start_creative_generation(
            session,
            scope_type="novel",
            scope_id=novel_id,
            kind="selection_edit",
            input_snapshot=snapshot,
            execution_agent_id="ai-novel-writer",
            requested_provider_id="provider-a",
            requested_model_id="model-a",
            generation_contract_version="follow-agent-effective-v1",
            novel_id=novel_id,
        )
    assert session.current is None


def test_recovery_query_filters_by_selection_id() -> None:
    novel_id = uuid4()
    wanted = uuid4()
    session = _GenerationSession(novel_id)
    for selection_id in (wanted, uuid4()):
        job = CreativeGenerationJob(
            id=uuid4(),
            scope_type="novel",
            scope_id=novel_id,
            novel_id=novel_id,
            kind="selection_edit",
            state="ready",
            input_hash=content_hash(str(selection_id)),
            input_snapshot=_snapshot(
                novel_id=novel_id,
                selection_id=selection_id,
            ),
            execution_agent_id="ai-novel-writer",
            requested_provider_id="provider-a",
            requested_model_id="model-a",
            generation_contract_version="follow-agent-effective-v1",
            attempt=1,
        )
        session.rows.append(job)

    recovered = list_creative_generations(
        session,
        scope_type="novel",
        scope_id=novel_id,
        kind="selection_edit",
        selection_id=wanted,
    )

    assert len(recovered) == 1
    assert recovered[0]["input_snapshot"]["selection_id"] == str(wanted)


def test_12k_diff_p95_is_below_100ms() -> None:
    repeated_original = (
        "旧站台的雨落在青石缝里。她把车票攥紧，又慢慢松开。" * 600
    )[:12_000]
    repeated_candidate = repeated_original.replace(
        "车票", "泛黄的车票", 20
    ).replace("慢慢", "终于", 20)[:12_000]
    numbered_parts: list[str] = []
    number = 0
    while len("".join(numbered_parts)) < 12_000:
        numbered_parts.append(
            f"第{number:04d}盏路灯照着不同的雨痕，她记下站台钟声与车票编号。"
        )
        number += 1
    varied_original = "".join(numbered_parts)[:12_000]
    varied_candidate = varied_original
    for number in range(0, 100, 5):
        varied_candidate = varied_candidate.replace(
            f"第{number:04d}盏",
            f"第{number:04d}束",
            1,
        )

    for case, original, candidate in (
        ("bounded-fallback", repeated_original, repeated_candidate),
        ("structured-changes", varied_original, varied_candidate),
    ):
        assert len(original) == len(candidate) == 12_000
        durations: list[float] = []
        for index in range(25):
            started = time.perf_counter()
            segments = build_selection_edit_diff(
                original,
                candidate,
                job_id=f"performance-{case}-{index}",
            )
            durations.append(time.perf_counter() - started)
            assert reconstruct_selection_edit_diff(segments, candidate=False) == original
            assert reconstruct_selection_edit_diff(segments, candidate=True) == candidate
        if case == "structured-changes":
            assert len(segments) > 20
        p95 = sorted(durations)[math.ceil(len(durations) * 0.95) - 1]
        assert p95 < 0.1, f"12k {case} diff p95 was {p95 * 1000:.2f}ms"
