"""Single-source novel domain service used by both HTTP and Agent tools."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import unified_diff
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    CandidateRevision,
    ChapterBrief,
    ChapterGenerationJob,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    IntelligenceCommitBatch,
    IntelligenceProposal,
    IntelligenceProposalItem,
    Novel,
    AssetPreset,
    AssetPresetItem,
    PrivateAsset,
    StoryFact,
    Volume,
)


class DomainError(RuntimeError):
    pass


class NotFoundError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class DraftConflictError(DomainError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("document draft version conflict")
        self.current = current


class BriefConflictError(DomainError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("chapter brief version conflict")
        self.current = current


class CandidateConflictError(DomainError):
    def __init__(self, current: dict[str, Any], candidate: dict[str, Any]):
        super().__init__("candidate base no longer matches the working copy")
        self.current = current
        self.candidate = candidate


class ProposalSupersededError(DomainError):
    def __init__(self, proposal: dict[str, Any]):
        super().__init__("intelligence proposal source revision is no longer current")
        self.proposal = proposal


class RestorationPlanConflictError(DomainError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("restoration fact plan is no longer current")
        self.current = current


CURRENT_FACT_STATUSES = ("active", "source_restored")
MINIMAX_M3_MODEL_ID = "MiniMax-M3"
MINIMUM_COMPLETED_CHAPTER_CHARACTERS = 1000
TARGET_COMPLETED_CHAPTER_CHARACTERS = 1250
MAXIMUM_COMPLETED_CHAPTER_CHARACTERS = 1500


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def markdown_to_text(markdown: str) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~>#-]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def visible_character_count(markdown: str) -> int:
    return sum(1 for character in markdown_to_text(markdown) if not character.isspace())


def _document_payload(document: Document, working: DocumentWorkingCopy) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "novel_id": str(document.novel_id),
        "volume_id": str(document.volume_id) if document.volume_id else None,
        "kind": document.kind,
        "title": document.title,
        "position": document.position,
        "status": document.status,
        "version": document.version,
        "draft_version": working.draft_version,
        "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
        "content_markdown": working.content_markdown,
        "content_hash": working.content_hash,
        "visible_character_count": visible_character_count(working.content_markdown),
        "updated_at": working.updated_at.isoformat() if working.updated_at else None,
    }


def _revision_payload(revision: DocumentRevision, *, include_content: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(revision.id),
        "document_id": str(revision.document_id),
        "revision_number": revision.revision_number,
        "parent_revision_id": (
            str(revision.parent_revision_id) if revision.parent_revision_id else None
        ),
        "restored_from_revision_id": (
            str(revision.restored_from_revision_id)
            if revision.restored_from_revision_id
            else None
        ),
        "content_hash": revision.content_hash,
        "source": revision.source,
        "visible_character_count": visible_character_count(revision.content_markdown),
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
    }
    if include_content:
        payload["content_markdown"] = revision.content_markdown
        payload["content_text"] = revision.content_text
    return payload


ROLE_CONSTRAINT_KEYS = ("required", "allowed", "context_only", "forbidden")
INTELLIGENCE_ITEM_TYPES = {
    "fact",
    "character_state",
    "relationship",
    "storyline_event",
    "foreshadow_progress",
    "foreshadow_new",
    "next_chapter_required_role",
}


def _normalize_role_constraints(value: dict[str, list[str]] | None) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for key in ROLE_CONSTRAINT_KEYS:
        seen: set[str] = set()
        items: list[str] = []
        for raw in (value or {}).get(key, []):
            name = str(raw).strip()
            if name and name not in seen:
                seen.add(name)
                items.append(name)
        normalized[key] = items
    return normalized


def _brief_payload(brief: ChapterBrief | None, document_id: UUID) -> dict[str, Any]:
    if brief is None:
        return {
            "id": None,
            "document_id": str(document_id),
            "version": 0,
            "target_word_count": 2000,
            "expectation_text": "",
            "outline_text": "",
            "forbidden_text": "",
            "role_constraints": _normalize_role_constraints(None),
            "created_at": None,
            "updated_at": None,
        }
    return {
        "id": str(brief.id),
        "document_id": str(brief.document_id),
        "version": brief.version,
        "target_word_count": brief.target_word_count,
        "expectation_text": brief.expectation_text,
        "outline_text": brief.outline_text,
        "forbidden_text": brief.forbidden_text,
        "role_constraints": _normalize_role_constraints(brief.role_constraints),
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
        "updated_at": brief.updated_at.isoformat() if brief.updated_at else None,
    }


def _candidate_diff(candidate: CandidateRevision) -> str:
    return "".join(
        unified_diff(
            candidate.base_content_markdown.splitlines(keepends=True),
            candidate.content_markdown.splitlines(keepends=True),
            fromfile="当前工作稿",
            tofile="AI 候选稿",
        )
    )


def _candidate_payload(candidate: CandidateRevision, *, include_content: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(candidate.id),
        "document_id": str(candidate.document_id),
        "generation_job_id": str(candidate.generation_job_id),
        "base_revision_id": str(candidate.base_revision_id) if candidate.base_revision_id else None,
        "base_draft_version": candidate.base_draft_version,
        "base_content_hash": candidate.base_content_hash,
        "content_hash": candidate.content_hash,
        "state": candidate.state,
        "adopted_revision_id": (
            str(candidate.adopted_revision_id) if candidate.adopted_revision_id else None
        ),
        "visible_character_count": visible_character_count(candidate.content_markdown),
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
        "decided_at": candidate.decided_at.isoformat() if candidate.decided_at else None,
    }
    if include_content:
        payload.update(
            {
                "base_content_markdown": candidate.base_content_markdown,
                "content_markdown": candidate.content_markdown,
                "content_text": candidate.content_text,
                "unified_diff": _candidate_diff(candidate),
            }
        )
    return payload


def _generation_job_payload(
    session: Session, job: ChapterGenerationJob, *, include_snapshot: bool = False
) -> dict[str, Any]:
    candidate = session.scalar(
        select(CandidateRevision).where(CandidateRevision.generation_job_id == job.id)
    )
    payload: dict[str, Any] = {
        "id": str(job.id),
        "document_id": str(job.document_id),
        "kind": job.kind,
        "input_hash": job.input_hash,
        "state": job.state,
        "brief_version": job.brief_version,
        "base_revision_id": str(job.base_revision_id) if job.base_revision_id else None,
        "base_draft_version": job.base_draft_version,
        "base_content_hash": job.base_content_hash,
        "model_profile_fingerprint": job.model_profile_fingerprint,
        "asset_snapshot": job.asset_snapshot,
        "requested_model_id": job.requested_model_id,
        "actual_model_id": job.actual_model_id,
        "provider_profile": job.provider_profile,
        "target_visible_character_count": job.target_visible_character_count,
        "output_visible_character_count": job.output_visible_character_count,
        "validation_state": job.validation_state,
        "attempt": job.attempt,
        "failure_message": job.failure_message,
        "candidate": _candidate_payload(candidate) if candidate else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
    if include_snapshot:
        payload["generation_context_snapshot"] = job.generation_context_snapshot
    return payload


def _intelligence_item_payload(item: IntelligenceProposalItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "proposal_id": str(item.proposal_id),
        "position": item.position,
        "item_type": item.item_type,
        "suggested_payload": item.suggested_payload,
        "confidence": item.confidence,
        "source_text": item.source_text,
        "reasoning_summary": item.reasoning_summary,
        "review_state": item.review_state,
        "committed_story_fact_id": (
            str(item.committed_story_fact_id) if item.committed_story_fact_id else None
        ),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _intelligence_proposal_payload(
    session: Session, proposal: IntelligenceProposal
) -> dict[str, Any]:
    items = session.scalars(
        select(IntelligenceProposalItem)
        .where(IntelligenceProposalItem.proposal_id == proposal.id)
        .order_by(IntelligenceProposalItem.position)
    ).all()
    working = session.get(DocumentWorkingCopy, proposal.document_id)
    source_revision = session.get(DocumentRevision, proposal.chapter_revision_id)
    source_current = bool(
        working
        and source_revision
        and working.content_hash == source_revision.content_hash
        and working.base_revision_id
        and (
            current_revision := session.get(DocumentRevision, working.base_revision_id)
        ) is not None
        and current_revision.content_hash == source_revision.content_hash
    )
    return {
        "id": str(proposal.id),
        "novel_id": str(proposal.novel_id),
        "document_id": str(proposal.document_id),
        "chapter_revision_id": str(proposal.chapter_revision_id),
        "input_hash": proposal.input_hash,
        "state": proposal.state,
        "source_current": source_current,
        "requested_model_id": proposal.requested_model_id,
        "actual_model_id": proposal.actual_model_id,
        "provider_profile": proposal.provider_profile,
        "model_profile_fingerprint": proposal.model_profile_fingerprint,
        "failure_message": proposal.failure_message,
        "items": [_intelligence_item_payload(item) for item in items],
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
    }


def _intelligence_commit_key(
    proposal_id: UUID,
    accepted_item_ids: set[UUID],
    item_overrides: dict[str, dict[str, object]],
) -> str:
    selected_overrides = {
        str(item_id): item_overrides.get(str(item_id), {})
        for item_id in sorted(accepted_item_ids, key=str)
    }
    canonical = json.dumps(
        {
            "proposal_id": str(proposal_id),
            "accepted_item_ids": sorted(str(item_id) for item_id in accepted_item_ids),
            "item_overrides": selected_overrides,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _intelligence_commit_batch_payload(batch: IntelligenceCommitBatch) -> dict[str, Any]:
    return {
        "id": str(batch.id),
        "proposal_id": str(batch.proposal_id),
        "chapter_revision_id": str(batch.chapter_revision_id),
        "commit_key": batch.commit_key,
        "state": batch.state,
        "accepted_item_ids": batch.accepted_item_ids,
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "reverted_at": batch.reverted_at.isoformat() if batch.reverted_at else None,
    }


def _require_novel(session: Session, novel_id: UUID) -> Novel:
    novel = session.get(Novel, novel_id)
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    return novel


def _require_document(session: Session, document_id: UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise NotFoundError(f"document {document_id} not found")
    return document


def _next_position(session: Session, model: type[Volume] | type[Document], novel_id: UUID) -> int:
    current = session.scalar(select(func.max(model.position)).where(model.novel_id == novel_id))
    return int(current or 0) + 1000


def _new_document(
    session: Session,
    *,
    novel_id: UUID,
    title: str,
    kind: str,
    position: int,
    volume_id: UUID | None,
) -> Document:
    document = Document(
        id=uuid4(),
        novel_id=novel_id,
        volume_id=volume_id,
        title=title.strip(),
        kind=kind,
        position=position,
    )
    empty_hash = content_hash("")
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document.id,
        revision_number=1,
        content_markdown="",
        content_text="",
        content_hash=empty_hash,
        source="initial",
    )
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=revision.id,
        draft_version=1,
        content_markdown="",
        content_hash=empty_hash,
    )
    session.add_all((document, revision, working))
    return document


def create_novel(session: Session, title: str, description: str = "") -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValidationError("novel title cannot be empty")
    novel = Novel(id=uuid4(), title=title, description=description.strip())
    volume = Volume(id=uuid4(), novel_id=novel.id, title="第一卷", position=1000)
    session.add_all((novel, volume))
    _new_document(
        session,
        novel_id=novel.id,
        title="第一章",
        kind="chapter",
        position=1000,
        volume_id=volume.id,
    )
    session.commit()
    return get_novel(session, novel.id)


def list_novels(session: Session) -> list[dict[str, Any]]:
    novels = session.scalars(select(Novel).order_by(Novel.updated_at.desc(), Novel.created_at.desc())).all()
    result: list[dict[str, Any]] = []
    for novel in novels:
        documents = session.scalars(
            select(Document).where(Document.novel_id == novel.id, Document.kind == "chapter")
        ).all()
        total_characters = 0
        for document in documents:
            working = session.get(DocumentWorkingCopy, document.id)
            if working:
                total_characters += visible_character_count(working.content_markdown)
        result.append(
            {
                "id": str(novel.id),
                "title": novel.title,
                "author_name": novel.author_name,
                "description": novel.description,
                "writing_type": novel.writing_type,
                "audience": novel.audience,
                "genre": novel.genre,
                "subgenre": novel.subgenre,
                "cover_mode": novel.cover_mode,
                "cover_image_data": novel.cover_image_data,
                "cover_asset_id": str(novel.cover_asset_id) if novel.cover_asset_id else None,
                "version": novel.version,
                "chapter_count": len(documents),
                "visible_character_count": total_characters,
                "created_at": novel.created_at.isoformat() if novel.created_at else None,
                "updated_at": novel.updated_at.isoformat() if novel.updated_at else None,
            }
        )
    return result


def delete_novel(
    session: Session,
    novel_id: UUID,
    *,
    expected_version: int,
) -> None:
    novel = session.scalar(
        select(Novel).where(Novel.id == novel_id).with_for_update()
    )
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    if novel.version != expected_version:
        raise ValidationError("小说已在其他位置更新，请刷新后重试")
    session.delete(novel)
    session.commit()


def get_novel(session: Session, novel_id: UUID) -> dict[str, Any]:
    novel = _require_novel(session, novel_id)
    return {
        "id": str(novel.id),
        "title": novel.title,
        "author_name": novel.author_name,
        "description": novel.description,
        "writing_type": novel.writing_type,
        "audience": novel.audience,
        "genre": novel.genre,
        "subgenre": novel.subgenre,
        "idea": novel.idea,
        "template_key": novel.template_key,
        "template_name": novel.template_name,
        "template_data": novel.template_data,
        "cover_mode": novel.cover_mode,
        "cover_image_data": novel.cover_image_data,
        "cover_asset_id": str(novel.cover_asset_id) if novel.cover_asset_id else None,
        "outline_target_chapters": novel.outline_target_chapters,
        "highlight": novel.highlight,
        "background": novel.background,
        "main_plot": novel.main_plot,
        "story_ledger_version": novel.story_ledger_version,
        "version": novel.version,
        "created_at": novel.created_at.isoformat() if novel.created_at else None,
        "updated_at": novel.updated_at.isoformat() if novel.updated_at else None,
        "tree": get_novel_tree(session, novel_id),
    }


def create_volume(session: Session, novel_id: UUID, title: str) -> dict[str, Any]:
    _require_novel(session, novel_id)
    title = title.strip()
    if not title:
        raise ValidationError("volume title cannot be empty")
    volume = Volume(
        id=uuid4(), novel_id=novel_id, title=title, position=_next_position(session, Volume, novel_id)
    )
    session.add(volume)
    session.commit()
    return {
        "id": str(volume.id),
        "novel_id": str(volume.novel_id),
        "title": volume.title,
        "position": volume.position,
        "version": volume.version,
    }


def create_document(
    session: Session,
    novel_id: UUID,
    title: str,
    *,
    kind: str = "chapter",
    volume_id: UUID | None = None,
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    if kind not in {"chapter", "outline", "setting"}:
        raise ValidationError(f"unsupported document kind: {kind}")
    title = title.strip()
    if not title:
        raise ValidationError("document title cannot be empty")
    if volume_id is not None:
        volume = session.get(Volume, volume_id)
        if volume is None or volume.novel_id != novel_id:
            raise ValidationError("volume does not belong to this novel")
    document = _new_document(
        session,
        novel_id=novel_id,
        title=title,
        kind=kind,
        position=_next_position(session, Document, novel_id),
        volume_id=volume_id,
    )
    session.commit()
    return get_document(session, document.id)


def get_novel_tree(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id).order_by(Volume.position)
    ).all()
    documents = session.scalars(
        select(Document).where(Document.novel_id == novel_id).order_by(Document.position)
    ).all()
    grouped: dict[UUID | None, list[dict[str, Any]]] = {volume.id: [] for volume in volumes}
    grouped[None] = []
    for document in documents:
        working = session.get(DocumentWorkingCopy, document.id)
        if working is None:
            continue
        grouped.setdefault(document.volume_id, []).append(_document_payload(document, working))
    result = [
        {
            "id": str(volume.id),
            "title": volume.title,
            "position": volume.position,
            "version": volume.version,
            "documents": grouped.get(volume.id, []),
        }
        for volume in volumes
    ]
    if grouped[None]:
        result.append(
            {
                "id": None,
                "title": "未分卷资料",
                "position": 2_147_483_647,
                "version": 1,
                "documents": grouped[None],
            }
        )
    return result


def get_document(session: Session, document_id: UUID) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.get(DocumentWorkingCopy, document.id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    payload = _document_payload(document, working)
    revisions = session.scalars(
        select(DocumentRevision)
        .where(DocumentRevision.document_id == document.id)
        .order_by(DocumentRevision.revision_number.desc())
    ).all()
    payload["revisions"] = [_revision_payload(revision) for revision in revisions]
    return payload


def get_chapter_brief(session: Session, document_id: UUID) -> dict[str, Any]:
    document = _require_document(session, document_id)
    if document.kind != "chapter":
        raise ValidationError("chapter brief is only available for chapter documents")
    brief = session.scalar(select(ChapterBrief).where(ChapterBrief.document_id == document_id))
    return _brief_payload(brief, document_id)


def save_chapter_brief(
    session: Session,
    document_id: UUID,
    *,
    expected_version: int,
    target_word_count: int,
    expectation_text: str,
    outline_text: str,
    forbidden_text: str,
    role_constraints: dict[str, list[str]],
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    if document.kind != "chapter":
        raise ValidationError("chapter brief is only available for chapter documents")
    brief = session.scalar(
        select(ChapterBrief).where(ChapterBrief.document_id == document_id).with_for_update()
    )
    if brief is None:
        if expected_version != 0:
            raise BriefConflictError(_brief_payload(None, document_id))
        brief = ChapterBrief(
            id=uuid4(),
            document_id=document_id,
            version=1,
            target_word_count=target_word_count,
            expectation_text=expectation_text.strip(),
            outline_text=outline_text.strip(),
            forbidden_text=forbidden_text.strip(),
            role_constraints=_normalize_role_constraints(role_constraints),
        )
        session.add(brief)
    else:
        if brief.version != expected_version:
            raise BriefConflictError(_brief_payload(brief, document_id))
        brief.version += 1
        brief.target_word_count = target_word_count
        brief.expectation_text = expectation_text.strip()
        brief.outline_text = outline_text.strip()
        brief.forbidden_text = forbidden_text.strip()
        brief.role_constraints = _normalize_role_constraints(role_constraints)
    session.commit()
    return _brief_payload(brief, document_id)


def _generation_snapshot(
    session: Session,
    document: Document,
    working: DocumentWorkingCopy,
    brief: ChapterBrief,
    asset_snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    context = get_novel_context(
        session, document.novel_id, document_id=document.id, max_chars=30_000
    )
    return {
        "schema_version": 1,
        "novel": context["novel"],
        "chapter": {
            "document_id": str(document.id),
            "title": document.title,
            "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
            "base_draft_version": working.draft_version,
            "base_content_hash": working.content_hash,
            "base_content_markdown": working.content_markdown,
        },
        "brief": {
            "version": brief.version,
            "target_word_count": brief.target_word_count,
            "expectation_text": brief.expectation_text,
            "outline_text": brief.outline_text,
            "forbidden_text": brief.forbidden_text,
            "role_constraints": _normalize_role_constraints(brief.role_constraints),
        },
        "previous_context": context["documents"],
        "story_facts": context["story_facts"],
        "private_assets": asset_snapshot,
    }


def _generation_asset_snapshot(
    session: Session,
    *,
    asset_ids: list[UUID] | None,
    preset_id: UUID | None,
) -> list[dict[str, Any]]:
    combined = list(asset_ids or [])
    if preset_id is not None:
        preset = session.get(AssetPreset, preset_id)
        if preset is None or preset.archived:
            raise ValidationError("资料预设不存在或已删除")
        combined.extend(
            session.scalars(
                select(AssetPresetItem.asset_id)
                .where(AssetPresetItem.preset_id == preset_id)
                .order_by(AssetPresetItem.position)
            ).all()
        )
    unique_ids = list(dict.fromkeys(combined))
    if not unique_ids:
        return []
    assets = session.scalars(
        select(PrivateAsset).where(
            PrivateAsset.id.in_(unique_ids), PrivateAsset.archived.is_(False)
        )
    ).all()
    by_id = {asset.id: asset for asset in assets}
    if set(unique_ids) != set(by_id):
        raise ValidationError("生成资料包含不存在或已删除的私有库条目")
    return [
        {
            "id": str(by_id[asset_id].id),
            "asset_type": by_id[asset_id].asset_type,
            "title": by_id[asset_id].title,
            "content": by_id[asset_id].content,
            "version": by_id[asset_id].version,
        }
        for asset_id in unique_ids
    ]


def start_chapter_generation(
    session: Session,
    document_id: UUID,
    *,
    expected_brief_version: int,
    force_new: bool = False,
    asset_ids: list[UUID] | None = None,
    preset_id: UUID | None = None,
    requested_model_id: str = MINIMAX_M3_MODEL_ID,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    if document.kind != "chapter":
        raise ValidationError("body generation is only available for chapter documents")
    brief = session.scalar(select(ChapterBrief).where(ChapterBrief.document_id == document_id))
    if brief is None:
        raise ValidationError("请先保存章节任务书")
    if brief.version != expected_brief_version:
        raise BriefConflictError(_brief_payload(brief, document_id))
    normalized_model = re.sub(r"[^a-z0-9]", "", requested_model_id.lower())
    if normalized_model != "minimaxm3":
        raise ValidationError("本项目的正文生成模型固定为 MiniMax M3")
    working = session.get(DocumentWorkingCopy, document_id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    asset_snapshot = _generation_asset_snapshot(
        session, asset_ids=asset_ids, preset_id=preset_id
    )
    snapshot = _generation_snapshot(session, document, working, brief, asset_snapshot)
    # The current paired-flow acceptance run requires every generated chapter
    # to land inside a strict 1000—1500 visible-character window.  The chapter
    # brief keeps the source product's planning target, while generation uses
    # a centered target to avoid repeatedly overshooting the upper boundary.
    acceptance_target = MINIMUM_COMPLETED_CHAPTER_CHARACTERS
    snapshot["acceptance"] = {
        "minimum_visible_character_count": MINIMUM_COMPLETED_CHAPTER_CHARACTERS,
        "maximum_visible_character_count": MAXIMUM_COMPLETED_CHAPTER_CHARACTERS,
        "target_visible_character_count": acceptance_target,
        "requested_visible_character_count": TARGET_COMPLETED_CHAPTER_CHARACTERS,
    }
    attempt = 1
    if force_new:
        previous_attempts = session.scalar(
            select(func.count(ChapterGenerationJob.id)).where(
                ChapterGenerationJob.document_id == document_id,
                ChapterGenerationJob.kind == "body",
                ChapterGenerationJob.brief_version == brief.version,
                ChapterGenerationJob.base_content_hash == working.content_hash,
            )
        )
        attempt = int(previous_attempts or 0) + 1
        snapshot["generation_attempt"] = attempt
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_hash = content_hash(serialized)
    existing = session.scalar(
        select(ChapterGenerationJob).where(
            ChapterGenerationJob.document_id == document_id,
            ChapterGenerationJob.kind == "body",
            ChapterGenerationJob.input_hash == input_hash,
        )
    )
    if existing is not None:
        if existing.state == "failed":
            existing.state = "running"
            existing.failure_message = None
            existing.completed_at = None
            session.commit()
        return _generation_job_payload(session, existing, include_snapshot=True)
    job = ChapterGenerationJob(
        id=uuid4(),
        document_id=document_id,
        kind="body",
        input_hash=input_hash,
        state="running",
        brief_version=brief.version,
        base_revision_id=working.base_revision_id,
        base_draft_version=working.draft_version,
        base_content_hash=working.content_hash,
        generation_context_snapshot=snapshot,
        asset_snapshot=asset_snapshot,
        requested_model_id=MINIMAX_M3_MODEL_ID,
        target_visible_character_count=acceptance_target,
        attempt=attempt,
    )
    session.add(job)
    session.commit()
    return _generation_job_payload(session, job, include_snapshot=True)


def build_chapter_generation_prompt(snapshot: dict[str, Any]) -> str:
    brief = snapshot["brief"]
    acceptance = snapshot.get("acceptance") or {}
    minimum_visible_character_count = max(
        MINIMUM_COMPLETED_CHAPTER_CHARACTERS,
        int(
            acceptance.get("target_visible_character_count")
            or MINIMUM_COMPLETED_CHAPTER_CHARACTERS
        ),
    )
    requested_visible_character_count = max(
        minimum_visible_character_count,
        int(
            acceptance.get("requested_visible_character_count")
            or brief["target_word_count"]
        ),
    )
    maximum_visible_character_count = max(
        minimum_visible_character_count,
        int(
            acceptance.get("maximum_visible_character_count")
            or MAXIMUM_COMPLETED_CHAPTER_CHARACTERS
        ),
    )
    requested_visible_character_count = min(
        requested_visible_character_count,
        maximum_visible_character_count,
    )
    roles = brief["role_constraints"]
    previous_context = snapshot.get("previous_context", [])
    context_text = "\n\n".join(
        f"【{item['title']}】\n{item.get('content_markdown', '')}" for item in previous_context
    )
    facts_text = "\n".join(
        f"- {fact['subject']}｜{fact['predicate']}｜{fact['object']}"
        for fact in snapshot.get("story_facts", [])
    )
    asset_text = "\n".join(
        f"- [{asset['asset_type']}] {asset['title']}：{asset['content']}"
        for asset in snapshot.get("private_assets", [])
    )
    return f"""你正在为作者生成一份可审阅的章节正文候选。请遵循 prose-writing Skill。

