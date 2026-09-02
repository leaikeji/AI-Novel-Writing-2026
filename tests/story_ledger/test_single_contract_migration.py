from __future__ import annotations

import hashlib
import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.models import CharacterRelationship, DerivedSourceBinding


ROOT = Path(__file__).resolve().parents[2]
REVISION = "20260902_0038"
DOWN_REVISION = "20260902_0037"
HEAD_REVISION = "20260902_0039"
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260902_0038_story_ledger_single_contract.py"
)


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))


def test_single_contract_revision_is_the_only_linear_head() -> None:
    scripts = _scripts()
    assert scripts.get_heads() == [HEAD_REVISION]
    assert scripts.get_revision(HEAD_REVISION).down_revision == REVISION
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_orm_contains_no_redundant_ledger_discriminator_or_relationship_alias() -> None:
    assert "derived_entity_type" not in DerivedSourceBinding.__table__.columns
    assert "relation_type" not in CharacterRelationship.__table__.columns
    binding_constraints = {
        constraint.name for constraint in DerivedSourceBinding.__table__.constraints
    }
    assert "uq_derived_source_fact_revision" in binding_constraints
    assert "uq_derived_source_entity_revision" not in binding_constraints


def test_migration_is_self_contained_and_fail_closed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for forbidden in (
        "from backend.models",
        "create_engine",
        "requests.",
        "subprocess",
    ):
        assert forbidden not in source
    for marker in (
        'revision = "20260902_0038"',
        'down_revision = "20260902_0037"',
        "derived_entity_type IS DISTINCT FROM 'story_fact'",
        "relation_type IS DISTINCT FROM label",
        'op.drop_column("derived_source_bindings", "derived_entity_type")',
        'op.drop_column("character_relationships", "relation_type")',
        'next_inverse["payload_hash"] = payload_hash',
        "commit hash rewrite would collide",
    ):
        assert marker in source


def test_commit_hash_contract_has_one_current_shape_and_reversible_old_shape() -> None:
    module = _scripts().get_revision(REVISION).module
    proposal_id = "00000000-0000-0000-0000-000000000100"
    accepted = [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
    ]
    current_payload = {
        "proposal_id": proposal_id,
        "accepted_item_ids": sorted(accepted),
    }
    previous_payload = {
        **current_payload,
        "item_overrides": {item_id: {} for item_id in sorted(accepted)},
    }

    def digest(payload: dict[str, object]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert module._canonical_payload_hash(
        proposal_id,
        accepted,
        include_empty_overrides=False,
    ) == digest(current_payload)
    assert module._canonical_payload_hash(
        proposal_id,
        accepted,
        include_empty_overrides=True,
    ) == digest(previous_payload)
