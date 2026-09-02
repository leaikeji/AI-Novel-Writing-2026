"""Shared fail-closed gate for tests that require the repository's full schema."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.narration.schema_readiness import repository_unique_head


def repository_head_or_fail() -> str:
    """Return the trusted repository head or stop the test before DB access."""

    head = repository_unique_head()
    if head is None:
        raise RuntimeError("repository migration graph is not one canonical linear chain")
    return head


def assert_database_at_repository_head(connection: Connection) -> str:
    """Assert that an isolated test database exactly matches the repository."""

    expected = repository_head_or_fail()
    actual = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if actual != expected:
        raise AssertionError(
            f"isolated database revision {actual!r} does not match repository {expected!r}"
        )
    return expected


__all__ = ["assert_database_at_repository_head", "repository_head_or_fail"]