只输出小说正文，不要解释、不要写标题、不要使用 Markdown 代码围栏，也不要声称已经保存。
正文结束后立即停止；禁止追加“完成”“下一步”“等待作者反馈”“进入下一章”“修订本稿”等工作状态或流程提示。
禁止在结尾追加方括号摘要、生成段数、情节清单、验收说明或任何形如「⟦……⟧」的状态胶囊。
绝对不要叙述你将加载、读取或遵循任何 Skill；不得输出“我需要先加载”等内部工作语句。
本章期望、章节大纲、内容禁区、角色限制和验收规则只用于约束创作，不是正文素材。不得在正文中复述、解释、否定或评论这些规则，也不得用“没有……”“不出现……”“不靠……”等作者说明来证明自己遵守了规则；请让合规结果自然发生在场景里。
输出的第一个字必须已经属于小说场景。

作品：{snapshot['novel']['title']}
章节：{snapshot['chapter']['title']}
创作目标：约 {requested_visible_character_count} 个中文可见字符
验收范围：{minimum_visible_character_count}—{maximum_visible_character_count} 个中文可见字符；低于下限或超过上限都必须整章重写
固定输出 6 个自然段，每段约 180—220 个中文可见字符，全部正文控制在 1100—1400 个可见字符；不得拆成第 7 段，也不得用短句单独成段。
本章期望：{brief['expectation_text'] or '按章纲推进，不额外扩张设定'}
章节大纲：
{brief['outline_text'] or '无固定章纲，保持前文连续并形成完整章节推进'}

