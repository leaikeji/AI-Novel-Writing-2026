from __future__ import annotations

from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
from typing import Sequence
import wave

import pytest

from backend.narration.voice_media import (
    DEFAULT_REFERENCE_NORMALIZATION_POLICY,
    ReferenceAudioQualityRejected,
    ReferenceToolchainUnavailable,
    normalize_reference_audio,
)


def _pcm_wav(
    *,
    duration_ms: int = 4_000,
    amplitude: int = 3_200,
    clipped: bool = False,
) -> bytes:
    sample_rate = 48_000
    frames = round(sample_rate * duration_ms / 1000)
    payload = BytesIO()
    with wave.open(payload, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        chunks: list[bytes] = []
        for frame in range(frames):
            if clipped:
                value = 32_767
            else:
                value = round(amplitude * math.sin(2 * math.pi * 220 * frame / sample_rate))
            chunks.append(struct.pack("<hh", value, value))
        target.writeframes(b"".join(chunks))
    return payload.getvalue()


class _Runner:
    def __init__(self, normalized: bytes, *, source_duration_ms: int = 4_000) -> None:
        self.normalized = normalized
        self.source_duration_ms = source_duration_ms
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[bytes]:
        assert timeout_seconds == DEFAULT_REFERENCE_NORMALIZATION_POLICY.timeout_seconds
        command = tuple(argv)
        self.commands.append(command)
        if "-show_entries" in command:
            payload = {
                "streams": [
                    {
                        "codec_type": "audio",
                        "codec_name": "pcm_s16le",
                        "sample_rate": "48000",
                        "channels": 2,
                    }
                ],
                "format": {"duration": str(self.source_duration_ms / 1000)},
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload).encode(), b"")
        Path(command[-1]).write_bytes(self.normalized)
        return subprocess.CompletedProcess(command, 0, b"", b"")


def _normalize(payload: bytes, runner: _Runner):
    return normalize_reference_audio(
        payload,
        mime_type="audio/wav",
        declared_sha256=hashlib.sha256(payload).hexdigest(),
        ffmpeg_path=Path(sys.executable),
        ffprobe_path=Path(sys.executable),
        expected_ffmpeg_build_id=(
            DEFAULT_REFERENCE_NORMALIZATION_POLICY.ffmpeg_build_id
        ),
        runner=runner,
    )


def test_normalizes_to_frozen_pcm_and_returns_complete_evidence() -> None:
    source = _pcm_wav()
    runner = _Runner(source)

    result = _normalize(source, runner)

    assert result.normalized_bytes == source
    assert result.normalized_sha256 == hashlib.sha256(source).hexdigest()
    assert (result.sample_rate_hz, result.channels, result.sample_width_bytes) == (
        48_000,
        2,
        2,
    )
    assert result.duration_ms == 4_000
    assert result.quality.silent_fraction == 0.0
    assert result.quality.clipped_fraction == 0.0
    assert result.validation_evidence["checks"] == {
        "single_audio_stream": True,
        "fully_decoded": True,
        "duration_within_bounds": True,
        "silence_within_bounds": True,
        "clipping_within_bounds": True,
        "rms_within_bounds": True,
        "format_is_48khz_stereo_s16_wav": True,
    }
    ffmpeg = runner.commands[1]
    assert "-protocol_whitelist" in ffmpeg
    assert "file,pipe" in ffmpeg
    assert "-nostdin" in ffmpeg
    assert "pcm_s16le" in ffmpeg
    assert ffmpeg[ffmpeg.index("-t") + 1] == "12.100"
    assert "shell" not in ffmpeg


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_pcm_wav(amplitude=0), "RMS"),
        (_pcm_wav(clipped=True), "clipping"),
        (_pcm_wav(duration_ms=2_000), "duration"),
    ],
    ids=("silence", "clipping", "duration"),
)
def test_rejects_silence_clipping_and_out_of_range_duration(
    payload: bytes,
    message: str,
) -> None:
    runner = _Runner(payload, source_duration_ms=round((len(payload) - 44) / 192))
    with pytest.raises(ReferenceAudioQualityRejected, match=message):
        _normalize(payload, runner)


def test_rejects_build_identity_before_executing_tools() -> None:
    payload = _pcm_wav()
    runner = _Runner(payload)
    with pytest.raises(ReferenceToolchainUnavailable, match="build identity"):
        normalize_reference_audio(
            payload,
            mime_type="audio/wav",
            declared_sha256=hashlib.sha256(payload).hexdigest(),
            ffmpeg_path=Path(sys.executable),
            ffprobe_path=Path(sys.executable),
            expected_ffmpeg_build_id="drifted-build",
            runner=runner,
        )
    assert runner.commands == []
