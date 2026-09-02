"""Auditable StoryFact correction and intelligence-batch revert commands."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..creative_data_models import StoryEventLink
from ..models import (
    CharacterRelationship,
    DerivedSourceBinding,
    DocumentRevision,
    IntelligenceCommitBatch,
    IntelligenceProposal,
    Novel,
    StoryFact,
)
from .contracts import StoryFactV2
from .fact_authority import resolve_fact_authority_rows


class StoryCorrectionErrorCode(str, Enum):
    NOT_FOUND = "story_fact_not_found"
    BATCH_NOT_FOUND = "intelligence_commit_batch_not_found"
    VERSION_CONFLICT = "story_ledger_version_conflict"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INVALID_TARGET = "story_fact_not_correctable"
    INVALID_REPLACEMENT = "invalid_story_fact_replacement"
    SOURCE_INVALID = "story_fact_source_invalid"


class StoryCorrectionError(ValueError):
    def __init__(
        self,
        code: StoryCorrectionErrorCode,
        message: str,
        *,
        current: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current = dict(current or {})


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _fact_payload(row: StoryFact) -> dict[str, object]:
    return {
        "id": str(row.id),
        "novel_id": str(row.novel_id),
        "fact_type": row.fact_type,
        "subject": row.subject,
        "predicate": row.predicate,
        "object_text": row.object_text,
        "details": dict(row.details or {}),
        "timeline_id": str(row.timeline_id) if row.timeline_id else None,
        "character_id": str(row.character_id) if row.character_id else None,
        "character_instance_id": (
            str(row.character_instance_id) if row.character_instance_id else None
        ),
        "relationship_id": str(row.relationship_id) if row.relationship_id else None,
        "dimension": row.dimension,
        "event_kind": row.event_kind,
        "story_sequence": row.story_sequence,
        "story_time": row.story_time_json,
        "visibility": row.visibility_json,
        "source_document_id": (
            str(row.source_document_id) if row.source_document_id else None
        ),
        "source_revision_id": (
            str(row.source_revision_id) if row.source_revision_id else None
        ),
        "source_start": row.source_start,
        "source_end": row.source_end,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _validated_source(
    session: Session,
    target: StoryFact,
) -> tuple[DocumentRevision | None, DerivedSourceBinding | None]:
    has_any = any(
        value is not None
        for value in (
            target.source_document_id,
            target.source_revision_id,
            target.source_start,
            target.source_end,
        )
    )
    has_all = all(
        value is not None
        for value in (
            target.source_document_id,
            target.source_revision_id,
            target.source_start,
            target.source_end,
        )
    )
    if not has_any:
        return None, None
    if not has_all:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.SOURCE_INVALID,
            "事实来源字段不完整，不能安全修正",
        )
    revision = session.get(DocumentRevision, target.source_revision_id)
    if (
        revision is None
        or revision.document_id != target.source_document_id
        or target.source_start is None
        or target.source_end is None
        or target.source_start < 0
        or target.source_end <= target.source_start
        or target.source_end > len(revision.content_text)
    ):
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.SOURCE_INVALID,
            "事实来源版本或证据区间已经失效",
        )
    binding = session.scalar(
        select(DerivedSourceBinding)
        .where(
            DerivedSourceBinding.derived_entity_id == target.id,
            DerivedSourceBinding.source_chapter_revision_id == revision.id,
        )
        .with_for_update()
    )
    if binding is None:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.SOURCE_INVALID,
            "事实缺少可审计的来源绑定，不能安全继承该证据",
        )
    if (
        binding.source_chapter_id != revision.document_id
        or binding.source_content_hash != revision.content_hash
    ):
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.SOURCE_INVALID,
            "事实来源绑定与来源版本不一致",
        )
    return revision, binding


def correct_story_fact(
    session: Session,
    novel_id: UUID,
    fact_id: UUID,
    *,
    expected_story_ledger_version: int,
    operation_key: str,
    reason: str,
    replacement: Mapping[str, object],
) -> dict[str, object]:
    novel = session.scalar(select(Novel).where(Novel.id == novel_id).with_for_update())
    if novel is None:
        raise StoryCorrectionError(StoryCorrectionErrorCode.NOT_FOUND, "小说不存在")
    target = session.scalar(
        select(StoryFact)
        .where(StoryFact.id == fact_id, StoryFact.novel_id == novel_id)
        .with_for_update()
    )
    if target is None:
        raise StoryCorrectionError(StoryCorrectionErrorCode.NOT_FOUND, "事实不存在")

    event_fingerprint = sha256(
        f"manual-correction-v1|{novel_id}|{fact_id}|{operation_key}".encode("utf-8")
    ).hexdigest()
    operation_hash = _canonical_hash(
        {
            "target_fact_id": fact_id,
            "replacement": dict(replacement),
            "reason": reason,
        }
    )
    replay = session.scalar(
        select(StoryFact).where(
            StoryFact.novel_id == novel_id,
            StoryFact.event_fingerprint == event_fingerprint,
        )
    )
    if replay is not None:
        link = session.scalar(
            select(StoryEventLink).where(
                StoryEventLink.novel_id == novel_id,
                StoryEventLink.source_fact_id == replay.id,
                StoryEventLink.target_fact_id == target.id,
                StoryEventLink.link_type == "supersedes",
            )
        )
        if link is None or dict(link.details_json or {}).get("operation_hash") != operation_hash:
            raise StoryCorrectionError(
                StoryCorrectionErrorCode.IDEMPOTENCY_CONFLICT,
                "operation_key 已被另一份修正内容使用",
            )
        return {
            "replayed": True,
            "story_ledger_version": novel.story_ledger_version,
            "fact": _fact_payload(replay),
        }

    if novel.story_ledger_version != expected_story_ledger_version:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.VERSION_CONFLICT,
            "故事账本版本已经变化",
            current={"story_ledger_version": novel.story_ledger_version},
        )
    if target.schema_version != "story-fact/2":
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_TARGET,
            "只有 StoryFact v2 可以修正",
        )
    incoming = session.scalar(
        select(StoryEventLink.id).where(
            StoryEventLink.novel_id == novel_id,
            StoryEventLink.target_fact_id == target.id,
            StoryEventLink.link_type == "supersedes",
        )
    )
    if incoming is not None:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_TARGET,
            "该事实已经被其他事实替代",
        )
    revision, binding = _validated_source(session, target)
    batch_states: dict[UUID, str] = {}
    if binding is not None and binding.commit_batch_id is not None:
        owning_batch = session.get(IntelligenceCommitBatch, binding.commit_batch_id)
        if owning_batch is not None:
            batch_states[owning_batch.id] = owning_batch.state
    authority = resolve_fact_authority_rows(
        (target,),
        bindings=((binding,) if binding is not None else ()),
        batch_states=batch_states,
    )[target.id]
    if not authority.included_in_current_projection:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_TARGET,
            "只有当前有效或历史可见的 StoryFact v2 可以修正",
            current={
                "effective_state": authority.effective_state.value,
                "reason_codes": [reason.value for reason in authority.reason_codes],
            },
        )
    current_editable = {
        "predicate": target.predicate,
        "object_text": target.object_text,
        "details": dict(target.details or {}),
        "dimension": target.dimension,
        "event_kind": target.event_kind,
        "story_sequence": target.story_sequence,
        "story_time": target.story_time_json,
        "visibility": target.visibility_json,
    }
    next_editable = {
        key: replacement.get(key, value)
        for key, value in current_editable.items()
    }
    if _canonical_hash(current_editable) == _canonical_hash(next_editable):
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_REPLACEMENT,
            "替代事实必须至少修改一个可编辑字段",
        )
    merged = {
        "id": uuid4(),
        "novel_id": target.novel_id,
        "schema_version": "story-fact/2",
        "fact_type": target.fact_type,
        "subject": target.subject,
        "predicate": replacement.get("predicate", target.predicate),
        "object_text": replacement.get("object_text", target.object_text),
        "details": replacement.get("details", dict(target.details or {})),
        "source_revision_id": target.source_revision_id,
        "source_document_id": target.source_document_id,
        "timeline_id": target.timeline_id,
        "character_id": target.character_id,
        "character_instance_id": target.character_instance_id,
        "relationship_id": target.relationship_id,
        "storyline_id": target.storyline_id,
        "foreshadow_id": target.foreshadow_id,
        "dimension": replacement.get("dimension", target.dimension),
        "event_kind": replacement.get("event_kind", target.event_kind),
        "story_sequence": replacement.get("story_sequence", target.story_sequence),
        "story_time_json": replacement.get("story_time", target.story_time_json),
        "visibility_json": replacement.get("visibility", target.visibility_json),
        "source_start": target.source_start,
        "source_end": target.source_end,
        "event_fingerprint": event_fingerprint,
        "status": target.status,
        "created_at": datetime.now(UTC),
    }
    try:
        validated = StoryFactV2.model_validate(merged)
    except ValueError as error:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_REPLACEMENT,
            "替代事实不符合 StoryFact v2 协议",
        ) from error
    data = validated.model_dump(mode="python")
    data["fact_type"] = validated.fact_type.value
    data["details"] = validated.details.model_dump(mode="json")
    data["story_time_json"] = (
        validated.story_time_json.model_dump(mode="json")
        if validated.story_time_json is not None
        else None
    )
    data["visibility_json"] = validated.visibility_json.model_dump(mode="json")
    data["status"] = validated.status.value
    replacement_row = StoryFact(**data)
    session.add(replacement_row)
    session.flush()

    if revision is not None:
        session.add(
            DerivedSourceBinding(
                id=uuid4(),
                derived_entity_id=replacement_row.id,
                source_chapter_id=revision.document_id,
                source_chapter_revision_id=revision.id,
                source_content_hash=revision.content_hash,
                proposal_item_id=None,
                commit_batch_id=None,
                validity_state=(
                    binding.validity_state if binding is not None else "current"
                ),
                restored_at=(
                    datetime.now(UTC)
                    if binding is not None
                    and binding.validity_state == "source_restored"
                    else None
                ),
            )
        )
    session.add(
        StoryEventLink(
            id=uuid4(),
            novel_id=novel_id,
            source_fact_id=replacement_row.id,
            target_fact_id=target.id,
            link_type="supersedes",
            details_json={
                "schema_version": "manual-correction-link/1",
                "reason": reason,
                "operation_key": operation_key,
                "operation_hash": operation_hash,
            },
            created_at=datetime.now(UTC),
        )
    )
    novel.story_ledger_version += 1
    session.flush()
    return {
        "replayed": False,
        "story_ledger_version": novel.story_ledger_version,
        "fact": _fact_payload(replacement_row),
    }


def _batch_scope(
    session: Session,
    novel_id: UUID,
    batch_id: UUID,
    *,
    lock: bool,
) -> tuple[IntelligenceCommitBatch, IntelligenceProposal]:
    statement = (
        select(IntelligenceCommitBatch, IntelligenceProposal)
        .join(
            IntelligenceProposal,
            IntelligenceProposal.id == IntelligenceCommitBatch.proposal_id,
        )
        .where(
            IntelligenceCommitBatch.id == batch_id,
            IntelligenceProposal.novel_id == novel_id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    row = session.execute(statement).one_or_none()
    if row is None:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.BATCH_NOT_FOUND,
            "同步批次不存在",
        )
    return row[0], row[1]


def intelligence_batch_revert_impact(
    session: Session,
    novel_id: UUID,
    batch_id: UUID,
) -> dict[str, object]:
    batch, _proposal = _batch_scope(session, novel_id, batch_id, lock=False)
    inverse = dict(batch.inverse_operations or {})
    fact_ids = [UUID(value) for value in inverse.get("created_story_fact_ids", [])]
    facts = list(
        session.scalars(
            select(StoryFact).where(
                StoryFact.novel_id == novel_id,
                StoryFact.id.in_(fact_ids),
            )
        )
    ) if fact_ids else []
    owned_ids = set(
        session.scalars(
            select(DerivedSourceBinding.derived_entity_id).where(
                DerivedSourceBinding.commit_batch_id == batch.id,
                DerivedSourceBinding.derived_entity_id.in_(fact_ids),
            )
        )
    ) if fact_ids else set()
    followup_targets = set(
        session.scalars(
            select(StoryEventLink.target_fact_id).where(
                StoryEventLink.novel_id == novel_id,
                StoryEventLink.target_fact_id.in_(fact_ids),
                StoryEventLink.link_type == "supersedes",
            )
        )
    ) if fact_ids else set()
    relation_ids = {
        UUID(value)
        for key in ("created_relationship_ids", "updated_relationship_ids")
        for value in inverse.get(key, [])
    }
    relations = list(
        session.scalars(
            select(CharacterRelationship).where(
                CharacterRelationship.novel_id == novel_id,
                CharacterRelationship.id.in_(relation_ids),
            )
        )
    ) if relation_ids else []
    return {
        "batch_id": str(batch.id),
        "state": batch.state,
        "already_reverted": batch.state == "reverted",
        "facts": [
            {
                **_fact_payload(fact),
                "batch_owned": fact.id in owned_ids,
                "disposition": (
                    "preserve_followup"
                    if fact.id in followup_targets
                    else "supersede"
                    if fact.id in owned_ids
                    else "preserve"
                ),
            }
            for fact in facts
        ],
        "relationships": [
            {
                "id": str(relation.id),
                "label": relation.label,
                "manual_override": relation.manual_override,
                "disposition": "preserve_root_reproject_visibility",
            }
            for relation in relations
        ],
    }


def revert_intelligence_batch(
    session: Session,
    novel_id: UUID,
    batch_id: UUID,
    *,
    expected_story_ledger_version: int,
    operation_key: str,
    reason: str | None = None,
) -> dict[str, object]:
    novel = session.scalar(select(Novel).where(Novel.id == novel_id).with_for_update())
    if novel is None:
        raise StoryCorrectionError(StoryCorrectionErrorCode.BATCH_NOT_FOUND, "小说不存在")
    batch, _proposal = _batch_scope(session, novel_id, batch_id, lock=True)
    cleaned_reason = reason.strip() if reason is not None else None
    operation_hash = _canonical_hash(
        {
            "batch_id": str(batch.id),
            "reason": cleaned_reason,
        }
    )
    if batch.state == "reverted":
        audit = dict((batch.inverse_operations or {}).get("revert_audit") or {})
        stored_hash = audit.get("operation_hash")
        if stored_hash is None and audit.get("operation_key"):
            stored_hash = _canonical_hash(
                {
                    "batch_id": str(batch.id),
                    "reason": audit.get("reason"),
                }
            )
        if (
            audit.get("operation_key") != operation_key
            or stored_hash != operation_hash
        ):
            raise StoryCorrectionError(
                StoryCorrectionErrorCode.IDEMPOTENCY_CONFLICT,
                "operation_key 已被另一份批次撤销内容使用",
            )
        return {
            "replayed": True,
            "changed": False,
            "outcome": "already_reverted",
            "batch_id": str(batch.id),
            "state": batch.state,
            "story_ledger_version": novel.story_ledger_version,
        }
    if batch.state != "committed":
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_TARGET,
            "只有已提交的同步批次可以撤销",
        )
    if novel.story_ledger_version != expected_story_ledger_version:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.VERSION_CONFLICT,
            "故事账本版本已经变化",
            current={"story_ledger_version": novel.story_ledger_version},
        )
    inverse = dict(batch.inverse_operations or {})
    fact_ids = [UUID(value) for value in inverse.get("created_story_fact_ids", [])]
    owned_ids = (
        set(
            session.scalars(
                select(DerivedSourceBinding.derived_entity_id)
                .where(
                    DerivedSourceBinding.commit_batch_id == batch.id,
                    DerivedSourceBinding.derived_entity_id.in_(fact_ids),
                )
                .with_for_update()
            )
        )
        if fact_ids
        else set()
    )
    if not owned_ids:
        raise StoryCorrectionError(
            StoryCorrectionErrorCode.INVALID_TARGET,
            "同步批次没有可撤销的权威事实",
        )
    now = datetime.now(UTC)
    batch.state = "reverted"
    batch.reverted_at = now
    batch.inverse_operations = {
        **inverse,
        "revert_audit": {
            "schema_version": "intelligence-batch-revert/2",
            "operation_key": operation_key,
            "operation_hash": operation_hash,
            "reason": cleaned_reason,
            "reverted_at": now.isoformat(),
        },
    }
    novel.story_ledger_version += 1
    session.flush()
    return {
        "replayed": False,
        "changed": True,
        "outcome": "reverted",
        "batch_id": str(batch.id),
        "state": batch.state,
        "story_ledger_version": novel.story_ledger_version,
    }


__all__ = [
    "StoryCorrectionError",
    "StoryCorrectionErrorCode",
    "correct_story_fact",
    "intelligence_batch_revert_impact",
    "revert_intelligence_batch",
]
