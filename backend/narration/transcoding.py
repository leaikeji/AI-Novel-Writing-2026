"""Bounded FFmpeg transcoding for validated narration segment audio.

The caller provides the fixed, verified FFmpeg/FFprobe paths.  Commands never
use a shell or network protocol and run outside database transactions.  All
outputs remain inside a temporary directory until complete bytes and probe
evidence have been validated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Callable, Protocol, Sequence

from .audio_pipeline import ProcessedPcmWav


TRANSCODING_VERSION = "narration-transcoding/1"


class TranscodingError(RuntimeError):
    """Base class for fail-closed external audio conversion."""


class TranscodingUnavailable(TranscodingError):
    """The fixed toolchain or AAC capability is unavailable."""


class TranscodingValidationError(TranscodingError):
    """A completed output does not match the frozen audio contract."""


@dataclass(frozen=True, slots=True)
class TranscodingPolicy:
    ffmpeg_build_id: str = "ffmpeg-9.0.1-lgpl-narrow-linux-arm64-v1"
    sample_rate_hz: int = 48_000
    channels: int = 2
    master_codec: str = "flac"
    playback_codec: str = "aac"
    playback_profile: str = "LC"
    playback_bitrate: str = "128k"
    timeout_seconds: int = 90
    maximum_master_bytes: int = 96 * 1024 * 1024
    maximum_playback_bytes: int = 48 * 1024 * 1024
    maximum_duration_drift_ms: int = 40
    maximum_duration_drift_ratio: float = 0.02
    allow_wav_fallback: bool = True

    def validate(self) -> None:
        if not self.ffmpeg_build_id or self.ffmpeg_build_id.strip() != self.ffmpeg_build_id:
            raise TranscodingValidationError("ffmpeg build id must be a normalized value")
        if self.sample_rate_hz != 48_000 or self.channels != 2:
            raise TranscodingValidationError("transcoding output must remain 48 kHz stereo")
        if (
            self.master_codec != "flac"
            or self.playback_codec != "aac"
            or self.playback_profile != "LC"
        ):
            raise TranscodingValidationError("transcoding codecs differ from the frozen contract")
        for value in (
            self.timeout_seconds,
            self.maximum_master_bytes,
            self.maximum_playback_bytes,
            self.maximum_duration_drift_ms,
        ):
            if type(value) is not int or value <= 0:
                raise TranscodingValidationError("transcoding bounds must be positive exact integers")
        if type(self.allow_wav_fallback) is not bool:
            raise TranscodingValidationError("WAV fallback flag must be an exact boolean")
        if not 0.0 <= self.maximum_duration_drift_ratio <= 1.0:
            raise TranscodingValidationError("transcoding duration ratio is invalid")


DEFAULT_TRANSCODING_POLICY = TranscodingPolicy()


@dataclass(frozen=True, slots=True)
class TranscodeArtifact:
    audio_bytes: bytes
    actual_sha256: str
    byte_size: int
    extension: str
    mime_type: str
    codec: str
    duration_ms: int
    sample_rate_hz: int
    channels: int


@dataclass(frozen=True, slots=True)
class TranscodedSegment:
    master: TranscodeArtifact
    playback: TranscodeArtifact
    used_wav_fallback: bool
    processing_fingerprint: str


class CommandRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[bytes]: ...


def subprocess_runner(
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


def transcoding_fingerprint(
    input_processing_fingerprint: str,
    policy: TranscodingPolicy = DEFAULT_TRANSCODING_POLICY,
) -> str:
    policy.validate()
    if not isinstance(input_processing_fingerprint, str) or not input_processing_fingerprint:
        raise TranscodingValidationError("input processing fingerprint is required")
    canonical = json.dumps(
        {
            "schema_version": TRANSCODING_VERSION,
            "input_processing_fingerprint": input_processing_fingerprint,
            "policy": asdict(policy),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _require_tool(path: Path, *, label: str) -> str:
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise TranscodingUnavailable(f"fixed {label} executable is unavailable")
    return os.fspath(path)


def validate_fixed_toolchain(
    *,
    ffmpeg_path: Path,
    ffprobe_path: Path,
    expected_build_id: str,
    policy: TranscodingPolicy = DEFAULT_TRANSCODING_POLICY,
    runner: CommandRunner = subprocess_runner,
) -> None:
    """Prove the pinned executables are runnable before production is advertised.

    The immutable container image is the authority for the executable bytes;
    ``expected_build_id`` fences that image identity to the frozen transcoding
    policy.  Running both narrow entry points catches missing executables,
    loader/architecture failures and unusable permissions before the HTTP
    production backend or worker is exposed.
    """

    policy.validate()
    if (
        not isinstance(expected_build_id, str)
        or not expected_build_id
        or expected_build_id != policy.ffmpeg_build_id
    ):
        raise TranscodingValidationError(
            "fixed FFmpeg build identity differs from the transcoding policy"
        )
    ffmpeg = _require_tool(ffmpeg_path, label="ffmpeg")
    ffprobe = _require_tool(ffprobe_path, label="ffprobe")
    timeout_seconds = min(policy.timeout_seconds, 15)
    _run_checked(
        runner,
        (ffmpeg, "-version"),
        timeout_seconds=timeout_seconds,
        label="fixed ffmpeg validation",
    )
    _run_checked(
        runner,
        (ffprobe, "-version"),
        timeout_seconds=timeout_seconds,
        label="fixed ffprobe validation",
    )


def _stderr_text(result: subprocess.CompletedProcess[bytes]) -> str:
    raw = result.stderr if isinstance(result.stderr, bytes) else b""
    return raw.decode("utf-8", errors="replace")[:2_000]


def _run_checked(
    runner: CommandRunner,
    argv: Sequence[str],
    *,
    timeout_seconds: int,
    label: str,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(tuple(argv), timeout_seconds=timeout_seconds)
    except (OSError, subprocess.SubprocessError) as error:
        raise TranscodingUnavailable(f"{label} execution is unavailable") from error
    if type(result.returncode) is not int:
        raise TranscodingValidationError(f"{label} returned an invalid status")
    if result.returncode != 0:
        raise TranscodingError(f"{label} failed: {_stderr_text(result)}")
    return result


def _read_bounded(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise TranscodingValidationError(f"{label} output is missing") from error
    if size <= 0 or size > maximum_bytes:
        raise TranscodingValidationError(f"{label} output size is outside bounds")
    payload = path.read_bytes()
    if len(payload) != size:
        raise TranscodingValidationError(f"{label} output changed while reading")
    return payload


def _probe(
    runner: CommandRunner,
    ffprobe: str,
    path: Path,
    *,
    timeout_seconds: int,
) -> tuple[str, str | None, int, int, int]:
    result = _run_checked(
        runner,
        (
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,profile,sample_rate,channels:format=duration",
            "-of",
            "json",
            os.fspath(path),
        ),
        timeout_seconds=timeout_seconds,
        label="ffprobe",
    )
    try:
        raw = result.stdout if isinstance(result.stdout, bytes) else b""
        payload = json.loads(raw.decode("utf-8"))
        streams = payload["streams"]
        stream = streams[0]
        codec = stream["codec_name"]
        profile = stream.get("profile")
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        duration_ms = round(float(payload["format"]["duration"]) * 1000)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise TranscodingValidationError("ffprobe returned an invalid audio contract") from error
    if (
        not isinstance(codec, str)
        or profile is not None and not isinstance(profile, str)
        or sample_rate <= 0
        or channels <= 0
        or duration_ms <= 0
    ):
        raise TranscodingValidationError("ffprobe audio values are invalid")
    return codec, profile, sample_rate, channels, duration_ms


def _validate_duration(
    actual_ms: int,
    expected_ms: int,
    policy: TranscodingPolicy,
) -> None:
    allowed = max(
        policy.maximum_duration_drift_ms,
        round(expected_ms * policy.maximum_duration_drift_ratio),
    )
    if abs(actual_ms - expected_ms) > allowed:
        raise TranscodingValidationError("transcoded duration drift exceeds the frozen limit")


def _artifact(
    payload: bytes,
    *,
    extension: str,
    mime_type: str,
    codec: str,
    duration_ms: int,
    policy: TranscodingPolicy,
) -> TranscodeArtifact:
    return TranscodeArtifact(
        audio_bytes=payload,
        actual_sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
        extension=extension,
        mime_type=mime_type,
        codec=codec,
        duration_ms=duration_ms,
        sample_rate_hz=policy.sample_rate_hz,
        channels=policy.channels,
    )


def transcode_segment(
    processed: ProcessedPcmWav,
    *,
    ffmpeg_path: Path,
    ffprobe_path: Path,
    policy: TranscodingPolicy = DEFAULT_TRANSCODING_POLICY,
    runner: CommandRunner = subprocess_runner,
) -> TranscodedSegment:
    if type(processed) is not ProcessedPcmWav:
        raise TranscodingValidationError("transcoding requires validated PCM evidence")
    policy.validate()
    if (
        processed.sample_rate_hz != policy.sample_rate_hz
        or processed.channels != policy.channels
        or processed.sample_width_bytes != 2
    ):
        raise TranscodingValidationError("processed PCM differs from the transcoder contract")
    if hashlib.sha256(processed.wav_bytes).hexdigest() != processed.actual_sha256:
        raise TranscodingValidationError("processed PCM bytes differ from their digest")
    ffmpeg = _require_tool(ffmpeg_path, label="ffmpeg")
    ffprobe = _require_tool(ffprobe_path, label="ffprobe")
    with TemporaryDirectory(prefix="anw-narration-transcode-") as directory:
        root = Path(directory)
        source = root / "source.wav"
        master_path = root / "master.flac"
        playback_path = root / "playback.m4a"
        source.write_bytes(processed.wav_bytes)
        common = (
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "+bitexact",
            "-i",
            os.fspath(source),
            "-map_metadata",
            "-1",
            "-vn",
            "-sn",
            "-dn",
            "-ar",
            str(policy.sample_rate_hz),
            "-ac",
            str(policy.channels),
        )
        _run_checked(
            runner,
            (
                *common,
                "-c:a",
                "flac",
                "-compression_level",
                "8",
                "-flags:a",
                "+bitexact",
                "-f",
                "flac",
                "-y",
                os.fspath(master_path),
            ),
            timeout_seconds=policy.timeout_seconds,
            label="FLAC master transcoding",
        )
        master_bytes = _read_bounded(
            master_path,
            maximum_bytes=policy.maximum_master_bytes,
            label="FLAC master",
        )
        master_probe = _probe(
            runner,
            ffprobe,
            master_path,
            timeout_seconds=policy.timeout_seconds,
        )
        master_codec, _profile, sample_rate, channels, master_duration = master_probe
        if (
            master_codec != policy.master_codec
            or sample_rate != policy.sample_rate_hz
            or channels != policy.channels
        ):
            raise TranscodingValidationError("FLAC master probe differs from the contract")
        _validate_duration(master_duration, processed.duration_ms, policy)

        used_fallback = False
        try:
            _run_checked(
                runner,
                (
                    *common,
                    "-c:a",
                    "aac",
                    "-profile:a",
                    "aac_low",
                    "-b:a",
                    policy.playback_bitrate,
                    "-flags:a",
                    "+bitexact",
                    "-movflags",
                    "+faststart",
                    "-f",
                    "ipod",
                    "-y",
                    os.fspath(playback_path),
                ),
                timeout_seconds=policy.timeout_seconds,
                label="AAC-LC playback transcoding",
            )
        except TranscodingError as error:
            message = str(error).lower()
            capability_failure = (
                "unknown encoder" in message
                or "encoder (codec aac) not found" in message
                or "requested encoder" in message and "not found" in message
            )
            if not policy.allow_wav_fallback or not capability_failure:
                raise
            used_fallback = True

        master = _artifact(
            master_bytes,
            extension="flac",
            mime_type="audio/flac",
            codec="flac",
            duration_ms=master_duration,
            policy=policy,
        )
        if used_fallback:
            playback = _artifact(
                processed.wav_bytes,
                extension="wav",
                mime_type="audio/wav",
                codec="pcm_s16le",
                duration_ms=processed.duration_ms,
                policy=policy,
            )
        else:
            playback_bytes = _read_bounded(
                playback_path,
                maximum_bytes=policy.maximum_playback_bytes,
                label="AAC-LC playback",
            )
            codec, profile, sample_rate, channels, playback_duration = _probe(
                runner,
                ffprobe,
                playback_path,
                timeout_seconds=policy.timeout_seconds,
            )
            if (
                codec != policy.playback_codec
                or profile != policy.playback_profile
                or sample_rate != policy.sample_rate_hz
                or channels != policy.channels
            ):
                raise TranscodingValidationError("AAC-LC playback probe differs from the contract")
            _validate_duration(playback_duration, processed.duration_ms, policy)
            playback = _artifact(
                playback_bytes,
                extension="m4a",
                mime_type="audio/mp4",
                codec="aac",
                duration_ms=playback_duration,
                policy=policy,
            )
        return TranscodedSegment(
            master=master,
            playback=playback,
            used_wav_fallback=used_fallback,
            processing_fingerprint=transcoding_fingerprint(
                processed.processing_fingerprint,
                policy,
            ),
        )


__all__ = [
    "CommandRunner",
    "DEFAULT_TRANSCODING_POLICY",
    "TRANSCODING_VERSION",
    "TranscodeArtifact",
    "TranscodedSegment",
    "TranscodingError",
    "TranscodingPolicy",
    "TranscodingUnavailable",
    "TranscodingValidationError",
    "subprocess_runner",
    "transcode_segment",
    "transcoding_fingerprint",
    "validate_fixed_toolchain",
]
