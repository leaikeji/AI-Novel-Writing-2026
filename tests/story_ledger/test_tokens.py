from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.story_ledger.tokens import (
    LedgerTokenError,
    decode_cursor,
    decode_snapshot,
    encode_cursor,
    encode_snapshot,
    filter_sha256,
)


def test_snapshot_token_round_trips_exact_novel_and_version() -> None:
    novel_id = uuid4()
    token = encode_snapshot(novel_id, 17)

    identity = decode_snapshot(token)

    assert identity.novel_id == novel_id
    assert identity.story_ledger_version == 17
    assert "ledger-snapshot/1" not in token


def test_cursor_binds_snapshot_filter_and_stable_sort_key() -> None:
    novel_id = uuid4()
    fact_id = uuid4()
    snapshot = encode_snapshot(novel_id, 3)
    digest = filter_sha256({"schema": "story-ledger-filter/1", "health": "ok"})
    created_at = datetime(2026, 9, 2, 1, 2, 3, 456789, tzinfo=UTC)

    cursor = encode_cursor(
        snapshot_token=snapshot,
        filter_sha256=digest,
        created_at=created_at,
        fact_id=fact_id,
    )
    decoded = decode_cursor(cursor)

    assert decoded.snapshot_token == snapshot
    assert decoded.filter_sha256 == digest
    assert decoded.created_at == created_at
    assert decoded.fact_id == fact_id


@pytest.mark.parametrize("value", ["", "not-base64", "e30", "W10"])
def test_malformed_tokens_fail_closed(value: str) -> None:
    with pytest.raises(LedgerTokenError):
        decode_snapshot(value)
    with pytest.raises(LedgerTokenError):
        decode_cursor(value)


def test_filter_digest_is_order_independent_for_mapping_keys() -> None:
    assert filter_sha256({"a": 1, "b": 2}) == filter_sha256({"b": 2, "a": 1})
