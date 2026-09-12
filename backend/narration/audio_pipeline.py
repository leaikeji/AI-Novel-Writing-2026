"""Deterministic, database-free validation and seam-safe PCM processing.

Qwen TTS Provider output is normalized at this boundary to the existing
48 kHz stereo media contract.  The module validates complete containers and
samples before applying one frozen gain/fade policy.  It performs no database,
filesystem, subprocess, or network operation.
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


AUDIO_PIPELINE_VERSION = "narration-audio-pipeline/2"
TTS_AUDIO_NORMALIZATION_VERSION = "qwen-tts-audio-normalization/1"
SHORT_CHINESE_DURATION_POLICY_VERSION = "qwen-tts-short-chinese-duration/1"

# ITU-R BS.1770 K-weighting coefficients for the pipeline's fixed 48 kHz rate.
# Keeping them local and frozen avoids adding a native DSP dependency to the
# Provider adapter while still measuring programme loudness instead of raw PCM energy.
_K_WEIGHTING_SHELF_B = (
    1.53512485958697,
    -2.69169618940638,
    1.19839281085285,
)
_K_WEIGHTING_SHELF_A = (1.0, -1.69065929318241, 0.73248077421585)
_K_WEIGHTING_HIGHPASS_B = (1.0, -2.0, 1.0)
_K_WEIGHTING_HIGHPASS_A = (1.0, -1.99004745483398, 0.99007225036621)
_LOUDNESS_OFFSET_DB = -0.691
_LOUDNESS_ABSOLUTE_GATE_LUFS = -70.0
_LOUDNESS_RELATIVE_GATE_DB = -10.0
_LOUDNESS_BLOCK_MS = 400
_LOUDNESS_HOP_MS = 100

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


class ShortChineseDurationError(AudioQualityError):
    """A bounded short-Chinese duration failure with no source text attached."""

    def __init__(
        self,
        *,
        actual_duration_ms: int,
        allowed_duration_ms: int,
        evaluated_codepoint_count: int,
    ) -> None:
        super().__init__(
            "synthesis WAV duration is implausible for short Chinese text"
        )
        self.actual_duration_ms = actual_duration_ms
        self.allowed_duration_ms = allowed_duration_ms
        self.evaluated_codepoint_count = evaluated_codepoint_count
        self.policy_version = SHORT_CHINESE_DURATION_POLICY_VERSION


def audio_validation_failure_evidence(error: BaseException) -> dict[str, object] | None:
    """Return the shared bounded diagnostic, never arbitrary exception text."""

    if not isinstance(error, (AudioFormatError, AudioQualityError)):
        return None
    reasons = {
        "synthesis WAV is empty or not bytes": "WAV_EMPTY_OR_NOT_BYTES",
        "synthesis WAV exceeds the bounded input size": "WAV_INPUT_TOO_LARGE",
        "synthesis WAV must contain uncompressed PCM": "WAV_NOT_PCM",
        "synthesis WAV container is corrupt": "WAV_CONTAINER_CORRUPT",
        "synthesis WAV must be 48 kHz stereo signed 16-bit PCM": "WAV_FORMAT_MISMATCH",
        "synthesis WAV metadata differs from the Provider result": "WAV_METADATA_MISMATCH",
        "synthesis WAV Provider format is unsupported": "WAV_FORMAT_MISMATCH",
        "synthesis WAV PCM payload is empty or truncated": "WAV_PAYLOAD_EMPTY_OR_TRUNCATED",
        "synthesis WAV frame count differs from its payload": "WAV_FRAME_COUNT_MISMATCH",
        "synthesis WAV duration is outside segment bounds": "WAV_DURATION_OUT_OF_BOUNDS",
        "synthesis WAV sample count is inconsistent": "WAV_SAMPLE_COUNT_MISMATCH",
        "synthesis WAV is silent or below the speech floor": "WAV_SILENT",
        "synthesis WAV exceeds the clipping limit": "WAV_CLIPPING_LIMIT_EXCEEDED",
        "synthesis WAV duration drift exceeds the frozen limit": "WAV_DURATION_DRIFT",
        "synthesis WAV duration is implausible for short Chinese text": "SHORT_CHINESE_DURATION_IMPLAUSIBLE",
        "synthesis WAV has no measurable programme loudness": "WAV_LOUDNESS_UNMEASURABLE",
        "audio processing changed the segment duration": "POSTPROCESS_DURATION_CHANGED",
    }
    evidence: dict[str, object] = {
        "schema_version": "narration-audio-validation-failure/1",
        "reason_code": reasons.get(str(error), "AUDIO_VALIDATION_UNKNOWN"),
    }
    if (
        isinstance(error, ShortChineseDurationError)
        and type(error.actual_duration_ms) is int
        and type(error.allowed_duration_ms) is int
        and type(error.evaluated_codepoint_count) is int
        and error.actual_duration_ms > error.allowed_duration_ms > 0
        and 0 < error.evaluated_codepoint_count
        <= DEFAULT_SHORT_CHINESE_DURATION_POLICY.maximum_codepoints
        and error.policy_version == SHORT_CHINESE_DURATION_POLICY_VERSION
    ):
        evidence.update(
            {
                "actual_duration_ms": error.actual_duration_ms,
                "allowed_duration_ms": error.allowed_duration_ms,
                "evaluated_codepoint_count": error.evaluated_codepoint_count,
                "policy_version": error.policy_version,
            }
        )
    return evidence


@dataclass(frozen=True, slots=True)
class ShortChineseDurationPolicy:
    """Conservative duration ceiling for short Chinese TTS outputs.

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
    target_loudness_lufs: float = -18.0
    maximum_gain_db: float = 18.0
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
        if not -60.0 <= self.target_loudness_lufs < 0.0:
            raise AudioPipelineError("target loudness must be between -60 and 0 LUFS")
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
    integrated_loudness_lufs: float
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
    loudness_target_limited: bool
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


