"""Opaque, versioned snapshot and pagination tokens.

The payload is intentionally an implementation detail.  It is validated on
every request and the snapshot version is always compared with the scoped
``Novel`` row; clients must never infer fields from the encoded value.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Mapping
from uuid import UUID


SNAPSHOT_SCHEMA = "ledger-snapshot/1"
CURSOR_SCHEMA = "story-ledger-cursor/1"


class LedgerTokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    novel_id: UUID
    story_ledger_version: int


@dataclass(frozen=True, slots=True)
class CursorIdentity:
    snapshot_token: str
    filter_sha256: str
    created_at: datetime
    fact_id: UUID


def _encode(payload: Mapping[str, object]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> dict[str, Any]:
    try:
        if not value or len(value) > 2_048:
            raise ValueError
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        raise LedgerTokenError("token is invalid") from error


def encode_snapshot(novel_id: UUID, story_ledger_version: int) -> str:
    if story_ledger_version < 1:
        raise ValueError("story_ledger_version must be positive")
    return _encode(
        {
            "schema": SNAPSHOT_SCHEMA,
            "novel_id": str(novel_id),
            "story_ledger_version": story_ledger_version,
        }
    )


def decode_snapshot(value: str) -> SnapshotIdentity:
    payload = _decode(value)
    if set(payload) != {"schema", "novel_id", "story_ledger_version"}:
        raise LedgerTokenError("snapshot token shape is invalid")
    try:
        if payload["schema"] != SNAPSHOT_SCHEMA:
            raise ValueError
        novel_id = UUID(str(payload["novel_id"]))
        version = int(payload["story_ledger_version"])
        if version < 1 or isinstance(payload["story_ledger_version"], bool):
            raise ValueError
    except (TypeError, ValueError) as error:
        raise LedgerTokenError("snapshot token value is invalid") from error
    return SnapshotIdentity(novel_id=novel_id, story_ledger_version=version)


def encode_cursor(
    *,
    snapshot_token: str,
    filter_sha256: str,
    created_at: datetime,
    fact_id: UUID,
) -> str:
    normalized = _utc(created_at)
    if len(filter_sha256) != 64:
        raise ValueError("filter_sha256 must be a SHA-256 digest")
    return _encode(
        {
            "schema": CURSOR_SCHEMA,
            "snapshot_token": snapshot_token,
            "filter_sha256": filter_sha256,
            "created_at": normalized.isoformat(timespec="microseconds"),
            "fact_id": str(fact_id),
        }
    )


def decode_cursor(value: str) -> CursorIdentity:
    payload = _decode(value)
    if set(payload) != {
        "schema",
        "snapshot_token",
        "filter_sha256",
        "created_at",
        "fact_id",
    }:
        raise LedgerTokenError("cursor shape is invalid")
    try:
        if payload["schema"] != CURSOR_SCHEMA:
            raise ValueError
        snapshot_token = str(payload["snapshot_token"])
        decode_snapshot(snapshot_token)
        filter_sha256 = str(payload["filter_sha256"])
        if len(filter_sha256) != 64:
            raise ValueError
        int(filter_sha256, 16)
        created_at = _utc(datetime.fromisoformat(str(payload["created_at"])))
        fact_id = UUID(str(payload["fact_id"]))
    except (TypeError, ValueError, LedgerTokenError) as error:
        raise LedgerTokenError("cursor value is invalid") from error
    return CursorIdentity(
        snapshot_token=snapshot_token,
        filter_sha256=filter_sha256,
        created_at=created_at,
        fact_id=fact_id,
    )


def filter_sha256(payload: Mapping[str, object]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CURSOR_SCHEMA",
    "LedgerTokenError",
    "SNAPSHOT_SCHEMA",
    "CursorIdentity",
    "SnapshotIdentity",
    "decode_cursor",
    "decode_snapshot",
    "encode_cursor",
    "encode_snapshot",
    "filter_sha256",
]
