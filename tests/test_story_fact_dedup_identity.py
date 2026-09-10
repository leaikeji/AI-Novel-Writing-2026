"""Story-fact identity regression tests; no database or model calls."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.services import (
    _find_matching_story_fact,
    _typed_story_fact_candidate,
)


def uid(value: int) -> UUID:
    return UUID(int=value)


PROPOSAL = SimpleNamespace(novel_id=uid(1), chapter_revision_id=uid(2), document_id=uid(3))
ITEM = SimpleNamespace(item_type="world_state")
LEGACY_HASH = "8033142bcdb88772bc40614f88955dd5b7e145374602b3daa096d2997de60793"
PAYLOAD = {
    "subject": "东门",
    "predicate": "开闭",
    "object": "关闭",
    "entity": {},
    "timeline_id": str(uid(4)),
    "dimension": "world_state",
    "event_kind": "confirmed",
    "source_start": 0,
    "source_end": 9,
    "story_sequence": 1,
}


def candidate(**changes):
    return _typed_story_fact_candidate(
        proposal=PROPOSAL,
        revision=SimpleNamespace(),
        item=ITEM,
        payload={**PAYLOAD, **changes},
    )


class MemoryLookup:
    def __init__(self, facts):
        self.facts = facts
        self.statements = []

    def scalar(self, statement):
        self.statements.append(statement)
        params = statement.compile().params
        assert statement._for_update_arg is not None
        assert params["novel_id_1"] == uid(1)
        if "event_fingerprint_1" in params:
            return next((fact for fact in self.facts if fact.event_fingerprint == params["event_fingerprint_1"]), None)
        assert statement._limit_clause.value == 1
        assert params["source_revision_id_1"] == uid(2)
        assert params["source_start_1"] == 0
        assert params["source_end_1"] == 9
        assert params["predicate_1"] == "开闭"
        assert "details_1" in params and "visibility_json_1" in params
        return next((fact for fact in self.facts if fact.subject == params["subject_1"]), None)



@pytest.mark.parametrize("change", [
    {"subject": "西门"},
    {"predicate": "门禁"},
    {"story_sequence": 2},
    {"visibility": "reader"},
])
def test_different_fact_meaning_is_not_deduplicated(change):
    assert candidate().event_fingerprint != candidate(**change).event_fingerprint


def test_same_fact_ignores_generated_ids_and_display_only_entity_metadata():
    original = candidate()
    repeated = candidate(entity={"label": "显示名变化", "is_new": False})
    assert original.id != repeated.id
    assert original.event_fingerprint == repeated.event_fingerprint


def test_existing_legacy_fact_is_reused_without_rewriting_it():
    current = candidate()
    old_hash = LEGACY_HASH
    old = current.model_copy(update={"event_fingerprint": old_hash})
    session = MemoryLookup([old])
    assert _find_matching_story_fact(session, current) is old
    assert old.event_fingerprint == old_hash
    assert len(session.statements) == 2


def test_legacy_hash_collision_does_not_hide_another_subject():
    east = candidate()
    west = candidate(subject="西门")
    old_hash = LEGACY_HASH
    old = east.model_copy(update={"event_fingerprint": old_hash})
    session = MemoryLookup([old])
    assert _find_matching_story_fact(session, west) is None


def test_new_identity_wins_when_legacy_collision_also_exists():
    east = candidate()
    west = candidate(subject="西门")
    old_hash = LEGACY_HASH
    old = east.model_copy(update={"event_fingerprint": old_hash})
    session = MemoryLookup([old, west])
    assert _find_matching_story_fact(session, west) is west
    assert len(session.statements) == 1


def test_typed_event_details_are_part_of_identity():
    values = dict(
        proposal=PROPOSAL,
        revision=SimpleNamespace(),
        item=SimpleNamespace(item_type="storyline_event"),
    )
    payload = {**PAYLOAD, "entity": {"storyline_id": str(uid(5))}}
    first = _typed_story_fact_candidate(**values, payload={**payload, "details": {"progress": 10}})
    second = _typed_story_fact_candidate(**values, payload={**payload, "details": {"progress": 20}})
    assert first.event_fingerprint != second.event_fingerprint


def test_legacy_fact_is_reused_when_only_entity_display_metadata_changes():
    old = candidate().model_copy(update={"event_fingerprint": LEGACY_HASH})
    repeated = candidate(entity={"label": "新版显示名", "is_new": False})
    session = MemoryLookup([old])
    assert _find_matching_story_fact(session, repeated) is old


def test_legacy_query_accepts_sql_null_and_json_null_story_time():
    session = MemoryLookup([])
    assert _find_matching_story_fact(session, candidate()) is None
    query = str(session.statements[-1])
    assert "story_facts.story_time_json IS NULL" in query
    assert "story_facts.story_time_json =" in query