def _integrated_loudness_lufs(
    samples: array[int],
    *,
    sample_rate_hz: int,
    channels: int,
) -> float:
    """Measure gated K-weighted programme loudness without native dependencies."""

    if sample_rate_hz != 48_000:
        raise AudioPipelineError("programme loudness coefficients require 48 kHz PCM")
    frame_count = len(samples) // channels
    hop_frames = round(sample_rate_hz * _LOUDNESS_HOP_MS / 1000)
    block_hops = _LOUDNESS_BLOCK_MS // _LOUDNESS_HOP_MS
    # Direct-form state is kept in fixed channel arrays. Avoiding a new state
    # object for every sample keeps this bounded pass cheap for long segments.
    shelf_x1 = [0.0] * channels
    shelf_x2 = [0.0] * channels
    shelf_y1 = [0.0] * channels
    shelf_y2 = [0.0] * channels
    highpass_x1 = [0.0] * channels
    highpass_x2 = [0.0] * channels
    highpass_y1 = [0.0] * channels
    highpass_y2 = [0.0] * channels
    hop_square_sums: list[tuple[float, int]] = []
    square_sum = 0.0
    frames_in_hop = 0

    sb0, sb1, sb2 = _K_WEIGHTING_SHELF_B
    _sa0, sa1, sa2 = _K_WEIGHTING_SHELF_A
    hb0, hb1, hb2 = _K_WEIGHTING_HIGHPASS_B
    _ha0, ha1, ha2 = _K_WEIGHTING_HIGHPASS_A
    for frame in range(frame_count):
        offset = frame * channels
        for channel in range(channels):
            sample = samples[offset + channel] / 32768.0
            shelf = (
                sb0 * sample
                + sb1 * shelf_x1[channel]
                + sb2 * shelf_x2[channel]
                - sa1 * shelf_y1[channel]
                - sa2 * shelf_y2[channel]
            )
            shelf_x2[channel] = shelf_x1[channel]
            shelf_x1[channel] = sample
            shelf_y2[channel] = shelf_y1[channel]
            shelf_y1[channel] = shelf
            weighted = (
                hb0 * shelf
                + hb1 * highpass_x1[channel]
                + hb2 * highpass_x2[channel]
                - ha1 * highpass_y1[channel]
                - ha2 * highpass_y2[channel]
            )
            highpass_x2[channel] = highpass_x1[channel]
            highpass_x1[channel] = shelf
            highpass_y2[channel] = highpass_y1[channel]
            highpass_y1[channel] = weighted
            square_sum += weighted * weighted
        frames_in_hop += 1
        if frames_in_hop == hop_frames:
            hop_square_sums.append((square_sum, frames_in_hop))
            square_sum = 0.0
            frames_in_hop = 0
    if frames_in_hop:
        hop_square_sums.append((square_sum, frames_in_hop))

    block_energies: list[float] = []
    for start in range(max(0, len(hop_square_sums) - block_hops + 1)):
        window = hop_square_sums[start : start + block_hops]
        window_frames = sum(item[1] for item in window)
        if window_frames != hop_frames * block_hops:
            continue
        block_energies.append(sum(item[0] for item in window) / window_frames)
    if not block_energies:
        total_frames = sum(item[1] for item in hop_square_sums)
        if total_frames:
            block_energies.append(
                sum(item[0] for item in hop_square_sums) / total_frames
            )

    absolutely_gated = [
        energy
        for energy in block_energies
        if energy > 0.0
        and _LOUDNESS_OFFSET_DB + 10.0 * math.log10(energy)
        >= _LOUDNESS_ABSOLUTE_GATE_LUFS
    ]
    if not absolutely_gated:
        return -120.0
    ungated_loudness = _LOUDNESS_OFFSET_DB + 10.0 * math.log10(
        sum(absolutely_gated) / len(absolutely_gated)
    )
    relative_gate = ungated_loudness + _LOUDNESS_RELATIVE_GATE_DB
    relatively_gated = [
        energy
        for energy in absolutely_gated
        if _LOUDNESS_OFFSET_DB + 10.0 * math.log10(energy) >= relative_gate
    ]
    return max(
        -120.0,
        _LOUDNESS_OFFSET_DB
        + 10.0 * math.log10(sum(relatively_gated) / len(relatively_gated)),
    )


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
        integrated_loudness_lufs=round(
            _integrated_loudness_lufs(
                samples,
                sample_rate_hz=sample_rate,
                channels=channels,
            ),
            6,
        ),
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
    _validate_inspection(
        inspection,
        policy=policy,
        expected_duration_ms=expected_duration_ms,
    )
    return inspection


