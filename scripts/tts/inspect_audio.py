#!/usr/bin/env python3
"""Inspect an uncompressed PCM WAV file and emit deterministic JSON metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import wave


SCHEMA_VERSION = "moss-tts-audio-inspection/1.0"
DEFAULT_SILENCE_THRESHOLD_DBFS = -50.0
READ_FRAMES = 65_536


class AudioInspectionError(ValueError):
    """Raised when the input cannot be inspected without ambiguity."""


def sha256_file(input_path: Path) -> str:
    digest = hashlib.sha256()
    with input_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_pcm_samples(raw: bytes, sample_width_bytes: int) -> list[int]:
    """Decode little-endian PCM samples; WAV 8-bit PCM is unsigned."""

    if len(raw) % sample_width_bytes:
        raise AudioInspectionError("PCM payload is not aligned to the sample width")
    if sample_width_bytes == 1:
        return [value - 128 for value in raw]
    if sample_width_bytes not in {2, 3, 4}:
        raise AudioInspectionError(
            f"unsupported PCM sample width: {sample_width_bytes} bytes"
        )
    return [
        int.from_bytes(
            raw[offset : offset + sample_width_bytes],
            byteorder="little",
            signed=True,
        )
        for offset in range(0, len(raw), sample_width_bytes)
    ]


def dbfs(value: float) -> float | None:
    if value <= 0:
        return None
    return round(20.0 * math.log10(value), 6)


def inspect_wav(
    input_path: Path,
    *,
    silence_threshold_dbfs: float = DEFAULT_SILENCE_THRESHOLD_DBFS,
) -> dict[str, object]:
    if not input_path.is_file():
        raise AudioInspectionError(f"input is not a file: {input_path}")
    if not -120.0 <= silence_threshold_dbfs <= 0.0:
        raise AudioInspectionError("silence threshold must be between -120 and 0 dBFS")

    before = input_path.stat()
    input_sha256 = sha256_file(input_path)
    sample_count = 0
    sum_samples = 0
    sum_squares = 0
    peak_abs = 0
    clipped_samples = 0
    silent_frames = 0

    try:
        with wave.open(str(input_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width_bytes = wav_file.getsampwidth()
            sample_rate_hz = wav_file.getframerate()
            declared_frame_count = wav_file.getnframes()
            compression_type = wav_file.getcomptype()
            compression_name = wav_file.getcompname()

            if compression_type != "NONE":
                raise AudioInspectionError(
                    f"compressed WAV is unsupported: {compression_type} ({compression_name})"
                )
            if channels <= 0 or sample_rate_hz <= 0:
                raise AudioInspectionError("WAV channel count and sample rate must be positive")
            if sample_width_bytes not in {1, 2, 3, 4}:
                raise AudioInspectionError(
                    f"unsupported PCM sample width: {sample_width_bytes} bytes"
                )

            bits_per_sample = sample_width_bytes * 8
            full_scale = 1 << (bits_per_sample - 1)
            positive_max = full_scale - 1
            negative_min = -full_scale
            silence_limit = full_scale * (10.0 ** (silence_threshold_dbfs / 20.0))
            decoded_frame_count = 0

            while True:
                raw = wav_file.readframes(READ_FRAMES)
                if not raw:
                    break
                samples = decode_pcm_samples(raw, sample_width_bytes)
                if len(samples) % channels:
                    raise AudioInspectionError(
                        "PCM payload is not aligned to the declared channel count"
                    )
                for offset in range(0, len(samples), channels):
                    frame = samples[offset : offset + channels]
                    decoded_frame_count += 1
                    if max(abs(value) for value in frame) <= silence_limit:
                        silent_frames += 1
                    for value in frame:
                        sample_count += 1
                        sum_samples += value
                        sum_squares += value * value
                        peak_abs = max(peak_abs, abs(value))
                        if value in {negative_min, positive_max}:
                            clipped_samples += 1
    except (EOFError, wave.Error) as error:
        raise AudioInspectionError(f"invalid or unsupported WAV: {error}") from error

    after = input_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AudioInspectionError("input changed while it was being inspected")
    if decoded_frame_count != declared_frame_count:
        raise AudioInspectionError(
            "decoded frame count does not match the WAV header: "
            f"{decoded_frame_count} != {declared_frame_count}"
        )

    duration_seconds = (
        decoded_frame_count / sample_rate_hz if sample_rate_hz else 0.0
    )
    peak_normalized = peak_abs / full_scale if sample_count else 0.0
    rms_normalized = (
        math.sqrt(sum_squares / sample_count) / full_scale if sample_count else 0.0
    )
    dc_offset_normalized = (
        (sum_samples / sample_count) / full_scale if sample_count else 0.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "source": {
            "file_name": input_path.name,
            "file_size_bytes": before.st_size,
            "sha256": input_sha256,
            "read_only_inspection": True,
        },
        "container": "WAV",
        "codec": "pcm_u8" if sample_width_bytes == 1 else "pcm_sle",
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "sample_width_bytes": sample_width_bytes,
        "bits_per_sample": bits_per_sample,
        "frame_count": decoded_frame_count,
        "sample_count": sample_count,
        "duration_seconds": round(duration_seconds, 9),
        "peak_abs_normalized": round(peak_normalized, 9),
        "peak_dbfs": dbfs(peak_normalized),
        "rms_normalized": round(rms_normalized, 9),
        "rms_dbfs": dbfs(rms_normalized),
        "dc_offset_normalized": round(dc_offset_normalized, 9),
        "silence_threshold_dbfs": round(silence_threshold_dbfs, 6),
        "silent_frame_count": silent_frames,
        "silent_frame_ratio": round(
            silent_frames / decoded_frame_count if decoded_frame_count else 0.0,
            9,
        ),
        "clipped_sample_count": clipped_samples,
        "clipped_sample_ratio": round(
            clipped_samples / sample_count if sample_count else 0.0,
            9,
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="uncompressed PCM WAV to inspect")
    parser.add_argument(
        "--silence-threshold-dbfs",
        type=float,
        default=DEFAULT_SILENCE_THRESHOLD_DBFS,
        help="a frame is silent when every channel is at or below this level (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSON to this path instead of stdout; cannot overwrite the input",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON instead of indented JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.output and args.output.resolve() == args.input.resolve():
            raise AudioInspectionError("output path must not overwrite the input WAV")
        payload = inspect_wav(
            args.input,
            silence_threshold_dbfs=args.silence_threshold_dbfs,
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
        if args.output:
            args.output.write_text(serialized + "\n", encoding="utf-8")
        else:
            print(serialized)
        return 0
    except (AudioInspectionError, OSError) as error:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            },
        }
        print(
            json.dumps(failure, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
