from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts.tts.chapter_e2e_readiness import (
    ATTESTATION_SCHEMA,
    DatabaseReadinessEvidence,
    EXPECTED_CAPTURES,
    MINIMUM_DATABASE_REVISION,
    REPORT_SCHEMA,
    ReadinessError,
    SqlAlchemyReadinessReader,
    _canonical_json,
    _database_revision_ready,
    _fixed_fixture_missing,
    build_parser,
    evaluate_readiness,
    load_private_attestation,
    main,
)


NOVEL_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/narration/chapter-e2e-v3.json"
)


class FakeReader:
    def __init__(self, evidence: DatabaseReadinessEvidence) -> None:
        self.evidence = evidence
        self.calls = 0

    def audit(self, attestation):  # type: ignore[no-untyped-def]
        assert attestation.novel_id == NOVEL_ID
        assert attestation.document_id == DOCUMENT_ID
        self.calls += 1
        return self.evidence


def _ready_evidence() -> DatabaseReadinessEvidence:
    return DatabaseReadinessEvidence(
        missing_codes=(),
        voice_role_count=3,
        distinct_profile_count=3,
        distinct_voice_version_count=3,
        official_preset_count=3,
        official_provenance_verified_count=3,
        database_checks_completed=True,
        authority_fingerprint_sha256="a" * 64,
    )


@pytest.mark.parametrize(
    ("revisions", "expected"),
    [
        (("20260829_0034",), True),
        (("20260830_0035",), True),
        (("20260901_0036",), True),
        (("20260829_0033",), False),
        (("20990101_9999",), False),
        (("20260829_0034", "20260830_0035"), False),
        ((), False),
    ],
    ids=(
        "minimum",
        "known-descendant-0035",
        "known-descendant-0036",
        "known-ancestor-0033",
        "unknown-or-forked-revision",
        "multiple-heads",
        "missing-head",
    ),
)
def test_database_revision_gate_uses_linear_minimum_ancestry(
    revisions: tuple[str, ...],
    expected: bool,
) -> None:
    assert MINIMUM_DATABASE_REVISION == "20260829_0034"
    assert _database_revision_ready(revisions) is expected


def _private_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "operator-private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def _payload(directory: Path) -> dict[str, object]:
    locks = []
    grants = {
        "nano": "LOCK-NANO/readiness0001",
        "browser": "LOCK-BROWSER/readiness0001",
        "data": "LOCK-T4-K-DATA/readiness0001",
    }
    for name in ("nano", "browser", "data"):
        path = directory / f"{name}.lock"
        path.write_bytes(b"")
        path.chmod(0o600)
        locks.append({"name": name, "path": str(path), "grant": grants[name]})
    return {
        "schema_version": ATTESTATION_SCHEMA,
        "fixture_manifest_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "novel_id": str(NOVEL_ID),
        "document_id": str(DOCUMENT_ID),
        "declarations": {
            "dedicated_test_novel": True,
            "dedicated_test_chapter": True,
            "append_only_recovery_accepted": True,
            "official_presets_local_use": True,
        },
        "expected_characters": ["林晚", "沈川"],
        "expected_official_presets": [
            {"role": "narrator", "preset_id": "onnx.Zhiming"},
            {"role": "林晚", "preset_id": "onnx.Xiaoyu"},
            {"role": "沈川", "preset_id": "onnx.Junhao"},
        ],
        "required_captures": [
            {"width": width, "height": height, "assistant_mode": mode}
            for width, height, mode in EXPECTED_CAPTURES
        ],
        "resource_locks": locks,
    }


def _write_attestation(
    directory: Path,
    payload: object,
    *,
    mode: int = 0o600,
) -> Path:
    path = directory / "readiness-attestation.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    path.chmod(mode)
    return path