def _validate_inspection(
    inspection: AudioInspection,
    *,
    policy: AudioPipelinePolicy,
    expected_duration_ms: int | None,
) -> None:
    if inspection.rms_dbfs <= policy.silence_rms_dbfs:
        raise AudioQualityError("synthesis WAV is silent or below the speech floor")
    if inspection.integrated_loudness_lufs <= _LOUDNESS_ABSOLUTE_GATE_LUFS:
        raise AudioQualityError("synthesis WAV has no measurable programme loudness")
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

    evaluation = _short_chinese_duration_evaluation(text, policy=policy)
    return evaluation[0] if evaluation is not None else None


def _short_chinese_duration_evaluation(
    text: str,
    *,
    policy: ShortChineseDurationPolicy,
) -> tuple[int, int] | None:
    """Return the duration ceiling and counted codepoints without retaining text."""

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
    return (
        onset_allowance_ms + len(compact) * policy.per_codepoint_allowance_ms,
        len(compact),
    )


def validate_synthesis_duration_for_text(
    text: str,
    duration_ms: int,
    *,
    policy: ShortChineseDurationPolicy = DEFAULT_SHORT_CHINESE_DURATION_POLICY,
) -> None:
    """Fail closed when a short Chinese TTS result has implausible duration."""

    if type(duration_ms) is not int or duration_ms <= 0:
        raise AudioPipelineError("synthesis duration must be a positive exact integer")
    evaluation = _short_chinese_duration_evaluation(text, policy=policy)
    if evaluation is not None and duration_ms > evaluation[0]:
        raise ShortChineseDurationError(
            actual_duration_ms=duration_ms,
            allowed_duration_ms=evaluation[0],
            evaluated_codepoint_count=evaluation[1],
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


def _normalize_provider_pcm_wav(
    wav_bytes: bytes,
    *,
    declared_sample_rate_hz: int,
    declared_channels: int,
    declared_sample_width_bytes: int,
    policy: AudioPipelinePolicy,
) -> bytes:
    """Normalize the two frozen Qwen Provider WAV shapes to the media shape."""

    policy.validate()
    declared = (
        declared_sample_rate_hz,
        declared_channels,
        declared_sample_width_bytes,
    )
    if any(type(value) is not int or value <= 0 for value in declared):
        raise AudioFormatError("synthesis WAV metadata differs from the Provider result")
    if type(wav_bytes) is not bytes or not wav_bytes:
        raise AudioFormatError("synthesis WAV is empty or not bytes")
    if len(wav_bytes) > policy.maximum_input_bytes:
        raise AudioFormatError("synthesis WAV exceeds the bounded input size")
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as reader:
            if reader.getcomptype() != "NONE":
                raise AudioFormatError("synthesis WAV must contain uncompressed PCM")
            actual = (
                reader.getframerate(),
                reader.getnchannels(),
                reader.getsampwidth(),
            )
            declared_frames = reader.getnframes()
            frames = reader.readframes(declared_frames + 1)
    except AudioPipelineError:
        raise
    except (EOFError, ValueError, wave.Error) as error:
        raise AudioFormatError("synthesis WAV container is corrupt") from error
    if actual != declared:
        raise AudioFormatError("synthesis WAV metadata differs from the Provider result")
    if actual == (policy.sample_rate_hz, policy.channels, policy.sample_width_bytes):
        return wav_bytes
    if actual != (24_000, 1, 2) or policy.sample_rate_hz != 48_000 or policy.channels != 2:
        raise AudioFormatError("synthesis WAV Provider format is unsupported")
    if not frames or len(frames) % 2:
        raise AudioFormatError("synthesis WAV PCM payload is empty or truncated")
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) != declared_frames:
        raise AudioFormatError("synthesis WAV frame count differs from its payload")

    # Linear 2x interpolation preserves duration and avoids a new native DSP
    # dependency.  Stereo duplication keeps the established media/transcoding
    # contract stable while the Provider boundary remains 24 kHz mono.
    normalized = array("h")
    for index, sample in enumerate(samples):
        following = samples[index + 1] if index + 1 < len(samples) else sample
        midpoint = round((sample + following) / 2)
        normalized.extend((sample, sample, midpoint, midpoint))
    return _encode_pcm_wav(
        normalized,
        sample_rate_hz=policy.sample_rate_hz,
        channels=policy.channels,
    )


