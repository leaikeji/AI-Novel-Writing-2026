"""Conflict boundaries verified without a PostgreSQL server or model calls."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from backend.context_v4_loader import (
    MAX_FACT_CANDIDATES,
    MAX_FINAL_FACTS,
    _complete_fact_group_ids,
    _select_story_facts,
)
from backend.creative_data_models import StoryEventLink
from backend.models import DerivedSourceBinding, StoryFact


def uid(value):
    return UUID(int=value)


@pytest.mark.parametrize("cap", [MAX_FINAL_FACTS, MAX_FACT_CANDIDATES])
@pytest.mark.parametrize("interleaved", [False, True])
def test_sql_omits_the_complete_group_when_the_cap_would_split_it(cap, interleaved):
    # SQLite is private in-memory SQL only. Execute the actual window query;
    # a fake session slicing a list cannot establish this boundary guarantee.
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE story_facts (
            id CHAR(32), novel_id CHAR(32), timeline_id CHAR(32), fact_type TEXT,
            character_instance_id CHAR(32), relationship_id CHAR(32),
            storyline_id CHAR(32), foreshadow_id CHAR(32), character_id CHAR(32),
            subject TEXT, dimension TEXT, predicate TEXT, story_sequence INTEGER,
            created_at TEXT)""")
        rows = []
        for index in range(cap + 1):
            is_pair = index in ({0, cap} if interleaved else {cap - 1, cap})
            rows.append((
                uid(1000 + index).hex, uid(1).hex, uid(2).hex,
                "general_fact", "door" if is_pair else f"other-{index}",
                "state", "open", 1 if interleaved or is_pair else cap + 1 - index,
                f"2026-09-10 00:00:{(cap - index) % 60:02}",
            ))
        # Stable timestamps make UUID descending the tie order. Put the first
        # conflicting row first and the second last for the interleaved case.
        if interleaved:
            rows = [(*row[:-1], f"{cap + 1 - index:06}") for index, row in enumerate(rows)]
        connection.exec_driver_sql("""INSERT INTO story_facts
            (id,novel_id,timeline_id,fact_type,subject,dimension,predicate,story_sequence,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", rows)
        # A different novel's matching group must not affect our window.
        connection.exec_driver_sql("""INSERT INTO story_facts
            (id,novel_id,timeline_id,fact_type,subject,dimension,predicate,story_sequence,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", (
            uid(9000).hex, uid(99).hex, uid(2).hex, "general_fact", "other-0",
            "state", "open", 99999, "999999",
        ))
        selected = set(connection.scalars(_complete_fact_group_ids(
            novel_id=uid(1),
            predicates=(StoryFact.timeline_id == uid(2), StoryFact.story_sequence <= cap + 1),
            cap=cap,
        )))
        pair_indices = {0, cap} if interleaved else {cap - 1, cap}
        assert not selected.intersection(uid(1000 + index) for index in pair_indices)
        assert len(selected) == cap - 1
        assert uid(9000) not in selected
    engine.dispose()


class ConflictSession:
    def __init__(self, *, peer_status="active", peer_in_scope=True):
        self.current = StoryFact(
            id=uid(10), novel_id=uid(1), schema_version="story-fact/2",
            fact_type="general_fact", subject="门", predicate="状态", object_text="开",
            details={"schema_version": "general-fact/1", "value": "开"},
            timeline_id=uid(2), dimension="state", event_kind="confirmed",
            story_sequence=3, visibility_json={"schema_version": "story-visibility/1", "scope": "all"},
            event_fingerprint="a" * 64, status="active", created_at=datetime.now(UTC),
        )
        self.link = SimpleNamespace(
            id=uid(100), novel_id=uid(1), source_fact_id=uid(10),
            target_fact_id=uid(11), link_type="contradicts",
        )
        self.peer = SimpleNamespace(
            id=uid(11), source_revision_id=None, status=peer_status, story_sequence=2,
        )
        self.peer_in_scope = peer_in_scope
        self.execute_count = 0
        self.statements = []

    def scalar(self, statement):
        return None

    def execute(self, statement):
        self.statements.append(statement)
        self.execute_count += 1
        if self.execute_count == 1:
            return [self.current]
        params = statement.compile().params
        assert params["novel_id_1"] == uid(1)
        assert params["timeline_id_1"] == uid(2)
        assert params["story_sequence_1"] == 10
        assert "story_facts.story_sequence IS NOT NULL" in str(statement)
        return [self.peer] if self.peer_in_scope else []

    def scalars(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        if entity is StoryEventLink:
            if "contradicts" in statement.compile().params.values():
                assert " OR " in str(statement)
                return [self.link]
            return []
        if entity is DerivedSourceBinding:
            return []
        if entity is StoryFact:
            return [self.current]
        return [self.current.id]


@pytest.mark.parametrize("status,in_scope,expected", [
    ("active", True, []),
    ("invalid", True, [uid(10)]),
    ("active", False, [uid(10)]),
])
def test_explicit_conflict_outside_selection_is_verified_before_excluding(status, in_scope, expected):
    session = ConflictSession(peer_status=status, peer_in_scope=in_scope)
    facts, links, _, omitted = _select_story_facts(
        session,
        novel_id=uid(1),
        scope=SimpleNamespace(timeline=SimpleNamespace(id=uid(2)), story_limits={uid(2): 10}),
    )
    assert [fact.id for fact in facts] == expected
    assert links == ()
    assert omitted == (0 if expected else 1)
