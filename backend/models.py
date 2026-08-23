"""SQLAlchemy models for the MVP-0 novel authority ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
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
    cover_asset_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    outline_target_chapters: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    highlight: Mapped[str] = mapped_column(Text, nullable=False, default="")
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    main_plot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    story_ledger_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
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
    __table_args__ = (UniqueConstraint("novel_id", "position", name="uq_volume_position"),)

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
        UniqueConstraint("document_id", "kind", "input_hash", name="uq_chapter_generation_input"),
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
    requested_model_id: Mapped[str] = mapped_column(
        String(120), nullable=False, default="MiniMax-M3"
    )
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
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
    model_profile_fingerprint: Mapped[str] = mapped_column(
        String(160), nullable=False, default="qwenpaw-active-agent"
    )
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
    __table_args__ = (Index("ix_story_facts_novel_type", "novel_id", "fact_type"),)

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
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntelligenceProposal(Base):
    """AI-extracted story-ledger changes awaiting explicit author review."""

    __tablename__ = "intelligence_proposals"
    __table_args__ = (
        UniqueConstraint(
            "chapter_revision_id", "input_hash", name="uq_intelligence_revision_input"
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
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    requested_model_id: Mapped[str] = mapped_column(
        String(120), nullable=False, default="MiniMax-M3"
    )
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
    provider_profile: Mapped[str | None] = mapped_column(String(160))
    model_profile_fingerprint: Mapped[str] = mapped_column(
        String(160), nullable=False, default="qwenpaw-active-agent"
    )
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


class NovelChunk(Base):
    __tablename__ = "novel_chunks"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "embedding_profile", "chunk_index", name="uq_novel_chunk_profile_index"
        ),
        Index("ix_novel_chunks_revision", "revision_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="CASCADE"), nullable=False
    )
    embedding_profile: Mapped[str] = mapped_column(String(160), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (Index("ix_media_assets_novel_kind", "novel_id", "kind"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "source_character_id", "target_character_id", "relation_type",
            name="uq_character_relationship_edge",
        ),
        Index("ix_character_relationships_novel", "novel_id"),
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
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Storyline(Base):
    __tablename__ = "storylines"
    __table_args__ = (
        UniqueConstraint("novel_id", "position", name="uq_storyline_position"),
        Index("ix_storylines_novel_type", "novel_id", "storyline_type"),
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
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    target_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
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
    """Auditable MiniMax generation for naming, outline steps and chapter outlines."""

    __tablename__ = "creative_generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "scope_type", "scope_id", "kind", "input_hash", "attempt",
            name="uq_creative_generation_attempt",
        ),
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
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False, default="MiniMax-M3")
    actual_model_id: Mapped[str | None] = mapped_column(String(160))
    provider_profile: Mapped[str | None] = mapped_column(String(160))
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_character_count: Mapped[int | None] = mapped_column(Integer)
    output_visible_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
