#!/usr/bin/env python3
"""One canonical digest chain shared by the T4-K host and collector.

This module is intentionally pure and public-data-only.  Callers remain
responsible for validating timestamps, sample counts, gaps, and runtime
semantics before invoking it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final, Mapping, Sequence


METRIC_CHAIN_DOMAIN: Final = b"moss-tts-t4k-sidecar-metric-chain/1\0"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_metric_summary_sha256(
    samples: Sequence[Mapping[str, object]],
) -> str:
    """Bind the complete validated raw metric sample projection."""

    return hashlib.sha256(_canonical_json(list(samples))).hexdigest()


def build_metric_sample_chain_sha256(
    *,
    request_fingerprint_sha256: str,
    window_started_at: str,
    window_ended_at: str,
    metrics_summary_sha256: str,
    samples: Sequence[Mapping[str, object]],
) -> str:
    """Hash an already validated request/window/sample projection."""

    seed: dict[str, object] = {
        "request_fingerprint_sha256": request_fingerprint_sha256,
        "window_started_at": window_started_at,
        "window_ended_at": window_ended_at,
        "metric_sample_count": len(samples),
        "metrics_summary_sha256": metrics_summary_sha256,
    }
    chain = hashlib.sha256(METRIC_CHAIN_DOMAIN + _canonical_json(seed)).digest()
    for sample in samples:
        chain = hashlib.sha256(
            METRIC_CHAIN_DOMAIN + chain + _canonical_json(sample)
        ).digest()
    return chain.hex()


__all__ = [
    "METRIC_CHAIN_DOMAIN",
    "build_metric_sample_chain_sha256",
    "build_metric_summary_sha256",
]
