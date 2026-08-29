"""Unified creative authority, story-state, private-library and semantic-index ORM.

The tables in this module are additive.  Legacy projection columns remain in
``backend.models`` until the explicit test-data rebuild and release gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class NovelOutlineRevision(Base):
    __tablename__ = "novel_outline_revisions"
    __table_args__ = (
        UniqueConstraint("novel_id", "revision_number", name="uq_outline_revision_number"),
        UniqueConstraint("novel_id", "idempotency_key", name="uq_outline_revision_idempotency"),
        UniqueConstraint("id", "novel_id", name="uq_outline_revision_novel_scope"),
        ForeignKeyConstraint(
            ["parent_revision_id", "novel_id"],
            ["novel_outline_revisions.id", "novel_outline_revisions.novel_id"],
            name="fk_outline_revision_parent_scope",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["restored_from_revision_id", "novel_id"],
            ["novel_outline_revisions.id", "novel_outline_revisions.novel_id"],
            name="fk_outline_revision_restore_scope",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("revision_number > 0", name="ck_outline_revision_number"),
        CheckConstraint("target_chapter_count > 0", name="ck_outline_target_chapters"),
        CheckConstraint("char_length(content_hash) = 64", name="ck_outline_content_hash"),
        CheckConstraint("char_length(request_hash) = 64", name="ck_outline_request_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    revision_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("creative_generation_jobs.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_chapter_count: Mapped[int] = mapped_column(Integer, nullable=False)
    background_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plot_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    highlight_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    character_revision_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    character_reference_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    change_set_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NovelOutlineHead(Base):
    __tablename__ = "novel_outline_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["current_revision_id", "novel_id"],
            ["novel_outline_revisions.id", "novel_outline_revisions.novel_id"],
            name="fk_outline_head_current_scope",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("version > 0", name="ck_outline_head_version"),
    )

    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    established_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    establishment_source: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NovelSettingRevision(Base):
    __tablename__ = "novel_setting_revisions"
    __table_args__ = (
        UniqueConstraint("novel_id", "revision_number", name="uq_setting_revision_number"),
        UniqueConstraint("novel_id", "idempotency_key", name="uq_setting_revision_idempotency"),
        UniqueConstraint("id", "novel_id", name="uq_setting_revision_novel_scope"),
        ForeignKeyConstraint(["parent_revision_id", "novel_id"], ["novel_setting_revisions.id", "novel_setting_revisions.novel_id"], name="fk_setting_revision_parent_scope", deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(["restored_from_revision_id", "novel_id"], ["novel_setting_revisions.id", "novel_setting_revisions.novel_id"], name="fk_setting_revision_restore_scope", deferrable=True, initially="DEFERRED"),
        CheckConstraint("revision_number > 0", name="ck_setting_revision_number"),
        CheckConstraint("schema_version > 0", name="ck_setting_schema_version"),
        CheckConstraint("char_length(content_hash) = 64", name="ck_setting_content_hash"),
        CheckConstraint("char_length(request_hash) = 64", name="ck_setting_request_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    revision_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("creative_generation_jobs.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_id: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    change_set_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NovelSettingHead(Base):
    __tablename__ = "novel_setting_heads"
    __table_args__ = (
        ForeignKeyConstraint(["current_revision_id", "novel_id"], ["novel_setting_revisions.id", "novel_setting_revisions.novel_id"], name="fk_setting_head_current_scope", deferrable=True, initially="DEFERRED"),
        CheckConstraint("version > 0", name="ck_setting_head_version"),
    )

    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    established_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    establishment_source: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NovelCharacterRevision(Base):
    __tablename__ = "novel_character_revisions"
    __table_args__ = (
        UniqueConstraint("character_id", "character_version", name="uq_character_revision_number"),
        UniqueConstraint("novel_id", "operation_key", "character_id", name="uq_character_revision_operation"),
        UniqueConstraint("id", "character_id", "novel_id", name="uq_character_revision_scope"),
        ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_character_revision_root_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["parent_revision_id", "character_id", "novel_id"], ["novel_character_revisions.id", "novel_character_revisions.character_id", "novel_character_revisions.novel_id"], name="fk_character_revision_parent_scope", deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(["restored_from_revision_id", "character_id", "novel_id"], ["novel_character_revisions.id", "novel_character_revisions.character_id", "novel_character_revisions.novel_id"], name="fk_character_revision_restore_scope", deferrable=True, initially="DEFERRED"),
        CheckConstraint("character_version > 0", name="ck_character_revision_number"),
        CheckConstraint("char_length(content_hash) = 64 AND char_length(operation_hash) = 64", name="ck_character_revision_hashes"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("creative_generation_jobs.id", ondelete="RESTRICT"))
    source_batch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("character_profile_apply_batches.id", ondelete="RESTRICT"))
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(30), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    change_set_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StoryTimeline(Base):
    __tablename__ = "story_timelines"
    __table_args__ = (
        UniqueConstraint("id", "novel_id", name="uq_story_timeline_novel_scope"),
        UniqueConstraint("novel_id", "timeline_key", name="uq_story_timeline_key"),
        ForeignKeyConstraint(["parent_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_story_timeline_parent_scope", deferrable=True, initially="DEFERRED"),
        Index("uq_story_timeline_primary", "novel_id", unique=True, postgresql_where=text("is_primary IS TRUE")),
        Index("uq_story_timeline_active_name", "novel_id", "normalized_name", unique=True, postgresql_where=text("lifecycle_state='active'")),
        CheckConstraint("timeline_kind IN ('main','branch','merge')", name="ck_story_timeline_kind"),
        CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_story_timeline_lifecycle"),
        CheckConstraint("version > 0", name="ck_story_timeline_version"),
        CheckConstraint("parent_timeline_id IS NULL OR parent_timeline_id <> id", name="ck_story_timeline_not_self_parent"),
        CheckConstraint("NOT is_primary OR parent_timeline_id IS NULL", name="ck_story_timeline_primary_parent"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    timeline_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    timeline_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_timeline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    fork_story_sequence: Mapped[int | None] = mapped_column(BigInteger)
    fork_anchor_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StoryTimelineLink(Base):
    __tablename__ = "story_timeline_links"
    __table_args__ = (
        ForeignKeyConstraint(["source_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_timeline_link_source_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["target_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_timeline_link_target_scope", ondelete="CASCADE"),
        UniqueConstraint("novel_id", "link_fingerprint", name="uq_timeline_link_fingerprint"),
        CheckConstraint("source_timeline_id <> target_timeline_id", name="ck_timeline_link_distinct"),
        CheckConstraint("link_type IN ('travel','memory_transfer','causal','loop_return','merge_reference')", name="ck_timeline_link_type"),
        CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_timeline_link_lifecycle"),
        CheckConstraint("char_length(link_fingerprint) = 64", name="ck_timeline_link_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    source_timeline_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_timeline_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    link_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_story_sequence: Mapped[int | None] = mapped_column(BigInteger)
    target_story_sequence: Mapped[int | None] = mapped_column(BigInteger)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    link_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CharacterInstance(Base):
    __tablename__ = "character_instances"
    __table_args__ = (
        UniqueConstraint("id", "novel_id", name="uq_character_instance_novel_scope"),
        ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_character_instance_root_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["origin_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_character_instance_timeline_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["derived_from_instance_id", "novel_id"], ["character_instances.id", "character_instances.novel_id"], name="fk_character_instance_source_scope", deferrable=True, initially="DEFERRED"),
        Index("uq_character_instance_active_origin", "novel_id", "origin_timeline_id", "character_id", unique=True, postgresql_where=text("lifecycle_state='active'")),
        CheckConstraint("derived_from_instance_id IS NULL OR derived_from_instance_id <> id", name="ck_character_instance_not_self"),
        CheckConstraint("continuity_kind IN ('native','derived','traveler')", name="ck_character_instance_continuity"),
        CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_character_instance_lifecycle"),
        CheckConstraint("version > 0", name="ck_character_instance_version"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    character_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    origin_timeline_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    derived_from_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    continuity_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    display_label: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    current_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CharacterInstanceRevision(Base):
    __tablename__ = "character_instance_revisions"
    __table_args__ = (
        UniqueConstraint("character_instance_id", "revision_number", name="uq_character_instance_revision_number"),
        UniqueConstraint("novel_id", "operation_key", "character_instance_id", name="uq_character_instance_revision_operation"),
        UniqueConstraint("id", "character_instance_id", "novel_id", name="uq_character_instance_revision_scope"),
        ForeignKeyConstraint(["character_instance_id", "novel_id"], ["character_instances.id", "character_instances.novel_id"], name="fk_character_instance_revision_root_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["parent_revision_id", "character_instance_id", "novel_id"], ["character_instance_revisions.id", "character_instance_revisions.character_instance_id", "character_instance_revisions.novel_id"], name="fk_character_instance_revision_parent_scope", deferrable=True, initially="DEFERRED"),
        ForeignKeyConstraint(["restored_from_revision_id", "character_instance_id", "novel_id"], ["character_instance_revisions.id", "character_instance_revisions.character_instance_id", "character_instance_revisions.novel_id"], name="fk_character_instance_revision_restore_scope", deferrable=True, initially="DEFERRED"),
        CheckConstraint("revision_number > 0 AND profile_schema_version > 0", name="ck_character_instance_revision_versions"),
        CheckConstraint("char_length(operation_hash) = 64 AND char_length(content_hash) = 64", name="ck_character_instance_revision_hashes"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    character_instance_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    change_set_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# Close the current-revision cycle after both tables are declared.
CharacterInstance.__table__.append_constraint(
    ForeignKeyConstraint(
        [CharacterInstance.__table__.c.current_revision_id, CharacterInstance.__table__.c.id, CharacterInstance.__table__.c.novel_id],
        [CharacterInstanceRevision.__table__.c.id, CharacterInstanceRevision.__table__.c.character_instance_id, CharacterInstanceRevision.__table__.c.novel_id],
        name="fk_character_instance_current_revision_scope",
        deferrable=True,
        initially="DEFERRED",
        use_alter=True,
    )
)


class RevisionTimelineMapping(Base):
    __tablename__ = "revision_timeline_mappings"
    __table_args__ = (
        UniqueConstraint("revision_id", "mapping_version", name="uq_revision_timeline_mapping_version"),
        UniqueConstraint("revision_id", "operation_key", name="uq_revision_timeline_mapping_operation"),
        UniqueConstraint("id", "revision_id", "document_id", "novel_id", name="uq_revision_timeline_mapping_scope"),
        UniqueConstraint("id", "novel_id", name="uq_revision_timeline_mapping_novel_scope"),
        ForeignKeyConstraint(["document_id", "novel_id"], ["documents.id", "documents.novel_id"], name="fk_revision_mapping_document_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["revision_id", "document_id", "source_content_hash"], ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"], name="fk_revision_mapping_source_guard", ondelete="CASCADE"),
        CheckConstraint("mapping_version > 0", name="ck_revision_mapping_version"),
        CheckConstraint("char_length(mapping_digest) = 64 AND char_length(operation_hash) = 64", name="ck_revision_mapping_hashes"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RevisionTimelineMappingHead(Base):
    __tablename__ = "revision_timeline_mapping_heads"
    __table_args__ = (
        ForeignKeyConstraint(["document_id", "novel_id"], ["documents.id", "documents.novel_id"], name="fk_revision_mapping_head_document_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["revision_id", "document_id", "source_content_hash"], ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"], name="fk_revision_mapping_head_source_guard", ondelete="CASCADE"),
        ForeignKeyConstraint(["current_mapping_revision_id", "revision_id", "document_id", "novel_id"], ["revision_timeline_mappings.id", "revision_timeline_mappings.revision_id", "revision_timeline_mappings.document_id", "revision_timeline_mappings.novel_id"], name="fk_revision_mapping_head_current_scope", deferrable=True, initially="DEFERRED"),
        CheckConstraint("version > 0", name="ck_revision_mapping_head_version"),
    )

    revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_mapping_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RevisionTimelineMappingSegment(Base):
    __tablename__ = "revision_timeline_mapping_segments"
    __table_args__ = (
        ForeignKeyConstraint(["mapping_revision_id", "novel_id"], ["revision_timeline_mappings.id", "revision_timeline_mappings.novel_id"], name="fk_revision_mapping_segment_revision_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_revision_mapping_segment_timeline_scope", ondelete="RESTRICT"),
        UniqueConstraint("mapping_revision_id", "ordinal", name="uq_revision_mapping_segment_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_revision_mapping_segment_ordinal"),
        CheckConstraint("source_start >= 0 AND source_end > source_start", name="ck_revision_mapping_segment_offsets"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    mapping_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    timeline_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)
    story_sequence: Mapped[int | None] = mapped_column(BigInteger)
    story_time_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class StoryEventLink(Base):
    __tablename__ = "story_event_links"
    __table_args__ = (
        ForeignKeyConstraint(["source_fact_id", "novel_id"], ["story_facts.id", "story_facts.novel_id"], name="fk_story_event_link_source_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["target_fact_id", "novel_id"], ["story_facts.id", "story_facts.novel_id"], name="fk_story_event_link_target_scope", ondelete="CASCADE"),
        UniqueConstraint("source_fact_id", "target_fact_id", "link_type", name="uq_story_event_link_semantics"),
        CheckConstraint("source_fact_id <> target_fact_id", name="ck_story_event_link_distinct"),
        CheckConstraint("link_type IN ('causes','reveals','contradicts','supersedes','enables')", name="ck_story_event_link_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    source_fact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    target_fact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    link_type: Mapped[str] = mapped_column(String(24), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PrivateAssetVersion(Base):
    __tablename__ = "private_asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_number", name="uq_private_asset_version_number"),
        UniqueConstraint("asset_id", "operation_key", name="uq_private_asset_version_operation"),
        UniqueConstraint("id", "asset_id", name="uq_private_asset_version_scope"),
        CheckConstraint("version_number > 0", name="ck_private_asset_version_number"),
        CheckConstraint("char_length(content_hash) = 64 AND char_length(operation_hash) = 64", name="ck_private_asset_version_hashes"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("private_assets.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rights_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NovelAssetBinding(Base):
    __tablename__ = "novel_asset_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["asset_version_id", "asset_id"], ["private_asset_versions.id", "private_asset_versions.asset_id"], name="fk_novel_asset_binding_version_scope", ondelete="RESTRICT"),
        Index("uq_novel_asset_binding_active_asset", "novel_id", "asset_id", unique=True, postgresql_where=text("lifecycle_state='active'")),
        Index("uq_novel_asset_binding_active_position", "novel_id", "position", unique=True, postgresql_where=text("lifecycle_state='active'")),
        CheckConstraint("usage_policy IN ('required','preferred','context_only','prohibited')", name="ck_novel_asset_binding_policy"),
        CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_novel_asset_binding_lifecycle"),
        CheckConstraint("position >= 0 AND version > 0", name="ck_novel_asset_binding_versions"),
        CheckConstraint("char_length(operation_hash) = 64", name="ck_novel_asset_binding_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("private_assets.id", ondelete="RESTRICT"), nullable=False)
    asset_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    usage_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmbeddingConfiguration(Base):
    __tablename__ = "embedding_configurations"
    __table_args__ = (
        UniqueConstraint("owner_id", "workspace_id", name="uq_embedding_configuration_scope"),
        CheckConstraint("version > 0", name="ck_embedding_configuration_version"),
        CheckConstraint("api_key_last4 IS NULL OR char_length(api_key_last4) = 4", name="ck_embedding_configuration_key_last4"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(240))
    api_key_last4: Mapped[str | None] = mapped_column(String(4))
    api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_generation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    candidate_generation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    previous_generation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    connection_state: Mapped[str] = mapped_column(String(30), nullable=False, default="unconfigured")
    connection_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"
    __table_args__ = (
        UniqueConstraint("owner_id", "workspace_id", "index_fingerprint", name="uq_embedding_profile_fingerprint"),
        UniqueConstraint("id", "owner_id", "workspace_id", name="uq_embedding_profile_scope"),
        CheckConstraint("dimension > 0", name="ck_embedding_profile_dimension"),
        CheckConstraint("char_length(index_fingerprint) = 64", name="ck_embedding_profile_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    protocol: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actual_model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    actual_revision: Mapped[str | None] = mapped_column(String(160))
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    output_type: Mapped[str] = mapped_column(String(30), nullable=False)
    document_text_type: Mapped[str] = mapped_column(String(30), nullable=False)
    query_text_type: Mapped[str] = mapped_column(String(30), nullable=False)
    distance_metric: Mapped[str] = mapped_column(String(30), nullable=False)
    index_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_state: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmbeddingGeneration(Base):
    __tablename__ = "embedding_generations"
    __table_args__ = (
        ForeignKeyConstraint(["profile_id", "owner_id", "workspace_id"], ["embedding_profiles.id", "embedding_profiles.owner_id", "embedding_profiles.workspace_id"], name="fk_embedding_generation_profile_scope", ondelete="RESTRICT"),
        UniqueConstraint("id", "owner_id", "workspace_id", name="uq_embedding_generation_scope"),
        UniqueConstraint("owner_id", "workspace_id", "generation_number", name="uq_embedding_generation_number"),
        Index("uq_embedding_generation_active", "owner_id", "workspace_id", unique=True, postgresql_where=text("state='active'")),
        CheckConstraint("generation_number > 0", name="ck_embedding_generation_number"),
        CheckConstraint("state IN ('draft','building','ready','active','failed','cancelled','stale','retired')", name="ck_embedding_generation_state"),
        CheckConstraint("evaluation_state IN ('not_run','pending','passed','failed')", name="ck_embedding_generation_evaluation_state"),
        CheckConstraint("char_length(index_fingerprint) = 64 AND char_length(consent_cohort_hash) = 64", name="ck_embedding_generation_hashes"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    generation_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    renderer_bundle_version: Mapped[str] = mapped_column(String(120), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(120), nullable=False)
    query_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    index_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_cohort_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    evaluation_state: Mapped[str] = mapped_column(String(20), nullable=False, default="not_run")
    evaluation_summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


for pointer_name in ("active_generation_id", "candidate_generation_id", "previous_generation_id"):
    EmbeddingConfiguration.__table__.append_constraint(
        ForeignKeyConstraint(
            [EmbeddingConfiguration.__table__.c[pointer_name], EmbeddingConfiguration.__table__.c.owner_id, EmbeddingConfiguration.__table__.c.workspace_id],
            [EmbeddingGeneration.__table__.c.id, EmbeddingGeneration.__table__.c.owner_id, EmbeddingGeneration.__table__.c.workspace_id],
            name=f"fk_embedding_configuration_{pointer_name.removesuffix('_id')}_scope",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        )
    )


class NovelEmbeddingConsent(Base):
    __tablename__ = "novel_embedding_consents"
    __table_args__ = (
        UniqueConstraint("id", "novel_id", name="uq_novel_embedding_consent_scope"),
        UniqueConstraint("novel_id", "idempotency_key", name="uq_novel_embedding_consent_idempotency"),
        Index("uq_novel_embedding_consent_active", "novel_id", unique=True, postgresql_where=text("revoked_at IS NULL")),
        CheckConstraint("char_length(operation_hash) = 64", name="ck_novel_embedding_consent_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    data_scope_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    notice_version: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_actor: Mapped[str] = mapped_column(String(120), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_actor: Mapped[str | None] = mapped_column(String(120))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(240))


class EmbeddingGenerationNovel(Base):
    __tablename__ = "embedding_generation_novels"
    __table_args__ = (
        ForeignKeyConstraint(["generation_id", "owner_id", "workspace_id"], ["embedding_generations.id", "embedding_generations.owner_id", "embedding_generations.workspace_id"], name="fk_embedding_generation_novel_generation_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], name="fk_embedding_generation_novel_novel_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["consent_id", "novel_id"], ["novel_embedding_consents.id", "novel_embedding_consents.novel_id"], name="fk_embedding_generation_novel_consent_scope", ondelete="RESTRICT"),
        UniqueConstraint("generation_id", "novel_id", name="uq_embedding_generation_novel"),
        CheckConstraint("state IN ('pending','building','ready','failed','cancelled','stale')", name="ck_embedding_generation_novel_state"),
        CheckConstraint("source_count >= 0 AND chunk_count >= 0 AND embedded_count >= 0 AND failure_count >= 0", name="ck_embedding_generation_novel_counts"),
        CheckConstraint("char_length(input_digest) = 64", name="ck_embedding_generation_novel_digest"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    consent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    target_corpora_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SemanticSource(Base):
    __tablename__ = "semantic_sources"
    __table_args__ = (
        ForeignKeyConstraint(["generation_id", "novel_id"], ["embedding_generation_novels.generation_id", "embedding_generation_novels.novel_id"], name="fk_semantic_source_generation_novel", ondelete="CASCADE"),
        ForeignKeyConstraint(["timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_semantic_source_timeline_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["character_instance_id", "novel_id"], ["character_instances.id", "character_instances.novel_id"], name="fk_semantic_source_character_instance_scope", ondelete="RESTRICT"),
        UniqueConstraint("generation_id", "novel_id", "source_fingerprint", name="uq_semantic_source_fingerprint"),
        UniqueConstraint("id", "generation_id", name="uq_semantic_source_generation_scope"),
        CheckConstraint("corpus IN ('manuscript','planning','private_asset','character','relationship','story_event','storyline','foreshadow','timeline')", name="ck_semantic_source_corpus"),
        CheckConstraint("status IN ('current','invalid','retired')", name="ck_semantic_source_status"),
        CheckConstraint("char_length(content_hash) = 64 AND char_length(source_fingerprint) = 64", name="ck_semantic_source_hashes"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    corpus: Mapped[str] = mapped_column(String(30), nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_revision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_locator_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(120), nullable=False)
    timeline_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    character_instance_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    narrative_start: Mapped[int | None] = mapped_column(BigInteger)
    narrative_end: Mapped[int | None] = mapped_column(BigInteger)
    visibility_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SemanticChunk(Base):
    __tablename__ = "semantic_chunks"
    __table_args__ = (
        ForeignKeyConstraint(["source_id", "generation_id"], ["semantic_sources.id", "semantic_sources.generation_id"], name="fk_semantic_chunk_source_generation", ondelete="CASCADE"),
        UniqueConstraint("source_id", "chunk_index", name="uq_semantic_chunk_index"),
        UniqueConstraint("id", "generation_id", name="uq_semantic_chunk_generation_scope"),
        CheckConstraint("chunk_index >= 0 AND source_start >= 0 AND source_end > source_start AND token_count >= 0", name="ck_semantic_chunk_bounds"),
        CheckConstraint("char_length(content_hash) = 64", name="ck_semantic_chunk_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmbeddingIndexBatch(Base):
    __tablename__ = "embedding_index_batches"
    __table_args__ = (
        ForeignKeyConstraint(["generation_id", "novel_id"], ["embedding_generation_novels.generation_id", "embedding_generation_novels.novel_id"], name="fk_embedding_batch_generation_novel", ondelete="CASCADE"),
        UniqueConstraint("generation_id", "novel_id", "batch_number", name="uq_embedding_batch_number"),
        UniqueConstraint("background_job_id", name="uq_embedding_batch_job"),
        UniqueConstraint("id", "generation_id", name="uq_embedding_batch_generation_scope"),
        CheckConstraint("batch_number >= 0 AND item_count BETWEEN 1 AND 10", name="ck_embedding_batch_size"),
        CheckConstraint("state IN ('pending','queued','running','ready','failed','cancelled')", name="ck_embedding_batch_state"),
        CheckConstraint("char_length(input_hash) = 64", name="ck_embedding_batch_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    novel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    background_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="RESTRICT"))
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmbeddingIndexBatchItem(Base):
    __tablename__ = "embedding_index_batch_items"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id", "generation_id"], ["embedding_index_batches.id", "embedding_index_batches.generation_id"], name="fk_embedding_batch_item_batch_generation", ondelete="CASCADE"),
        ForeignKeyConstraint(["chunk_id", "generation_id"], ["semantic_chunks.id", "semantic_chunks.generation_id"], name="fk_embedding_batch_item_chunk_generation", ondelete="RESTRICT"),
        UniqueConstraint("batch_id", "ordinal", name="uq_embedding_batch_item_ordinal"),
        UniqueConstraint("batch_id", "chunk_id", name="uq_embedding_batch_item_chunk"),
        CheckConstraint("ordinal BETWEEN 0 AND 9", name="ck_embedding_batch_item_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    generation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class SemanticEmbedding(Base):
    __tablename__ = "semantic_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(["chunk_id", "generation_id"], ["semantic_chunks.id", "semantic_chunks.generation_id"], name="fk_semantic_embedding_chunk_generation", ondelete="CASCADE"),
        ForeignKeyConstraint(["batch_id", "generation_id"], ["embedding_index_batches.id", "embedding_index_batches.generation_id"], name="fk_semantic_embedding_batch_generation", ondelete="RESTRICT"),
        UniqueConstraint("generation_id", "chunk_id", name="uq_semantic_embedding_chunk"),
        CheckConstraint("dimension > 0 AND vector_dims(embedding) = dimension", name="ck_semantic_embedding_dimension"),
        CheckConstraint("char_length(embedding_hash) = 64", name="ck_semantic_embedding_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    batch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
    embedding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("model_run_records.id", ondelete="RESTRICT"), nullable=False)
    response_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# Additive scope guards for legacy roots.  They live here because the target
# timeline/version tables are declared in this module.
Base.metadata.tables["private_assets"].append_constraint(
    ForeignKeyConstraint(
        [Base.metadata.tables["private_assets"].c.current_version_id, Base.metadata.tables["private_assets"].c.id],
        [PrivateAssetVersion.__table__.c.id, PrivateAssetVersion.__table__.c.asset_id],
        name="fk_private_asset_current_version_scope",
        deferrable=True,
        initially="DEFERRED",
        use_alter=True,
    )
)
Base.metadata.tables["asset_preset_items"].append_constraint(
    ForeignKeyConstraint(
        [Base.metadata.tables["asset_preset_items"].c.asset_version_id, Base.metadata.tables["asset_preset_items"].c.asset_id],
        [PrivateAssetVersion.__table__.c.id, PrivateAssetVersion.__table__.c.asset_id],
        name="fk_asset_preset_item_version_scope",
        ondelete="RESTRICT",
    )
)
Base.metadata.tables["asset_preset_items"].append_constraint(
    CheckConstraint(
        "usage_policy IN ('required','preferred','context_only','prohibited')",
        name="ck_asset_preset_item_usage_policy",
    )
)

_story_facts = Base.metadata.tables["story_facts"]
for local, remote, name in (
    (("timeline_id", "novel_id"), ("id", "novel_id"), "fk_story_fact_timeline_scope"),
    (("character_id", "novel_id"), ("id", "novel_id"), "fk_story_fact_character_scope"),
    (("character_instance_id", "novel_id"), ("id", "novel_id"), "fk_story_fact_character_instance_scope"),
    (("relationship_id", "novel_id"), ("id", "novel_id"), "fk_story_fact_relationship_scope"),
    (("storyline_id", "novel_id"), ("id", "novel_id"), "fk_story_fact_storyline_scope"),
    (("foreshadow_id", "novel_id"), ("id", "novel_id"), "fk_story_fact_foreshadow_scope"),
):
    target_table = {
        "timeline_id": StoryTimeline.__table__,
        "character_id": Base.metadata.tables["novel_characters"],
        "character_instance_id": CharacterInstance.__table__,
        "relationship_id": Base.metadata.tables["character_relationships"],
        "storyline_id": Base.metadata.tables["storylines"],
        "foreshadow_id": Base.metadata.tables["foreshadows"],
    }[local[0]]
    _story_facts.append_constraint(
        ForeignKeyConstraint(
            [_story_facts.c[column] for column in local],
            [target_table.c[column] for column in remote],
            name=name,
            ondelete="RESTRICT",
        )
    )
_story_facts.append_constraint(
    ForeignKeyConstraint(
        [_story_facts.c.source_revision_id, _story_facts.c.source_document_id],
        [Base.metadata.tables["document_revisions"].c.id, Base.metadata.tables["document_revisions"].c.document_id],
        name="fk_story_fact_source_guard",
        ondelete="RESTRICT",
    )
)

_relationships = Base.metadata.tables["character_relationships"]
for local_column, target, name in (
    ("timeline_id", StoryTimeline.__table__, "fk_relationship_timeline_scope"),
    ("source_character_instance_id", CharacterInstance.__table__, "fk_relationship_source_instance_scope"),
    ("target_character_instance_id", CharacterInstance.__table__, "fk_relationship_target_instance_scope"),
):
    _relationships.append_constraint(
        ForeignKeyConstraint(
            [_relationships.c[local_column], _relationships.c.novel_id],
            [target.c.id, target.c.novel_id],
            name=name,
            ondelete="RESTRICT",
        )
    )

_aliases = Base.metadata.tables["character_aliases"]
_aliases.append_constraint(ForeignKeyConstraint([_aliases.c.character_instance_id, _aliases.c.novel_id], [CharacterInstance.__table__.c.id, CharacterInstance.__table__.c.novel_id], name="fk_character_alias_instance_scope", ondelete="RESTRICT"))
_aliases.append_constraint(ForeignKeyConstraint([_aliases.c.timeline_id, _aliases.c.novel_id], [StoryTimeline.__table__.c.id, StoryTimeline.__table__.c.novel_id], name="fk_character_alias_timeline_scope", ondelete="RESTRICT"))
_aliases.append_constraint(ForeignKeyConstraint([_aliases.c.source_revision_id], [Base.metadata.tables["document_revisions"].c.id], name="fk_character_alias_source_revision", ondelete="RESTRICT"))
_aliases.append_constraint(CheckConstraint("valid_from_sequence IS NULL OR valid_to_sequence IS NULL OR valid_to_sequence >= valid_from_sequence", name="ck_character_alias_valid_range"))
