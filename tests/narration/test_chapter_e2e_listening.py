from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from uuid import UUID

import pytest

from scripts.tts import chapter_e2e_listening as listening
from scripts.tts import validate_chapter_e2e as validator
from scripts.tts.chapter_e2e_probe_request import (
    PROBE_REQUEST_FILENAME,
    PROBE_REQUEST_SCHEMA_VERSION,
)
from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
)


NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
OUTPUT_HASHES = ("e" * 64, "f" * 64)
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTOMATIC_EDITION_ID = UUID("44444444-4444-4444-8444-444444444444")
MANUAL_EDITION_ID = UUID("55555555-5555-4555-8555-555555555555")
RUN_FINGERPRINT = hashlib.sha256(str(RUN_ID).encode("ascii")).hexdigest()
TARGET_FINGERPRINT = hashlib.sha256(
    f"{NOVEL_ID}:{DOCUMENT_ID}".encode("ascii")
).hexdigest()
AUTOMATIC_EDITION_ID_SHA256 = hashlib.sha256(
    str(AUTOMATIC_EDITION_ID).encode("ascii")
).hexdigest()
MANUAL_EDITION_ID_SHA256 = hashlib.sha256(
    str(MANUAL_EDITION_ID).encode("ascii")
).hexdigest()
AUTOMATIC_EDITION_FINGERPRINT = hashlib.sha256(
    b"automatic-edition-api-fingerprint"
).hexdigest()
MANUAL_EDITION_FINGERPRINT = hashlib.sha256(
    b"manual-edition-api-fingerprint"
).hexdigest()
REVIEWER = "reviewer-t4k-01"


@pytest.fixture(autouse=True)
def _fixed_claim_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "listening-claims"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setattr(
        listening,
        "LISTENING_CLAIM_REGISTRY_DIRECTORY",
        directory,
    )
    monkeypatch.setattr(
        validator,
        "LISTENING_CLAIM_REGISTRY_DIRECTORY",
        directory,
    )


def test_clean_install_creates_the_fixed_private_claim_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = tmp_path / "clean" / "claims"
    monkeypatch.setattr(
        listening,
        "LISTENING_CLAIM_REGISTRY_DIRECTORY",
        registry,
    )
    monkeypatch.setattr(
        validator,
        "LISTENING_CLAIM_REGISTRY_DIRECTORY",
        registry,
    )
    request_directory = tmp_path / "request"
    request_directory.mkdir(mode=0o700)
    request_path = _write_request(request_directory)
    output = tmp_path / "output"
    output.mkdir(mode=0o700)

    record = output / listening.LISTENING_RECORD_FILENAME
    receipt = output / listening.FINALIZATION_RECEIPT_FILENAME
    listening.ListeningFinalizer(
        now=lambda: NOW + timedelta(seconds=1)
    ).finalize(
        request_path,
        record,
        receipt,
        reviewer_pseudonym=REVIEWER,
        verdict="pass",
        checks={name: True for name in listening.CHECK_NAMES},
        confirmation=listening.HUMAN_LISTENING_CONFIRMATION,
    )

    assert record.is_file()
    assert receipt.is_file()
    metadata = registry.stat()
    assert stat.S_ISDIR(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o700
    assert metadata.st_uid == os.getuid()
    assert (registry / f"{RUN_FINGERPRINT}.claim").is_file()
    assert (registry / f"{RUN_FINGERPRINT}.commit").is_file()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _request_payload(*, created_at: datetime = NOW) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": PROBE_REQUEST_SCHEMA_VERSION,
        "report_schema_version": PROBE_SCHEMA_VERSION,
        "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "controller_preflight_payload_sha256": "c" * 64,
        "binding_seed": {
            "run_fingerprint_sha256": RUN_FINGERPRINT,
            "target_scope_sha256": TARGET_FINGERPRINT,
            "automatic_edition_id_sha256": AUTOMATIC_EDITION_ID_SHA256,
            "manual_edition_id_sha256": MANUAL_EDITION_ID_SHA256,
            "automatic_edition_fingerprint_sha256": (
                AUTOMATIC_EDITION_FINGERPRINT
            ),
            "manual_edition_fingerprint_sha256": MANUAL_EDITION_FINGERPRINT,
            "listening_output_hashes": list(OUTPUT_HASHES),
            "required_stability_seconds": 1800.0,
        },
        "performance_seed": {
            "request_to_ready_seconds": [1.25, 2.5],
            "observed_http_first_audio_ms": [1250, 2500],
            "chapter_audio_duration_seconds": 415.04,
        },
        "required_captures": [
            {
                "width": width,
                "height": height,
                "assistant_mode": assistant_mode,
            }
            for width, height in validator.ALLOWED_VIEWPORTS
            for assistant_mode in ALLOWED_ASSISTANT_MODES
        ],
        "runtime_contract": {
            "sidecar_container_name": EXPECTED_SIDECAR_CONTAINER_NAME,
            "range_status_codes": list(EXPECTED_RANGE_STATUS_CODES),
        },
    }
    return {
        **unsigned,
        "request_fingerprint_sha256": hashlib.sha256(
            _canonical_json(unsigned)
        ).hexdigest(),
    }


