"""SQLAlchemy models for the MVP-0 novel authority ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Novel(Base):
    __tablename__ = "novels"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "workspace_id", name="uq_novel_local_scope"),
        Index("ix_novels_local_scope", "owner_id", "workspace_id"),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_novel_fixed_local_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, server_default=text("'29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid"))
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, server_default=text("'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid"))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    author_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    writing_type: Mapped[str] = mapped_column(String(20), nullable=False, default="long")
    audience: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    genre: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    subgenre: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    idea: Mapped[str] = mapped_column(Text, nullable=False, default="")
    template_key: Mapped[str | None] = mapped_column(String(120))
    template_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    template_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cover_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    cover_image_data: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    outline_target_chapters: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    highlight: Mapped[str] = mapped_column(Text, nullable=False, default="")
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    main_plot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    story_ledger_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    character_catalog_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    volumes: Mapped[list[Volume]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )


class Volume(Base):
    __tablename__ = "volumes"
    __table_args__ = (
        UniqueConstraint("novel_id", "position", name="uq_volume_position"),
        UniqueConstraint("id", "novel_id", name="uq_volume_novel_scope"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="volumes")
    documents: Mapped[list[Document]] = relationship(back_populates="volume")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("novel_id", "kind", "position", name="uq_document_position"),
        UniqueConstraint("id", "novel_id", name="uq_document_novel_scope"),
        Index("ix_documents_novel_kind", "novel_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    volume_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("volumes.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="chapter")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="documents")
    volume: Mapped[Volume | None] = relationship(back_populates="documents")
    working_copy: Mapped[DocumentWorkingCopy] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    revisions: Mapped[list[DocumentRevision]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_number", name="uq_document_revision_number"),
        UniqueConstraint("id", "document_id", name="uq_document_revision_document_scope"),
        UniqueConstraint(
            "id", "document_id", "content_hash", name="uq_document_revision_source_guard"
        ),
        Index(
            "uq_document_revision_tts_snapshot",
            "document_id",
            "content_hash",
            "source",
            unique=True,
            postgresql_where=text("source='tts_snapshot'"),
            sqlite_where=text("source='tts_snapshot'"),
        ),
        Index("ix_document_revisions_document_created", "document_id", "created_at"),
        Index("ix_document_revisions_restored_from", "restored_from_revision_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="revisions")


class DocumentWorkingCopy(Base):
    __tablename__ = "document_working_copies"

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    base_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    draft_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="working_copy")


class ChapterBrief(Base):
    """Author-owned control plane for one chapter generation run."""

    __tablename__ = "chapter_briefs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    expectation_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outline_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    forbidden_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role_constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChapterGenerationJob(Base):
    """Immutable generation input snapshot plus the model run state."""

    __tablename__ = "chapter_generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "kind", "input_hash", "attempt",
            name="uq_chapter_generation_attempt",
        ),
        Index("ix_chapter_generation_document_created", "document_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="body")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    brief_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    base_draft_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    asset_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    execution_agent_id: Mapped[str | None] = mapped_column(String(120))
    requested_provider_id: Mapped[str | None] = mapped_column(String(160))
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    generation_contract_version: Mapped[str | None] = mapped_column(String(120))
    actual_provider_id: Mapped[str | None] = mapped_column(String(160))
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
    model_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Legacy read-only columns. New generation code never writes them.
    provider_profile: Mapped[str | None] = mapped_column(String(160))
    target_visible_character_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3000
    )
    output_visible_character_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    validation_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_profile_fingerprint: Mapped[str | None] = mapped_column(String(160))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateRevision(Base):
    """A model result that is inspectable but not yet authoritative."""

    __tablename__ = "candidate_revisions"
    __table_args__ = (Index("ix_candidate_document_state", "document_id", "state"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    generation_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chapter_generation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    base_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    base_draft_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    adopted_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoryFact(Base):
    __tablename__ = "story_facts"
    __table_args__ = (
        UniqueConstraint("id", "novel_id", name="uq_story_fact_novel_scope"),
        Index("ix_story_facts_novel_type", "novel_id", "fact_type"),
        Index("ix_story_facts_timeline_state", "novel_id", "timeline_id", "fact_type", "status", "story_sequence", "created_at"),
        Index("ix_story_facts_character_instance", "novel_id", "character_instance_id", "fact_type", "status", "created_at"),
        Index("uq_story_fact_event_fingerprint", "novel_id", "event_fingerprint", unique=True, postgresql_where=text("event_fingerprint IS NOT NULL")),
        CheckConstraint("(source_start IS NULL AND source_end IS NULL) OR (source_start >= 0 AND source_end > source_start)", name="ck_story_fact_source_offsets"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    fact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    predicate: Mapped[str] = mapped_column(String(240), nullable=False)
    object_text: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    source_document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    schema_version: Mapped[str | None] = mapped_column(String(64))
    timeline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    character_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    relationship_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    storyline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    foreshadow_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    dimension: Mapped[str | None] = mapped_column(String(80))
    event_kind: Mapped[str | None] = mapped_column(String(80))
    story_sequence: Mapped[int | None] = mapped_column(BigInteger)
    story_time_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    visibility_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_start: Mapped[int | None] = mapped_column(Integer)
    source_end: Mapped[int | None] = mapped_column(Integer)
    event_fingerprint: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntelligenceProposal(Base):
    """AI-extracted story-ledger changes awaiting explicit author review."""

    __tablename__ = "intelligence_proposals"
    __table_args__ = (
        UniqueConstraint(
            "chapter_revision_id", "input_hash", "attempt",
            name="uq_intelligence_revision_attempt",
        ),
        Index("ix_intelligence_document_created", "document_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chapter_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_context_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    execution_agent_id: Mapped[str | None] = mapped_column(String(120))
    requested_provider_id: Mapped[str | None] = mapped_column(String(160))
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    generation_contract_version: Mapped[str | None] = mapped_column(String(120))
    actual_provider_id: Mapped[str | None] = mapped_column(String(160))
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
    model_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Legacy read-only columns. New generation code never writes them.
    provider_profile: Mapped[str | None] = mapped_column(String(160))
    model_profile_fingerprint: Mapped[str | None] = mapped_column(String(160))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntelligenceProposalItem(Base):
    __tablename__ = "intelligence_proposal_items"
    __table_args__ = (
        UniqueConstraint("proposal_id", "position", name="uq_intelligence_item_position"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("intelligence_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(40), nullable=False)
    suggested_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_state: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    committed_story_fact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("story_facts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntelligenceCommitBatch(Base):
    """One idempotent, author-approved write into the story ledger."""

    __tablename__ = "intelligence_commit_batches"
    __table_args__ = (
        UniqueConstraint("proposal_id", "commit_key", name="uq_intelligence_commit_key"),
        Index("ix_intelligence_commit_revision", "chapter_revision_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("intelligence_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    commit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="committing")
    accepted_item_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    inverse_operations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expected_story_ledger_version: Mapped[int | None] = mapped_column(BigInteger)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DerivedSourceBinding(Base):
    """Validity and provenance for a fact derived from one chapter revision."""

    __tablename__ = "derived_source_bindings"
    __table_args__ = (
        UniqueConstraint(
            "derived_entity_type",
            "derived_entity_id",
            "source_chapter_revision_id",
            name="uq_derived_source_entity_revision",
        ),
        Index("ix_derived_source_document_validity", "source_chapter_id", "validity_state"),
        Index("ix_derived_source_revision", "source_chapter_revision_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    derived_entity_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="story_fact"
    )
    derived_entity_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("story_facts.id", ondelete="CASCADE"), nullable=False
    )
    source_chapter_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    source_chapter_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("intelligence_proposal_items.id", ondelete="SET NULL"),
    )
    commit_batch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("intelligence_commit_batches.id", ondelete="SET NULL"),
    )
    validity_state: Mapped[str] = mapped_column(String(30), nullable=False, default="current")
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "workspace_id", name="uq_media_asset_local_scope"),
        UniqueConstraint(
            "id", "owner_id", "workspace_id", "novel_id",
            name="uq_media_asset_job_scope",
        ),
        UniqueConstraint(
            "storage_backend", "storage_path", name="uq_media_asset_physical_blob"
        ),
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_media_asset_novel_scope",
        ),
        Index("ix_media_assets_novel_kind", "novel_id", "kind"),
        Index("ix_media_assets_scope_class_state", "owner_id", "workspace_id", "asset_class", "state"),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_media_asset_fixed_local_scope",
        ),
        CheckConstraint(
            "asset_class IS NULL OR asset_class IN "
            "('source','voice_reference','preview','segment_master','segment_playback','export')",
            name="ck_media_asset_class",
        ),
        CheckConstraint(
            "(kind NOT LIKE 'narration_%' AND kind NOT LIKE 'tts_%') OR asset_class IS NOT NULL",
            name="ck_media_asset_tts_class_required",
        ),
        CheckConstraint(
            "state IN ('staging','ready','quarantined','deleting','deleted')",
            name="ck_media_asset_state",
        ),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_media_asset_byte_size"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_media_asset_duration"),
        CheckConstraint(
            "octet_length(storage_path) BETWEEN 1 AND 1024",
            name="ck_media_asset_storage_path_length",
        ),
        CheckConstraint(
            "state <> 'ready' OR asset_class IS NULL OR "
            "(byte_size IS NOT NULL AND mime_type IS NOT NULL "
            "AND checksum_algorithm='sha256' "
            "AND content_hash ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL)",
            name="ck_media_asset_ready_narration_identity",
        ),
        CheckConstraint(
            "asset_class IS NULL OR storage_backend <> 'local' OR "
            "(content_hash ~ '^[0-9a-f]{64}$' AND storage_path ~ "
            "('^assets/' || substr(replace(id::text,'-',''),1,2) || '/' || "
            "replace(id::text,'-','') || '/' || content_hash || "
            "'\\.(aac|flac|m4a|mp3|ogg|opus|wav)$'))",
            name="ck_media_asset_narration_canonical_path",
        ),
        CheckConstraint(
            "state <> 'ready' OR asset_class IS NULL OR storage_backend <> 'local' OR "
            "(CASE substring(storage_path from '\\.[^.]+$') "
            "WHEN '.aac' THEN mime_type='audio/aac' "
            "WHEN '.flac' THEN mime_type='audio/flac' "
            "WHEN '.m4a' THEN mime_type='audio/mp4' "
            "WHEN '.mp3' THEN mime_type='audio/mpeg' "
            "WHEN '.ogg' THEN mime_type='audio/ogg' "
            "WHEN '.opus' THEN mime_type='audio/ogg' "
            "WHEN '.wav' THEN mime_type='audio/wav' ELSE FALSE END)",
            name="ck_media_asset_narration_mime_path",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, server_default=text("'29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid"))
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, server_default=text("'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid"))
    novel_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE")
    )
    source_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_class: Mapped[str | None] = mapped_column(String(32))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    storage_backend: Mapped[str] = mapped_column(String(40), nullable=False, default="local")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    retention_policy: Mapped[str] = mapped_column(String(40), nullable=False, default="legacy")
    checksum_algorithm: Mapped[str] = mapped_column(String(20), nullable=False, default="sha256")
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gc_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    gc_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaGcDeletionRecord(Base):
    """Durable, immutable physical identity frozen before an out-of-tx unlink."""

    __tablename__ = "media_gc_deletion_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "owner_id", "workspace_id"],
            ["media_assets.id", "media_assets.owner_id", "media_assets.workspace_id"],
            name="fk_media_gc_plan_asset_local_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("asset_id", "generation", name="uq_media_gc_plan_generation"),
        CheckConstraint("generation >= 0", name="ck_media_gc_plan_generation"),
        CheckConstraint("byte_size >= 0", name="ck_media_gc_plan_byte_size"),
        CheckConstraint(
            "(file_present IS TRUE AND device IS NOT NULL AND inode IS NOT NULL) OR "
            "(file_present IS FALSE AND device IS NULL AND inode IS NULL)",
            name="ck_media_gc_plan_file_identity",
        ),
        CheckConstraint(
            "octet_length(storage_path) BETWEEN 1 AND 1024",
            name="ck_media_gc_plan_storage_path_length",
        ),
        CheckConstraint(
            "reason_code IN ('staging_orphan','unreferenced_derivative_after_grace',"
            "'recover_interrupted_delete')",
            name="ck_media_gc_plan_reason_code",
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    storage_backend: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    device: Mapped[int | None] = mapped_column(BigInteger)
    inode: Mapped[int | None] = mapped_column(BigInteger)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NovelCreationDraft(Base):
    """Persisted six-step long-form novel creation wizard."""

    __tablename__ = "novel_creation_drafts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    draft_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    completed_novel_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PrivateAsset(Base):
    __tablename__ = "private_assets"
    __table_args__ = (Index("ix_private_assets_type_archived", "asset_type", "archived"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    tags_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rights_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetPreset(Base):
    __tablename__ = "asset_presets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetPresetItem(Base):
    __tablename__ = "asset_preset_items"
    __table_args__ = (
        UniqueConstraint("preset_id", "asset_id", name="uq_asset_preset_asset"),
        UniqueConstraint("preset_id", "position", name="uq_asset_preset_position"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    preset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("asset_presets.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("private_assets.id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    usage_policy: Mapped[str] = mapped_column(String(24), nullable=False, default="preferred")
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class OutlineDraft(Base):
    """Persisted five-step outline wizard for one novel."""

    __tablename__ = "outline_drafts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_chapter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    background_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    characters_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    plot_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    highlight_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NovelCharacter(Base):
    __tablename__ = "novel_characters"
    __table_args__ = (
        UniqueConstraint("novel_id", "name", name="uq_novel_character_name"),
        UniqueConstraint("novel_id", "position", name="uq_novel_character_position"),
        UniqueConstraint("id", "novel_id", name="uq_novel_character_novel_scope"),
        Index("ix_novel_characters_novel_role", "novel_id", "role_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    role_type: Mapped[str] = mapped_column(String(30), nullable=False, default="supporting")
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"
    __table_args__ = (
        CheckConstraint(
            "source_character_id <> target_character_id",
            name="ck_character_relationship_distinct_endpoints",
        ),
        Index(
            "uq_character_relationship_active_semantics",
            "novel_id",
            "timeline_id",
            "source_character_instance_id",
            "target_character_instance_id",
            "directionality",
            "relation_kind",
            "normalized_label",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index("ix_character_relationships_novel", "novel_id", "archived_at"),
        Index("ix_character_relationships_pair", "novel_id", "relation_pair_key"),
        UniqueConstraint("id", "novel_id", name="uq_character_relationship_novel_scope"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_character_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novel_characters.id", ondelete="CASCADE"), nullable=False
    )
    target_character_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novel_characters.id", ondelete="CASCADE"), nullable=False
    )
    timeline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    target_character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    directionality: Mapped[str] = mapped_column(
        String(24), nullable=False, default="undirected"
    )
    relation_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(80), nullable=False)
    relation_pair_key: Mapped[str] = mapped_column(String(73), nullable=False)
    # Kept as a compatibility alias while older clients migrate to `label`.
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    # Author edits are durable overrides. Automated reconciliation may only
    # mutate rows where this flag is false.
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence: Mapped[int | None] = mapped_column(Integer)
    evidence_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_generation_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("creative_generation_jobs.id", ondelete="SET NULL")
    )
    source_chapter_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    proposal_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("intelligence_proposal_items.id", ondelete="SET NULL")
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "character_relationship_revisions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_character_relationship_current_revision",
        ),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CharacterRelationshipRevision(Base):
    __tablename__ = "character_relationship_revisions"
    __table_args__ = (
        UniqueConstraint(
            "relationship_id",
            "revision_number",
            name="uq_character_relationship_revision_number",
        ),
        Index(
            "ix_character_relationship_revision_source",
            "source_chapter_revision_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    relationship_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("character_relationships.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    timeline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    target_character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    directionality: Mapped[str] = mapped_column(String(24), nullable=False)
    relation_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    change_reason: Mapped[str] = mapped_column(String(30), nullable=False, default="editorial")
    changed_by: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence: Mapped[int | None] = mapped_column(Integer)
    evidence_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_generation_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("creative_generation_jobs.id", ondelete="SET NULL")
    )
    source_chapter_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    proposal_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("intelligence_proposal_items.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelationshipGraphView(Base):
    __tablename__ = "relationship_graph_views"
    __table_args__ = (
        UniqueConstraint("novel_id", "name", name="uq_relationship_graph_view_name"),
        Index("ix_relationship_graph_views_novel", "novel_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="默认视图")
    layout_algorithm: Mapped[str] = mapped_column(
        String(40), nullable=False, default="force_atlas_2"
    )
    random_seed: Mapped[str] = mapped_column(String(64), nullable=False, default="relationship-v1")
    zoom: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    pan_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pan_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RelationshipGraphPosition(Base):
    __tablename__ = "relationship_graph_positions"
    __table_args__ = (
        Index("ix_relationship_graph_positions_character", "character_id"),
    )

    view_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("relationship_graph_views.id", ondelete="CASCADE"),
        primary_key=True,
    )
    character_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("novel_characters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Storyline(Base):
    __tablename__ = "storylines"
    __table_args__ = (
        UniqueConstraint("novel_id", "position", name="uq_storyline_position"),
        Index("ix_storylines_novel_type", "novel_id", "storyline_type"),
        UniqueConstraint("id", "novel_id", name="uq_storyline_novel_scope"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    storyline_type: Mapped[str] = mapped_column(String(30), nullable=False, default="main")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Foreshadow(Base):
    __tablename__ = "foreshadows"
    __table_args__ = (
        UniqueConstraint("novel_id", "position", name="uq_foreshadow_position"),
        Index("ix_foreshadows_novel_status", "novel_id", "status"),
        UniqueConstraint("id", "novel_id", name="uq_foreshadow_novel_scope"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latest_progress: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChapterCreationDraft(Base):
    """Persisted six-step chapter wizard; completion atomically creates a chapter."""

    __tablename__ = "chapter_creation_drafts"
    __table_args__ = (Index("ix_chapter_creation_novel_state", "novel_id", "state"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    draft_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    volume_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("volumes.id", ondelete="SET NULL")
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    target_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2500)
    expectation_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outline_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    completed_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreativeGenerationJob(Base):
    """Auditable Agent generation for naming, outlines, review and relations."""

    __tablename__ = "creative_generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_id", "kind", "input_hash", "attempt",
            name="uq_creative_generation_attempt",
        ),
        UniqueConstraint("id", "novel_id", name="uq_creative_generation_job_novel_scope"),
        Index("ix_creative_generation_scope_created", "scope_type", "scope_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE")
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    execution_agent_id: Mapped[str | None] = mapped_column(String(120))
    requested_provider_id: Mapped[str | None] = mapped_column(String(160))
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    generation_contract_version: Mapped[str | None] = mapped_column(String(120))
    actual_provider_id: Mapped[str | None] = mapped_column(String(160))
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
    model_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Legacy read-only column. New generation code never writes it.
    provider_profile: Mapped[str | None] = mapped_column(String(160))
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_character_count: Mapped[int | None] = mapped_column(Integer)
    output_visible_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CharacterProfileApplyBatch(Base):
    """Immutable audit snapshot for one author-confirmed profile application."""

    __tablename__ = "character_profile_apply_batches"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "idempotency_key",
            name="uq_character_profile_apply_batch_idempotency",
        ),
        UniqueConstraint("id", "novel_id", name="uq_character_profile_apply_batch_novel_scope"),
        Index(
            "ix_character_profile_apply_batch_novel_created",
            "novel_id",
            "created_at",
        ),
        CheckConstraint(
            "state IN ('applied','restored')",
            name="ck_character_profile_apply_batch_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("novels.id", ondelete="CASCADE"),
        nullable=False,
    )
    generation_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("creative_generation_jobs.id", ondelete="SET NULL"),
    )
    restored_from_batch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("character_profile_apply_batches.id", ondelete="SET NULL"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")
    decisions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    before_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    after_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    base_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    result_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class NovelExport(Base):
    __tablename__ = "novel_exports"
    __table_args__ = (Index("ix_novel_exports_novel_created", "novel_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    export_format: Mapped[str] = mapped_column(String(20), nullable=False, default="markdown")
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Narration foundation schema.  The service layer deliberately lives outside
# this module; these rows only establish scope, immutability and reachability.
class NarrationRequest(Base):
    __tablename__ = "narration_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_narration_request_novel_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "novel_id"], ["documents.id", "documents.novel_id"],
            name="fk_narration_request_document_scope",
        ),
        ForeignKeyConstraint(
            ["source_revision_id", "document_id", "source_content_hash"],
            ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"],
            name="fk_narration_request_source_guard",
        ),
        ForeignKeyConstraint(
            ["review_script_id", "document_id"],
            ["narration_scripts.id", "narration_scripts.document_id"],
            name="fk_narration_request_review_script_document",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["current_review_version_id", "review_script_id"],
            ["narration_script_versions.id", "narration_script_versions.script_id"],
            name="fk_narration_request_current_review_version",
            use_alter=True,
        ),
        UniqueConstraint("owner_id", "workspace_id", "idempotency_key", name="uq_narration_request_idempotency"),
        UniqueConstraint("id", "allows_edition", name="uq_narration_request_edition_guard"),
        UniqueConstraint("id", "allows_render", name="uq_narration_request_render_guard"),
        UniqueConstraint("id", "novel_id", name="uq_narration_request_novel_guard"),
        UniqueConstraint(
            "id", "review_script_id", name="uq_narration_request_review_script_guard"
        ),
        UniqueConstraint(
            "id", "owner_id", "workspace_id", "novel_id", "allows_render",
            name="uq_narration_request_full_render_guard",
        ),
        CheckConstraint("intent IN ('analyze_only','create','update','batch')", name="ck_narration_request_intent"),
        CheckConstraint(
            "state IN ('created','analyzing','analyzed','review_required','queued','rendering',"
            "'partial_ready','ready','cancel_requested','cancelled','failed')",
            name="ck_narration_request_state",
        ),
        CheckConstraint("effective_policy IN ('blockers_only','always_review')", name="ck_narration_request_policy"),
        CheckConstraint(
            "force_review IS FALSE OR effective_policy='always_review'",
            name="ck_narration_request_force_review_policy",
        ),
        CheckConstraint(
            "(intent = 'analyze_only' AND explicit_generation_intent_at IS NULL "
            "AND explicit_generation_actor IS NULL) OR "
            "(intent IN ('create','update','batch') AND explicit_generation_intent_at IS NOT NULL "
            "AND explicit_generation_actor IS NOT NULL)",
            name="ck_narration_request_generation_intent",
        ),
        CheckConstraint(
            "(intent IN ('create','update') AND document_id IS NOT NULL AND source_revision_id IS NOT NULL "
            "AND source_content_hash IS NOT NULL) OR "
            "(intent='analyze_only' AND ((document_id IS NOT NULL "
            "AND source_revision_id IS NOT NULL AND source_content_hash IS NOT NULL) OR "
            "(document_id IS NULL AND source_revision_id IS NULL AND source_content_hash IS NULL))) OR "
            "(intent='batch' AND document_id IS NULL AND source_revision_id IS NULL "
            "AND source_content_hash IS NULL)",
            name="ck_narration_request_source_shape",
        ),
        CheckConstraint(
            "intent <> 'analyze_only' OR state NOT IN ('queued','rendering','partial_ready','ready')",
            name="ck_narration_request_analyze_state",
        ),
        CheckConstraint(
            "source_count >= 0",
            name="ck_narration_request_source_count",
        ),
        CheckConstraint(
            "(review_script_id IS NULL AND current_review_version_id IS NULL) OR "
            "(review_script_id IS NOT NULL AND current_review_version_id IS NOT NULL)",
            name="ck_narration_request_review_pointer_shape",
        ),
        CheckConstraint(
            "source_set_hash ~ '^[0-9a-f]{64}$'",
            name="ck_narration_request_source_set_hash",
        ),
        CheckConstraint(
            "(document_id IS NOT NULL AND source_count=0 AND "
            "source_set_hash='4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945') OR "
            "(document_id IS NULL AND source_count>0)",
            name="ck_narration_request_source_manifest_shape",
        ),
        Index("ix_narration_requests_scope_state", "owner_id", "workspace_id", "novel_id", "state"),
        Index(
            "ix_narration_requests_review_pointer",
            "review_script_id",
            "current_review_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    intent: Mapped[str] = mapped_column(String(20), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_content_hash: Mapped[str | None] = mapped_column(String(64))
    review_script_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    current_review_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sources_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    force_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    allows_edition: Mapped[bool] = mapped_column(Boolean, Computed("intent <> 'analyze_only'", persisted=True))
    allows_render: Mapped[bool] = mapped_column(Boolean, Computed("intent <> 'analyze_only'", persisted=True))
    explicit_generation_intent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    explicit_generation_actor: Mapped[str | None] = mapped_column(String(120))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_actor: Mapped[str | None] = mapped_column(String(120))
    cancel_reason_code: Mapped[str | None] = mapped_column(String(96))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrationRequestSource(Base):
    __tablename__ = "narration_request_sources"
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "novel_id"], ["narration_requests.id", "narration_requests.novel_id"], name="fk_narration_request_source_request_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["document_id", "novel_id"], ["documents.id", "documents.novel_id"], name="fk_narration_request_source_document"),
        ForeignKeyConstraint(
            ["revision_id", "document_id", "content_hash"],
            ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"],
            name="fk_narration_request_source_revision",
        ),
        UniqueConstraint("request_id", "document_id", name="uq_narration_request_source_document"),
        UniqueConstraint("request_id", "position", name="uq_narration_request_source_position"),
        CheckConstraint("position >= 0", name="ck_narration_request_source_position"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class NovelNarrationSettings(Base):
    __tablename__ = "novel_narration_settings"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_novel_narration_settings_novel"),
        CheckConstraint("script_review_policy IN ('blockers_only','always_review')", name="ck_narration_settings_review_policy"),
        CheckConstraint("analysis_mode IN ('local_rules_only','cloud_assisted')", name="ck_narration_settings_analysis_mode"),
        CheckConstraint(
            "(narrator_profile_id IS NULL AND narrator_version_id IS NULL) OR "
            "(narrator_profile_id IS NOT NULL AND narrator_version_id IS NOT NULL)",
            name="ck_narration_settings_narrator_shape",
        ),
        ForeignKeyConstraint(["narrator_version_id", "narrator_profile_id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_narration_settings_narrator_version", ondelete="RESTRICT"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    narrator_profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    narrator_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    script_review_policy: Mapped[str] = mapped_column(String(24), nullable=False, default="blockers_only")
    analysis_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="local_rules_only")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationSettingsSnapshot(Base):
    __tablename__ = "narration_settings_snapshots"
    __table_args__ = (
        UniqueConstraint("owner_id", "workspace_id", "fingerprint", name="uq_narration_settings_snapshot_fingerprint"),
        UniqueConstraint(
            "id", "owner_id", "workspace_id", "novel_id",
            name="uq_narration_settings_snapshot_edition_guard",
        ),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_narration_settings_snapshot_novel_scope"),
        CheckConstraint(
            "taxonomy_version = 'narration-review-taxonomy/1'",
            name="ck_narration_settings_snapshot_taxonomy_version",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationScopeOverride(Base):
    __tablename__ = "narration_scope_overrides"
    __table_args__ = (
        UniqueConstraint("novel_id", "scope_kind", "scope_id", name="uq_narration_scope_override"),
        CheckConstraint("scope_kind IN ('volume','chapter')", name="ck_narration_scope_override_kind"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class NarrationCloudConsent(Base):
    __tablename__ = "narration_cloud_consents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    data_scope: Mapped[str] = mapped_column(String(120), nullable=False)
    notice_version: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(160))
    model_id: Mapped[str | None] = mapped_column(String(160))
    confirmed_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoiceRightsRecord(Base):
    __tablename__ = "voice_rights_records"
    __table_args__ = (
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_voice_rights_record_novel_scope"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT"))
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(240), nullable=False)
    notice_version: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    commercial_use: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redistribution: Mapped[bool] = mapped_column(Boolean, nullable=False)
    voice_cloning: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subject_consent_reference: Mapped[str | None] = mapped_column(String(240))
    confirmed_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk_flags_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class VoiceRightsEvent(Base):
    __tablename__ = "voice_rights_events"
    __table_args__ = (
        UniqueConstraint("rights_record_id", "event_key", name="uq_voice_rights_event_key"),
        CheckConstraint("event_type IN ('confirmed','revoked','expired','review_blocked')", name="ck_voice_rights_event_type"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    rights_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_rights_records.id", ondelete="RESTRICT"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(96))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "workspace_id", name="uq_voice_profile_local_scope"),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_voice_profile_novel_scope"),
        Index("ix_voice_profiles_scope_novel", "owner_id", "workspace_id", "novel_id", "status"),
        CheckConstraint("status IN ('draft','active','archived','unavailable')", name="ck_voice_profile_status"),
        ForeignKeyConstraint(["current_version_id", "id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_voice_profile_current_version", ondelete="RESTRICT"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceProfileVersion(Base):
    __tablename__ = "voice_profile_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version_number", name="uq_voice_profile_version_number"),
        UniqueConstraint("id", "profile_id", name="uq_voice_profile_version_profile_guard"),
        UniqueConstraint("owner_id", "workspace_id", "fingerprint", name="uq_voice_profile_version_fingerprint"),
        CheckConstraint("source_type IN ('preset','uploaded','generated')", name="ck_voice_profile_version_source_type"),
        CheckConstraint("state IN ('draft','preview_ready','locked','unavailable','deleted')", name="ck_voice_profile_version_state"),
        CheckConstraint(
            "quality_state IN ('pending','accepted','rejected')",
            name="ck_voice_profile_version_quality_state",
        ),
        CheckConstraint(
            "activation_basis IN ('preview_confirmed','explicit_official_preset_selection',"
            "'character_one_click_generation','experimental_machine_validated')",
            name="ck_voice_profile_version_activation_basis",
        ),
        CheckConstraint(
            "validation_basis IN ('pending','human_accepted','machine_validated','not_required')",
            name="ck_voice_profile_version_validation_basis",
        ),
        CheckConstraint(
            "state <> 'locked' OR ("
            "(activation_basis='preview_confirmed' AND validation_basis='human_accepted' "
            "AND quality_state='accepted' AND locked_actor IS NOT NULL AND locked_at IS NOT NULL) OR "
            "(activation_basis='explicit_official_preset_selection' AND source_type='preset' "
            "AND validation_basis='not_required' AND quality_state='pending' "
            "AND locked_actor IS NULL AND locked_at IS NULL) OR "
            "(activation_basis='experimental_machine_validated' AND source_type='generated' "
            "AND validation_basis='machine_validated' AND quality_state='accepted' "
            "AND model_run_id IS NOT NULL AND locked_actor IS NULL AND locked_at IS NULL) OR "
            "(activation_basis='character_one_click_generation' AND source_type='generated' "
            "AND validation_basis='machine_validated' AND quality_state='accepted' "
            "AND model_run_id IS NOT NULL AND reference_asset_id IS NOT NULL "
            "AND locked_actor IS NULL AND locked_at IS NULL))",
            name="ck_voice_profile_version_locked_shape",
        ),
        CheckConstraint(
            "state = 'locked' OR (activation_basis='preview_confirmed' AND validation_basis='pending')",
            name="ck_voice_profile_version_unlocked_activation",
        ),
        CheckConstraint(
            "source_type <> 'uploaded' OR reference_asset_id IS NOT NULL",
            name="ck_voice_profile_version_uploaded_reference",
        ),
        CheckConstraint(
            "model_run_id IS NULL OR (state='locked' AND source_type='generated' "
            "AND activation_basis IN ('experimental_machine_validated',"
            "'character_one_click_generation') "
            "AND validation_basis='machine_validated' AND quality_state='accepted')",
            name="ck_voice_profile_version_model_run_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profiles.id", ondelete="RESTRICT"), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    provider_id: Mapped[str | None] = mapped_column(String(160))
    model_id: Mapped[str | None] = mapped_column(String(160))
    model_revision: Mapped[str | None] = mapped_column(String(160))
    preset_key: Mapped[str | None] = mapped_column(String(160))
    reference_asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"))
    preview_asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"))
    model_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model_run_records.id", ondelete="RESTRICT")
    )
    rights_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_rights_records.id", ondelete="RESTRICT"), nullable=False)
    description_digest_key_id: Mapped[str | None] = mapped_column(String(80))
    description_digest: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="zh-CN")
    seed: Mapped[int | None] = mapped_column(BigInteger)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    activation_basis: Mapped[str] = mapped_column(
        String(48), nullable=False, default="preview_confirmed"
    )
    validation_basis: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    locked_actor: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceActionReceipt(Base):
    """Durable cross-process idempotency receipt for product voice actions."""

    __tablename__ = "voice_action_receipts"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "operation",
            "idempotency_key",
            name="uq_voice_action_receipt_idempotency",
        ),
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "operation",
            "resource_id",
            name="uq_voice_action_receipt_resource",
        ),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_voice_action_receipt_fixed_local_scope",
        ),
        CheckConstraint(
            "operation ~ '^[a-z][a-z0-9_]{2,47}$'",
            name="ck_voice_action_receipt_operation",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'",
            name="ck_voice_action_receipt_idempotency_key",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_voice_action_receipt_request_hash",
        ),
        CheckConstraint(
            "state IN ('reserved','completed')",
            name="ck_voice_action_receipt_state",
        ),
        CheckConstraint(
            "(state='reserved' AND completed_at IS NULL) OR "
            "(state='completed' AND completed_at IS NOT NULL "
            "AND completed_at >= reserved_at)",
            name="ck_voice_action_receipt_lifecycle",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        server_default=text("'29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        server_default=text("'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid"),
    )
    operation: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoiceActionCommand(Base):
    """Immutable request/result evidence for one multi-resource voice action."""

    __tablename__ = "voice_action_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_action_command_novel_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_voice_action_command_character_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["voice_version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_action_command_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "workspace_id", "operation", "id"],
            [
                "voice_action_receipts.owner_id",
                "voice_action_receipts.workspace_id",
                "voice_action_receipts.operation",
                "voice_action_receipts.resource_id",
            ],
            name="fk_voice_action_command_receipt",
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_voice_action_command_fixed_local_scope",
        ),
        CheckConstraint(
            "operation ~ '^[a-z][a-z0-9_]{2,47}$'",
            name="ck_voice_action_command_operation",
        ),
        CheckConstraint(
            "operation = 'official_preset_selection'",
            name="ck_voice_action_command_operation_kind",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_voice_action_command_request_hash",
        ),
        CheckConstraint(
            "preset_key IS NULL OR preset_key ~ '^onnx\\.[A-Za-z][A-Za-z0-9]{0,79}$'",
            name="ck_voice_action_command_preset_key",
        ),
        CheckConstraint(
            "target_kind IN ('narrator','character')",
            name="ck_voice_action_command_target_kind",
        ),
        CheckConstraint(
            "(target_kind='narrator' AND target_character_id IS NULL) OR "
            "(target_kind='character' AND target_character_id IS NOT NULL)",
            name="ck_voice_action_command_target_shape",
        ),
        CheckConstraint(
            "state IN ('reserved','completed')",
            name="ck_voice_action_command_state",
        ),
        CheckConstraint(
            "target_language IS NULL OR target_language ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="ck_voice_action_command_target_language",
        ),
        CheckConstraint(
            "(state='reserved' AND profile_id IS NULL AND voice_version_id IS NULL "
            "AND settings_version IS NULL AND binding_version IS NULL "
            "AND target_language IS NULL AND language_mismatch IS NULL "
            "AND completed_at IS NULL) OR "
            "(state='completed' AND profile_id IS NOT NULL AND voice_version_id IS NOT NULL "
            "AND settings_version IS NOT NULL AND settings_version>0 "
            "AND ((target_kind='narrator' AND binding_version IS NULL) "
            "OR (target_kind='character' AND binding_version IS NOT NULL AND binding_version>0)) "
            "AND target_language IS NOT NULL AND language_mismatch IS NOT NULL "
            "AND completed_at IS NOT NULL AND completed_at>=created_at)",
            name="ck_voice_action_command_lifecycle",
        ),
        Index(
            "ix_voice_action_commands_scope_created",
            "owner_id",
            "workspace_id",
            "novel_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(48), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_character_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    preset_key: Mapped[str | None] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    voice_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    settings_version: Mapped[int | None] = mapped_column(BigInteger)
    binding_version: Mapped[int | None] = mapped_column(BigInteger)
    target_language: Mapped[str | None] = mapped_column(String(40))
    language_mismatch: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CharacterCastPlanCommand(Base):
    """Durable, novel-scoped authority for one whole-book casting run."""

    __tablename__ = "character_cast_plan_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_character_cast_plan_novel_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["timeline_id", "novel_id"],
            ["story_timelines.id", "story_timelines.novel_id"],
            name="fk_character_cast_plan_timeline_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "novel_id",
            "idempotency_key",
            name="uq_character_cast_plan_idempotency",
        ),
        UniqueConstraint(
            "id", "novel_id", name="uq_character_cast_plan_novel_guard"
        ),
        Index(
            "ix_character_cast_plan_scope_created",
            "owner_id",
            "workspace_id",
            "novel_id",
            "created_at",
        ),
        Index(
            "uq_character_cast_plan_active",
            "novel_id",
            "timeline_id",
            unique=True,
            postgresql_where=text("state IN ('reserved','analyzing')"),
        ),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_character_cast_plan_fixed_local_scope",
        ),
        CheckConstraint(
            "mode='fill_and_deduplicate'",
            name="ck_character_cast_plan_mode",
        ),
        CheckConstraint(
            "state IN ('reserved','analyzing','ready_applied',"
            "'ready_applied_with_warnings','ready_unapplied','failed','superseded')",
            name="ck_character_cast_plan_state",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$' "
            "AND request_hash ~ '^[0-9a-f]{64}$' "
            "AND catalog_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND workspace_digest ~ '^[0-9a-f]{64}$' "
            "AND settings_digest ~ '^[0-9a-f]{64}$' "
            "AND bindings_digest ~ '^[0-9a-f]{64}$'",
            name="ck_character_cast_plan_digests",
        ),
        CheckConstraint(
            "character_catalog_version >= 0 AND settings_version >= 0 "
            "AND progress_total > 0 AND progress_current >= 0 "
            "AND progress_current <= progress_total",
            name="ck_character_cast_plan_versions_progress",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_character_cast_plan_failure_code",
        ),
        CheckConstraint(
            "(state IN ('reserved','analyzing') AND completed_at IS NULL "
            "AND failure_code IS NULL) OR "
            "(state='failed' AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
            "(state IN ('ready_applied','ready_applied_with_warnings',"
            "'ready_unapplied','superseded') AND completed_at IS NOT NULL "
            "AND failure_code IS NULL)",
            name="ck_character_cast_plan_terminal_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    timeline_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="reserved")
    character_catalog_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settings_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    catalog_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    settings_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    bindings_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CharacterCastPlanItem(Base):
    """One recoverable analysis target inside a whole-book casting run."""

    __tablename__ = "character_cast_plan_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["command_id", "novel_id"],
            ["character_cast_plan_commands.id", "character_cast_plan_commands.novel_id"],
            name="fk_character_cast_plan_item_command_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_character_cast_plan_item_character_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["voice_version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_character_cast_plan_item_voice_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["voice_action_command_id"],
            ["voice_action_commands.id"],
            name="fk_character_cast_plan_item_action_command",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "command_id", "position", name="uq_character_cast_plan_item_position"
        ),
        UniqueConstraint(
            "command_id", "target_key", name="uq_character_cast_plan_item_target"
        ),
        Index(
            "ix_character_cast_plan_items_command_state",
            "command_id",
            "state",
            "position",
        ),
        CheckConstraint(
            "target_kind IN ('narrator','character') AND "
            "((target_kind='narrator' AND target_key='narrator' "
            "AND character_id IS NULL AND character_name IS NULL AND role_type IS NULL) OR "
            "(target_kind='character' AND character_id IS NOT NULL "
            "AND target_key=('character:'||character_id::text) "
            "AND character_name IS NOT NULL AND role_type IS NOT NULL))",
            name="ck_character_cast_plan_item_target",
        ),
        CheckConstraint(
            "state IN ('pending','analyzing','preserved','scored','assigned','blocked')",
            name="ck_character_cast_plan_item_state",
        ),
        CheckConstraint(
            "position >= 0 AND priority_rank >= 0 AND attempt >= 0 "
            "AND expected_binding_version >= 0",
            name="ck_character_cast_plan_item_counters",
        ),
        CheckConstraint(
            "workspace_digest ~ '^[0-9a-f]{64}$' "
            "AND (model_evidence_digest IS NULL "
            "OR model_evidence_digest ~ '^[0-9a-f]{64}$')",
            name="ck_character_cast_plan_item_digests",
        ),
        CheckConstraint(
            "(state='analyzing' AND lease_fence IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state<>'analyzing' AND lease_fence IS NULL AND lease_expires_at IS NULL)",
            name="ck_character_cast_plan_item_lease",
        ),
        CheckConstraint(
            "(profile_id IS NULL AND voice_version_id IS NULL) OR "
            "(profile_id IS NOT NULL AND voice_version_id IS NOT NULL)",
            name="ck_character_cast_plan_item_voice_shape",
        ),
        CheckConstraint(
            "voice_source_type IS NULL OR voice_source_type IN ('preset','uploaded','generated')",
            name="ck_character_cast_plan_item_voice_source",
        ),
        CheckConstraint(
            "brief_schema_version IS NULL OR brief_schema_version IN "
            "('character-voice-brief/1','narrator-voice-brief/1')",
            name="ck_character_cast_plan_item_brief_schema",
        ),
        CheckConstraint(
            "selected_preset_key IS NULL OR "
            "selected_preset_key ~ '^onnx\\.[A-Za-z][A-Za-z0-9]{0,79}$'",
            name="ck_character_cast_plan_item_preset",
        ),
        CheckConstraint(
            "score_milli IS NULL OR (score_milli >= 0 AND score_milli <= 1000)",
            name="ck_character_cast_plan_item_score",
        ),
        CheckConstraint(
            "warning_code IS NULL OR warning_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_character_cast_plan_item_warning_code",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_character_cast_plan_item_failure_code",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    command_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    target_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    character_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    character_name: Mapped[str | None] = mapped_column(String(240))
    role_type: Mapped[str | None] = mapped_column(String(30))
    expected_binding_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_fence: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    brief_schema_version: Mapped[str | None] = mapped_column(String(80))
    brief_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_evidence_digest: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(40))
    selected_preset_key: Mapped[str | None] = mapped_column(String(160))
    score_milli: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    voice_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    voice_source_type: Mapped[str | None] = mapped_column(String(20))
    current_preset_key: Mapped[str | None] = mapped_column(String(160))
    voice_action_command_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    warning_code: Mapped[str | None] = mapped_column(String(96))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoiceReferenceAssetLink(Base):
    """Immutable provenance from an uploaded original to a normalized reference."""

    __tablename__ = "voice_reference_asset_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["voice_version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_reference_link_version_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "voice_version_id", name="uq_voice_reference_link_version"
        ),
        Index(
            "ix_voice_reference_links_scope_profile",
            "owner_id",
            "workspace_id",
            "novel_id",
            "profile_id",
        ),
        Index("ix_voice_reference_links_source_asset", "source_asset_id"),
        Index("ix_voice_reference_links_reference_asset", "reference_asset_id"),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_voice_reference_link_fixed_local_scope",
        ),
        CheckConstraint(
            "normalization_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_reference_link_normalization_fingerprint",
        ),
        CheckConstraint(
            "validation_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_reference_link_validation_fingerprint",
        ),
        CheckConstraint(
            "source_asset_id <> reference_asset_id",
            name="ck_voice_reference_link_distinct_assets",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT")
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("voice_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    voice_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    rights_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("voice_rights_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    reference_asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    normalization_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoicePreview(Base):
    """Private, expiring Nano preview execution and publication record."""

    __tablename__ = "voice_previews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_preview_version_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", name="uq_voice_preview_job"),
        Index(
            "ix_voice_previews_scope_status",
            "owner_id",
            "workspace_id",
            "novel_id",
            "status",
        ),
        Index("ix_voice_previews_expiry", "expires_at", "status"),
        Index("ix_voice_previews_reference_asset", "reference_asset_id"),
        Index("ix_voice_previews_result_asset", "result_asset_id"),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_voice_preview_fixed_local_scope",
        ),
        CheckConstraint(
            "status IN ('queued','running','ready','failed','cancelled')",
            name="ck_voice_preview_status",
        ),
        CheckConstraint(
            "preview_text_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$' "
            "AND preview_text_digest ~ '^[0-9a-f]{64}$'",
            name="ck_voice_preview_text_digest",
        ),
        CheckConstraint(
            "model_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND reference_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND parameters_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_preview_fingerprints",
        ),
        CheckConstraint(
            "preview_text IS NULL OR "
            "(char_length(preview_text) BETWEEN 1 AND 500 AND btrim(preview_text) <> '')",
            name="ck_voice_preview_private_text_bounds",
        ),
        CheckConstraint(
            "(status='queued' AND preview_text IS NOT NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND result_asset_id IS NULL "
            "AND expires_at IS NULL AND failure_code IS NULL) OR "
            "(status='running' AND preview_text IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND result_asset_id IS NULL "
            "AND expires_at IS NULL AND failure_code IS NULL) OR "
            "(status='ready' AND preview_text IS NULL AND completed_at IS NOT NULL "
            "AND result_asset_id IS NOT NULL AND expires_at IS NOT NULL "
            "AND expires_at > completed_at AND failure_code IS NULL) OR "
            "(status='failed' AND preview_text IS NULL AND completed_at IS NOT NULL "
            "AND result_asset_id IS NULL AND expires_at IS NULL "
            "AND failure_code IS NOT NULL AND btrim(failure_code) <> '') OR "
            "(status='cancelled' AND preview_text IS NULL AND completed_at IS NOT NULL "
            "AND result_asset_id IS NULL AND expires_at IS NULL AND failure_code IS NULL)",
            name="ck_voice_preview_lifecycle_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT")
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("voice_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    rights_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("voice_rights_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    reference_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    result_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    preview_text: Mapped[str | None] = mapped_column(Text)
    preview_text_digest_key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    preview_text_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    model_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NanoVoiceExperimentCommand(Base):
    """Durable asynchronous Nano tuning request and CAS application evidence."""

    __tablename__ = "nano_voice_experiment_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_nano_voice_experiment_novel_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["profile_id"],
            ["voice_profiles.id"],
            name="fk_nano_voice_experiment_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_nano_voice_experiment_character_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["version_id", "profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_nano_voice_experiment_version_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["background_job_id", "owner_id", "workspace_id", "novel_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id", "background_jobs.novel_id"],
            name="fk_nano_voice_experiment_job_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "idempotency_key",
            name="uq_nano_voice_experiment_idempotency",
        ),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_nano_voice_experiment_fixed_local_scope",
        ),
        CheckConstraint(
            "target_kind IN ('narrator','character')",
            name="ck_nano_voice_experiment_target_kind",
        ),
        CheckConstraint(
            "(target_kind='narrator' AND target_character_id IS NULL "
            "AND expected_binding_version IS NULL) OR "
            "(target_kind='character' AND target_character_id IS NOT NULL "
            "AND expected_binding_version IS NOT NULL AND expected_binding_version>=0)",
            name="ck_nano_voice_experiment_target_shape",
        ),
        CheckConstraint(
            "expected_settings_version>=0",
            name="ck_nano_voice_experiment_expected_settings_version",
        ),
        CheckConstraint(
            "base_preset_id ~ '^onnx\\.[A-Za-z][A-Za-z0-9]{0,79}$'",
            name="ck_nano_voice_experiment_preset_id",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$'",
            name="ck_nano_voice_experiment_idempotency_key",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' "
            "AND parameters_digest ~ '^[0-9a-f]{64}$' "
            "AND input_digest ~ '^[0-9a-f]{64}$' "
            "AND fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nano_voice_experiment_digests",
        ),
        CheckConstraint(
            "input_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'",
            name="ck_nano_voice_experiment_digest_key",
        ),
        CheckConstraint(
            "parameters_json ?& ARRAY['schema_version','seed',"
            "'text_temperature_milli','text_top_p_milli','text_top_k',"
            "'audio_temperature_milli','audio_top_p_milli','audio_top_k',"
            "'audio_repetition_penalty_milli','sample_mode','max_new_frames'] "
            "AND parameters_json->>'schema_version'='nano-decode-parameters/3' "
            "AND parameters_json->>'sample_mode'='full' "
            "AND parameters_json->>'max_new_frames'='375'",
            name="ck_nano_voice_experiment_parameters_shape",
        ),
        CheckConstraint(
            "state IN ('pending','running','ready_applied','ready_unapplied','failed')",
            name="ck_nano_voice_experiment_state",
        ),
        CheckConstraint(
            "(state='pending' AND started_at IS NULL AND completed_at IS NULL "
            "AND applied_at IS NULL AND failure_code IS NULL "
            "AND created_at<=updated_at) OR "
            "(state='running' AND started_at IS NOT NULL AND started_at>=created_at "
            "AND completed_at IS NULL AND applied_at IS NULL AND failure_code IS NULL "
            "AND updated_at>=started_at) OR "
            "(state='ready_applied' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND completed_at>=started_at AND applied_at IS NOT NULL "
            "AND applied_at>=completed_at AND updated_at>=applied_at "
            "AND failure_code IS NULL) OR "
            "(state='ready_unapplied' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND completed_at>=started_at AND applied_at IS NULL "
            "AND updated_at>=completed_at AND failure_code IS NULL) OR "
            "(state='failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND completed_at>=started_at AND applied_at IS NULL "
            "AND updated_at>=completed_at AND failure_code IN ("
            "'NANO_EXPERIMENT_MODEL_UNAVAILABLE','NANO_EXPERIMENT_SYNTHESIS_FAILED',"
            "'NANO_EXPERIMENT_AUDIO_INVALID','NANO_EXPERIMENT_MODEL_IDENTITY_MISMATCH',"
            "'NANO_EXPERIMENT_PARAMETERS_MISMATCH','NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH',"
            "'NANO_EXPERIMENT_DATABASE_FAILED'))",
            name="ck_nano_voice_experiment_lifecycle",
        ),
        CheckConstraint(
            "(state<>'ready_applied' AND applied_settings_version IS NULL "
            "AND applied_binding_version IS NULL) OR "
            "(state='ready_applied' AND applied_settings_version IS NOT NULL "
            "AND applied_settings_version>0 AND "
            "((target_kind='narrator' AND applied_binding_version IS NULL) OR "
            "(target_kind='character' AND applied_binding_version IS NOT NULL "
            "AND applied_binding_version>0)))",
            name="ck_nano_voice_experiment_applied_versions",
        ),
        Index(
            "ix_nano_voice_experiments_scope_created",
            "owner_id",
            "workspace_id",
            "novel_id",
            "created_at",
        ),
        Index(
            "ix_nano_voice_experiments_state",
            "state",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    preview_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("voice_previews.id", ondelete="RESTRICT"), nullable=False
    )
    background_job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    base_preset_id: Mapped[str] = mapped_column(String(160), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_character_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    expected_settings_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_binding_version: Mapped[int | None] = mapped_column(BigInteger)
    applied_settings_version: Mapped[int | None] = mapped_column(BigInteger)
    applied_binding_version: Mapped[int | None] = mapped_column(BigInteger)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parameters_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_digest_key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    reused_version: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoiceDesignDraft(Base):
    """Immutable character workspace projection used by VoiceGenerator."""

    __tablename__ = "voice_design_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_design_draft_novel_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_voice_design_draft_character_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "fingerprint",
            name="uq_voice_design_draft_fingerprint",
        ),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_voice_design_draft_fixed_local_scope",
        ),
        CheckConstraint(
            "character_version > 0 AND character_catalog_version >= 0",
            name="ck_voice_design_draft_character_versions",
        ),
        CheckConstraint(
            "workspace_digest ~ '^[0-9a-f]{64}$' "
            "AND brief_digest ~ '^[0-9a-f]{64}$' "
            "AND instruction_digest ~ '^[0-9a-f]{64}$' "
            "AND model_evidence_digest ~ '^[0-9a-f]{64}$' "
            "AND parameters_digest ~ '^[0-9a-f]{64}$' "
            "AND fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_voice_design_draft_digests",
        ),
        CheckConstraint(
            "instruction_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'",
            name="ck_voice_design_draft_digest_key",
        ),
        CheckConstraint(
            "brief_schema_version='character-voice-brief/1' "
            "AND brief_json->>'schema_version'='character-voice-brief/1'",
            name="ck_voice_design_draft_brief_schema",
        ),
        CheckConstraint(
            "char_length(instruction) BETWEEN 1 AND 1200 "
            "AND instruction=btrim(instruction)",
            name="ck_voice_design_draft_instruction",
        ),
        CheckConstraint(
            "language IN ('zh-CN','en','ja-JP') AND seed >= 0",
            name="ck_voice_design_draft_language_seed",
        ),
        CheckConstraint(
            "parameters_json->>'schema_version'='voice-generator-audio-parameters/1' "
            "AND parameters_json->>'audio_temperature_milli'='1500' "
            "AND parameters_json->>'audio_top_p_milli'='600' "
            "AND parameters_json->>'audio_top_k'='50' "
            "AND parameters_json->>'audio_repetition_penalty_milli'='1100'",
            name="ck_voice_design_draft_official_parameters",
        ),
        CheckConstraint(
            "runtime_identity_json->>'protocol_version'='moss-voice-generator-host/1' "
            "AND runtime_identity_json->>'topology'='mps-bf16-staged-process-v1' "
            "AND runtime_identity_json->>'voice_generator_revision'="
            "'97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4' "
            "AND runtime_identity_json->>'codec_revision'="
            "'3cd226ba2947efa357ef453bcad111b6eafba782'",
            name="ck_voice_design_draft_runtime_identity",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    character_catalog_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    brief_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    brief_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    brief_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    instruction_digest_key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    instruction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    model_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parameters_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoiceGeneratorCommand(Base):
    """Durable one-click character voice generation and CAS application."""

    __tablename__ = "voice_generator_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "owner_id", "workspace_id"],
            ["novels.id", "novels.owner_id", "novels.workspace_id"],
            name="fk_voice_generator_command_novel_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["character_id", "novel_id"],
            ["novel_characters.id", "novel_characters.novel_id"],
            name="fk_voice_generator_command_character_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["background_job_id", "owner_id", "workspace_id", "novel_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id", "background_jobs.novel_id"],
            name="fk_voice_generator_command_job_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["voice_version_id", "voice_profile_id"],
            ["voice_profile_versions.id", "voice_profile_versions.profile_id"],
            name="fk_voice_generator_command_version_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "idempotency_key",
            name="uq_voice_generator_command_idempotency",
        ),
        UniqueConstraint(
            "host_request_id",
            name="uq_voice_generator_command_host_request",
        ),
        Index(
            "ix_voice_generator_commands_scope_created",
            "owner_id",
            "workspace_id",
            "novel_id",
            "character_id",
            "created_at",
        ),
        Index(
            "uq_voice_generator_command_character_active",
            "novel_id",
            "character_id",
            unique=True,
            postgresql_where=text(
                "state IN ('queued','analyzing_character','waiting_for_heavy_runtime',"
                "'generating_voice','unloading_voice_generator','validating_with_nano')"
            ),
        ),
        CheckConstraint(
            "owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid "
            "AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid",
            name="ck_voice_generator_command_fixed_local_scope",
        ),
        CheckConstraint(
            "expected_binding_version >= 0 "
            "AND (applied_binding_version IS NULL OR applied_binding_version > 0)",
            name="ck_voice_generator_command_binding_versions",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$' "
            "AND request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_voice_generator_command_request_identity",
        ),
        CheckConstraint(
            "state IN ('queued','analyzing_character','waiting_for_heavy_runtime',"
            "'generating_voice','unloading_voice_generator','validating_with_nano',"
            "'ready_applied','ready_unapplied','failed_character_analysis',"
            "'failed_runtime_unavailable','failed_memory_safety','failed_generation',"
            "'failed_audio_validation','failed_nano_validation','failed_storage',"
            "'cancelled','superseded')",
            name="ck_voice_generator_command_state",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_voice_generator_command_failure_code",
        ),
        CheckConstraint(
            "progress_current >= 0 AND progress_total = 6 "
            "AND progress_current <= progress_total",
            name="ck_voice_generator_command_progress",
        ),
        CheckConstraint(
            "(draft_id IS NULL AND state IN ('queued','analyzing_character',"
            "'failed_character_analysis','cancelled','superseded')) OR draft_id IS NOT NULL",
            name="ck_voice_generator_command_draft_state",
        ),
        CheckConstraint(
            "(voice_profile_id IS NULL AND voice_version_id IS NULL) OR "
            "(voice_profile_id IS NOT NULL AND voice_version_id IS NOT NULL)",
            name="ck_voice_generator_command_voice_result_shape",
        ),
        CheckConstraint(
            "(state='ready_applied' AND voice_version_id IS NOT NULL "
            "AND applied_binding_version IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(state='ready_unapplied' AND voice_version_id IS NOT NULL "
            "AND applied_binding_version IS NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(state LIKE 'failed_%' AND completed_at IS NOT NULL "
            "AND applied_binding_version IS NULL AND failure_code IS NOT NULL) OR "
            "(state IN ('cancelled','superseded') AND completed_at IS NOT NULL "
            "AND applied_binding_version IS NULL) OR "
            "(state IN ('queued','analyzing_character','waiting_for_heavy_runtime',"
            "'generating_voice','unloading_voice_generator','validating_with_nano') "
            "AND completed_at IS NULL AND applied_binding_version IS NULL "
            "AND failure_code IS NULL)",
            name="ck_voice_generator_command_terminal_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("voice_design_drafts.id", ondelete="RESTRICT")
    )
    background_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    host_request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    expected_binding_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_binding_version: Mapped[int | None] = mapped_column(BigInteger)
    generated_reference_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    nano_validation_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    generator_model_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model_run_records.id", ondelete="RESTRICT")
    )
    nano_model_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model_run_records.id", ondelete="RESTRICT")
    )
    voice_profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    voice_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False, default="queued")
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoiceGeneratorRunEvidence(Base):
    """Immutable, path-free receipt for one native host generation attempt."""

    __tablename__ = "voice_generator_run_evidence"
    __table_args__ = (
        UniqueConstraint(
            "command_id",
            "attempt_number",
            name="uq_voice_generator_run_attempt_number",
        ),
        UniqueConstraint(
            "model_run_id",
            name="uq_voice_generator_run_model_run",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_voice_generator_run_attempt_number",
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$' "
            "AND runtime_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND instruction_digest ~ '^[0-9a-f]{64}$' "
            "AND (token_digest IS NULL OR token_digest ~ '^[0-9a-f]{64}$') "
            "AND (audio_digest IS NULL OR audio_digest ~ '^[0-9a-f]{64}$')",
            name="ck_voice_generator_run_digests",
        ),
        CheckConstraint(
            "result_classification IN ('success','retryable_failure',"
            "'non_retryable_failure','cancelled','security_failure')",
            name="ck_voice_generator_run_result",
        ),
        CheckConstraint(
            "protocol_version='moss-voice-generator-host/1' "
            "AND topology='mps-bf16-staged-process-v1'",
            name="ck_voice_generator_run_runtime_identity",
        ),
        CheckConstraint(
            "completed_at >= started_at",
            name="ck_voice_generator_run_time_order",
        ),
        CheckConstraint(
            "result_classification <> 'success' OR "
            "(token_digest IS NOT NULL AND audio_digest IS NOT NULL)",
            name="ck_voice_generator_run_success_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    command_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("voice_generator_commands.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    model_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("model_run_records.id", ondelete="RESTRICT"), nullable=False
    )
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(80), nullable=False)
    topology: Mapped[str] = mapped_column(String(80), nullable=False)
    runtime_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actual_identity_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    instruction_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    token_digest: Mapped[str | None] = mapped_column(String(64))
    audio_digest: Mapped[str | None] = mapped_column(String(64))
    audio_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    memory_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    exit_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CharacterAlias(Base):
    __tablename__ = "character_aliases"
    __table_args__ = (
        ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_character_alias_character_scope", ondelete="CASCADE"),
        UniqueConstraint("character_id", "normalized_alias", name="uq_character_alias_character_value"),
        Index("ix_character_aliases_novel_normalized", "novel_id", "normalized_alias", "lifecycle_state"),
        CheckConstraint("lifecycle_state IN ('active','conflicted','archived')", name="ck_character_alias_lifecycle"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    alias: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(240), nullable=False)
    character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    timeline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    alias_kind: Mapped[str | None] = mapped_column(String(30))
    valid_from_sequence: Mapped[int | None] = mapped_column(BigInteger)
    valid_to_sequence: Mapped[int | None] = mapped_column(BigInteger)
    identity_layer: Mapped[str | None] = mapped_column(String(30))
    knowledge_scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_character_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("novel_character_revisions.id", ondelete="RESTRICT"),
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CharacterVoiceBinding(Base):
    __tablename__ = "character_voice_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_character_voice_binding_character", ondelete="CASCADE"),
        ForeignKeyConstraint(["voice_version_id", "profile_id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_character_voice_binding_version"),
        UniqueConstraint("character_id", name="uq_character_voice_binding_character"),
        CheckConstraint("binding_policy IN ('dedicated','inherited','unset')", name="ck_character_voice_binding_policy"),
        CheckConstraint(
            "(binding_policy='unset' AND profile_id IS NULL AND voice_version_id IS NULL) OR "
            "(binding_policy IN ('dedicated','inherited') AND profile_id IS NOT NULL AND voice_version_id IS NOT NULL)",
            name="ck_character_voice_binding_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profiles.id", ondelete="RESTRICT"))
    voice_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    binding_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="unset")
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="zh-CN")
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GenericVoicePool(Base):
    __tablename__ = "generic_voice_pools"
    __table_args__ = (UniqueConstraint("novel_id", "name", "version_number", name="uq_generic_voice_pool_version"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class GenericVoiceSlot(Base):
    __tablename__ = "generic_voice_slots"
    __table_args__ = (
        UniqueConstraint("pool_id", "position", name="uq_generic_voice_slot_position"),
        UniqueConstraint("pool_id", "slot_key", name="uq_generic_voice_slot_key"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    pool_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("generic_voice_pools.id", ondelete="CASCADE"), nullable=False)
    slot_key: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    voice_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profile_versions.id", ondelete="RESTRICT"), nullable=False)
    labels_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class VoiceCastingRule(Base):
    __tablename__ = "voice_casting_rules"
    __table_args__ = (UniqueConstraint("novel_id", "priority", "version_number", name="uq_voice_casting_rule_priority"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    target_pool_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("generic_voice_pools.id", ondelete="RESTRICT"))
    target_slot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("generic_voice_slots.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnonymousSpeaker(Base):
    __tablename__ = "anonymous_speakers"
    __table_args__ = (
        UniqueConstraint("novel_id", "stable_key_algorithm", "stable_key", name="uq_anonymous_speaker_stable_key"),
        CheckConstraint("scope_kind IN ('scene','chapter','novel')", name="ck_anonymous_speaker_scope_kind"),
        CheckConstraint("confidence IN ('high','medium','low','unknown')", name="ck_anonymous_speaker_confidence"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    stable_key_algorithm: Mapped[str] = mapped_column(String(120), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    inferred_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    slot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("generic_voice_slots.id", ondelete="SET NULL"))
    voice_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profile_versions.id", ondelete="RESTRICT"))
    promoted_character_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novel_characters.id", ondelete="SET NULL"))
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")


class PronunciationProfile(Base):
    __tablename__ = "pronunciation_profiles"
    __table_args__ = (
        UniqueConstraint("novel_id", "version_number", name="uq_pronunciation_profile_version"),
        UniqueConstraint("novel_id", "fingerprint", name="uq_pronunciation_profile_fingerprint"),
        UniqueConstraint("id", "novel_id", name="uq_pronunciation_profile_edition_guard"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PronunciationEntry(Base):
    __tablename__ = "pronunciation_entries"
    __table_args__ = (
        UniqueConstraint("profile_id", "scope_kind", "scope_id", "normalized_source", "priority", name="uq_pronunciation_entry_match"),
        CheckConstraint("scope_kind IN ('novel','volume','chapter')", name="ck_pronunciation_entry_scope_kind"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pronunciation_profiles.id", ondelete="CASCADE"), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_source: Mapped[str] = mapped_column(Text, nullable=False)
    spoken_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)


class NarrationScript(Base):
    __tablename__ = "narration_scripts"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "novel_id"], ["documents.id", "documents.novel_id"], name="fk_narration_script_document_scope"),
        ForeignKeyConstraint(["revision_id", "document_id", "content_hash"], ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"], name="fk_narration_script_revision_guard"),
        UniqueConstraint("document_id", "revision_id", name="uq_narration_script_revision"),
        UniqueConstraint("id", "document_id", name="uq_narration_script_document_guard"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationScriptVersion(Base):
    __tablename__ = "narration_script_versions"
    __table_args__ = (
        UniqueConstraint("script_id", "version_number", name="uq_narration_script_version_number"),
        UniqueConstraint("script_id", "id", name="uq_narration_script_version_script_guard"),
        UniqueConstraint("id", "is_approved", name="uq_narration_script_version_approved_guard"),
        UniqueConstraint("script_id", "idempotency_key", name="uq_narration_script_version_idempotency"),
        ForeignKeyConstraint(
            ["script_id", "parent_version_id"],
            ["narration_script_versions.script_id", "narration_script_versions.id"],
            name="fk_narration_script_version_parent_same_script",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["approval_request_id", "approval_request_allows_edition"], ["narration_requests.id", "narration_requests.allows_edition"], name="fk_narration_script_version_approval_request"),
        CheckConstraint("state IN ('draft','analyzing','analyzed','review_required','approved','failed')", name="ck_narration_script_version_state"),
        CheckConstraint("approval_kind IS NULL OR approval_kind IN ('auto_no_blockers','manual_after_review')", name="ck_narration_script_version_approval_kind"),
        CheckConstraint("effective_policy IN ('blockers_only','always_review')", name="ck_narration_script_version_policy"),
        CheckConstraint("blocker_count >= 0 AND warning_count >= 0", name="ck_narration_script_version_counts"),
        CheckConstraint(
            "state <> 'approved' OR (blocker_count = 0 AND approval_kind IS NOT NULL AND approved_at IS NOT NULL "
            "AND approved_actor_type IS NOT NULL AND approved_actor_id IS NOT NULL "
            "AND approval_request_id IS NOT NULL AND approval_request_allows_edition IS TRUE)",
            name="ck_narration_script_version_approved_shape",
        ),
        CheckConstraint(
            "taxonomy_version = 'narration-review-taxonomy/1'",
            name="ck_narration_script_version_taxonomy_version",
        ),
        CheckConstraint(
            "approval_kind <> 'auto_no_blockers' OR (effective_policy = 'blockers_only' AND approval_request_id IS NOT NULL AND approval_request_allows_edition IS TRUE)",
            name="ck_narration_script_version_auto_policy",
        ),
        CheckConstraint(
            "approval_kind <> 'manual_after_review' OR (approved_actor_type = 'owner' AND approved_actor_id IS NOT NULL)",
            name="ck_narration_script_version_manual_actor",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    script_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_scripts.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    is_approved: Mapped[bool] = mapped_column(Boolean, Computed("state = 'approved'", persisted=True))
    analyzer_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    settings_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_model_fingerprint: Mapped[str | None] = mapped_column(String(64))
    actual_model_fingerprint: Mapped[str | None] = mapped_column(String(64))
    taxonomy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_kind: Mapped[str | None] = mapped_column(String(32))
    approval_request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    approval_request_allows_edition: Mapped[bool | None] = mapped_column(Boolean)
    effective_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    approved_actor_type: Mapped[str | None] = mapped_column(String(24))
    approved_actor_id: Mapped[str | None] = mapped_column(String(120))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationScene(Base):
    __tablename__ = "narration_scenes"
    __table_args__ = (UniqueConstraint("script_version_id", "ordinal", name="uq_narration_scene_ordinal"), UniqueConstraint("id", "script_version_id", name="uq_narration_scene_version_guard"))
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    script_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_script_versions.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start: Mapped[int | None] = mapped_column(Integer)
    source_end: Mapped[int | None] = mapped_column(Integer)
    boundary_source: Mapped[str] = mapped_column(String(40), nullable=False)
    local_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(240))


class NarrationSegment(Base):
    __tablename__ = "narration_segments"
    __table_args__ = (
        ForeignKeyConstraint(["scene_id", "script_version_id"], ["narration_scenes.id", "narration_scenes.script_version_id"], name="fk_narration_segment_scene_guard"),
        UniqueConstraint("script_version_id", "ordinal", name="uq_narration_segment_ordinal"),
        UniqueConstraint("id", "script_version_id", name="uq_narration_segment_version_guard"),
        CheckConstraint("speaker_kind IN ('narrator','character','anonymous','group','unknown')", name="ck_narration_segment_speaker_kind"),
        CheckConstraint("confidence IN ('high','medium','low','unknown')", name="ck_narration_segment_confidence"),
        CheckConstraint(
            "(source_start_utf16 IS NULL AND source_end_utf16 IS NULL) OR "
            "(source_start_utf16 IS NOT NULL AND source_end_utf16 IS NOT NULL "
            "AND source_start_utf16 >= 0 AND source_end_utf16 >= source_start_utf16)",
            name="ck_narration_segment_source_range",
        ),
        CheckConstraint("ordinal >= 0 AND pause_before_ms >= 0 AND pause_after_ms >= 0", name="ck_narration_segment_nonnegative"),
        CheckConstraint(
            "(speaker_kind='character' AND character_id IS NOT NULL AND anonymous_speaker_id IS NULL) OR "
            "(speaker_kind='anonymous' AND anonymous_speaker_id IS NOT NULL AND character_id IS NULL) OR "
            "(speaker_kind IN ('narrator','group','unknown') AND character_id IS NULL AND anonymous_speaker_id IS NULL)",
            name="ck_narration_segment_speaker_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    script_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_script_versions.id", ondelete="CASCADE"), nullable=False)
    scene_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    paragraph_ordinal: Mapped[int | None] = mapped_column(Integer)
    source_block_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source_start_utf16: Mapped[int | None] = mapped_column(Integer)
    source_end_utf16: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    spoken_text: Mapped[str] = mapped_column(Text, nullable=False)
    local_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anchor_before_hash: Mapped[str | None] = mapped_column(String(64))
    anchor_after_hash: Mapped[str | None] = mapped_column(String(64))
    speaker_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    character_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novel_characters.id", ondelete="RESTRICT"))
    anonymous_speaker_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("anonymous_speakers.id", ondelete="RESTRICT"))
    casting_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    emotion: Mapped[str | None] = mapped_column(String(24))
    expression: Mapped[str | None] = mapped_column(String(24))
    pause_before_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pause_after_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NarrationScriptIssue(Base):
    __tablename__ = "narration_script_issues"
    __table_args__ = (
        ForeignKeyConstraint(["segment_id", "script_version_id"], ["narration_segments.id", "narration_segments.script_version_id"], name="fk_narration_issue_segment_guard"),
        CheckConstraint("severity IN ('warning','blocker')", name="ck_narration_issue_severity"),
        CheckConstraint("taxonomy_version = 'narration-review-taxonomy/1'", name="ck_narration_issue_taxonomy_version"),
        CheckConstraint(
            "(severity='warning' AND code IN ('W_SPEAKER_MEDIUM_CONFIDENCE','W_NEW_ANONYMOUS_SPEAKER','W_GENERIC_VOICE_FALLBACK','W_MANUAL_OVERRIDE_INHERITED','W_PRONUNCIATION_SOFT_FALLBACK','W_CLOUD_ASSISTED_USED','W_SCENE_BOUNDARY_MEDIUM_CONFIDENCE')) OR "
            "(severity='blocker' AND code IN ('B_SPEAKER_UNKNOWN','B_SPEAKER_LOW_CONFIDENCE','B_CHARACTER_ALIAS_CONFLICT','B_CHARACTER_REFERENCE_INVALID','B_ANONYMOUS_IDENTITY_CONFLICT','B_CASTING_TARGET_UNRESOLVED','B_VOICE_MISSING','B_VOICE_VERSION_UNAVAILABLE','B_VOICE_RIGHTS_UNAVAILABLE','B_PRONUNCIATION_HARD_CONFLICT','B_CLOUD_DECISION_UNAVAILABLE'))",
            name="ck_narration_issue_taxonomy_code",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    script_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_script_versions.id", ondelete="CASCADE"), nullable=False)
    segment_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    taxonomy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_summary: Mapped[str | None] = mapped_column(String(500))
    evidence_digest: Mapped[str | None] = mapped_column(String(64))


class NarrationScriptReviewActionRecord(Base):
    """Immutable idempotency and provenance ledger for an owner review action."""

    __tablename__ = "narration_script_review_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "request_id",
                "owner_id",
                "workspace_id",
                "novel_id",
                "request_allows_render",
            ],
            [
                "narration_requests.id",
                "narration_requests.owner_id",
                "narration_requests.workspace_id",
                "narration_requests.novel_id",
                "narration_requests.allows_render",
            ],
            name="fk_narration_review_action_request_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["script_id", "parent_version_id"],
            ["narration_script_versions.script_id", "narration_script_versions.id"],
            name="fk_narration_review_action_parent_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["script_id", "result_version_id"],
            ["narration_script_versions.script_id", "narration_script_versions.id"],
            name="fk_narration_review_action_result_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["request_id", "script_id"],
            ["narration_requests.id", "narration_requests.review_script_id"],
            name="fk_narration_review_action_request_script",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["result_edition_id", "request_id"],
            ["narration_editions.id", "narration_editions.request_id"],
            name="fk_narration_review_action_result_edition",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["result_edition_id", "result_version_id"],
            ["narration_editions.id", "narration_editions.script_version_id"],
            name="fk_narration_review_action_edition_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint(
            "owner_id",
            "workspace_id",
            "idempotency_key",
            name="uq_narration_review_action_idempotency",
        ),
        UniqueConstraint(
            "request_id",
            "request_version_after",
            name="uq_narration_review_action_request_version",
        ),
        CheckConstraint(
            "action_kind IN ('patch_segment','reanalyze_segments','approve')",
            name="ck_narration_review_action_kind",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_narration_review_action_request_hash",
        ),
        CheckConstraint(
            "request_allows_render IS TRUE",
            name="ck_narration_review_action_generation_request",
        ),
        CheckConstraint(
            "request_version_before >= 1 AND "
            "request_version_after = request_version_before + 1",
            name="ck_narration_review_action_request_versions",
        ),
        CheckConstraint(
            "actor_type = 'owner' AND length(btrim(actor_id)) > 0",
            name="ck_narration_review_action_owner_actor",
        ),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_narration_review_action_idempotency_key",
        ),
        CheckConstraint(
            "(action_kind = 'approve' AND result_version_id = parent_version_id "
            "AND result_edition_id IS NOT NULL) OR "
            "(action_kind IN ('patch_segment','reanalyze_segments') "
            "AND result_version_id <> parent_version_id "
            "AND result_edition_id IS NULL)",
            name="ck_narration_review_action_result_shape",
        ),
        Index(
            "ix_narration_review_actions_request_created",
            "request_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_narration_review_actions_parent",
            "script_id",
            "parent_version_id",
        ),
        Index(
            "ix_narration_review_actions_result",
            "script_id",
            "result_version_id",
        ),
        Index("ix_narration_review_actions_edition", "result_edition_id"),
        Index(
            "uq_narration_review_action_approve_request",
            "request_id",
            unique=True,
            postgresql_where=text("action_kind = 'approve'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_allows_render: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    script_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    parent_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    result_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    result_edition_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_version_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_version_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BackgroundResourceClassPolicy(Base):
    """Server-owned registry for schedulable resource classes.

    Rows are installed by migrations.  API/tool payloads may name a job kind,
    but they cannot invent a resource class or publication-fence policy.
    """

    __tablename__ = "background_resource_class_policies"
    __table_args__ = (
        CheckConstraint("max_concurrency > 0", name="ck_background_resource_policy_slots"),
        CheckConstraint("version > 0", name="ck_background_resource_policy_version"),
        CheckConstraint(
            "requires_publish_fence IS FALSE OR exact_resource_key IS NOT NULL",
            name="ck_background_resource_policy_fence_key",
        ),
    )

    resource_class: Mapped[str] = mapped_column(String(80), primary_key=True)
    requires_publish_fence: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exact_resource_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundResourceClassSlot(Base):
    __tablename__ = "background_resource_class_slots"
    __table_args__ = (
        UniqueConstraint("resource_key", name="uq_background_resource_slot_key"),
        CheckConstraint("slot_number >= 0", name="ck_background_resource_slot_number"),
    )

    resource_class: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("background_resource_class_policies.resource_class", ondelete="RESTRICT"),
        primary_key=True,
    )
    slot_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_key: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundJobKindPolicy(Base):
    __tablename__ = "background_job_kind_policies"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_background_job_kind_policy_version"),
    )

    job_kind: Mapped[str] = mapped_column(String(80), primary_key=True)
    resource_class: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("background_resource_class_policies.resource_class", ondelete="RESTRICT"),
        nullable=False,
    )
    executor_key: Mapped[str] = mapped_column(String(80), nullable=False, default="narration-worker")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundExecutorEpoch(Base):
    __tablename__ = "background_executor_epochs"
    __table_args__ = (
        UniqueConstraint(
            "executor_key", "generation", name="uq_background_executor_epoch_generation"
        ),
        Index(
            "uq_background_executor_epoch_active",
            "executor_key",
            unique=True,
            postgresql_where=text("state='active'"),
        ),
        CheckConstraint("generation > 0", name="ck_background_executor_epoch_generation"),
        CheckConstraint(
            "state IN ('active','revoked')", name="ck_background_executor_epoch_state"
        ),
        CheckConstraint(
            "(state='active' AND revoked_at IS NULL AND revoked_actor IS NULL "
            "AND revoked_reason_code IS NULL) OR "
            "(state='revoked' AND revoked_at IS NOT NULL AND revoked_actor IS NOT NULL "
            "AND revoked_reason_code IS NOT NULL)",
            name="ck_background_executor_epoch_lifecycle",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    executor_key: Mapped[str] = mapped_column(String(80), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_actor: Mapped[str | None] = mapped_column(String(120))
    revoked_reason_code: Mapped[str | None] = mapped_column(String(96))


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "owner_id", "workspace_id", "novel_id", "request_allows_render"],
            ["narration_requests.id", "narration_requests.owner_id", "narration_requests.workspace_id", "narration_requests.novel_id", "narration_requests.allows_render"],
            name="fk_background_job_request_render_guard",
        ),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_background_job_novel_scope"),
        UniqueConstraint(
            "id", "owner_id", "workspace_id", "novel_id",
            name="uq_background_job_media_scope",
        ),
        UniqueConstraint(
            "id", "owner_id", "workspace_id",
            name="uq_background_job_command_scope",
        ),
        UniqueConstraint(
            "id", "owner_id", "workspace_id", "novel_id", "request_id",
            name="uq_background_job_publication_scope",
        ),
        UniqueConstraint("owner_id", "workspace_id", "idempotency_key", name="uq_background_job_idempotency"),
        CheckConstraint("state IN ('queued','running','retry_wait','succeeded','failed','dead_letter','cancel_requested','cancelled')", name="ck_background_job_state"),
        CheckConstraint(
            "job_kind NOT IN ('narration.segment_render','narration.export') OR "
            "(request_id IS NOT NULL AND novel_id IS NOT NULL AND request_allows_render IS TRUE)",
            name="ck_background_job_render_guard",
        ),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="ck_background_job_attempts"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"))
    request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    request_allows_render: Mapped[bool | None] = mapped_column(Boolean)
    job_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_class: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("background_resource_class_policies.resource_class", ondelete="RESTRICT"),
        nullable=False,
    )
    base_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    interactive_priority: Mapped[int | None] = mapped_column(Integer)
    interactive_priority_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_actor: Mapped[str | None] = mapped_column(String(120))
    cancel_reason_code: Mapped[str | None] = mapped_column(String(96))
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActiveJobAsset(Base):
    """Persistent asset reachability for non-terminal background jobs.

    Rows are append-only apart from the one-way ``released_at`` transition.
    A terminal job must have released every row in the same transaction.
    """

    __tablename__ = "active_job_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "owner_id", "workspace_id", "novel_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id", "background_jobs.novel_id"],
            name="fk_active_job_asset_job_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["asset_id", "owner_id", "workspace_id", "novel_id"],
            ["media_assets.id", "media_assets.owner_id", "media_assets.workspace_id", "media_assets.novel_id"],
            name="fk_active_job_asset_media_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "role IN ('input','working','output','checkpoint')",
            name="ck_active_job_asset_role",
        ),
        CheckConstraint(
            "released_at IS NULL OR released_at >= acquired_at",
            name="ck_active_job_asset_lifecycle",
        ),
        Index("ix_active_job_assets_unreleased", "asset_id", "released_at"),
    )

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackgroundManualRetryCommand(Base):
    """Immutable, idempotent authorisation for one manual retry attempt."""

    __tablename__ = "background_manual_retry_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "owner_id", "workspace_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id"],
            name="fk_background_manual_retry_job_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id", "workspace_id", "idempotency_key",
            name="uq_background_manual_retry_idempotency",
        ),
        UniqueConstraint(
            "claimed_attempt_id", name="uq_background_manual_retry_claimed_attempt"
        ),
        Index(
            "uq_background_manual_retry_pending_job",
            "job_id",
            unique=True,
            postgresql_where=text("state='pending'"),
        ),
        CheckConstraint(
            "state IN ('pending','claimed','cancelled')",
            name="ck_background_manual_retry_state",
        ),
        CheckConstraint(
            "(state='pending' AND claimed_attempt_id IS NULL AND claimed_at IS NULL "
            "AND cancelled_at IS NULL AND cancelled_actor IS NULL "
            "AND cancelled_reason_code IS NULL) OR "
            "(state='claimed' AND claimed_attempt_id IS NOT NULL AND claimed_at IS NOT NULL "
            "AND cancelled_at IS NULL AND cancelled_actor IS NULL "
            "AND cancelled_reason_code IS NULL) OR "
            "(state='cancelled' AND claimed_attempt_id IS NULL AND claimed_at IS NULL "
            "AND cancelled_at IS NOT NULL AND cancelled_actor IS NOT NULL "
            "AND cancelled_reason_code IS NOT NULL)",
            name="ck_background_manual_retry_lifecycle",
        ),
        CheckConstraint(
            "trim(idempotency_key) <> '' AND trim(actor) <> '' AND trim(reason) <> ''",
            name="ck_background_manual_retry_audit_text",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    claimed_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "background_job_attempts.id",
            name="fk_background_manual_retry_claimed_attempt",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_actor: Mapped[str | None] = mapped_column(String(120))
    cancelled_reason_code: Mapped[str | None] = mapped_column(String(96))


class BackgroundJobAttempt(Base):
    __tablename__ = "background_job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_background_job_attempt_number"),
        CheckConstraint("retry_kind IN ('initial','automatic','manual')", name="ck_background_job_attempt_retry_kind"),
        CheckConstraint("error_classification IS NULL OR error_classification IN ('retryable','non_retryable','cancelled','security_failure')", name="ck_background_job_attempt_error_class"),
        CheckConstraint("attempt_number > 0 AND lease_generation > 0", name="ck_background_job_attempt_positive"),
        UniqueConstraint(
            "manual_retry_command_id",
            name="uq_background_job_attempt_manual_retry_command",
        ),
        UniqueConstraint(
            "resource_key", "resource_lease_generation",
            name="uq_background_job_attempt_resource_generation",
        ),
        CheckConstraint(
            "(retry_kind='manual' AND manual_retry_command_id IS NOT NULL "
            "AND manual_actor IS NOT NULL AND manual_reason IS NOT NULL) OR "
            "(retry_kind IN ('initial','automatic') AND manual_retry_command_id IS NULL "
            "AND manual_actor IS NULL AND manual_reason IS NULL)",
            name="ck_background_job_attempt_manual_shape",
        ),
        CheckConstraint(
            "resource_lease_generation > 0",
            name="ck_background_job_attempt_resource_generation",
        ),
        CheckConstraint(
            "(completed_at IS NULL AND error_classification IS NULL "
            "AND error_code IS NULL AND actual_result_digest IS NULL) OR "
            "(completed_at IS NOT NULL AND ((actual_result_digest ~ '^[0-9a-f]{64}$' "
            "AND error_classification IS NULL AND error_code IS NULL) OR "
            "(actual_result_digest IS NULL AND error_classification IS NOT NULL "
            "AND error_code IS NOT NULL)))",
            name="ck_background_job_attempt_completion_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    manual_retry_command_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "background_manual_retry_commands.id",
            name="fk_background_job_attempt_manual_retry_command",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    manual_actor: Mapped[str | None] = mapped_column(String(120))
    manual_reason: Mapped[str | None] = mapped_column(String(240))
    executor_epoch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "background_executor_epochs.id",
            name="fk_background_job_attempt_executor_epoch",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    resource_key: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "background_resource_class_slots.resource_key",
            name="fk_background_job_attempt_resource_slot",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    resource_lease_token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    resource_lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(160), nullable=False)
    lease_token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_classification: Mapped[str | None] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(96))
    actual_result_digest: Mapped[str | None] = mapped_column(String(64))


class BackgroundResourceLock(Base):
    __tablename__ = "background_resource_locks"
    resource_key: Mapped[str] = mapped_column(
        String(160),
        ForeignKey(
            "background_resource_class_slots.resource_key",
            name="fk_background_resource_lock_slot",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    lease_owner: Mapped[str] = mapped_column(String(160), nullable=False)
    lease_token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRunRecord(Base):
    __tablename__ = "model_run_records"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "requested_model_id",
            name="uq_model_run_attempt",
        ),
        CheckConstraint(
            "result_classification IN "
            "('success','retryable_failure','non_retryable_failure','cancelled','security_failure')",
            name="ck_model_run_result_classification",
        ),
        CheckConstraint(
            "output_digest IS NULL OR output_digest ~ '^[0-9a-f]{64}$'",
            name="ck_model_run_output_digest_sha256",
        ),
        CheckConstraint(
            "result_classification <> 'success' OR "
            "(actual_model_id IS NOT NULL AND model_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND output_digest IS NOT NULL AND duration_ms IS NOT NULL AND duration_ms >= 0)",
            name="ck_model_run_success_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("background_job_attempts.id", ondelete="RESTRICT"), nullable=False)
    requested_provider_id: Mapped[str | None] = mapped_column(String(160))
    requested_model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_revision: Mapped[str | None] = mapped_column(String(160))
    actual_provider_id: Mapped[str | None] = mapped_column(String(160))
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
    actual_revision: Mapped[str | None] = mapped_column(String(160))
    model_fingerprint: Mapped[str | None] = mapped_column(String(64))
    parameters_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    input_digest_key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    output_digest: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    provider_request_id: Mapped[str | None] = mapped_column(String(240))
    result_classification: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationEdition(Base):
    __tablename__ = "narration_editions"
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "request_allows_edition"], ["narration_requests.id", "narration_requests.allows_edition"], name="fk_narration_edition_request_guard"),
        ForeignKeyConstraint(["script_version_id", "script_is_approved"], ["narration_script_versions.id", "narration_script_versions.is_approved"], name="fk_narration_edition_approved_guard"),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_narration_edition_novel_scope"),
        ForeignKeyConstraint(
            ["settings_snapshot_id", "owner_id", "workspace_id", "novel_id"],
            ["narration_settings_snapshots.id", "narration_settings_snapshots.owner_id", "narration_settings_snapshots.workspace_id", "narration_settings_snapshots.novel_id"],
            name="fk_narration_edition_settings_scope",
        ),
        ForeignKeyConstraint(
            ["pronunciation_profile_id", "novel_id"],
            ["pronunciation_profiles.id", "pronunciation_profiles.novel_id"],
            name="fk_narration_edition_pronunciation_scope",
        ),
        UniqueConstraint("owner_id", "workspace_id", "edition_fingerprint", name="uq_narration_edition_fingerprint"),
        UniqueConstraint("id", "script_version_id", name="uq_narration_edition_script_guard"),
        UniqueConstraint("id", "request_id", name="uq_narration_edition_request_guard"),
        CheckConstraint("request_allows_edition IS TRUE AND script_is_approved IS TRUE", name="ck_narration_edition_guards"),
        CheckConstraint("context_mode = 'independent_segment'", name="ck_narration_edition_context_mode"),
        CheckConstraint(
            "state IN ('created','rendering','partial_ready','ready','unavailable')",
            name="ck_narration_edition_state",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_allows_edition: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    script_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    script_is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings_snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_settings_snapshots.id", ondelete="RESTRICT"), nullable=False)
    pronunciation_profile_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pronunciation_profiles.id", ondelete="RESTRICT"))
    tts_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    tokenizer_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    postprocess_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    context_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="independent_segment")
    buffer_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    edition_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    unavailable_reason: Mapped[str | None] = mapped_column(String(96))
    created_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationEditionSegment(Base):
    __tablename__ = "narration_edition_segments"
    __table_args__ = (
        ForeignKeyConstraint(["edition_id", "script_version_id"], ["narration_editions.id", "narration_editions.script_version_id"], name="fk_narration_edition_segment_edition"),
        ForeignKeyConstraint(["segment_id", "script_version_id"], ["narration_segments.id", "narration_segments.script_version_id"], name="fk_narration_edition_segment_script"),
        ForeignKeyConstraint(["voice_version_id", "profile_id"], ["voice_profile_versions.id", "voice_profile_versions.profile_id"], name="fk_narration_edition_segment_voice_guard"),
        UniqueConstraint("edition_id", "ordinal", name="uq_narration_edition_segment_ordinal"),
        UniqueConstraint("id", "edition_id", name="uq_narration_edition_segment_edition_guard"),
        CheckConstraint(
            "render_state IN ('pending','queued','rendering','ready','failed','cancelled','quarantined')",
            name="ck_narration_edition_segment_state",
        ),
        CheckConstraint(
            "render_digest_key_id IS NULL OR "
            "render_digest_key_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$'",
            name="ck_narration_edition_segment_digest_key_id",
        ),
        CheckConstraint("ordinal >= 0 AND gap_after_ms >= 0", name="ck_narration_edition_segment_nonnegative"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    edition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    script_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    segment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("generic_voice_slots.id", ondelete="RESTRICT"))
    profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profiles.id", ondelete="RESTRICT"), nullable=False)
    voice_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profile_versions.id", ondelete="RESTRICT"), nullable=False)
    resolution_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    render_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL identifies legacy narration-render-input/1 rows.  Every new v2
    # Edition freezes the HMAC key identity used for its private spoken-text
    # cache digest so later key rotation cannot make the Edition unverifiable.
    render_digest_key_id: Mapped[str | None] = mapped_column(String(80))
    render_state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    gap_after_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(96))


class NarrationSegmentRender(Base):
    __tablename__ = "narration_segment_renders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "owner_id", "workspace_id", "novel_id", "request_allows_render"],
            ["narration_requests.id", "narration_requests.owner_id", "narration_requests.workspace_id", "narration_requests.novel_id", "narration_requests.allows_render"],
            name="fk_narration_segment_render_request_guard",
        ),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_narration_segment_render_novel_scope"),
        ForeignKeyConstraint(
            ["source_job_id", "owner_id", "workspace_id", "novel_id", "request_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id", "background_jobs.novel_id", "background_jobs.request_id"],
            name="fk_narration_segment_render_source_job_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "workspace_id", "render_fingerprint", name="uq_narration_segment_render_fingerprint"),
        UniqueConstraint("source_job_id", name="uq_narration_segment_render_source_job"),
        CheckConstraint("request_allows_render IS TRUE", name="ck_narration_segment_render_request_guard"),
        CheckConstraint("state IN ('pending','rendering','ready','failed','cancelled','quarantined')", name="ck_narration_segment_render_state"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_narration_segment_render_duration"),
        CheckConstraint(
            "state <> 'ready' OR (duration_ms IS NOT NULL AND ready_at IS NOT NULL)",
            name="ck_narration_segment_render_ready_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_allows_render: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    render_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    voice_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profile_versions.id", ondelete="RESTRICT"), nullable=False)
    model_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    postprocess_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    source_job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    audio_validation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrationRenderAsset(Base):
    __tablename__ = "narration_render_assets"
    __table_args__ = (
        UniqueConstraint("render_id", "role", name="uq_narration_render_asset_role"),
        UniqueConstraint("asset_id", name="uq_narration_render_asset_asset"),
        CheckConstraint("role IN ('master','playback')", name="ck_narration_render_asset_role"),
        CheckConstraint(
            "actual_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_narration_render_asset_sha256",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    render_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_segment_renders.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class NarrationExport(Base):
    __tablename__ = "narration_exports"
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "request_allows_render"], ["narration_requests.id", "narration_requests.allows_render"], name="fk_narration_export_request_guard"),
        ForeignKeyConstraint(
            ["edition_id", "request_id"], ["narration_editions.id", "narration_editions.request_id"],
            name="fk_narration_export_edition_request_guard",
        ),
        UniqueConstraint("edition_id", "export_fingerprint", name="uq_narration_export_fingerprint"),
        UniqueConstraint("asset_id", name="uq_narration_export_asset"),
        CheckConstraint("request_allows_render IS TRUE", name="ck_narration_export_request_guard"),
        CheckConstraint("state IN ('staging','ready','failed','cancelled','quarantined')", name="ck_narration_export_state"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    edition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_editions.id", ondelete="RESTRICT"), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_allows_render: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    export_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationManifest(Base):
    __tablename__ = "narration_manifests"
    __table_args__ = (
        UniqueConstraint("edition_id", "manifest_revision", name="uq_narration_manifest_revision"),
        UniqueConstraint("id", "edition_id", "manifest_revision", name="uq_narration_manifest_state_guard"),
        UniqueConstraint("id", "edition_id", name="uq_narration_manifest_edition_guard"),
        CheckConstraint("manifest_revision >= 1", name="ck_narration_manifest_revision"),
        CheckConstraint("schema_version = 'narration-manifest/2.0'", name="ck_narration_manifest_schema"),
        CheckConstraint("status IN ('partial_ready','ready','unavailable')", name="ck_narration_manifest_status"),
        CheckConstraint("ready_prefix_count >= 0 AND total_duration_ms >= 0", name="ck_narration_manifest_nonnegative"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    edition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_editions.id", ondelete="RESTRICT"), nullable=False)
    manifest_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(120), nullable=False)
    canonical_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    etag_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ready_prefix_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ready_ranges_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrationManifestSegment(Base):
    __tablename__ = "narration_manifest_segments"
    __table_args__ = (
        UniqueConstraint("manifest_id", "ordinal", name="uq_narration_manifest_segment_ordinal"),
        ForeignKeyConstraint(["edition_segment_id", "edition_id"], ["narration_edition_segments.id", "narration_edition_segments.edition_id"], name="fk_narration_manifest_segment_edition"),
        ForeignKeyConstraint(["manifest_id", "edition_id"], ["narration_manifests.id", "narration_manifests.edition_id"], name="fk_narration_manifest_segment_manifest_edition"),
        CheckConstraint(
            "render_state IN ('pending','rendering','ready','failed','unavailable')",
            name="ck_narration_manifest_segment_state",
        ),
        CheckConstraint(
            "ordinal >= 0 AND gap_after_ms >= 0 AND (duration_ms IS NULL OR duration_ms >= 0)",
            name="ck_narration_manifest_segment_nonnegative",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    manifest_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_manifests.id", ondelete="CASCADE"), nullable=False)
    edition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    edition_segment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    render_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_segment_renders.id", ondelete="RESTRICT"))
    render_state: Mapped[str] = mapped_column(String(24), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    gap_after_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NarrationEditionState(Base):
    __tablename__ = "narration_edition_state"
    __table_args__ = (
        ForeignKeyConstraint(["current_manifest_id", "edition_id", "current_manifest_revision"], ["narration_manifests.id", "narration_manifests.edition_id", "narration_manifests.manifest_revision"], name="fk_narration_edition_state_manifest"),
        UniqueConstraint("edition_id", name="uq_narration_edition_state_edition"),
        CheckConstraint(
            "(current_manifest_id IS NULL AND current_manifest_revision IS NULL) OR "
            "(current_manifest_id IS NOT NULL AND current_manifest_revision IS NOT NULL)",
            name="ck_narration_edition_state_manifest_shape",
        ),
    )
    edition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_editions.id", ondelete="CASCADE"), primary_key=True)
    current_manifest_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    current_manifest_revision: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentNarrationState(Base):
    __tablename__ = "document_narration_state"
    __table_args__ = (
        UniqueConstraint("owner_id", "workspace_id", "document_id", name="uq_document_narration_state_document"),
        ForeignKeyConstraint(["current_script_version_id", "script_id"], ["narration_script_versions.id", "narration_script_versions.script_id"], name="fk_document_narration_state_script_version"),
        ForeignKeyConstraint(["script_id", "document_id"], ["narration_scripts.id", "narration_scripts.document_id"], name="fk_document_narration_state_script"),
        CheckConstraint(
            "(script_id IS NULL AND current_script_version_id IS NULL) OR "
            "(script_id IS NOT NULL AND current_script_version_id IS NOT NULL)",
            name="ck_document_narration_state_script_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    script_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    current_script_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    current_edition_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_editions.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    switched_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    switched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrationPlaybackProgress(Base):
    __tablename__ = "narration_playback_progress"
    __table_args__ = (
        UniqueConstraint("owner_id", "workspace_id", "profile_id", "edition_id", name="uq_narration_playback_progress"),
        ForeignKeyConstraint(["edition_id", "manifest_revision"], ["narration_manifests.edition_id", "narration_manifests.manifest_revision"], name="fk_narration_playback_manifest_revision"),
        ForeignKeyConstraint(["edition_segment_id", "edition_id"], ["narration_edition_segments.id", "narration_edition_segments.edition_id"], name="fk_narration_playback_edition_segment"),
        CheckConstraint(
            "offset_ms >= 0 AND last_legal_start_ordinal >= 0 "
            "AND playback_rate_millis BETWEEN 250 AND 4000",
            name="ck_narration_playback_nonnegative",
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(160), nullable=False)
    edition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_editions.id", ondelete="CASCADE"), nullable=False)
    manifest_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    edition_segment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("narration_edition_segments.id", ondelete="CASCADE"), nullable=False)
    offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_legal_start_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    playback_rate_millis: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VoiceDeletionRequest(Base):
    __tablename__ = "voice_deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "state IN ('grace_pending','requested','cancelled','live_deleting',"
            "'live_deleted_backup_pending','completed','failed','superseded')",
            name="ck_voice_deletion_request_state",
        ),
        CheckConstraint(
            "command IN ('delete_uploaded_original_only','discard_unreferenced_private_voice',"
            "'true_delete_private_voice')",
            name="ck_voice_deletion_request_command",
        ),
        CheckConstraint(
            "state NOT IN ('live_deleting','live_deleted_backup_pending','completed') OR "
            "(confirmed_actor IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_voice_deletion_confirmation_shape",
        ),
        CheckConstraint(
            "asset_count >= 0 AND total_bytes >= 0",
            name="ck_voice_deletion_request_asset_totals",
        ),
        CheckConstraint(
            "external_backup_status IN ('unmanaged','managed_pending','managed_expired')",
            name="ck_voice_deletion_request_backup_status",
        ),
        CheckConstraint(
            "(state='superseded' AND superseded_at IS NOT NULL "
            "AND failure_code IN ('VOICE_DELETE_PROFILE_CHANGED',"
            "'VOICE_DELETE_IMPACT_CHANGED','VOICE_DELETE_IMPACT_EXPIRED',"
            "'VOICE_DELETE_JOB_DRAIN_TIMEOUT')) OR "
            "(state<>'superseded' AND superseded_at IS NULL)",
            name="ck_voice_deletion_request_superseded_shape",
        ),
        CheckConstraint(
            "(job_drain_started_at IS NULL AND job_drain_deadline IS NULL) OR "
            "(job_drain_started_at IS NOT NULL AND job_drain_deadline IS NOT NULL "
            "AND job_drain_deadline>job_drain_started_at)",
            name="ck_voice_deletion_request_job_drain_shape",
        ),
        CheckConstraint(
            "(state='failed' AND failure_code IN ("
            "'VOICE_DELETE_WAITING_FOR_JOBS','VOICE_DELETE_UNLINK_FAILED',"
            "'VOICE_DELETE_STORAGE_TEMPORARY','VOICE_DELETE_FINALIZE_FAILED',"
            "'VOICE_DELETE_SCOPE_INVALID','VOICE_DELETE_FILE_IDENTITY_INVALID',"
            "'VOICE_DELETE_ASSET_PLAN_INVALID')) OR "
            "(state='superseded' AND failure_code IN ("
            "'VOICE_DELETE_PROFILE_CHANGED','VOICE_DELETE_IMPACT_CHANGED',"
            "'VOICE_DELETE_IMPACT_EXPIRED','VOICE_DELETE_JOB_DRAIN_TIMEOUT')) OR "
            "(state NOT IN ('failed','superseded') AND failure_code IS NULL)",
            name="ck_voice_deletion_request_failure_shape",
        ),
        Index(
            "ix_voice_deletion_requests_scope_profile_state",
            "owner_id",
            "workspace_id",
            "voice_profile_id",
            "state",
        ),
        Index(
            "uq_voice_deletion_requests_idempotency",
            "owner_id",
            "workspace_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_voice_deletion_requests_active_profile",
            "owner_id",
            "workspace_id",
            "voice_profile_id",
            unique=True,
            postgresql_where=text(
                "state IN ('grace_pending','requested','live_deleting',"
                "'live_deleted_backup_pending','failed')"
            ),
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT")
    )
    voice_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_profiles.id", ondelete="RESTRICT"), nullable=False)
    command: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="requested")
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    expected_profile_version: Mapped[int | None] = mapped_column(BigInteger)
    impact_digest_key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    impact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    impact_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    impact_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execute_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    asset_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    external_backup_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unmanaged"
    )
    requested_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_actor: Mapped[str | None] = mapped_column(String(120))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_actor: Mapped[str | None] = mapped_column(String(120))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_drain_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_drain_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VoiceDeletionAssetPlan(Base):
    __tablename__ = "voice_deletion_asset_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "owner_id", "workspace_id"],
            ["media_assets.id", "media_assets.owner_id", "media_assets.workspace_id"],
            name="fk_voice_deletion_asset_plan_media_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "deletion_request_id",
            "asset_id",
            name="uq_voice_deletion_asset_plan_request_asset",
        ),
        CheckConstraint(
            "role IN ('reference','preview','render_master','render_playback','export')",
            name="ck_voice_deletion_asset_plan_role",
        ),
        CheckConstraint(
            "state IN ('planned','unlinking','unlinked','finalized','failed')",
            name="ck_voice_deletion_asset_plan_state",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$' AND byte_size >= 0 AND gc_generation >= 0",
            name="ck_voice_deletion_asset_plan_identity",
        ),
        CheckConstraint(
            "(file_present IS TRUE AND device IS NOT NULL AND inode IS NOT NULL) OR "
            "(file_present IS FALSE AND device IS NULL AND inode IS NULL)",
            name="ck_voice_deletion_asset_plan_file_identity",
        ),
        Index(
            "ix_voice_deletion_asset_plans_request_state",
            "deletion_request_id",
            "state",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    deletion_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("voice_deletion_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gc_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    device: Mapped[int | None] = mapped_column(BigInteger)
    inode: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="planned")
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetTombstone(Base):
    __tablename__ = "asset_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "original_asset_id", name="uq_asset_tombstone_original_asset"
        ),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    original_asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    deletion_request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("voice_deletion_requests.id", ondelete="RESTRICT"))
    digest_key_id: Mapped[str] = mapped_column(String(80), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    deleted_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
