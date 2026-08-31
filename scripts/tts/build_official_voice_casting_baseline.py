#!/usr/bin/env python3
"""Build the 18-preset casting baseline from verified fixed-sentence WAVs.

This script does not call a model, network, database, or media store.  It only
accepts an operator-supplied, hash-closed source manifest and exactly 18 local
PCM WAV files.  The output contains objective measurements and deterministic
relative buckets; it never asks a human to label how a voice "sounds".
"""

from __future__ import annotations

from array import array
import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import statistics
import sys
import wave


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.narration.character_voice_matching import (
    ACOUSTIC_EXTRACTOR_SPEC,
    ACOUSTIC_EXTRACTOR_SPEC_SHA256,
    BASELINE_SCHEMA_VERSION,
    EXTRACTOR_SCHEMA_VERSION,
    canonical_sha256,
)
from backend.narration.official_presets import (
    OFFICIAL_PRESET_MANIFEST_PATH,
    OFFICIAL_PRESET_MANIFEST_SHA256,
    OFFICIAL_PRESET_MAX_NEW_FRAMES,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
    OFFICIAL_PRESET_SAMPLE_MODE,
    OFFICIAL_PRESETS,
)


SOURCE_SCHEMA_VERSION = "official-voice-casting-source/1"
SIDECAR_PROTOCOL_VERSION = "moss-tts-sidecar/1.1"
EXTRACTOR_SPEC = ACOUSTIC_EXTRACTOR_SPEC
EXTRACTOR_SPEC_SHA256 = ACOUSTIC_EXTRACTOR_SPEC_SHA256

_ROOT_KEYS = {
    "schema_version",
    "official_manifest",
    "source",
    "prompts",
    "items",
}
_MANIFEST_KEYS = {"repository", "revision", "path", "sha256"}
_SOURCE_KEYS = {
    "model_fingerprint_sha256",
    "model_revision",
    "sidecar_protocol_version",
    "sample_mode",
    "max_new_frames",
    "seed",
}
_ITEM_KEYS = {"preset_id", "audio_path", "audio_sha256"}
_PROMPT_KEYS = {"text_sha256", "codepoint_count"}


class BaselineBuildError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Measurement:
    preset_id: str
    language: str
    presentation: str
    source_audio_sha256: str
    sample_rate_hz: int
    duration_ms: int
    voiced_duration_ms: int
    pitch_hz_milli: int
    rms_dbfs_milli: int
    zero_crossing_rate_millionths: int
    periodicity_millionths: int
    crest_factor_milli: int


