#!/usr/bin/env python3
"""Deterministic fake runner for T0-C driver tests only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import struct
import sys
import tempfile
import wave


REQUEST_SCHEMA = "moss-tts-quality-runner-request/1.0"
RESPONSE_SCHEMA = "moss-tts-quality-runner-response/1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def write_fixture_wav(path: Path, *, text_hash: str, seed: int) -> None:
    sample_rate = 48_000
    channels = 2
    duration_seconds = 0.24 + (int(text_hash[:2], 16) % 9) / 100.0
    frame_count = int(sample_rate * duration_seconds)
    frequency = 180 + ((int(text_hash[2:6], 16) + seed) % 260)
    amplitude = 2_400
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        for frame_index in range(frame_count):
            sample = int(amplitude * math.sin(2 * math.pi * frequency * frame_index / sample_rate))
            target.writeframesraw(struct.pack("<hh", sample, sample))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if request.get("schema_version") != REQUEST_SCHEMA:
            raise ValueError("unsupported request schema")
        text = request.get("text")
        text_hash = request.get("text_sha256")
        if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != text_hash:
            raise ValueError("fixture text hash mismatch")
        if request.get("streaming") is not True or request.get("enable_wetext") is not False:
            raise ValueError("unexpected quality runner parameters")
        output = Path(str(request["output_wav"]))
        write_fixture_wav(output, text_hash=text_hash, seed=int(request["seed"]))
        response: dict[str, object] = {
            "schema_version": RESPONSE_SCHEMA,
            "status": "passed",
            "adapter_kind": "fixture-fake",
            "first_packet_ms": 0.5,
            "peak_rss_bytes": peak_rss_bytes(),
            "peak_accelerator_bytes": None,
            "output_sha256": sha256_file(output),
            "error": None,
        }
        atomic_json(args.response, response)
        return 0
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        atomic_json(
            args.response,
            {
                "schema_version": RESPONSE_SCHEMA,
                "status": "failed",
                "adapter_kind": "fixture-fake",
                "first_packet_ms": None,
                "peak_rss_bytes": peak_rss_bytes(),
                "peak_accelerator_bytes": None,
                "output_sha256": None,
                "error": {
                    "category": "fixture",
                    "code": "invalid_fake_request",
                    "message_redacted": "fake runner request was invalid",
                },
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
