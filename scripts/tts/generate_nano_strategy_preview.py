#!/usr/bin/env python3
"""Generate long previews for the bounded Zhiming short-cue policy.

This operator-only helper runs inside the private Sidecar container.  It uses
the official ``onnx.Zhiming`` preset for every segment, changes decoding only
for the short attribution cues, and emits no token or source text in logs.
"""

from __future__ import annotations

import hashlib
import http.client
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
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
OUTPUT_ROOT = Path("/tmp/nano-strategy-preview")
FFMPEG_PATH = Path("/opt/ffmpeg/bin/ffmpeg")
SEGMENTS = (
    (True, "林晚说道："),
    (False, "夜雨刚停，旧车站的铁棚还在滴水，远处的信号灯透过薄雾，映在空荡荡的站台上。"),
    (True, "沈川说道："),
    (False, "两个人沿着墙边缓慢前行，先核对门牌和路线，再检查脚下是否有新鲜的水迹与脚印。"),
    (True, "苏棠说道："),
    (False, "风从售票厅破旧的窗缝穿过，号码牌轻轻碰着墙面，清脆的响声在清晨显得格外清楚。"),
    (True, "欧阳澈说道："),
    (False, "他们没有急着推开仓库侧门，而是停在安全距离外，把已经确认的事实逐条记录下来。"),
    (True, "林晚说道。"),
    (True, "沈川说道。"),
)
STRATEGIES = {
    "A-fixed-seed1": ("fixed", 1),
}


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


def _pcm_frames(wav_bytes: bytes) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(BytesIO(wav_bytes), "rb") as source:
        parameters = (
            source.getnchannels(),
            source.getsampwidth(),
            source.getframerate(),
        )
        return parameters, source.readframes(source.getnframes())


def _duration_ms(wav_bytes: bytes) -> int:
    with wave.open(BytesIO(wav_bytes), "rb") as source:
        return round(source.getnframes() * 1000 / source.getframerate())


def _write_composite(path: Path, parts: list[bytes]) -> int:
    expected = (2, 2, 48_000)
    silence = b"\x00" * round(expected[2] * 0.18) * expected[0] * expected[1]
    frames: list[bytes] = []
    for index, part in enumerate(parts):
        parameters, pcm = _pcm_frames(part)
        if parameters != expected:
            raise RuntimeError("Sidecar WAV format changed")
        if index:
            frames.append(silence)
        frames.append(pcm)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(expected[0])
        output.setsampwidth(expected[1])
        output.setframerate(expected[2])
        output.writeframes(b"".join(frames))
    path.chmod(0o600)
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

        results: list[dict[str, object]] = []
        official_long_parts: list[bytes] = []
        for strategy_name, (cue_mode, cue_seed) in STRATEGIES.items():
            parts: list[bytes] = []
            segment_results: list[dict[str, object]] = []
            for index, (is_short_cue, text) in enumerate(SEGMENTS):
                _request_json(
                    "/v1/lease/renew",
                    {"request_id": str(uuid4())},
                    token_header="X-MOSS-Worker-Token",
                    token=worker_token,
                    expected_status=200,
                )
                sample_mode = cue_mode if is_short_cue else "fixed"
                seed = cue_seed if is_short_cue else 0
                audio = _request_wav(
                        {
                            "max_new_frames": 375,
                            "request_id": str(uuid4()),
                            "requested_model_fingerprint_sha256": (
                                MODEL_FINGERPRINT_SHA256
                            ),
                            "sample_mode": sample_mode,
                            "scope_fingerprint": LOCAL_SCOPE_FINGERPRINT,
                            "seed": seed,
                            "text": text,
                            "voice": "onnx.Zhiming",
                        },
                        worker_token=worker_token,
                    )
                parts.append(audio)
                if strategy_name == "A-fixed-seed1" and not is_short_cue:
                    official_long_parts.append(audio)
                segment_results.append(
                    {
                        "ordinal": index,
                        "is_short_cue": is_short_cue,
                        "text_sha256": hashlib.sha256(
                            text.encode("utf-8")
                        ).hexdigest(),
                        "sample_mode": sample_mode,
                        "seed": seed,
                        "duration_ms": _duration_ms(audio),
                    }
                )
            wav_path = OUTPUT_ROOT / f"{strategy_name}.wav"
            duration_ms = _write_composite(wav_path, parts)
            m4a_path = OUTPUT_ROOT / f"{strategy_name}.m4a"
            subprocess.run(
                (
                    str(FFMPEG_PATH),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    str(m4a_path),
                ),
                check=True,
                timeout=120,
            )
            m4a_path.chmod(0o600)
            results.append(
                {
                    "strategy": strategy_name,
                    "text_codepoints": sum(len(text) for _cue, text in SEGMENTS),
                    "segment_count": len(SEGMENTS),
                    "duration_ms": duration_ms,
                    "audio_sha256": hashlib.sha256(m4a_path.read_bytes()).hexdigest(),
                    "segments": segment_results,
                }
            )
        baseline_wav_path = OUTPUT_ROOT / "zhiming-project-fixed-seed0-long.wav"
        baseline_duration_ms = _write_composite(
            baseline_wav_path,
            official_long_parts,
        )
        baseline_m4a_path = OUTPUT_ROOT / "zhiming-project-fixed-seed0-long.m4a"
        subprocess.run(
            (
                str(FFMPEG_PATH),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(baseline_wav_path),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(baseline_m4a_path),
            ),
            check=True,
            timeout=120,
        )
        baseline_m4a_path.chmod(0o600)
        results.append(
            {
                "strategy": "zhiming-project-fixed-seed0-long",
                "text_codepoints": sum(
                    len(text) for is_short_cue, text in SEGMENTS if not is_short_cue
                ),
                "segment_count": len(official_long_parts),
                "duration_ms": baseline_duration_ms,
                "audio_sha256": hashlib.sha256(
                    baseline_m4a_path.read_bytes()
                ).hexdigest(),
            }
        )
        (OUTPUT_ROOT / "results.json").write_bytes(
            _canonical_json({"results": results}) + b"\n"
        )
        (OUTPUT_ROOT / "results.json").chmod(0o600)
        print(json.dumps({"status": "PASS", "strategy_count": len(results)}))
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
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
