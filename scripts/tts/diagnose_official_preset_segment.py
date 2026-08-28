#!/usr/bin/env python3
"""Inspect one real official-preset synthesis without retaining text or audio.

This operator-only helper is intended to run inside the existing TTS Sidecar
after the PawApp worker lease has been released.  The input is base64-encoded
UTF-8 on stdin.  Output contains only bounded audio metrics and hashes; the
WAV and decoded text never leave memory.
"""

from __future__ import annotations

from array import array
import argparse
import base64
from io import BytesIO
import hashlib
import http.client
import json
import math
from pathlib import Path
import re
import sys
import wave
from uuid import uuid4


PROTOCOL_VERSION = "moss-tts-sidecar/1.1"
BOOTSTRAP_TOKEN_PATH = Path("/run/moss-tts-secrets/moss_tts_sidecar_token")
MODEL_FINGERPRINT_SHA256 = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
LOCAL_SCOPE_FINGERPRINT = (
    "8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095"
)
CHINESE_OFFICIAL_PRESETS = (
    "onnx.Junhao",
    "onnx.Lingyu",
    "onnx.Xiaoyu",
    "onnx.Yuewen",
    "onnx.Zhiming",
    "onnx.Zixuan",
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_request(
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
        response_body = response.read()
        if response.status != expected_status:
            raise RuntimeError(f"{path} returned an unexpected HTTP status")
        result = json.loads(response_body.decode("utf-8"))
        if type(result) is not dict:
            raise RuntimeError(f"{path} returned an invalid JSON object")
        return result
    finally:
        connection.close()


def _synthesize(payload: dict[str, object], worker_token: str) -> bytes:
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
            raise RuntimeError("synthesis returned an unexpected HTTP status")
        expected_sha256 = response.getheader("X-MOSS-Audio-SHA256")
        if expected_sha256 != hashlib.sha256(audio).hexdigest():
            raise RuntimeError("Sidecar audio digest evidence differs")
        return audio
    finally:
        connection.close()


def _metrics(audio: bytes) -> dict[str, object]:
    try:
        with wave.open(BytesIO(audio), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            frames = source.readframes(frame_count + 1)
    except (EOFError, ValueError, wave.Error) as error:
        raise RuntimeError("synthesis WAV is not readable") from error
    if sample_width != 2 or len(frames) != frame_count * channels * sample_width:
        raise RuntimeError("synthesis WAV PCM payload differs from its header")
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise RuntimeError("synthesis WAV is empty")
    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    clipped = sum(abs(value) >= 32767 for value in samples)

    def dbfs(value: float) -> float:
        return -120.0 if value <= 0 else max(
            -120.0, 20.0 * math.log10(value / 32768.0)
        )

    return {
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "byte_size": len(audio),
        "channels": channels,
        "clipped_fraction": round(clipped / len(samples), 9),
        "duration_ms": round(frame_count * 1000 / sample_rate),
        "frame_count": frame_count,
        "peak_dbfs": round(dbfs(float(peak)), 6),
        "rms_dbfs": round(dbfs(rms), 6),
        "sample_rate_hz": sample_rate,
        "sample_width_bytes": sample_width,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", choices=CHINESE_OFFICIAL_PRESETS, required=True)
    args = parser.parse_args()
    encoded = "".join(sys.stdin.read().split())
    try:
        text = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError("stdin is not canonical base64 UTF-8") from error
    if not text or len(text) > 4_000 or "\x00" in text:
        raise RuntimeError("diagnostic text is outside the Sidecar bounds")
    token = BOOTSTRAP_TOKEN_PATH.read_text(encoding="ascii")
    if re.fullmatch(r"[\x21-\x7e]{32,256}", token) is None:
        raise RuntimeError("bootstrap token file is invalid")

    worker_token = ""
    try:
        acquired = _json_request(
            "/v1/lease/acquire",
            {"request_id": str(uuid4())},
            token_header="X-MOSS-Sidecar-Token",
            token=token,
            expected_status=200,
        )
        worker_token_value = acquired.get("worker_token")
        if type(worker_token_value) is not str:
            raise RuntimeError("lease response omitted the worker token")
        worker_token = worker_token_value
        _json_request(
            "/v1/warmup",
            {"request_id": str(uuid4())},
            token_header="X-MOSS-Worker-Token",
            token=worker_token,
            expected_status=200,
        )
        audio = _synthesize(
            {
                "max_new_frames": 375,
                "request_id": str(uuid4()),
                "requested_model_fingerprint_sha256": MODEL_FINGERPRINT_SHA256,
                "sample_mode": "fixed",
                "scope_fingerprint": LOCAL_SCOPE_FINGERPRINT,
                "seed": 1234,
                "text": text,
                "voice": args.voice,
            },
            worker_token,
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "text_chars": len(text),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "voice": args.voice,
                    "decode": {
                        "seed": 1234,
                        "sample_mode": "fixed",
                        "max_new_frames": 375,
                    },
                    "audio": _metrics(audio),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    finally:
        if worker_token:
            try:
                _json_request(
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