def _refingerprint(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    del unsigned["request_fingerprint_sha256"]
    payload["request_fingerprint_sha256"] = hashlib.sha256(
        _canonical_json(unsigned)
    ).hexdigest()


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def _write_request(
    directory: Path,
    payload: dict[str, object] | None = None,
    *,
    raw: bytes | None = None,
) -> Path:
    directory.chmod(0o700)
    path = directory / PROBE_REQUEST_FILENAME
    path.write_bytes(
        raw
        if raw is not None
        else _canonical_json(payload or _request_payload()) + b"\n"
    )
    path.chmod(0o600)
    return path


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    return (
        _write_request(request_directory),
        output_directory / listening.LISTENING_RECORD_FILENAME,
        output_directory / listening.FINALIZATION_RECEIPT_FILENAME,
    )


def _arguments(
    probe_request: Path,
    record: Path,
    receipt: Path,
    *,
    mode: str = "finalize",
    verdict: str = "pass",
    values: dict[str, str] | None = None,
    reviewer: str = REVIEWER,
    confirmation: str = listening.HUMAN_LISTENING_CONFIRMATION,
) -> list[str]:
    checks = {
        "narrator-character-distinguishable": "yes",
        "voices-stable": "yes",
        "no-missing-or-repeated-text": "yes",
        "all-samples-intelligible-mandarin": "yes",
        "no-abnormal-pause-or-seam": "yes",
        "loudness-consistent": "yes",
    }
    checks.update(values or {})
    return [
        "--mode",
        mode,
        "--probe-request-file",
        str(probe_request),
        "--listening-record",
        str(record),
        "--finalization-receipt",
        str(receipt),
        "--reviewer-pseudonym",
        reviewer,
        "--verdict",
        verdict,
        "--narrator-character-distinguishable",
        checks["narrator-character-distinguishable"],
        "--voices-stable",
        checks["voices-stable"],
        "--no-missing-or-repeated-text",
        checks["no-missing-or-repeated-text"],
        "--all-samples-intelligible-mandarin",
        checks["all-samples-intelligible-mandarin"],
        "--no-abnormal-pause-or-seam",
        checks["no-abnormal-pause-or-seam"],
        "--loudness-consistent",
        checks["loudness-consistent"],
        "--confirm-human-listening",
        confirmation,
    ]


def _finalizer(*, now: datetime = NOW) -> listening.ListeningFinalizer:
    return listening.ListeningFinalizer(now=lambda: now)


def _run(
    probe_request: Path,
    record: Path,
    receipt: Path,
    **argument_overrides: object,
) -> int:
    return listening.main(
        _arguments(
            probe_request,
            record,
            receipt,
            **argument_overrides,
        ),
        finalizer=_finalizer(),
    )


def _assert_validator_state_after_schema_integration(
    record_path: Path,
    expected_state: str,
) -> None:
    arguments = {
        "run_id": RUN_ID,
        "novel_id": NOVEL_ID,
        "document_id": DOCUMENT_ID,
        "automatic_edition_id_sha256": AUTOMATIC_EDITION_ID_SHA256,
        "manual_edition_id_sha256": MANUAL_EDITION_ID_SHA256,
        "automatic_edition_fingerprint_sha256": (
            AUTOMATIC_EDITION_FINGERPRINT
        ),
        "manual_edition_fingerprint_sha256": MANUAL_EDITION_FINGERPRINT,
        "expected_output_hashes": OUTPUT_HASHES,
        "collector_collected_at": "2026-08-27T12:00:00Z",
    }
    if validator.LISTENING_SCHEMA == listening.LISTENING_SCHEMA:
        assert validator._load_listening_record(
            record_path,
            **arguments,
        )["state"] == expected_state
        return
    assert validator.LISTENING_SCHEMA == listening.LEGACY_LISTENING_SCHEMA
    with pytest.raises(validator.RunnerError, match="LISTENING_RECORD_INVALID"):
        validator._load_listening_record(record_path, **arguments)


def test_finalize_pass_writes_exact_v1_1_record_and_v1_2_redacted_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe_request, record_path, receipt_path = _paths(tmp_path)

    assert _run(probe_request, record_path, receipt_path) == 0

    output = capsys.readouterr()
    assert output.out.strip() == "LISTENING_FINALIZED"
    assert output.err == ""
    record_raw = record_path.read_bytes()
    record = json.loads(record_raw)
    assert record == {
        "schema_version": listening.LISTENING_SCHEMA,
        "reviewer_pseudonym": REVIEWER,
        "reviewed_at": "2026-08-27T12:00:00Z",
        "verdict": "pass",
        "output_hashes": list(OUTPUT_HASHES),
        "checks": {
            "narrator_character_distinguishable": True,
            "voices_stable": True,
            "no_missing_or_repeated_text": True,
            "all_samples_intelligible_mandarin": True,
            "no_abnormal_pause_or_seam": True,
            "loudness_consistent": True,
        },
    }
    _assert_validator_state_after_schema_integration(record_path, "PASS")

    receipt = json.loads(receipt_path.read_bytes())
    request = json.loads(probe_request.read_bytes())
    assert receipt == {
        "schema_version": listening.FINALIZATION_RECEIPT_SCHEMA,
        "finalized_at": "2026-08-27T12:00:00Z",
        "verdict": "pass",
        "probe_request_fingerprint_sha256": request[
            "request_fingerprint_sha256"
        ],
        "run_fingerprint_sha256": RUN_FINGERPRINT,
        "target_scope_sha256": TARGET_FINGERPRINT,
        "automatic_edition_id_sha256": AUTOMATIC_EDITION_ID_SHA256,
        "manual_edition_id_sha256": MANUAL_EDITION_ID_SHA256,
        "automatic_edition_fingerprint_sha256": (
            AUTOMATIC_EDITION_FINGERPRINT
        ),
        "manual_edition_fingerprint_sha256": MANUAL_EDITION_FINGERPRINT,
        "listening_record_sha256": hashlib.sha256(record_raw).hexdigest(),
        "reviewed_roles": list(listening.REVIEWED_ROLES),
    }
    receipt_text = receipt_path.read_text("utf-8")
    assert REVIEWER not in receipt_text
    for output_hash in OUTPUT_HASHES:
        assert output_hash not in receipt_text
    for path in (record_path, receipt_path):
        details = path.stat()
        assert stat.S_IMODE(details.st_mode) == 0o600
        assert details.st_uid == os.getuid()
        assert details.st_nlink == 1

    registry = listening.LISTENING_CLAIM_REGISTRY_DIRECTORY
    claim = json.loads((registry / f"{RUN_FINGERPRINT}.claim").read_bytes())
    commit = json.loads((registry / f"{RUN_FINGERPRINT}.commit").read_bytes())
    assert claim["schema_version"] == listening.LISTENING_CLAIM_SCHEMA
    assert claim["automatic_edition_id_sha256"] == AUTOMATIC_EDITION_ID_SHA256
    assert claim["manual_edition_id_sha256"] == MANUAL_EDITION_ID_SHA256
    assert (
        claim["automatic_edition_fingerprint_sha256"]
        == AUTOMATIC_EDITION_FINGERPRINT
    )
    assert (
        claim["manual_edition_fingerprint_sha256"]
        == MANUAL_EDITION_FINGERPRINT
    )
    assert commit["schema_version"] == validator.LISTENING_COMMIT_SCHEMA


@pytest.mark.parametrize(
    "mutation_kind",
    [
        "missing-auto-id",
        "tampered-auto-id",
        "swapped-edition-ids",
        "swapped-edition-fingerprints",
        "legacy-claim-schema",
    ],
)
def test_prepared_claim_requires_exact_v1_2_edition_id_and_api_fingerprint_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation_kind: str,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    original_write = listening._write_exclusive_at
    calls = 0

    def stop_after_claim(
        parent_descriptor: int,
        filename: str,
        data: bytes,
    ) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise listening.ListeningFinalizeError("LISTENING_WRITE_FAILED")
        return original_write(parent_descriptor, filename, data)

    monkeypatch.setattr(listening, "_write_exclusive_at", stop_after_claim)
    assert _run(probe_request, record, receipt) == 2
    capsys.readouterr()
    monkeypatch.setattr(listening, "_write_exclusive_at", original_write)

    claim_path = (
        listening.LISTENING_CLAIM_REGISTRY_DIRECTORY
        / f"{RUN_FINGERPRINT}.claim"
    )
    claim = json.loads(claim_path.read_bytes())
    claim.pop("self_sha256")
    if mutation_kind == "missing-auto-id":
        claim.pop("automatic_edition_id_sha256")
    elif mutation_kind == "tampered-auto-id":
        claim["automatic_edition_id_sha256"] = "0" * 64
    elif mutation_kind == "swapped-edition-ids":
        claim["automatic_edition_id_sha256"], claim["manual_edition_id_sha256"] = (
            claim["manual_edition_id_sha256"],
            claim["automatic_edition_id_sha256"],
        )
    elif mutation_kind == "swapped-edition-fingerprints":
        (
            claim["automatic_edition_fingerprint_sha256"],
            claim["manual_edition_fingerprint_sha256"],
        ) = (
            claim["manual_edition_fingerprint_sha256"],
            claim["automatic_edition_fingerprint_sha256"],
        )
    else:
        claim["schema_version"] = "moss-tts-chapter-listening-claim/1.1"
    sealed = listening._seal_document(claim)
    claim_path.write_bytes(_canonical_json(sealed) + b"\n")

    assert _run(probe_request, record, receipt) == 2
    error = capsys.readouterr().err.strip()
    assert error in {
        "LISTENING_CLAIM_INVALID",
        "LISTENING_FINALIZATION_CONFLICT",
    }
    assert not record.exists()
    assert not receipt.exists()


@pytest.mark.parametrize(
    "mutation_kind",
    [
        "missing-auto-id",
        "swapped-edition-ids",
        "swapped-edition-fingerprints",
        "legacy-receipt-schema",
    ],
)
def test_existing_receipt_requires_exact_v1_2_edition_id_and_api_fingerprint_binding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation_kind: str,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    assert _run(probe_request, record, receipt) == 0
    capsys.readouterr()
    payload = json.loads(receipt.read_bytes())
    if mutation_kind == "missing-auto-id":
        payload.pop("automatic_edition_id_sha256")
    elif mutation_kind == "swapped-edition-ids":
        payload["automatic_edition_id_sha256"], payload["manual_edition_id_sha256"] = (
            payload["manual_edition_id_sha256"],
            payload["automatic_edition_id_sha256"],
        )
    elif mutation_kind == "swapped-edition-fingerprints":
        (
            payload["automatic_edition_fingerprint_sha256"],
            payload["manual_edition_fingerprint_sha256"],
        ) = (
            payload["manual_edition_fingerprint_sha256"],
            payload["automatic_edition_fingerprint_sha256"],
        )
    else:
        payload["schema_version"] = (
            "moss-tts-chapter-listening-finalization-receipt/1.1"
        )
    tampered = _canonical_json(payload) + b"\n"
    receipt.write_bytes(tampered)

    assert _run(probe_request, record, receipt) == 2
    assert capsys.readouterr().err.strip() == "LISTENING_FINALIZATION_CONFLICT"
    assert receipt.read_bytes() == tampered


def test_author_can_finalize_after_the_full_thirty_minute_stability_window(
    tmp_path: Path,
) -> None:
    probe_request, record_path, receipt_path = _paths(tmp_path)
    finalizer = listening.ListeningFinalizer(
        now=lambda: NOW + timedelta(minutes=30, seconds=1)
    )

    finalizer.finalize(
        probe_request,
        record_path,
        receipt_path,
        reviewer_pseudonym=REVIEWER,
        verdict="pass",
        checks={name: True for name in listening.CHECK_NAMES},
        confirmation=listening.HUMAN_LISTENING_CONFIRMATION,
    )

    assert record_path.is_file()
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["finalized_at"] == "2026-08-27T12:30:01Z"


def test_finalize_fail_preserves_explicit_negative_human_decision(
    tmp_path: Path,
) -> None:
    probe_request, record_path, receipt_path = _paths(tmp_path)

    assert _run(
        probe_request,
        record_path,
        receipt_path,
        verdict="fail",
        values={"no-abnormal-pause-or-seam": "no"},
    ) == 0

    record = json.loads(record_path.read_bytes())
    assert record["verdict"] == "fail"
    assert record["checks"]["no_abnormal_pause_or_seam"] is False
    _assert_validator_state_after_schema_integration(record_path, "FAIL")
    assert json.loads(receipt_path.read_bytes())["verdict"] == "fail"


def test_pass_requires_all_six_explicit_yes_values(tmp_path: Path) -> None:
    probe_request, record_path, receipt_path = _paths(tmp_path)

    assert _run(
        probe_request,
        record_path,
        receipt_path,
        values={"voices-stable": "no"},
    ) == 2
    assert not record_path.exists()
    assert not receipt_path.exists()

    assert _run(
        probe_request,
        record_path,
        receipt_path,
        values={"all-samples-intelligible-mandarin": "no"},
    ) == 2
    assert not record_path.exists()
    assert not receipt_path.exists()

    argv = _arguments(probe_request, record_path, receipt_path)
    index = argv.index("--all-samples-intelligible-mandarin")
    del argv[index : index + 2]
    assert listening.main(argv, finalizer=_finalizer()) == 2
    assert not record_path.exists()
    assert not receipt_path.exists()


def test_explicit_unintelligible_mandarin_is_preserved_in_fail_record(
    tmp_path: Path,
) -> None:
    probe_request, record_path, receipt_path = _paths(tmp_path)

    assert _run(
        probe_request,
        record_path,
        receipt_path,
        verdict="fail",
        values={"all-samples-intelligible-mandarin": "no"},
    ) == 0

    record = json.loads(record_path.read_bytes())
    assert record["schema_version"] == listening.LISTENING_SCHEMA
    assert record["verdict"] == "fail"
    assert record["checks"]["all_samples_intelligible_mandarin"] is False


def test_legacy_v1_0_record_is_preserved_but_not_reused_for_v1_1(
    tmp_path: Path,
) -> None:
    probe_request, record_path, receipt_path = _paths(tmp_path)
    legacy_record = _canonical_json(
        {
            "schema_version": listening.LEGACY_LISTENING_SCHEMA,
            "reviewer_pseudonym": REVIEWER,
            "reviewed_at": "2026-08-27T12:00:00Z",
            "verdict": "pass",
            "output_hashes": list(OUTPUT_HASHES),
            "checks": {
                "narrator_character_distinguishable": True,
                "voices_stable": True,
                "no_missing_or_repeated_text": True,
                "no_abnormal_pause_or_seam": True,
                "loudness_consistent": True,
            },
        }
    ) + b"\n"
    record_path.write_bytes(legacy_record)
    record_path.chmod(0o600)

    assert _run(probe_request, record_path, receipt_path) == 2
    assert record_path.read_bytes() == legacy_record
    assert not receipt_path.exists()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda payload: payload.__setitem__("schema_version", "forged"),
            "LISTENING_PROBE_SCHEMA_INVALID",
        ),
        (
            lambda payload: payload.__setitem__(
                "request_fingerprint_sha256", "0" * 64
            ),
            "LISTENING_PROBE_FINGERPRINT_INVALID",
        ),
        (
            lambda payload: payload["binding_seed"].__setitem__(
                "required_stability_seconds", 1799.0
            ),
            "LISTENING_PROBE_BINDING_INVALID",
        ),
        (
            lambda payload: payload.__setitem__(
                "controller_preflight_payload_sha256", "invalid"
            ),
            "LISTENING_PROBE_CONTROLLER_BINDING_INVALID",
        ),
        (
            lambda payload: payload["performance_seed"].__setitem__(
                "chapter_audio_duration_seconds", 0.0
            ),
            "LISTENING_PROBE_PERFORMANCE_INVALID",
        ),
    ],
)
def test_forged_probe_request_is_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: object,
    expected_code: str,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    payload = _request_payload()
    assert callable(mutation)
    mutation(payload)
    if expected_code != "LISTENING_PROBE_FINGERPRINT_INVALID":
        _refingerprint(payload)
    probe_request = _write_request(request_directory, payload)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == expected_code
    assert not record.exists()
    assert not receipt.exists()


