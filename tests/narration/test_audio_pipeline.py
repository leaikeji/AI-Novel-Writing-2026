from __future__ import annotations

from array import array
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys
import wave

import pytest

from backend.narration.audio_pipeline import (
    AudioFormatError,
    AudioPipelineError,
    AudioQualityError,
    ShortChineseDurationPolicy,
    inspect_pcm_wav,
    process_synthesis_wav,
    short_chinese_duration_limit_ms,
)
from backend.narration.transcoding import (
    DEFAULT_TRANSCODING_POLICY,
    TranscodingError,
    TranscodingUnavailable,
    TranscodingValidationError,
    transcode_segment,
    validate_fixed_toolchain,
)


def _wav_bytes(
    *,
    duration_ms: int = 500,
    sample_rate: int = 48_000,
    channels: int = 2,
    sample_width: int = 2,
    amplitude: int = 6_000,
    constant: int | None = None,
) -> bytes:
    frame_count = round(sample_rate * duration_ms / 1000)
    samples = array("h")
    for index in range(frame_count):
        value = constant if constant is not None else round(
            amplitude * math.sin(2 * math.pi * 440 * index / sample_rate)
        )
        for _channel in range(channels):
            samples.append(value)
    if sys.byteorder != "little":
        samples.byteswap()
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        if sample_width == 2:
            writer.writeframes(samples.tobytes())
        else:
            writer.writeframes(b"\x00" * frame_count * channels * sample_width)
    return output.getvalue()


def _edge_samples(wav_bytes: bytes) -> tuple[tuple[int, ...], tuple[int, ...]]:
    with wave.open(BytesIO(wav_bytes), "rb") as reader:
        raw = reader.readframes(reader.getnframes())
        channels = reader.getnchannels()
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return tuple(samples[:channels]), tuple(samples[-channels:])


def test_pcm_pipeline_is_deterministic_normalized_and_seam_safe() -> None:
    source = _wav_bytes()

    first = process_synthesis_wav(source, expected_duration_ms=500)
    second = process_synthesis_wav(source, expected_duration_ms=500)

    assert first.wav_bytes == second.wav_bytes
    assert first.actual_sha256 == second.actual_sha256
    assert first.processing_fingerprint == second.processing_fingerprint
    assert first.duration_ms == 500
    assert first.sample_rate_hz == 48_000
    assert first.channels == 2
    assert abs(first.output_inspection.rms_dbfs + 20.0) < 0.1
    assert first.output_inspection.peak_dbfs <= -1.0
    assert _edge_samples(first.wav_bytes) == ((0, 0), (0, 0))


@pytest.mark.parametrize(
    "payload,error",
    [
        (b"", AudioFormatError),
        (b"not-a-wave", AudioFormatError),
        (_wav_bytes(sample_rate=44_100), AudioFormatError),
        (_wav_bytes(channels=1), AudioFormatError),
        (_wav_bytes(sample_width=1), AudioFormatError),
        (_wav_bytes(constant=0), AudioQualityError),
        (_wav_bytes(constant=32_767), AudioQualityError),
    ],
)
def test_pcm_pipeline_rejects_invalid_format_silence_and_clipping(
    payload: bytes,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        process_synthesis_wav(payload)


def test_pcm_pipeline_rejects_large_duration_drift() -> None:
    payload = _wav_bytes(duration_ms=500)
    with pytest.raises(AudioQualityError, match="duration drift"):
        inspect_pcm_wav(payload, expected_duration_ms=900)


@pytest.mark.parametrize(
    ("spoken_text", "duration_ms"),
    [
        ("林晚说道：", 3_760),
        ("沈川说道：", 22_080),
    ],
)
def test_pcm_pipeline_rejects_confirmed_short_chinese_duration_runaways(
    spoken_text: str,
    duration_ms: int,
) -> None:
    assert short_chinese_duration_limit_ms(spoken_text) == 3_200

    with pytest.raises(AudioQualityError, match="short Chinese text"):
        process_synthesis_wav(
            _wav_bytes(duration_ms=duration_ms),
            spoken_text=spoken_text,
        )


@pytest.mark.parametrize(
    ("spoken_text", "duration_ms"),
    [
        ("站台上的灯忽然闪了一次，四周仍然没有人影。", 4_160),
        ("远处传来货车压过石子的声音，随后又恢复安静。", 4_240),
    ],
)
def test_pcm_pipeline_accepts_observed_normal_chinese_narration(
    spoken_text: str,
    duration_ms: int,
) -> None:
    limit_ms = short_chinese_duration_limit_ms(spoken_text)
    assert limit_ms is not None and duration_ms < limit_ms

    processed = process_synthesis_wav(
        _wav_bytes(duration_ms=duration_ms),
        spoken_text=spoken_text,
    )

    assert processed.duration_ms == duration_ms


def test_short_chinese_duration_gate_is_narrow_calibratable_and_boundary_exact() -> None:
    policy = ShortChineseDurationPolicy(
        maximum_codepoints=5,
        onset_allowance_ms=1_200,
        per_codepoint_allowance_ms=400,
    )
    assert short_chinese_duration_limit_ms("林晚说道：", policy=policy) == 3_200
    assert short_chinese_duration_limit_ms("沈川说道：", policy=policy) == 3_200
    assert short_chinese_duration_limit_ms("林晚说道: A", policy=policy) is None
    assert short_chinese_duration_limit_ms("第2章：", policy=policy) is None
    assert short_chinese_duration_limit_ms("这是一段超过五个字的中文。", policy=policy) is None

    process_synthesis_wav(
        _wav_bytes(duration_ms=3_200),
        spoken_text="林晚说道：",
    )
    with pytest.raises(AudioQualityError, match="short Chinese text"):
        process_synthesis_wav(
            _wav_bytes(duration_ms=3_201),
            spoken_text="林晚说道：",
        )

    with pytest.raises(AudioPipelineError, match="positive exact integers"):
        short_chinese_duration_limit_ms(
            "林晚说道：",
            policy=ShortChineseDurationPolicy(maximum_codepoints=True),
        )


class _FakeRunner:
    def __init__(
        self,
        *,
        aac_unavailable: bool = False,
        playback_profile: str = "LC",
        fail_master: bool = False,
    ) -> None:
        self.aac_unavailable = aac_unavailable
        self.playback_profile = playback_profile
        self.fail_master = fail_master
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[bytes]:
        assert timeout_seconds == 90
        self.calls.append(tuple(argv))
        output = Path(argv[-1])
        if "ffprobe" in Path(argv[0]).name:
            if output.suffix == ".flac":
                codec, profile = "flac", None
            else:
                codec, profile = "aac", self.playback_profile
            payload = {
                "streams": [
                    {
                        "codec_name": codec,
                        "profile": profile,
                        "sample_rate": "48000",
                        "channels": 2,
                    }
                ],
                "format": {"duration": "0.500000"},
            }
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(payload).encode("utf-8"),
                stderr=b"",
            )
        if output.suffix == ".flac":
            if self.fail_master:
                return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"bad input")
            output.write_bytes(b"fLaC" + b"m" * 64)
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if self.aac_unavailable:
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout=b"",
                stderr=b"Unknown encoder 'aac'",
            )
        output.write_bytes(b"\x00\x00\x00\x18ftypM4A " + b"p" * 64)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")


