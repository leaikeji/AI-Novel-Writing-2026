#!/usr/bin/env python3
"""Generate a bounded real-Nano corpus for short-text instability diagnosis.

This operator-only helper is intended to run inside an isolated Sidecar
container.  It never prints either the bootstrap secret or the worker lease
token and writes only WAV files plus non-secret hashes/durations.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import sys
import time
import wave
from pathlib import Path
from uuid import uuid4


PROTOCOL_VERSION = "moss-tts-sidecar/1.1"
BOOTSTRAP_TOKEN_PATH = Path("/run/moss-tts-secrets/moss_tts_sidecar_token")
MODEL_FINGERPRINT_SHA256 = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
LOCAL_SCOPE_FINGERPRINT = (
    "8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095"
)
OUTPUT_ROOT = Path("/tmp/nano-short-text-diagnostic")
CASES = (
    ("lin-original-seed0", "林晚说道：", 0, "fixed"),
    ("shen-original-seed0", "沈川说道：", 0, "fixed"),
    ("lin-original-seed1", "林晚说道：", 1, "fixed"),
    ("shen-original-seed1", "沈川说道：", 1, "fixed"),
    ("lin-original-seed42", "林晚说道：", 42, "fixed"),
    ("shen-original-seed42", "沈川说道：", 42, "fixed"),
    ("lin-period-seed0", "林晚说道。", 0, "fixed"),
    ("shen-period-seed0", "沈川说道。", 0, "fixed"),
    ("lin-original-greedy", "林晚说道：", 0, "greedy"),
    ("shen-original-greedy", "沈川说道：", 0, "greedy"),
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
) -> tuple[dict[str, object], dict[str, str]]:
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
        payload_bytes = response.read()
        if response.status != expected_status:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        row = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(row, dict):
            raise RuntimeError(f"{path} response is not an object")
        return row, {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()


def _request_wav(
    payload: dict[str, object],
    *,
    worker_token: str,
) -> tuple[bytes, dict[str, str]]:
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
        return audio, {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()


def _duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as source:
        return round(source.getnframes() * 1000 / source.getframerate())


def main() -> int:
    OUTPUT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(OUTPUT_ROOT, 0o700)
    bootstrap_token = BOOTSTRAP_TOKEN_PATH.read_text(encoding="ascii")
    if re.fullmatch(r"[\x21-\x7e]{32,256}", bootstrap_token) is None:
        raise RuntimeError("bootstrap token file is invalid")

    worker_token = ""
    try:
        acquire_id = str(uuid4())
        acquired, _headers = _request_json(
            "/v1/lease/acquire",
            {"request_id": acquire_id},
            token_header="X-MOSS-Sidecar-Token",
            token=bootstrap_token,
            expected_status=200,
        )
        worker_token_value = acquired.get("worker_token")
        if not isinstance(worker_token_value, str):
            raise RuntimeError("lease response omitted worker token")
        worker_token = worker_token_value

        warmup_id = str(uuid4())
        _request_json(
            "/v1/warmup",
            {"request_id": warmup_id},
            token_header="X-MOSS-Worker-Token",
            token=worker_token,
            expected_status=200,
        )

        results: list[dict[str, object]] = []
        for case_name, text, seed, sample_mode in CASES:
            request_id = str(uuid4())
            started = time.monotonic()
            audio, headers = _request_wav(
                {
                    "max_new_frames": 375,
                    "request_id": request_id,
                    "requested_model_fingerprint_sha256": MODEL_FINGERPRINT_SHA256,
                    "sample_mode": sample_mode,
                    "scope_fingerprint": LOCAL_SCOPE_FINGERPRINT,
                    "seed": seed,
                    "text": text,
                    "voice": "onnx.Zhiming",
                },
                worker_token=worker_token,
            )
            output_path = OUTPUT_ROOT / f"{case_name}.wav"
            output_path.write_bytes(audio)
            output_path.chmod(0o600)
            digest = hashlib.sha256(audio).hexdigest()
            if headers.get("x-moss-audio-sha256") != digest:
                raise RuntimeError("Sidecar audio hash evidence mismatch")
            results.append(
                {
                    "case": case_name,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "seed": seed,
                    "sample_mode": sample_mode,
                    "duration_ms": _duration_ms(output_path),
                    "wall_ms": round((time.monotonic() - started) * 1000),
                    "audio_sha256": digest,
                }
            )

        result_path = OUTPUT_ROOT / "results.json"
        result_path.write_bytes(_canonical_json({"cases": results}) + b"\n")
        result_path.chmod(0o600)
        print(json.dumps({"status": "PASS", "case_count": len(results)}))
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
                {"status": "FAILED", "error": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