@pytest.mark.parametrize(
    "field",
    [
        "automatic_edition_id_sha256",
        "manual_edition_id_sha256",
        "automatic_edition_fingerprint_sha256",
        "manual_edition_fingerprint_sha256",
    ],
)
def test_probe_binding_requires_all_four_edition_id_and_api_fingerprint_hashes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    payload = _request_payload()
    binding = payload["binding_seed"]
    assert isinstance(binding, dict)
    binding.pop(field)
    _refingerprint(payload)
    probe_request = _write_request(request_directory, payload)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    assert capsys.readouterr().err.strip() == "LISTENING_PROBE_BINDING_INVALID"
    assert not record.exists()
    assert not receipt.exists()


@pytest.mark.parametrize(
    ("target_field", "source_field"),
    [
        ("automatic_edition_id_sha256", "manual_edition_id_sha256"),
        (
            "automatic_edition_fingerprint_sha256",
            "manual_edition_fingerprint_sha256",
        ),
    ],
)
def test_probe_binding_rejects_collapsed_automatic_and_manual_editions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    target_field: str,
    source_field: str,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    payload = _request_payload()
    binding = payload["binding_seed"]
    assert isinstance(binding, dict)
    binding[target_field] = binding[source_field]
    _refingerprint(payload)
    probe_request = _write_request(request_directory, payload)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    assert capsys.readouterr().err.strip() == "LISTENING_PROBE_BINDING_INVALID"
    assert not record.exists()
    assert not receipt.exists()


