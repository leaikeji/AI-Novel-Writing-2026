"""SQLAlchemy models for the MVP-0 novel authority ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
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
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(
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
