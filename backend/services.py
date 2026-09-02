"""Single-source novel domain service used by both HTTP and Agent tools."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from difflib import unified_diff
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .context_v3_loader import assemble_context_from_db
from .context_v4 import RetrievalPurpose as ContextRetrievalPurpose
from .context_v4_loader import assemble_writing_context_from_db
from .embedding.writing import WritingPosition
from .creative_data_models import (
    CharacterInstance,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from .story_state import StoryFactV2
from .private_library import (
    DirectAssetSelection,
    UsagePolicy,
    build_generation_asset_snapshot,
)

from .generation_runtime import (
    CHAPTER_GENERATION_STALE_GRACE_SECONDS,
    CHAPTER_GENERATION_TIMEOUT_SECONDS,
)
from .model_execution import ModelEvidencePolicyError, candidate_actual_identity

from .models import (
    CandidateRevision,
    ChapterBrief,
    ChapterGenerationJob,
    CharacterRelationship,
    CharacterRelationshipRevision,
    DerivedSourceBinding,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    IntelligenceCommitBatch,
    IntelligenceProposal,
    IntelligenceProposalItem,
    Novel,
    NovelCharacter,
    Foreshadow,
    AssetPreset,
    AssetPresetItem,
    PrivateAsset,
    StoryFact,
    Storyline,
    Volume,
)
from .relationship_contracts import (
    RELATIONSHIP_DIRECTIONALITIES,
    RELATIONSHIP_KINDS,
    canonical_relationship_endpoints,
    normalize_relationship_label,
    relationship_pair_key,
)
from .story_state.persistence import ensure_default_story_state
from .volume_chapter_titles import (
    VolumeChapterContractError,
    canonical_tree,
    context_chapter_title,
    display_chapter_title,
    semantic_title,
)


logger = logging.getLogger(__name__)


class DomainError(RuntimeError):
    pass


class NotFoundError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class ChapterLengthValidationError(ValidationError):
    """Structured length rejection for a complete, untruncated model reply."""

    def __init__(
        self,
        message: str,
        *,
        validation_state: str,
        output_visible_character_count: int,
        minimum_visible_character_count: int,
        maximum_visible_character_count: int,
        requested_visible_character_count: int,
    ) -> None:
        super().__init__(message)
        self.validation_state = validation_state
        self.error_code = f"chapter_length_{validation_state.removesuffix('_target')}"
        self.output_visible_character_count = output_visible_character_count
        self.minimum_visible_character_count = minimum_visible_character_count
        self.maximum_visible_character_count = maximum_visible_character_count
        self.requested_visible_character_count = requested_visible_character_count


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


class IntelligenceCommitConflictError(DomainError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        current: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = dict(current or {})


class RestorationPlanConflictError(DomainError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("restoration fact plan is no longer current")
        self.current = current


def _mark_active_novel_index_outdated(session: Session, novel_id: UUID) -> None:
    """Record a recoverable semantic-index gap after authority already committed."""

    from .creative_data_models import (
        EmbeddingConfiguration,
        EmbeddingGenerationNovel,
    )

    novel = session.get(Novel, novel_id)
    if novel is None:
        session.commit()
        return
    configuration = session.scalar(
        select(EmbeddingConfiguration).where(
            EmbeddingConfiguration.owner_id == novel.owner_id,
            EmbeddingConfiguration.workspace_id == novel.workspace_id,
        )
    )
    if configuration is None or configuration.active_generation_id is None:
        session.commit()
        return
    build = session.scalar(
        select(EmbeddingGenerationNovel)
        .where(
            EmbeddingGenerationNovel.generation_id
            == configuration.active_generation_id,
            EmbeddingGenerationNovel.novel_id == novel_id,
        )
        .with_for_update()
    )
    if build is not None and build.sync_state != "revoked":
        build.sync_state = "outdated"
        if build.state not in {"cancelled", "stale"}:
            build.state = "outdated"
    session.commit()


def _refresh_active_novel_index_after_commit(
    session: Session,
    novel_id: UUID,
) -> bool:
    """Refresh after an authority commit without changing that action's outcome."""

    try:
        from .embedding.indexing import request_active_novel_refresh

        requested = request_active_novel_refresh(session, novel_id)
        session.commit()
        return requested
    except Exception:
        session.rollback()
        logger.warning(
            "semantic index refresh failed after authority commit for novel %s",
            novel_id,
            exc_info=True,
        )
        try:
            _mark_active_novel_index_outdated(session, novel_id)
        except Exception:
            session.rollback()
            logger.warning(
                "failed to mark semantic index outdated for novel %s",
                novel_id,
                exc_info=True,
            )
        return False


CURRENT_FACT_STATUSES = ("active", "source_restored")
INTELLIGENCE_STALE_FAILURE_MESSAGE = "上一次章节同步已超时失去执行上下文，请重新生成同步候选"
CHAPTER_LENGTH_TOLERANCE_RATIO = 0.15
CHAPTER_LENGTH_CONTROL_VERSION = "chapter-length-control/1"
CHAPTER_GENERATION_STALE_FAILURE_MESSAGE = (
    "上一次章节生成未在规定时间内完成，系统已结束该任务，正式正文未修改；"
    "请检查当前 Agent 模型后重新生成。"
)


def _chapter_length_window(target_count: int) -> tuple[int, int]:
    target = max(1, int(target_count))
    minimum = math.floor(target * (1 - CHAPTER_LENGTH_TOLERANCE_RATIO))
    maximum = math.ceil(target * (1 + CHAPTER_LENGTH_TOLERANCE_RATIO))
    return max(1, minimum), max(1, maximum)


def _generation_acceptance_window(
    job: ChapterGenerationJob,
) -> tuple[int, int, int]:
    snapshot = (
        job.generation_context_snapshot
        if isinstance(job.generation_context_snapshot, dict)
        else {}
    )
    acceptance = snapshot.get("acceptance")
    acceptance = acceptance if isinstance(acceptance, dict) else {}
    brief = snapshot.get("brief")
    brief = brief if isinstance(brief, dict) else {}
    requested = int(
        acceptance.get("requested_visible_character_count")
        or brief.get("target_word_count")
        or job.target_visible_character_count
    )
    default_minimum, default_maximum = _chapter_length_window(requested)
    minimum = int(
        acceptance.get("minimum_visible_character_count")
        or acceptance.get("target_visible_character_count")
        or job.target_visible_character_count
        or default_minimum
    )
    maximum = int(
        acceptance.get("maximum_visible_character_count") or default_maximum
    )
    return minimum, max(minimum, maximum), requested


def _candidate_length_validation_message(
    job: ChapterGenerationJob,
    *,
    actual_count: int | None = None,
) -> str:
    minimum, maximum, requested = _generation_acceptance_window(job)
    actual = int(
        (job.output_visible_character_count or 0)
        if actual_count is None
        else actual_count
    )
    return (
        f"正文候选未通过{minimum}—{maximum}字验收范围"
        f"（目标{requested}字，实际{actual}字），不能采用"
    )


