from __future__ import annotations

from pathlib import Path

import pytest

from backend.narration.schema_readiness import (
    _FEATURE_REQUIRED_FUNCTION_MARKERS,
    _function_definitions_satisfy,
    _linear_repository_chain,
    ALEMBIC_CONFIG_PATH,
    CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
    REPOSITORY_BASE_REVISION,
    character_cast_schema_ready,
    database_revision_satisfies,
    narration_feature_schema_ready,
    repository_unique_head,
    voice_generator_schema_ready,
)
from tests.narration.current_schema_gate import (
    assert_database_at_repository_head,
    repository_head_or_fail,
)


MINIMUM = "20260829_0032"


def test_repository_unique_head_uses_the_canonical_repository_only() -> None:
    chain = _linear_repository_chain(str(ALEMBIC_CONFIG_PATH.resolve()))

    assert chain[-1] == REPOSITORY_BASE_REVISION
    assert repository_unique_head() == chain[0] == "20260902_0039"
    assert repository_head_or_fail() == chain[0]


def test_current_schema_gate_requires_an_exact_database_head() -> None:
    class FakeConnection:
        def __init__(self, revision: str) -> None:
            self.revision = revision

        def scalar(self, _statement):  # type: ignore[no-untyped-def]
            return self.revision

    assert assert_database_at_repository_head(  # type: ignore[arg-type]
        FakeConnection("20260902_0039")
    ) == "20260902_0039"
    with pytest.raises(AssertionError, match="does not match repository"):
        assert_database_at_repository_head(  # type: ignore[arg-type]
            FakeConnection("20260830_0035")
        )


def test_minimum_and_known_linear_descendants_are_accepted() -> None:
    assert database_revision_satisfies((MINIMUM,), minimum_revision=MINIMUM)
    assert database_revision_satisfies(
        ("20260829_0033",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260829_0034",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260830_0035",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260901_0036",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260902_0037",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260902_0038",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260902_0039",), minimum_revision=MINIMUM
    )


def test_character_cast_requires_0036_or_a_known_linear_descendant() -> None:
    assert database_revision_satisfies(
        ("20260901_0036",),
        minimum_revision=CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
    )
    assert database_revision_satisfies(
        ("20260902_0037",),
        minimum_revision=CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
    )
    assert database_revision_satisfies(
        ("20260902_0038",),
        minimum_revision=CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
    )
    assert database_revision_satisfies(
        ("20260902_0039",),
        minimum_revision=CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
    )
    assert not database_revision_satisfies(
        ("20260830_0035",),
        minimum_revision=CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
    )


def test_older_unknown_and_multiple_database_heads_fail_closed() -> None:
    assert not database_revision_satisfies(
        ("20260829_0031",), minimum_revision=MINIMUM
    )
    assert not database_revision_satisfies(
        ("20990101_9999",), minimum_revision=MINIMUM
    )
    assert not database_revision_satisfies(
        (MINIMUM, "20260829_0033"), minimum_revision=MINIMUM
    )
    assert not database_revision_satisfies((), minimum_revision=MINIMUM)


def test_missing_or_malformed_repository_graph_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ini"
    assert not database_revision_satisfies(
        (MINIMUM,), minimum_revision=MINIMUM, config_path=missing
    )
    assert not database_revision_satisfies(
        (MINIMUM,), minimum_revision="", config_path=missing
    )


def test_truncated_repository_graph_fails_closed(tmp_path: Path) -> None:
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "20990101_0001_truncated.py").write_text(
        'revision = "20990101_0001"\n'
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n",
        encoding="utf-8",
    )
    config = tmp_path / "alembic.ini"
    config.write_text("[alembic]\nscript_location = migrations\n", encoding="utf-8")

    assert not database_revision_satisfies(
        ("20990101_0001",),
        minimum_revision="20990101_0001",
        config_path=config,
    )


def test_repository_chain_is_resolved_from_the_config_not_process_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _linear_repository_chain.cache_clear()
    monkeypatch.chdir(tmp_path)
    assert "20260829_0034" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert "20260830_0035" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert "20260901_0036" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert "20260902_0037" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert "20260902_0038" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert "20260902_0039" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert database_revision_satisfies(
        ("20260829_0034",),
        minimum_revision=MINIMUM,
    )
    _linear_repository_chain.cache_clear()


def test_feature_schema_sentinel_rejects_non_engine_values() -> None:
    assert narration_feature_schema_ready(None) is False  # type: ignore[arg-type]
    assert voice_generator_schema_ready(None) is False  # type: ignore[arg-type]
    assert character_cast_schema_ready(None) is False  # type: ignore[arg-type]


def test_feature_schema_sentinel_requires_current_function_bodies() -> None:
    definitions = {
        signature: "\n".join(markers)
        for signature, markers in _FEATURE_REQUIRED_FUNCTION_MARKERS.items()
    }
    assert _function_definitions_satisfy(definitions)

    stale = dict(definitions)
    stale["narration_guard_voice_preview_job_closure_v1()"] = (
        "legacy one-preview-per-job closure"
    )
    assert not _function_definitions_satisfy(stale)
    assert not _function_definitions_satisfy(
        {
            signature: definition
            for signature, definition in definitions.items()
            if signature != "narration_guard_voice_deletion()"
        }
    )
