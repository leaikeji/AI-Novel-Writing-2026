from __future__ import annotations

from pathlib import Path

from backend.narration.schema_readiness import (
    _FEATURE_REQUIRED_FUNCTION_MARKERS,
    _function_definitions_satisfy,
    _linear_repository_chain,
    ALEMBIC_CONFIG_PATH,
    database_revision_satisfies,
    narration_feature_schema_ready,
)


MINIMUM = "20260829_0032"


def test_minimum_and_known_linear_descendants_are_accepted() -> None:
    assert database_revision_satisfies((MINIMUM,), minimum_revision=MINIMUM)
    assert database_revision_satisfies(
        ("20260829_0033",), minimum_revision=MINIMUM
    )
    assert database_revision_satisfies(
        ("20260829_0034",), minimum_revision=MINIMUM
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


def test_repository_chain_is_resolved_from_the_config_not_process_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _linear_repository_chain.cache_clear()
    monkeypatch.chdir(tmp_path)
    assert "20260829_0034" in _linear_repository_chain(
        str(ALEMBIC_CONFIG_PATH.resolve())
    )
    assert database_revision_satisfies(
        ("20260829_0034",),
        minimum_revision=MINIMUM,
    )
    _linear_repository_chain.cache_clear()


def test_feature_schema_sentinel_rejects_non_engine_values() -> None:
    assert narration_feature_schema_ready(None) is False  # type: ignore[arg-type]


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
