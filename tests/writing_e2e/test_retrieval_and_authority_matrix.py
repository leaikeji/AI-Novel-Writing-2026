from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.creative_schemas import OutlineCharacterDraftV2
from backend.embedding.contracts import RetrievalPurpose
from backend.embedding.writing import (
    deterministic_query,
    retrieval_purpose_for_selection,
    retrieve_for_writing,
)
from backend.model_execution import (
    ModelEvidencePolicyError,
    candidate_actual_identity,
)
from backend.model_execution.evidence import (
    ModelIdentity,
    determine_model_execution_evidence,
)
from backend.model_runtime import normalize_intelligence_generation_json

from ._host_stub import FakeSession, import_creative_api, reply


@pytest.mark.parametrize(
    ("operation", "use_novel_context", "expected"),
    [
        ("rewrite", False, RetrievalPurpose.SELECTION_REWRITE),
        ("expand", False, RetrievalPurpose.SELECTION_EXPAND),
        ("dialogue", False, RetrievalPurpose.SELECTION_DIALOGUE),
        ("review", False, RetrievalPurpose.SELECTION_REVIEW),
        ("polish", False, None),
        ("shorten", False, None),
        ("custom", False, None),
        ("custom", True, RetrievalPurpose.SELECTION_CUSTOM),
    ],
)
def test_selection_retrieval_is_an_explicit_operation_matrix(
    operation: str,
    use_novel_context: bool,
    expected: RetrievalPurpose | None,
) -> None:
    assert (
        retrieval_purpose_for_selection(
            operation,
            use_novel_context=use_novel_context,
        )
        is expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (RuntimeError("network unavailable"), "semantic_retrieval_unavailable"),
        (SimpleNamespace(code="dense_timeout"), "dense_timeout"),
    ],
    ids=("unclassified-failure", "stable-error-code"),
)
async def test_vector_failure_degrades_without_persisting_query_or_blocking_writing(
    monkeypatch: pytest.MonkeyPatch,
    error: object,
    expected_reason: str,
) -> None:
    from backend.embedding import writing

    async def fail(*_args, **_kwargs):
        if isinstance(error, BaseException):
            raise error
        failure = RuntimeError("dense query timed out")
        failure.code = error.code
        raise failure

    monkeypatch.setattr(writing, "semantic_search", fail)
    query = deterministic_query(
        purpose=RetrievalPurpose.CHAPTER_BODY,
        title="第二章",
        outline="查找第一章车票线索",
        expectation="不得泄漏未来信息",
    )

    snapshot = await retrieve_for_writing(
        object(),
        novel_id=uuid4(),
        purpose=RetrievalPurpose.CHAPTER_BODY,
        query=query,
    )

    assert snapshot["mode"] == "lexical_only"
    assert snapshot["hits"] == []
    assert snapshot["degraded_reason"] == expected_reason
    assert query not in repr(snapshot)
    assert "api_key" not in repr(snapshot).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        HTTPException(
            status_code=409,
            detail={"code": "timeline_required", "message": "timeline is required"},
        ),
        HTTPException(
            status_code=404,
            detail={"code": "timeline_not_found", "message": "timeline is not active"},
        ),
    ],
)
async def test_deterministic_timeline_errors_are_not_degraded(
    monkeypatch: pytest.MonkeyPatch,
    failure: HTTPException,
) -> None:
    from backend.embedding import writing

    async def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(writing, "semantic_search", fail)

    with pytest.raises(HTTPException) as caught:
        await retrieve_for_writing(
            object(),
            novel_id=uuid4(),
            purpose=RetrievalPurpose.CHAPTER_REVIEW,
            query="目标线审稿",
        )

    assert caught.value.detail == failure.detail


def _evidence(*, exposed: bool, mismatch: bool = False) -> dict[str, object]:
    identity = ModelIdentity("provider-plan37", "model-plan37")
    chunks: object
    if exposed:
        chunks = reply(
            text="candidate",
            provider_id="provider-plan37",
            model_id="model-other" if mismatch else "model-plan37",
        ).chunks
    else:
        chunks = reply(text="candidate", provider_id=None, model_id=None).chunks
    return determine_model_execution_evidence(
        preflight_identity=identity,
        postflight_identity=identity,
        reply_chunks=chunks,
        agent_id="ai-novel-writer",
        duration_ms=4,
    ).as_dict()