def _tool(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def test_transcoder_produces_flac_and_aac_without_shell_or_external_paths(
    tmp_path: Path,
) -> None:
    processed = process_synthesis_wav(_wav_bytes())
    ffmpeg = _tool(tmp_path / "ffmpeg")
    ffprobe = _tool(tmp_path / "ffprobe")
    runner = _FakeRunner()

    result = transcode_segment(
        processed,
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        runner=runner,
    )

    assert result.master.extension == "flac"
    assert result.master.mime_type == "audio/flac"
    assert result.playback.extension == "m4a"
    assert result.playback.mime_type == "audio/mp4"
    assert result.playback.codec == "aac"
    assert result.used_wav_fallback is False
    assert all("http://" not in " ".join(call) for call in runner.calls)
    assert all("https://" not in " ".join(call) for call in runner.calls)
    ffmpeg_calls = [call for call in runner.calls if Path(call[0]).name == "ffmpeg"]
    assert len(ffmpeg_calls) == 2
    assert all("-nostdin" in call and "-map_metadata" in call for call in ffmpeg_calls)


def test_transcoder_uses_only_explicit_wav_fallback_for_missing_aac(
    tmp_path: Path,
) -> None:
    processed = process_synthesis_wav(_wav_bytes())
    runner = _FakeRunner(aac_unavailable=True)

    result = transcode_segment(
        processed,
        ffmpeg_path=_tool(tmp_path / "ffmpeg"),
        ffprobe_path=_tool(tmp_path / "ffprobe"),
        runner=runner,
    )

    assert result.used_wav_fallback is True
    assert result.playback.audio_bytes == processed.wav_bytes
    assert result.playback.mime_type == "audio/wav"
    assert result.playback.codec == "pcm_s16le"


def test_transcoder_rejects_bad_probe_and_non_capability_failure(
    tmp_path: Path,
) -> None:
    processed = process_synthesis_wav(_wav_bytes())
    ffmpeg = _tool(tmp_path / "ffmpeg")
    ffprobe = _tool(tmp_path / "ffprobe")
    with pytest.raises(TranscodingValidationError, match="AAC-LC"):
        transcode_segment(
            processed,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            runner=_FakeRunner(playback_profile="HE-AAC"),
        )
    with pytest.raises(TranscodingError, match="FLAC master"):
        transcode_segment(
            processed,
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            runner=_FakeRunner(fail_master=True),
        )


def test_fixed_toolchain_is_runnable_and_build_fenced_before_use(
    tmp_path: Path,
) -> None:
    ffmpeg = _tool(tmp_path / "ffmpeg")
    ffprobe = _tool(tmp_path / "ffprobe")
    calls: list[tuple[str, ...]] = []

    def runner(
        argv: tuple[str, ...],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[bytes]:
        assert timeout_seconds == 15
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=b"version", stderr=b"")

    validate_fixed_toolchain(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        expected_build_id=DEFAULT_TRANSCODING_POLICY.ffmpeg_build_id,
        runner=runner,
    )

    assert calls == [(str(ffmpeg), "-version"), (str(ffprobe), "-version")]
    with pytest.raises(TranscodingValidationError, match="build identity"):
        validate_fixed_toolchain(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            expected_build_id="unexpected-build",
            runner=runner,
        )
    with pytest.raises(TranscodingUnavailable, match="ffmpeg"):
        validate_fixed_toolchain(
            ffmpeg_path=tmp_path / "missing-ffmpeg",
            ffprobe_path=ffprobe,
            expected_build_id=DEFAULT_TRANSCODING_POLICY.ffmpeg_build_id,
            runner=runner,
        )


def test_audio_modules_have_no_database_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    source = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "backend/narration/audio_pipeline.py",
            "backend/narration/transcoding.py",
        )
    )
    assert "sqlalchemy" not in source
    assert "backend.models" not in source
