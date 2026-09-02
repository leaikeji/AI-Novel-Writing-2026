from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.embedding.refresh import (
    MAX_GC_SOURCES_PER_RUN,
    gc_obsolete_active_generation_data,
)


pytestmark = pytest.mark.long_novel


class _ChurnSession:
    def __init__(self) -> None:
        self.source_ids = tuple(uuid4() for _ in range(1_000))
        self.sql: list[str] = []

    def scalar(self, statement: object) -> int:
        self.sql.append(str(statement))
        return 1

    def scalars(self, statement: object) -> tuple[UUID, ...]:
        sql = str(statement)
        self.sql.append(sql)
        if "semantic_sources" in sql and "FOR UPDATE" in sql:
            return self.source_ids
        return ()

    def execute(self, statement: object) -> SimpleNamespace:
        sql = str(statement)
        self.sql.append(sql)
        if sql.lstrip().startswith("SELECT"):
            return SimpleNamespace(one=lambda: (1_500, 1_500))
        return SimpleNamespace()

    def flush(self) -> None:
        return None


def test_retired_churn_cleanup_never_crosses_five_hundred_source_bound() -> None:
    session = _ChurnSession()

    result = gc_obsolete_active_generation_data(
        session,  # type: ignore[arg-type]
        generation_id=uuid4(),
    )

    assert result.source_count == MAX_GC_SOURCES_PER_RUN == 500
    candidate_sql = next(sql for sql in session.sql if "FOR UPDATE" in sql)
    assert "LIMIT" in candidate_sql
    assert "semantic_sources.status IN" in candidate_sql
    assert "semantic_source_refreshes" in candidate_sql
    assert "background_jobs" in candidate_sql