def process_provider_synthesis_wav(
    wav_bytes: bytes,
    *,
    declared_sample_rate_hz: int,
    declared_channels: int,
    declared_sample_width_bytes: int,
    policy: AudioPipelinePolicy = DEFAULT_AUDIO_PIPELINE_POLICY,
    expected_duration_ms: int | None = None,
    spoken_text: str | None = None,
) -> ProcessedPcmWav:
    """Validate Provider metadata, normalize Qwen WAV, and run the media policy."""

    normalized = _normalize_provider_pcm_wav(
        wav_bytes,
        declared_sample_rate_hz=declared_sample_rate_hz,
        declared_channels=declared_channels,
        declared_sample_width_bytes=declared_sample_width_bytes,
        policy=policy,
    )
    return process_synthesis_wav(
        normalized,
        policy=policy,
        expected_duration_ms=expected_duration_ms,
        spoken_text=spoken_text,
    )


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
    _validate_inspection(
        input_inspection,
        policy=policy,
        expected_duration_ms=expected_duration_ms,
    )
    peak_linear = 32768.0 * (10.0 ** (policy.peak_limit_dbfs / 20.0))
    current_peak = 32768.0 * (10.0 ** (input_inspection.peak_dbfs / 20.0))
    loudness_gain = 10.0 ** (
        (policy.target_loudness_lufs - input_inspection.integrated_loudness_lufs)
        / 20.0
    )
    gain = min(
        loudness_gain,
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
        loudness_target_limited=gain < loudness_gain - 1e-12,
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
    "TTS_AUDIO_NORMALIZATION_VERSION",
    "ShortChineseDurationPolicy",
    "audio_processing_fingerprint",
    "audio_validation_failure_evidence",
    "inspect_pcm_wav",
    "process_synthesis_wav",
    "process_provider_synthesis_wav",
    "short_chinese_duration_limit_ms",
    "validate_synthesis_duration_for_text",
]
