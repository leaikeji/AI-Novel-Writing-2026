from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.model_execution import (
    MODEL_EXECUTION_EVIDENCE_SCHEMA_VERSION,
    ModelExecutionContractError,
    ModelExecutionEvidenceStatus,
    ModelExecutionEvidenceV2,
    ModelExecutionRejectionReason,
    ModelIdentity,
    ProviderUsage,
    PublicUsageState,
    determine_model_execution_evidence,
    inspect_public_reply_metadata,
)


IDENTITY = ModelIdentity(provider_id="provider-a", model_id="model-a")
_UNSET = object()


def _chunks(usage: object, *, mapping_shape: bool = False) -> object:
    metadata = {"qwenpaw_turn_usage": {"usage": usage}}
    if mapping_shape:
        return [{"output": [{"role": "assistant", "metadata": metadata}]}]
    return [
        SimpleNamespace(
            output=[SimpleNamespace(role="assistant", metadata=metadata)]
        )
    ]


def _complete_usage(**changes: object) -> dict[str, object]:
    return {
        "provider_id": "provider-a",
        "model_name": "model-a",
        "prompt_tokens": 101,
        "completion_tokens": 202,
        "total_tokens": 303,
        **changes,
    }


def _determine(
    *,
    preflight: ModelIdentity = IDENTITY,
    postflight: ModelIdentity = IDENTITY,
    chunks: object = _UNSET,
) -> ModelExecutionEvidenceV2:
    return determine_model_execution_evidence(
        preflight_identity=preflight,
        postflight_identity=postflight,
        reply_chunks=_chunks(_complete_usage()) if chunks is _UNSET else chunks,
        agent_id="ai-novel-writer",
        duration_ms=842,
    )


def test_complete_public_usage_verifies_exact_actual_identity() -> None:
    evidence = _determine()

    assert evidence.status is ModelExecutionEvidenceStatus.VERIFIED_FROM_PROVIDER_USAGE
    assert evidence.actual_identity == IDENTITY
    assert evidence.usage == ProviderUsage(101, 202, 303)
    assert evidence.effective_model_pre_post_match is True
    assert evidence.private_usage_buffer_used is False
    assert evidence.as_dict() == {
        "schema_version": MODEL_EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "status": "verified_from_provider_usage",
        "execution_agent_id": "ai-novel-writer",
        "preflight_effective": {
            "provider_id": "provider-a",
            "model_id": "model-a",
            "source": "effective-model-api",
            "effective_max_input_length": None,
        },
        "postflight_effective": {
            "provider_id": "provider-a",
            "model_id": "model-a",
            "source": "effective-model-api",
        },
        "reported_actual": {
            "provider_id": "provider-a",
            "model_id": "model-a",
        },
        "usage": {
            "status": "exposed",
            "prompt_tokens": 101,
            "completion_tokens": 202,
            "total_tokens": 303,
            "provider_request_id": None,
        },
        "verification_reason": "provider_usage_matches_effective_model",
        "duration_ms": 842,
        "private_usage_buffer_used": False,
    }


def test_mapping_chunks_and_model_id_fallback_are_public_contract_shapes() -> None:
    usage = _complete_usage(model_name=None, model_id="model-a")
    observation = inspect_public_reply_metadata(
        _chunks(usage, mapping_shape=True)
    )

    assert observation.state is PublicUsageState.PRESENT
    assert observation.actual_identity == IDENTITY
    assert observation.usage == ProviderUsage(101, 202, 303)


def test_absent_usage_is_not_exposed_and_never_copies_requested_to_actual() -> None:
    chunks = [
        SimpleNamespace(
            output=[
                SimpleNamespace(
                    role="assistant",
                    metadata={"arbitrary_provider_id": "provider-a"},
                )
            ]
        )
    ]
    evidence = _determine(chunks=chunks)

    assert evidence.status is ModelExecutionEvidenceStatus.NOT_EXPOSED
    assert evidence.actual_identity is None
    assert evidence.usage is None
    assert evidence.rejection_reason is None
    assert evidence.private_usage_buffer_used is False
    assert evidence.as_dict()["reported_actual"] is None


def test_only_the_closing_assistant_message_can_supply_public_usage() -> None:
    chunks = [
        SimpleNamespace(
            output=[
                SimpleNamespace(
                    role="assistant",
                    metadata={
                        "qwenpaw_turn_usage": {"usage": _complete_usage()}
                    },
                ),
                SimpleNamespace(role="assistant", metadata={}),
            ]
        )
    ]

    evidence = _determine(chunks=chunks)

    assert evidence.status is ModelExecutionEvidenceStatus.NOT_EXPOSED
    assert evidence.actual_identity is None