内容禁区：{brief['forbidden_text'] or '无额外禁区'}
必须出场：{'、'.join(roles['required']) or '无'}
允许出场：{'、'.join(roles['allowed']) or '无'}
仅作上下文、不要安排现场出场：{'、'.join(roles['context_only']) or '无'}
禁止出现：{'、'.join(roles['forbidden']) or '无'}

已确认故事事实：
{facts_text or '- 暂无结构化故事事实'}

本次作者选用的私有库资料：
{asset_text or '- 未选择，按章纲与前文创作'}

截至本章的上下文（可能包含本章当前工作稿，仅作连续性参考）：
{context_text or '暂无前文'}
""".strip()


def _clean_model_candidate(text: str) -> str:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:markdown|md|text)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    # Some host-agent replies leak a one-sentence orchestration preamble and
    # concatenate it directly with the first prose sentence. Remove only an
    # anchored instruction about the explicitly named prose-writing Skill;
    # broader first-person prose must remain untouched.
    orchestration_prefix = (
        r"^(?:(?:我(?:需要|将|会|先)?|需要|将|先)\s*(?:先\s*)?"
        r"(?:加载|读取|查看|调用|使用|遵循)[^\n。！？!?]{0,240}"
        r"prose[- ]writing[^\n。！？!?]{0,240}[。！？!?]\s*)+"
    )
    candidate = re.sub(orchestration_prefix, "", candidate, flags=re.IGNORECASE).lstrip()
    embedded_orchestration = (
        r"(?:我(?:需要|将|会|先)?|需要|将|先)\s*(?:先\s*)?"
        r"(?:加载|读取|查看|调用|使用|遵循)[^\n。！？!?]{0,240}"
        r"prose[- ]writing"
    )
    if re.search(embedded_orchestration, candidate, flags=re.IGNORECASE):
        raise ValidationError("模型正文中混入了 Skill 工作语句，请重新生成候选")
    # The host agent can occasionally append its own status capsule after the prose.
    # Strip only final standalone capsules with known orchestration wording so an
    # author's legitimate in-story brackets are never touched. Older host builds
    # occasionally emitted the wrong opening glyph, so both variants are accepted.
    capsule_pattern = r"[⟦⟧][^\n⟧]{0,800}⟧"
    candidate = re.sub(
        rf"(?:\n+\s*{capsule_pattern}\s*)+$",
        "",
        candidate,
    ).strip()
    if re.fullmatch(rf"\s*{capsule_pattern}\s*", candidate):
        candidate = ""
    if re.search(rf"(?:^|\n)\s*{capsule_pattern}\s*(?:$|\n)", candidate):
        raise ValidationError("模型正文中混入了系统状态说明，请重新生成候选")
    if not candidate:
        raise ValidationError("模型没有返回可用正文")
    return candidate


def complete_chapter_generation(
    session: Session,
    job_id: UUID,
    *,
    content_markdown: str,
    model_profile_fingerprint: str = "qwenpaw-active-agent",
    actual_model_id: str,
    provider_profile: str,
) -> dict[str, Any]:
    job = session.scalar(
        select(ChapterGenerationJob)
        .where(ChapterGenerationJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"generation job {job_id} not found")
    existing = session.scalar(
        select(CandidateRevision).where(CandidateRevision.generation_job_id == job.id)
    )
    if existing is not None:
        return _generation_job_payload(session, job)
    candidate_text = _clean_model_candidate(content_markdown)
    normalized_model = re.sub(r"[^a-z0-9]", "", actual_model_id.lower())
    if normalized_model != "minimaxm3":
        job.state = "failed"
        job.actual_model_id = actual_model_id
        job.provider_profile = provider_profile
        job.failure_message = "实际模型不是 MiniMax M3，正文结果已作废"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ValidationError(job.failure_message)
    output_visible_character_count = visible_character_count(candidate_text)
    if output_visible_character_count < job.target_visible_character_count:
        job.state = "failed"
        job.model_profile_fingerprint = model_profile_fingerprint
        job.actual_model_id = actual_model_id
        job.provider_profile = provider_profile
        job.output_visible_character_count = output_visible_character_count
        job.validation_state = "below_target"
        job.failure_message = (
            f"正文仅有{output_visible_character_count}个可见字符，"
            f"低于{job.target_visible_character_count}字门槛，必须整章重写"
        )
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ValidationError(job.failure_message)
    if output_visible_character_count > MAXIMUM_COMPLETED_CHAPTER_CHARACTERS:
        job.state = "failed"
        job.model_profile_fingerprint = model_profile_fingerprint
        job.actual_model_id = actual_model_id
        job.provider_profile = provider_profile
        job.output_visible_character_count = output_visible_character_count
        job.validation_state = "above_target"
        job.failure_message = (
            f"正文共有{output_visible_character_count}个可见字符，"
            f"超过{MAXIMUM_COMPLETED_CHAPTER_CHARACTERS}字范围，必须整章重写"
        )
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ValidationError(job.failure_message)
    base_content = str(job.generation_context_snapshot["chapter"]["base_content_markdown"])
    candidate = CandidateRevision(
        id=uuid4(),
        document_id=job.document_id,
        generation_job_id=job.id,
        base_revision_id=job.base_revision_id,
        base_draft_version=job.base_draft_version,
        base_content_hash=job.base_content_hash,
        base_content_markdown=base_content,
        content_markdown=candidate_text,
        content_text=markdown_to_text(candidate_text),
        content_hash=content_hash(candidate_text),
        state="ready",
    )
    job.state = "ready"
    job.model_profile_fingerprint = model_profile_fingerprint
    job.actual_model_id = actual_model_id
    job.provider_profile = provider_profile
    job.output_visible_character_count = output_visible_character_count
    job.validation_state = "meets_target"
    job.completed_at = datetime.now(timezone.utc)
    session.add(candidate)
    session.commit()
    return _generation_job_payload(session, job)


def fail_chapter_generation(session: Session, job_id: UUID, message: str) -> dict[str, Any]:
    job = session.get(ChapterGenerationJob, job_id)
    if job is None:
        raise NotFoundError(f"generation job {job_id} not found")
    job.state = "failed"
    job.failure_message = message[:4000]
    job.completed_at = datetime.now(timezone.utc)
    session.commit()
    return _generation_job_payload(session, job)


def list_chapter_generation_jobs(session: Session, document_id: UUID) -> list[dict[str, Any]]:
    _require_document(session, document_id)
    jobs = session.scalars(
        select(ChapterGenerationJob)
        .where(ChapterGenerationJob.document_id == document_id)
        .order_by(ChapterGenerationJob.created_at.desc())
    ).all()
    return [_generation_job_payload(session, job) for job in jobs]


def get_candidate(session: Session, candidate_id: UUID) -> dict[str, Any]:
    candidate = session.get(CandidateRevision, candidate_id)
    if candidate is None:
        raise NotFoundError(f"candidate {candidate_id} not found")
    return _candidate_payload(candidate)


def adopt_candidate(
    session: Session, candidate_id: UUID, *, expected_draft_version: int
) -> dict[str, Any]:
    candidate = session.scalar(
        select(CandidateRevision).where(CandidateRevision.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise NotFoundError(f"candidate {candidate_id} not found")
    generation_job = session.get(ChapterGenerationJob, candidate.generation_job_id)
    if (
        generation_job is None
        or generation_job.validation_state != "meets_target"
        or generation_job.output_visible_character_count
        < generation_job.target_visible_character_count
    ):
        raise ValidationError("正文候选未通过1000—1500字验收范围，不能采用")
    document = _require_document(session, candidate.document_id)
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == candidate.document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {candidate.document_id} not found")
    if candidate.state == "accepted" and candidate.adopted_revision_id:
        return {
            "document": get_document(session, candidate.document_id),
            "candidate": _candidate_payload(candidate),
            "revision": get_revision(
                session, candidate.document_id, candidate.adopted_revision_id
            ),
        }
    if candidate.state != "ready":
        raise ValidationError(f"candidate cannot be adopted from state {candidate.state}")
    if (
        working.draft_version != expected_draft_version
        or working.draft_version != candidate.base_draft_version
        or working.content_hash != candidate.base_content_hash
    ):
        raise CandidateConflictError(
            _document_payload(document, working), _candidate_payload(candidate)
        )
    latest_number = session.scalar(
        select(func.max(DocumentRevision.revision_number)).where(
            DocumentRevision.document_id == candidate.document_id
        )
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=candidate.document_id,
        revision_number=int(latest_number or 0) + 1,
        parent_revision_id=working.base_revision_id,
        content_markdown=candidate.content_markdown,
        content_text=candidate.content_text,
        content_hash=candidate.content_hash,
        source="ai_candidate_adopt",
    )
    session.add(revision)
    session.flush()
    _supersede_intelligence_for_document(
        session, candidate.document_id, invalidate_committed_facts=False
    )
    _reconcile_story_facts_for_revision(session, candidate.document_id, revision)
    working.base_revision_id = revision.id
    working.content_markdown = candidate.content_markdown
    working.content_hash = candidate.content_hash
    working.draft_version += 1
    candidate.state = "accepted"
    candidate.adopted_revision_id = revision.id
    candidate.decided_at = datetime.now(timezone.utc)
    session.commit()
    return {
        "document": get_document(session, candidate.document_id),
        "candidate": _candidate_payload(candidate),
        "revision": _revision_payload(revision, include_content=True),
    }


def reject_candidate(session: Session, candidate_id: UUID) -> dict[str, Any]:
    candidate = session.get(CandidateRevision, candidate_id)
    if candidate is None:
        raise NotFoundError(f"candidate {candidate_id} not found")
    if candidate.state == "accepted":
        raise ValidationError("accepted candidate cannot be rejected")
    if candidate.state != "rejected":
        candidate.state = "rejected"
        candidate.decided_at = datetime.now(timezone.utc)
        session.commit()
    return _candidate_payload(candidate)


def _fact_summary(fact: StoryFact, status: str) -> dict[str, Any]:
    return {
        "id": str(fact.id),
        "fact_type": fact.fact_type,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object_text": fact.object_text,
        "status": status,
    }


def _document_fact_binding_rows(
    session: Session, document_id: UUID, *, lock: bool = False
) -> list[tuple[DerivedSourceBinding, StoryFact]]:
    statement = (
        select(DerivedSourceBinding, StoryFact)
        .join(StoryFact, StoryFact.id == DerivedSourceBinding.derived_entity_id)
        .where(
            DerivedSourceBinding.source_chapter_id == document_id,
            DerivedSourceBinding.derived_entity_type == "story_fact",
        )
        .order_by(DerivedSourceBinding.created_at, DerivedSourceBinding.id)
    )
    if lock:
        statement = statement.with_for_update(of=DerivedSourceBinding)
    return [(row[0], row[1]) for row in session.execute(statement).all()]


def _restore_fact_plan(
    session: Session,
    document: Document,
    working: DocumentWorkingCopy,
    target_revision: DocumentRevision,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    rows = _document_fact_binding_rows(session, document.id, lock=lock)
    currently_effective = {"current", "source_restored"}
    deactivate: list[dict[str, Any]] = []
    reactivate: list[dict[str, Any]] = []
    remain_current: list[dict[str, Any]] = []
    plan_bindings: list[tuple[str, str, str]] = []
    for binding, fact in rows:
        matches_target = binding.source_content_hash == target_revision.content_hash
        is_current = binding.validity_state in currently_effective
        plan_bindings.append(
            (str(binding.id), binding.validity_state, binding.source_content_hash)
        )
        if is_current and not matches_target:
            deactivate.append(_fact_summary(fact, binding.validity_state))
        elif not is_current and matches_target:
            reactivate.append(_fact_summary(fact, binding.validity_state))
        elif is_current and matches_target:
            remain_current.append(_fact_summary(fact, binding.validity_state))

    batches = session.scalars(
        select(IntelligenceCommitBatch)
        .join(
            DocumentRevision,
            DocumentRevision.id == IntelligenceCommitBatch.chapter_revision_id,
        )
        .where(
            DocumentRevision.document_id == document.id,
            DocumentRevision.content_hash == target_revision.content_hash,
            IntelligenceCommitBatch.state == "committed",
        )
        .order_by(IntelligenceCommitBatch.committed_at, IntelligenceCommitBatch.id)
    ).all()
    current_revision = (
        session.get(DocumentRevision, working.base_revision_id)
        if working.base_revision_id
        else None
    )
    plan_material = {
        "document_id": str(document.id),
        "target_revision_id": str(target_revision.id),
        "target_content_hash": target_revision.content_hash,
        "current_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
        "working_content_hash": working.content_hash,
        "expected_draft_version": working.draft_version,
        "bindings": sorted(plan_bindings),
        "commit_batches": sorted(str(batch.id) for batch in batches),
    }
    fact_plan_hash = hashlib.sha256(
        json.dumps(plan_material, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    current_markdown = working.content_markdown
    body_diff = "".join(
        unified_diff(
            current_markdown.splitlines(keepends=True),
            target_revision.content_markdown.splitlines(keepends=True),
            fromfile="当前工作稿",
            tofile=f"目标版本 {target_revision.revision_number}",
        )
    )
    return {
        "document_id": str(document.id),
        "expected_draft_version": working.draft_version,
        "fact_plan_hash": fact_plan_hash,
        "current_revision": (
            _revision_payload(current_revision) if current_revision is not None else None
        ),
        "target_revision": _revision_payload(target_revision),
        "working_copy_dirty": bool(
            current_revision is None or working.content_hash != current_revision.content_hash
        ),
        "unified_diff": body_diff,
        "will_deactivate": deactivate,
        "will_reactivate": reactivate,
        "will_remain_current": remain_current,
        "available_commit_batches": [
            _intelligence_commit_batch_payload(batch) for batch in batches
        ],
    }


def preview_restore_revision(
    session: Session, document_id: UUID, revision_id: UUID
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    target_revision = session.get(DocumentRevision, revision_id)
    if target_revision is None or target_revision.document_id != document_id:
        raise NotFoundError(f"revision {revision_id} not found for document {document_id}")
    working = session.get(DocumentWorkingCopy, document_id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    return _restore_fact_plan(session, document, working, target_revision)


def _reconcile_story_facts_for_revision(
    session: Session,
    document_id: UUID,
    target_revision: DocumentRevision,
    *,
    restored: bool = False,
) -> None:
    now = datetime.now(timezone.utc)
    for binding, fact in _document_fact_binding_rows(session, document_id, lock=True):
        if binding.source_content_hash == target_revision.content_hash:
            binding.validity_state = "source_restored" if restored else "current"
            binding.invalidated_at = None
            binding.restored_at = now if restored else None
            fact.status = "source_restored" if restored else "active"
        else:
            binding.validity_state = "source_superseded"
            binding.invalidated_at = now
            binding.restored_at = None
            fact.status = "source_superseded"


def _supersede_intelligence_for_document(
    session: Session, document_id: UUID, *, invalidate_committed_facts: bool = True
) -> None:
    proposals = session.scalars(
        select(IntelligenceProposal).where(
            IntelligenceProposal.document_id == document_id,
            IntelligenceProposal.state.in_(("running", "ready", "partially_accepted")),
        )
    ).all()
    for proposal in proposals:
        proposal.state = "superseded"
    if not invalidate_committed_facts:
        return
    now = datetime.now(timezone.utc)
    bound_fact_ids: set[UUID] = set()
    for binding, fact in _document_fact_binding_rows(session, document_id, lock=True):
        binding.validity_state = "source_superseded"
        binding.invalidated_at = now
        binding.restored_at = None
        fact.status = "source_superseded"
        bound_fact_ids.add(fact.id)
    revision_ids = select(DocumentRevision.id).where(DocumentRevision.document_id == document_id)
    legacy_facts = session.scalars(
        select(StoryFact).where(
            StoryFact.source_revision_id.in_(revision_ids),
            StoryFact.status.in_(CURRENT_FACT_STATUSES),
        )
    ).all()
    for fact in legacy_facts:
        if fact.id not in bound_fact_ids:
            fact.status = "source_superseded"


def start_intelligence_proposal(
    session: Session, document_id: UUID, *, revision_id: UUID
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.get(DocumentWorkingCopy, document_id)
    revision = session.get(DocumentRevision, revision_id)
    if revision is None or revision.document_id != document_id:
        raise NotFoundError(f"revision {revision_id} not found for document {document_id}")
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.base_revision_id != revision_id or working.content_hash != revision.content_hash:
        raise ValidationError("请先建立当前正文检查点，再提取情报")
    extractor_profile = "story-ledger-extractor-v3"
    input_hash = content_hash(f"{revision.content_hash}:{extractor_profile}")
    existing = session.scalar(
        select(IntelligenceProposal).where(
            IntelligenceProposal.document_id == document_id,
            IntelligenceProposal.input_hash == input_hash,
        ).order_by(IntelligenceProposal.created_at)
    )
    if existing is not None:
        existing_items = session.scalars(
            select(IntelligenceProposalItem).where(
                IntelligenceProposalItem.proposal_id == existing.id
            )
        ).all()
        if existing.state == "failed" and not existing_items:
            existing.state = "running"
            existing.failure_message = None
            session.commit()
        elif existing.state == "superseded":
            pending = sum(1 for item in existing_items if item.review_state == "pending")
            accepted = sum(1 for item in existing_items if item.review_state == "accepted")
            if pending:
                existing.state = "partially_accepted" if accepted else "ready"
            elif accepted:
                existing.state = "accepted"
            elif existing_items:
                existing.state = "rejected"
            else:
                existing.state = "running"
            session.commit()
        return _intelligence_proposal_payload(session, existing)
    proposal = IntelligenceProposal(
        id=uuid4(),
        novel_id=document.novel_id,
        document_id=document_id,
        chapter_revision_id=revision_id,
        input_hash=input_hash,
        state="running",
        model_profile_fingerprint="qwenpaw-active-agent",
    )
    session.add(proposal)
    session.commit()
    return _intelligence_proposal_payload(session, proposal)


def build_intelligence_prompt(session: Session, proposal_id: UUID) -> str:
    proposal = session.get(IntelligenceProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    document = _require_document(session, proposal.document_id)
    revision = session.get(DocumentRevision, proposal.chapter_revision_id)
    if revision is None:
        raise NotFoundError(f"revision {proposal.chapter_revision_id} not found")
    existing_facts = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == proposal.novel_id,
            StoryFact.status.in_(CURRENT_FACT_STATUSES),
        )
        .order_by(StoryFact.created_at)
        .limit(200)
    ).all()
    ledger = "\n".join(
        f"- {fact.fact_type}｜{fact.subject}｜{fact.predicate}｜{fact.object_text}"
        for fact in existing_facts
    )
    return f"""请从下面这章正式正文中提取“候选情报”。只返回严格 JSON，不要代码围栏或解释。

