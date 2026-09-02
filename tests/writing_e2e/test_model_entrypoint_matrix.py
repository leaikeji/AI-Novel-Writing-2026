from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from backend.model_runtime import ModelAudit

from ._host_stub import FakeSession, import_app, import_creative_api, reply


CONFIGURED_MODEL = ModelAudit(
    provider_id="provider-plan37",
    model_id="model-plan37",
    source="effective-model-api",
    effective_max_input_length=32_768,
)


def _selection_snapshot(
    novel_id: UUID,
    *,
    operation: str,
    use_novel_context: bool = False,
) -> dict[str, object]:
    selection_text = "她把湿透的车票放在证物袋旁。"
    digest = hashlib.sha256(selection_text.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "selection_id": str(uuid4()),
        "operation": operation,
        "custom_instruction": "补强线索连续性" if operation == "custom" else None,
        "use_novel_context": use_novel_context,
        "target": {
            "novel_id": str(novel_id),
            "document_id": None,
            "entity_type": "setting",
            "entity_id": str(novel_id),
            "field_id": "settings.idea",
            "field_label": "创作思路",
            "persistence": "explicit-save",
            "context_revision": 2,
        },
        "base": {
            "field_value_sha256": digest,
            "persistence_version_kind": "entity",
            "persistence_version": 1,
            "start_utf16": 0,
            "end_utf16": len(selection_text.encode("utf-16-le")) // 2,
            "selection_text": selection_text,
            "selection_text_sha256": digest,
            "before": "雨声压住了站台广播。",
            "after": "远处绿灯只亮了一秒。",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("usage_provider", "usage_model", "expected_status", "should_complete"),
    [
        ("provider-plan37", "model-plan37", "verified_from_provider_usage", True),
        (None, None, "not_exposed", True),
        ("provider-plan37", "model-other", "rejected", False),
    ],
    ids=("verified", "usage-not-exposed", "usage-model-mismatch"),
)
async def test_creative_entrypoint_applies_one_model_evidence_policy(
    monkeypatch: pytest.MonkeyPatch,
    usage_provider: str | None,
    usage_model: str | None,
    expected_status: str,
    should_complete: bool,
) -> None:
    """The same public-evidence verdict controls candidate persistence."""

    api = import_creative_api(monkeypatch)
    job_id = uuid4()
    complete_calls: list[dict[str, object]] = []
    fail_calls: list[dict[str, object]] = []
    monkeypatch.setattr(api, "_creative_writing_retrieval", _none_retrieval)
    monkeypatch.setattr(
        api,
        "start_creative_generation",
        lambda *_args, **_kwargs: {
            "id": str(job_id),
            "kind": "novel_naming",
            "state": "running",
            "should_execute": True,
            "input_snapshot": {},
        },
    )
    monkeypatch.setattr(api, "build_creative_generation_prompt", lambda _job: "prompt")
    monkeypatch.setattr(api, "ensure_prompt_within_effective_limit", lambda *_: None)

    def complete(_session, received_job_id, **kwargs):
        assert received_job_id == job_id
        complete_calls.append(kwargs)
        return {"id": str(job_id), "state": "ready", **kwargs}

    def fail(_session, received_job_id, **kwargs):
        assert received_job_id == job_id
        fail_calls.append(kwargs)
        return {"id": str(job_id), "state": "failed", **kwargs}

    monkeypatch.setattr(api, "complete_creative_generation", complete)
    monkeypatch.setattr(api, "fail_creative_generation", fail)

    async def chat(*_args, **_kwargs):
        return reply(
            text='{"titles":["消失的档案"]}',
            provider_id=usage_provider,
            model_id=usage_model,
        )

    request = api.StartCreativeGenerationRequest(
        scope_type="novel_creation",
        scope_id=uuid4(),
        kind="novel_naming",
        input_snapshot={},
    )
    if should_complete:
        result = await api.creative_generations_create(
            request,
            ctx=SimpleNamespace(chat=chat),
            configured_model=CONFIGURED_MODEL,
            session=FakeSession(),
        )
        assert result["state"] == "ready"
        assert not fail_calls
        evidence = complete_calls[0]["model_evidence"]
        assert evidence["status"] == expected_status
        if expected_status == "not_exposed":
            assert evidence["reported_actual"] is None
            assert evidence["usage"]["status"] == "not_exposed"
    else:
        with pytest.raises(HTTPException) as captured:
            await api.creative_generations_create(
                request,
                ctx=SimpleNamespace(chat=chat),
                configured_model=CONFIGURED_MODEL,
                session=FakeSession(),
            )
        assert captured.value.status_code == 502
        assert captured.value.detail["type"] == "model_verification_failed"
        assert not complete_calls
        assert fail_calls[0]["model_evidence"]["status"] == expected_status


async def _none_retrieval(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "operation", "use_novel_context", "expected_purpose"),
    [
        ("review", None, False, "chapter_review"),
        ("selection_edit", "rewrite", False, "selection_rewrite"),
        ("selection_edit", "expand", False, "selection_expand"),
        ("selection_edit", "dialogue", False, "selection_dialogue"),
        ("selection_edit", "review", False, "selection_review"),
        ("selection_edit", "polish", False, None),
        ("selection_edit", "shorten", False, None),
        ("selection_edit", "custom", False, None),
        ("selection_edit", "custom", True, "selection_custom"),
    ],
)
async def test_creative_api_uses_the_frozen_retrieval_trigger_matrix(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    operation: str | None,
    use_novel_context: bool,
    expected_purpose: str | None,
) -> None:
    api = import_creative_api(monkeypatch)
    novel_id = uuid4()
    retrieval_calls: list[dict[str, object]] = []

    async def retrieve(_session, **kwargs):
        retrieval_calls.append(kwargs)
        return {"mode": "lexical_only", "hits": []}

    monkeypatch.setattr(api, "retrieve_for_writing", retrieve)
    request = api.StartCreativeGenerationRequest(
        scope_type="novel",
        scope_id=novel_id,
        kind=kind,
        input_snapshot=(
            _selection_snapshot(
                novel_id,
                operation=operation or "review",
                use_novel_context=use_novel_context,
            )
            if kind == "selection_edit"
            else {}
        ),
        novel_id=novel_id,
    )

    result = await api._creative_writing_retrieval(FakeSession(), request)

    if expected_purpose is None:
        assert result is None
        assert retrieval_calls == []
    else:
        assert result == {"mode": "lexical_only", "hits": []}
        assert len(retrieval_calls) == 1
        assert retrieval_calls[0]["purpose"].value == expected_purpose
        assert retrieval_calls[0]["novel_id"] == novel_id


