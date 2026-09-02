from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.creative_schemas import CreateRelationshipRequest
from backend.schemas import CommitIntelligenceRequest
from backend.story_ledger.api import router as read_router
from backend.story_state.corrections_api import router as mutation_router


ROOT = Path(__file__).resolve().parents[2]


def _routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for router in (read_router, mutation_router)
        for route in router.routes
        for method in (route.methods or set())
    }


def test_only_canonical_story_ledger_paths_are_registered() -> None:
    routes = _routes()
    canonical = {
        ("GET", "/novels/{novel_id}/story-ledger/summary"),
        ("GET", "/novels/{novel_id}/story-ledger/facts"),
        ("GET", "/novels/{novel_id}/story-ledger/facts/{fact_id}"),
        ("GET", "/novels/{novel_id}/story-ledger/facts/{fact_id}/source"),
        ("GET", "/novels/{novel_id}/story-ledger/facts/{fact_id}/impact-preview"),
        ("GET", "/novels/{novel_id}/story-ledger/batches/{batch_id}/impact-preview"),
        ("POST", "/novels/{novel_id}/story-ledger/facts/{fact_id}/corrections"),
        ("POST", "/novels/{novel_id}/story-ledger/batches/{batch_id}/revert"),
    }
    retired = {
        ("GET", "/novels/{novel_id}/story-facts"),
        ("POST", "/novels/{novel_id}/story-facts/{fact_id}/corrections"),
        (
            "GET",
            "/novels/{novel_id}/intelligence-commit-batches/{batch_id}/revert-impact",
        ),
        (
            "POST",
            "/novels/{novel_id}/intelligence-commit-batches/{batch_id}/revert",
        ),
    }
    assert canonical <= routes
    assert retired.isdisjoint(routes)
    app_source = (ROOT / "backend/app.py").read_text(encoding="utf-8")
    assert '@router.get("/novels/{novel_id}/story-facts")' not in app_source


def test_retired_command_fields_are_rejected_instead_of_translated() -> None:
    item_id = uuid4()
    with pytest.raises(PydanticValidationError):
        CommitIntelligenceRequest.model_validate(
            {
                "accepted_item_ids": [item_id],
                "item_overrides": {str(item_id): {"subject": "旧覆盖"}},
            }
        )

    with pytest.raises(PydanticValidationError):
        CreateRelationshipRequest.model_validate(
            {
                "source_character_id": uuid4(),
                "target_character_id": uuid4(),
                "label": "同盟",
                "relation_type": "同盟",
            }
        )