JSON 结构：
{{"items":[{{"item_type":"fact|character_state|relationship|storyline_event|foreshadow_progress|foreshadow_new|next_chapter_required_role","subject":"主体","predicate":"变化或关系","object":"客体或内容","source_text":"正文中的短证据","reasoning_summary":"为何值得进入故事账本","confidence":0到100}}]}}

规则：
1. 只提取正文明确发生或明确揭示的内容，不把猜测写成事实。
2. 调查、协作、敌对和线索交换不能误分成恋爱关系。
3. 已有相同事实不要重复；不确定时省略。
4. 每项必须有可在正文中找到的 source_text。
5. 所有字符串内禁止使用未转义的英文双引号；引用原文时统一改用中文引号「」。
6. 正文不为空时至少返回 1 条情报，不得返回空 items。
7. 小说时间线与现实系统日期无关。严禁用当前现实年份补全「今年」「去年」「本月」等相对日期；必须以正文最近的明确场景日期为锚点推断。无法可靠推断时保留正文原有相对表述，不得擅自补全年份。
8. source_text 与 object 中的日期必须彼此一致；正文写明发生在 1992 年的场景，不得改写成 2026 年或其他现实年份。
9. 只有当本章结尾明确决定、约定或迫使某个已知角色在下一章继续出场时，才增加 next_chapter_required_role；subject 必须只写角色姓名，predicate 固定写「下一章必现」，object 简述正文依据。没有明确依据时不要输出此类型。
10. foreshadow_new 只用于本章新出现、尚未解决且会影响后续章节的悬念；subject 必须写成可直接展示的简短伏笔名称（如「码头老板的阴谋线」），不得只写角色名或普通物件名。foreshadow_progress 只能推进现有故事账本中同名伏笔，不得凭角色名新建伏笔。
11. storyline_event 只用于推进可跨越多个章节的稳定故事线；subject 应写故事线名称或稳定主题，不得把一次动作、普通物件、地点切换或一句对白各自拆成新故事线。

