"""Versioned HMAC keys for privacy-safe narration digests.

The keyring is an operator-owned secret file.  Importing this module performs
no filesystem access and never creates or rotates keys.  A missing, replaced,
weakly-permissioned, or malformed keyring always fails closed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Final, Literal, Mapping
import unicodedata

from .fingerprints import canonical_json_bytes


DIGEST_KEYRING_SCHEMA_VERSION: Final = "narration-hmac-keyring/1"
PRIVATE_TEXT_DIGEST_SCHEMA_VERSION: Final = "narration-private-text-digest/1"
MAX_KEYRING_BYTES: Final = 64 * 1024
MAX_KEY_COUNT: Final = 16

_DIGEST_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_PURPOSE = re.compile(r"^[a-z][a-z0-9._:-]{0,79}$")


class DigestKeyringError(RuntimeError):
    """Stable configuration failure whose message never includes secret data."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class HmacDigestKey:
    key_id: str
    secret: bytes = field(repr=False)
    status: Literal["active", "verify_only"] = "active"

    def __post_init__(self) -> None:
        if type(self.key_id) is not str or _DIGEST_KEY_ID.fullmatch(self.key_id) is None:
            raise ValueError("digest key id is invalid")
        if type(self.secret) is not bytes or not 32 <= len(self.secret) <= 128:
            raise ValueError(
                "HMAC digest key must contain at least 32 bytes and no more than 128 bytes"
            )
        if self.status not in {"active", "verify_only"}:
            raise ValueError("HMAC digest key status is invalid")

    def digest(self, value: bytes) -> str:
        """Create a new digest; verify-only keys cannot write new evidence."""

        if type(value) is not bytes:
            raise TypeError("HMAC input must be bytes")
        if self.status != "active":
            raise DigestKeyringError(
                "DIGEST_KEY_VERIFY_ONLY",
                "historical narration digest key cannot create new evidence",
            )
        return hmac.new(self.secret, value, hashlib.sha256).hexdigest()

    def digest_for_verification(self, value: bytes) -> str:
        if type(value) is not bytes:
            raise TypeError("HMAC input must be bytes")
        return hmac.new(self.secret, value, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class DigestKeyring:
    active_key_id: str
    keys: Mapping[str, HmacDigestKey] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.active_key_id) is not str
            or _DIGEST_KEY_ID.fullmatch(self.active_key_id) is None
        ):
            raise ValueError("active digest key id is invalid")
        if not isinstance(self.keys, Mapping) or not 1 <= len(self.keys) <= MAX_KEY_COUNT:
            raise ValueError("digest keyring must contain 1..16 keys")
        normalized: dict[str, HmacDigestKey] = {}
        for key_id, key in self.keys.items():
            if type(key_id) is not str or type(key) is not HmacDigestKey:
                raise ValueError("digest keyring entries are invalid")
            if key.key_id != key_id or key_id in normalized:
                raise ValueError("digest keyring identity is inconsistent")
            normalized[key_id] = key
        if self.active_key_id not in normalized:
            raise ValueError("active digest key is absent")
        active_ids = [
            key_id for key_id, key in normalized.items() if key.status == "active"
        ]
        if active_ids != [self.active_key_id]:
            raise ValueError("digest keyring must identify exactly one active key")
        object.__setattr__(self, "keys", MappingProxyType(normalized))

    @property
    def active(self) -> HmacDigestKey:
        return self.keys[self.active_key_id]

    def require(self, key_id: str) -> HmacDigestKey:
        """Resolve a key for historical verification, never implicit writing."""

        try:
            return self.keys[key_id]
        except (KeyError, TypeError) as error:
            raise DigestKeyringError(
                "DIGEST_KEY_UNAVAILABLE",
                "required narration digest key is unavailable",
            ) from None

    def digest_active(self, value: bytes) -> tuple[str, str]:
        """Create new evidence with exactly the configured active key."""

        return self.active_key_id, self.active.digest(value)

    def verify(self, key_id: str, value: bytes, expected_digest: str) -> bool:
        """Verify historical evidence without enabling historical writes."""

        if type(value) is not bytes or type(expected_digest) is not str:
            return False
        if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
            return False
        key = self.require(key_id)
        actual = key.digest_for_verification(value)
        return hmac.compare_digest(actual, expected_digest)


def private_text_digest(
    key: HmacDigestKey,
    *,
    purpose: str,
    text: str,
) -> str:
    """Return a domain-separated HMAC for private text, never a naked SHA."""

    if type(key) is not HmacDigestKey:
        raise TypeError("private text digest requires HmacDigestKey")
    if type(purpose) is not str or _PURPOSE.fullmatch(purpose) is None:
        raise ValueError("private text digest purpose is invalid")
    if type(text) is not str or unicodedata.normalize("NFC", text) != text:
        raise ValueError("private digest text must be an NFC string")
    return key.digest(
        canonical_json_bytes(
            {
                "schema_version": PRIVATE_TEXT_DIGEST_SCHEMA_VERSION,
                "purpose": purpose,
                "text": text,
            }
        )
    )


