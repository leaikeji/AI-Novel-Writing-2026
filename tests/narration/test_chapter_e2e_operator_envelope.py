from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from scripts.tts import chapter_e2e_operator_envelope as operator_module
from scripts.tts.chapter_e2e_operator_envelope import (
    AUTHOR_REVIEW_CONFIRMATION,
    CLAIM_SCHEMA,
    ENVELOPE_SCHEMA,
    OperatorEnvelopeError,
    claim_operator_envelope,
    issue_operator_envelope,
    load_operator_envelope,
    main,
    private_lock_identity_sha256,
    verify_operator_envelope_binding,
)
from scripts.tts.chapter_e2e_readiness import (
    ATTESTATION_SCHEMA,
    DatabaseReadinessEvidence,
    EXPECTED_CAPTURES,
    FIXTURE_AUTOMATIC_CASE,
    FIXTURE_MANUAL_CASE,
    ReadinessAttestation,
    evaluate_readiness,
    load_private_attestation,
)
from scripts.tts.validate_chapter_e2e import ChapterFixture, RunnerConfig, load_fixture


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/narration/chapter-e2e-v3.json"
)
NOW = datetime(2026, 8, 27, 1, 2, 3, tzinfo=timezone.utc)
NONCE = "n" * 43


def _fixture() -> ChapterFixture:
    return load_fixture(
        FIXTURE,
        automatic_case_id=FIXTURE_AUTOMATIC_CASE,
        manual_case_id=FIXTURE_MANUAL_CASE,
    )


class FakeReader:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.calls = 0

    def audit(self, attestation):  # type: ignore[no-untyped-def]
        assert attestation.novel_id == NOVEL_ID
        assert attestation.document_id == DOCUMENT_ID
        self.calls += 1
        return DatabaseReadinessEvidence(
            missing_codes=() if self.ready else ("CURRENT_EDITION_NOT_READY",),
            voice_role_count=3 if self.ready else 0,
            distinct_profile_count=3 if self.ready else 0,
            distinct_voice_version_count=3 if self.ready else 0,
            official_preset_count=3 if self.ready else 0,
            official_provenance_verified_count=3 if self.ready else 0,
            database_checks_completed=True,
            authority_fingerprint_sha256=(
                "a" * 64 if self.ready else None
            ),
        )


def _private_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "operator-private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def _claim_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "operator-claim-registry"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setattr(
        operator_module,
        "CLAIM_REGISTRY_DIRECTORY",
        directory,
    )
    return directory


def _recovery_directory(directory: Path) -> Path:
    recovery = directory / "recovery"
    recovery.mkdir(mode=0o700, exist_ok=True)
    recovery.chmod(0o700)
    return recovery


def _directory_identity(path: Path) -> tuple[int, ...]:
    return operator_module._directory_identity(path.stat())


