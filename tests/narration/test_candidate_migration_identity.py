from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.tts import candidate_migration_identity as identity


BASE = identity.CANONICAL_BASE_REVISION


def _migration_source(
    revision: str,
    down_revision: str | None,
    *,
    tail: str = "",
) -> str:
    return (
        f"revision = {revision!r}\n"
        f"down_revision = {down_revision!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        f"{tail}"
    )


def _candidate(
    root: Path,
    nodes: list[tuple[str, str | None]],
    *,
    tails: dict[str, str] | None = None,
    config: str = "[alembic]\nscript_location = backend/migrations\n",
) -> Path:
    root.mkdir()
    (root / "alembic.ini").write_text(config, encoding="utf-8")
    versions = root / "backend" / "migrations" / "versions"
    versions.mkdir(parents=True)
    for revision, parent in nodes:
        path = versions / f"{revision}_fixture.py"
        path.write_text(
            _migration_source(
                revision,
                parent,
                tail=(tails or {}).get(revision, ""),
            ),
            encoding="utf-8",
        )
    return root


def test_valid_graph_is_parsed_without_executing_top_level_code(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    candidate = _candidate(
        tmp_path / "candidate",
        [(BASE, None), ("20260901_0036", BASE)],
        tails={
            "20260901_0036": (
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed')\n"
                "raise RuntimeError('must never run')\n"
            )
        },
    )

    result = identity.inspect_candidate_migrations(candidate)

    assert result.base == BASE
    assert result.head == "20260901_0036"
    assert result.revisions == (BASE, "20260901_0036")
    assert result.file_count == 2
    assert result.total_bytes > 0
    assert not marker.exists()


@pytest.mark.parametrize(
    "nodes",
    [
        [("20260901_0036", None)],
        [("20260823_0099", None), ("20260901_0036", "20260823_0099")],
    ],
)
def test_fixed_canonical_base_cannot_be_truncated_or_replaced(
    tmp_path: Path,
    nodes: list[tuple[str, str | None]],
) -> None:
    candidate = _candidate(tmp_path / "candidate", nodes)

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_CANONICAL_BASE_MISSING",
    ):
        identity.inspect_candidate_migrations(candidate)


def test_two_candidates_are_inspected_independently_without_cached_head(
    tmp_path: Path,
) -> None:
    first = _candidate(
        tmp_path / "first",
        [(BASE, None), ("20260830_0035", BASE)],
    )
    second = _candidate(
        tmp_path / "second",
        [(BASE, None), ("20260901_0036", BASE)],
    )

    assert identity.inspect_candidate_migrations(first).head == "20260830_0035"
    assert identity.inspect_candidate_migrations(second).head == "20260901_0036"
    assert identity.inspect_candidate_migrations(first).head == "20260830_0035"


def test_multiple_heads_are_rejected(tmp_path: Path) -> None:
    candidate = _candidate(
        tmp_path / "candidate",
        [
            (BASE, None),
            ("20260830_0035", BASE),
            ("20260901_0036", BASE),
        ],
    )

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_HEAD_CARDINALITY_INVALID",
    ):
        identity.inspect_candidate_migrations(candidate)


def test_non_literal_or_branching_identity_is_rejected(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "candidate", [(BASE, None)])
    migration = next(
        (candidate / "backend" / "migrations" / "versions").glob("*.py")
    )
    migration.write_text(
        (
            "revision = make_revision()\n"
            "down_revision = None\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_IDENTITY_NOT_LITERAL",
    ):
        identity.inspect_candidate_migrations(candidate)


def test_tuple_down_revision_and_filename_mismatch_are_rejected(
    tmp_path: Path,
) -> None:
    tuple_candidate = _candidate(tmp_path / "tuple", [(BASE, None)])
    migration = next(
        (tuple_candidate / "backend" / "migrations" / "versions").glob("*.py")
    )
    migration.write_text(
        (
            f"revision = {BASE!r}\n"
            "down_revision = ('20260822_0000', '20260822_0001')\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_DOWN_REVISION_INVALID",
    ):
        identity.inspect_candidate_migrations(tuple_candidate)

    filename_candidate = _candidate(tmp_path / "filename", [(BASE, None)])
    original = next(
        (filename_candidate / "backend" / "migrations" / "versions").glob("*.py")
    )
    original.rename(original.with_name("20260823_9999_wrong.py"))
    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_FILENAME_MISMATCH",
    ):
        identity.inspect_candidate_migrations(filename_candidate)


@pytest.mark.parametrize(
    ("option", "value", "code"),
    [
        ("script_location", "../backend/migrations", "ALEMBIC_SCRIPT_LOCATION_INVALID"),
        ("version_locations", "/tmp/versions", "ALEMBIC_VERSION_LOCATIONS_UNSUPPORTED"),
        ("recursive_version_locations", "true", "ALEMBIC_VERSION_LOCATIONS_UNSUPPORTED"),
        ("sourceless", "true", "ALEMBIC_SOURCELESS_UNSUPPORTED"),
    ],
)
def test_alembic_loader_escape_options_are_rejected(
    tmp_path: Path,
    option: str,
    value: str,
    code: str,
) -> None:
    if option == "script_location":
        config = f"[alembic]\nscript_location = {value}\n"
    else:
        config = (
            "[alembic]\nscript_location = backend/migrations\n"
            f"{option} = {value}\n"
        )
    candidate = _candidate(tmp_path / "candidate", [(BASE, None)], config=config)

    with pytest.raises(identity.CandidateMigrationError, match=code):
        identity.inspect_candidate_migrations(candidate)


def test_migration_file_count_limit_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(
        tmp_path / "candidate",
        [(BASE, None), ("20260901_0036", BASE)],
    )
    monkeypatch.setattr(identity, "MAX_MIGRATION_FILES", 1)

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_FILE_COUNT_EXCEEDED",
    ):
        identity.inspect_candidate_migrations(candidate)


def test_migration_single_file_size_limit_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(tmp_path / "candidate", [(BASE, None)])
    monkeypatch.setattr(identity, "MAX_MIGRATION_FILE_BYTES", 80)

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_FILE_TOO_LARGE",
    ):
        identity.inspect_candidate_migrations(candidate)


def test_migration_total_size_limit_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(
        tmp_path / "candidate",
        [(BASE, None), ("20260901_0036", BASE)],
    )
    monkeypatch.setattr(identity, "MAX_MIGRATION_TOTAL_BYTES", 150)

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_TOTAL_BYTES_EXCEEDED",
    ):
        identity.inspect_candidate_migrations(candidate)


def test_missing_nofollow_support_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate(tmp_path / "candidate", [(BASE, None)])
    monkeypatch.delattr(os, "O_NOFOLLOW")

    with pytest.raises(
        identity.CandidateMigrationError,
        match="MIGRATION_NOFOLLOW_UNAVAILABLE",
    ):
        identity.inspect_candidate_migrations(candidate)