@pytest.mark.parametrize(
    ("evidence", "actual"),
    [
        (_evidence(exposed=True), ("provider-plan37", "model-plan37")),
        (_evidence(exposed=False), (None, None)),
    ],
    ids=("verified", "not-exposed"),
)
def test_candidate_gate_accepts_only_truthful_public_evidence(
    evidence: dict[str, object],
    actual: tuple[str | None, str | None],
) -> None:
    assert candidate_actual_identity(
        evidence,
        requested_provider_id="provider-plan37",
        requested_model_id="model-plan37",
    ) == actual


def test_candidate_gate_rejects_model_mismatch() -> None:
    with pytest.raises(ModelEvidencePolicyError, match="已拒绝"):
        candidate_actual_identity(
            _evidence(exposed=True, mismatch=True),
            requested_provider_id="provider-plan37",
            requested_model_id="model-plan37",
        )


def test_outline_character_draft_keeps_stable_link_and_instance_profile_fields() -> None:
    character_id = uuid4()
    draft = OutlineCharacterDraftV2(
        draft_key="lead-001",
        character_id=character_id,
        role_type="main",
        name="周清和",
        gender="女",
        age_at_story_start_note="开篇约三十岁",
        identity_summary="市档案馆编目员",
        personality_summary="对程序极度谨慎，却会为关键证词破例。",
        core_goal="找到被替换的档案原件",
        bio="现代悬疑主角",
        origin="manual",
    )

    payload = draft.model_dump(mode="json")
    assert payload["schema_version"] == "outline-character-draft/2"
    assert payload["character_id"] == str(character_id)
    assert payload["identity_summary"] == "市档案馆编目员"
    assert payload["age_at_story_start_note"] == "开篇约三十岁"


def test_intelligence_normalization_keeps_model_output_as_unconfirmed_items() -> None:
    source = "周清和把车票线索告诉了陆川。"
    payload = {
        "items": [
            {
                "fact_type": "knowledge_event",
                "entity_key": "character_lead",
                "subject": "周清和",
                "predicate": "告知",
                "object": "车票线索",
                "source_text": source,
                "dimension": "case_clue",
                "event_kind": "learn",
                "confidence": 90,
            }
        ]
    }

    items = normalize_intelligence_generation_json(payload, repr(payload))
    assert len(items) == 1
    assert items[0]["fact_type"] == "knowledge_event"
    assert items[0]["source_text"] == source
    assert "story_fact_id" not in items[0]
    assert "accepted" not in items[0]


def test_outline_formalization_surfaces_same_name_link_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = import_creative_api(monkeypatch)
    novel_id = uuid4()
    existing_id = uuid4()

    def conflict(*_args, **_kwargs):
        raise api.CharacterLinkRequiredError(
            [
                {
                    "draft_key": "lead-001",
                    "draft_name": "周清和",
                    "existing_character_id": str(existing_id),
                    "existing_character_name": "周清和",
                }
            ]
        )

    monkeypatch.setattr(api, "complete_outline_draft", conflict)
    session = FakeSession()
    with pytest.raises(HTTPException) as captured:
        api.outline_drafts_complete(
            novel_id,
            api.CompleteVersionedRequest(expected_version=4),
            session=session,
        )

    assert captured.value.status_code == 409
    detail = captured.value.detail
    assert detail["type"] == "character_link_required"
    assert detail["conflicts"][0]["existing_character_id"] == str(existing_id)
    assert session.rollback_count == 1


def test_plan37_matrix_declares_postgres_only_authority_gates() -> None:
    """Keep stub evidence honest about the transactions it cannot prove."""

    gates = {
        "outline_materializes_root_instance_and_revisions": "postgres_integration",
        "candidate_adoption_creates_immutable_revision": "postgres_integration",
        "storyfact_confirmation_is_atomic": "postgres_integration",
        "active_index_refresh_retires_previous_source": "postgres_integration",
    }
    assert set(gates.values()) == {"postgres_integration"}
    assert set(gates) == {
        "outline_materializes_root_instance_and_revisions",
        "candidate_adoption_creates_immutable_revision",
        "storyfact_confirmation_is_atomic",
        "active_index_refresh_retires_previous_source",
    }
