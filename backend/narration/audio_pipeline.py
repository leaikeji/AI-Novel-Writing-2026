"""Deterministic, database-free validation and seam-safe PCM processing.

MOSS-TTS-Nano returns a bounded 48 kHz stereo PCM WAV.  This module validates
the complete container and samples before applying one frozen gain/fade policy.
It performs no database, filesystem, subprocess, or network operation.
"""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import json
import math
import re
import sys
import wave


AUDIO_PIPELINE_VERSION = "narration-audio-pipeline/1"
SHORT_CHINESE_DURATION_POLICY_VERSION = "nano-short-chinese-duration/2"

_HAN_CODEPOINT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SHORT_CHINESE_PUNCTUATION = frozenset(
    "，。！？；：、,.!?;:“”‘’「」『』（）()—…《》〈〉"
)


class AudioPipelineError(RuntimeError):
    """Base class for fail-closed segment audio processing."""


class AudioFormatError(AudioPipelineError):
    """The synthesis output is not the frozen PCM WAV format."""


class AudioQualityError(AudioPipelineError):
    """The decoded samples fail a frozen quality boundary."""


@dataclass(frozen=True, slots=True)
class ShortChineseDurationPolicy:
    """Conservative duration ceiling for short, Chinese-only Nano inputs.

    The fixed onset allowance avoids treating a short pause or ordinary model
    startup prosody as a failure.  The per-codepoint allowance is deliberately
    well above the approximately 200 ms/codepoint observed for valid Chinese
    chapter narration, while still isolating the confirmed short-text runaway
    outputs before they can be transcoded or published.
    """

    maximum_codepoints: int = 32
    onset_allowance_ms: int = 1_200
    per_codepoint_allowance_ms: int = 400
    ultrashort_maximum_codepoints: int = 4
    ultrashort_onset_allowance_ms: int = 4_000

    def validate(self) -> None:
        values = (
            self.maximum_codepoints,
            self.onset_allowance_ms,
            self.per_codepoint_allowance_ms,
            self.ultrashort_maximum_codepoints,
            self.ultrashort_onset_allowance_ms,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise AudioPipelineError(
                "short Chinese duration policy requires positive exact integers"
            )


DEFAULT_SHORT_CHINESE_DURATION_POLICY = ShortChineseDurationPolicy()


@dataclass(frozen=True, slots=True)
class AudioPipelinePolicy:
    sample_rate_hz: int = 48_000
    channels: int = 2
    sample_width_bytes: int = 2
    minimum_duration_ms: int = 80
    maximum_duration_ms: int = 180_000
    maximum_input_bytes: int = 96 * 1024 * 1024
    silence_rms_dbfs: float = -55.0
    maximum_clipped_fraction: float = 0.001
    target_rms_dbfs: float = -20.0
    maximum_gain_db: float = 6.0
    peak_limit_dbfs: float = -1.0
    seam_fade_ms: int = 3
    maximum_duration_drift_ms: int = 40
    maximum_duration_drift_ratio: float = 0.02

    def validate(self) -> None:
        integer_values = (
            self.sample_rate_hz,
            self.channels,
            self.sample_width_bytes,
            self.minimum_duration_ms,
            self.maximum_duration_ms,
            self.maximum_input_bytes,
            self.seam_fade_ms,
            self.maximum_duration_drift_ms,
        )
        if any(type(value) is not int or value < 0 for value in integer_values):
            raise AudioPipelineError("audio policy integers must be exact non-negative values")
        if (
            self.sample_rate_hz <= 0
            or self.channels <= 0
            or self.sample_width_bytes != 2
            or self.minimum_duration_ms <= 0
            or self.maximum_duration_ms < self.minimum_duration_ms
            or self.maximum_input_bytes <= 0
        ):
            raise AudioPipelineError("audio policy format or duration bounds are invalid")
        if not -120.0 <= self.silence_rms_dbfs < 0.0:
            raise AudioPipelineError("silence threshold must be between -120 and 0 dBFS")
        if not 0.0 <= self.maximum_clipped_fraction <= 1.0:
            raise AudioPipelineError("clipping fraction must be between zero and one")
        if not -60.0 <= self.target_rms_dbfs < 0.0:
            raise AudioPipelineError("target RMS must be between -60 and 0 dBFS")
        if not 0.0 <= self.maximum_gain_db <= 24.0:
            raise AudioPipelineError("maximum gain must be between zero and 24 dB")
        if not -12.0 <= self.peak_limit_dbfs < 0.0:
            raise AudioPipelineError("peak limit must be between -12 and 0 dBFS")
        if not 0.0 <= self.maximum_duration_drift_ratio <= 1.0:
            raise AudioPipelineError("duration drift ratio must be between zero and one")


DEFAULT_AUDIO_PIPELINE_POLICY = AudioPipelinePolicy()


@dataclass(frozen=True, slots=True)
class AudioInspection:
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    duration_ms: int
    peak_dbfs: float
    rms_dbfs: float
    clipped_sample_count: int
    clipped_fraction: float
    actual_sha256: str


@dataclass(frozen=True, slots=True)
class ProcessedPcmWav:
    wav_bytes: bytes
    actual_sha256: str
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    input_inspection: AudioInspection
    output_inspection: AudioInspection
    applied_gain_db: float
    seam_fade_ms: int
    processing_fingerprint: str


def audio_processing_fingerprint(
    policy: AudioPipelinePolicy = DEFAULT_AUDIO_PIPELINE_POLICY,
    *,
    short_chinese_policy: ShortChineseDurationPolicy = (
        DEFAULT_SHORT_CHINESE_DURATION_POLICY
    ),
) -> str:
    policy.validate()
    short_chinese_policy.validate()
    payload = {
        "schema_version": AUDIO_PIPELINE_VERSION,
        "policy": asdict(policy),
        "short_chinese_duration_policy_version": (
            SHORT_CHINESE_DURATION_POLICY_VERSION
        ),
        "short_chinese_duration_policy": asdict(short_chinese_policy),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(value / 32768.0))


def _decode_pcm_wav(
    wav_bytes: bytes,
    policy: AudioPipelinePolicy,
) -> tuple[array[int], AudioInspection]:
    policy.validate()
    if type(wav_bytes) is not bytes or not wav_bytes:
        raise AudioFormatError("synthesis WAV is empty or not bytes")
    if len(wav_bytes) > policy.maximum_input_bytes:
        raise AudioFormatError("synthesis WAV exceeds the bounded input size")
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as reader:
            if reader.getcomptype() != "NONE":
                raise AudioFormatError("synthesis WAV must contain uncompressed PCM")
            sample_rate = reader.getframerate()
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            declared_frames = reader.getnframes()
            frames = reader.readframes(declared_frames + 1)
    except AudioPipelineError:
        raise
    except (EOFError, ValueError, wave.Error) as error:
        raise AudioFormatError("synthesis WAV container is corrupt") from error
    if (
        sample_rate != policy.sample_rate_hz
        or channels != policy.channels
        or sample_width != policy.sample_width_bytes
    ):
        raise AudioFormatError(
            "synthesis WAV must be 48 kHz stereo signed 16-bit PCM"
        )
    frame_width = channels * sample_width
    if not frames or len(frames) % frame_width:
        raise AudioFormatError("synthesis WAV PCM payload is empty or truncated")
    actual_frames = len(frames) // frame_width
    if actual_frames != declared_frames:
        raise AudioFormatError("synthesis WAV frame count differs from its payload")
    duration_ms = round(actual_frames * 1000 / sample_rate)
    if not policy.minimum_duration_ms <= duration_ms <= policy.maximum_duration_ms:
        raise AudioQualityError("synthesis WAV duration is outside segment bounds")
    sample_count = actual_frames * channels
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) != sample_count:
        raise AudioFormatError("synthesis WAV sample count is inconsistent")
    peak = max(abs(value) for value in samples)
    square_sum = sum(value * value for value in samples)
    rms = math.sqrt(square_sum / sample_count)
    clipped_count = sum(abs(value) >= 32767 for value in samples)
    clipped_fraction = clipped_count / sample_count
    inspection = AudioInspection(
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frame_count=actual_frames,
        duration_ms=duration_ms,
        peak_dbfs=round(_dbfs(float(peak)), 6),
        rms_dbfs=round(_dbfs(rms), 6),
        clipped_sample_count=clipped_count,
        clipped_fraction=round(clipped_fraction, 9),
        actual_sha256=hashlib.sha256(wav_bytes).hexdigest(),
    )
    return samples, inspection


