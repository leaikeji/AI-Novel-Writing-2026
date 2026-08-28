"""Bounded reference-audio validation and deterministic FFmpeg normalization.

This module deliberately has no database dependency.  The caller must invoke it
outside every database transaction, then persist only the returned immutable
bytes, hashes, and structured evidence in short transactions.
"""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass, field
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Final, Protocol, Sequence
import wave

from .services import canonical_sha256


REFERENCE_NORMALIZATION_VERSION: Final = "narration-reference-normalization/1"
REFERENCE_MIME_TYPES: Final = frozenset({"audio/wav", "audio/flac"})
REFERENCE_MAX_UPLOAD_BYTES: Final = 16 * 1024 * 1024


class ReferenceMediaError(RuntimeError):
    """Base class for redacted reference-media failures."""


class ReferenceToolchainUnavailable(ReferenceMediaError):
    """The fixed FFmpeg/FFprobe toolchain could not be executed."""


class ReferenceAudioInvalid(ReferenceMediaError):
    """The input cannot be safely decoded into the frozen reference format."""


class ReferenceAudioQualityRejected(ReferenceMediaError):
    """The decoded reference fails an explicit product-quality boundary."""


@dataclass(frozen=True, slots=True)
class ReferenceNormalizationPolicy:
    ffmpeg_build_id: str = "ffmpeg-9.0.1-lgpl-narrow-linux-arm64-v1"
    sample_rate_hz: int = 48_000
    channels: int = 2
    sample_width_bytes: int = 2
    minimum_duration_ms: int = 3_000
    maximum_duration_ms: int = 12_000
    maximum_input_bytes: int = REFERENCE_MAX_UPLOAD_BYTES
    maximum_output_bytes: int = 4 * 1024 * 1024
    timeout_seconds: int = 45
    analysis_window_ms: int = 100
    silence_rms_dbfs: float = -50.0
    maximum_silent_fraction: float = 0.45
    maximum_leading_silence_ms: int = 1_500
    maximum_trailing_silence_ms: int = 1_500
    maximum_clipped_fraction: float = 0.001
    minimum_rms_dbfs: float = -42.0
    maximum_rms_dbfs: float = -6.0

    def validate(self) -> None:
        exact_positive = (
            self.sample_rate_hz,
            self.channels,
            self.sample_width_bytes,
            self.minimum_duration_ms,
            self.maximum_duration_ms,
            self.maximum_input_bytes,
            self.maximum_output_bytes,
            self.timeout_seconds,
            self.analysis_window_ms,
            self.maximum_leading_silence_ms,
            self.maximum_trailing_silence_ms,
        )
        if any(type(value) is not int or value <= 0 for value in exact_positive):
            raise ReferenceAudioInvalid("reference policy integer bounds are invalid")
        if (
            self.sample_rate_hz != 48_000
            or self.channels != 2
            or self.sample_width_bytes != 2
            or self.maximum_duration_ms < self.minimum_duration_ms
            or self.maximum_input_bytes > REFERENCE_MAX_UPLOAD_BYTES
        ):
            raise ReferenceAudioInvalid("reference policy differs from the frozen format")
        if (
            not self.ffmpeg_build_id
            or self.ffmpeg_build_id.strip() != self.ffmpeg_build_id
        ):
            raise ReferenceAudioInvalid("reference FFmpeg build identity is invalid")
        if not -120.0 <= self.silence_rms_dbfs < 0.0:
            raise ReferenceAudioInvalid("reference silence threshold is invalid")
        if not 0.0 <= self.maximum_silent_fraction <= 1.0:
            raise ReferenceAudioInvalid("reference silent fraction is invalid")
        if not 0.0 <= self.maximum_clipped_fraction <= 1.0:
            raise ReferenceAudioInvalid("reference clipped fraction is invalid")
        if not -120.0 <= self.minimum_rms_dbfs < self.maximum_rms_dbfs < 0.0:
            raise ReferenceAudioInvalid("reference RMS bounds are invalid")


DEFAULT_REFERENCE_NORMALIZATION_POLICY = ReferenceNormalizationPolicy()


@dataclass(frozen=True, slots=True)
class ReferenceFormatEvidence:
    mime_type: str
    codec: str
    sample_rate_hz: int
    channels: int
    duration_ms: int
    byte_size: int
    actual_sha256: str


@dataclass(frozen=True, slots=True)
class ReferenceQualityEvidence:
    frame_count: int
    duration_ms: int
    peak_dbfs: float
    rms_dbfs: float
    clipped_sample_count: int
    clipped_fraction: float
    silent_window_count: int
    window_count: int
    silent_fraction: float
    leading_silence_ms: int
    trailing_silence_ms: int