def _latest_chapter_length_control(
    session: Session,
    *,
    document_id: UUID,
    brief_version: int,
    base_revision_id: UUID | None,
    base_draft_version: int,
    base_content_hash: str,
    requested_provider_id: str,
    requested_model_id: str,
    minimum_count: int,
    maximum_count: int,
    requested_count: int,
) -> dict[str, Any] | None:
    """Return feedback only from the same immutable generation baseline."""

    recent_failures = session.scalars(
        select(ChapterGenerationJob)
        .where(
            ChapterGenerationJob.document_id == document_id,
            ChapterGenerationJob.kind == "body",
            ChapterGenerationJob.state == "failed",
            ChapterGenerationJob.validation_state.in_(("above_target", "below_target")),
            ChapterGenerationJob.brief_version == brief_version,
            ChapterGenerationJob.base_revision_id == base_revision_id,
            ChapterGenerationJob.base_draft_version == base_draft_version,
            ChapterGenerationJob.base_content_hash == base_content_hash,
            ChapterGenerationJob.requested_provider_id == requested_provider_id,
            ChapterGenerationJob.requested_model_id == requested_model_id,
        )
        .order_by(ChapterGenerationJob.completed_at.desc(), ChapterGenerationJob.created_at.desc())
        .limit(10)
    ).all()
    for previous in recent_failures:
        if _generation_acceptance_window(previous) != (
            minimum_count,
            maximum_count,
            requested_count,
        ):
            continue
        actual_count = int(previous.output_visible_character_count or 0)
        delta = (
            actual_count - maximum_count
            if previous.validation_state == "above_target"
            else minimum_count - actual_count
        )
        calibrated_target = round(
            requested_count * requested_count / max(1, actual_count)
        )
        calibrated_target = min(
            math.ceil(maximum_count * 1.25),
            max(math.floor(minimum_count * 0.65), calibrated_target),
        )
        previous_snapshot = (
            previous.generation_context_snapshot
            if isinstance(previous.generation_context_snapshot, dict)
            else {}
        )
        previous_control = previous_snapshot.get("length_control")
        previous_control = (
            previous_control if isinstance(previous_control, dict) else {}
        )
        root_job_id = str(previous_control.get("root_job_id") or previous.id)
        retry_round = max(1, int(previous_control.get("retry_round") or 1)) + 1
        return {
            "schema_version": CHAPTER_LENGTH_CONTROL_VERSION,
            "mode": "retry_feedback",
            "root_job_id": root_job_id,
            "previous_job_id": str(previous.id),
            "retry_round": retry_round,
            "previous_validation_state": previous.validation_state,
            "previous_visible_character_count": actual_count,
            "required_adjustment_visible_character_count": max(1, delta),
            "calibrated_drafting_target_visible_character_count": calibrated_target,
        }
    return None


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _lock_generation_attempt(
    session: Session,
    *,
    namespace: str,
    scope_key: str,
    input_hash: str,
) -> None:
    """Serialize attempt allocation for one PostgreSQL generation key."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    lock_key = f"ai-novel-generation:{namespace}:{scope_key}:{input_hash}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": lock_key},
    )


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


def document_version_state(
    *,
    content_hash_value: str,
    visible_count: int,
    base_content_hash: str | None,
    base_source: str | None,
) -> str:
    """Derive the author-facing working-copy state without inventing publication."""

    if base_content_hash != content_hash_value:
        return "saved_working_copy"
    if base_source == "initial" and visible_count == 0:
        return "empty_draft"
    return "checkpointed"


def _document_base_revision(
    session: Session,
    working: DocumentWorkingCopy,
) -> DocumentRevision | None:
    if working.base_revision_id is None:
        return None
    revision = session.get(DocumentRevision, working.base_revision_id)
    if revision is None or revision.document_id != working.document_id:
        return None
    return revision


def _document_payload(
    document: Document,
    working: DocumentWorkingCopy,
) -> dict[str, Any]:
    character_count = visible_character_count(working.content_markdown)
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
        "visible_character_count": character_count,
        "updated_at": working.updated_at.isoformat() if working.updated_at else None,
    }


def _versioned_document_payload(
    document: Document,
    working: DocumentWorkingCopy,
    base_revision: DocumentRevision | None,
) -> dict[str, Any]:
    payload = _document_payload(document, working)
    payload["version_state"] = document_version_state(
        content_hash_value=working.content_hash,
        visible_count=payload["visible_character_count"],
        base_content_hash=base_revision.content_hash if base_revision else None,
        base_source=base_revision.source if base_revision else None,
    )
    return payload


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
    "character_state",
    "relationship_state",
    "storyline_event",
    "foreshadow_event",
    "story_time",
    "knowledge_event",
    "world_state",
    "general_fact",
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
    minimum_count, maximum_count, requested_count = _generation_acceptance_window(job)
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
        "execution_agent_id": job.execution_agent_id,
        "requested_provider_id": job.requested_provider_id,
        "model_profile_fingerprint": job.model_profile_fingerprint,
        "asset_snapshot": job.asset_snapshot,
        "requested_model_id": job.requested_model_id,
        "generation_contract_version": job.generation_contract_version,
        "actual_provider_id": job.actual_provider_id,
        "actual_model_id": job.actual_model_id,
        "model_evidence": job.model_evidence_json,
        "provider_profile": job.actual_provider_id or job.provider_profile,
        "target_visible_character_count": job.target_visible_character_count,
        "minimum_visible_character_count": minimum_count,
        "maximum_visible_character_count": maximum_count,
        "requested_visible_character_count": requested_count,
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
        "execution_agent_id": proposal.execution_agent_id,
        "requested_provider_id": proposal.requested_provider_id,
        "requested_model_id": proposal.requested_model_id,
        "generation_contract_version": proposal.generation_contract_version,
        "actual_provider_id": proposal.actual_provider_id,
        "actual_model_id": proposal.actual_model_id,
        "model_evidence": proposal.model_evidence_json,
        "provider_profile": proposal.actual_provider_id or proposal.provider_profile,
        "model_profile_fingerprint": proposal.model_profile_fingerprint,
        "attempt": proposal.attempt,
        "failure_message": proposal.failure_message,
        "items": [_intelligence_item_payload(item) for item in items],
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
    }


def _intelligence_commit_payload_hash(
    proposal_id: UUID,
    accepted_item_ids: set[UUID],
) -> str:
    canonical = json.dumps(
        {
            "proposal_id": str(proposal_id),
            "accepted_item_ids": sorted(str(item_id) for item_id in accepted_item_ids),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _intelligence_operation_key(
    operation_key: str | None,
    *,
    payload_hash: str,
) -> tuple[str, str | None]:
    if operation_key is None:
        return payload_hash, None
    cleaned = operation_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", cleaned):
        raise ValidationError(
            "operation_key must be 1-120 safe ASCII characters"
        )
    stored_key = hashlib.sha256(
        f"intelligence-commit-operation/1|{cleaned}".encode("utf-8")
    ).hexdigest()
    return stored_key, cleaned


def _intelligence_commit_batch_payload(batch: IntelligenceCommitBatch) -> dict[str, Any]:
    inverse = dict(batch.inverse_operations or {})
    return {
        "id": str(batch.id),
        "proposal_id": str(batch.proposal_id),
        "chapter_revision_id": str(batch.chapter_revision_id),
        "commit_key": batch.commit_key,
        "operation_key": inverse.get("operation_key"),
        "state": batch.state,
        "accepted_item_ids": batch.accepted_item_ids,
        "expected_story_ledger_version": batch.expected_story_ledger_version,
        "changed": bool(inverse.get("changed")),
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "reverted_at": batch.reverted_at.isoformat() if batch.reverted_at else None,
    }


def _require_novel(session: Session, novel_id: UUID) -> Novel:
    novel = session.get(Novel, novel_id)
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    return novel


def _lock_novel(session: Session, novel_id: UUID) -> Novel:
    novel = session.scalar(
        select(Novel).where(Novel.id == novel_id).with_for_update()
    )
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


def _runtime_chapter_title(
    session: Session,
    document: Document,
    *,
    suffix: str = "",
) -> str:
    """Project one chapter through the current canonical tree for model contracts."""

    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == document.novel_id)
    ).all()
    chapters = session.scalars(
        select(Document).where(
            Document.novel_id == document.novel_id,
            Document.kind == "chapter",
        )
    ).all()
    tree = canonical_tree(volumes, chapters)
    ordinal = tree.chapter_ordinals.get(document.id)
    if ordinal is None:
        raise ValidationError("chapter is missing from the canonical novel tree")
    return context_chapter_title(document.title, ordinal, suffix=suffix)


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
    volume = Volume(id=uuid4(), novel_id=novel.id, title="", position=1000)
    session.add_all((novel, volume))
    _new_document(
        session,
        novel_id=novel.id,
        title="",
        kind="chapter",
        position=1000,
        volume_id=volume.id,
    )
    session.flush()
    # Single-timeline novels require no author configuration: their primary
    # timeline is part of the same creation transaction as the novel itself.
    ensure_default_story_state(
        session,
        novel.id,
        expected_story_ledger_version=novel.story_ledger_version,
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
    _lock_novel(session, novel_id)
    title = semantic_title(title, "volume")
    if len(title) > 240:
        raise ValidationError("分卷名称不能超过240个字符")
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
    _lock_novel(session, novel_id)
    if kind not in {"chapter", "outline", "setting"}:
        raise ValidationError(f"unsupported document kind: {kind}")
    if kind == "chapter" and volume_id is None:
        raise VolumeChapterContractError(
            "chapter_volume_required", "请先创建分卷，再新建章节"
        )
    title = semantic_title(title, "chapter") if kind == "chapter" else title.strip()
    if kind != "chapter" and not title:
        raise VolumeChapterContractError(
            "document_title_required", "文档标题不能为空"
        )
    if len(title) > 240:
        raise ValidationError("文档标题不能超过240个字符")
    if volume_id is not None:
        volume = session.scalar(
            select(Volume)
            .where(Volume.id == volume_id, Volume.novel_id == novel_id)
            .with_for_update()
        )
        if volume is None or volume.novel_id != novel_id:
            raise VolumeChapterContractError(
                "chapter_volume_invalid",
                "所选分卷不存在或不属于当前小说，请刷新后重试",
            )
    document = _new_document(
        session,
        novel_id=novel_id,
        title=title,
        kind=kind,
        position=_next_position(session, Document, novel_id),
        volume_id=volume_id,
    )
    session.commit()
    if kind == "chapter":
        _refresh_active_novel_index_after_commit(session, novel_id)
    return get_document(session, document.id)


def get_novel_tree(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id).order_by(Volume.position)
    ).all()
    documents = session.scalars(
        select(Document).where(Document.novel_id == novel_id).order_by(Document.position)
    ).all()
    document_ids = [document.id for document in documents]
    working_copies = (
        session.scalars(
            select(DocumentWorkingCopy).where(
                DocumentWorkingCopy.document_id.in_(document_ids)
            )
        ).all()
        if document_ids
        else []
    )
    working_by_document_id = {
        working.document_id: working for working in working_copies
    }
    base_revision_ids = [
        working.base_revision_id
        for working in working_copies
        if working.base_revision_id is not None
    ]
    base_revisions = (
        session.scalars(
            select(DocumentRevision).where(DocumentRevision.id.in_(base_revision_ids))
        ).all()
        if base_revision_ids
        else []
    )
    base_revision_by_id = {revision.id: revision for revision in base_revisions}
    grouped: dict[UUID | None, list[dict[str, Any]]] = {volume.id: [] for volume in volumes}
    grouped[None] = []
    for document in documents:
        working = working_by_document_id.get(document.id)
        if working is None:
            continue
        group_id = document.volume_id if document.volume_id in grouped else None
        base_revision = (
            base_revision_by_id.get(working.base_revision_id)
            if working.base_revision_id is not None
            else None
        )
        grouped[group_id].append(
            _versioned_document_payload(document, working, base_revision)
        )
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
    payload = _versioned_document_payload(
        document,
        working,
        _document_base_revision(session, working),
    )
    revisions = session.scalars(
        select(DocumentRevision)
        .where(
            DocumentRevision.document_id == document.id,
            DocumentRevision.source != "tts_snapshot",
        )
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


def _derive_brief_role_constraints_v3(
    session: Session,
    document: Document,
    normalized_roles: dict[str, list[str]],
) -> dict[str, Any]:
    """Resolve legacy display names once, then persist only stable V3 refs."""

    timelines = tuple(
        session.scalars(
            select(StoryTimeline)
            .where(
                StoryTimeline.novel_id == document.novel_id,
                StoryTimeline.lifecycle_state == "active",
            )
            .order_by(StoryTimeline.position, StoryTimeline.id)
        )
    )
    if len(timelines) != 1:
        raise ValidationError("timeline_required: 多时间线章纲必须在时间线工作区保存")
    timeline = timelines[0]
    refs: list[dict[str, str]] = []
    for name in normalized_roles["required"]:
        characters = tuple(
            session.scalars(
                select(NovelCharacter).where(
                    NovelCharacter.novel_id == document.novel_id,
                    NovelCharacter.name == name,
                    NovelCharacter.lifecycle_state == "active",
                )
            )
        )
        if len(characters) != 1:
            raise ValidationError(f"required_character_unavailable: 无法唯一解析人物“{name}”")
        character = characters[0]
        instances = tuple(
            session.scalars(
                select(CharacterInstance).where(
                    CharacterInstance.novel_id == document.novel_id,
                    CharacterInstance.character_id == character.id,
                    CharacterInstance.origin_timeline_id == timeline.id,
                    CharacterInstance.lifecycle_state == "active",
                )
            )
        )
        if len(instances) != 1:
            raise ValidationError(
                f"character_instance_required: 无法唯一解析人物“{name}”的时间线实例"
            )
        instance = instances[0]
        refs.append(
            {
                "character_id": str(character.id),
                "character_instance_id": str(instance.id),
                "display_label": instance.display_label or character.name,
            }
        )
    return {
        "schema_version": "chapter-role-constraints/3",
        "timeline_id": str(timeline.id),
        "required_characters": refs,
        "point_of_view": None,
        "public_requirements": [],
        "prohibited_outcomes": [],
        "author_secret_constraints": [],
        "author_secret_facts": [],
    }


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
    normalized_roles = _normalize_role_constraints(role_constraints)
    if brief is None:
        if expected_version != 0:
            raise BriefConflictError(_brief_payload(None, document_id))
        v3 = _derive_brief_role_constraints_v3(session, document, normalized_roles)
        brief = ChapterBrief(
            id=uuid4(),
            document_id=document_id,
            version=1,
            target_word_count=target_word_count,
            expectation_text=expectation_text.strip(),
            outline_text=outline_text.strip(),
            forbidden_text=forbidden_text.strip(),
            role_constraints=normalized_roles | {"_v3": v3},
        )
        session.add(brief)
    else:
        if brief.version != expected_version:
            raise BriefConflictError(_brief_payload(brief, document_id))
        previous_roles = _normalize_role_constraints(brief.role_constraints)
        previous_v3 = (
            (brief.role_constraints or {}).get("_v3")
            if isinstance(brief.role_constraints, dict)
            else None
        )
        brief.version += 1
        brief.target_word_count = target_word_count
        brief.expectation_text = expectation_text.strip()
        brief.outline_text = outline_text.strip()
        brief.forbidden_text = forbidden_text.strip()
        next_v3 = (
            previous_v3
            if previous_v3 is not None and previous_roles == normalized_roles
            else _derive_brief_role_constraints_v3(session, document, normalized_roles)
        )
        brief.role_constraints = normalized_roles | {"_v3": next_v3}
    session.commit()
    return _brief_payload(brief, document_id)


def _generation_snapshot(
    session: Session,
    document: Document,
    working: DocumentWorkingCopy,
    brief: ChapterBrief,
    writing_retrieval: dict[str, Any] | None,
    writing_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "novel": {
            "id": str(document.novel_id),
            "title": str(
                session.scalar(select(Novel.title).where(Novel.id == document.novel_id))
                or ""
            ),
        },
        "chapter": {
            "document_id": str(document.id),
            "title": _runtime_chapter_title(session, document),
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
        "writing_context": writing_context,
        "writing_retrieval": writing_retrieval,
    }


def _generation_asset_snapshot(
    session: Session,
    *,
    novel_id: UUID,
    asset_ids: list[UUID] | None,
    preset_id: UUID | None,
) -> list[dict[str, Any]]:
    direct = tuple(
        DirectAssetSelection(
            asset_id=asset_id,
            usage_policy=UsagePolicy.PREFERRED,
            selection_key=f"chapter-request:{index}",
        )
        for index, asset_id in enumerate(dict.fromkeys(asset_ids or []))
    )
    return build_generation_asset_snapshot(
        session,
        novel_id,
        direct_selections=direct,
        preset_ids=((preset_id,) if preset_id is not None else ()),
        include_novel_bindings=True,
    )


def start_chapter_generation(
    session: Session,
    document_id: UUID,
    *,
    expected_brief_version: int,
    execution_agent_id: str,
    requested_provider_id: str,
    requested_model_id: str,
    generation_contract_version: str,
    force_new: bool = False,
    asset_ids: list[UUID] | None = None,
    preset_id: UUID | None = None,
    writing_retrieval: dict[str, Any] | None = None,
    writing_position: WritingPosition,
    effective_context_window_tokens: int,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    if document.kind != "chapter":
        raise ValidationError("body generation is only available for chapter documents")
    brief = session.scalar(select(ChapterBrief).where(ChapterBrief.document_id == document_id))
    if brief is None:
        raise ValidationError("请先保存章节任务书")
    if brief.version != expected_brief_version:
        raise BriefConflictError(_brief_payload(brief, document_id))
    if not all(
        value.strip()
        for value in (
            execution_agent_id,
            requested_provider_id,
            requested_model_id,
            generation_contract_version,
        )
    ):
        raise ValidationError("正文生成缺少可核验的 Agent 或 requested 模型证据")
    working = session.get(DocumentWorkingCopy, document_id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    asset_snapshot = _generation_asset_snapshot(
        session, novel_id=document.novel_id, asset_ids=asset_ids, preset_id=preset_id
    )
    if effective_context_window_tokens <= 0:
        raise ValidationError("当前正文模型没有提供可核验的有效上下文窗口")
    writing_context = assemble_writing_context_from_db(
        session,
        position=writing_position,
        purpose=ContextRetrievalPurpose.CHAPTER_BODY,
        requested_provider_id=requested_provider_id,
        requested_model_id=requested_model_id,
        budget_provider_id=requested_provider_id,
        budget_model_id=requested_model_id,
        effective_context_window_tokens=effective_context_window_tokens,
        reserved_output_tokens=max(1, int(brief.target_word_count) * 2),
        chapter_brief=brief,
        private_assets=asset_snapshot,
        writing_retrieval=writing_retrieval,
    )
    snapshot = _generation_snapshot(
        session, document, working, brief, writing_retrieval, writing_context
    )
    requested_count = int(brief.target_word_count)
    minimum_count, maximum_count = _chapter_length_window(requested_count)
    snapshot["acceptance"] = {
        "minimum_visible_character_count": minimum_count,
        "maximum_visible_character_count": maximum_count,
        "target_visible_character_count": minimum_count,
        "requested_visible_character_count": requested_count,
        "tolerance_ratio": CHAPTER_LENGTH_TOLERANCE_RATIO,
    }
    if force_new:
        length_control = _latest_chapter_length_control(
            session,
            document_id=document_id,
            brief_version=brief.version,
            base_revision_id=working.base_revision_id,
            base_draft_version=working.draft_version,
            base_content_hash=working.content_hash,
            requested_provider_id=requested_provider_id,
            requested_model_id=requested_model_id,
            minimum_count=minimum_count,
            maximum_count=maximum_count,
            requested_count=requested_count,
        )
        if length_control is not None:
            snapshot["length_control"] = length_control
    hash_material = {
        "input_snapshot": snapshot,
        "execution_agent_id": execution_agent_id,
        "requested_provider_id": requested_provider_id,
        "requested_model_id": requested_model_id,
        "generation_contract_version": generation_contract_version,
    }
    serialized = json.dumps(
        hash_material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    input_hash = content_hash(serialized)
    expire_stale_chapter_generation_jobs(session, document_id)
    _lock_generation_attempt(
        session,
        namespace="chapter-body",
        scope_key=str(document_id),
        input_hash=input_hash,
    )
    existing = session.scalar(
        select(ChapterGenerationJob).where(
            ChapterGenerationJob.document_id == document_id,
            ChapterGenerationJob.kind == "body",
            ChapterGenerationJob.input_hash == input_hash,
        ).order_by(ChapterGenerationJob.attempt.desc())
    )
    if existing is not None and not force_new and existing.state in {"running", "ready"}:
        payload = _generation_job_payload(session, existing, include_snapshot=True)
        payload["should_execute"] = False
        return payload
    attempt = (existing.attempt + 1) if existing is not None else 1
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
        execution_agent_id=execution_agent_id,
        requested_provider_id=requested_provider_id,
        requested_model_id=requested_model_id,
        generation_contract_version=generation_contract_version,
        target_visible_character_count=minimum_count,
        attempt=attempt,
    )
    session.add(job)
    session.commit()
    payload = _generation_job_payload(session, job, include_snapshot=True)
    payload["should_execute"] = True
    return payload


def build_chapter_generation_prompt(snapshot: dict[str, Any]) -> str:
    brief = snapshot["brief"]
    acceptance = snapshot.get("acceptance") or {}
    requested_visible_character_count = int(
        acceptance.get("requested_visible_character_count")
        or brief["target_word_count"]
    )
    default_minimum, default_maximum = _chapter_length_window(
        requested_visible_character_count
    )
    minimum_visible_character_count = int(
        acceptance.get("minimum_visible_character_count")
        or acceptance.get("target_visible_character_count")
        or default_minimum
    )
    maximum_visible_character_count = int(
        acceptance.get("maximum_visible_character_count") or default_maximum
    )
    roles = brief["role_constraints"]
    current_document_id = str(snapshot["chapter"].get("document_id") or "")
    current_draft_text = str(snapshot["chapter"].get("base_content_markdown") or "")
    current_draft_count = visible_character_count(current_draft_text)
    length_control = snapshot.get("length_control")
    length_control = length_control if isinstance(length_control, dict) else {}
    writing_context = snapshot.get("writing_context")
    writing_context = writing_context if isinstance(writing_context, dict) else {}
    envelope = writing_context.get("envelope")
    envelope = envelope if isinstance(envelope, dict) else {}
    v4_blocks = tuple(
        item for item in envelope.get("included_blocks", []) if isinstance(item, dict)
    )

    def v4_section_text(section: str) -> str:
        return "\n\n".join(
            f"【{item.get('title', section)}】\n{item.get('content', '')}"
            for item in v4_blocks if item.get("section") == section
        )

    context_v3 = snapshot.get("context_v3")
    context_v3 = context_v3 if isinstance(context_v3, dict) else {}
    if envelope:
        context_text = v4_section_text("manuscript")
        planning_text = v4_section_text("formal_planning")
        character_text = v4_section_text("character_state")
        asset_text = v4_section_text("private_assets")
        semantic_text = v4_section_text("semantic_evidence")
        facts_text = "\n".join(
            f"- {fact.get('subject', '')}｜{fact.get('predicate', '')}｜{fact.get('object_text', '')}"
            for fact in envelope.get("current_story_facts", []) if isinstance(fact, dict)
        )
        chapter_timeline_text = json.dumps(
            envelope.get("chapter_timeline", {}), ensure_ascii=False, sort_keys=True
        )
        chapter_requirements_text = v4_section_text("chapter_requirements")
        diagnostics_text = json.dumps(
            {
                "assembly_hash": writing_context.get("assembly_hash"),
                "context_policy_version": writing_context.get("context_policy_version"),
                "diagnostics": envelope.get("diagnostics", {}),
                "budget": envelope.get("budget", {}),
            }, ensure_ascii=False, sort_keys=True
        )
    else:
        previous_context = [
            item for item in snapshot.get("previous_context", [])
            if str(item.get("document_id") or "") != current_document_id
        ]
        context_text = "\n\n".join(
            f"【{item['title']}】\n{item.get('content_markdown', '')}"
            for item in previous_context
        )
        facts_text = "\n".join(
            f"- {fact['subject']}｜{fact['predicate']}｜{fact['object']}"
            for fact in snapshot.get("story_facts", [])
        )
        asset_text = "\n".join(
            f"- [{asset['asset_type']}] {asset['title']}：{asset['content']}"
            for asset in snapshot.get("private_assets", [])
        )
        planning_text = "\n\n".join(
            f"【{item.get('title', '正式规划')}】\n{item.get('content', '')}"
            for item in context_v3.get("formal_planning", []) if isinstance(item, dict)
        )
    def character_context_line(item: dict[str, Any]) -> str:
        age = item.get("age_projection")
        age = age if isinstance(age, dict) else {}
        if age.get("precision") == "range":
            age_text = f"{age.get('minimum_age')}—{age.get('maximum_age')}岁"
        else:
            age_text = f"未知（{age.get('reason') or '缺少故事时间依据'}）"
        return (
            f"- {item.get('ref', {}).get('display_label', '')}："
            f"{item.get('public_profile', '')}；按本章故事时间的年龄：{age_text}"
        )

    if not envelope:
        character_text = "\n".join(
            character_context_line(item)
            for item in context_v3.get("character_state", []) if isinstance(item, dict)
        )
        chapter_timeline_text = json.dumps(
            context_v3.get("chapter_timeline", {}), ensure_ascii=False, sort_keys=True
        ) if context_v3 else ""
        chapter_requirements_text = json.dumps(
            context_v3.get("chapter_requirements", {}), ensure_ascii=False, sort_keys=True
        ) if context_v3 else ""
        retrieval = snapshot.get("writing_retrieval")
        retrieval = retrieval if isinstance(retrieval, dict) else {}
        semantic_text = "\n".join(
            f"- [{item.get('corpus', '')}] {item.get('snippet', '')}"
            for item in retrieval.get("hits", []) if isinstance(item, dict)
        )
        diagnostics_text = json.dumps(
            {
                "context": context_v3.get("diagnostics", {}),
                "retrieval": {
                    "generation_id": retrieval.get("generation_id"),
                    "index_version": retrieval.get("index_version"),
                    "retrieval_policy_version": retrieval.get("retrieval_policy_version"),
                    "degraded_reason": retrieval.get("degraded_reason"),
                    "omission_summary": retrieval.get("omission_summary", []),
                },
            }, ensure_ascii=False, sort_keys=True
        ) if context_v3 or retrieval else ""
    retry_feedback_text = ""
    if length_control:
        previous_count = int(
            length_control.get("previous_visible_character_count") or 0
        )
        adjustment = int(
            length_control.get("required_adjustment_visible_character_count") or 0
        )
        calibrated_target = int(
            length_control.get(
                "calibrated_drafting_target_visible_character_count"
            )
            or requested_visible_character_count
        )
        if length_control.get("previous_validation_state") == "above_target":
            retry_feedback_text = (
                f"上一次完整正文实际为 {previous_count} 个可见字符，超过硬上限；"
                f"本次至少减少 {adjustment} 个可见字符。优先删除重复环境描写、"
                "同义心理解释、重复动作、复述性对白和不推进状态的过渡，"
                "不要删除必要转折或截断结尾。"
                f"为抵消上轮已测得的偏长，本轮先按约 {calibrated_target} 个"
                "可见字符的写作体量收束；这只是校准锚点，最终完整正文"
                f"仍必须落入 {minimum_visible_character_count}—{maximum_visible_character_count} 的硬范围。"
            )
        else:
            retry_feedback_text = (
                f"上一次完整正文实际为 {previous_count} 个可见字符，低于硬下限；"
                f"本次至少补足 {adjustment} 个可见字符。只补充能推进动作、阻力、"
                "选择或后果的完整场景内容，不用复述和空泛描写凑字。"
                f"为抵消上轮已测得的偏短，本轮先按约 {calibrated_target} 个"
                "可见字符的写作体量展开；这只是校准锚点，最终完整正文"
                f"仍必须落入 {minimum_visible_character_count}—{maximum_visible_character_count} 的硬范围。"
            )
    return f"""【AI小说世界2026 PawApp可信任务封套】