def inspect_pcm_wav(
    wav_bytes: bytes,
    *,
    policy: AudioPipelinePolicy = DEFAULT_AUDIO_PIPELINE_POLICY,
    expected_duration_ms: int | None = None,
) -> AudioInspection:
    _samples, inspection = _decode_pcm_wav(wav_bytes, policy)
    if inspection.rms_dbfs <= policy.silence_rms_dbfs:
        raise AudioQualityError("synthesis WAV is silent or below the speech floor")
    if inspection.clipped_fraction > policy.maximum_clipped_fraction:
        raise AudioQualityError("synthesis WAV exceeds the clipping limit")
    if expected_duration_ms is not None:
        if type(expected_duration_ms) is not int or expected_duration_ms <= 0:
            raise AudioPipelineError("expected duration must be a positive exact integer")
        allowed_drift = max(
            policy.maximum_duration_drift_ms,
            round(expected_duration_ms * policy.maximum_duration_drift_ratio),
        )
        if abs(inspection.duration_ms - expected_duration_ms) > allowed_drift:
            raise AudioQualityError("synthesis WAV duration drift exceeds the frozen limit")
    return inspection


def short_chinese_duration_limit_ms(
    text: str,
    *,
    policy: ShortChineseDurationPolicy = DEFAULT_SHORT_CHINESE_DURATION_POLICY,
) -> int | None:
    """Return the calibrated ceiling for a short Chinese-only synthesis input.

    Mixed-language, numeric, emoji, or longer text stays outside this narrow
    gate.  Global PCM format, silence, clipping, and 180-second bounds continue
    to protect every synthesis result independently.
    """

    policy.validate()
    if type(text) is not str or not text:
        raise AudioPipelineError("spoken text must be a non-empty string")
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise AudioPipelineError("spoken text contains an invalid Unicode scalar") from error
    compact = "".join(character for character in text if not character.isspace())
    if not compact or len(compact) > policy.maximum_codepoints:
        return None
    if not any(_HAN_CODEPOINT.fullmatch(character) for character in compact):
        return None
    if any(
        _HAN_CODEPOINT.fullmatch(character) is None
        and character not in _SHORT_CHINESE_PUNCTUATION
        for character in compact
    ):
        return None
    onset_allowance_ms = (
        policy.ultrashort_onset_allowance_ms
        if len(compact) <= policy.ultrashort_maximum_codepoints
        else policy.onset_allowance_ms
    )
    return onset_allowance_ms + len(compact) * policy.per_codepoint_allowance_ms