def _exact_object(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise BaselineBuildError(f"{label} fields changed")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_sha(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BaselineBuildError(f"{label} must be lowercase SHA-256")
    return value


def _load_input_manifest(path: Path) -> tuple[dict, bytes]:
    try:
        encoded = path.read_bytes()
        value = json.loads(encoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BaselineBuildError("source manifest is unreadable") from error
    root = _exact_object(value, _ROOT_KEYS, "source manifest")
    if root["schema_version"] != SOURCE_SCHEMA_VERSION:
        raise BaselineBuildError("source manifest schema changed")

    official = _exact_object(
        root["official_manifest"], _MANIFEST_KEYS, "official manifest"
    )
    if official != {
        "repository": OFFICIAL_PRESET_REPOSITORY,
        "revision": OFFICIAL_PRESET_REVISION,
        "path": OFFICIAL_PRESET_MANIFEST_PATH,
        "sha256": OFFICIAL_PRESET_MANIFEST_SHA256,
    }:
        raise BaselineBuildError("official manifest identity changed")

    source = _exact_object(root["source"], _SOURCE_KEYS, "source identity")
    if source != {
        "model_fingerprint_sha256": OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        "model_revision": OFFICIAL_PRESET_REVISION,
        "sidecar_protocol_version": SIDECAR_PROTOCOL_VERSION,
        "sample_mode": OFFICIAL_PRESET_SAMPLE_MODE,
        "max_new_frames": OFFICIAL_PRESET_MAX_NEW_FRAMES,
        "seed": OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
    }:
        raise BaselineBuildError("fixed Nano source identity changed")

    prompts = root["prompts"]
    expected_languages = {preset.language for preset in OFFICIAL_PRESETS}
    if type(prompts) is not dict or set(prompts) != expected_languages:
        raise BaselineBuildError("source prompts must cover the three languages")
    for language, prompt_value in prompts.items():
        prompt = _exact_object(prompt_value, _PROMPT_KEYS, f"{language} prompt")
        _valid_sha(prompt["text_sha256"], f"{language} prompt text")
        if (
            type(prompt["codepoint_count"]) is not int
            or not 1 <= prompt["codepoint_count"] <= 400
        ):
            raise BaselineBuildError("prompt codepoint_count is outside bounds")

    items = root["items"]
    if type(items) is not list or len(items) != len(OFFICIAL_PRESETS):
        raise BaselineBuildError("source must contain all 18 official recordings")
    for row_value, preset in zip(items, OFFICIAL_PRESETS, strict=True):
        row = _exact_object(row_value, _ITEM_KEYS, "source recording")
        if row["preset_id"] != preset.preset_id:
            raise BaselineBuildError("source recordings differ from manifest order")
        if (
            type(row["audio_path"]) is not str
            or not row["audio_path"]
            or Path(row["audio_path"]).is_absolute()
            or ".." in Path(row["audio_path"]).parts
        ):
            raise BaselineBuildError("source audio_path is unsafe")
        _valid_sha(row["audio_sha256"], "source audio")
    return root, encoded


def _pcm_mono(audio: bytes) -> tuple[int, list[int]]:
    try:
        with wave.open(BytesIO(audio), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frame_count = reader.getnframes()
            compression = reader.getcomptype()
            frames = reader.readframes(frame_count + 1)
    except (EOFError, ValueError, wave.Error) as error:
        raise BaselineBuildError("source WAV is unreadable") from error
    if (
        channels not in {1, 2}
        or sample_width != 2
        or compression != "NONE"
        or not 8_000 <= sample_rate <= 192_000
        or frame_count < sample_rate // 10
        or frame_count > sample_rate * 120
        or len(frames) != frame_count * channels * sample_width
    ):
        raise BaselineBuildError("source WAV is outside the frozen PCM bounds")
    values = array("h")
    values.frombytes(frames)
    if sys.byteorder != "little":
        values.byteswap()
    if channels == 1:
        return sample_rate, list(values)
    return sample_rate, [
        (int(values[index]) + int(values[index + 1])) // 2
        for index in range(0, len(values), 2)
    ]


def _dbfs_milli(value: float) -> int:
    if value <= 0:
        return -120_000
    return max(-120_000, min(0, round(20_000 * math.log10(value / 32768.0))))


def _active_samples(samples: list[int], sample_rate: int) -> tuple[list[int], int]:
    frame_size = max(1, sample_rate * EXTRACTOR_SPEC["active_frame_ms"] // 1000)
    frames: list[tuple[list[int], float]] = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if len(frame) < frame_size // 2:
            continue
        rms = math.sqrt(sum(value * value for value in frame) / len(frame))
        frames.append((frame, rms))
    if not frames:
        raise BaselineBuildError("source WAV has no complete analysis frame")
    peak_rms = max(rms for _, rms in frames)
    floor = 32768.0 * (10 ** (EXTRACTOR_SPEC["active_floor_dbfs_milli"] / 20_000))
    relative = peak_rms * (
        10 ** (EXTRACTOR_SPEC["active_relative_db_milli"] / 20_000)
    )
    threshold = max(floor, relative)
    active_frames = [frame for frame, rms in frames if rms >= threshold]
    if not active_frames:
        raise BaselineBuildError("source WAV contains no objectively active frame")
    active = [value for frame in active_frames for value in frame]
    return active, sum(len(frame) for frame in active_frames)


def _resample_to_8k(samples: list[int], sample_rate: int) -> list[float]:
    target = EXTRACTOR_SPEC["pitch_resample_hz"]
    if sample_rate == target:
        return [float(value) for value in samples]
    length = max(1, len(samples) * target // sample_rate)
    result: list[float] = []
    for index in range(length):
        position = index * sample_rate / target
        left = min(len(samples) - 1, int(position))
        right = min(len(samples) - 1, left + 1)
        fraction = position - left
        result.append(samples[left] * (1.0 - fraction) + samples[right] * fraction)
    return result


def _pitch_and_periodicity(samples: list[int], sample_rate: int) -> tuple[int, int]:
    series = _resample_to_8k(samples, sample_rate)
    target = EXTRACTOR_SPEC["pitch_resample_hz"]
    window = target * EXTRACTOR_SPEC["pitch_window_ms"] // 1000
    hop = target * EXTRACTOR_SPEC["pitch_hop_ms"] // 1000
    minimum_lag = target // EXTRACTOR_SPEC["pitch_max_hz"]
    maximum_lag = target // EXTRACTOR_SPEC["pitch_min_hz"]
    starts = list(range(0, max(0, len(series) - window + 1), hop))
    maximum_windows = EXTRACTOR_SPEC["pitch_max_windows"]
    if len(starts) > maximum_windows:
        starts = [
            starts[round(index * (len(starts) - 1) / (maximum_windows - 1))]
            for index in range(maximum_windows)
        ]
    pitches: list[float] = []
    correlations: list[float] = []
    for start in starts:
        frame = series[start : start + window]
        mean = sum(frame) / len(frame)
        centered = [value - mean for value in frame]
        energy = sum(value * value for value in centered)
        if energy <= 0:
            continue
        best_lag = 0
        best_correlation = -1.0
        for lag in range(minimum_lag, maximum_lag + 1):
            left = centered[:-lag]
            right = centered[lag:]
            numerator = sum(a * b for a, b in zip(left, right, strict=True))
            left_energy = sum(value * value for value in left)
            right_energy = sum(value * value for value in right)
            denominator = math.sqrt(left_energy * right_energy)
            correlation = numerator / denominator if denominator else -1.0
            if correlation > best_correlation:
                best_lag = lag
                best_correlation = correlation
        if (
            best_lag
            and round(best_correlation * 1_000_000)
            >= EXTRACTOR_SPEC["pitch_min_periodicity_millionths"]
        ):
            pitches.append(target / best_lag)
            correlations.append(best_correlation)
    if not pitches:
        raise BaselineBuildError("source WAV has no measurable periodic pitch")
    return (
        round(statistics.median(pitches) * 1000),
        max(0, min(1_000_000, round(statistics.median(correlations) * 1_000_000))),
    )


def _measure(
    *, preset_id: str, language: str, presentation: str, audio: bytes
) -> Measurement:
    sample_rate, samples = _pcm_mono(audio)
    active, active_count = _active_samples(samples, sample_rate)
    pitch, periodicity = _pitch_and_periodicity(active, sample_rate)
    rms = math.sqrt(sum(value * value for value in active) / len(active))
    peak = max(abs(value) for value in active)
    crossings = sum(
        (left < 0 <= right) or (left >= 0 > right)
        for left, right in zip(active, active[1:])
    )
    return Measurement(
        preset_id=preset_id,
        language=language,
        presentation=presentation,
        source_audio_sha256=_sha256_bytes(audio),
        sample_rate_hz=sample_rate,
        duration_ms=round(len(samples) * 1000 / sample_rate),
        voiced_duration_ms=round(active_count * 1000 / sample_rate),
        pitch_hz_milli=pitch,
        rms_dbfs_milli=_dbfs_milli(rms),
        zero_crossing_rate_millionths=round(
            crossings * 1_000_000 / max(1, len(active) - 1)
        ),
        periodicity_millionths=periodicity,
        crest_factor_milli=round(peak * 1000 / max(rms, 1e-12)),
    )


def _midrank_bucket(value: int, cohort: list[int]) -> int:
    if len(cohort) < 2:
        return 0
    below = sum(item < value for item in cohort)
    equal = sum(item == value for item in cohort)
    percentile = (below + (equal - 1) / 2) / (len(cohort) - 1)
    return max(-2, min(2, round(percentile * 4 - 2)))


def _texture(
    *, energy: int, zcr: int, periodicity: int, crest: int
) -> str:
    if energy <= -2:
        return "soft"
    if periodicity <= -2 and zcr >= 1:
        return "airy"
    if periodicity <= -1 and zcr <= -1:
        return "husky"
    if energy >= 2 and periodicity >= 0:
        return "firm"
    if zcr >= 2:
        return "bright"
    if zcr <= -2:
        return "dark"
    if periodicity >= 1 or crest <= -1:
        return "clear"
    return "warm"


def build_baseline(
    *, input_manifest_path: Path, audio_root: Path, implementation_path: Path
) -> dict[str, object]:
    source_manifest, source_manifest_bytes = _load_input_manifest(input_manifest_path)
    root = audio_root.resolve(strict=True)
    if not root.is_dir():
        raise BaselineBuildError("audio root must be a directory")
    measurements: list[Measurement] = []
    for row, preset in zip(
        source_manifest["items"], OFFICIAL_PRESETS, strict=True
    ):
        candidate = root.joinpath(row["audio_path"])
        if candidate.is_symlink():
            raise BaselineBuildError("source audio cannot be a symlink")
        path = candidate.resolve(strict=True)
        if not path.is_file() or root not in path.parents:
            raise BaselineBuildError("source audio escaped the fixed root")
        audio = path.read_bytes()
        actual_sha256 = _sha256_bytes(audio)
        if actual_sha256 != row["audio_sha256"]:
            raise BaselineBuildError("source audio SHA-256 changed")
        presentation = "masculine" if preset.group.endswith("Male") else "feminine"
        measurements.append(
            _measure(
                preset_id=preset.preset_id,
                language=preset.language,
                presentation=presentation,
                audio=audio,
            )
        )

    pitch_cohorts = {
        presentation: [
            item.pitch_hz_milli
            for item in measurements
            if item.presentation == presentation
        ]
        for presentation in {item.presentation for item in measurements}
    }
    language_metrics = {
        language: {
            "pace": [
                -item.voiced_duration_ms
                for item in measurements
                if item.language == language
            ],
            "energy": [item.rms_dbfs_milli for item in measurements if item.language == language],
            "zcr": [
                item.zero_crossing_rate_millionths
                for item in measurements
                if item.language == language
            ],
            "periodicity": [
                item.periodicity_millionths
                for item in measurements
                if item.language == language
            ],
            "crest": [
                item.crest_factor_milli
                for item in measurements
                if item.language == language
            ],
        }
        for language in {item.language for item in measurements}
    }

    output_rows: list[dict[str, object]] = []
    for item in measurements:
        cohort = language_metrics[item.language]
        pitch = _midrank_bucket(
            item.pitch_hz_milli, pitch_cohorts[item.presentation]
        )
        pace = _midrank_bucket(-item.voiced_duration_ms, cohort["pace"])
        energy = _midrank_bucket(item.rms_dbfs_milli, cohort["energy"])
        zcr = _midrank_bucket(item.zero_crossing_rate_millionths, cohort["zcr"])
        periodicity = _midrank_bucket(
            item.periodicity_millionths, cohort["periodicity"]
        )
        crest = _midrank_bucket(item.crest_factor_milli, cohort["crest"])
        output_rows.append(
            {
                "preset_id": item.preset_id,
                "language": item.language,
                "presentation": item.presentation,
                "source_audio_sha256": item.source_audio_sha256,
                "sample_rate_hz": item.sample_rate_hz,
                "duration_ms": item.duration_ms,
                "voiced_duration_ms": item.voiced_duration_ms,
                "pitch_hz_milli": item.pitch_hz_milli,
                "rms_dbfs_milli": item.rms_dbfs_milli,
                "zero_crossing_rate_millionths": item.zero_crossing_rate_millionths,
                "periodicity_millionths": item.periodicity_millionths,
                "crest_factor_milli": item.crest_factor_milli,
                "pitch": pitch,
                "pace": pace,
                "energy": energy,
                "texture": _texture(
                    energy=energy,
                    zcr=zcr,
                    periodicity=periodicity,
                    crest=crest,
                ),
            }
        )

    audio_hashes = [item.source_audio_sha256 for item in measurements]
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "status": "ready",
        "reason_code": None,
        "official_manifest": source_manifest["official_manifest"],
        "extractor": {
            "schema_version": EXTRACTOR_SCHEMA_VERSION,
            "spec_sha256": EXTRACTOR_SPEC_SHA256,
            "implementation_sha256": _sha256_bytes(implementation_path.read_bytes()),
        },
        "source": {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "kind": "nano_fixed_short_sentence",
            **source_manifest["source"],
            "input_manifest_sha256": _sha256_bytes(source_manifest_bytes),
            "aggregate_audio_sha256": canonical_sha256(audio_hashes),
            "prompts": source_manifest["prompts"],
        },
        "items": output_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_baseline(
        input_manifest_path=args.input_manifest,
        audio_root=args.audio_root,
        implementation_path=Path(__file__).resolve(),
    )
    encoded = json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaselineBuildError as error:
        print(f"baseline build failed: {error}", file=sys.stderr)
        raise SystemExit(2)
