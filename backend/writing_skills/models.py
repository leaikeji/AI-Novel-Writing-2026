"""Durable action claims, separate from authoritative novel revisions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..models import Base

STATES = ("claimed", "routing_started", "route_ready", "assembled", "dispatch_started",
          "dispatched", "failed", "cancelled", "unknown", "stale")


class WritingSkillDispatch(Base):
    __tablename__ = "writing_skill_dispatches"
    __table_args__ = (
        UniqueConstraint("owner_id", "workspace_id", "agent_id", "entry", "action_id",
                         name="uq_writing_skill_action"),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"],
                             ["novels.id", "novels.owner_id", "novels.workspace_id"],
                             ondelete="CASCADE", name="fk_writing_skill_novel_scope"),
        CheckConstraint("owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid AND "
                        "workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
                        name="ck_writing_skill_local_scope"),
        CheckConstraint("agent_id = 'ai-novel-writer' AND entry IN ('button','native')",
                        name="ck_writing_skill_entry"),
        CheckConstraint("(scope_kind = 'novel' AND novel_id IS NOT NULL AND scope_id = novel_id) OR "
                        "(scope_kind = 'creation_draft' AND novel_id IS NULL)",
                        name="ck_writing_skill_scope"),
        CheckConstraint("state IN (" + ",".join(repr(s) for s in STATES) + ")",
                        name="ck_writing_skill_state"),
        CheckConstraint("fence >= 1", name="ck_writing_skill_fence"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(40), nullable=False)
    entry: Mapped[str] = mapped_column(String(16), nullable=False)
    action_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    client_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    route_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="claimed")
    fence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    method_packet: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    job_ref: Mapped[str | None] = mapped_column(String(240))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