def validate_synthesis_duration_for_text(
    text: str,
    duration_ms: int,
    *,
    policy: ShortChineseDurationPolicy = DEFAULT_SHORT_CHINESE_DURATION_POLICY,
) -> None:
    """Fail closed when a short Chinese Nano result has implausible duration."""

    if type(duration_ms) is not int or duration_ms <= 0:
        raise AudioPipelineError("synthesis duration must be a positive exact integer")
    limit_ms = short_chinese_duration_limit_ms(text, policy=policy)
    if limit_ms is not None and duration_ms > limit_ms:
        raise AudioQualityError(
            "synthesis WAV duration is implausible for short Chinese text"
        )


def _encode_pcm_wav(
    samples: array[int],
    *,
    sample_rate_hz: int,
    channels: int,
) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate_hz)
        encoded = array("h", samples)
        if sys.byteorder != "little":
            encoded.byteswap()
        writer.writeframes(encoded.tobytes())
    return output.getvalue()


def process_synthesis_wav(
    wav_bytes: bytes,
    *,
    policy: AudioPipelinePolicy = DEFAULT_AUDIO_PIPELINE_POLICY,
    expected_duration_ms: int | None = None,
    spoken_text: str | None = None,
) -> ProcessedPcmWav:
    samples, input_inspection = _decode_pcm_wav(wav_bytes, policy)
    if spoken_text is not None:
        validate_synthesis_duration_for_text(
            spoken_text,
            input_inspection.duration_ms,
        )
    inspect_pcm_wav(
        wav_bytes,
        policy=policy,
        expected_duration_ms=expected_duration_ms,
    )
    rms_linear = 32768.0 * (10.0 ** (input_inspection.rms_dbfs / 20.0))
    target_rms = 32768.0 * (10.0 ** (policy.target_rms_dbfs / 20.0))
    peak_linear = 32768.0 * (10.0 ** (policy.peak_limit_dbfs / 20.0))
    current_peak = 32768.0 * (10.0 ** (input_inspection.peak_dbfs / 20.0))
    gain = min(
        target_rms / max(rms_linear, 1.0),
        peak_linear / max(current_peak, 1.0),
        10.0 ** (policy.maximum_gain_db / 20.0),
    )
    applied_gain_db = 20.0 * math.log10(max(gain, 1e-12))
    frame_count = input_inspection.frame_count
    fade_frames = min(
        round(policy.sample_rate_hz * policy.seam_fade_ms / 1000),
        max(0, (frame_count - 1) // 2),
    )
    processed = array("h")
    for index, sample in enumerate(samples):
        frame = index // policy.channels
        fade = 1.0
        if fade_frames:
            fade = min(
                1.0,
                frame / fade_frames,
                (frame_count - 1 - frame) / fade_frames,
            )
        value = round(sample * gain * max(0.0, fade))
        processed.append(max(-32767, min(32767, value)))
    output_bytes = _encode_pcm_wav(
        processed,
        sample_rate_hz=policy.sample_rate_hz,
        channels=policy.channels,
    )
    output_inspection = inspect_pcm_wav(
        output_bytes,
        policy=policy,
        expected_duration_ms=input_inspection.duration_ms,
    )
    if output_inspection.duration_ms != input_inspection.duration_ms:
        raise AudioQualityError("audio processing changed the segment duration")
    return ProcessedPcmWav(
        wav_bytes=output_bytes,
        actual_sha256=output_inspection.actual_sha256,
        duration_ms=output_inspection.duration_ms,
        sample_rate_hz=policy.sample_rate_hz,
        channels=policy.channels,
        sample_width_bytes=policy.sample_width_bytes,
        input_inspection=input_inspection,
        output_inspection=output_inspection,
        applied_gain_db=round(applied_gain_db, 6),
        seam_fade_ms=policy.seam_fade_ms,
        processing_fingerprint=audio_processing_fingerprint(policy),
    )


__all__ = [
    "AUDIO_PIPELINE_VERSION",
    "AudioFormatError",
    "AudioInspection",
    "AudioPipelineError",
    "AudioPipelinePolicy",
    "AudioQualityError",
    "DEFAULT_AUDIO_PIPELINE_POLICY",
    "DEFAULT_SHORT_CHINESE_DURATION_POLICY",
    "ProcessedPcmWav",
    "SHORT_CHINESE_DURATION_POLICY_VERSION",
    "ShortChineseDurationPolicy",
    "audio_processing_fingerprint",
    "inspect_pcm_wav",
    "process_synthesis_wav",
    "short_chinese_duration_limit_ms",
    "validate_synthesis_duration_for_text",
]
