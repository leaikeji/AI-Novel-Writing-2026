from __future__ import annotations

import argparse
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.creative_services import (
    create_novel_character,
    get_relationship_auto_sync_status,
    list_character_relationships,
)
from backend.database import get_engine
from backend.models import IntelligenceProposal, Novel, StoryFact
from backend.services import (
    commit_intelligence_items,
    complete_intelligence_proposal,
    create_checkpoint,
    create_novel,
    delete_novel,
    get_document,
    restore_revision,
    save_draft,
    start_intelligence_proposal,
)


def snapshot(session, novel_id: UUID) -> dict[str, object]:
    visible = list_character_relationships(session, novel_id)
    historical = list_character_relationships(session, novel_id, include_archived=True)
    fact_statuses = list(
        session.scalars(
            select(StoryFact.status)
            .where(StoryFact.novel_id == novel_id)
            .order_by(StoryFact.created_at, StoryFact.id)
        )
    )
    status = get_relationship_auto_sync_status(session, novel_id)
    return {
        "visible_relationship_count": len(visible),
        "historical_relationship_count": len(historical),
        "fact_statuses": fact_statuses,
        "ai_relationship_count": status["ai_relationship_count"],
        "manual_relationship_count": status["manual_relationship_count"],
        "current_relationship_fact_count": status["source_summary"]["relationship_facts"],
    }


def create_fixture(session) -> dict[str, object]:
    title = f"验收-关系来源有效性-{uuid4().hex[:8]}"
    novel = create_novel(session, title)
    novel_id = UUID(novel["id"])
    document_id = UUID(novel["tree"][0]["documents"][0]["id"])
    source = create_novel_character(
        session,
        novel_id,
        role_type="main",
        name="苏晚",
        description="旧电台修复师",
        details={},
    )
    target = create_novel_character(
        session,
        novel_id,
        role_type="supporting",
        name="陆沉舟",
        description="灯塔维护工程师",
        details={},
    )
    relationship_text = "苏晚与陆沉舟约定共同调查旧电台档案。"
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=1,
        content_markdown=relationship_text,
    )
    revision = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )["revision"]
    proposal = start_intelligence_proposal(
        session,
        document_id,
        revision_id=UUID(revision["id"]),
        execution_agent_id="ai-novel-writer",
        requested_provider_id="local-audit",
        requested_model_id="deterministic-browser-audit",
        generation_contract_version="browser-audit-v1",
    )
    proposal_row = session.get(IntelligenceProposal, UUID(proposal["id"]))
    if proposal_row is None:
        raise RuntimeError("audit proposal was not persisted")
    character_key_by_id = {
        value["character_id"]: key
        for key, value in proposal_row.extraction_context_json["character_catalog"].items()
    }
    proposal = complete_intelligence_proposal(
        session,
        UUID(proposal["id"]),
        items=[
            {
                "fact_type": "relationship_state",
                "source_character_key": character_key_by_id[source["id"]],
                "target_character_key": character_key_by_id[target["id"]],
                "directionality": "undirected",
                "relation_kind": "ally",
                "relationship_label": "调查同盟",
                "dimension": "alliance",
                "event_kind": "formed",
                "subject": "苏晚与陆沉舟",
                "predicate": "结成同盟",
                "object": "共同调查旧电台档案",
                "source_text": relationship_text,
                "reasoning_summary": "形成稳定协作关系",
                "confidence": 93,
                "details": {},
            }
        ],
        actual_model_id="deterministic-browser-audit",
        actual_provider_id="local-audit",
    )
    committed = commit_intelligence_items(
        session,
        UUID(proposal["id"]),
        accepted_item_ids=[UUID(proposal["items"][0]["id"])],
    )
    return {
        "phase": "created",
        "title": title,
        "novel_id": str(novel_id),
        "document_id": str(document_id),
        "source_revision_id": revision["id"],
        "relationship_sync": committed["relationship_sync"],
        **snapshot(session, novel_id),
    }


def invalidate_fixture(session, novel_id: UUID, document_id: UUID) -> dict[str, object]:
    current = get_document(session, document_id)
    saved = save_draft(
        session,
        document_id,
        expected_draft_version=current["draft_version"],
        content_markdown="苏晚独自整理旧电台档案。",
    )
    before_checkpoint = snapshot(session, novel_id)
    checkpoint = create_checkpoint(
        session,
        document_id,
        expected_draft_version=saved["draft_version"],
    )
    return {
        "phase": "invalidated",
        "before_checkpoint": before_checkpoint,
        "new_revision_id": checkpoint["revision"]["id"],
        **snapshot(session, novel_id),
    }


def restore_fixture(
    session, novel_id: UUID, document_id: UUID, source_revision_id: UUID
) -> dict[str, object]:
    current = get_document(session, document_id)
    restored = restore_revision(
        session,
        document_id,
        source_revision_id,
        expected_draft_version=current["draft_version"],
    )
    return {
        "phase": "restored",
        "restored_revision_id": restored["revision"]["id"],
        **snapshot(session, novel_id),
    }


def delete_fixture(session, novel_id: UUID, expected_title: str) -> dict[str, object]:
    novel = session.get(Novel, novel_id)
    if novel is None or novel.title != expected_title or not expected_title.startswith(
        "验收-关系来源有效性-"
    ):
        raise RuntimeError("refusing to delete a non-audit novel")
    delete_novel(session, novel_id, expected_version=novel.version)
    remaining = int(
        session.scalar(select(func.count(Novel.id)).where(Novel.id == novel_id)) or 0
    )
    return {"phase": "deleted", "novel_id": str(novel_id), "remaining": remaining}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=("create", "invalidate", "restore", "check", "list", "delete")
    )
    parser.add_argument("--novel-id")
    parser.add_argument("--document-id")
    parser.add_argument("--source-revision-id")
    parser.add_argument("--title")
    args = parser.parse_args()
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        if args.phase == "create":
            result = create_fixture(session)
        elif args.phase == "invalidate":
            result = invalidate_fixture(
                session, UUID(args.novel_id), UUID(args.document_id)
            )
        elif args.phase == "restore":
            result = restore_fixture(
                session,
                UUID(args.novel_id),
                UUID(args.document_id),
                UUID(args.source_revision_id),
            )
        elif args.phase == "check":
            result = {"phase": "checked", **snapshot(session, UUID(args.novel_id))}
        elif args.phase == "list":
            rows = list(
                session.execute(
                    select(Novel.id, Novel.title)
                    .where(Novel.title.like("验收-关系来源有效性-%"))
                    .order_by(Novel.created_at, Novel.id)
                )
            )
            result = {
                "phase": "listed",
                "novels": [{"id": str(novel_id), "title": title} for novel_id, title in rows],
            }
        else:
            result = delete_fixture(session, UUID(args.novel_id), args.title)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
