from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from backend.narration.digest_keyring import (
    DIGEST_KEYRING_SCHEMA_VERSION,
    DigestKeyring,
    DigestKeyringError,
    HmacDigestKey,
    load_digest_keyring,
    private_text_digest,
)


ACTIVE_SECRET = b"a" * 32
OLD_SECRET = b"b" * 32


def _payload() -> dict[str, object]:
    return {
        "schema_version": DIGEST_KEYRING_SCHEMA_VERSION,
        "active_key_id": "tts-local-2026-08",
        "keys": [
            {
                "key_id": "tts-local-2026-08",
                "status": "active",
                "secret_base64": base64.b64encode(ACTIVE_SECRET).decode("ascii"),
            },
            {
                "key_id": "tts-local-2026-07",
                "status": "verify_only",
                "secret_base64": base64.b64encode(OLD_SECRET).decode("ascii"),
            },
        ],
    }


def _write(path: Path, payload: object, *, mode: int = 0o600) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    path.chmod(mode)


def test_loads_one_active_and_retains_verify_only_keys(tmp_path: Path) -> None:
    path = tmp_path / "narration-digest-keyring.json"
    _write(path, _payload())

    keyring = load_digest_keyring(path)

    assert keyring.active_key_id == "tts-local-2026-08"
    assert keyring.active.secret == ACTIVE_SECRET
    assert keyring.require("tts-local-2026-07").secret == OLD_SECRET
    assert "secret" not in repr(keyring).lower()
    assert ACTIVE_SECRET.decode("ascii") not in repr(keyring)

    payload = b"private narration evidence"
    key_id, digest = keyring.digest_active(payload)
    assert key_id == keyring.active_key_id
    assert keyring.verify(key_id, payload, digest) is True
    assert keyring.verify(key_id, payload + b"!", digest) is False
    historical = keyring.require("tts-local-2026-07")
    historical_digest = historical.digest_for_verification(payload)
    assert keyring.verify(historical.key_id, payload, historical_digest) is True
    with pytest.raises(DigestKeyringError) as verify_only_error:
        historical.digest(payload)
    assert verify_only_error.value.code == "DIGEST_KEY_VERIFY_ONLY"


def test_private_text_digest_is_domain_separated_and_not_naked_sha() -> None:
    key = HmacDigestKey("tts-local-test", ACTIVE_SECRET)

    render = private_text_digest(
        key,
        purpose="render-spoken-text",
        text="你终于来了。",
    )
    audit = private_text_digest(
        key,
        purpose="model-input-audit",
        text="你终于来了。",
    )

    assert len(render) == len(audit) == 64
    assert render != audit
    assert render == private_text_digest(
        key,
        purpose="render-spoken-text",
        text="你终于来了。",
    )


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda payload: payload.update(schema_version="unknown/1"), "DIGEST_KEYRING_VERSION_UNSUPPORTED"),
        (lambda payload: payload.update(active_key_id="missing"), "DIGEST_KEYRING_INVALID"),
        (
            lambda payload: payload["keys"][0].update(status="verify_only"),  # type: ignore[index,union-attr]
            "DIGEST_KEYRING_INVALID",
        ),
        (
            lambda payload: payload["keys"][0].update(secret_base64="not-base64"),  # type: ignore[index,union-attr]
            "DIGEST_KEYRING_INVALID",
        ),
    ],
)
def test_malformed_keyrings_fail_closed(
    tmp_path: Path,
    mutate,  # type: ignore[no-untyped-def]
    expected_code: str,
) -> None:
    payload = _payload()
    mutate(payload)
    path = tmp_path / "narration-digest-keyring.json"
    _write(path, payload)

    with pytest.raises(DigestKeyringError) as captured:
        load_digest_keyring(path)

    assert captured.value.code == expected_code
    assert ACTIVE_SECRET.decode("ascii") not in str(captured.value)


def test_missing_weak_permission_symlink_and_duplicate_fields_fail_closed(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(DigestKeyringError, match="unavailable") as missing_error:
        load_digest_keyring(missing)
    assert missing_error.value.code == "DIGEST_KEYRING_UNAVAILABLE"
    assert missing_error.value.__cause__ is None
    assert str(missing) not in str(missing_error.value)

    weak = tmp_path / "weak.json"
    _write(weak, _payload(), mode=0o644)
    with pytest.raises(DigestKeyringError) as weak_error:
        load_digest_keyring(weak)
    assert weak_error.value.code == "DIGEST_KEYRING_FILE_INVALID"

    target = tmp_path / "target.json"
    _write(target, _payload())
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(DigestKeyringError) as symlink_error:
        load_digest_keyring(symlink)
    assert symlink_error.value.code == "DIGEST_KEYRING_UNAVAILABLE"

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"narration-hmac-keyring/1",'
        '"active_key_id":"first","active_key_id":"second","keys":[]}',
        encoding="utf-8",
    )
    duplicate.chmod(0o600)
    with pytest.raises(DigestKeyringError) as duplicate_error:
        load_digest_keyring(duplicate)
    assert duplicate_error.value.code == "DIGEST_KEYRING_INVALID"


def test_required_historical_key_missing_fails_closed() -> None:
    keyring = DigestKeyring(
        active_key_id="tts-local-test",
        keys={
            "tts-local-test": HmacDigestKey("tts-local-test", ACTIVE_SECRET),
        },
    )
    with pytest.raises(DigestKeyringError) as captured:
        keyring.require("tts-local-retired")
    assert captured.value.code == "DIGEST_KEY_UNAVAILABLE"
    assert "secret" not in str(captured.value).lower()
