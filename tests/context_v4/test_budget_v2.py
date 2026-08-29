from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.context_v4 import (
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextBudgetResultV1,
    ContextBudgetResultV2,
    ContextBudgetV1,
    ContextBudgetV2,
    ContextRequirement,
    WritingContextSnapshotV1,
    WritingContextSnapshotV2,
    assemble_novel_context,
    freeze_writing_context,
    freeze_writing_context_v2,
)

from .test_assembler import _block, _budget, _snapshot, _timeline


def _budget_v2(
    *,
    window: int = 200,
    output: int = 20,
    prompt: int = 10,
    overhead: int = 10,
) -> ContextBudgetV2:
    return ContextBudgetV2(
        requested_provider_id="configured-provider",
        requested_model_id="configured-model-alias",
        budget_provider_id="catalog-provider",
        budget_model_id="catalog-model-revision",
        effective_context_window_tokens=window,
        reserved_output_tokens=output,
        reserved_prompt_tokens=prompt,
        fixed_overhead_tokens=overhead,
        estimator_version="fixture-estimator/1",
    )


def test_context_budget_v2_separates_requested_and_budget_identity() -> None:
    budget = _budget_v2()
    assert budget.schema_version == "context-budget/2"
    assert budget.requested_provider_id == "configured-provider"
    assert budget.requested_model_id == "configured-model-alias"
    assert budget.budget_provider_id == "catalog-provider"
    assert budget.budget_model_id == "catalog-model-revision"
    assert budget.effective_context_window_tokens == 200
    assert budget.hard_input_token_budget == 170
    assert "actual_model_id" not in ContextBudgetV2.model_fields
    assert "actual_provider_id" not in ContextBudgetV2.model_fields


def test_context_budget_v2_rejects_blank_identity_and_exhausted_window() -> None:
    with pytest.raises(ValidationError):
        ContextBudgetV2.model_validate(
            {**_budget_v2().model_dump(), "requested_provider_id": ""}
        )
    with pytest.raises(ValidationError, match="leave no input"):
        _budget_v2(window=30, output=20, prompt=10)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ContextBudgetV2.model_validate(
            {**_budget_v2().model_dump(), "actual_model_id": "invented-before-call"}
        )


def test_assembler_returns_v2_accounting_without_actual_identity() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    block = _block(novel_id, title="完整资料", tokens=40)
    envelope = assemble_novel_context(
        _snapshot(
            novel_id,
            main,
            blocks=(block,),
            budget=_budget_v2(window=100, output=20, prompt=10, overhead=10),
        )
    )

    assert isinstance(envelope.budget, ContextBudgetResultV2)
    assert envelope.budget.requested_provider_id == "configured-provider"
    assert envelope.budget.budget_model_id == "catalog-model-revision"
    assert envelope.budget.hard_input_token_budget == 70
    assert envelope.budget.included_block_tokens == 40
    assert envelope.budget.remaining_tokens == 20
    serialized = envelope.budget.model_dump(mode="json")
    assert not any(key.startswith("actual_") for key in serialized)


def test_v2_overflow_reports_budget_identity_not_pre_call_actual() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    required = _block(
        novel_id,
        title="超额强制资料",
        tokens=61,
        requirement=ContextRequirement.REQUIRED,
    )
    with pytest.raises(ContextAssemblyError) as captured:
        assemble_novel_context(
            _snapshot(
                novel_id,
                main,
                blocks=(required,),
                budget=_budget_v2(window=100, output=20, prompt=10, overhead=10),
            )
        )
    assert captured.value.code is ContextAssemblyErrorCode.CONTEXT_OVERFLOW
    assert captured.value.details["requested_provider_id"] == "configured-provider"
    assert captured.value.details["budget_model_id"] == "catalog-model-revision"
    assert "actual_model_id" not in captured.value.details


def test_writing_snapshot_v2_is_stable_and_never_requires_actual() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    envelope = assemble_novel_context(
        _snapshot(novel_id, main, budget=_budget_v2())
    )

    left = freeze_writing_context_v2(
        envelope,
        context_policy_version="writing-context/2",
    )
    right = freeze_writing_context_v2(
        envelope,
        context_policy_version="writing-context/2",
    )
    assert isinstance(left, WritingContextSnapshotV2)
    assert left.schema_version == "writing-context-snapshot/2"
    assert left.assembly_hash == right.assembly_hash
    assert left.requested_model_id == "configured-model-alias"
    assert left.budget_model_id == "catalog-model-revision"
    assert left.effective_context_window_tokens == 200
    assert "actual_model_id" not in WritingContextSnapshotV2.model_fields
    assert "actual_provider_id" not in WritingContextSnapshotV2.model_fields
    assert not any(
        name.startswith("actual")
        for name in inspect.signature(freeze_writing_context_v2).parameters
    )
    assert "actual_model_id" not in left.model_dump_json()


def test_writing_snapshot_v2_rejects_identity_drift_from_envelope() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    envelope = assemble_novel_context(
        _snapshot(novel_id, main, budget=_budget_v2())
    )
    assert isinstance(envelope.budget, ContextBudgetResultV2)
    with pytest.raises(ValidationError, match="identity differs"):
        WritingContextSnapshotV2(
            novel_id=novel_id,
            purpose=envelope.purpose,
            requested_provider_id="other-provider",
            requested_model_id=envelope.budget.requested_model_id,
            budget_provider_id=envelope.budget.budget_provider_id,
            budget_model_id=envelope.budget.budget_model_id,
            effective_context_window_tokens=(
                envelope.budget.effective_context_window_tokens
            ),
            context_policy_version="writing-context/2",
            envelope=envelope,
            assembly_hash="0" * 64,
        )


def test_v1_budget_and_snapshot_remain_read_compatible() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    envelope = assemble_novel_context(
        _snapshot(novel_id, main, budget=_budget())
    )
    assert isinstance(envelope.budget, ContextBudgetResultV1)
    snapshot = freeze_writing_context(
        envelope,
        requested_model_id="writer-requested",
        actual_model_id="writer-model",
        context_policy_version="writing-context/1",
    )
    restored = WritingContextSnapshotV1.model_validate(
        snapshot.model_dump(mode="python")
    )
    assert restored == snapshot
    assert isinstance(restored.envelope.budget, ContextBudgetResultV1)


def test_v1_and_v2_freezers_reject_the_other_budget_generation() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id)
    v1_envelope = assemble_novel_context(
        _snapshot(novel_id, main, budget=ContextBudgetV1(**_budget().model_dump()))
    )
    v2_envelope = assemble_novel_context(
        _snapshot(novel_id, main, budget=_budget_v2())
    )
    with pytest.raises(ValueError, match="V2 freeze"):
        freeze_writing_context_v2(
            v1_envelope,
            context_policy_version="writing-context/2",
        )
    with pytest.raises(ValueError, match="V1 freeze"):
        freeze_writing_context(
            v2_envelope,
            requested_model_id="writer-requested",
            actual_model_id="writer-model",
            context_policy_version="writing-context/1",
        )
