"""Static contracts for timelines, character instances and StoryFact v2.

The module deliberately inspects metadata and migration text without opening a
database connection or executing Alembic.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

import backend.creative_data_models  # noqa: F401  # registers additive tables
from backend.models import Base


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "backend/migrations/versions/20260829_0026_story_state_v2.py"


def _table(name: str):
    return Base.metadata.tables[name]


def _constraint(table_name: str, constraint_name: str, kind: type):
    matches = [
        constraint
        for constraint in _table(table_name).constraints
        if isinstance(constraint, kind) and constraint.name == constraint_name
    ]
    assert len(matches) == 1, (
        f"{table_name} must define exactly one {kind.__name__} "
        f"named {constraint_name}"
    )
    return matches[0]


def _column_names(constraint) -> tuple[str, ...]:
    return tuple(column.name for column in constraint.columns)


def _remote_names(constraint: ForeignKeyConstraint) -> tuple[str, ...]:
    return tuple(element.target_fullname for element in constraint.elements)


def test_story_state_tables_and_story_fact_v2_columns_are_registered() -> None:
    assert {
        "story_timelines",
        "story_timeline_links",
        "character_instances",
        "character_instance_revisions",
        "revision_timeline_mapping_heads",
        "revision_timeline_mappings",
        "revision_timeline_mapping_segments",
        "story_event_links",
    } <= set(Base.metadata.tables)

    assert {
        "source_document_id",
        "schema_version",
        "timeline_id",
        "character_id",
        "character_instance_id",
        "relationship_id",
        "storyline_id",
        "foreshadow_id",
        "dimension",
        "event_kind",
        "story_sequence",
        "story_time_json",
        "visibility_json",
        "source_start",
        "source_end",
        "event_fingerprint",
    } <= set(_table("story_facts").c.keys())


def test_timelines_and_links_cannot_cross_novel_scope() -> None:
    parent = _constraint(
        "story_timelines",
        "fk_story_timeline_parent_scope",
        ForeignKeyConstraint,
    )
    assert _column_names(parent) == ("parent_timeline_id", "novel_id")
    assert _remote_names(parent) == (
        "story_timelines.id",
        "story_timelines.novel_id",
    )
    assert parent.deferrable is True
    assert parent.initially == "DEFERRED"

    for endpoint in ("source", "target"):
        constraint = _constraint(
            "story_timeline_links",
            f"fk_timeline_link_{endpoint}_scope",
            ForeignKeyConstraint,
        )
        assert _column_names(constraint) == (f"{endpoint}_timeline_id", "novel_id")
        assert _remote_names(constraint) == (
            "story_timelines.id",
            "story_timelines.novel_id",
        )

    primary = next(
        index for index in _table("story_timelines").indexes
        if index.name == "uq_story_timeline_primary"
    )
    assert primary.unique is True
    assert tuple(column.name for column in primary.columns) == ("novel_id",)
    assert "is_primary IS TRUE" in str(primary.dialect_options["postgresql"]["where"])


def test_character_instance_identity_and_revision_chain_are_scoped() -> None:
    expected = {
        "fk_character_instance_root_scope": (
            ("character_id", "novel_id"),
            ("novel_characters.id", "novel_characters.novel_id"),
        ),
        "fk_character_instance_timeline_scope": (
            ("origin_timeline_id", "novel_id"),
            ("story_timelines.id", "story_timelines.novel_id"),
        ),
        "fk_character_instance_source_scope": (
            ("derived_from_instance_id", "novel_id"),
            ("character_instances.id", "character_instances.novel_id"),
        ),
        "fk_character_instance_current_revision_scope": (
            ("current_revision_id", "id", "novel_id"),
            (
                "character_instance_revisions.id",
                "character_instance_revisions.character_instance_id",
                "character_instance_revisions.novel_id",
            ),
        ),
    }
    for name, (local, remote) in expected.items():
        constraint = _constraint("character_instances", name, ForeignKeyConstraint)
        assert _column_names(constraint) == local
        assert _remote_names(constraint) == remote

    for relation, local in (
        ("root", ("character_instance_id", "novel_id")),
        ("parent", ("parent_revision_id", "character_instance_id", "novel_id")),
        ("restore", ("restored_from_revision_id", "character_instance_id", "novel_id")),
    ):
        constraint = _constraint(
            "character_instance_revisions",
            f"fk_character_instance_revision_{relation}_scope",
            ForeignKeyConstraint,
        )
        assert _column_names(constraint) == local

    number = _constraint(
        "character_instance_revisions",
        "uq_character_instance_revision_number",
        UniqueConstraint,
    )
    assert _column_names(number) == ("character_instance_id", "revision_number")


def test_revision_timeline_mapping_has_head_revision_and_segment_layers() -> None:
    head_pointer = _constraint(
        "revision_timeline_mapping_heads",
        "fk_revision_mapping_head_current_scope",
        ForeignKeyConstraint,
    )
    assert _column_names(head_pointer) == (
        "current_mapping_revision_id",
        "revision_id",
        "document_id",
        "novel_id",
    )
    assert _remote_names(head_pointer) == (
        "revision_timeline_mappings.id",
        "revision_timeline_mappings.revision_id",
        "revision_timeline_mappings.document_id",
        "revision_timeline_mappings.novel_id",
    )

    for table_name, constraint_name in (
        ("revision_timeline_mapping_heads", "fk_revision_mapping_head_source_guard"),
        ("revision_timeline_mappings", "fk_revision_mapping_source_guard"),
    ):
        guard = _constraint(table_name, constraint_name, ForeignKeyConstraint)
        assert _column_names(guard) == (
            "revision_id",
            "document_id",
            "source_content_hash",
        )
        assert _remote_names(guard) == (
            "document_revisions.id",
            "document_revisions.document_id",
            "document_revisions.content_hash",
        )

    segment_revision = _constraint(
        "revision_timeline_mapping_segments",
        "fk_revision_mapping_segment_revision_scope",
        ForeignKeyConstraint,
    )
    segment_timeline = _constraint(
        "revision_timeline_mapping_segments",
        "fk_revision_mapping_segment_timeline_scope",
        ForeignKeyConstraint,
    )
    assert _column_names(segment_revision) == ("mapping_revision_id", "novel_id")
    assert _column_names(segment_timeline) == ("timeline_id", "novel_id")


def test_story_fact_v2_entity_and_source_references_are_scope_guarded() -> None:
    targets = {
        "timeline": "story_timelines",
        "character": "novel_characters",
        "character_instance": "character_instances",
        "relationship": "character_relationships",
        "storyline": "storylines",
        "foreshadow": "foreshadows",
    }
    for domain, target in targets.items():
        constraint = _constraint(
            "story_facts",
            f"fk_story_fact_{domain}_scope",
            ForeignKeyConstraint,
        )
        local_id = "character_instance_id" if domain == "character_instance" else f"{domain}_id"
        assert _column_names(constraint) == (local_id, "novel_id")
        assert _remote_names(constraint) == (f"{target}.id", f"{target}.novel_id")

    source = _constraint(
        "story_facts",
        "fk_story_fact_source_guard",
        ForeignKeyConstraint,
    )
    assert _column_names(source) == ("source_revision_id", "source_document_id")
    assert _remote_names(source) == (
        "document_revisions.id",
        "document_revisions.document_id",
    )

    fingerprint = next(
        index for index in _table("story_facts").indexes
        if index.name == "uq_story_fact_event_fingerprint"
    )
    assert fingerprint.unique is True
    assert tuple(column.name for column in fingerprint.columns) == (
        "novel_id",
        "event_fingerprint",
    )


def test_story_state_migration_is_linear_narrow_and_io_free() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260829_0026"' in source
    assert 'down_revision = "20260829_0025"' in source
    for table_name in (
        "story_timelines",
        "story_timeline_links",
        "character_instances",
        "character_instance_revisions",
        "revision_timeline_mapping_heads",
        "revision_timeline_mappings",
        "revision_timeline_mapping_segments",
        "story_event_links",
    ):
        assert f'"{table_name}"' in source
    for forbidden in ("from backend.models", "create_engine", "requests.", "subprocess"):
        assert forbidden not in source
