from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import stat

import pytest

from backend.narration.digest_keyring import DigestKeyringError, load_digest_keyring
from scripts.tts import manage_digest_keyring as operations


FIRST_SECRET = b"a" * 32
SECOND_SECRET = b"b" * 32


def _initialize(path: Path, *, key_id: str = "narration-local-2026-08") -> str:
    return operations.initialize_digest_keyring(
        path,
        key_id,
        fresh_install=True,
        assert_no_db_references=True,
        no_db_references_check=lambda: True,
        secret_factory=lambda size: FIRST_SECRET if size == 32 else b"",
    )


def _temporary_artifacts(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.new-*"))


def test_fresh_init_is_atomic_0600_strict_and_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    assert _initialize(path) == "narration-local-2026-08"

    metadata = path.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1
    assert _temporary_artifacts(path) == []
    keyring = load_digest_keyring(path)
    assert keyring.active_key_id == "narration-local-2026-08"
    assert keyring.active.secret == FIRST_SECRET
    assert keyring.active.status == "active"
    before = path.read_bytes()
    before_identity = (metadata.st_dev, metadata.st_ino)

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.initialize_digest_keyring(
            path,
            "narration-local-replacement",
            fresh_install=True,
            assert_no_db_references=True,
            no_db_references_check=lambda: True,
            secret_factory=lambda size: SECOND_SECRET,
        )

    assert captured.value.code == "DIGEST_KEYRING_ALREADY_EXISTS"
    assert path.read_bytes() == before
    assert (path.stat().st_dev, path.stat().st_ino) == before_identity
    assert _temporary_artifacts(path) == []


@pytest.mark.parametrize(
    ("fresh_install", "assert_no_db_references"),
    [(False, False), (True, False), (False, True)],
)
def test_fresh_init_requires_both_explicit_attestations(
    tmp_path: Path,
    fresh_install: bool,
    assert_no_db_references: bool,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.initialize_digest_keyring(
            path,
            "narration-local-2026-08",
            fresh_install=fresh_install,
            assert_no_db_references=assert_no_db_references,
        )

    assert captured.value.code == "DIGEST_KEYRING_FRESH_INIT_ATTESTATION_REQUIRED"
    assert not path.exists()


def test_injected_reference_gate_blocks_init_and_hides_checker_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    with pytest.raises(operations.DigestKeyringOperationError) as references:
        operations.initialize_digest_keyring(
            path,
            "narration-local-2026-08",
            fresh_install=True,
            assert_no_db_references=True,
            no_db_references_check=lambda: False,
        )
    assert references.value.code == "DIGEST_KEYRING_DATABASE_REFERENCES_PRESENT"
    assert not path.exists()

    def failed_check() -> bool:
        raise RuntimeError(f"database secret at {path}")

    with pytest.raises(operations.DigestKeyringOperationError) as failed:
        operations.initialize_digest_keyring(
            path,
            "narration-local-2026-08",
            fresh_install=True,
            assert_no_db_references=True,
            no_db_references_check=failed_check,
        )
    assert failed.value.code == "DIGEST_KEYRING_REFERENCE_CHECK_FAILED"
    assert str(path) not in str(failed.value)
    assert not path.exists()


def test_init_refuses_existing_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "unrelated"
    target.write_text("keep", encoding="utf-8")
    path = tmp_path / "narration-digest-keyring.json"
    path.symlink_to(target)

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        _initialize(path)

    assert captured.value.code == "DIGEST_KEYRING_ALREADY_EXISTS"
    assert target.read_text(encoding="utf-8") == "keep"
    assert path.is_symlink()


def test_concurrent_operator_command_fails_closed_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    def busy(descriptor: int, operation: int) -> None:
        del descriptor, operation
        raise BlockingIOError("simulated private operator lock")

    monkeypatch.setattr(operations.fcntl, "flock", busy)
    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        _initialize(path)

    assert captured.value.code == "DIGEST_KEYRING_BUSY"
    assert not path.exists()
    assert _temporary_artifacts(path) == []


def test_rotation_retains_old_key_as_verify_only_and_publishes_one_active(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _initialize(path)
    old = load_digest_keyring(path)
    evidence = b"existing-private-evidence"
    old_digest = old.active.digest(evidence)

    result = operations.rotate_digest_keyring(
        path,
        "narration-local-2026-09",
        secret_factory=lambda size: SECOND_SECRET if size == 32 else b"",
    )

    assert result == "narration-local-2026-09"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_nlink == 1
    assert _temporary_artifacts(path) == []
    rotated = load_digest_keyring(path)
    assert rotated.active_key_id == "narration-local-2026-09"
    assert rotated.active.secret == SECOND_SECRET
    assert rotated.active.status == "active"
    historical = rotated.require("narration-local-2026-08")
    assert historical.secret == FIRST_SECRET
    assert historical.status == "verify_only"
    assert rotated.verify(historical.key_id, evidence, old_digest) is True
    with pytest.raises(DigestKeyringError) as verify_only:
        historical.digest(evidence)
    assert verify_only.value.code == "DIGEST_KEY_VERIFY_ONLY"


def test_rotation_never_initializes_a_missing_keyring(tmp_path: Path) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.rotate_digest_keyring(
            path,
            "narration-local-2026-09",
            secret_factory=lambda size: SECOND_SECRET,
        )

    assert captured.value.code == "DIGEST_KEYRING_MISSING"
    assert not path.exists()
    assert _temporary_artifacts(path) == []


@pytest.mark.parametrize("unsafe_mode", [0o400, 0o640, 0o666])
def test_rotation_rejects_unsafe_or_unexpected_existing_mode(
    tmp_path: Path,
    unsafe_mode: int,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _initialize(path)
    before = path.read_bytes()
    path.chmod(unsafe_mode)

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.rotate_digest_keyring(
            path,
            "narration-local-2026-09",
            secret_factory=lambda size: SECOND_SECRET,
        )

    assert captured.value.code == "DIGEST_KEYRING_FILE_INVALID"
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == unsafe_mode


def test_rotation_rejects_symlink_and_hardlink_without_replacement(tmp_path: Path) -> None:
    target = tmp_path / "target-keyring.json"
    _initialize(target)
    target_before = target.read_bytes()

    symlink = tmp_path / "symlink-keyring.json"
    symlink.symlink_to(target)
    with pytest.raises(operations.DigestKeyringOperationError) as symlink_error:
        operations.rotate_digest_keyring(
            symlink,
            "narration-local-2026-09",
            secret_factory=lambda size: SECOND_SECRET,
        )
    assert symlink_error.value.code == "DIGEST_KEYRING_FILE_INVALID"

    hardlink = tmp_path / "hardlink-keyring.json"
    os.link(target, hardlink)
    with pytest.raises(operations.DigestKeyringOperationError) as hardlink_error:
        operations.rotate_digest_keyring(
            hardlink,
            "narration-local-2026-09",
            secret_factory=lambda size: SECOND_SECRET,
        )
    assert hardlink_error.value.code == "DIGEST_KEYRING_FILE_INVALID"
    assert target.read_bytes() == target_before
    assert symlink.is_symlink()
    assert hardlink.exists()


def test_failed_atomic_replace_preserves_old_keyring_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _initialize(path)
    before = path.read_bytes()

    def fail_replace(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del args, kwargs
        raise OSError("simulated path-bearing replace failure")

    monkeypatch.setattr(operations.os, "replace", fail_replace)
    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.rotate_digest_keyring(
            path,
            "narration-local-2026-09",
            secret_factory=lambda size: SECOND_SECRET,
        )

    assert captured.value.code == "DIGEST_KEYRING_REPLACE_FAILED"
    assert path.read_bytes() == before
    assert load_digest_keyring(path).active_key_id == "narration-local-2026-08"
    assert _temporary_artifacts(path) == []


def test_failed_temporary_write_leaves_no_secret_or_temp_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    def fail_write(descriptor: int, payload: bytes) -> None:
        del descriptor, payload
        raise OSError(f"simulated private write failure at {path}")

    monkeypatch.setattr(operations, "_write_all", fail_write)
    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        _initialize(path)

    assert captured.value.code == "DIGEST_KEYRING_WRITE_FAILED"
    assert str(path) not in str(captured.value)
    assert not path.exists()
    assert _temporary_artifacts(path) == []


def test_duplicate_rotation_key_id_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _initialize(path)
    before = path.read_bytes()

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.rotate_digest_keyring(
            path,
            "narration-local-2026-08",
            secret_factory=lambda size: SECOND_SECRET,
        )

    assert captured.value.code == "DIGEST_KEY_ID_ALREADY_EXISTS"
    assert path.read_bytes() == before


def test_rotation_refuses_to_drop_history_when_frozen_capacity_is_reached(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _initialize(path, key_id="narration-local-00")
    for index in range(1, 16):
        operations.rotate_digest_keyring(
            path,
            f"narration-local-{index:02d}",
            secret_factory=lambda size, marker=index: bytes([marker]) * size,
        )
    before = path.read_bytes()

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.rotate_digest_keyring(
            path,
            "narration-local-16",
            secret_factory=lambda size: b"z" * size,
        )

    assert captured.value.code == "DIGEST_KEYRING_CAPACITY_EXCEEDED"
    assert path.read_bytes() == before
    keyring = load_digest_keyring(path)
    assert len(keyring.keys) == 16
    assert keyring.active_key_id == "narration-local-15"


def test_rotation_reuses_frozen_loader_and_rejects_malformed_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _initialize(path)
    path.write_text('{"schema_version":"different/1"}', encoding="utf-8")
    path.chmod(0o600)
    before = path.read_bytes()

    with pytest.raises(operations.DigestKeyringOperationError) as captured:
        operations.rotate_digest_keyring(
            path,
            "narration-local-2026-09",
            secret_factory=lambda size: SECOND_SECRET,
        )

    assert captured.value.code == "DIGEST_KEYRING_INVALID"
    assert path.read_bytes() == before


def test_cli_output_contains_only_safe_status_code_and_key_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "private" / "narration-digest-keyring.json"
    path.parent.mkdir(mode=0o700)
    monkeypatch.setattr(operations.secrets, "token_bytes", lambda size: FIRST_SECRET)

    result = operations.main(
        [
            "init",
            "--path",
            str(path),
            "--key-id",
            "narration-local-2026-08",
            "--fresh-install",
            "--assert-no-db-references",
        ],
        no_db_references_check=lambda: True,
    )

    assert result == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "code": "DIGEST_KEYRING_CREATED",
        "key_id": "narration-local-2026-08",
    }
    assert str(path) not in output.out
    assert base64.b64encode(FIRST_SECRET).decode("ascii") not in output.out
    assert FIRST_SECRET.decode("ascii") not in output.out

    monkeypatch.setattr(operations.secrets, "token_bytes", lambda size: SECOND_SECRET)
    result = operations.main(
        [
            "rotate",
            "--path",
            str(path),
            "--key-id",
            "narration-local-2026-09",
        ],
    )
    assert result == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "code": "DIGEST_KEYRING_ROTATED",
        "key_id": "narration-local-2026-09",
    }
    assert str(path) not in output.out
    assert base64.b64encode(SECOND_SECRET).decode("ascii") not in output.out
    assert SECOND_SECRET.decode("ascii") not in output.out


def test_cli_failures_never_echo_path_secret_or_exception_detail(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "missing-secret-named-value"

    result = operations.main(
        [
            "rotate",
            "--path",
            str(path),
            "--key-id",
            "narration-local-2026-09",
        ],
    )

    assert result == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"code": "DIGEST_KEYRING_MISSING"}
    assert str(path) not in output.out
    assert "missing-secret-named-value" not in output.out

    result = operations.main(
        [
            "init",
            "--path",
            str(path),
            "--key-id",
            "narration-local-2026-08",
            "--unexpected-path-bearing-argument",
            str(path),
        ],
    )
    assert result == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"code": "DIGEST_KEYRING_ARGUMENTS_INVALID"}
    assert str(path) not in output.out


def test_weak_parent_is_rejected_without_creating_secret(tmp_path: Path) -> None:
    parent = tmp_path / "weak-parent"
    parent.mkdir(mode=0o700)
    parent.chmod(0o777)
    path = parent / "narration-digest-keyring.json"
    try:
        with pytest.raises(operations.DigestKeyringOperationError) as captured:
            _initialize(path)
        assert captured.value.code == "DIGEST_KEYRING_PARENT_INVALID"
        assert not path.exists()
    finally:
        parent.chmod(0o700)