def test_all_ready_is_still_hold_and_only_ready_for_operator_review(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    path = _write_attestation(directory, payload)
    attestation = load_private_attestation(path)
    reader = FakeReader(_ready_evidence())

    report = evaluate_readiness(attestation, reader=reader)

    assert reader.calls == 1
    assert report == {
        "schema_version": REPORT_SCHEMA,
        "status": "HOLD",
        "decision": "READY_FOR_OPERATOR_REVIEW",
        "mode": "readonly",
        "release_gate_passed": False,
        "missing_codes": [],
        "summary": {
            "database_checks_completed": True,
            "required_capture_count": 4,
            "resource_locks_ready_count": 3,
            "voice_role_count": 3,
            "distinct_profile_count": 3,
            "distinct_voice_version_count": 3,
            "official_preset_count": 3,
            "official_provenance_verified_count": 3,
        },
    }
    serialized = _canonical_json(report)
    assert "PASS" not in serialized
    for sensitive in (
        str(NOVEL_ID),
        str(DOCUMENT_ID),
        str(directory),
        payload["fixture_manifest_sha256"],
        "林晚",
        "沈川",
        "LOCK-NANO/readiness0001",
    ):
        assert str(sensitive) not in serialized


def test_missing_conditions_are_aggregated_without_sensitive_values(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    declarations = payload["declarations"]
    assert isinstance(declarations, dict)
    declarations["dedicated_test_novel"] = False
    declarations["official_presets_local_use"] = False
    payload["fixture_manifest_sha256"] = "f" * 64
    payload["expected_characters"] = ["林晚"]
    payload["required_captures"] = [
        {"width": 1920, "height": 1080, "assistant_mode": "collapsed"}
    ]
    locks = payload["resource_locks"]
    assert isinstance(locks, list)
    payload["resource_locks"] = locks[:1]
    path = _write_attestation(directory, payload)
    reader = FakeReader(
        DatabaseReadinessEvidence(
            missing_codes=(
                "CURRENT_EDITION_NOT_READY",
                "VOICE_RIGHTS_NOT_READY",
            ),
            voice_role_count=1,
            distinct_profile_count=1,
            distinct_voice_version_count=1,
            official_preset_count=0,
            official_provenance_verified_count=0,
            database_checks_completed=True,
            authority_fingerprint_sha256=None,
        )
    )

    report = evaluate_readiness(
        load_private_attestation(path),
        reader=reader,
    )

    assert report["status"] == "HOLD"
    assert report["decision"] == "NOT_READY"
    assert report["missing_codes"] == sorted(
        [
            "AUTHORITY_FINGERPRINT_NOT_READY",
            "CURRENT_EDITION_NOT_READY",
            "DEDICATED_NOVEL_DECLARATION_REQUIRED",
            "EXACT_DESKTOP_CAPTURE_MATRIX_NOT_READY",
            "FIXTURE_BINDING_NOT_READY",
            "OFFICIAL_PRESET_LOCAL_USE_DECLARATION_REQUIRED",
            "REQUIRED_CHARACTER_CAST_NOT_READY",
            "RESOURCE_LOCK_SET_NOT_READY",
            "THREE_DISTINCT_VOICES_NOT_READY",
            "OFFICIAL_PRESET_PROVENANCE_NOT_READY",
            "VOICE_RIGHTS_NOT_READY",
        ]
    )
    serialized = _canonical_json(report)
    assert "f" * 64 not in serialized
    assert str(path) not in serialized


def test_attestation_rejects_superseded_official_preset_mapping(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    bindings = payload["expected_official_presets"]
    assert isinstance(bindings, list)
    bindings[0] = {"role": "narrator", "preset_id": "onnx.Lingyu"}

    with pytest.raises(
        ReadinessError,
        match="ATTESTATION_OFFICIAL_PRESETS_INVALID",
    ):
        load_private_attestation(_write_attestation(directory, payload))


def test_fixed_fixture_binding_uses_the_single_stably_loaded_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    path = _write_attestation(directory, payload)
    attestation = load_private_attestation(path)
    calls = 0

    def fake_load_fixture(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            manifest_sha256=attestation.fixture_manifest_sha256,
            voice_scope="local_personal_use",
            production_eligible=True,
            commercial_distribution_status="not_evaluated",
            minimum_character_speakers=2,
            minimum_distinct_voice_versions=3,
            expected_formal_speakers=("林晚", "沈川"),
            required_viewports=((1920, 1080), (2560, 1440)),
            automatic=SimpleNamespace(source_text="林晚与沈川"),
            manual=SimpleNamespace(source_text="沈川与林晚"),
        )

    def reject_second_path_read(self: Path) -> bytes:
        raise AssertionError("fixture authority must not be reopened after stable loading")

    monkeypatch.setattr(
        "scripts.tts.chapter_e2e_readiness.load_fixture",
        fake_load_fixture,
    )
    monkeypatch.setattr(Path, "read_bytes", reject_second_path_read)

    assert _fixed_fixture_missing(attestation) == set()
    assert calls == 1


def test_exact_viewport_contract_has_only_four_desktop_combinations(
    tmp_path: Path,
) -> None:
    assert EXPECTED_CAPTURES == (
        (1920, 1080, "collapsed"),
        (1920, 1080, "expanded"),
        (2560, 1440, "collapsed"),
        (2560, 1440, "expanded"),
    )
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    captures = payload["required_captures"]
    assert isinstance(captures, list)
    captures.append(
        {"width": 1366, "height": 768, "assistant_mode": "collapsed"}
    )
    path = _write_attestation(directory, payload)

    report = evaluate_readiness(
        load_private_attestation(path),
        reader=FakeReader(_ready_evidence()),
    )

    assert report["missing_codes"] == [
        "EXACT_DESKTOP_CAPTURE_MATRIX_NOT_READY"
    ]


def test_attestation_requires_external_owner_0600_regular_file_and_0700_parent(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    path = _write_attestation(directory, payload, mode=0o644)

    with pytest.raises(ReadinessError, match="ATTESTATION_FILE_UNSAFE"):
        load_private_attestation(path)

    path.chmod(0o600)
    directory.chmod(0o755)
    with pytest.raises(ReadinessError, match="ATTESTATION_FILE_UNSAFE"):
        load_private_attestation(path)

    directory.chmod(0o700)
    path.unlink()
    target = directory / "real.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    target.chmod(0o600)
    path.symlink_to(target)
    with pytest.raises(ReadinessError, match="ATTESTATION_FILE_UNSAFE"):
        load_private_attestation(path)


def test_attestation_schema_is_strict_and_rejects_duplicate_keys(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    payload["unexpected"] = True
    path = _write_attestation(directory, payload)
    with pytest.raises(ReadinessError, match="ATTESTATION_SCHEMA_INVALID"):
        load_private_attestation(path)

    duplicate = (
        '{"schema_version":"%s","schema_version":"%s"}'
        % (ATTESTATION_SCHEMA, ATTESTATION_SCHEMA)
    )
    path.write_text(duplicate, encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ReadinessError, match="ATTESTATION_JSON_INVALID"):
        load_private_attestation(path)


def test_database_reader_rejects_non_postgresql_before_any_query() -> None:
    class FakeSession:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

        def get_bind(self):  # type: ignore[no-untyped-def]
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def execute(self, _statement):
            raise AssertionError("must not query a non-PostgreSQL database")

    reader = SqlAlchemyReadinessReader(FakeSession, storage=None)
    with pytest.raises(ReadinessError, match="DATABASE_POSTGRESQL_REQUIRED"):
        with reader._read_session():  # noqa: SLF001 - safety boundary test
            raise AssertionError("unreachable")


def test_database_reader_fails_closed_when_transaction_is_not_read_only() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.scalar_values = iter(("off", "repeatable read"))

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

        def get_bind(self):  # type: ignore[no-untyped-def]
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement):  # type: ignore[no-untyped-def]
            assert "REPEATABLE READ READ ONLY" in str(statement)

        def scalar(self, _statement):
            return next(self.scalar_values)

    reader = SqlAlchemyReadinessReader(FakeSession, storage=None)
    with pytest.raises(ReadinessError, match="DATABASE_READ_ONLY_REQUIRED"):
        with reader._read_session():  # noqa: SLF001 - safety boundary test
            raise AssertionError("unreachable")


def test_cli_accepts_only_readonly_attestation_and_emits_canonical_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    actions = {action.dest for action in build_parser()._actions}  # noqa: SLF001
    assert actions == {"mode", "attestation_file"}
    directory = _private_directory(tmp_path)
    payload = _payload(directory)
    path = _write_attestation(directory, payload)

    result = main(
        ["--mode", "readonly", "--attestation-file", str(path)],
        reader=FakeReader(_ready_evidence()),
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["status"] == "HOLD"
    assert report["decision"] == "READY_FOR_OPERATOR_REVIEW"
    assert captured.out == _canonical_json(report) + "\n"
    assert str(path) not in captured.out
    assert str(NOVEL_ID) not in captured.out


def test_cli_argument_failure_is_redacted_hold_json_on_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(["--mode", "readonly", "--database-url", "secret-dsn"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["status"] == "HOLD"
    assert report["missing_codes"] == ["READINESS_ARGUMENTS_INVALID"]
    assert "secret-dsn" not in captured.out
    assert captured.out == _canonical_json(report) + "\n"


def test_help_cannot_escape_the_canonical_json_only_cli_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(["--help"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["missing_codes"] == ["READINESS_ARGUMENTS_INVALID"]
    assert captured.out == _canonical_json(report) + "\n"