@pytest.mark.parametrize(
    "chunks",
    [
        None,
        {"not": "a chunk sequence"},
        _chunks("not-an-object"),
        [
            SimpleNamespace(
                output=[
                    SimpleNamespace(
                        role="assistant",
                        metadata={"qwenpaw_turn_usage": "not-an-object"},
                    )
                ]
            )
        ],
        _chunks(_complete_usage(provider_id={"forged": "provider-a"})),
        _chunks(_complete_usage(model_name=[])),
        _chunks(_complete_usage(prompt_tokens=True)),
        _chunks(_complete_usage(prompt_tokens=-1)),
        _chunks(_complete_usage(
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
        )),
    ],
    ids=[
        "none-chunks",
        "mapping-not-sequence",
        "usage-not-mapping",
        "envelope-not-mapping",
        "provider-not-string",
        "model-not-string",
        "boolean-token",
        "negative-token",
        "all-token-counts-absent",
    ],
)
def test_malformed_public_usage_is_rejected_instead_of_not_exposed(
    chunks: object,
) -> None:
    evidence = _determine(chunks=chunks)

    assert evidence.status is ModelExecutionEvidenceStatus.REJECTED
    assert evidence.rejection_reason is (
        ModelExecutionRejectionReason.PUBLIC_USAGE_MALFORMED
    )
    assert evidence.actual_identity is None
    assert evidence.usage is None
    assert evidence.private_usage_buffer_used is False


@pytest.mark.parametrize(
    ("provider_id", "model_id"),
    [("provider-b", "model-a"), ("provider-a", "model-b")],
)
def test_provider_usage_identity_mismatch_is_rejected_and_preserved(
    provider_id: str,
    model_id: str,
) -> None:
    evidence = _determine(
        chunks=_chunks(
            _complete_usage(provider_id=provider_id, model_name=model_id)
        )
    )

    assert evidence.status is ModelExecutionEvidenceStatus.REJECTED
    assert evidence.rejection_reason is (
        ModelExecutionRejectionReason.PROVIDER_USAGE_IDENTITY_MISMATCH
    )
    assert evidence.actual_identity == ModelIdentity(provider_id, model_id)
    assert evidence.usage == ProviderUsage(101, 202, 303)


def test_preflight_postflight_switch_is_rejected_even_with_valid_usage() -> None:
    postflight = ModelIdentity("provider-b", "model-b")
    evidence = _determine(postflight=postflight)

    assert evidence.status is ModelExecutionEvidenceStatus.REJECTED
    assert evidence.rejection_reason is (
        ModelExecutionRejectionReason.PREFLIGHT_POSTFLIGHT_IDENTITY_MISMATCH
    )
    assert evidence.effective_model_pre_post_match is False
    assert evidence.actual_identity == IDENTITY
    assert evidence.usage == ProviderUsage(101, 202, 303)


def test_not_exposed_contract_forbids_non_null_actual_or_usage() -> None:
    with pytest.raises(ModelExecutionContractError, match="null actual usage"):
        ModelExecutionEvidenceV2(
            status=ModelExecutionEvidenceStatus.NOT_EXPOSED,
            preflight_identity=IDENTITY,
            postflight_identity=IDENTITY,
            actual_identity=IDENTITY,
            usage=ProviderUsage(1, 1, 2),
            agent_id="ai-novel-writer",
            duration_ms=1,
        )


@pytest.mark.parametrize(
    ("agent_id", "duration_ms"),
    [("", 1), ("ai-novel-writer", -1), ("ai-novel-writer", True)],
)
def test_invalid_execution_inputs_raise_contract_errors(
    agent_id: str,
    duration_ms: int,
) -> None:
    with pytest.raises(ModelExecutionContractError):
        determine_model_execution_evidence(
            preflight_identity=IDENTITY,
            postflight_identity=IDENTITY,
            reply_chunks=[],
            agent_id=agent_id,
            duration_ms=duration_ms,
        )


def test_domain_module_imports_only_python_standard_library() -> None:
    source_path = Path(__file__).resolve().parents[2] / "backend" / "model_execution" / "evidence.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert imported_roots <= {"__future__", "collections", "dataclasses", "enum", "typing"}
