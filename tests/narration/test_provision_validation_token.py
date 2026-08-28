from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.tts import provision_validation_token as provisioner


TOKEN = "v" * 43


class _Port:
    def __init__(self, digest: str | None = None) -> None:
        self.digest = digest
        self.installs = 0
        self.destroyed = 0

    def current_digest(self) -> str | None:
        return self.digest

    def install_from_host_file(self, path: Path) -> None:
        self.installs += 1
        value = provisioner.read_private_host_token(path)
        self.digest = hashlib.sha256(value.encode("ascii")).hexdigest()

    def destroy(self) -> None:
        self.destroyed += 1
        self.digest = None


def _private_path(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path / "validation-token"


def test_provision_is_private_idempotent_and_never_returns_secret(
    tmp_path: Path,
) -> None:
    path = _private_path(tmp_path)
    port = _Port()

    created = provisioner.provision_token(
        path,
        port,
        token_factory=lambda: TOKEN,
    )
    repeated = provisioner.provision_token(
        path,
        port,
        token_factory=lambda: "w" * 43,
    )

    assert created == {
        "schema_version": 1,
        "status": "READY",
        "host_token_created": True,
        "container_token_ready": True,
        "secret_values_emitted": False,
    }
    assert repeated["host_token_created"] is False
    assert path.stat().st_mode & 0o777 == 0o600
    assert provisioner.read_private_host_token(path) == TOKEN
    assert port.installs == 1
    assert TOKEN not in repr(created) + repr(repeated)
    assert hashlib.sha256(TOKEN.encode("ascii")).hexdigest() not in repr(created)


def test_mismatch_fails_without_overwriting_either_copy(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    provisioner._atomic_create_host_token(path, TOKEN)
    mismatched = _Port(hashlib.sha256(b"different").hexdigest())

    with pytest.raises(
        provisioner.TokenProvisionError,
        match="CONTAINER_TOKEN_MISMATCH",
    ):
        provisioner.provision_token(path, mismatched)

    assert provisioner.read_private_host_token(path) == TOKEN
    assert mismatched.installs == 0


def test_verify_then_destroy_removes_only_exact_token_copies(tmp_path: Path) -> None:
    path = _private_path(tmp_path)
    port = _Port()
    provisioner.provision_token(path, port, token_factory=lambda: TOKEN)

    verified = provisioner.verify_token(path, port)
    destroyed = provisioner.destroy_token(path, port)

    assert verified["status"] == "READY"
    assert destroyed == {
        "schema_version": 1,
        "status": "DESTROYED",
        "host_token_present": False,
        "container_token_present": False,
        "secret_values_emitted": False,
    }
    assert not path.exists()
    assert port.destroyed == 1
    assert port.current_digest() is None


@pytest.mark.parametrize("failure", ("mismatch", "missing_container"))
def test_destroy_preserves_host_copy_when_identity_is_not_proven(
    tmp_path: Path,
    failure: str,
) -> None:
    path = _private_path(tmp_path)
    provisioner._atomic_create_host_token(path, TOKEN)
    digest = (
        hashlib.sha256(b"different").hexdigest()
        if failure == "mismatch"
        else None
    )
    port = _Port(digest)

    expected = (
        "CONTAINER_TOKEN_MISMATCH"
        if failure == "mismatch"
        else "TOKEN_COPIES_INCOMPLETE"
    )
    with pytest.raises(provisioner.TokenProvisionError, match=expected):
        provisioner.destroy_token(path, port)

    assert provisioner.read_private_host_token(path) == TOKEN
    assert port.destroyed == 0


def test_host_path_and_permissions_fail_closed(tmp_path: Path) -> None:
    private = _private_path(tmp_path)
    private.write_text(TOKEN, encoding="ascii")
    private.chmod(0o644)
    with pytest.raises(
        provisioner.TokenProvisionError,
        match="HOST_TOKEN_FILE_INVALID",
    ):
        provisioner.read_private_host_token(private)

    repository_path = provisioner.PROJECT_ROOT / ".forbidden-validation-token"
    with pytest.raises(
        provisioner.TokenProvisionError,
        match="HOST_TOKEN_PATH_INVALID",
    ):
        provisioner._validate_host_path(repository_path)


def test_destroy_requires_distinct_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _private_path(tmp_path)
    monkeypatch.setattr(provisioner, "DockerContainerTokenPort", _Port)

    status = provisioner.main(
        [
            "--mode",
            "destroy",
            "--host-token-file",
            str(path),
            "--confirm",
            provisioner.CONFIRMATION,
        ]
    )

    assert status == 2
    error = capsys.readouterr().err
    assert "CONFIRMATION_REQUIRED" in error
    assert TOKEN not in error