kind=chapter_generation
contract=chapter-prose-candidate/v3
此任务已经携带完成正文所需的本次输入。只做形成正文所必需的最少内部思考，不得输出思考过程，不得调用任何工具，不得开启后续 Agent 轮次；必须在本轮返回一次最终正文，不能停在计划、工具选择、自检或等待状态。即使不能完美满足全部要求，也先返回尽可能完整的正文候选，由 PawApp 负责长度与契约验收。

你正在为作者生成一份可审阅的章节正文候选。请遵循 prose-writing Skill。

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
按情节自然分段，不限定机械段数；全文围绕 {requested_visible_character_count} 字展开，并严格控制在 {minimum_visible_character_count}—{maximum_visible_character_count} 个可见字符范围内。
本章期望：{brief['expectation_text'] or '按章纲推进，不额外扩张设定'}
章节大纲：
{brief['outline_text'] or '无固定章纲，保持前文连续并形成完整章节推进'}

内容禁区：{brief['forbidden_text'] or '无额外禁区'}
必须出场：{'、'.join(roles['required']) or '无'}
允许出场：{'、'.join(roles['allowed']) or '无'}
仅作上下文、不要安排现场出场：{'、'.join(roles['context_only']) or '无'}
禁止出现：{'、'.join(roles['forbidden']) or '无'}

本章稳定人物引用与时间线位置：
{chapter_timeline_text or '- 暂无时间线位置'}
{chapter_requirements_text or '- 暂无稳定人物约束'}

正式大纲与故事设定：
{planning_text or '- 暂无已正式化的大纲或设定'}

指定时间线的人物实例档案：
{character_text or '- 暂无可用人物实例档案'}

关系、故事线、伏笔、时间与知识的确定性状态：
{facts_text or '- 暂无结构化故事事实'}

本次作者选用的私有库资料：
{asset_text or '- 未选择，按章纲与前文创作'}

当前章旧稿（{current_draft_count} 个可见字符，仅用于保留事实、人物声音和连续性；它不是本次最终答案。必须依照任务书生成一份完整的新候选，达到上述目标范围，不得原样返回旧稿）：
{current_draft_text or '当前章尚无旧稿'}

本章之前的正文上下文（仅作连续性参考）：
{context_text or '暂无前文章节'}

语义检索补充证据（只作线索，不能覆盖上面的确定性事实）：
{semantic_text or '- 本次未提供语义证据'}

来源、冲突和省略说明：
{diagnostics_text or '- 无额外诊断'}