@pytest.mark.parametrize(
    ("created_at", "expected_code"),
    [
        (
            NOW - timedelta(
                seconds=listening.DEFAULT_MAX_REQUEST_AGE_SECONDS + 1
            ),
            "LISTENING_PROBE_REQUEST_EXPIRED",
        ),
        (
            NOW + timedelta(
                seconds=listening.DEFAULT_MAX_FUTURE_SKEW_SECONDS + 1
            ),
            "LISTENING_PROBE_TIME_FUTURE",
        ),
    ],
)
def test_probe_request_must_be_fresh(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    created_at: datetime,
    expected_code: str,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    probe_request = _write_request(
        request_directory,
        _request_payload(created_at=created_at),
    )
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    assert capsys.readouterr().err.strip() == expected_code


@pytest.mark.parametrize("capture_mutation", ["missing", "duplicate", "reordered"])
def test_probe_request_requires_the_exact_four_capture_combinations(
    tmp_path: Path,
    capture_mutation: str,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    payload = _request_payload()
    captures = payload["required_captures"]
    assert isinstance(captures, list)
    if capture_mutation == "missing":
        captures.pop()
    elif capture_mutation == "duplicate":
        captures[-1] = dict(captures[0])
    else:
        captures.reverse()
    _refingerprint(payload)
    probe_request = _write_request(request_directory, payload)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    assert not record.exists()
    assert not receipt.exists()

@pytest.mark.parametrize("hash_mutation", ["malformed", "duplicate", "unsorted"])
def test_probe_request_requires_exact_canonical_output_hashes(
    tmp_path: Path,
    hash_mutation: str,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    payload = _request_payload()
    binding = payload["binding_seed"]
    assert isinstance(binding, dict)
    if hash_mutation == "malformed":
        binding["listening_output_hashes"] = ["not-a-sha256"]
    elif hash_mutation == "duplicate":
        binding["listening_output_hashes"] = [OUTPUT_HASHES[0]] * 2
    else:
        binding["listening_output_hashes"] = list(reversed(OUTPUT_HASHES))
    _refingerprint(payload)
    probe_request = _write_request(request_directory, payload)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    assert not record.exists()
    assert not receipt.exists()

def test_probe_request_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    payload = _request_payload()
    raw = _canonical_json(payload)
    duplicate = raw[:-1] + b',"schema_version":"forged"}\n'
    probe_request = _write_request(request_directory, raw=duplicate)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(probe_request, record, receipt) == 2
    assert not record.exists()
    assert not receipt.exists()


@pytest.mark.parametrize("unsafe", ["file-mode", "parent-mode", "hard-link"])
def test_probe_request_requires_owner_only_single_link_file(
    tmp_path: Path,
    unsafe: str,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    if unsafe == "file-mode":
        probe_request.chmod(0o644)
    elif unsafe == "parent-mode":
        probe_request.parent.chmod(0o755)
    else:
        os.link(probe_request, probe_request.with_name("request-copy.json"))

    assert _run(probe_request, record, receipt) == 2
    assert not record.exists()
    assert not receipt.exists()


def test_probe_request_and_output_symlinks_are_rejected(tmp_path: Path) -> None:
    target_directory = _private_directory(tmp_path / "target")
    output_directory = _private_directory(tmp_path / "finalized")
    target_request = _write_request(target_directory)
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(target_directory, target_is_directory=True)
    linked_request = linked_directory / PROBE_REQUEST_FILENAME
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(linked_request, record, receipt) == 2
    assert target_request.exists()
    assert not record.exists()
    assert not receipt.exists()

    receipt.symlink_to(tmp_path / "does-not-exist")
    assert _run(target_request, record, receipt) == 2
    assert receipt.is_symlink()
    assert not record.exists()


def test_finalization_is_non_overwriting_and_replay_safe(tmp_path: Path) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    assert _run(probe_request, record, receipt) == 0
    record_before = record.read_bytes()
    receipt_before = receipt.read_bytes()
    record_details = record.stat()
    receipt_details = receipt.stat()

    assert _run(probe_request, record, receipt) == 0
    assert record.read_bytes() == record_before
    assert receipt.read_bytes() == receipt_before
    assert record.stat().st_ino == record_details.st_ino
    assert receipt.stat().st_ino == receipt_details.st_ino

    assert _run(
        probe_request,
        record,
        receipt,
        verdict="fail",
        values={"no-missing-or-repeated-text": "no"},
    ) == 2
    assert record.read_bytes() == record_before
    assert receipt.read_bytes() == receipt_before
    assert record.stat().st_ino == record_details.st_ino
    assert receipt.stat().st_ino == receipt_details.st_ino

    alternate = _private_directory(tmp_path / "alternate-output")
    alternate_record = alternate / listening.LISTENING_RECORD_FILENAME
    alternate_receipt = alternate / listening.FINALIZATION_RECEIPT_FILENAME
    assert _run(
        probe_request,
        alternate_record,
        alternate_receipt,
        verdict="fail",
        values={"no-missing-or-repeated-text": "no"},
    ) == 2
    assert not alternate_record.exists()
    assert not alternate_receipt.exists()


@pytest.mark.parametrize("failed_exclusive_call", [2, 3, 4])
def test_prepared_decision_resumes_after_each_publication_crash_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_exclusive_call: int,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    original_write = listening._write_exclusive_at
    calls = 0

    def fail_exclusive(
        parent_descriptor: int,
        filename: str,
        data: bytes,
    ) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == failed_exclusive_call:
            raise listening.ListeningFinalizeError("LISTENING_WRITE_FAILED")
        return original_write(parent_descriptor, filename, data)

    monkeypatch.setattr(listening, "_write_exclusive_at", fail_exclusive)

    assert _run(probe_request, record, receipt) == 2
    registry = listening.LISTENING_CLAIM_REGISTRY_DIRECTORY
    claim = registry / f"{RUN_FINGERPRINT}.claim"
    commit = registry / f"{RUN_FINGERPRINT}.commit"
    assert claim.is_file()
    assert not commit.exists()
    claim_before = claim.read_bytes()
    claim_inode = claim.stat().st_ino
    if failed_exclusive_call == 2:
        assert not receipt.exists()
        assert not record.exists()
    elif failed_exclusive_call == 3:
        assert receipt.is_file()
        assert not record.exists()
    else:
        assert receipt.is_file()
        assert record.is_file()

    monkeypatch.setattr(listening, "_write_exclusive_at", original_write)
    assert _run(probe_request, record, receipt) == 0
    assert record.is_file()
    assert receipt.is_file()
    assert commit.is_file()
    assert claim.read_bytes() == claim_before
    assert claim.stat().st_ino == claim_inode


def test_prepared_decision_can_resume_after_probe_request_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    original_write = listening._write_exclusive_at
    calls = 0

    def stop_after_claim(
        parent_descriptor: int,
        filename: str,
        data: bytes,
    ) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise listening.ListeningFinalizeError("LISTENING_WRITE_FAILED")
        return original_write(parent_descriptor, filename, data)

    monkeypatch.setattr(listening, "_write_exclusive_at", stop_after_claim)
    assert _run(probe_request, record, receipt) == 2
    claim = (
        listening.LISTENING_CLAIM_REGISTRY_DIRECTORY
        / f"{RUN_FINGERPRINT}.claim"
    )
    assert claim.is_file()

    monkeypatch.setattr(listening, "_write_exclusive_at", original_write)
    after_expiry = listening.ListeningFinalizer(
        now=lambda: NOW
        + timedelta(seconds=listening.DEFAULT_MAX_REQUEST_AGE_SECONDS + 60)
    )
    after_expiry.finalize(
        probe_request,
        record,
        receipt,
        reviewer_pseudonym=REVIEWER,
        verdict="pass",
        checks={name: True for name in listening.CHECK_NAMES},
        confirmation=listening.HUMAN_LISTENING_CONFIRMATION,
    )

    assert record.is_file()
    assert receipt.is_file()
    assert (
        listening.LISTENING_CLAIM_REGISTRY_DIRECTORY
        / f"{RUN_FINGERPRINT}.commit"
    ).is_file()


@pytest.mark.parametrize(
    ("trigger", "swapped_directory"),
    [
        ("claim", "output"),
        ("claim", "registry"),
        ("receipt", "output"),
        ("record", "output"),
        ("commit", "output"),
        ("commit", "registry"),
    ],
)
def test_directory_replacement_during_finalization_never_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
    swapped_directory: str,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    registry = listening.LISTENING_CLAIM_REGISTRY_DIRECTORY
    output = record.parent
    original_write = listening._write_exclusive_at
    moved: Path | None = None

    def matches(filename: str) -> bool:
        if trigger == "claim":
            return filename == f"{RUN_FINGERPRINT}.claim"
        if trigger == "commit":
            return filename == f"{RUN_FINGERPRINT}.commit"
        if trigger == "receipt":
            return filename == listening.FINALIZATION_RECEIPT_FILENAME
        return filename == listening.LISTENING_RECORD_FILENAME

    def swap_after_write(
        parent_descriptor: int,
        filename: str,
        data: bytes,
    ) -> tuple[int, int]:
        nonlocal moved
        identity = original_write(parent_descriptor, filename, data)
        if moved is None and matches(filename):
            target = output if swapped_directory == "output" else registry
            moved = target.with_name(f"{target.name}-{trigger}-moved")
            target.rename(moved)
            target.mkdir(mode=0o700)
            target.chmod(0o700)
        return identity

    monkeypatch.setattr(
        listening,
        "_write_exclusive_at",
        swap_after_write,
    )

    assert _run(probe_request, record, receipt) == 2
    assert moved is not None
    assert not record.exists()
    assert not receipt.exists()
    assert not (registry / f"{RUN_FINGERPRINT}.claim").exists()
    assert not (registry / f"{RUN_FINGERPRINT}.commit").exists()
    assert not (moved / listening.LISTENING_RECORD_FILENAME).exists()
    assert not (moved / listening.FINALIZATION_RECEIPT_FILENAME).exists()
    assert not (moved / f"{RUN_FINGERPRINT}.claim").exists()
    assert not (moved / f"{RUN_FINGERPRINT}.commit").exists()


def test_cli_rejects_non_finalize_mode_and_wrong_confirmation(
    tmp_path: Path,
) -> None:
    probe_request, record, receipt = _paths(tmp_path)

    assert _run(probe_request, record, receipt, mode="request") == 2
    assert _run(
        probe_request,
        record,
        receipt,
        confirmation="I-DID-NOT-LISTEN",
    ) == 2
    assert not record.exists()
    assert not receipt.exists()


def test_cli_help_is_a_standard_zero_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert listening.main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "Finalize one explicit T4-K human listening decision" in captured.out
    assert captured.err == ""


def test_cli_stdout_and_stderr_never_echo_private_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_reviewer = "private-reviewer-987"
    request_directory = _private_directory(tmp_path / "private-request-path")
    output_directory = _private_directory(tmp_path / "private-output-path")
    payload = _request_payload()
    payload["request_fingerprint_sha256"] = "0" * 64
    probe_request = _write_request(request_directory, payload)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME

    assert _run(
        probe_request,
        record,
        receipt,
        reviewer=secret_reviewer,
    ) == 2
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    for private_value in (
        str(probe_request),
        str(record),
        str(receipt),
        secret_reviewer,
        RUN_FINGERPRINT,
        TARGET_FINGERPRINT,
        AUTOMATIC_EDITION_FINGERPRINT,
        MANUAL_EDITION_FINGERPRINT,
        *OUTPUT_HASHES,
        *listening.REVIEWED_ROLES,
    ):
        assert private_value not in rendered
    assert captured.err.strip() == "LISTENING_PROBE_FINGERPRINT_INVALID"


def test_cli_redacts_unexpected_exception_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe_request, record, receipt = _paths(tmp_path)
    secret = f"private:{probe_request}"

    class FailingFinalizer:
        def finalize(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError(secret)

    result = listening.main(
        _arguments(probe_request, record, receipt),
        finalizer=FailingFinalizer(),  # type: ignore[arg-type]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err.strip() == "LISTENING_INTERNAL_ERROR"
    assert secret not in captured.err
    assert "Traceback" not in captured.err


def test_private_inputs_and_outputs_cannot_be_inside_code_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_directory = _private_directory(tmp_path / "request")
    output_directory = _private_directory(tmp_path / "finalized")
    probe_request = _write_request(request_directory)
    record = output_directory / listening.LISTENING_RECORD_FILENAME
    receipt = output_directory / listening.FINALIZATION_RECEIPT_FILENAME
    monkeypatch.setattr(listening, "REPOSITORY_ROOT", tmp_path)

    assert _run(probe_request, record, receipt) == 2
    assert not record.exists()
    assert not receipt.exists()
