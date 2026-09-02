"""Public, redacted projection of internal writing-retrieval evidence."""

from __future__ import annotations

from typing import Any, Mapping


RETRIEVAL_SUMMARY_SCHEMA_VERSION = "retrieval-summary/1"

_INDEX_REASONS = {
    "ready": "ready",
    "not_authorized": "not_authorized",
    "index_building": "building",
    "index_outdated": "outdated",
    "partial_failed": "partial_failed",
}


def retrieval_summary(
    snapshot: Mapping[str, Any] | None,
) -> dict[str, object]:
    if not snapshot:
        return {
            "schema_version": RETRIEVAL_SUMMARY_SCHEMA_VERSION,
            "outcome": "not_run",
            "mode": "context_only",
            "reason_code": "not_applicable",
            "hit_count": 0,
            "index_state": None,
        }
    raw_mode = str(snapshot.get("mode") or "context_only")
    mode = raw_mode if raw_mode in {"hybrid", "lexical_only", "context_only"} else "context_only"
    hits = snapshot.get("hits")
    hit_count = len(hits) if isinstance(hits, (list, tuple)) else 0
    raw_reason = str(
        snapshot.get("reason_code")
        or snapshot.get("degraded_reason")
        or ""
    ).strip()
    if mode == "hybrid":
        outcome = "used" if hit_count else "no_hit"
        reason_code = "ready" if hit_count else "no_hit"
    elif mode == "lexical_only":
        outcome = "degraded" if raw_reason else ("used" if hit_count else "no_hit")
        reason_code = raw_reason or ("ready" if hit_count else "no_hit")
    else:
        outcome = "degraded" if raw_reason else ("no_hit" if not hit_count else "used")
        reason_code = raw_reason or ("no_hit" if not hit_count else "ready")
    allowed_reasons = {
        "ready",
        "not_authorized",
        "index_building",
        "index_outdated",
        "partial_failed",
        "provider_unavailable",
        "no_hit",
        "not_applicable",
    }
    if reason_code not in allowed_reasons:
        reason_code = "provider_unavailable" if outcome == "degraded" else "not_applicable"
    return {
        "schema_version": RETRIEVAL_SUMMARY_SCHEMA_VERSION,
        "outcome": outcome,
        "mode": mode,
        "reason_code": reason_code,
        "hit_count": hit_count,
        "index_state": _INDEX_REASONS.get(reason_code),
    }