【最终输出收束门】
现在只返回一份从开场到本章出口都完整的小说正文。目标约 {requested_visible_character_count} 个可见字符，硬范围 {minimum_visible_character_count}—{maximum_visible_character_count}；不得靠截断、摘要、大纲化或追加说明满足长度。
{retry_feedback_text or '这是本轮首次生成；发送前静默压缩重复表达或补足必要行动，确保完整正文落入硬范围。'}
完成必要情节推进后立即收束并停止，不为覆盖所有资料而扩写，不增加章纲之外的支线。
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
    actual_provider_id: str | None = None,
    actual_model_id: str | None = None,
    model_evidence: dict[str, Any] | None = None,
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
    if job.state != "running":
        return _generation_job_payload(session, job)
    if model_evidence is not None:
        try:
            actual_provider_id, actual_model_id = candidate_actual_identity(
                model_evidence,
                requested_provider_id=str(job.requested_provider_id or ""),
                requested_model_id=job.requested_model_id,
            )
        except ModelEvidencePolicyError as error:
            job.model_evidence_json = dict(model_evidence)
            job.state = "failed"
            job.failure_message = str(error)
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            raise ValidationError(str(error)) from error
        job.model_evidence_json = dict(model_evidence)
    elif (
        actual_provider_id != job.requested_provider_id
        or actual_model_id != job.requested_model_id
    ):
        job.state = "failed"
        job.failure_message = (
            "正文回复模型与任务启动模型不一致，结果已作废："
            f"requested={job.requested_provider_id}/{job.requested_model_id}, "
            f"actual={actual_provider_id}/{actual_model_id}"
        )
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ValidationError(job.failure_message)
    job.actual_provider_id = actual_provider_id
    job.actual_model_id = actual_model_id
    candidate_text = _clean_model_candidate(content_markdown)
    output_visible_character_count = visible_character_count(candidate_text)
    minimum_visible_character_count, maximum_visible_character_count, requested_visible_character_count = (
        _generation_acceptance_window(job)
    )
    if output_visible_character_count < minimum_visible_character_count:
        job.state = "failed"
        job.output_visible_character_count = output_visible_character_count
        job.validation_state = "below_target"
        job.failure_message = (
            f"正文仅有{output_visible_character_count}个可见字符，"
            f"低于目标{requested_visible_character_count}字允许的下浮15%范围"
            f"（下限{minimum_visible_character_count}字），必须整章重写"
        )
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ChapterLengthValidationError(
            job.failure_message,
            validation_state=job.validation_state,
            output_visible_character_count=output_visible_character_count,
            minimum_visible_character_count=minimum_visible_character_count,
            maximum_visible_character_count=maximum_visible_character_count,
            requested_visible_character_count=requested_visible_character_count,
        )
    if output_visible_character_count > maximum_visible_character_count:
        job.state = "failed"
        job.output_visible_character_count = output_visible_character_count
        job.validation_state = "above_target"
        job.failure_message = (
            f"正文共有{output_visible_character_count}个可见字符，"
            f"超过目标{requested_visible_character_count}字允许的上浮15%范围"
            f"（上限{maximum_visible_character_count}字），必须整章重写"
        )
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ChapterLengthValidationError(
            job.failure_message,
            validation_state=job.validation_state,
            output_visible_character_count=output_visible_character_count,
            minimum_visible_character_count=minimum_visible_character_count,
            maximum_visible_character_count=maximum_visible_character_count,
            requested_visible_character_count=requested_visible_character_count,
        )
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
    job.output_visible_character_count = output_visible_character_count
    job.validation_state = "meets_target"
    job.completed_at = datetime.now(timezone.utc)
    session.add(candidate)
    session.commit()
    return _generation_job_payload(session, job, include_snapshot=True)