@pytest.mark.asyncio
async def test_chapter_body_creates_candidate_only_after_evidence_and_never_adopts_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body reply reaches candidate completion, not the adoption transaction."""

    app = import_app(monkeypatch)
    document_id = uuid4()
    novel_id = uuid4()
    timeline_id = uuid4()
    job_id = uuid4()
    complete_calls: list[dict[str, object]] = []
    adopt_calls: list[object] = []
    monkeypatch.setattr(
        app,
        "resolve_writing_position",
        lambda *_: SimpleNamespace(
            novel_id=novel_id,
            document_id=document_id,
            title="第一章",
            timeline_id=timeline_id,
            narrative_sequence=1,
            story_sequence_cutoff=1,
        ),
    )
    monkeypatch.setattr(
        app,
        "get_chapter_brief",
        lambda *_: {"outline_text": "车站发现档案", "expectation_text": "建立线索"},
    )

    async def degraded(*_args, **_kwargs):
        return {"mode": "lexical_only", "hits": [], "degraded_reason": "dense_timeout"}

    monkeypatch.setattr(app, "retrieve_for_writing", degraded)
    monkeypatch.setattr(
        app,
        "start_chapter_generation",
        lambda *_args, **kwargs: {
            "id": str(job_id),
            "state": "running",
            "should_execute": True,
            "generation_context_snapshot": {
                "chapter": {"title": "第一章"},
                "writing_retrieval": kwargs["writing_retrieval"],
            },
        },
    )
    monkeypatch.setattr(app, "build_chapter_generation_prompt", lambda *_: "chapter-prompt")
    monkeypatch.setattr(app, "ensure_prompt_within_effective_limit", lambda *_: None)

    def complete(_session, received_job_id, **kwargs):
        assert received_job_id == job_id
        complete_calls.append(kwargs)
        return {"id": str(job_id), "state": "ready", "candidate": {"state": "ready"}}

    monkeypatch.setattr(app, "complete_chapter_generation", complete)
    monkeypatch.setattr(
        app,
        "adopt_candidate",
        lambda *_args, **_kwargs: adopt_calls.append((_args, _kwargs)),
    )

    async def chat(*_args, **_kwargs):
        return reply(text="正文候选", provider_id=None, model_id=None)

    result = await app.generation_jobs_create_body(
        document_id,
        app.GenerateChapterRequest(expected_brief_version=1),
        ctx=SimpleNamespace(chat=chat),
        configured_model=CONFIGURED_MODEL,
        session=FakeSession(),
    )

    assert result["candidate"]["state"] == "ready"
    assert complete_calls[0]["content_markdown"] == "正文候选"
    evidence = complete_calls[0]["model_evidence"]
    assert evidence["status"] == "not_exposed"
    assert evidence["reported_actual"] is None
    assert adopt_calls == []


@pytest.mark.asyncio
async def test_chapter_body_returns_structured_retryable_length_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = import_app(monkeypatch)
    document_id = uuid4()
    novel_id = uuid4()
    timeline_id = uuid4()
    job_id = uuid4()
    monkeypatch.setattr(
        app,
        "resolve_writing_position",
        lambda *_: SimpleNamespace(
            novel_id=novel_id,
            document_id=document_id,
            title="第二章",
            timeline_id=timeline_id,
            narrative_sequence=2,
            story_sequence_cutoff=2,
        ),
    )
    monkeypatch.setattr(
        app,
        "get_chapter_brief",
        lambda *_: {"outline_text": "核对档案", "expectation_text": "召回前文线索"},
    )

    async def degraded(*_args, **_kwargs):
        return {"mode": "lexical_only", "hits": []}

    monkeypatch.setattr(app, "retrieve_for_writing", degraded)
    monkeypatch.setattr(
        app,
        "start_chapter_generation",
        lambda *_args, **_kwargs: {
            "id": str(job_id),
            "state": "running",
            "should_execute": True,
            "generation_context_snapshot": {},
        },
    )
    monkeypatch.setattr(app, "build_chapter_generation_prompt", lambda *_: "prompt")
    monkeypatch.setattr(app, "ensure_prompt_within_effective_limit", lambda *_: None)

    def reject_length(*_args, **_kwargs):
        raise app.ChapterLengthValidationError(
            "正文超过上限",
            validation_state="above_target",
            output_visible_character_count=3387,
            minimum_visible_character_count=1700,
            maximum_visible_character_count=2300,
            requested_visible_character_count=2000,
        )

    failed_job = {
        "id": str(job_id),
        "state": "failed",
        "validation_state": "above_target",
        "output_visible_character_count": 3387,
        "minimum_visible_character_count": 1700,
        "maximum_visible_character_count": 2300,
        "requested_provider_id": CONFIGURED_MODEL.provider_id,
        "requested_model_id": CONFIGURED_MODEL.model_id,
        "actual_provider_id": None,
        "actual_model_id": None,
    }
    monkeypatch.setattr(app, "complete_chapter_generation", reject_length)
    monkeypatch.setattr(app, "fail_chapter_generation", lambda *_args, **_kwargs: failed_job)

    async def chat(*_args, **_kwargs):
        return reply(text="超长正文占位", provider_id=None, model_id=None)

    with pytest.raises(HTTPException) as captured:
        await app.generation_jobs_create_body(
            document_id,
            app.GenerateChapterRequest(expected_brief_version=1, force_new=True),
            ctx=SimpleNamespace(chat=chat),
            configured_model=CONFIGURED_MODEL,
            session=FakeSession(),
        )

    assert captured.value.status_code == 422
    detail = captured.value.detail
    assert detail["type"] == "chapter_length_out_of_range"
    assert detail["direction"] == "above_target"
    assert detail["retryable"] is True
    assert detail["output_visible_character_count"] == 3387
    assert detail["job"] == failed_job
    assert "content_markdown" not in detail


@pytest.mark.asyncio
async def test_intelligence_extraction_yields_proposal_items_but_never_commits_storyfacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = import_app(monkeypatch)
    document_id = uuid4()
    revision_id = uuid4()
    proposal_id = uuid4()
    complete_calls: list[dict[str, object]] = []
    commit_calls: list[object] = []
    monkeypatch.setattr(
        app,
        "start_intelligence_proposal",
        lambda *_args, **_kwargs: {
            "id": str(proposal_id),
            "state": "running",
            "should_execute": True,
        },
    )
    monkeypatch.setattr(app, "build_intelligence_prompt", lambda *_: "fact-prompt")
    monkeypatch.setattr(app, "ensure_prompt_within_effective_limit", lambda *_: None)

    def complete(_session, received_id, **kwargs):
        assert received_id == proposal_id
        complete_calls.append(kwargs)
        return {"id": str(proposal_id), "state": "ready", "items": kwargs["items"]}

    monkeypatch.setattr(app, "complete_intelligence_proposal", complete)
    monkeypatch.setattr(
        app,
        "commit_intelligence_items",
        lambda *_args, **_kwargs: commit_calls.append((_args, _kwargs)),
    )

    async def chat(*_args, **_kwargs):
        return reply(
            text='{"no_changes":true,"items":[]}',
            provider_id=None,
            model_id=None,
        )

    result = await app.intelligence_proposals_create(
        document_id,
        app.ExtractIntelligenceRequest(revision_id=revision_id),
        ctx=SimpleNamespace(chat=chat),
        configured_model=CONFIGURED_MODEL,
        session=FakeSession(),
    )

    assert result == {"id": str(proposal_id), "state": "ready", "items": []}
    assert complete_calls[0]["items"] == []
    assert complete_calls[0]["model_evidence"]["status"] == "not_exposed"
    assert commit_calls == []


def test_candidate_adoption_and_storyfact_commit_require_explicit_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = import_app(monkeypatch)
    candidate_id = uuid4()
    proposal_id = uuid4()
    item_id = uuid4()
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        app,
        "adopt_candidate",
        lambda _session, received_id, **kwargs: calls.append(
            ("adopt", (received_id, kwargs))
        )
        or {"candidate": {"state": "accepted"}},
    )
    monkeypatch.setattr(
        app,
        "commit_intelligence_items",
        lambda _session, received_id, **kwargs: calls.append(
            ("commit", (received_id, kwargs))
        )
        or {"state": "committed"},
    )
    session = FakeSession()

    adopted = app.candidates_adopt(
        candidate_id,
        app.AdoptCandidateRequest(expected_draft_version=3),
        session=session,
    )
    committed = app.intelligence_proposals_commit(
        proposal_id,
        app.CommitIntelligenceRequest(accepted_item_ids=[item_id]),
        session=session,
    )

    assert adopted["candidate"]["state"] == "accepted"
    assert committed["state"] == "committed"
    assert calls == [
        ("adopt", (candidate_id, {"expected_draft_version": 3})),
        (
            "commit",
            (
                proposal_id,
                {
                    "accepted_item_ids": [item_id],
                    "expected_story_ledger_version": None,
                    "operation_key": None,
                },
            ),
        ),
    ]


def test_storyfact_commit_forwards_snapshot_and_stable_operation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = import_app(monkeypatch)
    proposal_id = uuid4()
    item_id = uuid4()
    captured: dict[str, object] = {}

    def commit(_session, received_id, **kwargs):
        captured.update({"proposal_id": received_id, **kwargs})
        return {"state": "accepted"}

    monkeypatch.setattr(app, "commit_intelligence_items", commit)

    result = app.intelligence_proposals_commit(
        proposal_id,
        app.CommitIntelligenceRequest(
            accepted_item_ids=[item_id],
            expected_story_ledger_version=7,
            operation_key="chapter-intel:attempt-7",
        ),
        session=FakeSession(),
    )

    assert result == {"state": "accepted"}
    assert captured == {
        "proposal_id": proposal_id,
        "accepted_item_ids": [item_id],
        "expected_story_ledger_version": 7,
        "operation_key": "chapter-intel:attempt-7",
    }


@pytest.mark.parametrize(
    ("code", "current"),
    [
        ("idempotency_conflict", {}),
        ("story_ledger_version_conflict", {"story_ledger_version": 9}),
    ],
)
def test_storyfact_commit_maps_frozen_conflicts_to_http_409(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    current: dict[str, object],
) -> None:
    app = import_app(monkeypatch)

    def fail(*_args, **_kwargs):
        raise app.IntelligenceCommitConflictError(
            code,
            "commit conflict",
            current=current,
        )

    monkeypatch.setattr(app, "commit_intelligence_items", fail)

    with pytest.raises(HTTPException) as raised:
        app.intelligence_proposals_commit(
            uuid4(),
            app.CommitIntelligenceRequest(
                accepted_item_ids=[uuid4()],
                expected_story_ledger_version=8,
                operation_key="chapter-intel:attempt-8",
            ),
            session=FakeSession(),
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["type"] == code
    if current:
        assert raised.value.detail["current"] == current