@dataclass(frozen=True, slots=True)
class NormalizedReferenceAudio:
    normalized_bytes: bytes = field(repr=False)
    normalized_sha256: str
    normalized_byte_size: int
    mime_type: str
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    source: ReferenceFormatEvidence
    normalized: ReferenceFormatEvidence
    quality: ReferenceQualityEvidence
    validation_evidence: dict[str, object]
    normalization_fingerprint: str


class ReferenceCommandRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[bytes]: ...


def reference_subprocess_runner(
    argv: Sequence[str],
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        tuple(argv),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        shell=False,
    )


def _tool(path: Path, *, label: str) -> str:
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ReferenceToolchainUnavailable(f"fixed {label} executable is unavailable")
    return os.fspath(path)


def _run(
    runner: ReferenceCommandRunner,
    argv: Sequence[str],
    *,
    timeout_seconds: int,
    label: str,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(tuple(argv), timeout_seconds=timeout_seconds)
    except (OSError, subprocess.SubprocessError) as error:
        raise ReferenceToolchainUnavailable(f"{label} is unavailable") from error
    if type(result.returncode) is not int:
        raise ReferenceAudioInvalid(f"{label} returned an invalid status")
    if result.returncode != 0:
        raise ReferenceAudioInvalid(f"{label} rejected the reference audio")
    return result


def reference_normalization_fingerprint(
    policy: ReferenceNormalizationPolicy = DEFAULT_REFERENCE_NORMALIZATION_POLICY,
) -> str:
    policy.validate()
    policy_payload = {
        key: (format(value, ".17g") if isinstance(value, float) else value)
        for key, value in asdict(policy).items()
    }
    return canonical_sha256(
        {
            "schema_version": REFERENCE_NORMALIZATION_VERSION,
            "policy": policy_payload,
            "codec": "pcm_s16le",
            "container": "wav",
        }
    )


def _probe_source(
    runner: ReferenceCommandRunner,
    ffprobe: str,
    path: Path,
    *,
    mime_type: str,
    byte_size: int,
    actual_sha256: str,
    timeout_seconds: int,
) -> ReferenceFormatEvidence:
    result = _run(
        runner,
        (
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,sample_rate,channels:format=duration",
            "-of",
            "json",
            os.fspath(path),
        ),
        timeout_seconds=timeout_seconds,
        label="fixed ffprobe reference inspection",
    )
    try:
        payload = json.loads(bytes(result.stdout or b"").decode("utf-8", "strict"))
        streams = payload["streams"]
        if type(streams) is not list or len(streams) != 1:
            raise ValueError("reference must contain exactly one stream")
        stream = streams[0]
        if stream["codec_type"] != "audio":
            raise ValueError("reference stream is not audio")
        codec = str(stream["codec_name"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        duration_ms = round(float(payload["format"]["duration"]) * 1000)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReferenceAudioInvalid("ffprobe returned invalid reference evidence") from error
    allowed_codecs = (
        {
            "pcm_u8",
            "pcm_s16le",
            "pcm_s24le",
            "pcm_s32le",
            "pcm_f32le",
            "pcm_f64le",
        }
        if mime_type == "audio/wav"
        else {"flac"}
    )
    if (
        codec not in allowed_codecs
        or not 8_000 <= sample_rate <= 192_000
        or not 1 <= channels <= 8
        or duration_ms <= 0
    ):
        raise ReferenceAudioInvalid("reference source format is unsupported")
    return ReferenceFormatEvidence(
        mime_type=mime_type,
        codec=codec,
        sample_rate_hz=sample_rate,
        channels=channels,
        duration_ms=duration_ms,
        byte_size=byte_size,
        actual_sha256=actual_sha256,
    )


def _dbfs(value: float) -> float:
    if value <= 0.0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(value / 32768.0))


def _inspect_normalized_wav(
    payload: bytes,
    policy: ReferenceNormalizationPolicy,
) -> tuple[ReferenceFormatEvidence, ReferenceQualityEvidence]:
    try:
        with wave.open(BytesIO(payload), "rb") as source:
            observed = (
                source.getframerate(),
                source.getnchannels(),
                source.getsampwidth(),
                source.getcomptype(),
            )
            frame_count = source.getnframes()
            decoded = source.readframes(frame_count)
            exhausted = bool(source.readframes(1))
    except (EOFError, wave.Error) as error:
        raise ReferenceAudioInvalid("normalized reference WAV cannot be decoded") from error
    expected = (
        policy.sample_rate_hz,
        policy.channels,
        policy.sample_width_bytes,
        "NONE",
    )
    if observed != expected or frame_count <= 0 or exhausted:
        raise ReferenceAudioInvalid("normalized reference differs from 48 kHz stereo s16 WAV")
    if len(decoded) != frame_count * policy.channels * policy.sample_width_bytes:
        raise ReferenceAudioInvalid("normalized reference frame count is inconsistent")
    samples = array("h")
    samples.frombytes(decoded)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) != frame_count * policy.channels:
        raise ReferenceAudioInvalid("normalized reference sample count is inconsistent")
    duration_ms = round(frame_count * 1000 / policy.sample_rate_hz)
    if not policy.minimum_duration_ms <= duration_ms <= policy.maximum_duration_ms:
        raise ReferenceAudioQualityRejected("reference duration is outside the product range")
    squares = 0
    peak = 0
    clipped = 0
    clip_threshold = round(32767 * 0.999)
    for sample in samples:
        absolute = abs(int(sample))
        squares += absolute * absolute
        peak = max(peak, absolute)
        if absolute >= clip_threshold:
            clipped += 1
    rms = math.sqrt(squares / len(samples))
    rms_dbfs = _dbfs(rms)
    peak_dbfs = _dbfs(float(peak))
    clipped_fraction = clipped / len(samples)

    frames_per_window = max(
        1, round(policy.sample_rate_hz * policy.analysis_window_ms / 1000)
    )
    window_silent: list[bool] = []
    for start_frame in range(0, frame_count, frames_per_window):
        end_frame = min(frame_count, start_frame + frames_per_window)
        start_sample = start_frame * policy.channels
        end_sample = end_frame * policy.channels
        window = samples[start_sample:end_sample]
        window_rms = math.sqrt(
            sum(int(sample) * int(sample) for sample in window) / len(window)
        )
        window_silent.append(_dbfs(window_rms) <= policy.silence_rms_dbfs)
    silent_windows = sum(window_silent)
    silent_fraction = silent_windows / len(window_silent)
    leading_windows = 0
    for silent in window_silent:
        if not silent:
            break
        leading_windows += 1
    trailing_windows = 0
    for silent in reversed(window_silent):
        if not silent:
            break
        trailing_windows += 1
    leading_ms = min(duration_ms, leading_windows * policy.analysis_window_ms)
    trailing_ms = min(duration_ms, trailing_windows * policy.analysis_window_ms)
    evidence = ReferenceQualityEvidence(
        frame_count=frame_count,
        duration_ms=duration_ms,
        peak_dbfs=round(peak_dbfs, 4),
        rms_dbfs=round(rms_dbfs, 4),
        clipped_sample_count=clipped,
        clipped_fraction=round(clipped_fraction, 8),
        silent_window_count=silent_windows,
        window_count=len(window_silent),
        silent_fraction=round(silent_fraction, 8),
        leading_silence_ms=leading_ms,
        trailing_silence_ms=trailing_ms,
    )
    if clipped_fraction > policy.maximum_clipped_fraction:
        raise ReferenceAudioQualityRejected("reference contains excessive clipping")
    if not policy.minimum_rms_dbfs <= rms_dbfs <= policy.maximum_rms_dbfs:
        raise ReferenceAudioQualityRejected("reference RMS is outside the product range")
    if silent_fraction > policy.maximum_silent_fraction:
        raise ReferenceAudioQualityRejected("reference contains excessive silence")
    if leading_ms > policy.maximum_leading_silence_ms:
        raise ReferenceAudioQualityRejected("reference leading silence is excessive")
    if trailing_ms > policy.maximum_trailing_silence_ms:
        raise ReferenceAudioQualityRejected("reference trailing silence is excessive")
    digest = hashlib.sha256(payload).hexdigest()
    normalized = ReferenceFormatEvidence(
        mime_type="audio/wav",
        codec="pcm_s16le",
        sample_rate_hz=policy.sample_rate_hz,
        channels=policy.channels,
        duration_ms=duration_ms,
        byte_size=len(payload),
        actual_sha256=digest,
    )
    return normalized, evidence


def normalize_reference_audio(
    reference_audio: bytes,
    *,
    mime_type: str,
    declared_sha256: str,
    ffmpeg_path: Path,
    ffprobe_path: Path,
    expected_ffmpeg_build_id: str,
    policy: ReferenceNormalizationPolicy = DEFAULT_REFERENCE_NORMALIZATION_POLICY,
    runner: ReferenceCommandRunner = reference_subprocess_runner,
) -> NormalizedReferenceAudio:
    """Fully decode and normalize one WAV/FLAC reference outside a DB tx."""

    policy.validate()
    if expected_ffmpeg_build_id != policy.ffmpeg_build_id:
        raise ReferenceToolchainUnavailable("fixed FFmpeg build identity changed")
    if type(reference_audio) is not bytes or not 1 <= len(reference_audio) <= policy.maximum_input_bytes:
        raise ReferenceAudioInvalid("reference byte size is outside the product bound")
    if mime_type not in REFERENCE_MIME_TYPES:
        raise ReferenceAudioInvalid("reference MIME type is unsupported")
    actual_sha256 = hashlib.sha256(reference_audio).hexdigest()
    if actual_sha256 != declared_sha256:
        raise ReferenceAudioInvalid("reference bytes disagree with their SHA-256")
    if mime_type == "audio/wav":
        valid_magic = (
            len(reference_audio) >= 12
            and reference_audio[:4] == b"RIFF"
            and reference_audio[8:12] == b"WAVE"
        )
        suffix = ".wav"
    else:
        valid_magic = reference_audio.startswith(b"fLaC")
        suffix = ".flac"
    if not valid_magic:
        raise ReferenceAudioInvalid("reference signature disagrees with its MIME type")
    ffmpeg = _tool(ffmpeg_path, label="ffmpeg")
    ffprobe = _tool(ffprobe_path, label="ffprobe")
    with TemporaryDirectory(prefix="anw-voice-reference-") as directory:
        root = Path(directory)
        source_path = root / f"source{suffix}"
        normalized_path = root / "normalized.wav"
        source_path.write_bytes(reference_audio)
        source = _probe_source(
            runner,
            ffprobe,
            source_path,
            mime_type=mime_type,
            byte_size=len(reference_audio),
            actual_sha256=actual_sha256,
            timeout_seconds=policy.timeout_seconds,
        )
        if not (
            policy.minimum_duration_ms
            <= source.duration_ms
            <= policy.maximum_duration_ms
        ):
            raise ReferenceAudioQualityRejected(
                "reference duration is outside the product range"
            )
        _run(
            runner,
            (
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-fflags",
                "+bitexact",
                "-i",
                os.fspath(source_path),
                "-map",
                "0:a:0",
                "-map_metadata",
                "-1",
                "-vn",
                "-sn",
                "-dn",
                "-t",
                format((policy.maximum_duration_ms + 100) / 1000, ".3f"),
                "-ar",
                str(policy.sample_rate_hz),
                "-ac",
                str(policy.channels),
                "-c:a",
                "pcm_s16le",
                "-flags:a",
                "+bitexact",
                "-f",
                "wav",
                "-y",
                os.fspath(normalized_path),
            ),
            timeout_seconds=policy.timeout_seconds,
            label="fixed FFmpeg reference normalization",
        )
        try:
            normalized_size = normalized_path.stat().st_size
        except OSError as error:
            raise ReferenceAudioInvalid("normalized reference output is missing") from error
        if not 1 <= normalized_size <= policy.maximum_output_bytes:
            raise ReferenceAudioInvalid("normalized reference output exceeds its bound")
        normalized_bytes = normalized_path.read_bytes()
        if len(normalized_bytes) != normalized_size:
            raise ReferenceAudioInvalid("normalized reference changed while reading")
    normalized, quality = _inspect_normalized_wav(normalized_bytes, policy)
    duration_drift = abs(normalized.duration_ms - source.duration_ms)
    if duration_drift > max(80, round(source.duration_ms * 0.02)):
        raise ReferenceAudioInvalid("reference duration changed during normalization")
    fingerprint = reference_normalization_fingerprint(policy)
    validation_evidence: dict[str, object] = {
        "schema_version": REFERENCE_NORMALIZATION_VERSION,
        "normalization_fingerprint": fingerprint,
        "source": asdict(source),
        "normalized": asdict(normalized),
        "quality": asdict(quality),
        "checks": {
            "single_audio_stream": True,
            "fully_decoded": True,
            "duration_within_bounds": True,
            "silence_within_bounds": True,
            "clipping_within_bounds": True,
            "rms_within_bounds": True,
            "format_is_48khz_stereo_s16_wav": True,
        },
    }
    return NormalizedReferenceAudio(
        normalized_bytes=normalized_bytes,
        normalized_sha256=normalized.actual_sha256,
        normalized_byte_size=normalized.byte_size,
        mime_type="audio/wav",
        duration_ms=normalized.duration_ms,
        sample_rate_hz=normalized.sample_rate_hz,
        channels=normalized.channels,
        sample_width_bytes=policy.sample_width_bytes,
        source=source,
        normalized=normalized,
        quality=quality,
        validation_evidence=validation_evidence,
        normalization_fingerprint=fingerprint,
    )


__all__ = [
    "DEFAULT_REFERENCE_NORMALIZATION_POLICY",
    "NormalizedReferenceAudio",
    "REFERENCE_MAX_UPLOAD_BYTES",
    "REFERENCE_MIME_TYPES",
    "REFERENCE_NORMALIZATION_VERSION",
    "ReferenceAudioInvalid",
    "ReferenceAudioQualityRejected",
    "ReferenceCommandRunner",
    "ReferenceFormatEvidence",
    "ReferenceMediaError",
    "ReferenceNormalizationPolicy",
    "ReferenceQualityEvidence",
    "ReferenceToolchainUnavailable",
    "normalize_reference_audio",
    "reference_normalization_fingerprint",
    "reference_subprocess_runner",
]
