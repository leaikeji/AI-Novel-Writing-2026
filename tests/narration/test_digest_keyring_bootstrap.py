from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import stat

import pytest

from backend.narration.digest_keyring import load_digest_keyring
from scripts.tts import bootstrap_digest_keyring as bootstrap
from scripts.tts import manage_digest_keyring as operations


KEY_ID = "narration-local-2026-08"


def _guard(no_references: bool):  # type: ignore[no-untyped-def]
    @contextmanager
    def guarded():  # type: ignore[no-untyped-def]
        yield no_references

    return guarded


def _existing_keyring(path: Path) -> None:
    operations.initialize_digest_keyring(
        path,
        KEY_ID,
        fresh_install=True,
        assert_no_db_references=True,
        no_db_references_check=lambda: True,
        secret_factory=lambda size: b"x" * size,
    )


def test_fresh_bootstrap_requires_automatic_zero_reference_proof(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    with pytest.raises(bootstrap.DigestKeyringBootstrapError) as captured:
        bootstrap.bootstrap_digest_keyring(
            path,
            key_id=KEY_ID,
            fresh_install=True,
            reference_guard=_guard(False),
        )

    assert captured.value.code == "DIGEST_KEYRING_DATABASE_REFERENCES_PRESENT"
    assert not path.exists()


def test_fresh_bootstrap_creates_only_after_zero_reference_proof(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    result = bootstrap.bootstrap_digest_keyring(
        path,
        key_id=KEY_ID,
        fresh_install=True,
        reference_guard=_guard(True),
    )

    assert result == ("DIGEST_KEYRING_CREATED", KEY_ID)
    assert load_digest_keyring(path).active_key_id == KEY_ID


def test_fresh_bootstrap_creates_only_one_private_parent_directory(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "ai-novel-world-2026"
    path = parent / "narration-digest-keyring.json"

    result = bootstrap.bootstrap_digest_keyring(
        path,
        key_id=KEY_ID,
        fresh_install=True,
        reference_guard=_guard(True),
    )

    assert result == ("DIGEST_KEYRING_CREATED", KEY_ID)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700


def test_missing_keyring_without_fresh_authority_never_creates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"

    with pytest.raises(bootstrap.DigestKeyringBootstrapError) as captured:
        bootstrap.bootstrap_digest_keyring(
            path,
            key_id=None,
            fresh_install=False,
            reference_guard=_guard(True),
        )

    assert captured.value.code == "DIGEST_KEYRING_MISSING"
    assert not path.exists()


def test_existing_keyring_with_historical_references_is_validation_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _existing_keyring(path)
    before = path.read_bytes()

    def forbidden_initialize(*args: object, **kwargs: object) -> str:
        del args, kwargs
        raise AssertionError("existing keyring must never be initialized or replaced")

    monkeypatch.setattr(bootstrap, "initialize_digest_keyring", forbidden_initialize)

    result = bootstrap.bootstrap_digest_keyring(
        path,
        key_id="ignored-new-key",
        fresh_install=True,
        reference_guard=_guard(False),
    )

    assert result == ("DIGEST_KEYRING_VALID", KEY_ID)
    assert path.read_bytes() == before


def test_existing_invalid_keyring_is_never_repaired(tmp_path: Path) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    path.write_text("not-a-keyring", encoding="utf-8")
    path.chmod(0o600)
    before = path.read_bytes()

    with pytest.raises(bootstrap.DigestKeyringBootstrapError) as captured:
        bootstrap.bootstrap_digest_keyring(
            path,
            key_id=KEY_ID,
            fresh_install=True,
            reference_guard=_guard(True),
        )

    assert captured.value.code == "DIGEST_KEYRING_INVALID"
    assert path.read_bytes() == before


def test_existing_keyring_with_unsafe_mode_is_never_accepted_or_repaired(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _existing_keyring(path)
    before = path.read_bytes()
    path.chmod(0o640)

    with pytest.raises(bootstrap.DigestKeyringBootstrapError) as captured:
        bootstrap.bootstrap_digest_keyring(
            path,
            key_id=None,
            fresh_install=False,
            reference_guard=_guard(False),
        )

    assert captured.value.code == "DIGEST_KEYRING_FILE_INVALID"
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


class _FakeConnection:
    def __init__(self, *, revision: str, reference_count: int) -> None:
        self.revision = revision
        self.reference_count = reference_count
        self.events: list[str] = []

    def scalars(self, statement: object) -> tuple[str, ...]:
        self.events.append(str(statement))
        return (self.revision,)

    def execute(self, statement: object) -> None:
        self.events.append(str(statement))

    def scalar(self, statement: object) -> int:
        self.events.append(str(statement))
        return self.reference_count


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def begin(self):  # type: ignore[no-untyped-def]
        yield self.connection


def test_database_guard_checks_exact_head_then_locks_before_counting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(
        revision=bootstrap.EXPECTED_ALEMBIC_HEAD,
        reference_count=0,
    )
    monkeypatch.setattr(bootstrap, "get_engine", lambda: _FakeEngine(connection))

    with bootstrap.database_reference_guard() as no_references:
        assert no_references is True

    assert connection.events == [
        "SELECT version_num FROM alembic_version",
        bootstrap._LOCK_REFERENCES_SQL,
        bootstrap._COUNT_REFERENCES_SQL,
    ]


def test_database_guard_fails_closed_before_table_access_on_wrong_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(revision="20260827_0019", reference_count=0)
    monkeypatch.setattr(bootstrap, "get_engine", lambda: _FakeEngine(connection))

    with pytest.raises(bootstrap.DigestKeyringBootstrapError) as captured:
        with bootstrap.database_reference_guard():
            pass

    assert captured.value.code == "DIGEST_KEYRING_SCHEMA_NOT_READY"
    assert connection.events == ["SELECT version_num FROM alembic_version"]


def test_main_returns_only_stable_code_on_internal_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    leaked = "postgresql://user:secret@example.invalid/private"

    def fail(*args: object, **kwargs: object) -> tuple[str, str]:
        del args, kwargs
        raise RuntimeError(leaked)

    monkeypatch.setattr(bootstrap, "bootstrap_digest_keyring", fail)

    assert bootstrap.main(["--path", "/safe/absolute/keyring.json"]) == 2
    output = capsys.readouterr().out
    assert output == '{"code":"DIGEST_KEYRING_BOOTSTRAP_FAILED"}\n'
    assert leaked not in output