def fail_chapter_generation(
    session: Session,
    job_id: UUID,
    message: str,
    *,
    actual_provider_id: str | None = None,
    actual_model_id: str | None = None,
    model_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = session.scalar(
        select(ChapterGenerationJob)
        .where(ChapterGenerationJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"generation job {job_id} not found")
    if job.state != "running":
        return _generation_job_payload(session, job)
    if actual_provider_id and actual_model_id:
        job.actual_provider_id = actual_provider_id
        job.actual_model_id = actual_model_id
    if model_evidence is not None:
        job.model_evidence_json = dict(model_evidence)
    job.state = "failed"
    job.failure_message = message[:4000]
    job.completed_at = datetime.now(timezone.utc)
    session.commit()
    return _generation_job_payload(session, job)


def list_chapter_generation_jobs(session: Session, document_id: UUID) -> list[dict[str, Any]]:
    _require_document(session, document_id)
    expire_stale_chapter_generation_jobs(session, document_id)
    jobs = session.scalars(
        select(ChapterGenerationJob)
        .where(ChapterGenerationJob.document_id == document_id)
        .order_by(ChapterGenerationJob.created_at.desc())
    ).all()
    return [_generation_job_payload(session, job) for job in jobs]


def expire_stale_chapter_generation_jobs(
    session: Session,
    document_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Fail request-scoped chapter jobs that can no longer have a live owner."""

    current_time = now or datetime.now(timezone.utc)
    stale_after_seconds = (
        CHAPTER_GENERATION_TIMEOUT_SECONDS
        + CHAPTER_GENERATION_STALE_GRACE_SECONDS
    )
    cutoff = current_time - timedelta(seconds=stale_after_seconds)
    stale_jobs = session.scalars(
        select(ChapterGenerationJob)
        .where(
            ChapterGenerationJob.document_id == document_id,
            ChapterGenerationJob.state == "running",
            ChapterGenerationJob.created_at <= cutoff,
        )
        .with_for_update()
    ).all()
    for job in stale_jobs:
        job.state = "failed"
        job.validation_state = "runtime_timeout"
        job.failure_message = CHAPTER_GENERATION_STALE_FAILURE_MESSAGE
        job.completed_at = current_time
    if stale_jobs:
        session.commit()
    return len(stale_jobs)


def get_candidate(session: Session, candidate_id: UUID) -> dict[str, Any]:
    candidate = session.get(CandidateRevision, candidate_id)
    if candidate is None:
        raise NotFoundError(f"candidate {candidate_id} not found")
    return _candidate_payload(candidate)


def adopt_candidate(
    session: Session, candidate_id: UUID, *, expected_draft_version: int
) -> dict[str, Any]:
    candidate_scope = session.get(CandidateRevision, candidate_id)
    if candidate_scope is None:
        raise NotFoundError(f"candidate {candidate_id} not found")
    scoped_document_id = candidate_scope.document_id
    document = _require_document(session, scoped_document_id)
    novel = _lock_novel(session, document.novel_id)
    candidate = session.scalar(
        select(CandidateRevision)
        .where(CandidateRevision.id == candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if candidate is None:
        raise NotFoundError(f"candidate {candidate_id} not found")
    if candidate.document_id != scoped_document_id:
        raise ValidationError("正文候选的作品范围已变化，请重试")
    generation_job = session.get(ChapterGenerationJob, candidate.generation_job_id)
    if generation_job is None:
        raise ValidationError("正文候选缺少对应生成任务，不能采用")
    minimum_count, maximum_count, _ = _generation_acceptance_window(generation_job)
    candidate_count = visible_character_count(candidate.content_markdown)
    if (
        generation_job.validation_state != "meets_target"
        or generation_job.output_visible_character_count != candidate_count
        or not minimum_count <= candidate_count <= maximum_count
    ):
        raise ValidationError(
            _candidate_length_validation_message(
                generation_job,
                actual_count=candidate_count,
            )
        )
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
            _versioned_document_payload(
                document,
                working,
                _document_base_revision(session, working),
            ),
            _candidate_payload(candidate),
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
    _supersede_intelligence_for_document(session, candidate.document_id)
    reconciliation = _reconcile_story_facts_for_revision(
        session, candidate.document_id, revision
    )
    if reconciliation["changed"]:
        novel.story_ledger_version += 1
    working.base_revision_id = revision.id
    working.content_markdown = candidate.content_markdown
    working.content_hash = candidate.content_hash
    working.draft_version += 1
    candidate.state = "accepted"
    candidate.adopted_revision_id = revision.id
    candidate.decided_at = datetime.now(timezone.utc)
    from .embedding.indexing import request_active_novel_refresh
    request_active_novel_refresh(session, document.novel_id)
    session.commit()
    return {
        "document": get_document(session, candidate.document_id),
        "candidate": _candidate_payload(candidate),
        "revision": _revision_payload(revision, include_content=True),
        "story_ledger_version": novel.story_ledger_version,
        "reconciliation": reconciliation,
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
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = _document_fact_binding_rows(session, document_id, lock=True)
    changed_binding_ids: list[str] = []
    metadata_changed_binding_ids: list[str] = []
    changed_fact_ids: set[str] = set()
    activated_binding_ids: list[str] = []
    invalidated_binding_ids: list[str] = []
    for binding, fact in rows:
        if binding.source_content_hash == target_revision.content_hash:
            target_state = "source_restored" if restored else "current"
            validity_changed = binding.validity_state != target_state
            metadata_changed = (
                binding.invalidated_at is not None
                or (restored and binding.restored_at is None)
                or (not restored and binding.restored_at is not None)
            )
            if validity_changed or metadata_changed:
                binding.validity_state = target_state
                binding.invalidated_at = None
                binding.restored_at = now if restored else None
            if validity_changed:
                activated_binding_ids.append(str(binding.id))
        else:
            validity_changed = binding.validity_state != "source_superseded"
            metadata_changed = (
                binding.invalidated_at is None or binding.restored_at is not None
            )
            if validity_changed or metadata_changed:
                binding.validity_state = "source_superseded"
                if binding.invalidated_at is None:
                    binding.invalidated_at = now
                binding.restored_at = None
            if validity_changed:
                invalidated_binding_ids.append(str(binding.id))
        if validity_changed:
            changed_binding_ids.append(str(binding.id))
            changed_fact_ids.add(str(fact.id))
        elif metadata_changed:
            metadata_changed_binding_ids.append(str(binding.id))
    return {
        "changed": bool(changed_binding_ids),
        "metadata_changed": bool(metadata_changed_binding_ids),
        "target_revision_id": str(target_revision.id),
        "changed_binding_ids": changed_binding_ids,
        "metadata_changed_binding_ids": metadata_changed_binding_ids,
        "changed_fact_ids": sorted(changed_fact_ids),
        "activated_binding_ids": activated_binding_ids,
        "invalidated_binding_ids": invalidated_binding_ids,
    }


def _supersede_intelligence_for_document(
    session: Session, document_id: UUID
) -> None:
    proposals = session.scalars(
        select(IntelligenceProposal).where(
            IntelligenceProposal.document_id == document_id,
            IntelligenceProposal.state.in_(("running", "ready", "partially_accepted")),
        )
    ).all()
    for proposal in proposals:
        proposal.state = "superseded"


def _intelligence_extraction_context(
    session: Session,
    document: Document,
    revision: DocumentRevision,
) -> dict[str, Any]:
    """Freeze server-owned IDs exposed to the extractor as short opaque keys."""

    timelines = tuple(
        session.scalars(
            select(StoryTimeline)
            .where(
                StoryTimeline.novel_id == document.novel_id,
                StoryTimeline.lifecycle_state == "active",
            )
            .order_by(StoryTimeline.position, StoryTimeline.id)
        )
    )
    if not timelines:
        raise ValidationError("小说尚未初始化主时间线")
    if len(timelines) == 1:
        timeline_segments = [{
            "timeline_id": str(timelines[0].id),
            "source_start": 0,
            "source_end": len(revision.content_text),
            "story_sequence": None,
        }]
    else:
        head = session.get(RevisionTimelineMappingHead, revision.id)
        if head is None or head.source_content_hash != revision.content_hash:
            raise ValidationError("timeline_required: 多时间线正文必须先完成当前 revision 的区间映射")
        segments = tuple(
            session.scalars(
                select(RevisionTimelineMappingSegment)
                .where(
                    RevisionTimelineMappingSegment.mapping_revision_id
                    == head.current_mapping_revision_id
                )
                .order_by(RevisionTimelineMappingSegment.ordinal)
            )
        )
        if not segments:
            raise ValidationError("timeline_required: 当前 revision 没有可用时间线区间")
        timeline_segments = [
            {
                "timeline_id": str(item.timeline_id),
                "source_start": item.source_start,
                "source_end": item.source_end,
                "story_sequence": item.story_sequence,
            }
            for item in segments
        ]
    chapter_timeline_ids = {UUID(item["timeline_id"]) for item in timeline_segments}
    by_timeline = {item.id: item for item in timelines}
    reachable = set(chapter_timeline_ids)
    for timeline_id in tuple(chapter_timeline_ids):
        current = by_timeline.get(timeline_id)
        while current is not None and current.parent_timeline_id is not None:
            reachable.add(current.parent_timeline_id)
            current = by_timeline.get(current.parent_timeline_id)

    instances = tuple(
        session.scalars(
            select(CharacterInstance)
            .where(
                CharacterInstance.novel_id == document.novel_id,
                CharacterInstance.lifecycle_state == "active",
                CharacterInstance.origin_timeline_id.in_(reachable),
            )
            .order_by(CharacterInstance.created_at, CharacterInstance.id)
        )
    )
    roots = {
        item.id: item
        for item in session.scalars(
            select(NovelCharacter).where(
                NovelCharacter.novel_id == document.novel_id,
                NovelCharacter.lifecycle_state == "active",
            )
        )
    }
    character_catalog = {
        f"character_{index}": {
            "character_id": str(instance.character_id),
            "character_instance_id": str(instance.id),
            "timeline_id": str(instance.origin_timeline_id),
            "label": instance.display_label or roots[instance.character_id].name,
        }
        for index, instance in enumerate(instances, start=1)
        if instance.character_id in roots
    }
    character_key_by_instance_id = {
        UUID(str(metadata["character_instance_id"])): key
        for key, metadata in character_catalog.items()
    }
    relationship_scope = CharacterRelationship.timeline_id.in_(reachable)
    if len(timelines) == 1:
        # Legacy single-line rows remain readable until the experimental test
        # database is rebuilt.  Once a second line exists, every relationship
        # presented to the extractor must be explicitly scoped.
        relationship_scope = (
            relationship_scope | CharacterRelationship.timeline_id.is_(None)
        )
    relationship_catalog = {
        f"relationship_{index}": {
            "relationship_id": str(item.id),
            "timeline_id": str(item.timeline_id) if item.timeline_id else None,
            "source_character_id": str(item.source_character_id),
            "target_character_id": str(item.target_character_id),
            "source_character_instance_id": (
                str(item.source_character_instance_id)
                if item.source_character_instance_id
                else None
            ),
            "target_character_instance_id": (
                str(item.target_character_instance_id)
                if item.target_character_instance_id
                else None
            ),
            "source_character_key": character_key_by_instance_id.get(
                item.source_character_instance_id
            ),
            "target_character_key": character_key_by_instance_id.get(
                item.target_character_instance_id
            ),
            "source_label": roots.get(item.source_character_id).name
            if roots.get(item.source_character_id)
            else "",
            "target_label": roots.get(item.target_character_id).name
            if roots.get(item.target_character_id)
            else "",
            "directionality": item.directionality,
            "relation_kind": item.relation_kind,
            "label": item.label,
            "manual_override": item.manual_override,
        }
        for index, item in enumerate(
            session.scalars(
                select(CharacterRelationship)
                .where(
                    CharacterRelationship.novel_id == document.novel_id,
                    CharacterRelationship.archived_at.is_(None),
                    relationship_scope,
                )
                .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
            ),
            start=1,
        )
    }
    storyline_catalog = {
        f"storyline_{index}": {"storyline_id": str(item.id), "label": item.title}
        for index, item in enumerate(
            session.scalars(
                select(Storyline)
                .where(
                    Storyline.novel_id == document.novel_id,
                    Storyline.status != "archived",
                )
                .order_by(Storyline.position, Storyline.id)
            ),
            start=1,
        )
    }
    foreshadow_catalog = {
        f"foreshadow_{index}": {"foreshadow_id": str(item.id), "label": item.title}
        for index, item in enumerate(
            session.scalars(
                select(Foreshadow)
                .where(Foreshadow.novel_id == document.novel_id)
                .order_by(Foreshadow.position, Foreshadow.id)
            ),
            start=1,
        )
    }
    chapter_sequence = int(
        session.scalar(
            select(func.count()).select_from(Document).where(
                Document.novel_id == document.novel_id,
                Document.kind == "chapter",
                Document.position <= document.position,
            )
        )
        or 0
    )
    return {
        "schema_version": "story-extraction-context/2",
        "timeline_segments": timeline_segments,
        "character_catalog": character_catalog,
        "relationship_catalog": relationship_catalog,
        "storyline_catalog": storyline_catalog,
        "foreshadow_catalog": foreshadow_catalog,
        "chapter_sequence": chapter_sequence,
        "source_revision_id": str(revision.id),
        "source_content_hash": revision.content_hash,
    }


def start_intelligence_proposal(
    session: Session,
    document_id: UUID,
    *,
    revision_id: UUID,
    execution_agent_id: str,
    requested_provider_id: str,
    requested_model_id: str,
    generation_contract_version: str,
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
    if not all(
        value.strip()
        for value in (
            execution_agent_id,
            requested_provider_id,
            requested_model_id,
            generation_contract_version,
        )
    ):
        raise ValidationError("章节情报生成缺少可核验的 Agent 或 requested 模型证据")
    expire_stale_intelligence_proposals(session, document_id)
    extraction_context = _intelligence_extraction_context(session, document, revision)
    extractor_contract = "story-ledger-extractor-v5"
    input_hash = content_hash(
        json.dumps(
            {
                "revision_content_hash": revision.content_hash,
                "extractor_contract": extractor_contract,
                "execution_agent_id": execution_agent_id,
                "requested_provider_id": requested_provider_id,
                "requested_model_id": requested_model_id,
                "generation_contract_version": generation_contract_version,
                "extraction_context": extraction_context,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    _lock_generation_attempt(
        session,
        namespace="intelligence",
        scope_key=str(revision_id),
        input_hash=input_hash,
    )
    existing = session.scalar(
        select(IntelligenceProposal).where(
            IntelligenceProposal.document_id == document_id,
            IntelligenceProposal.input_hash == input_hash,
        ).order_by(IntelligenceProposal.attempt.desc())
    )
    if existing is not None and existing.state not in {"failed", "superseded"}:
        payload = _intelligence_proposal_payload(session, existing)
        payload["should_execute"] = False
        return payload
    attempt = (existing.attempt + 1) if existing is not None else 1
    proposal = IntelligenceProposal(
        id=uuid4(),
        novel_id=document.novel_id,
        document_id=document_id,
        chapter_revision_id=revision_id,
        input_hash=input_hash,
        state="running",
        execution_agent_id=execution_agent_id,
        requested_provider_id=requested_provider_id,
        requested_model_id=requested_model_id,
        generation_contract_version=generation_contract_version,
        attempt=attempt,
        extraction_context_json=extraction_context,
    )
    session.add(proposal)
    session.commit()
    payload = _intelligence_proposal_payload(session, proposal)
    payload["should_execute"] = True
    return payload


def build_intelligence_prompt(session: Session, proposal_id: UUID) -> str:
    proposal = session.get(IntelligenceProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    document = _require_document(session, proposal.document_id)
    revision = session.get(DocumentRevision, proposal.chapter_revision_id)
    if revision is None:
        raise NotFoundError(f"revision {proposal.chapter_revision_id} not found")
    extraction_context = dict(proposal.extraction_context_json or {})
    timeline_ids = {
        UUID(str(item["timeline_id"]))
        for item in extraction_context.get("timeline_segments", [])
        if isinstance(item, dict) and item.get("timeline_id")
    }
    existing_facts = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == proposal.novel_id,
            StoryFact.schema_version == "story-fact/2",
            StoryFact.timeline_id.in_(timeline_ids),
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
{{"no_changes":false,"items":[{{"fact_type":"character_state|relationship_state|storyline_event|foreshadow_event|story_time|knowledge_event|world_state|general_fact","entity_key":"已有实体目录短键；新关系及general_fact/world_state/story_time可为空","source_character_key":"仅新关系填写人物短键","target_character_key":"仅新关系填写人物短键","directionality":"新关系填写directed或undirected","relation_kind":"新关系分类","relationship_label":"新关系名称","dimension":"状态维度短键","event_kind":"事件动作短键","subject":"主体显示文字","predicate":"变化描述","object":"客体或内容","source_text":"正文中的逐字短证据","visibility":"author|reader|all","details":{{}},"reasoning_summary":"为何值得进入故事账本","confidence":0到100}}]}}

规则：
1. 只提取正文明确发生或明确揭示的内容，不把猜测写成事实。
2. 只能引用下方服务器目录给出的短键；禁止输出姓名作为实体定位信息，禁止自行构造 UUID。
3. 已有相同事实不要重复；不确定时省略。正文没有新增或变化事实时，必须返回空 items，即 {{"no_changes":true,"items":[]}}。
4. 每项必须有可在正文中找到的 source_text。
5. 所有字符串内禁止使用未转义的英文双引号；引用原文时统一改用中文引号「」。
6. 不要为了满足数量制造情报。
7. 小说时间线与现实系统日期无关。严禁用当前现实年份补全「今年」「去年」「本月」等相对日期；必须以正文最近的明确场景日期为锚点推断。无法可靠推断时保留正文原有相对表述，不得擅自补全年份。
8. source_text 与 object 中的日期必须彼此一致；正文写明发生在 1992 年的场景，不得改写成 2026 年或其他现实年份。
9. character_state 和 knowledge_event 必须使用 character_catalog 的短键；storyline_event、foreshadow_event 必须分别使用对应目录短键。
10. relationship_state 若发展已有关系，必须使用 relationship_catalog 的 entity_key，不得改写关系定义；若正文明确形成了目录中不存在的新关系，entity_key 留空，并填写 source_character_key、target_character_key、directionality、relation_kind、relationship_label。两个人物键必须来自 character_catalog，禁止按姓名定位或自造 UUID。
11. 不得在提取阶段创建人物、故事线或伏笔根对象；目录没有对应对象时省略并交给作者另行规划。新关系也只是候选，只有作者看到结果并明确应用后才会建立。
12. visibility 默认 author；只有正文已经向读者或所有在场视角明确揭露时才能填写 reader 或 all。
13. details 只填写类型所需结构：knowledge_event 使用 operation/knowledge_key；story_time 使用 transition/from_time/to_time，其中时间值必须是 {{"schema_version":"story-time/1","label":"正文原有时间表述","precision":"unknown"}} 结构；foreshadow_event 使用 event/note。其他类型可留空对象，由服务器按类型补成版本化结构。

章节：{_runtime_chapter_title(session, document)}
服务器实体短键目录：
{json.dumps({key: extraction_context.get(key, {}) for key in ('character_catalog', 'relationship_catalog', 'storyline_catalog', 'foreshadow_catalog')}, ensure_ascii=False, sort_keys=True)}

正文区间时间线映射：
{json.dumps(extraction_context.get('timeline_segments', []), ensure_ascii=False, sort_keys=True)}

现有故事账本：
{ledger or '- 暂无'}

正式正文：
{revision.content_text}
""".strip()


def complete_intelligence_proposal(
    session: Session,
    proposal_id: UUID,
    *,
    items: list[dict[str, Any]],
    actual_provider_id: str | None = None,
    actual_model_id: str | None = None,
    model_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal = session.scalar(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    if proposal.state != "running":
        return _intelligence_proposal_payload(session, proposal)
    if model_evidence is not None:
        try:
            actual_provider_id, actual_model_id = candidate_actual_identity(
                model_evidence,
                requested_provider_id=str(proposal.requested_provider_id or ""),
                requested_model_id=proposal.requested_model_id,
            )
        except ModelEvidencePolicyError as error:
            proposal.model_evidence_json = dict(model_evidence)
            proposal.state = "failed"
            proposal.failure_message = str(error)
            session.commit()
            raise ValidationError(str(error)) from error
        proposal.model_evidence_json = dict(model_evidence)
    elif (
        actual_provider_id != proposal.requested_provider_id
        or actual_model_id != proposal.requested_model_id
    ):
        proposal.state = "failed"
        proposal.failure_message = (
            "章节情报回复模型与任务启动模型不一致，结果已作废："
            f"requested={proposal.requested_provider_id}/{proposal.requested_model_id}, "
            f"actual={actual_provider_id}/{actual_model_id}"
        )
        session.commit()
        raise ValidationError(proposal.failure_message)
    proposal.actual_provider_id = actual_provider_id
    proposal.actual_model_id = actual_model_id
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
    novel = session.scalar(
        select(Novel).where(Novel.id == proposal.novel_id).with_for_update()
    )
    if novel is None:
        raise NotFoundError(f"novel {proposal.novel_id} not found")
    existing = session.scalar(
        select(func.count(IntelligenceProposalItem.id)).where(
            IntelligenceProposalItem.proposal_id == proposal_id
        )
    )
    if existing:
        return _intelligence_proposal_payload(session, proposal)
    normalized: list[IntelligenceProposalItem] = []
    extraction_context = dict(proposal.extraction_context_json or {})
    character_catalog = extraction_context.get("character_catalog", {})
    relationship_catalog = extraction_context.get("relationship_catalog", {})
    catalog_by_type = {
        "character_state": extraction_context.get("character_catalog", {}),
        "knowledge_event": extraction_context.get("character_catalog", {}),
        "relationship_state": extraction_context.get("relationship_catalog", {}),
        "storyline_event": extraction_context.get("storyline_catalog", {}),
        "foreshadow_event": extraction_context.get("foreshadow_catalog", {}),
    }
    segments = [
        item
        for item in extraction_context.get("timeline_segments", [])
        if isinstance(item, dict)
    ]
    for position, raw in enumerate(items[:200], start=1):
        item_type = str(raw.get("fact_type", raw.get("item_type", ""))).strip()
        if item_type not in INTELLIGENCE_ITEM_TYPES:
            continue
        subject = str(raw.get("subject", "")).strip()
        predicate = str(raw.get("predicate", "")).strip()
        object_text = str(raw.get("object", "")).strip()
        source_text = str(raw.get("source_text", "")).strip()
        if not subject or not predicate or not object_text or not source_text:
            continue
        occurrences: list[int] = []
        offset = revision.content_text.find(source_text)
        while offset >= 0:
            occurrences.append(offset)
            offset = revision.content_text.find(source_text, offset + 1)
        if len(occurrences) != 1:
            continue
        source_start = occurrences[0]
        source_end = source_start + len(source_text)
        matching_segments = [
            segment
            for segment in segments
            if int(segment.get("source_start", -1)) <= source_start
            and int(segment.get("source_end", -1)) >= source_end
        ]
        if len(matching_segments) != 1:
            continue
        segment = matching_segments[0]
        entity_key = str(raw.get("entity_key", "")).strip()
        entity_metadata: dict[str, Any] = {}
        if item_type == "relationship_state":
            existing_relationship = (
                relationship_catalog.get(entity_key)
                if isinstance(relationship_catalog, dict) and entity_key
                else None
            )
            if isinstance(existing_relationship, dict):
                entity_metadata = {**existing_relationship, "is_new": False}
            else:
                source_key = str(raw.get("source_character_key") or "").strip()
                target_key = str(raw.get("target_character_key") or "").strip()
                source_metadata = (
                    character_catalog.get(source_key)
                    if isinstance(character_catalog, dict)
                    else None
                )
                target_metadata = (
                    character_catalog.get(target_key)
                    if isinstance(character_catalog, dict)
                    else None
                )
                directionality = str(raw.get("directionality") or "").strip()
                relation_kind = str(raw.get("relation_kind") or "").strip()
                relationship_label = str(
                    raw.get("relationship_label") or ""
                ).strip()
                if (
                    entity_key
                    or not isinstance(source_metadata, dict)
                    or not isinstance(target_metadata, dict)
                    or directionality not in RELATIONSHIP_DIRECTIONALITIES
                    or relation_kind not in RELATIONSHIP_KINDS
                    or not relationship_label
                    or len(relationship_label) > 80
                ):
                    continue
                try:
                    source_id = UUID(str(source_metadata["character_id"]))
                    target_id = UUID(str(target_metadata["character_id"]))
                    canonical_source, _ = canonical_relationship_endpoints(
                        source_id, target_id, directionality
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if canonical_source != source_id:
                    source_key, target_key = target_key, source_key
                    source_metadata, target_metadata = target_metadata, source_metadata
                entity_metadata = {
                    "relationship_id": None,
                    "timeline_id": str(segment["timeline_id"]),
                    "source_character_id": str(source_metadata["character_id"]),
                    "target_character_id": str(target_metadata["character_id"]),
                    "source_character_instance_id": str(
                        source_metadata["character_instance_id"]
                    ),
                    "target_character_instance_id": str(
                        target_metadata["character_instance_id"]
                    ),
                    "source_character_key": source_key,
                    "target_character_key": target_key,
                    "source_label": str(source_metadata.get("label") or ""),
                    "target_label": str(target_metadata.get("label") or ""),
                    "directionality": directionality,
                    "relation_kind": relation_kind,
                    "label": relationship_label,
                    "manual_override": False,
                    "is_new": True,
                }
        else:
            catalog = catalog_by_type.get(item_type)
            if isinstance(catalog, dict):
                candidate = catalog.get(entity_key)
                if not isinstance(candidate, dict):
                    continue
                entity_metadata = dict(candidate)
        if item_type == "relationship_state" and not entity_metadata:
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
                    "entity_key": entity_key or None,
                    "entity": entity_metadata,
                    "timeline_id": str(segment["timeline_id"]),
                    "story_sequence": (
                        segment.get("story_sequence")
                        if segment.get("story_sequence") is not None
                        else extraction_context.get("chapter_sequence")
                    ),
                    "source_start": source_start,
                    "source_end": source_end,
                    "dimension": str(raw.get("dimension") or item_type)[:80],
                    "event_kind": str(raw.get("event_kind") or "confirmed")[:80],
                    "visibility": str(raw.get("visibility") or "author"),
                    "details": (
                        raw.get("details") if isinstance(raw.get("details"), dict) else {}
                    ),
                },
                confidence=max(0, min(confidence, 100)),
                source_text=source_text,
                reasoning_summary=str(raw.get("reasoning_summary", "")).strip(),
                review_state="pending",
            )
        )
    relationship_item_count = sum(
        1
        for raw in items[:200]
        if str(raw.get("fact_type", raw.get("item_type", ""))).strip()
        == "relationship_state"
    )
    normalized_relationship_count = sum(
        1 for item in normalized if item.item_type == "relationship_state"
    )
    if normalized_relationship_count != relationship_item_count:
        raise ValidationError("关系候选包含无效或越权的人物、关系、时间线或正文证据")
    session.add_all(normalized)
    proposal.state = "ready"
    proposal.failure_message = None
    session.commit()
    return _intelligence_proposal_payload(session, proposal)


def fail_intelligence_proposal(
    session: Session,
    proposal_id: UUID,
    message: str,
    *,
    actual_provider_id: str | None = None,
    actual_model_id: str | None = None,
    model_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proposal = session.scalar(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    if proposal.state != "running":
        return _intelligence_proposal_payload(session, proposal)
    if actual_provider_id and actual_model_id:
        proposal.actual_provider_id = actual_provider_id
        proposal.actual_model_id = actual_model_id
    if model_evidence is not None:
        proposal.model_evidence_json = dict(model_evidence)
    proposal.state = "failed"
    proposal.failure_message = message[:4000]
    session.commit()
    return _intelligence_proposal_payload(session, proposal)


def list_intelligence_proposals(
    session: Session, document_id: UUID
) -> list[dict[str, Any]]:
    _require_document(session, document_id)
    expire_stale_intelligence_proposals(session, document_id)
    proposals = session.scalars(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.document_id == document_id)
        .order_by(IntelligenceProposal.created_at.desc())
    ).all()
    return [_intelligence_proposal_payload(session, proposal) for proposal in proposals]


def expire_stale_intelligence_proposals(
    session: Session,
    document_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(
        seconds=(
            CHAPTER_GENERATION_TIMEOUT_SECONDS
            + CHAPTER_GENERATION_STALE_GRACE_SECONDS
        )
    )
    stale_proposals = session.scalars(
        select(IntelligenceProposal)
        .where(
            IntelligenceProposal.document_id == document_id,
            IntelligenceProposal.state == "running",
            IntelligenceProposal.created_at <= cutoff,
        )
        .with_for_update()
    ).all()
    for proposal in stale_proposals:
        proposal.state = "failed"
        proposal.failure_message = INTELLIGENCE_STALE_FAILURE_MESSAGE
    if stale_proposals:
        session.commit()
    return len(stale_proposals)


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


def _normalize_story_time_value(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        normalized = dict(value)
        normalized.setdefault("schema_version", "story-time/1")
        normalized.setdefault("precision", "unknown")
        return normalized
    label = str(value or "").strip()
    if not label:
        return None
    return {
        "schema_version": "story-time/1",
        "label": label[:300],
        "precision": "unknown",
    }


def _story_time_invents_calendar_year(
    source_text: str,
    payload: dict[str, object],
) -> bool:
    source_years = set(re.findall(r"(?<!\d)[12]\d{3}(?!\d)", source_text))
    proposed_text = json.dumps(
        {"object": payload.get("object"), "details": payload.get("details")},
        ensure_ascii=False,
        sort_keys=True,
    )
    proposed_years = set(re.findall(r"(?<!\d)[12]\d{3}(?!\d)", proposed_text))
    return bool(proposed_years - source_years)


def _typed_story_fact_candidate(
    *,
    proposal: IntelligenceProposal,
    revision: DocumentRevision,
    item: IntelligenceProposalItem,
    payload: dict[str, object],
) -> StoryFactV2:
    fact_type = item.item_type
    entity = payload.get("entity")
    entity = entity if isinstance(entity, dict) else {}
    object_text = str(payload.get("object", "")).strip()
    predicate = str(payload.get("predicate", "")).strip()
    raw_details = payload.get("details")
    raw_details = raw_details if isinstance(raw_details, dict) else {}
    if fact_type == "character_state":
        details = {"schema_version": "character-state/1", "value": object_text}
    elif fact_type == "relationship_state":
        details = {"schema_version": "relationship-state/1", "value": object_text}
    elif fact_type == "storyline_event":
        details = {
            "schema_version": "storyline-event/1",
            "event": str(raw_details.get("event") or predicate),
            "value": raw_details.get("value", object_text),
            "status": raw_details.get("status"),
            "progress": raw_details.get("progress"),
        }
    elif fact_type == "foreshadow_event":
        event = str(raw_details.get("event") or payload.get("event_kind") or "reinforce")
        if event not in {"plant", "reinforce", "reveal", "resolve", "cancel"}:
            event = "reinforce"
        details = {
            "schema_version": "foreshadow-event/1",
            "event": event,
            "note": str(raw_details.get("note") or object_text),
        }
    elif fact_type == "story_time":
        transition = str(raw_details.get("transition") or "unknown")
        if transition not in {"advance", "flashback", "flashforward", "anchor", "unknown"}:
            transition = "unknown"
        from_time = _normalize_story_time_value(raw_details.get("from_time"))
        to_time = _normalize_story_time_value(raw_details.get("to_time") or object_text)
        details = {
            "schema_version": "story-time-event/1",
            "transition": transition,
            "from_time": from_time,
            "to_time": to_time,
        }
    elif fact_type == "knowledge_event":
        operation = str(raw_details.get("operation") or "learn")
        if operation not in {"learn", "forget", "believe", "doubt", "reveal"}:
            operation = "learn"
        details = {
            "schema_version": "knowledge-event/1",
            "operation": operation,
            "knowledge_key": str(raw_details.get("knowledge_key") or payload.get("dimension")),
        }
    elif fact_type == "world_state":
        details = {"schema_version": "world-state/1", "value": object_text}
    else:
        details = {"schema_version": "general-fact/1", "value": object_text}
    visibility = str(payload.get("visibility") or "author")
    if visibility not in {"author", "reader", "all"}:
        visibility = "author"
    fingerprint_material = {
        "novel_id": str(proposal.novel_id),
        "source_revision_id": str(proposal.chapter_revision_id),
        "source_start": payload.get("source_start"),
        "source_end": payload.get("source_end"),
        "timeline_id": payload.get("timeline_id"),
        "fact_type": fact_type,
        "dimension": payload.get("dimension"),
        "event_kind": payload.get("event_kind"),
        "entity": entity,
        "object": object_text,
    }
    fingerprint = content_hash(
        json.dumps(
            fingerprint_material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    try:
        return StoryFactV2.model_validate(
            {
            "id": uuid4(),
            "novel_id": proposal.novel_id,
            "fact_type": fact_type,
            "subject": str(payload.get("subject", "")).strip(),
            "predicate": predicate,
            "object_text": object_text,
            "details": details,
            "source_revision_id": proposal.chapter_revision_id,
            "source_document_id": proposal.document_id,
            "timeline_id": payload.get("timeline_id"),
            "character_id": entity.get("character_id"),
            "character_instance_id": entity.get("character_instance_id"),
            "relationship_id": entity.get("relationship_id"),
            "storyline_id": entity.get("storyline_id"),
            "foreshadow_id": entity.get("foreshadow_id"),
            "dimension": payload.get("dimension"),
            "event_kind": payload.get("event_kind"),
            "story_sequence": payload.get("story_sequence"),
            "story_time_json": to_time if fact_type == "story_time" else None,
            "visibility_json": {"scope": visibility},
            "source_start": payload.get("source_start"),
            "source_end": payload.get("source_end"),
            "event_fingerprint": fingerprint,
            "status": "active",
            "created_at": datetime.now(timezone.utc),
            }
        )
    except PydanticValidationError as error:
        raise ValidationError("候选情报不符合 StoryFact v2 类型契约") from error


def _record_incremental_relationship_revision(
    session: Session,
    relation: CharacterRelationship,
) -> CharacterRelationshipRevision:
    current_number = session.scalar(
        select(func.max(CharacterRelationshipRevision.revision_number)).where(
            CharacterRelationshipRevision.relationship_id == relation.id
        )
    )
    relationship_revision = CharacterRelationshipRevision(
        id=uuid4(),
        relationship_id=relation.id,
        revision_number=int(current_number or 0) + 1,
        source_character_id=relation.source_character_id,
        target_character_id=relation.target_character_id,
        timeline_id=relation.timeline_id,
        source_character_instance_id=relation.source_character_instance_id,
        target_character_instance_id=relation.target_character_instance_id,
        directionality=relation.directionality,
        relation_kind=relation.relation_kind,
        label=relation.label,
        description=relation.description,
        status=relation.status,
        change_reason="chapter_sync",
        changed_by="ai_auto",
        manual_override=False,
        confidence=relation.confidence,
        evidence_json=list(relation.evidence_json or []),
        source_generation_job_id=None,
        source_chapter_revision_id=relation.source_chapter_revision_id,
        proposal_item_id=relation.proposal_item_id,
    )
    session.add(relationship_revision)
    session.flush()
    relation.current_revision_id = relationship_revision.id
    return relationship_revision


def _materialize_relationship_candidate(
    session: Session,
    *,
    proposal: IntelligenceProposal,
    item: IntelligenceProposalItem,
    payload: dict[str, object],
) -> tuple[CharacterRelationship, bool]:
    """Resolve a relationship candidate without persisting a new root.

    The caller validates and deduplicates the StoryFact first, then persists a
    newly constructed relationship in the same transaction only when the
    accepted command has an authoritative effect.
    """
    raw_entity = payload.get("entity")
    if not isinstance(raw_entity, dict):
        raise ValidationError("关系候选缺少服务端解析的关系范围")
    entity = dict(raw_entity)
    relationship_id = entity.get("relationship_id")
    if relationship_id:
        try:
            stable_relationship_id = UUID(str(relationship_id))
        except (TypeError, ValueError) as error:
            raise ValidationError("关系候选引用的关系 ID 无效") from error
        relation = session.scalar(
            select(CharacterRelationship)
            .where(
                CharacterRelationship.id == stable_relationship_id,
                CharacterRelationship.novel_id == proposal.novel_id,
                CharacterRelationship.archived_at.is_(None),
            )
            .with_for_update()
        )
        if relation is None:
            raise ValidationError("关系候选引用的关系已失效，请重新同步")
        entity.update(
            {
                "relationship_id": str(relation.id),
                "timeline_id": str(relation.timeline_id) if relation.timeline_id else None,
                "source_character_id": str(relation.source_character_id),
                "target_character_id": str(relation.target_character_id),
                "source_character_instance_id": (
                    str(relation.source_character_instance_id)
                    if relation.source_character_instance_id
                    else None
                ),
                "target_character_instance_id": (
                    str(relation.target_character_instance_id)
                    if relation.target_character_instance_id
                    else None
                ),
                "directionality": relation.directionality,
                "relation_kind": relation.relation_kind,
                "label": relation.label,
                "manual_override": relation.manual_override,
                "is_new": False,
            }
        )
        payload["entity"] = entity
        return relation, False

    try:
        source_id = UUID(str(entity["source_character_id"]))
        target_id = UUID(str(entity["target_character_id"]))
        source_instance_id = UUID(str(entity["source_character_instance_id"]))
        target_instance_id = UUID(str(entity["target_character_instance_id"]))
        timeline_id = UUID(str(entity["timeline_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("新关系候选的人物或时间线范围无效") from error
    directionality = str(entity.get("directionality") or "")
    relation_kind = str(entity.get("relation_kind") or "")
    label = str(entity.get("label") or "").strip()
    if (
        directionality not in RELATIONSHIP_DIRECTIONALITIES
        or relation_kind not in RELATIONSHIP_KINDS
        or not label
        or len(label) > 80
    ):
        raise ValidationError("新关系候选的方向、分类或名称无效")
    original_source_id = source_id
    try:
        source_id, target_id = canonical_relationship_endpoints(
            source_id, target_id, directionality
        )
    except ValueError as error:
        raise ValidationError("新关系候选的两端人物无效") from error
    if source_id != original_source_id:
        source_instance_id, target_instance_id = target_instance_id, source_instance_id

    characters = tuple(
        session.scalars(
            select(NovelCharacter).where(
                NovelCharacter.id.in_((source_id, target_id)),
                NovelCharacter.novel_id == proposal.novel_id,
                NovelCharacter.lifecycle_state == "active",
            )
        )
    )
    if len(characters) != 2:
        raise ValidationError("新关系候选的人物已失效或不属于当前小说")
    timeline = session.scalar(
        select(StoryTimeline).where(
            StoryTimeline.id == timeline_id,
            StoryTimeline.novel_id == proposal.novel_id,
            StoryTimeline.lifecycle_state == "active",
        )
    )
    instances = tuple(
        session.scalars(
            select(CharacterInstance).where(
                CharacterInstance.id.in_((source_instance_id, target_instance_id)),
                CharacterInstance.novel_id == proposal.novel_id,
                CharacterInstance.lifecycle_state == "active",
            )
        )
    )
    instance_by_id = {record.id: record for record in instances}
    if (
        timeline is None
        or len(instances) != 2
        or instance_by_id[source_instance_id].character_id != source_id
        or instance_by_id[target_instance_id].character_id != target_id
        or instance_by_id[source_instance_id].origin_timeline_id != timeline_id
        or instance_by_id[target_instance_id].origin_timeline_id != timeline_id
    ):
        raise ValidationError("新关系候选的人物实例或时间线已失效")

    matches = tuple(
        session.scalars(
            select(CharacterRelationship)
            .where(
                CharacterRelationship.novel_id == proposal.novel_id,
                CharacterRelationship.timeline_id == timeline_id,
                CharacterRelationship.source_character_id == source_id,
                CharacterRelationship.target_character_id == target_id,
                CharacterRelationship.source_character_instance_id == source_instance_id,
                CharacterRelationship.target_character_instance_id == target_instance_id,
                CharacterRelationship.directionality == directionality,
                CharacterRelationship.relation_kind == relation_kind,
                CharacterRelationship.archived_at.is_(None),
            )
            .with_for_update()
        )
    )
    normalized_label = normalize_relationship_label(label)
    exact_matches = tuple(
        relation for relation in matches if relation.normalized_label == normalized_label
    )
    if len(exact_matches) == 1:
        relation = exact_matches[0]
    elif len(matches) == 1:
        relation = matches[0]
    elif matches:
        raise ValidationError("同一人物对存在多个相近关系，请重新同步并选择已有关系")
    else:
        relation = CharacterRelationship(
            id=uuid4(),
            novel_id=proposal.novel_id,
            source_character_id=source_id,
            target_character_id=target_id,
            timeline_id=timeline_id,
            source_character_instance_id=source_instance_id,
            target_character_instance_id=target_instance_id,
            directionality=directionality,
            relation_kind=relation_kind,
            label=label,
            normalized_label=normalized_label,
            relation_pair_key=relationship_pair_key(source_id, target_id),
            description=str(payload.get("object") or "").strip(),
            status="active",
            created_by="ai_auto",
            manual_override=False,
            confidence=item.confidence,
            evidence_json=[item.source_text],
            source_chapter_revision_id=proposal.chapter_revision_id,
            proposal_item_id=item.id,
            version=1,
        )
        created = True
        entity["is_new"] = True
        entity["manual_override"] = False
        entity["relationship_id"] = str(relation.id)
        payload["entity"] = entity
        return relation, created

    entity.update(
        {
            "relationship_id": str(relation.id),
            "label": relation.label,
            "manual_override": relation.manual_override,
            "is_new": False,
        }
    )
    payload["entity"] = entity
    return relation, False


def _intelligence_commit_result(
    session: Session,
    proposal: IntelligenceProposal,
    novel: Novel,
    batch: IntelligenceCommitBatch,
    *,
    replayed: bool,
) -> dict[str, Any]:
    inverse = dict(batch.inverse_operations or {})
    originally_changed = bool(inverse.get("changed"))
    if replayed:
        outcome = "no_change" if batch.state == "no_change" else "already_committed"
    else:
        outcome = "committed" if originally_changed else "no_change"
    payload = _intelligence_proposal_payload(session, proposal)
    payload["commit_batch"] = _intelligence_commit_batch_payload(batch)
    payload["relationship_sync"] = {
        "created": len(inverse.get("created_relationship_ids") or []),
        "updated": len(inverse.get("updated_relationship_ids") or []),
        "skipped": int(inverse.get("skipped_relationship_count") or 0),
    }
    payload["rejected_invalid_item_ids"] = list(
        inverse.get("rejected_invalid_item_ids") or []
    )
    payload["changed"] = False if replayed else originally_changed
    payload["replayed"] = replayed
    payload["outcome"] = outcome
    payload["story_ledger_version"] = novel.story_ledger_version
    payload["commit_story_ledger_version"] = int(
        inverse.get("result_story_ledger_version") or novel.story_ledger_version
    )
    return payload


def commit_intelligence_items(
    session: Session,
    proposal_id: UUID,
    *,
    accepted_item_ids: list[UUID],
    expected_story_ledger_version: int | None = None,
    operation_key: str | None = None,
) -> dict[str, Any]:
    selected = set(accepted_item_ids)
    if not selected:
        raise ValidationError("accepted intelligence item ids cannot be empty")
    payload_hash = _intelligence_commit_payload_hash(
        proposal_id,
        selected,
    )
    commit_key, normalized_operation_key = _intelligence_operation_key(
        operation_key,
        payload_hash=payload_hash,
    )
    proposal_snapshot = session.get(IntelligenceProposal, proposal_id)
    if proposal_snapshot is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    novel = session.scalar(
        select(Novel).where(Novel.id == proposal_snapshot.novel_id).with_for_update()
    )
    if novel is None:
        raise NotFoundError(f"novel {proposal_snapshot.novel_id} not found")
    proposal = session.scalar(
        select(IntelligenceProposal)
        .where(IntelligenceProposal.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    existing_batch = session.scalar(
        select(IntelligenceCommitBatch)
        .where(
            IntelligenceCommitBatch.proposal_id == proposal.id,
            IntelligenceCommitBatch.commit_key == commit_key,
        )
        .with_for_update()
    )
    if existing_batch is not None:
        existing_inverse = dict(existing_batch.inverse_operations or {})
        existing_payload_hash = existing_inverse.get("payload_hash")
        if existing_payload_hash is None and normalized_operation_key is None:
            existing_payload_hash = existing_batch.commit_key
        if (
            existing_payload_hash != payload_hash
            or existing_inverse.get("operation_key") != normalized_operation_key
        ):
            raise IntelligenceCommitConflictError(
                "idempotency_conflict",
                "operation_key 已被另一份章节情报提交内容使用",
            )
        if existing_batch.state in {"committed", "no_change", "reverted"}:
            result = _intelligence_commit_result(
                session,
                proposal,
                novel,
                existing_batch,
                replayed=True,
            )
            session.commit()
            return result

    if (
        expected_story_ledger_version is not None
        and novel.story_ledger_version != expected_story_ledger_version
    ):
        raise IntelligenceCommitConflictError(
            "story_ledger_version_conflict",
            "故事账本版本已经变化",
            current={"story_ledger_version": novel.story_ledger_version},
        )
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == proposal.document_id)
        .with_for_update()
    )
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
    items = session.scalars(
        select(IntelligenceProposalItem)
        .where(IntelligenceProposalItem.proposal_id == proposal_id)
        .with_for_update()
    ).all()
    known_ids = {item.id for item in items}
    if not selected.issubset(known_ids):
        raise ValidationError("accepted intelligence item ids do not belong to this proposal")

    batch = existing_batch or IntelligenceCommitBatch(
        id=uuid4(),
        proposal_id=proposal.id,
        chapter_revision_id=proposal.chapter_revision_id,
        commit_key=commit_key,
        state="committing",
        accepted_item_ids=sorted(str(item_id) for item_id in selected),
        inverse_operations={
            "schema_version": "intelligence-commit-inverse/2",
            "operation_key": normalized_operation_key,
            "payload_hash": payload_hash,
            "created_story_fact_ids": [],
            "created_relationship_ids": [],
            "updated_relationship_ids": [],
            "skipped_relationship_count": 0,
            "rejected_invalid_item_ids": [],
            "changed": False,
        },
        expected_story_ledger_version=(
            expected_story_ledger_version
            if expected_story_ledger_version is not None
            else novel.story_ledger_version
        ),
    )
    if existing_batch is None:
        session.add(batch)
        session.flush()
    else:
        batch.state = "committing"
        batch.accepted_item_ids = sorted(str(item_id) for item_id in selected)
        batch.inverse_operations = {
            "schema_version": "intelligence-commit-inverse/2",
            "operation_key": normalized_operation_key,
            "payload_hash": payload_hash,
            "created_story_fact_ids": [],
            "created_relationship_ids": [],
            "updated_relationship_ids": [],
            "skipped_relationship_count": 0,
            "rejected_invalid_item_ids": [],
            "changed": False,
        }
        batch.expected_story_ledger_version = (
            expected_story_ledger_version
            if expected_story_ledger_version is not None
            else novel.story_ledger_version
        )
    created_fact_ids: list[str] = []
    created_relationship_ids: set[str] = set()
    updated_relationship_ids: set[str] = set()
    skipped_relationship_count = 0
    rejected_invalid_item_ids: list[str] = []
    for item in items:
        if item.id not in selected:
            continue
        if item.committed_story_fact_id:
            continue
        payload = dict(item.suggested_payload)
        if item.item_type == "story_time" and _story_time_invents_calendar_year(
            item.source_text,
            payload,
        ):
            item.review_state = "rejected"
            rejected_invalid_item_ids.append(str(item.id))
            continue
        subject = str(payload.get("subject", "")).strip()
        predicate = str(payload.get("predicate", "")).strip()
        object_text = str(payload.get("object", "")).strip()
        if not subject or not predicate or not object_text:
            raise ValidationError("accepted intelligence item requires subject, predicate and object")
        relationship: CharacterRelationship | None = None
        relationship_created = False
        if item.item_type == "relationship_state":
            relationship, relationship_created = _materialize_relationship_candidate(
                session,
                proposal=proposal,
                item=item,
                payload=payload,
            )
        candidate = _typed_story_fact_candidate(
            proposal=proposal, revision=revision, item=item, payload=payload
        )
        fact = session.scalar(
            select(StoryFact)
            .where(
                StoryFact.novel_id == proposal.novel_id,
                StoryFact.event_fingerprint == candidate.event_fingerprint,
            )
            .with_for_update()
        )
        if fact is None:
            if relationship is not None and relationship_created:
                session.add(relationship)
                session.flush()
                _record_incremental_relationship_revision(session, relationship)
            candidate_data = candidate.model_dump(mode="python")
            candidate_data["details"] = candidate.details.model_dump(mode="json")
            candidate_data["visibility_json"] = candidate.visibility_json.model_dump(mode="json")
            story_time = candidate.story_time_json
            candidate_data["story_time_json"] = (
                story_time.model_dump(mode="json") if story_time is not None else None
            )
            candidate_data["schema_version"] = "story-fact/2"
            candidate_data["fact_type"] = candidate.fact_type.value
            candidate_data["status"] = candidate.status.value
            fact = StoryFact(**candidate_data)
            session.add(fact)
            session.flush()
            session.add(
                DerivedSourceBinding(
                    id=uuid4(),
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
            if relationship is not None:
                if relationship_created:
                    created_relationship_ids.add(str(relationship.id))
                elif str(relationship.id) not in created_relationship_ids:
                    updated_relationship_ids.add(str(relationship.id))
        elif relationship is not None:
            skipped_relationship_count += 1
            if relationship_created:
                entity = payload.get("entity")
                if isinstance(entity, dict):
                    entity = dict(entity)
                    entity["relationship_id"] = (
                        str(fact.relationship_id) if fact.relationship_id else None
                    )
                    entity["is_new"] = False
                    payload["entity"] = entity
        item.review_state = "accepted"
        item.suggested_payload = payload
        item.committed_story_fact_id = fact.id
    pending = sum(1 for item in items if item.review_state == "pending")
    accepted = sum(1 for item in items if item.review_state == "accepted")
    if pending:
        proposal.state = "partially_accepted" if accepted else "ready"
    else:
        proposal.state = "accepted" if accepted else "rejected"
    proposal.reviewed_at = datetime.now(timezone.utc)
    authoritative_changed = bool(
        created_fact_ids or created_relationship_ids or updated_relationship_ids
    )
    batch.state = "committed" if authoritative_changed else "no_change"
    inverse_operations = {
        "schema_version": "intelligence-commit-inverse/2",
        "operation_key": normalized_operation_key,
        "payload_hash": payload_hash,
        "created_story_fact_ids": created_fact_ids,
        "created_relationship_ids": sorted(created_relationship_ids),
        "updated_relationship_ids": sorted(updated_relationship_ids),
        "skipped_relationship_count": skipped_relationship_count,
        "rejected_invalid_item_ids": rejected_invalid_item_ids,
        "changed": authoritative_changed,
    }
    batch.committed_at = proposal.reviewed_at
    if authoritative_changed:
        novel.story_ledger_version += 1
    inverse_operations["result_story_ledger_version"] = novel.story_ledger_version
    batch.inverse_operations = inverse_operations
    session.commit()
    return _intelligence_commit_result(
        session,
        proposal,
        novel,
        batch,
        replayed=False,
    )


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
    base_revision = _document_base_revision(session, working)
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(
            _versioned_document_payload(document, working, base_revision)
        )
    server_hash = content_hash(content_markdown)
    if client_hash is not None and client_hash != server_hash:
        raise ValidationError("content_hash does not match content_markdown")
    if working.content_hash == server_hash:
        return _versioned_document_payload(document, working, base_revision)
    _supersede_intelligence_for_document(session, document_id)
    working.content_markdown = content_markdown
    working.content_hash = server_hash
    working.draft_version += 1
    document.novel.updated_at = func.now()
    session.commit()
    return _versioned_document_payload(document, working, base_revision)


def create_checkpoint(
    session: Session, document_id: UUID, *, expected_draft_version: int
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    novel = _lock_novel(session, document.novel_id)
    working = session.scalar(
        select(DocumentWorkingCopy)
        .where(DocumentWorkingCopy.document_id == document_id)
        .with_for_update()
    )
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if working.draft_version != expected_draft_version:
        raise DraftConflictError(
            _versioned_document_payload(
                document,
                working,
                _document_base_revision(session, working),
            )
        )
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
    _supersede_intelligence_for_document(session, document_id)
    reconciliation = _reconcile_story_facts_for_revision(
        session, document_id, revision
    )
    if reconciliation["changed"]:
        novel.story_ledger_version += 1
    working.base_revision_id = revision.id
    working.draft_version += 1
    from .embedding.indexing import request_active_novel_refresh
    request_active_novel_refresh(session, document.novel_id)
    session.commit()
    return {
        "document": get_document(session, document_id),
        "revision": _revision_payload(revision, include_content=True),
        "story_ledger_version": novel.story_ledger_version,
        "reconciliation": reconciliation,
    }


def restore_revision(
    session: Session,
    document_id: UUID,
    revision_id: UUID,
    *,
    expected_draft_version: int,
    expected_fact_plan_hash: str | None = None,
) -> dict[str, Any]:
    document = _require_document(session, document_id)
    novel = _lock_novel(session, document.novel_id)
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
        raise DraftConflictError(
            _versioned_document_payload(
                document,
                working,
                _document_base_revision(session, working),
            )
        )
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
    _supersede_intelligence_for_document(session, document_id)
    reconciliation = _reconcile_story_facts_for_revision(
        session, document_id, restored, restored=True
    )
    if reconciliation["changed"]:
        novel.story_ledger_version += 1
    working.base_revision_id = restored.id
    working.content_markdown = restored.content_markdown
    working.content_hash = restored.content_hash
    working.draft_version += 1
    from .embedding.indexing import request_active_novel_refresh
    request_active_novel_refresh(session, document.novel_id)
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
        "story_ledger_version": novel.story_ledger_version,
        "reconciliation": reconciliation,
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
    documents = session.scalars(
        select(Document).where(Document.novel_id == novel_id)
    ).all()
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id).order_by(Volume.position)
    ).all()
    tree = canonical_tree(volumes, documents)
    chapter_ordinals = tree.chapter_ordinals
    title_by_document_id = {
        document.id: (
            display_chapter_title(document.title, chapter_ordinals[document.id])
            if document.kind == "chapter" and document.id in chapter_ordinals
            else document.title
        )
        for document in documents
    }
    title_match_ids = [
        document_id
        for document_id, title in title_by_document_id.items()
        if query.casefold() in title.casefold()
    ]
    pattern = f"%{query}%"
    rows = session.execute(
        select(Document, DocumentWorkingCopy)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(
            Document.novel_id == novel_id,
            or_(
                DocumentWorkingCopy.content_markdown.ilike(pattern),
                Document.id.in_(title_match_ids),
            ),
        )
        .order_by(Document.position)
    ).all()
    rows.sort(
        key=lambda row: (
            0,
            chapter_ordinals[row[0].id],
        )
        if row[0].id in chapter_ordinals
        else (1, row[0].position)
    )
    results: list[dict[str, Any]] = []
    for document, working in rows:
        plain = markdown_to_text(working.content_markdown)
        title = title_by_document_id[document.id]
        index = plain.lower().find(query.lower())
        start = max(0, index - 120) if index >= 0 else 0
        results.append(
            {
                "document_id": str(document.id),
                "title": title,
                "kind": document.kind,
                "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
                "snippet": plain[start : start + 360],
            }
        )
        if len(results) >= max(1, min(limit, 50)):
            break
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
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id)
    ).all()
    tree = canonical_tree(volumes, documents)
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
        revision = (
            session.get(DocumentRevision, working.base_revision_id)
            if working.base_revision_id
            else None
        )
        formal_markdown = revision.content_markdown if revision is not None else ""
        text = formal_markdown[-remaining:]
        selected.append(
            {
                "document_id": str(document.id),
                "title": (
                    context_chapter_title(
                        document.title,
                        tree.chapter_ordinals[document.id],
                    )
                    if document.kind == "chapter"
                    and document.id in tree.chapter_ordinals
                    else document.title
                ),
                "kind": document.kind,
                "base_revision_id": str(working.base_revision_id) if working.base_revision_id else None,
                "content_markdown": text,
            }
        )
        remaining -= len(text)
        if remaining <= 0:
            break
    selected.reverse()
    envelope = None
    if session.scalar(
        select(StoryTimeline.id).where(
            StoryTimeline.novel_id == novel_id,
            StoryTimeline.lifecycle_state == "active",
        ).limit(1)
    ) is not None:
        try:
            envelope = assemble_context_from_db(
                session, novel_id, document_id=document_id
            )
        except ValueError as error:
            raise ValidationError("章节时间线或人物实例约束无效") from error
    if envelope is not None:
        projected_facts = [
            *(fact for item in envelope.character_state for fact in item.current_state_facts),
            *envelope.story_state.current_facts,
            *envelope.chapter_requirements.author_secret_facts,
        ]
        fact_payloads = [
            {
                "id": str(fact.id),
                "type": fact.fact_type.value,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object_text,
                "source_revision_id": str(fact.source_revision_id) if fact.source_revision_id else None,
                "timeline_id": str(fact.timeline_id) if fact.timeline_id else None,
                "character_instance_id": (
                    str(fact.character_instance_id) if fact.character_instance_id else None
                ),
            }
            for fact in projected_facts
        ]
    else:
        # Temporary read compatibility for experimental rows created before
        # migration 0026.  It is removed when the separately authorized test
        # database rebuild occurs; no new write path creates such rows.
        facts = session.scalars(
            select(StoryFact)
            .where(
                StoryFact.novel_id == novel_id,
                StoryFact.status.in_(CURRENT_FACT_STATUSES),
            )
            .order_by(StoryFact.created_at)
            .limit(200)
        ).all()
        fact_payloads = [
            {
                "id": str(fact.id),
                "type": fact.fact_type,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object_text,
                "source_revision_id": str(fact.source_revision_id) if fact.source_revision_id else None,
            }
            for fact in facts
        ]
    return {
        "novel": {"id": str(novel.id), "title": novel.title, "description": novel.description},
        "current_document_id": str(document_id) if document_id else None,
        "documents": selected,
        "story_facts": fact_payloads,
        "context_v3": envelope.model_dump(mode="json") if envelope is not None else None,
        "retrieval": (
            "deterministic/context-v3; semantic evidence is supplemental"
            if envelope is not None
            else "legacy-current-revision; awaiting authorized experimental data rebuild"
        ),
    }
