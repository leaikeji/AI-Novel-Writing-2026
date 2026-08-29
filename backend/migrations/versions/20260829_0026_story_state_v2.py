"""Add multi-timeline story state and StoryFact v2.

Revision ID: 20260829_0026
Revises: 20260829_0025
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260829_0026"
down_revision = "20260829_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "intelligence_proposals",
        sa.Column(
            "extraction_context_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    for table, name in (
        ("character_relationships", "uq_character_relationship_novel_scope"),
        ("storylines", "uq_storyline_novel_scope"),
        ("foreshadows", "uq_foreshadow_novel_scope"),
        ("story_facts", "uq_story_fact_novel_scope"),
    ):
        op.create_unique_constraint(name, table, ["id", "novel_id"])

    op.create_table(
        "story_timelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timeline_key", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("normalized_name", sa.String(240), nullable=False),
        sa.Column("timeline_kind", sa.String(20), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parent_timeline_id", postgresql.UUID(as_uuid=True)),
        sa.Column("fork_story_sequence", sa.BigInteger()),
        sa.Column("fork_anchor_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("lifecycle_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "novel_id", name="uq_story_timeline_novel_scope"),
        sa.UniqueConstraint("novel_id", "timeline_key", name="uq_story_timeline_key"),
        sa.CheckConstraint("timeline_kind IN ('main','branch','merge')", name="ck_story_timeline_kind"),
        sa.CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_story_timeline_lifecycle"),
        sa.CheckConstraint("version > 0", name="ck_story_timeline_version"),
        sa.CheckConstraint("parent_timeline_id IS NULL OR parent_timeline_id <> id", name="ck_story_timeline_not_self_parent"),
        sa.CheckConstraint("NOT is_primary OR parent_timeline_id IS NULL", name="ck_story_timeline_primary_parent"),
    )
    op.create_foreign_key(
        "fk_story_timeline_parent_scope", "story_timelines", "story_timelines",
        ["parent_timeline_id", "novel_id"], ["id", "novel_id"], deferrable=True, initially="DEFERRED"
    )
    op.create_index("uq_story_timeline_primary", "story_timelines", ["novel_id"], unique=True, postgresql_where=sa.text("is_primary IS TRUE"))
    op.create_index("uq_story_timeline_active_name", "story_timelines", ["novel_id", "normalized_name"], unique=True, postgresql_where=sa.text("lifecycle_state='active'"))

    op.create_table(
        "story_timeline_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_timeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_timeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_type", sa.String(30), nullable=False),
        sa.Column("source_story_sequence", sa.BigInteger()),
        sa.Column("target_story_sequence", sa.BigInteger()),
        sa.Column("details_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("link_fingerprint", sa.String(64), nullable=False),
        sa.Column("lifecycle_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_timeline_link_source_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_timeline_link_target_scope", ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", "link_fingerprint", name="uq_timeline_link_fingerprint"),
        sa.CheckConstraint("source_timeline_id <> target_timeline_id", name="ck_timeline_link_distinct"),
        sa.CheckConstraint("link_type IN ('travel','memory_transfer','causal','loop_return','merge_reference')", name="ck_timeline_link_type"),
        sa.CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_timeline_link_lifecycle"),
        sa.CheckConstraint("char_length(link_fingerprint) = 64", name="ck_timeline_link_fingerprint"),
    )

    op.create_table(
        "character_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin_timeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("derived_from_instance_id", postgresql.UUID(as_uuid=True)),
        sa.Column("continuity_kind", sa.String(20), nullable=False),
        sa.Column("display_label", sa.String(240), nullable=False, server_default=""),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("lifecycle_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id", "novel_id"], ["novel_characters.id", "novel_characters.novel_id"], name="fk_character_instance_root_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["origin_timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_character_instance_timeline_scope", ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "novel_id", name="uq_character_instance_novel_scope"),
        sa.CheckConstraint("derived_from_instance_id IS NULL OR derived_from_instance_id <> id", name="ck_character_instance_not_self"),
        sa.CheckConstraint("continuity_kind IN ('native','derived','traveler')", name="ck_character_instance_continuity"),
        sa.CheckConstraint("lifecycle_state IN ('active','archived')", name="ck_character_instance_lifecycle"),
        sa.CheckConstraint("version > 0", name="ck_character_instance_version"),
    )
    op.create_foreign_key(
        "fk_character_instance_source_scope", "character_instances", "character_instances",
        ["derived_from_instance_id", "novel_id"], ["id", "novel_id"], deferrable=True, initially="DEFERRED"
    )
    op.create_index("uq_character_instance_active_origin", "character_instances", ["novel_id", "origin_timeline_id", "character_id"], unique=True, postgresql_where=sa.text("lifecycle_state='active'"))

    op.create_table(
        "character_instance_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("restored_from_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("operation_key", sa.String(160), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("profile_schema_version", sa.Integer(), nullable=False),
        sa.Column("profile_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("change_set_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["character_instance_id", "novel_id"], ["character_instances.id", "character_instances.novel_id"], name="fk_character_instance_revision_root_scope", ondelete="CASCADE"),
        sa.UniqueConstraint("character_instance_id", "revision_number", name="uq_character_instance_revision_number"),
        sa.UniqueConstraint("novel_id", "operation_key", "character_instance_id", name="uq_character_instance_revision_operation"),
        sa.UniqueConstraint("id", "character_instance_id", "novel_id", name="uq_character_instance_revision_scope"),
        sa.CheckConstraint("revision_number > 0 AND profile_schema_version > 0", name="ck_character_instance_revision_versions"),
        sa.CheckConstraint("char_length(operation_hash) = 64 AND char_length(content_hash) = 64", name="ck_character_instance_revision_hashes"),
    )
    op.create_foreign_key("fk_character_instance_revision_parent_scope", "character_instance_revisions", "character_instance_revisions", ["parent_revision_id", "character_instance_id", "novel_id"], ["id", "character_instance_id", "novel_id"], deferrable=True, initially="DEFERRED")
    op.create_foreign_key("fk_character_instance_revision_restore_scope", "character_instance_revisions", "character_instance_revisions", ["restored_from_revision_id", "character_instance_id", "novel_id"], ["id", "character_instance_id", "novel_id"], deferrable=True, initially="DEFERRED")
    op.create_foreign_key("fk_character_instance_current_revision_scope", "character_instances", "character_instance_revisions", ["current_revision_id", "id", "novel_id"], ["id", "character_instance_id", "novel_id"], deferrable=True, initially="DEFERRED")

    op.create_table(
        "revision_timeline_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("mapping_version", sa.BigInteger(), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("operation_key", sa.String(160), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("mapping_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id", "novel_id"], ["documents.id", "documents.novel_id"], name="fk_revision_mapping_document_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id", "document_id", "source_content_hash"], ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"], name="fk_revision_mapping_source_guard", ondelete="CASCADE"),
        sa.UniqueConstraint("revision_id", "mapping_version", name="uq_revision_timeline_mapping_version"),
        sa.UniqueConstraint("revision_id", "operation_key", name="uq_revision_timeline_mapping_operation"),
        sa.UniqueConstraint("id", "revision_id", "document_id", "novel_id", name="uq_revision_timeline_mapping_scope"),
        sa.UniqueConstraint("id", "novel_id", name="uq_revision_timeline_mapping_novel_scope"),
        sa.CheckConstraint("mapping_version > 0", name="ck_revision_mapping_version"),
        sa.CheckConstraint("char_length(mapping_digest) = 64 AND char_length(operation_hash) = 64", name="ck_revision_mapping_hashes"),
    )
    op.create_table(
        "revision_timeline_mapping_heads",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("current_mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id", "novel_id"], ["documents.id", "documents.novel_id"], name="fk_revision_mapping_head_document_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id", "document_id", "source_content_hash"], ["document_revisions.id", "document_revisions.document_id", "document_revisions.content_hash"], name="fk_revision_mapping_head_source_guard", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_mapping_revision_id", "revision_id", "document_id", "novel_id"], ["revision_timeline_mappings.id", "revision_timeline_mappings.revision_id", "revision_timeline_mappings.document_id", "revision_timeline_mappings.novel_id"], name="fk_revision_mapping_head_current_scope", deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint("version > 0", name="ck_revision_mapping_head_version"),
    )
    op.create_table(
        "revision_timeline_mapping_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("story_sequence", sa.BigInteger()),
        sa.Column("story_time_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["mapping_revision_id", "novel_id"], ["revision_timeline_mappings.id", "revision_timeline_mappings.novel_id"], name="fk_revision_mapping_segment_revision_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timeline_id", "novel_id"], ["story_timelines.id", "story_timelines.novel_id"], name="fk_revision_mapping_segment_timeline_scope", ondelete="RESTRICT"),
        sa.UniqueConstraint("mapping_revision_id", "ordinal", name="uq_revision_mapping_segment_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_revision_mapping_segment_ordinal"),
        sa.CheckConstraint("source_start >= 0 AND source_end > source_start", name="ck_revision_mapping_segment_offsets"),
    )

    additions = (
        ("source_document_id", postgresql.UUID(as_uuid=True)),
        ("schema_version", sa.String(64)),
        ("timeline_id", postgresql.UUID(as_uuid=True)),
        ("character_id", postgresql.UUID(as_uuid=True)),
        ("character_instance_id", postgresql.UUID(as_uuid=True)),
        ("relationship_id", postgresql.UUID(as_uuid=True)),
        ("storyline_id", postgresql.UUID(as_uuid=True)),
        ("foreshadow_id", postgresql.UUID(as_uuid=True)),
        ("dimension", sa.String(80)),
        ("event_kind", sa.String(80)),
        ("story_sequence", sa.BigInteger()),
        ("story_time_json", postgresql.JSONB()),
        ("visibility_json", postgresql.JSONB()),
        ("source_start", sa.Integer()),
        ("source_end", sa.Integer()),
        ("event_fingerprint", sa.String(64)),
    )
    for name, column_type in additions:
        op.add_column("story_facts", sa.Column(name, column_type))
    op.create_foreign_key("fk_story_fact_timeline_scope", "story_facts", "story_timelines", ["timeline_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_story_fact_character_scope", "story_facts", "novel_characters", ["character_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_story_fact_character_instance_scope", "story_facts", "character_instances", ["character_instance_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_story_fact_relationship_scope", "story_facts", "character_relationships", ["relationship_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_story_fact_storyline_scope", "story_facts", "storylines", ["storyline_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_story_fact_foreshadow_scope", "story_facts", "foreshadows", ["foreshadow_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_story_fact_source_guard", "story_facts", "document_revisions", ["source_revision_id", "source_document_id"], ["id", "document_id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_story_fact_source_offsets", "story_facts", "(source_start IS NULL AND source_end IS NULL) OR (source_start >= 0 AND source_end > source_start)")
    op.create_index("uq_story_fact_event_fingerprint", "story_facts", ["novel_id", "event_fingerprint"], unique=True, postgresql_where=sa.text("event_fingerprint IS NOT NULL"))
    op.create_index("ix_story_facts_timeline_state", "story_facts", ["novel_id", "timeline_id", "fact_type", "status", "story_sequence", "created_at"])
    op.create_index("ix_story_facts_character_instance", "story_facts", ["novel_id", "character_instance_id", "fact_type", "status", "created_at"])

    op.create_table(
        "story_event_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_fact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_type", sa.String(24), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_fact_id", "novel_id"], ["story_facts.id", "story_facts.novel_id"], name="fk_story_event_link_source_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_fact_id", "novel_id"], ["story_facts.id", "story_facts.novel_id"], name="fk_story_event_link_target_scope", ondelete="CASCADE"),
        sa.UniqueConstraint("source_fact_id", "target_fact_id", "link_type", name="uq_story_event_link_semantics"),
        sa.CheckConstraint("source_fact_id <> target_fact_id", name="ck_story_event_link_distinct"),
        sa.CheckConstraint("link_type IN ('causes','reveals','contradicts','supersedes','enables')", name="ck_story_event_link_type"),
    )

    op.drop_index(
        "uq_character_relationship_active_semantics",
        table_name="character_relationships",
    )
    for name in ("timeline_id", "source_character_instance_id", "target_character_instance_id"):
        op.add_column("character_relationships", sa.Column(name, postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_relationship_timeline_scope", "character_relationships", "story_timelines", ["timeline_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_relationship_source_instance_scope", "character_relationships", "character_instances", ["source_character_instance_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_relationship_target_instance_scope", "character_relationships", "character_instances", ["target_character_instance_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_index(
        "uq_character_relationship_active_semantics",
        "character_relationships",
        [
            "novel_id", "timeline_id", "source_character_instance_id",
            "target_character_instance_id", "directionality", "relation_kind",
            "normalized_label",
        ],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    for name in ("timeline_id", "source_character_instance_id", "target_character_instance_id"):
        op.add_column(
            "character_relationship_revisions",
            sa.Column(name, postgresql.UUID(as_uuid=True)),
        )

    alias_additions = (
        ("character_instance_id", postgresql.UUID(as_uuid=True)),
        ("timeline_id", postgresql.UUID(as_uuid=True)),
        ("alias_kind", sa.String(30)),
        ("valid_from_sequence", sa.BigInteger()),
        ("valid_to_sequence", sa.BigInteger()),
        ("identity_layer", sa.String(30)),
        ("knowledge_scope_json", postgresql.JSONB()),
        ("source_revision_id", postgresql.UUID(as_uuid=True)),
    )
    for name, column_type in alias_additions:
        op.add_column("character_aliases", sa.Column(name, column_type))
    op.create_foreign_key("fk_character_alias_instance_scope", "character_aliases", "character_instances", ["character_instance_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_character_alias_timeline_scope", "character_aliases", "story_timelines", ["timeline_id", "novel_id"], ["id", "novel_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_character_alias_source_revision", "character_aliases", "document_revisions", ["source_revision_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_character_alias_valid_range", "character_aliases", "valid_from_sequence IS NULL OR valid_to_sequence IS NULL OR valid_to_sequence >= valid_from_sequence")


def downgrade() -> None:
    op.drop_constraint("ck_character_alias_valid_range", "character_aliases", type_="check")
    for name in ("fk_character_alias_source_revision", "fk_character_alias_timeline_scope", "fk_character_alias_instance_scope"):
        op.drop_constraint(name, "character_aliases", type_="foreignkey")
    for name in ("source_revision_id", "knowledge_scope_json", "identity_layer", "valid_to_sequence", "valid_from_sequence", "alias_kind", "timeline_id", "character_instance_id"):
        op.drop_column("character_aliases", name)
    for name in ("timeline_id", "source_character_instance_id", "target_character_instance_id"):
        op.drop_column("character_relationship_revisions", name)
    op.drop_index(
        "uq_character_relationship_active_semantics",
        table_name="character_relationships",
    )
    for name in ("fk_relationship_target_instance_scope", "fk_relationship_source_instance_scope", "fk_relationship_timeline_scope"):
        op.drop_constraint(name, "character_relationships", type_="foreignkey")
    for name in ("target_character_instance_id", "source_character_instance_id", "timeline_id"):
        op.drop_column("character_relationships", name)
    op.create_index(
        "uq_character_relationship_active_semantics",
        "character_relationships",
        [
            "novel_id", "source_character_id", "target_character_id",
            "directionality", "relation_kind", "normalized_label",
        ],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_table("story_event_links")
    op.drop_index("ix_story_facts_character_instance", table_name="story_facts")
    op.drop_index("ix_story_facts_timeline_state", table_name="story_facts")
    op.drop_index("uq_story_fact_event_fingerprint", table_name="story_facts")
    op.drop_constraint("ck_story_fact_source_offsets", "story_facts", type_="check")
    for name in ("fk_story_fact_source_guard", "fk_story_fact_foreshadow_scope", "fk_story_fact_storyline_scope", "fk_story_fact_relationship_scope", "fk_story_fact_character_instance_scope", "fk_story_fact_character_scope", "fk_story_fact_timeline_scope"):
        op.drop_constraint(name, "story_facts", type_="foreignkey")
    for name in ("event_fingerprint", "source_end", "source_start", "visibility_json", "story_time_json", "story_sequence", "event_kind", "dimension", "foreshadow_id", "storyline_id", "relationship_id", "character_instance_id", "character_id", "timeline_id", "schema_version", "source_document_id"):
        op.drop_column("story_facts", name)
    op.drop_table("revision_timeline_mapping_segments")
    op.drop_table("revision_timeline_mapping_heads")
    op.drop_table("revision_timeline_mappings")
    op.drop_constraint("fk_character_instance_current_revision_scope", "character_instances", type_="foreignkey")
    op.drop_table("character_instance_revisions")
    op.drop_table("character_instances")
    op.drop_table("story_timeline_links")
    op.drop_table("story_timelines")
    for table, name in (
        ("story_facts", "uq_story_fact_novel_scope"),
        ("foreshadows", "uq_foreshadow_novel_scope"),
        ("storylines", "uq_storyline_novel_scope"),
        ("character_relationships", "uq_character_relationship_novel_scope"),
    ):
        op.drop_constraint(name, table, type_="unique")
    op.drop_column("intelligence_proposals", "extraction_context_json")
