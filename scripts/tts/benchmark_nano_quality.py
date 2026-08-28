#!/usr/bin/env python3
"""Run the frozen T0-C MOSS-TTS-Nano quality benchmark.

The driver is deliberately download-free.  A real run requires explicit local
source, model and media paths and reuses the frozen T0-B managed worker.  The evidence directory receives only a
contract-valid metrics JSON and a listening template; generated/reference audio,
model files and raw fixture requests stay outside the repository.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import uuid
import wave


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INSPECT_AUDIO_PATH = REPOSITORY_ROOT / "scripts" / "tts" / "inspect_audio.py"
RESULT_SCHEMA = "moss-tts-benchmark-result/1.0"
MANIFEST_SCHEMA = "moss-tts-benchmark-manifest/1.0"
AUTHORIZED_SCHEMA = "moss-tts-authorized-texts/1.0"
MANAGED_WORKER_PATH = REPOSITORY_ROOT / "scripts" / "tts" / "benchmark_nano_topologies.py"
SEGMENT_SEPARATOR = "\n<SEGMENT>\n"
HASH_LENGTH = 64
REFERENCE_DURATIONS = {3, 5, 8, 12}
REFERENCE_AUDIO_FORMAT = {
    "container": "WAV",
    "codec": "pcm_sle",
    "sample_rate_hz": 48_000,
    "channels": 2,
    "sample_width_bytes": 2,
}
QUALITY_MATRIX_CASE_IDS = (
    "narration-neutral",
    "dialogue-explicit-speaker",
    "dialogue-two-person",
    "dialogue-multi-person",
    "dialogue-omitted-subject",
    "inner-monologue",
    "anonymous-young",
    "anonymous-middle-aged",
    "anonymous-elder",
    "anonymous-child",
    "crowd-voice",
    "markdown-input",
    "emoji-and-combining",
    "nested-quotes",
    "special-punctuation",
    "polyphonic-characters",
    "name-year-date",
    "mixed-chinese-english",
    "long-sentence",
    "independent-segment-seams",
)
DEFECT_KEYS = (
    "missing_text",
    "repeated_text",
    "voice_drift",
    "abnormal_pauses",
    "seam_artifacts",
    "clipping_or_noise",
    "loudness_inconsistent",
)
SENSITIVE_PATH_FLAGS = {
    "--output-dir": "<evidence-output-dir>",
    "--source-dir": "<source-dir>",
    "--model-dir": "<model-dir>",
    "--media-output-dir": "<media-output-dir>",
    "--worker-script": "<worker-script>",
}


class BenchmarkError(RuntimeError):
    """Raised when a benchmark input, path or worker response is unsafe."""


class SegmentRunnerError(BenchmarkError):
    """A redacted runner failure that can be represented as a case failure."""

    def __init__(self, code: str, message: str, *, category: str = "runner") -> None:
        super().__init__(message)
        self.code = code
        self.category = category


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != HASH_LENGTH:
        return False
    return all(character in "0123456789abcdef" for character in value)


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BenchmarkError(f"required JSON file is missing: {path.name}") from error
    except json.JSONDecodeError as error:
        raise BenchmarkError(f"invalid JSON in {path.name}: line {error.lineno}") from error
    if not isinstance(value, dict):
        raise BenchmarkError(f"top-level JSON must be an object: {path.name}")
    return value


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def resolve_authorized_texts(manifest_path: Path, declared_path: object) -> Path:
    if not isinstance(declared_path, str) or not declared_path:
        raise BenchmarkError("manifest authorized_texts.path must be a non-empty string")
    relative_path = Path(declared_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise BenchmarkError("manifest authorized_texts.path must be repository-relative and safe")
    candidates = [REPOSITORY_ROOT / relative_path, manifest_path.parent / relative_path]
    existing: list[Path] = []
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() not in [item.resolve() for item in existing]:
            existing.append(candidate)
    if not existing:
        raise BenchmarkError("declared authorized texts file does not exist")
    if len(existing) > 1:
        raise BenchmarkError("declared authorized texts path resolves ambiguously")
    return existing[0]


def validate_fixture_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = load_json_object(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise BenchmarkError(f"manifest schema must be {MANIFEST_SCHEMA}")
    fixture_set_id = manifest.get("fixture_set_id")
    if not isinstance(fixture_set_id, str) or not fixture_set_id:
        raise BenchmarkError("manifest fixture_set_id is missing")

    authorized_contract = manifest.get("authorized_texts")
    if not isinstance(authorized_contract, dict):
        raise BenchmarkError("manifest authorized_texts contract is missing")
    if authorized_contract.get("schema_version") != AUTHORIZED_SCHEMA:
        raise BenchmarkError(f"authorized text contract must require {AUTHORIZED_SCHEMA}")
    authorized_path = resolve_authorized_texts(manifest_path, authorized_contract.get("path"))
    authorized = load_json_object(authorized_path)
    if authorized.get("schema_version") != AUTHORIZED_SCHEMA:
        raise BenchmarkError(f"authorized text schema must be {AUTHORIZED_SCHEMA}")
    required_fixture_set = authorized_contract.get("required_fixture_set_id")
    if authorized.get("fixture_set_id") != required_fixture_set:
        raise BenchmarkError("authorized text fixture_set_id does not match the manifest contract")

    raw_texts = authorized.get("texts")
    if not isinstance(raw_texts, list) or not raw_texts:
        raise BenchmarkError("authorized texts must be a non-empty array")
    texts: dict[str, dict[str, Any]] = {}
    for index, raw_text in enumerate(raw_texts):
        if not isinstance(raw_text, dict):
            raise BenchmarkError(f"authorized text #{index} must be an object")
        text_id = raw_text.get("id")
        text = raw_text.get("text")
        declared_hash = raw_text.get("sha256")
        if not isinstance(text_id, str) or not text_id or text_id in texts:
            raise BenchmarkError(f"authorized text #{index} has a missing or duplicate id")
        if not isinstance(text, str) or not text:
            raise BenchmarkError(f"authorized text {text_id} has no exact text string")
        observed_hash = sha256_text(text)
        if declared_hash != observed_hash:
            raise BenchmarkError(f"authorized text hash drift: {text_id}")
        for metadata_key in ("author", "source", "license", "purpose"):
            if metadata_key not in raw_text:
                raise BenchmarkError(f"authorized text {text_id} is missing {metadata_key}")
        texts[text_id] = raw_text

    required_coverage = manifest.get("required_coverage")
    if (
        not isinstance(required_coverage, list)
        or not required_coverage
        or not all(isinstance(item, str) and item for item in required_coverage)
        or len(required_coverage) != len(set(required_coverage))
    ):
        raise BenchmarkError("required_coverage must be a unique non-empty string array")

    raw_references = manifest.get("reference_profiles")
    if not isinstance(raw_references, list):
        raise BenchmarkError("reference_profiles must be an array")
    references: dict[str, dict[str, Any]] = {}
    observed_durations: set[int] = set()
    for raw_reference in raw_references:
        if not isinstance(raw_reference, dict):
            raise BenchmarkError("reference profile must be an object")
        reference_id = raw_reference.get("id")
        duration = raw_reference.get("target_duration_seconds")
        if not isinstance(reference_id, str) or not reference_id or reference_id in references:
            raise BenchmarkError("reference profile id is missing or duplicated")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise BenchmarkError(f"reference profile {reference_id} has invalid target duration")
        if raw_reference.get("asset_state") == "placeholder_only":
            if raw_reference.get("asset_path") is not None or raw_reference.get("sha256") is not None:
                raise BenchmarkError(f"placeholder reference {reference_id} must not claim an asset")
        references[reference_id] = raw_reference
        observed_durations.add(duration)
    if not REFERENCE_DURATIONS.issubset(observed_durations):
        raise BenchmarkError("reference profiles must cover 3, 5, 8 and 12 seconds")

    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BenchmarkError("manifest cases must be a non-empty array")
    cases: dict[str, dict[str, Any]] = {}
    observed_coverage: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise BenchmarkError(f"case #{index} must be an object")
        case_id = raw_case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in cases:
            raise BenchmarkError(f"case #{index} has a missing or duplicate id")
        input_data = raw_case.get("input")
        if not isinstance(input_data, dict):
            raise BenchmarkError(f"case {case_id} has no input object")
        text_ids = input_data.get("text_ids")
        declared_hashes = input_data.get("text_sha256")
        if (
            not isinstance(text_ids, list)
            or not text_ids
            or not isinstance(declared_hashes, list)
            or len(text_ids) != len(declared_hashes)
        ):
            raise BenchmarkError(f"case {case_id} has invalid text id/hash arrays")
        exact_texts: list[str] = []
        observed_hashes: list[str] = []
        for text_id in text_ids:
            if not isinstance(text_id, str) or text_id not in texts:
                raise BenchmarkError(f"case {case_id} references unknown text id")
            exact_texts.append(str(texts[text_id]["text"]))
            observed_hashes.append(str(texts[text_id]["sha256"]))
        if declared_hashes != observed_hashes:
            raise BenchmarkError(f"case text hash drift: {case_id}")
        combined = sha256_text(SEGMENT_SEPARATOR.join(exact_texts))
        if input_data.get("combined_sha256") != combined:
            raise BenchmarkError(f"case combined hash drift: {case_id}")
        reference_id = raw_case.get("reference_profile_id")
        if reference_id is not None and reference_id not in references:
            raise BenchmarkError(f"case {case_id} references an unknown reference profile")
        covers = raw_case.get("covers")
        if not isinstance(covers, list) or not covers or not all(isinstance(item, str) for item in covers):
            raise BenchmarkError(f"case {case_id} has invalid coverage")
        observed_coverage.update(covers)
        cases[case_id] = raw_case

    missing_coverage = set(required_coverage) - observed_coverage
    unknown_coverage = observed_coverage - set(required_coverage)
    if missing_coverage:
        raise BenchmarkError("manifest coverage is incomplete: " + ", ".join(sorted(missing_coverage)))
    if unknown_coverage:
        raise BenchmarkError("manifest cases declare unknown coverage: " + ", ".join(sorted(unknown_coverage)))

    privacy = manifest.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("fixture_only") is not True:
        raise BenchmarkError("manifest privacy must require fixture_only=true")
    result_contract = manifest.get("result_contract")
    if not isinstance(result_contract, dict) or result_contract.get("schema_version") != RESULT_SCHEMA:
        raise BenchmarkError(f"manifest result contract must be {RESULT_SCHEMA}")
    return manifest, texts, cases


def parse_key_value(items: list[str], flag_name: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key or not value or key in parsed:
            raise BenchmarkError(f"{flag_name} requires unique PROFILE=VALUE entries")
        parsed[key] = value
    return parsed


def relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_real_paths(args: argparse.Namespace) -> None:
    required_paths = {
        "--source-dir": args.source_dir,
        "--model-dir": args.model_dir,
        "--media-output-dir": args.media_output_dir,
        "--worker-script": args.worker_script,
    }
    missing = [flag for flag, value in required_paths.items() if value is None]
    if missing:
        raise BenchmarkError("real execution requires explicit " + ", ".join(missing))
    if not args.model_revision or not args.source_revision:
        raise BenchmarkError("real execution requires --model-revision and --source-revision")
    if args.cpu_threads <= 0:
        raise BenchmarkError("--cpu-threads must be positive")
    if args.case_timeout_seconds <= 0:
        raise BenchmarkError("--case-timeout-seconds must be positive")
    if args.case_timeout_seconds != 600.0:
        raise BenchmarkError("the frozen managed worker request timeout is exactly 600 seconds")

    source_dir = args.source_dir.resolve()
    model_dir = args.model_dir.resolve()
    media_dir = args.media_output_dir.resolve()
    evidence_dir = args.output_dir.resolve()
    worker_script = args.worker_script.resolve()
    if not source_dir.is_dir():
        raise BenchmarkError("source directory does not exist")
    if not model_dir.is_dir():
        raise BenchmarkError("model directory does not exist")
    if not worker_script.is_file():
        raise BenchmarkError("managed worker script does not exist")
    if relative_to(model_dir, REPOSITORY_ROOT):
        raise BenchmarkError("model directory must remain outside the repository")
    if relative_to(media_dir, REPOSITORY_ROOT):
        raise BenchmarkError("media output directory must remain outside the repository")
    for left_name, left, right_name, right in (
        ("media", media_dir, "evidence", evidence_dir),
        ("media", media_dir, "model", model_dir),
        ("evidence", evidence_dir, "model", model_dir),
    ):
        if relative_to(left, right) or relative_to(right, left):
            raise BenchmarkError(f"{left_name} and {right_name} directories must not overlap")
    if worker_script != MANAGED_WORKER_PATH.resolve():
        raise BenchmarkError("T0-C must consume the frozen T0-B managed worker implementation")
    if args.allow_fake_worker_for_tests and relative_to(evidence_dir, REPOSITORY_ROOT):
        raise BenchmarkError("fake worker output is forbidden in repository evidence directories")


def safe_tree_inventory(root: Path) -> tuple[str, list[dict[str, object]]]:
    excluded_names = {".git", ".venv", "__pycache__", ".DS_Store"}
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in excluded_names for part in relative.parts):
            continue
        if path.is_symlink():
            raise BenchmarkError("model/source inventory does not follow symbolic links")
        if not path.is_file():
            continue
        records.append(
            {
                "path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not records:
        raise BenchmarkError("model/source inventory contains no regular files")
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical), records


def physical_memory_bytes() -> int:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
    page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    page_count = os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else 1
    return max(1, int(page_size) * int(page_count))


def hardware_name() -> str:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return platform.processor() or platform.machine() or "unknown processor"


def environment_record() -> dict[str, object]:
    return {
        "hardware": hardware_name(),
        "os_name": platform.system() or "unknown",
        "os_version": platform.release() or "unknown",
        "architecture": platform.machine() or "unknown",
        "python_version": platform.python_version(),
        "physical_memory_bytes": physical_memory_bytes(),
    }


def sanitize_argv(argv: list[str]) -> list[str]:
    sanitized: list[str] = []
    replace_next: str | None = None
    for item in argv:
        if replace_next is not None:
            sanitized.append(replace_next)
            replace_next = None
            continue
        if item in SENSITIVE_PATH_FLAGS:
            sanitized.append(item)
            replace_next = SENSITIVE_PATH_FLAGS[item]
            continue
        if item == "--reference-audio":
            sanitized.append(item)
            replace_next = "<profile>=<external-reference-audio>"
            continue
        sanitized.append(item)
    return sanitized


def make_listening(status: str, reason: str | None = None) -> dict[str, object]:
    return {
        "status": status,
        "reviewer": None,
        "verdict": "not_reviewed",
        "defects": {key: None for key in DEFECT_KEYS},
        "notes_redacted": None,
        "skipped_reason": reason,
    }


def base_case_record(
    case: dict[str, Any],
    *,
    reference_sha256: str | None = None,
) -> dict[str, Any]:
    input_data = case["input"]
    return {
        "case_id": case["id"],
        "status": "skipped",
        "input": {
            "text_ids": list(input_data["text_ids"]),
            "text_sha256": list(input_data["text_sha256"]),
            "combined_sha256": input_data["combined_sha256"],
            "reference_profile_id": case.get("reference_profile_id"),
            "reference_sha256": reference_sha256,
        },
        "timing": {
            "first_packet_ms": None,
            "synthesis_wall_ms": None,
            "audio_duration_seconds": None,
            "rtf": None,
        },
        "resources": {"peak_rss_bytes": None, "peak_accelerator_bytes": None},
        "output": {
            "audio_sha256": None,
            "audio_inspection": None,
            "ready_segment_sha256": [],
        },
        "control": {
            "cancel_requested": False,
            "cancel_acknowledged": False,
            "failure_injected": False,
            "crash_recovered": False,
            "ready_segments_reused": 0,
        },
        "error": None,
        "listening": make_listening("pending"),
        "diagnostics": {
            "expected_terminal_status": case.get("expected_terminal_status"),
            "segment_mode": case.get("segment_mode"),
            "covers": list(case.get("covers", [])),
            "runner_invocations": 0,
        },
    }


def set_non_passed(
    result: dict[str, Any],
    *,
    status: str,
    category: str,
    code: str,
    message: str,
    listening_reason: str,
) -> dict[str, Any]:
    result["status"] = status
    result["output"]["audio_sha256"] = None
    result["output"]["audio_inspection"] = None
    result["error"] = {
        "category": category,
        "code": code,
        "message_redacted": message,
    }
    result["listening"] = make_listening("skipped_with_reason", listening_reason)
    return result


def load_audio_inspector() -> Any:
    spec = importlib.util.spec_from_file_location("t0c_inspect_audio", INSPECT_AUDIO_PATH)
    if spec is None or spec.loader is None:
        raise BenchmarkError("could not load the frozen WAV inspector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_wav(path: Path) -> dict[str, Any]:
    module = load_audio_inspector()
    try:
        inspection = module.inspect_wav(path)
    except Exception as error:
        raise SegmentRunnerError("wav_inspection_failed", "generated WAV failed technical inspection") from error
    if not isinstance(inspection, dict) or inspection.get("status") != "ok":
        raise SegmentRunnerError("wav_inspection_failed", "generated WAV failed technical inspection")
    return inspection


def concatenate_wavs(inputs: list[Path], output: Path) -> None:
    if not inputs:
        raise SegmentRunnerError("no_segments", "runner returned no ready segments")
    parameters: tuple[int, int, int, str, str] | None = None
    frames: list[bytes] = []
    try:
        for input_path in inputs:
            with wave.open(str(input_path), "rb") as source:
                observed = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                    source.getcompname(),
                )
                if parameters is None:
                    parameters = observed
                elif observed != parameters:
                    raise SegmentRunnerError(
                        "incompatible_segments",
                        "independent segment WAV parameters do not match",
                    )
                frames.append(source.readframes(source.getnframes()))
        assert parameters is not None
        with wave.open(str(output), "wb") as destination:
            destination.setnchannels(parameters[0])
            destination.setsampwidth(parameters[1])
            destination.setframerate(parameters[2])
            destination.setcomptype(parameters[3], parameters[4])
            for payload in frames:
                destination.writeframes(payload)
    except (EOFError, wave.Error) as error:
        raise SegmentRunnerError("invalid_segment_wav", "runner produced an invalid WAV") from error


def load_managed_worker_adapter() -> Any:
    """Load the T0-B client so T0-C has exactly one model lifecycle."""

    module_name = "t0b_managed_worker_contract"
    spec = importlib.util.spec_from_file_location(module_name, MANAGED_WORKER_PATH)
    if spec is None or spec.loader is None:
        raise BenchmarkError("could not load the frozen T0-B managed worker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    adapter = getattr(module, "ManagedSubprocessOnnxAdapter", None)
    if adapter is None:
        raise BenchmarkError("T0-B managed worker adapter contract is unavailable")
    return adapter


def run_segment(
    *,
    args: argparse.Namespace,
    worker: Any,
    case: dict[str, Any],
    segment_index: int,
    text: str,
    case_media_dir: Path,
) -> dict[str, Any]:
    segment_id = f"segment-{segment_index + 1:03d}"
    output_path = case_media_dir / f"{segment_id}.wav"
    try:
        measurement = worker.synthesize(
            text,
            output_path,
            voice=args.voice,
            seed=args.seed,
            max_new_frames=args.max_new_frames,
            sample_mode=args.sample_mode,
        )
    except Exception as error:
        raise SegmentRunnerError(
            "managed_worker_request_failed",
            "managed worker did not produce a valid ready WAV",
            category="managed_worker",
        ) from error
    if not output_path.is_file():
        raise SegmentRunnerError("missing_output", "managed worker did not create the prescribed WAV")
    observed_hash = sha256_file(output_path)
    inspection = inspect_wav(output_path)
    ready_wav_ms = measurement.ready_wav_ms or measurement.wall_ms
    event_order = [event.get("event") for event in measurement.events]
    if event_order != ["started", "inference_entered", "ready", "published"]:
        raise SegmentRunnerError("worker_event_order", "managed worker event order is invalid")
    for event in measurement.events:
        if event.get("request_id") != measurement.request_id:
            raise SegmentRunnerError("worker_request_id", "worker event request identity is invalid")
        if (
            event.get("pid") != measurement.worker_pid
            or event.get("generation") != measurement.worker_generation
        ):
            raise SegmentRunnerError("worker_identity", "worker event process identity is invalid")
    published_hashes = [
        event.get("audio_sha256")
        for event in measurement.events
        if event.get("event") in {"ready", "published"}
    ]
    if published_hashes != [observed_hash, observed_hash]:
        raise SegmentRunnerError("output_hash_mismatch", "worker event hash does not match the WAV")
    return {
        "path": output_path,
        "sha256": observed_hash,
        "inspection": inspection,
        "request_wall_ms": float(measurement.wall_ms),
        "request_to_ready_wav_ms": float(ready_wav_ms),
        "request_to_internal_first_audio_ms": measurement.internal_first_audio_ms,
        "process_start_to_ready_ms": measurement.process_start_to_ready_ms,
        "peak_rss_bytes": int(measurement.peak_rss_bytes),
        "peak_accelerator_bytes": measurement.peak_accelerator_bytes,
        "worker_pid": measurement.worker_pid,
        "worker_generation": measurement.worker_generation,
        "request_id": measurement.request_id,
        "event_order": event_order,
    }


def sanitize_worker_telemetry(worker: Any) -> dict[str, Any]:
    """Keep lifecycle proof while excluding event rows with absolute media paths."""

    raw = worker.telemetry()
    event_log = raw.get("event_log") if isinstance(raw.get("event_log"), dict) else {}
    last_restart = raw.get("last_restart") if isinstance(raw.get("last_restart"), dict) else None
    return {
        "current_pid": raw.get("current_pid"),
        "worker_generation": raw.get("worker_generation"),
        "pid_history": list(raw.get("pid_history") or []),
        "process_start_to_ready_ms": raw.get("process_start_to_ready_ms"),
        "last_restart": last_restart,
        "synthesis_counts_by_text_sha256": dict(
            raw.get("synthesis_counts_by_text_sha256") or {}
        ),
        "event_log": {
            "file_name": event_log.get("file_name"),
            "event_count": event_log.get("event_count"),
            "sha256": event_log.get("sha256"),
        },
        "raw_events_excluded_from_evidence": True,
    }


def validate_reference_audio(
    *,
    profile: dict[str, Any],
    reference_path: Path,
    expected_hash: str,
    tolerance_seconds: float,
) -> tuple[str, dict[str, Any]]:
    if reference_path.is_symlink():
        raise BenchmarkError("reference audio must not be a symbolic link")
    resolved = reference_path.resolve()
    if relative_to(resolved, REPOSITORY_ROOT) or not resolved.is_file():
        raise BenchmarkError("reference audio must be an existing external controlled file")
    if not is_sha256(expected_hash):
        raise BenchmarkError("reference audio requires an explicit lowercase SHA-256")
    observed_hash = sha256_file(resolved)
    if observed_hash != expected_hash:
        raise BenchmarkError("reference audio hash mismatch")
    inspection = inspect_wav(resolved)
    format_mismatches = [
        key
        for key, expected in REFERENCE_AUDIO_FORMAT.items()
        if inspection.get(key) != expected
    ]
    if format_mismatches:
        raise BenchmarkError(
            "reference audio format must be 48 kHz stereo 16-bit PCM WAV"
        )
    target = float(profile["target_duration_seconds"])
    duration = float(inspection["duration_seconds"])
    if abs(duration - target) > tolerance_seconds:
        raise BenchmarkError("reference audio duration is outside the configured tolerance")
    return observed_hash, inspection


def run_real_case(
    *,
    args: argparse.Namespace,
    worker: Any,
    case: dict[str, Any],
    texts: dict[str, dict[str, Any]],
    reference_sha256: str | None,
    run_media_dir: Path,
) -> dict[str, Any]:
    result = base_case_record(case, reference_sha256=reference_sha256)
    fault = case.get("fault_injection") if isinstance(case.get("fault_injection"), dict) else None
    if fault and fault.get("kind") == "adapter_error":
        result["control"]["failure_injected"] = True
        return set_non_passed(
            result,
            status="failed",
            category="injected",
            code="adapter_error_before_first_segment",
            message="deterministic adapter failure injected before the first segment",
            listening_reason="no audio: deterministic failure injection",
        )

    case_media_dir = run_media_dir / case["id"]
    case_media_dir.mkdir(parents=True, exist_ok=False)
    ready: list[dict[str, Any]] = []
    try:
        for index, text_id in enumerate(case["input"]["text_ids"]):
            ready.append(
                run_segment(
                    args=args,
                    worker=worker,
                    case=case,
                    segment_index=index,
                    text=str(texts[text_id]["text"]),
                    case_media_dir=case_media_dir,
                )
            )
            result["diagnostics"]["runner_invocations"] += 1
            result["output"]["ready_segment_sha256"].append(ready[-1]["sha256"])
            if fault and fault.get("kind") == "cancel_request" and len(ready) >= int(
                fault.get("after_ready_segments", 0)
            ):
                result["control"]["cancel_requested"] = True
                result["control"]["cancel_acknowledged"] = True
                cancelled = bool(worker.acknowledge_between_segment_cancel())
                result["control"]["cancel_acknowledged"] = cancelled
                elapsed_ms = sum(float(item["request_wall_ms"]) for item in ready)
                duration = sum(float(item["inspection"]["duration_seconds"]) for item in ready)
                result["timing"] = {
                    "first_packet_ms": round(ready[0]["request_to_ready_wav_ms"], 6),
                    "synthesis_wall_ms": round(elapsed_ms, 6),
                    "audio_duration_seconds": round(duration, 9),
                    "rtf": round(elapsed_ms / 1000.0 / duration, 9) if duration > 0 else None,
                }
                result["resources"] = {
                    "peak_rss_bytes": max(item["peak_rss_bytes"] for item in ready),
                    "peak_accelerator_bytes": max(
                        (item["peak_accelerator_bytes"] for item in ready if item["peak_accelerator_bytes"] is not None),
                        default=None,
                    ),
                }
                return set_non_passed(
                    result,
                    status="cancelled",
                    category="control",
                    code="cancel_after_ready_segment",
                    message="cancellation was requested and acknowledged after a ready segment",
                    listening_reason="final case audio intentionally not produced after cancellation",
                )
    except SegmentRunnerError as error:
        result["diagnostics"]["runner_invocations"] += 1
        return set_non_passed(
            result,
            status="failed",
            category=error.category,
            code=error.code,
            message=str(error),
            listening_reason="runner did not produce a valid final WAV",
        )

    if fault and fault.get("kind") == "worker_crash":
        # A single-process quality driver cannot truthfully prove durable restart.
        # Preserve ready hashes, but do not promote a simulated restart to passed.
        result["control"]["failure_injected"] = True
        result["diagnostics"]["durable_resume_not_exercised"] = True
        return set_non_passed(
            result,
            status="skipped",
            category="capability",
            code="durable_resume_requires_worker_harness",
            message="durable crash/resume is reserved for the worker recovery harness",
            listening_reason="quality driver cannot claim an unperformed process restart",
        )

    if not ready:
        return set_non_passed(
            result,
            status="failed",
            category="runner",
            code="no_ready_segments",
            message="runner returned no ready segments",
            listening_reason="no audio was generated",
        )
    final_path = ready[0]["path"]
    if len(ready) > 1:
        final_path = case_media_dir / "joined-independent-segments.wav"
        try:
            concatenate_wavs([item["path"] for item in ready], final_path)
        except SegmentRunnerError as error:
            return set_non_passed(
                result,
                status="failed",
                category=error.category,
                code=error.code,
                message=str(error),
                listening_reason="independent segments could not be joined without cross-fade",
            )
    try:
        final_inspection = inspect_wav(final_path)
    except SegmentRunnerError as error:
        return set_non_passed(
            result,
            status="failed",
            category=error.category,
            code=error.code,
            message=str(error),
            listening_reason="final WAV failed technical inspection",
        )
    elapsed_ms = sum(float(item["request_wall_ms"]) for item in ready)
    duration = float(final_inspection["duration_seconds"])
    result["status"] = "passed"
    result["timing"] = {
        "first_packet_ms": round(ready[0]["request_to_ready_wav_ms"], 6),
        "synthesis_wall_ms": round(elapsed_ms, 6),
        "audio_duration_seconds": duration,
        "rtf": round(elapsed_ms / 1000.0 / duration, 9) if duration > 0 else None,
    }
    result["resources"] = {
        "peak_rss_bytes": max(item["peak_rss_bytes"] for item in ready),
        "peak_accelerator_bytes": max(
            (item["peak_accelerator_bytes"] for item in ready if item["peak_accelerator_bytes"] is not None),
            default=None,
        ),
    }
    result["output"]["audio_sha256"] = sha256_file(final_path)
    result["output"]["audio_inspection"] = final_inspection
    result["error"] = None
    result["listening"] = make_listening("pending")
    result["diagnostics"]["independent_segments_joined_without_crossfade"] = len(ready) > 1
    result["diagnostics"]["timing_semantics"] = {
        "process_start_to_ready_ms": ready[0]["process_start_to_ready_ms"],
        "first_packet_ms": "request_to_ready_wav_ms; first playable complete WAV at worker boundary",
        "synthesis_wall_ms": "sum of steady-state worker request wall times; excludes process startup",
        "rtf": "steady-state request wall divided by final audio duration",
        "internal_first_audio_is_not_client_playable": True,
    }
    result["diagnostics"]["managed_worker_segments"] = [
        {
            "audio_sha256": item["sha256"],
            "request_to_internal_first_audio_ms": item["request_to_internal_first_audio_ms"],
            "request_to_ready_wav_ms": round(item["request_to_ready_wav_ms"], 6),
            "request_wall_ms": round(item["request_wall_ms"], 6),
            "worker_pid": item["worker_pid"],
            "worker_generation": item["worker_generation"],
            "peak_rss_bytes": item["peak_rss_bytes"],
            "event_order": item["event_order"],
            "request_parameters": {
                "voice": args.voice,
                "seed": args.seed,
                "max_new_frames": args.max_new_frames,
                "sample_mode": args.sample_mode,
            },
        }
        for item in ready
    ]
    return result


def determine_run_status(case_results: list[dict[str, Any]], *, dry_run: bool) -> str:
    statuses = [case["status"] for case in case_results]
    if dry_run:
        return "blocked" if all(status == "blocked" for status in statuses) else "skipped"
    if statuses and all(status == "passed" for status in statuses):
        return "passed"
    if "passed" in statuses and any(status != "passed" for status in statuses):
        return "partial"
    for status in ("failed", "cancelled", "crashed", "blocked", "skipped"):
        if status in statuses:
            return status
    return "failed"


def listening_template(run_id: str, cases: list[dict[str, Any]]) -> str:
    lines = [
        "# T0-C 人工听感记录",
        "",
        "状态：**待真实 Nano 运行后由实际审听人填写；未听不得标记 pass。**",
        "",
        f"- Run ID：`{run_id}`",
        "- 音频位置：仅外部受控媒体目录（本文档不记绝对路径）",
        "- 填写规则：只记 fixture `text_id`、输出 hash、设备与脱敏结论；不复制正文或音频。",
        "",
    ]
    for case in cases:
        lines.extend(
            [
                f"## {case['id']}",
                "",
                f"- 对照文本：`{', '.join(case['input']['text_ids'])}`",
                "- 输出 SHA-256：",
                "- 审阅人代号：",
                "- 时间与监听设备：",
                "- 听检状态：`pending`",
                "- 结论：`not_reviewed`",
                "",
                "| 项目 | 是 | 否 | 无法判断 | 说明（脱敏） |",
                "| --- | --- | --- | --- | --- |",
                "| 漏字 |  |  |  |  |",
                "| 重复 |  |  |  |  |",
                "| 音色漂移 |  |  |  |  |",
                "| 异常停顿 |  |  |  |  |",
                "| 独立句段接缝异常 |  |  |  |  |",
                "| 爆音或噪声 |  |  |  |  |",
                "| 响度不一致 |  |  |  |  |",
                "",
                "- 与旁白/其他人物的可区分性：",
                "- 跨句段稳定性：",
                "- 跳过原因（如有）：",
                "",
            ]
        )
    return "\n".join(lines)


def build_metrics(args: argparse.Namespace, raw_argv: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    manifest, texts, case_map = validate_fixture_manifest(args.fixture_manifest)
    if args.quality_matrix and args.case_id:
        raise BenchmarkError("--quality-matrix and --case-id are mutually exclusive")
    selected_ids = list(QUALITY_MATRIX_CASE_IDS) if args.quality_matrix else (args.case_id or list(case_map))
    if len(selected_ids) != len(set(selected_ids)):
        raise BenchmarkError("--case-id values must be unique")
    unknown_cases = [case_id for case_id in selected_ids if case_id not in case_map]
    if unknown_cases:
        raise BenchmarkError("unknown --case-id: " + ", ".join(unknown_cases))
    selected_cases = [case_map[case_id] for case_id in selected_ids]
    references = {item["id"]: item for item in manifest["reference_profiles"]}
    reference_paths = parse_key_value(args.reference_audio, "--reference-audio")
    reference_hashes = parse_key_value(args.reference_sha256, "--reference-sha256")
    if set(reference_paths) != set(reference_hashes):
        raise BenchmarkError("--reference-audio and --reference-sha256 profile sets must match")
    unknown_references = set(reference_paths) - set(references)
    if unknown_references:
        raise BenchmarkError("unknown reference profile: " + ", ".join(sorted(unknown_references)))

    started = datetime.now().astimezone()
    timestamp = started.strftime("%Y%m%dT%H%M%S%z")
    run_id = f"T0-C-{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    exact_command = [Path(sys.executable).name, str(Path(__file__).relative_to(REPOSITORY_ROOT)), *raw_argv]
    case_results: list[dict[str, Any]] = []
    model: dict[str, Any]
    parameters: dict[str, Any] = {
        "fixture_manifest_sha256": sha256_file(args.fixture_manifest),
        "authorized_texts_fixture_set_id": manifest["authorized_texts"]["required_fixture_set_id"],
        "selected_case_ids": selected_ids,
        "voice": args.voice,
        "seed": args.seed,
        "cpu_threads": args.cpu_threads,
        "sample_mode": args.sample_mode,
        "streaming": True,
        "max_new_frames": args.max_new_frames,
        "voice_clone_max_text_tokens": args.voice_clone_max_text_tokens,
        "enable_wetext": False,
        "enable_normalize_tts_text": True,
        "reference_duration_tolerance_seconds": args.reference_duration_tolerance_seconds,
        "automatic_download": False,
        "dry_run": args.dry_run,
        "exact_argv_sha256": sha256_text(json.dumps(exact_command, ensure_ascii=False, separators=(",", ":"))),
        "path_values_redacted_in_command": True,
    }

    if args.dry_run:
        driver_hash = sha256_file(Path(__file__))
        model = {
            "name": "MOSS-TTS-Nano (not loaded)",
            "revision": "not-loaded-dry-run",
            "revision_sha256": None,
            "revision_hash_status": "not_applicable",
            "execution_backend": "dry-run",
            "artifacts": [
                {
                    "name": "benchmark_nano_quality.py",
                    "revision": driver_hash,
                    "sha256": driver_hash,
                    "hash_status": "verified",
                    "source": "repository benchmark driver",
                }
            ],
        }
        for case in selected_cases:
            result = base_case_record(case)
            if case.get("reference_profile_id"):
                set_non_passed(
                    result,
                    status="blocked",
                    category="authorization",
                    code="reference_placeholder_only",
                    message="authorized reference audio has not been supplied",
                    listening_reason="reference audio is a placeholder, not an audio asset",
                )
            else:
                set_non_passed(
                    result,
                    status="skipped",
                    category="execution",
                    code="dry_run_no_model_execution",
                    message="dry-run validates inputs and plans execution without loading a model",
                    listening_reason="dry-run produces no audio",
                )
            case_results.append(result)
        exit_code = 0
    else:
        validate_real_paths(args)
        source_tree_hash, source_files = safe_tree_inventory(args.source_dir)
        model_tree_hash, model_files = safe_tree_inventory(args.model_dir)
        if args.expected_source_tree_sha256 and args.expected_source_tree_sha256 != source_tree_hash:
            raise BenchmarkError("source tree SHA-256 does not match --expected-source-tree-sha256")
        if args.expected_model_tree_sha256 and args.expected_model_tree_sha256 != model_tree_hash:
            raise BenchmarkError("model tree SHA-256 does not match --expected-model-tree-sha256")
        worker_hash = sha256_file(args.worker_script)
        model = {
            "name": args.model_name,
            "revision": args.model_revision,
            "revision_sha256": model_tree_hash,
            "revision_hash_status": "verified",
            "execution_backend": args.execution_backend,
            "artifacts": [
                {
                    "name": "nano-model-tree",
                    "revision": args.model_revision,
                    "sha256": model_tree_hash,
                    "hash_status": "verified",
                    "source": "explicit controlled model directory",
                },
                {
                    "name": "nano-source-tree",
                    "revision": args.source_revision,
                    "sha256": source_tree_hash,
                    "hash_status": "verified",
                    "source": "explicit pinned official source directory",
                },
                {
                    "name": "managed-worker",
                    "revision": worker_hash,
                    "sha256": worker_hash,
                    "hash_status": "verified",
                    "source": "frozen T0-B managed worker implementation",
                },
            ],
        }
        parameters.update(
            {
                "model_tree_sha256": model_tree_hash,
                "model_artifact_count": len(model_files),
                "model_artifact_bytes": sum(int(item["size_bytes"]) for item in model_files),
                "source_revision": args.source_revision,
                "source_tree_sha256": source_tree_hash,
                "source_artifact_count": len(source_files),
                "source_artifact_bytes": sum(int(item["size_bytes"]) for item in source_files),
                "managed_worker_sha256": worker_hash,
                "reference_profiles_supplied": sorted(reference_paths),
                "case_timeout_seconds": args.case_timeout_seconds,
                "media_retained_externally": True,
            }
        )
        run_media_dir = args.media_output_dir.resolve() / run_id
        run_media_dir.mkdir(parents=True, exist_ok=False)
        adapter_type = load_managed_worker_adapter()
        worker = adapter_type(
            source_root=args.source_dir,
            model_root=args.model_dir,
            output_root=run_media_dir,
            cpu_threads=args.cpu_threads,
            max_new_frames=args.max_new_frames,
            sample_mode=args.sample_mode,
            seed=args.seed,
            voice=args.voice,
            fake_worker=args.allow_fake_worker_for_tests,
        )
        try:
            for case in selected_cases:
                reference_id = case.get("reference_profile_id")
                reference_hash: str | None = None
                if reference_id:
                    if reference_id not in reference_paths:
                        result = base_case_record(case)
                        case_results.append(
                            set_non_passed(
                                result,
                                status="blocked",
                                category="authorization",
                                code="reference_placeholder_only",
                                message="authorized reference audio has not been supplied",
                                listening_reason="reference audio is a placeholder, not an audio asset",
                            )
                        )
                        continue
                    reference_path = Path(reference_paths[reference_id])
                    reference_hash, reference_inspection = validate_reference_audio(
                        profile=references[reference_id],
                        reference_path=reference_path,
                        expected_hash=reference_hashes[reference_id],
                        tolerance_seconds=args.reference_duration_tolerance_seconds,
                    )
                    parameters.setdefault("reference_inspections", {})[reference_id] = {
                        "sha256": reference_hash,
                        "duration_seconds": reference_inspection["duration_seconds"],
                        "sample_rate_hz": reference_inspection["sample_rate_hz"],
                        "channels": reference_inspection["channels"],
                        "sample_width_bytes": reference_inspection["sample_width_bytes"],
                        "codec": reference_inspection["codec"],
                        "container": reference_inspection["container"],
                    }
                    result = base_case_record(case, reference_sha256=reference_hash)
                    case_results.append(
                        set_non_passed(
                            result,
                            status="blocked",
                            category="capability",
                            code="managed_worker_reference_audio_unsupported",
                            message="the frozen managed worker has no reference-audio request field",
                            listening_reason="reference cloning was not executed by the managed worker",
                        )
                    )
                    continue
                case_results.append(
                    run_real_case(
                        args=args,
                        worker=worker,
                        case=case,
                        texts=texts,
                        reference_sha256=reference_hash,
                        run_media_dir=run_media_dir,
                    )
                )
            case_segments = [
                segment
                for case_result in case_results
                for segment in case_result.get("diagnostics", {}).get(
                    "managed_worker_segments", []
                )
            ]
            observed_pids = sorted(
                {segment["worker_pid"] for segment in case_segments if segment["worker_pid"]}
            )
            observed_generations = sorted(
                {
                    segment["worker_generation"]
                    for segment in case_segments
                    if segment["worker_generation"] is not None
                }
            )
            parameters["managed_worker"] = {
                "contract": "scripts/tts/benchmark_nano_topologies.py __worker__ JSONL",
                "single_process_for_selected_cases": True,
                "fake_worker": args.allow_fake_worker_for_tests,
                "process_start_to_ready_ms": worker.process_start_to_ready_ms,
                "observed_case_worker_pids": observed_pids,
                "observed_case_worker_generations": observed_generations,
                "same_pid_across_case_requests": bool(case_segments) and len(observed_pids) == 1,
                "same_generation_across_case_requests": bool(case_segments)
                and len(observed_generations) == 1,
                "telemetry": sanitize_worker_telemetry(worker),
            }
            if args.same_worker_probe_repetitions:
                probe_case_id = args.same_worker_probe_case_id or selected_cases[0]["id"]
                if probe_case_id not in case_map:
                    raise BenchmarkError("--same-worker-probe-case-id is unknown")
                probe_case = case_map[probe_case_id]
                if probe_case.get("reference_profile_id"):
                    raise BenchmarkError("same-worker probe cannot use a reference-audio case")
                text_id = probe_case["input"]["text_ids"][0]
                probe_rows: list[dict[str, Any]] = []
                probe_dir = run_media_dir / "same-worker-repeat-probe"
                probe_dir.mkdir(parents=True, exist_ok=False)
                for repetition in range(args.same_worker_probe_repetitions):
                    probe = run_segment(
                        args=args,
                        worker=worker,
                        case=probe_case,
                        segment_index=repetition,
                        text=str(texts[text_id]["text"]),
                        case_media_dir=probe_dir,
                    )
                    probe_rows.append(
                        {
                            "audio_sha256": probe["sha256"],
                            "worker_pid": probe["worker_pid"],
                            "worker_generation": probe["worker_generation"],
                            "request_to_internal_first_audio_ms": probe[
                                "request_to_internal_first_audio_ms"
                            ],
                            "request_to_ready_wav_ms": round(
                                probe["request_to_ready_wav_ms"], 6
                            ),
                            "request_wall_ms": round(probe["request_wall_ms"], 6),
                        }
                    )
                parameters["managed_worker_same_request_probe"] = {
                    "case_id": probe_case_id,
                    "repetitions": len(probe_rows),
                    "same_pid": len({row["worker_pid"] for row in probe_rows}) == 1,
                    "same_generation": len(
                        {row["worker_generation"] for row in probe_rows}
                    )
                    == 1,
                    "distinct_audio_hash_count": len(
                        {row["audio_sha256"] for row in probe_rows}
                    ),
                    "rows": probe_rows,
                }
            # Snapshot only after optional probes so the event-log hash/count
            # and synthesis counters describe every request in this run.
            parameters["managed_worker"]["telemetry"] = sanitize_worker_telemetry(worker)
        finally:
            worker.close()
        mismatches = [
            result["case_id"]
            for result in case_results
            if result["status"] != result["diagnostics"]["expected_terminal_status"]
            and not (
                result["diagnostics"]["expected_terminal_status"] == "passed"
                and result["status"] == "skipped"
                and result["error"]
                and result["error"]["code"] == "durable_resume_requires_worker_harness"
            )
        ]
        parameters["unexpected_terminal_case_ids"] = mismatches
        exit_code = 1 if mismatches else 0

    finished = datetime.now().astimezone()
    run_status = determine_run_status(case_results, dry_run=args.dry_run)
    metrics = {
        "schema_version": RESULT_SCHEMA,
        "run": {
            "run_id": run_id,
            "benchmark_id": "nano-quality",
            "work_package_id": "T0-C",
            "status": run_status,
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "environment": environment_record(),
            "model": model,
            "parameters": parameters,
            "command": {"argv": sanitize_argv(exact_command), "exit_code": exit_code},
            "privacy": {
                "fixture_only": True,
                "contains_user_text": False,
                "contains_private_reference_audio": False,
                "evidence_contains_audio": False,
            },
        },
        "cases": case_results,
    }
    return metrics, selected_cases, exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--media-output-dir", type=Path)
    parser.add_argument("--worker-script", type=Path, default=MANAGED_WORKER_PATH)
    parser.add_argument("--case-id", action="append", default=[], help="repeat to select cases")
    parser.add_argument(
        "--quality-matrix",
        action="store_true",
        help="run the frozen 19 Chinese quality cases plus independent-segment seam case",
    )
    parser.add_argument("--voice", default="Junhao")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--sample-mode", choices=("greedy", "fixed", "full"), default="fixed")
    parser.add_argument("--max-new-frames", type=int, default=375)
    parser.add_argument("--voice-clone-max-text-tokens", type=int, default=75)
    parser.add_argument("--model-name", default="MOSS-TTS-Nano-100M")
    parser.add_argument("--model-revision")
    parser.add_argument("--source-revision")
    parser.add_argument("--expected-model-tree-sha256")
    parser.add_argument("--expected-source-tree-sha256")
    parser.add_argument("--execution-backend", default="managed-subprocess-onnx-cpu")
    parser.add_argument(
        "--reference-audio",
        action="append",
        default=[],
        metavar="PROFILE=PATH",
        help="explicit external authorized reference WAV; repeat with matching hash",
    )
    parser.add_argument(
        "--reference-sha256",
        action="append",
        default=[],
        metavar="PROFILE=SHA256",
    )
    parser.add_argument("--reference-duration-tolerance-seconds", type=float, default=0.75)
    parser.add_argument("--case-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--same-worker-probe-case-id")
    parser.add_argument("--same-worker-probe-repetitions", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="replace a dry-run candidate metrics.json only; real metrics/listening are never overwritten",
    )
    parser.add_argument(
        "--allow-fake-worker-for-tests",
        action="store_true",
        help="test-only; use T0-B fake worker and reject its output from repository evidence",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_argv)
    metrics_path = args.output_dir / "metrics.json"
    listening_path = args.output_dir / "listening.md"
    try:
        if args.reference_duration_tolerance_seconds < 0:
            raise BenchmarkError("--reference-duration-tolerance-seconds must be non-negative")
        if args.same_worker_probe_repetitions < 0 or args.same_worker_probe_repetitions > 20:
            raise BenchmarkError("--same-worker-probe-repetitions must be between 0 and 20")
        replaced_candidate: dict[str, str] | None = None
        if metrics_path.exists() and not args.replace_existing:
            raise BenchmarkError("metrics.json already exists; preserve it or use --replace-existing explicitly")
        if metrics_path.exists():
            existing = load_json_object(metrics_path)
            existing_run = existing.get("run") if isinstance(existing.get("run"), dict) else {}
            existing_parameters = (
                existing_run.get("parameters") if isinstance(existing_run.get("parameters"), dict) else {}
            )
            existing_model = existing_run.get("model") if isinstance(existing_run.get("model"), dict) else {}
            if existing_parameters.get("dry_run") is not True or existing_model.get("execution_backend") != "dry-run":
                raise BenchmarkError("--replace-existing cannot overwrite non-dry-run benchmark evidence")
            replaced_candidate = {
                "run_id": str(existing_run.get("run_id") or "unknown"),
                "sha256": sha256_file(metrics_path),
            }
        metrics, selected_cases, exit_code = build_metrics(args, raw_argv)
        if replaced_candidate is not None:
            metrics["run"]["parameters"]["replaced_dry_run_candidate"] = replaced_candidate
        serialized = json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        atomic_write_text(metrics_path, serialized)
        if not listening_path.exists():
            atomic_write_text(listening_path, listening_template(metrics["run"]["run_id"], selected_cases))
        print(
            json.dumps(
                {
                    "schema_version": RESULT_SCHEMA,
                    "run_id": metrics["run"]["run_id"],
                    "status": metrics["run"]["status"],
                    "case_count": len(metrics["cases"]),
                    "metrics_file": metrics_path.name,
                    "listening_file": listening_path.name,
                    "exit_code": exit_code,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return exit_code
    except (BenchmarkError, OSError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "moss-tts-benchmark-error/1.0",
                    "status": "blocked",
                    "error": {
                        "category": "validation",
                        "code": type(error).__name__,
                        "message_redacted": str(error),
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