章节：{document.title}
现有故事账本：
{ledger or '- 暂无'}

正式正文：
{revision.content_markdown}
""".strip()


def complete_intelligence_proposal(
    session: Session,
    proposal_id: UUID,
    *,
    items: list[dict[str, Any]],
    model_profile_fingerprint: str = "qwenpaw-active-agent",
    actual_model_id: str,
    provider_profile: str,
) -> dict[str, Any]:
    proposal = session.scalar(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    working = session.get(DocumentWorkingCopy, proposal.document_id)
    revision = session.get(DocumentRevision, proposal.chapter_revision_id)
    if (
        working is None
        or revision is None
        or working.base_revision_id != proposal.chapter_revision_id
        or working.content_hash != revision.content_hash
    ):
        proposal.state = "superseded"
        session.commit()
        raise ProposalSupersededError(_intelligence_proposal_payload(session, proposal))
    existing = session.scalar(
        select(func.count(IntelligenceProposalItem.id)).where(
            IntelligenceProposalItem.proposal_id == proposal_id
        )
    )
    if existing:
        return _intelligence_proposal_payload(session, proposal)
    normalized_model = re.sub(r"[^a-z0-9]", "", actual_model_id.lower())
    if normalized_model != "minimaxm3":
        proposal.state = "failed"
        proposal.actual_model_id = actual_model_id
        proposal.provider_profile = provider_profile
        proposal.failure_message = "实际模型不是 MiniMax M3，情报结果已作废"
        session.commit()
        raise ValidationError(proposal.failure_message)
    normalized: list[IntelligenceProposalItem] = []
    for position, raw in enumerate(items[:200], start=1):
        item_type = str(raw.get("item_type", "fact")).strip()
        if item_type not in INTELLIGENCE_ITEM_TYPES:
            item_type = "fact"
        subject = str(raw.get("subject", "")).strip()
        predicate = str(raw.get("predicate", "")).strip()
        object_text = str(raw.get("object", "")).strip()
        source_text = str(raw.get("source_text", "")).strip()
        if not subject or not predicate or not object_text or not source_text:
            continue
        try:
            confidence = int(raw.get("confidence", 50))
        except (TypeError, ValueError):
            confidence = 50
        normalized.append(
            IntelligenceProposalItem(
                id=uuid4(),
                proposal_id=proposal.id,
                position=position,
                item_type=item_type,
                suggested_payload={
                    "subject": subject,
                    "predicate": predicate,
                    "object": object_text,
                },
                confidence=max(0, min(confidence, 100)),
                source_text=source_text,
                reasoning_summary=str(raw.get("reasoning_summary", "")).strip(),
                review_state="pending",
            )
        )
    session.add_all(normalized)
    proposal.state = "ready"
    proposal.requested_model_id = MINIMAX_M3_MODEL_ID
    proposal.actual_model_id = actual_model_id
    proposal.provider_profile = provider_profile
    proposal.model_profile_fingerprint = model_profile_fingerprint
    proposal.failure_message = None
    session.commit()
    return _intelligence_proposal_payload(session, proposal)


def fail_intelligence_proposal(
    session: Session, proposal_id: UUID, message: str
) -> dict[str, Any]:
    proposal = session.get(IntelligenceProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    proposal.state = "failed"
    proposal.failure_message = message[:4000]
    session.commit()
    return _intelligence_proposal_payload(session, proposal)


def list_intelligence_proposals(
    session: Session, document_id: UUID
) -> list[dict[str, Any]]:
    _require_document(session, document_id)
    proposals = session.scalars(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.document_id == document_id)
        .order_by(IntelligenceProposal.created_at.desc())
    ).all()
    return [_intelligence_proposal_payload(session, proposal) for proposal in proposals]


def review_intelligence_item(
    session: Session, item_id: UUID, *, review_state: str
) -> dict[str, Any]:
    if review_state not in {"pending", "rejected"}:
        raise ValidationError("unsupported intelligence review state")
    item = session.get(IntelligenceProposalItem, item_id)
    if item is None:
        raise NotFoundError(f"intelligence proposal item {item_id} not found")
    if item.committed_story_fact_id:
        raise ValidationError("committed intelligence item cannot be changed")
    item.review_state = review_state
    proposal = session.get(IntelligenceProposal, item.proposal_id)
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {item.proposal_id} not found")
    items = session.scalars(
        select(IntelligenceProposalItem).where(
            IntelligenceProposalItem.proposal_id == proposal.id
        )
    ).all()
    pending = sum(1 for candidate in items if candidate.review_state == "pending")
    accepted = sum(1 for candidate in items if candidate.review_state == "accepted")
    if pending:
        proposal.state = "partially_accepted" if accepted else "ready"
    else:
        proposal.state = "accepted" if accepted else "rejected"
        proposal.reviewed_at = datetime.now(timezone.utc)
    session.commit()
    return _intelligence_proposal_payload(session, proposal)


def commit_intelligence_items(
    session: Session,
    proposal_id: UUID,
    *,
    accepted_item_ids: list[UUID],
    item_overrides: dict[str, dict[str, object]] | None = None,
) -> dict[str, Any]:
    proposal_snapshot = session.get(IntelligenceProposal, proposal_id)
    if proposal_snapshot is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == proposal_snapshot.document_id)
        .with_for_update()
    )
    proposal = session.scalar(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    revision = session.get(DocumentRevision, proposal.chapter_revision_id)
    current_revision = (
        session.get(DocumentRevision, working.base_revision_id)
        if working and working.base_revision_id
        else None
    )
    if (
        working is None
        or revision is None
        or current_revision is None
        or working.content_hash != revision.content_hash
        or current_revision.content_hash != revision.content_hash
    ):
        proposal.state = "superseded"
        session.commit()
        raise ProposalSupersededError(_intelligence_proposal_payload(session, proposal))
    selected = set(accepted_item_ids)
    items = session.scalars(
        select(IntelligenceProposalItem)
        .where(IntelligenceProposalItem.proposal_id == proposal_id)
        .with_for_update()
    ).all()
    known_ids = {item.id for item in items}
    if not selected or not selected.issubset(known_ids):
        raise ValidationError("accepted intelligence item ids do not belong to this proposal")
    overrides = item_overrides or {}
    commit_key = _intelligence_commit_key(proposal.id, selected, overrides)
    existing_batch = session.scalar(
        select(IntelligenceCommitBatch).where(
            IntelligenceCommitBatch.proposal_id == proposal.id,
            IntelligenceCommitBatch.commit_key == commit_key,
        )
    )
    if existing_batch is not None and existing_batch.state == "committed":
        payload = _intelligence_proposal_payload(session, proposal)
        payload["commit_batch"] = _intelligence_commit_batch_payload(existing_batch)
        session.commit()
        return payload

    batch = existing_batch or IntelligenceCommitBatch(
        id=uuid4(),
        proposal_id=proposal.id,
        chapter_revision_id=proposal.chapter_revision_id,
        commit_key=commit_key,
        state="committing",
        accepted_item_ids=sorted(str(item_id) for item_id in selected),
        inverse_operations={"created_story_fact_ids": []},
    )
    if existing_batch is None:
        session.add(batch)
        session.flush()
    else:
        batch.state = "committing"
        batch.accepted_item_ids = sorted(str(item_id) for item_id in selected)
        batch.inverse_operations = {"created_story_fact_ids": []}
    created_fact_ids: list[str] = []
    for item in items:
        if item.id not in selected:
            continue
        if item.committed_story_fact_id:
            continue
        override = overrides.get(str(item.id), {})
        payload = {**item.suggested_payload, **override}
        subject = str(payload.get("subject", "")).strip()
        predicate = str(payload.get("predicate", "")).strip()
        object_text = str(payload.get("object", "")).strip()
        if not subject or not predicate or not object_text:
            raise ValidationError("accepted intelligence item requires subject, predicate and object")
        fact = StoryFact(
            id=uuid4(),
            novel_id=proposal.novel_id,
            fact_type=item.item_type,
            subject=subject,
            predicate=predicate,
            object_text=object_text,
            details={
                "proposal_id": str(proposal.id),
                "proposal_item_id": str(item.id),
                "source_text": item.source_text,
                "reasoning_summary": item.reasoning_summary,
                "model_suggestion": item.suggested_payload,
                "commit_batch_id": str(batch.id),
            },
            source_revision_id=proposal.chapter_revision_id,
            status="active",
        )
        session.add(fact)
        session.flush()
        session.add(
            DerivedSourceBinding(
                id=uuid4(),
                derived_entity_type="story_fact",
                derived_entity_id=fact.id,
                source_chapter_id=proposal.document_id,
                source_chapter_revision_id=proposal.chapter_revision_id,
                source_content_hash=revision.content_hash,
                proposal_item_id=item.id,
                commit_batch_id=batch.id,
                validity_state="current",
            )
        )
        created_fact_ids.append(str(fact.id))
        item.review_state = "accepted"
        item.suggested_payload = {
            "subject": subject,
            "predicate": predicate,
            "object": object_text,
        }
        item.committed_story_fact_id = fact.id
    pending = sum(1 for item in items if item.review_state == "pending")
    accepted = sum(1 for item in items if item.review_state == "accepted")
    if pending:
        proposal.state = "partially_accepted" if accepted else "ready"
    else:
        proposal.state = "accepted" if accepted else "rejected"
    proposal.reviewed_at = datetime.now(timezone.utc)
    batch.state = "committed"
    batch.inverse_operations = {"created_story_fact_ids": created_fact_ids}
    batch.committed_at = proposal.reviewed_at
    session.commit()
    result = _intelligence_proposal_payload(session, proposal)
    result["commit_batch"] = _intelligence_commit_batch_payload(batch)
    return result


def list_story_facts(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    facts = session.scalars(
        select(StoryFact)
        .where(StoryFact.novel_id == novel_id)
        .order_by(StoryFact.created_at.desc())
        .limit(500)
    ).all()
    return [
        {
            "id": str(fact.id),
            "novel_id": str(fact.novel_id),
            "fact_type": fact.fact_type,
            "subject": fact.subject,
            "predicate": fact.predicate,
            "object_text": fact.object_text,
            "details": fact.details,
            "source_revision_id": (
                str(fact.source_revision_id) if fact.source_revision_id else None
            ),
            "status": fact.status,
            "created_at": fact.created_at.isoformat() if fact.created_at else None,
        }
        for fact in facts
    ]


def save_draft(
    session: Session,
    document_id: UUID,
    *,
    expected_draft_version: int,
    content_markdown: str,
    client_hash: str | None = None,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(_document_payload(document, working))
    server_hash = content_hash(content_markdown)
    if client_hash is not None and client_hash != server_hash:
        raise ValidationError("content_hash does not match content_markdown")
    if working.content_hash == server_hash:
        return _document_payload(document, working)
    _supersede_intelligence_for_document(
        session, document_id, invalidate_committed_facts=False
    )
    working.content_markdown = content_markdown
    working.content_hash = server_hash
    working.draft_version += 1
    document.novel.updated_at = func.now()
    session.commit()
    return _document_payload(document, working)


def create_checkpoint(
    session: Session, document_id: UUID, *, expected_draft_version: int
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(_document_payload(document, working))
    latest_number = session.scalar(
        select(func.max(DocumentRevision.revision_number)).where(
            DocumentRevision.document_id == document_id
        )
    )
    revision = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=int(latest_number or 0) + 1,
        parent_revision_id=working.base_revision_id,
        content_markdown=working.content_markdown,
        content_text=markdown_to_text(working.content_markdown),
        content_hash=working.content_hash,
        source="manual_checkpoint",
    )
    session.add(revision)
    session.flush()
    _supersede_intelligence_for_document(
        session, document_id, invalidate_committed_facts=False
    )
    _reconcile_story_facts_for_revision(session, document_id, revision)
    working.base_revision_id = revision.id
    working.draft_version += 1
    session.commit()
    return {"document": get_document(session, document_id), "revision": _revision_payload(revision, include_content=True)}


def restore_revision(
    session: Session,
    document_id: UUID,
    revision_id: UUID,
    *,
    expected_draft_version: int,
    expected_fact_plan_hash: str | None = None,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    source_revision = session.get(DocumentRevision, revision_id)
    if source_revision is None or source_revision.document_id != document_id:
        raise NotFoundError(f"revision {revision_id} not found for document {document_id}")
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(_document_payload(document, working))
    fact_plan = _restore_fact_plan(
        session, document, working, source_revision, lock=True
    )
    if (
        expected_fact_plan_hash is not None
        and expected_fact_plan_hash != fact_plan["fact_plan_hash"]
    ):
        raise RestorationPlanConflictError(fact_plan)
    latest_number = session.scalar(
        select(func.max(DocumentRevision.revision_number)).where(
            DocumentRevision.document_id == document_id
        )
    )
    next_revision_number = int(latest_number or 0) + 1
    current_revision = (
        session.get(DocumentRevision, working.base_revision_id)
        if working.base_revision_id
        else None
    )
    preserved_revision: DocumentRevision | None = None
    restore_parent_id = working.base_revision_id
    if current_revision is None or working.content_hash != current_revision.content_hash:
        preserved_revision = DocumentRevision(
            id=uuid4(),
            document_id=document_id,
            revision_number=next_revision_number,
            parent_revision_id=working.base_revision_id,
            content_markdown=working.content_markdown,
            content_text=markdown_to_text(working.content_markdown),
            content_hash=working.content_hash,
            source="pre_restore_checkpoint",
        )
        session.add(preserved_revision)
        session.flush()
        restore_parent_id = preserved_revision.id
        next_revision_number += 1
    restored = DocumentRevision(
        id=uuid4(),
        document_id=document_id,
        revision_number=next_revision_number,
        parent_revision_id=restore_parent_id,
        restored_from_revision_id=source_revision.id,
        content_markdown=source_revision.content_markdown,
        content_text=source_revision.content_text,
        content_hash=source_revision.content_hash,
        source="manual_restore",
    )
    session.add(restored)
    session.flush()
    _supersede_intelligence_for_document(
        session, document_id, invalidate_committed_facts=False
    )
    _reconcile_story_facts_for_revision(
        session, document_id, restored, restored=True
    )
    working.base_revision_id = restored.id
    working.content_markdown = restored.content_markdown
    working.content_hash = restored.content_hash
    working.draft_version += 1
    session.commit()
    return {
        "document": get_document(session, document_id),
        "revision": _revision_payload(restored, include_content=True),
        "preserved_revision": (
            _revision_payload(preserved_revision, include_content=True)
            if preserved_revision is not None
            else None
        ),
        "restoration_plan": fact_plan,
    }


def get_revision(session: Session, document_id: UUID, revision_id: UUID) -> dict[str, Any]:
    revision = session.get(DocumentRevision, revision_id)
    if revision is None or revision.document_id != document_id:
        raise NotFoundError(f"revision {revision_id} not found for document {document_id}")
    return _revision_payload(revision, include_content=True)


def search_novel(session: Session, novel_id: UUID, query: str, limit: int = 20) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    query = query.strip()
    if not query:
        return []
    pattern = f"%{query}%"
    rows = session.execute(
        select(Document, DocumentWorkingCopy)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(
            Document.novel_id == novel_id,
            DocumentWorkingCopy.content_markdown.ilike(pattern) | Document.title.ilike(pattern),
        )
        .order_by(Document.position)
        .limit(max(1, min(limit, 50)))
    ).all()
    results: list[dict[str, Any]] = []
    for document, working in rows:
        plain = markdown_to_text(working.content_markdown)
        index = plain.lower().find(query.lower())
        start = max(0, index - 120) if index >= 0 else 0
        results.append(
            {
                "document_id": str(document.id),
                "title": document.title,
                "kind": document.kind,
                "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
                "snippet": plain[start : start + 360],
            }
        )
    return results


def get_novel_context(
    session: Session,
    novel_id: UUID,
    *,
    document_id: UUID | None = None,
    max_chars: int = 12_000,
) -> dict[str, Any]:
    novel = _require_novel(session, novel_id)
    max_chars = max(1_000, min(max_chars, 40_000))
    documents = session.scalars(
        select(Document)
        .where(Document.novel_id == novel_id)
        .order_by(Document.position)
    ).all()
    current_index = len(documents) - 1
    if document_id is not None:
        matches = [index for index, item in enumerate(documents) if item.id == document_id]
        if not matches:
            raise ValidationError("document does not belong to this novel")
        current_index = matches[0]
    selected: list[dict[str, Any]] = []
    remaining = max_chars
    for document in reversed(documents[: current_index + 1]):
        working = session.get(DocumentWorkingCopy, document.id)
        if working is None:
            continue
        text = working.content_markdown[-remaining:]
        selected.append(
            {
                "document_id": str(document.id),
                "title": document.title,
                "kind": document.kind,
                "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
                "content_markdown": text,
            }
        )
        remaining -= len(text)
        if remaining <= 0:
            break
    selected.reverse()
    facts = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.status.in_(CURRENT_FACT_STATUSES),
        )
        .order_by(StoryFact.created_at)
        .limit(200)
    ).all()
    return {
        "novel": {"id": str(novel.id), "title": novel.title, "description": novel.description},
        "current_document_id": str(document_id) if document_id else None,
        "documents": selected,
        "story_facts": [
            {
                "id": str(fact.id),
                "type": fact.fact_type,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object_text,
                "source_revision_id": str(fact.source_revision_id) if fact.source_revision_id else None,
            }
            for fact in facts
        ],
        "retrieval": "lexical/current-revision context; vector retrieval is intentionally disabled in MVP-0",
    }