def historical_private_text_digest(
    key: HmacDigestKey,
    *,
    purpose: str,
    text: str,
) -> str:
    """Recompute immutable historical evidence with active or verify-only key."""

    if type(key) is not HmacDigestKey:
        raise TypeError("historical private text digest requires HmacDigestKey")
    if type(purpose) is not str or _PURPOSE.fullmatch(purpose) is None:
        raise ValueError("private text digest purpose is invalid")
    if type(text) is not str or unicodedata.normalize("NFC", text) != text:
        raise ValueError("private digest text must be an NFC string")
    return key.digest_for_verification(
        canonical_json_bytes(
            {
                "schema_version": PRIVATE_TEXT_DIGEST_SCHEMA_VERSION,
                "purpose": purpose,
                "text": text,
            }
        )
    )


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise DigestKeyringError(
                "DIGEST_KEYRING_INVALID",
                "narration digest keyring contains a duplicate field",
            )
        value[key] = item
    return value


def _read_secret_file(path: Path) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute():
        raise DigestKeyringError(
            "DIGEST_KEYRING_PATH_INVALID",
            "narration digest keyring path is invalid",
        )
    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if nofollow is None:
        raise DigestKeyringError(
            "DIGEST_KEYRING_OPEN_POLICY_UNAVAILABLE",
            "secure narration digest keyring open policy is unavailable",
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | cloexec | nofollow)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= MAX_KEYRING_BYTES
            or stat.S_IMODE(before.st_mode) & 0o077
        ):
            raise DigestKeyringError(
                "DIGEST_KEYRING_FILE_INVALID",
                "narration digest keyring secret file is invalid",
            )
        chunks: list[bytes] = []
        remaining = MAX_KEYRING_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or len(payload) != before.st_size
        ):
            raise DigestKeyringError(
                "DIGEST_KEYRING_CHANGED",
                "narration digest keyring changed while being read",
            )
        return payload
    except DigestKeyringError:
        raise
    except OSError as error:
        raise DigestKeyringError(
            "DIGEST_KEYRING_UNAVAILABLE",
            "narration digest keyring is unavailable",
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_digest_keyring(path: Path) -> DigestKeyring:
    """Load one strict keyring without exposing its path or key bytes."""

    raw = _read_secret_file(path)
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
        )
    except DigestKeyringError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DigestKeyringError(
            "DIGEST_KEYRING_INVALID",
            "narration digest keyring is not valid strict JSON",
        ) from None
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "active_key_id",
        "keys",
    }:
        raise DigestKeyringError(
            "DIGEST_KEYRING_INVALID",
            "narration digest keyring shape is invalid",
        )
    if payload["schema_version"] != DIGEST_KEYRING_SCHEMA_VERSION:
        raise DigestKeyringError(
            "DIGEST_KEYRING_VERSION_UNSUPPORTED",
            "narration digest keyring version is unsupported",
        )
    active_key_id = payload["active_key_id"]
    rows = payload["keys"]
    if type(active_key_id) is not str or type(rows) is not list:
        raise DigestKeyringError(
            "DIGEST_KEYRING_INVALID",
            "narration digest keyring values are invalid",
        )
    if not 1 <= len(rows) <= MAX_KEY_COUNT:
        raise DigestKeyringError(
            "DIGEST_KEYRING_INVALID",
            "narration digest keyring has an invalid key count",
        )
    keys: dict[str, HmacDigestKey] = {}
    active_rows = 0
    for row in rows:
        if type(row) is not dict or set(row) != {
            "key_id",
            "status",
            "secret_base64",
        }:
            raise DigestKeyringError(
                "DIGEST_KEYRING_INVALID",
                "narration digest keyring entry shape is invalid",
            )
        key_id = row["key_id"]
        status = row["status"]
        encoded = row["secret_base64"]
        if (
            type(key_id) is not str
            or _DIGEST_KEY_ID.fullmatch(key_id) is None
            or type(status) is not str
            or status not in {"active", "verify_only"}
            or type(encoded) is not str
            or not encoded
        ):
            raise DigestKeyringError(
                "DIGEST_KEYRING_INVALID",
                "narration digest keyring entry is invalid",
            )
        try:
            secret = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise DigestKeyringError(
                "DIGEST_KEYRING_INVALID",
                "narration digest keyring entry encoding is invalid",
            ) from None
        try:
            key = HmacDigestKey(key_id=key_id, secret=secret, status=status)
        except ValueError as error:
            raise DigestKeyringError(
                "DIGEST_KEYRING_INVALID",
                "narration digest keyring entry material is invalid",
            ) from None
        if key_id in keys:
            raise DigestKeyringError(
                "DIGEST_KEYRING_INVALID",
                "narration digest keyring contains duplicate key identities",
            )
        keys[key_id] = key
        if status == "active":
            active_rows += 1
            if key_id != active_key_id:
                raise DigestKeyringError(
                    "DIGEST_KEYRING_INVALID",
                    "narration digest keyring active marker is inconsistent",
                )
    if active_rows != 1 or active_key_id not in keys:
        raise DigestKeyringError(
            "DIGEST_KEYRING_INVALID",
            "narration digest keyring must contain exactly one active key",
        )
    try:
        return DigestKeyring(active_key_id=active_key_id, keys=keys)
    except ValueError as error:
        raise DigestKeyringError(
            "DIGEST_KEYRING_INVALID",
            "narration digest keyring identities are invalid",
        ) from None


__all__ = [
    "DIGEST_KEYRING_SCHEMA_VERSION",
    "DigestKeyring",
    "DigestKeyringError",
    "HmacDigestKey",
    "PRIVATE_TEXT_DIGEST_SCHEMA_VERSION",
    "historical_private_text_digest",
    "load_digest_keyring",
    "private_text_digest",
]
