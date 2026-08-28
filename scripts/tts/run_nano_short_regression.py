#!/usr/bin/env python3
"""Run the bounded Zhiming short-attribution corpus against real Nano.

This operator-only helper is executed inside the private Sidecar container.
It reads the project-owned fixture, keeps runtime WAV files outside Git, and
writes a validator-compatible metadata result without logging tokens or text.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import wave
from uuid import uuid4


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts.tts.nano_short_regression import (
    MODEL_FINGERPRINT_SHA256,
    RESULT_SCHEMA_VERSION,
    load_regression_fixture,
    validate_regression_result,
)


PROTOCOL_VERSION = "moss-tts-sidecar/1.1"
BOOTSTRAP_TOKEN_PATH = Path("/run/moss-tts-secrets/moss_tts_sidecar_token")
LOCAL_SCOPE_FINGERPRINT = (
    "8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095"
)
SHORT_ATTRIBUTION_RE = re.compile(
    r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{1,8}说道[\uff1a:\u3002]$"
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _request_json(
    path: str,
    payload: dict[str, object],
    *,
    token_header: str,
    token: str,
    expected_status: int,
) -> dict[str, object]:
    body = _canonical_json(payload)
    connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=180)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                token_header: token,
                "X-MOSS-Protocol-Version": PROTOCOL_VERSION,
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        raw = response.read()
        if response.status != expected_status:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"{path} response is not an object")
        return value
    finally:
        connection.close()


def _request_wav(payload: dict[str, object], *, worker_token: str) -> bytes:
    body = _canonical_json(payload)
    connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=180)
    try:
        connection.request(
            "POST",
            "/v1/synthesize",
            body=body,
            headers={
                "X-MOSS-Worker-Token": worker_token,
                "X-MOSS-Protocol-Version": PROTOCOL_VERSION,
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        audio = response.read()
        if response.status != 200:
            raise RuntimeError(f"synthesis returned HTTP {response.status}")
        digest = hashlib.sha256(audio).hexdigest()
        if response.getheader("X-MOSS-Audio-SHA256") != digest:
            raise RuntimeError("Sidecar audio hash evidence mismatch")
        return audio
    finally:
        connection.close()


def _duration_ms(wav_bytes: bytes) -> int:
    with wave.open(BytesIO(wav_bytes), "rb") as source:
        if (
            source.getnchannels(),
            source.getsampwidth(),
            source.getframerate(),
        ) != (2, 2, 48_000):
            raise RuntimeError("Sidecar WAV format changed")
        return round(source.getnframes() * 1000 / source.getframerate())


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    fixture_path = arguments.fixture.resolve(strict=True)
    output_dir = arguments.output_dir
    if not output_dir.is_absolute() or output_dir.exists():
        raise RuntimeError("output directory must be absolute and new")
    output_dir.mkdir(mode=0o700, parents=True)
    os.chmod(output_dir, 0o700)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(mode=0o700)
    fixture = load_regression_fixture(fixture_path)
    if fixture.allowed_strategies != ("fixed_seed_1",):
        raise RuntimeError("fixture strategy is not frozen to fixed_seed_1")

    bootstrap_token = BOOTSTRAP_TOKEN_PATH.read_text(encoding="ascii")
    if re.fullmatch(r"[\x21-\x7e]{32,256}", bootstrap_token) is None:
        raise RuntimeError("bootstrap token file is invalid")
    worker_token = ""
    try:
        acquired = _request_json(
            "/v1/lease/acquire",
            {"request_id": str(uuid4())},
            token_header="X-MOSS-Sidecar-Token",
            token=bootstrap_token,
            expected_status=200,
        )
        token_value = acquired.get("worker_token")
        if not isinstance(token_value, str):
            raise RuntimeError("lease response omitted worker token")
        worker_token = token_value
        _request_json(
            "/v1/warmup",
            {"request_id": str(uuid4())},
            token_header="X-MOSS-Worker-Token",
            token=worker_token,
            expected_status=200,
        )

        rows: list[dict[str, object]] = []
        for case in fixture.cases:
            _request_json(
                "/v1/lease/renew",
                {"request_id": str(uuid4())},
                token_header="X-MOSS-Worker-Token",
                token=worker_token,
                expected_status=200,
            )
            short_attribution = SHORT_ATTRIBUTION_RE.fullmatch(case.text) is not None
            audio = _request_wav(
                {
                    "max_new_frames": 375,
                    "request_id": str(uuid4()),
                    "requested_model_fingerprint_sha256": (
                        MODEL_FINGERPRINT_SHA256
                    ),
                    "sample_mode": "fixed",
                    "scope_fingerprint": LOCAL_SCOPE_FINGERPRINT,
                    "seed": 1 if short_attribution else 0,
                    "text": case.text,
                    "voice": fixture.preset_id,
                },
                worker_token=worker_token,
            )
            audio_path = audio_dir / f"{case.case_id}.wav"
            audio_path.write_bytes(audio)
            audio_path.chmod(0o600)
            rows.append(
                {
                    "case_id": case.case_id,
                    "text_sha256": case.text_sha256,
                    "occurrence_count": case.occurrence_count,
                    "duration_ms": _duration_ms(audio),
                    "audio_sha256": hashlib.sha256(audio).hexdigest(),
                }
            )

        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "fixture_id": fixture.fixture_id,
            "fixture_sha256": fixture.fixture_sha256,
            "source_chapter_fixture_sha256": (
                fixture.source_chapter_fixture_sha256
            ),
            "model_fingerprint_sha256": MODEL_FINGERPRINT_SHA256,
            "preset_id": fixture.preset_id,
            "language": fixture.language,
            "speaker_kind": fixture.speaker_kind,
            "segment_kind": fixture.segment_kind,
            "policy_version": fixture.policy_version,
            "selected_strategy": "fixed_seed_1",
            "cases": rows,
        }
        audio_hashes = validate_regression_result(
            fixture,
            result,
            selected_strategy="fixed_seed_1",
        )
        result_bytes = _canonical_json(result) + b"\n"
        result_path = output_dir / "result.json"
        result_path.write_bytes(result_bytes)
        result_path.chmod(0o600)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "case_count": len(rows),
                    "distinct_audio_count": len(audio_hashes),
                    "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        if worker_token:
            try:
                _request_json(
                    "/v1/lease/release",
                    {"request_id": str(uuid4())},
                    token_header="X-MOSS-Worker-Token",
                    token=worker_token,
                    expected_status=202,
                )
            except Exception:
                pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error": type(error).__name__,
                    "reason": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