def _install_recovery_head(
    directory: Path,
    *,
    state: str = "BASELINE_CAPTURED",
    generation: int = 1,
    previous_record_sha256: str | None = None,
) -> tuple[Path, str]:
    unsigned: dict[str, object] = {
        "state": state,
        "generation": generation,
        "previous_record_sha256": previous_record_sha256,
    }
    payload = {
        **unsigned,
        "self_sha256": hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    raw = (
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    path = directory / "recovery.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return path, hashlib.sha256(raw).hexdigest()


def _attestation_payload(directory: Path) -> dict[str, object]:
    grants = {
        "nano": "LOCK-NANO/operator-envelope-001",
        "browser": "LOCK-BROWSER/operator-envelope-001",
        "data": "LOCK-T4-K-DATA/operator-envelope-001",
    }
    locks = []
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


def _attestation_file(directory: Path) -> Path:
    path = directory / "attestation.json"
    path.write_text(
        json.dumps(
            _attestation_payload(directory),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _issue(
    directory: Path,
    *,
    reader: FakeReader | None = None,
) -> tuple[Path, ReadinessAttestation]:
    attestation = load_private_attestation(_attestation_file(directory))
    output = directory / "operator-envelope.json"
    issue_operator_envelope(
        attestation=attestation,
        reader=reader or FakeReader(),
        run_id=RUN_ID,
        output_file=output,
        confirmation=AUTHOR_REVIEW_CONFIRMATION,
        now=NOW,
        nonce=NONCE,
    )
    return output, attestation


def _config(directory: Path) -> RunnerConfig:
    return RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=FIXTURE,
        api_base="http://127.0.0.1:18088/api/ai-novel-world-2026",
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id=FIXTURE_AUTOMATIC_CASE,
        manual_case_id=FIXTURE_MANUAL_CASE,
        private_work_dir=directory / "recovery",
        output_dir=directory / "result",
        duration_minutes=30.0,
        listening_record=directory / "listening.json",
        resume=False,
    )


def _locks(
    attestation: ReadinessAttestation,
) -> tuple[dict[str, Path], dict[str, str], dict[str, str]]:
    paths = {item.name: item.path for item in attestation.resource_locks}
    grants = {item.name: item.grant for item in attestation.resource_locks}
    return (
        paths,
        grants,
        {
            name: private_lock_identity_sha256(
                paths[name],
                name=name,
                grant=grants[name],
            )
            for name in paths
        },
    )


def test_issue_and_load_exact_short_lived_four_viewport_envelope(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    output, _attestation = _issue(directory)

    envelope = load_operator_envelope(output, now=NOW)

    assert envelope.run_id == RUN_ID
    assert envelope.novel_id == NOVEL_ID
    assert envelope.document_id == DOCUMENT_ID
    assert envelope.required_captures == (
        (1920, 1080, "collapsed"),
        (1920, 1080, "expanded"),
        (2560, 1440, "collapsed"),
        (2560, 1440, "expanded"),
    )
    assert envelope.expires_at - envelope.issued_at == timedelta(minutes=15)
    assert envelope.nonce == NONCE
    assert output.stat().st_mode & 0o777 == 0o600
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == ENVELOPE_SCHEMA
    assert "path" not in output.read_text(encoding="utf-8")
    assert "token" not in output.read_text(encoding="utf-8").lower()


def test_issue_requires_author_review_and_live_ready_report(tmp_path: Path) -> None:
    directory = _private_directory(tmp_path)
    attestation = load_private_attestation(_attestation_file(directory))
    output = directory / "operator-envelope.json"

    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_AUTHOR_REVIEW_REQUIRED"):
        issue_operator_envelope(
            attestation=attestation,
            reader=FakeReader(),
            run_id=RUN_ID,
            output_file=output,
            confirmation="not-reviewed",
            now=NOW,
            nonce=NONCE,
        )
    assert not output.exists()

    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_READINESS_NOT_READY"):
        issue_operator_envelope(
            attestation=attestation,
            reader=FakeReader(ready=False),
            run_id=RUN_ID,
            output_file=output,
            confirmation=AUTHOR_REVIEW_CONFIRMATION,
            now=NOW,
            nonce=NONCE,
        )
    assert not output.exists()


def test_loader_rejects_expired_tampered_or_non_private_envelope(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    output, _attestation = _issue(directory)

    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_EXPIRED"):
        load_operator_envelope(output, now=NOW + timedelta(minutes=16))

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["runtime"]["required_captures"].append(
        {"width": 1366, "height": 768, "assistant_mode": "collapsed"}
    )
    output.write_text(json.dumps(payload), encoding="utf-8")
    output.chmod(0o600)
    with pytest.raises(
        OperatorEnvelopeError,
        match="OPERATOR_ENVELOPE_FINGERPRINT_INVALID",
    ):
        load_operator_envelope(output, now=NOW)

    output.chmod(0o644)
    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_FILE_UNSAFE"):
        load_operator_envelope(output, now=NOW)


def test_binding_rechecks_scope_fixture_cases_duration_locks_and_readiness(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    output, attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)
    reader = FakeReader()
    report = evaluate_readiness(
        attestation,
        reader=reader,
        _include_authority_fingerprint=True,
    )
    lock_paths, lock_grants, lock_identities = _locks(attestation)

    verify_operator_envelope_binding(
        envelope,
        config=_config(directory),
        fixture=_fixture(),
        attestation=attestation,
        lock_paths=lock_paths,
        lock_grants=lock_grants,
        lock_identity_sha256=lock_identities,
        readiness_report=report,
        resume=False,
    )

    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_BINDING_INVALID"):
        verify_operator_envelope_binding(
            envelope,
            config=replace(_config(directory), document_id=UUID(int=9)),
            fixture=_fixture(),
            attestation=attestation,
            lock_paths=lock_paths,
            lock_grants=lock_grants,
            lock_identity_sha256=lock_identities,
            readiness_report=report,
            resume=False,
        )
    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_READINESS_NOT_READY"):
        verify_operator_envelope_binding(
            envelope,
            config=_config(directory),
            fixture=_fixture(),
            attestation=attestation,
            lock_paths=lock_paths,
            lock_grants=lock_grants,
            lock_identity_sha256=lock_identities,
            readiness_report={**report, "decision": "NOT_READY"},
            resume=False,
        )


def test_claim_is_one_shot_but_exact_resume_survives_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claim_registry(tmp_path, monkeypatch)
    directory = _private_directory(tmp_path)
    output, _attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)
    recovery = _recovery_directory(directory)

    with claim_operator_envelope(
        output,
        envelope,
        private_work_dir=recovery,
        private_work_dir_identity=_directory_identity(recovery),
        resume=False,
        now=NOW + timedelta(seconds=1),
    ) as lease:
        _record, digest = _install_recovery_head(recovery)
        lease.transition("BASELINE_SEALED", 1, digest)
    claim = operator_module._claim_path(envelope)
    assert claim.stat().st_mode & 0o777 == 0o600
    assert json.loads(claim.read_text(encoding="utf-8"))["schema_version"] == CLAIM_SCHEMA
    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_ALREADY_CLAIMED"):
        with claim_operator_envelope(
            output,
            envelope,
            private_work_dir=recovery,
            private_work_dir_identity=_directory_identity(recovery),
            resume=False,
            now=NOW + timedelta(seconds=2),
        ):
            pass

    expired = load_operator_envelope(
        output,
        now=NOW + timedelta(hours=1),
        require_fresh=False,
    )
    with claim_operator_envelope(
        output,
        expired,
        private_work_dir=recovery,
        private_work_dir_identity=_directory_identity(recovery),
        resume=True,
        now=NOW + timedelta(hours=1),
    ) as resumed:
        assert resumed.snapshot().state == "BASELINE_SEALED"
        assert resumed.snapshot().latest_recovery_sha256 == digest
    wrong = replace(expired, run_id=UUID(int=8))
    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_CLAIM_INVALID"):
        with claim_operator_envelope(
            output,
            wrong,
            private_work_dir=recovery,
            private_work_dir_identity=_directory_identity(recovery),
            resume=True,
            now=NOW + timedelta(hours=1),
        ):
            pass


def test_claim_registry_clean_install_and_prepared_retry_are_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = tmp_path / "clean" / "nested" / "operator-claims"
    monkeypatch.setattr(
        operator_module,
        "CLAIM_REGISTRY_DIRECTORY",
        registry,
    )
    directory = _private_directory(tmp_path)
    recovery = _recovery_directory(directory)
    output, _attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)

    for offset in (1, 2):
        with claim_operator_envelope(
            output,
            envelope,
            private_work_dir=recovery,
            private_work_dir_identity=_directory_identity(recovery),
            resume=False,
            now=NOW + timedelta(seconds=offset),
        ) as lease:
            assert lease.snapshot() == operator_module.RecoveryClaimSnapshot(
                state="PREPARED",
                recovery_generation=0,
                latest_recovery_sha256=None,
            )

    assert registry.is_dir()
    assert registry.stat().st_mode & 0o777 == 0o700
    claim = operator_module._claim_path(envelope)
    assert claim.stat().st_mode & 0o777 == 0o600


def test_one_ahead_resume_does_not_persist_before_full_validator_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _claim_registry(tmp_path, monkeypatch)
    directory = _private_directory(tmp_path)
    recovery = _recovery_directory(directory)
    output, _attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)

    with claim_operator_envelope(
        output,
        envelope,
        private_work_dir=recovery,
        private_work_dir_identity=_directory_identity(recovery),
        resume=False,
        now=NOW,
    ) as lease:
        assert lease.snapshot().state == "PREPARED"
    claim_path = operator_module._claim_path(envelope)
    prepared_bytes = claim_path.read_bytes()
    _install_recovery_head(recovery)

    with claim_operator_envelope(
        output,
        envelope,
        private_work_dir=recovery,
        private_work_dir_identity=_directory_identity(recovery),
        resume=True,
        now=NOW + timedelta(seconds=1),
    ) as lease:
        assert lease.snapshot().state == "PREPARED"
        assert lease.snapshot().recovery_generation == 0

    assert claim_path.read_bytes() == prepared_bytes
    assert registry.is_dir()

def test_claim_registry_blocks_copied_or_second_envelope_for_same_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claim_registry(tmp_path, monkeypatch)
    directory = _private_directory(tmp_path)
    output, attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)
    recovery = _recovery_directory(directory)
    with claim_operator_envelope(
        output,
        envelope,
        private_work_dir=recovery,
        private_work_dir_identity=_directory_identity(recovery),
        resume=False,
        now=NOW,
    ) as lease:
        _record, digest = _install_recovery_head(recovery)
        lease.transition("BASELINE_SEALED", 1, digest)

    copied_directory = tmp_path / "copied-private"
    copied_directory.mkdir(mode=0o700)
    copied_directory.chmod(0o700)
    copied = copied_directory / "copied-envelope.json"
    copied.write_bytes(output.read_bytes())
    copied.chmod(0o600)
    copied_envelope = load_operator_envelope(copied, now=NOW)
    copied_recovery = _recovery_directory(copied_directory)
    with pytest.raises(
        OperatorEnvelopeError,
        match="OPERATOR_ENVELOPE_CLAIM_INVALID",
    ):
        with claim_operator_envelope(
            copied,
            copied_envelope,
            private_work_dir=copied_recovery,
            private_work_dir_identity=_directory_identity(copied_recovery),
            resume=False,
            now=NOW,
        ):
            pass

    second = directory / "second-envelope.json"
    issue_operator_envelope(
        attestation=attestation,
        reader=FakeReader(),
        run_id=RUN_ID,
        output_file=second,
        confirmation=AUTHOR_REVIEW_CONFIRMATION,
        now=NOW,
        nonce="s" * 43,
    )
    with pytest.raises(
        OperatorEnvelopeError,
        match="OPERATOR_ENVELOPE_CLAIM_INVALID",
    ):
        with claim_operator_envelope(
            second,
            load_operator_envelope(second, now=NOW),
            private_work_dir=recovery,
            private_work_dir_identity=_directory_identity(recovery),
            resume=False,
            now=NOW,
        ):
            pass


def test_cli_emits_only_redacted_status_and_never_overwrites(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = _private_directory(tmp_path)
    attestation_path = _attestation_file(directory)
    output = directory / "operator-envelope.json"
    argv = [
        "--mode",
        "issue",
        "--attestation-file",
        str(attestation_path),
        "--run-id",
        str(RUN_ID),
        "--output-file",
        str(output),
        "--confirm-author-review",
        AUTHOR_REVIEW_CONFIRMATION,
    ]

    result = main(
        argv,
        reader=FakeReader(),
        now=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report == {
        "code": "READY_FOR_FIXED_LAUNCHER",
        "release_gate_passed": False,
        "schema_version": ENVELOPE_SCHEMA,
        "status": "ISSUED",
    }
    for sensitive in (
        str(RUN_ID),
        str(NOVEL_ID),
        str(DOCUMENT_ID),
        str(directory),
        NONCE,
        "LOCK-NANO/operator-envelope-001",
    ):
        assert sensitive not in captured.out

    result = main(
        argv,
        reader=FakeReader(),
        now=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )
    second = capsys.readouterr()
    assert result == 2
    assert json.loads(second.out)["code"] == "OPERATOR_ENVELOPE_EXISTS"
    assert str(output) not in second.out


def test_resume_binding_skips_new_readiness_but_keeps_all_static_bindings(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    output, attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)
    lock_paths, lock_grants, lock_identities = _locks(attestation)

    verify_operator_envelope_binding(
        envelope,
        config=replace(_config(directory), resume=True),
        fixture=_fixture(),
        attestation=attestation,
        lock_paths=lock_paths,
        lock_grants=lock_grants,
        lock_identity_sha256=lock_identities,
        readiness_report=None,
        resume=True,
    )

    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_BINDING_INVALID"):
        verify_operator_envelope_binding(
            envelope,
            config=replace(_config(directory), resume=True),
            fixture=_fixture(),
            attestation=attestation,
            lock_paths=lock_paths,
            lock_grants=lock_grants,
            lock_identity_sha256=lock_identities,
            readiness_report={"decision": "READY_FOR_OPERATOR_REVIEW"},
            resume=True,
        )


def test_claim_requires_private_external_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claim_registry(tmp_path, monkeypatch)
    directory = _private_directory(tmp_path)
    output, _attestation = _issue(directory)
    envelope = load_operator_envelope(output, now=NOW)
    recovery = _recovery_directory(directory)
    directory.chmod(0o755)

    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_FILE_UNSAFE"):
        with claim_operator_envelope(
            output,
            envelope,
            private_work_dir=recovery,
            private_work_dir_identity=_directory_identity(recovery),
            resume=False,
            now=NOW,
        ):
            pass

    directory.chmod(0o700)
    output.unlink()
    target = directory / "target.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    output.symlink_to(target)
    with pytest.raises(OperatorEnvelopeError, match="OPERATOR_ENVELOPE_FILE_UNSAFE"):
        load_operator_envelope(output, now=NOW)
