#!/usr/bin/env python3
"""Benchmark the frozen MOSS-TTS-Nano execution-topology candidates.

The command deliberately separates three modes:

* ``contract`` validates frozen inputs and records explicit blocked results;
* ``fake`` exercises result, recovery, audio-inspection and report plumbing only;
* ``real`` loads the pinned official ONNX runtime or an explicit external runner.

Generated audio and immutable per-run JSON stay in ``--runtime-dir``.  The
evidence directory receives only the derived, redacted ``metrics.json``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import resource
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence
import uuid
import wave


RESULT_SCHEMA_VERSION = "moss-tts-benchmark-result/1.0"
MANIFEST_SCHEMA_VERSION = "moss-tts-benchmark-manifest/1.0"
TEXT_SCHEMA_VERSION = "moss-tts-authorized-texts/1.0"
TOPOLOGY_CONFIG_SCHEMA_VERSION = "moss-tts-topology-config/1.0"
WORK_PACKAGE_ID = "T0-B"
TOPOLOGIES = (
    "in_process_onnx_cpu",
    "managed_subprocess_onnx_cpu",
    "linux_arm64_sidecar_onnx",
    "browser_onnx_preview",
)
MODEL_COMPONENT_IDS = (
    "moss-tts-nano-100m-onnx",
    "moss-audio-tokenizer-nano-onnx",
)
SOURCE_COMPONENT_ID = "moss-tts-nano-source"
DEFAULT_MODEL_LOCK = Path("prototypes/moss-tts-nano/model-sources.lock.json")
DEFAULT_VOICE = "Junhao"
SEGMENT_SEPARATOR = "\n<SEGMENT>\n"
DEFECT_KEYS = (
    "missing_text",
    "repeated_text",
    "voice_drift",
    "abnormal_pauses",
    "seam_artifacts",
    "clipping_or_noise",
    "loudness_inconsistent",
)


class BenchmarkError(ValueError):
    """An input or execution condition that must not be silently repaired."""


class AdapterUnavailable(BenchmarkError):
    """Raised when a topology has no runnable adapter in this environment."""


@dataclass(frozen=True)
class FrozenInputs:
    manifest: dict[str, Any]
    texts: dict[str, str]
    model_lock: dict[str, Any]
    fixture_manifest_path: Path
    model_lock_path: Path


@dataclass(frozen=True)
class ModelFingerprint:
    revision: str
    revision_sha256: str
    model_tree_sha256: str
    source_tree_sha256: str
    artifacts: list[dict[str, Any]]


@dataclass(frozen=True)
class SynthesisMeasurement:
    audio_path: Path
    first_packet_ms: float
    wall_ms: float
    peak_rss_bytes: int | None
    peak_accelerator_bytes: int | None
    internal_first_audio_ms: float | None = None
    ready_wav_ms: float | None = None
    process_start_to_ready_ms: float | None = None
    worker_pid: int | None = None
    worker_generation: int | None = None
    request_id: str | None = None
    events: tuple[dict[str, Any], ...] = ()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def require_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{label} must be a JSON object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BenchmarkError(f"{label} must be a JSON array")
    return value


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise BenchmarkError(f"{label} is not a file")
    try:
        return require_mapping(json.loads(path.read_text(encoding="utf-8")), label)
    except json.JSONDecodeError as error:
        raise BenchmarkError(
            f"{label} is invalid JSON at line {error.lineno}, column {error.colno}"
        ) from error


def resolve_repo_relative(repo_root: Path, raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise BenchmarkError(f"{label} must be a non-empty repository-relative path")
    path = Path(raw_path)
    if path.is_absolute():
        raise BenchmarkError(f"{label} must not be absolute")
    resolved = (repo_root / path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as error:
        raise BenchmarkError(f"{label} escapes the repository") from error
    return resolved


def validate_frozen_inputs(
    *,
    repo_root: Path,
    fixture_manifest_path: Path,
    model_lock_path: Path,
) -> FrozenInputs:
    manifest = load_json(fixture_manifest_path, "fixture manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BenchmarkError(f"fixture manifest must use {MANIFEST_SCHEMA_VERSION}")
    fixture_set_id = manifest.get("fixture_set_id")
    if not isinstance(fixture_set_id, str) or not fixture_set_id:
        raise BenchmarkError("fixture manifest fixture_set_id is missing")

    authorized = require_mapping(manifest.get("authorized_texts"), "authorized_texts")
    texts_path = resolve_repo_relative(
        repo_root,
        authorized.get("path"),
        "authorized_texts.path",
    )
    texts_payload = load_json(texts_path, "authorized texts")
    if texts_payload.get("schema_version") != TEXT_SCHEMA_VERSION:
        raise BenchmarkError(f"authorized texts must use {TEXT_SCHEMA_VERSION}")
    if texts_payload.get("fixture_set_id") != authorized.get("required_fixture_set_id"):
        raise BenchmarkError("authorized fixture_set_id does not match the manifest")

    text_rows = require_list(texts_payload.get("texts"), "authorized texts.texts")
    text_by_id: dict[str, str] = {}
    hash_by_id: dict[str, str] = {}
    for index, raw_row in enumerate(text_rows):
        row = require_mapping(raw_row, f"authorized texts.texts[{index}]")
        text_id = row.get("id")
        text = row.get("text")
        expected_hash = row.get("sha256")
        if not isinstance(text_id, str) or not text_id:
            raise BenchmarkError(f"authorized texts.texts[{index}].id is invalid")
        if text_id in text_by_id:
            raise BenchmarkError(f"duplicate authorized text id: {text_id}")
        if not isinstance(text, str) or not text:
            raise BenchmarkError(f"authorized text {text_id} is empty")
        observed_hash = sha256_bytes(text.encode("utf-8"))
        if expected_hash != observed_hash:
            raise BenchmarkError(f"authorized text hash mismatch: {text_id}")
        text_by_id[text_id] = text
        hash_by_id[text_id] = observed_hash

    required_coverage = set(
        str(item) for item in require_list(manifest.get("required_coverage"), "required_coverage")
    )
    observed_coverage: set[str] = set()
    case_ids: set[str] = set()
    cases = require_list(manifest.get("cases"), "fixture manifest.cases")
    if not cases:
        raise BenchmarkError("fixture manifest must contain cases")
    reference_profiles = {
        row.get("id"): row
        for row in (
            require_mapping(item, "reference profile")
            for item in require_list(manifest.get("reference_profiles"), "reference_profiles")
        )
    }
    for index, raw_case in enumerate(cases):
        case = require_mapping(raw_case, f"cases[{index}]")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise BenchmarkError(f"invalid or duplicate case id at cases[{index}]")
        case_ids.add(case_id)
        input_row = require_mapping(case.get("input"), f"case {case_id}.input")
        text_ids = require_list(input_row.get("text_ids"), f"case {case_id}.text_ids")
        text_hashes = require_list(
            input_row.get("text_sha256"), f"case {case_id}.text_sha256"
        )
        if not text_ids or len(text_ids) != len(text_hashes):
            raise BenchmarkError(f"case {case_id} text ids and hashes do not align")
        selected_texts: list[str] = []
        for text_id, expected_hash in zip(text_ids, text_hashes, strict=True):
            if text_id not in text_by_id:
                raise BenchmarkError(f"case {case_id} references unknown text id")
            if expected_hash != hash_by_id[text_id]:
                raise BenchmarkError(f"case {case_id} text hash mismatch")
            selected_texts.append(text_by_id[text_id])
        combined = sha256_bytes(SEGMENT_SEPARATOR.join(selected_texts).encode("utf-8"))
        if input_row.get("combined_sha256") != combined:
            raise BenchmarkError(f"case {case_id} combined hash mismatch")
        covers = require_list(case.get("covers"), f"case {case_id}.covers")
        observed_coverage.update(str(item) for item in covers)

        reference_id = case.get("reference_profile_id")
        if reference_id is not None:
            profile = reference_profiles.get(reference_id)
            if not isinstance(profile, dict):
                raise BenchmarkError(f"case {case_id} references unknown reference profile")
            if profile.get("asset_state") == "placeholder_only":
                if profile.get("asset_path") is not None or profile.get("sha256") is not None:
                    raise BenchmarkError(f"placeholder reference {reference_id} contains an asset")
                if case.get("expected_terminal_status") != "blocked":
                    raise BenchmarkError(f"placeholder case {case_id} must be blocked")

    missing_coverage = sorted(required_coverage - observed_coverage)
    if missing_coverage:
        raise BenchmarkError("fixture coverage is incomplete: " + ", ".join(missing_coverage))

    model_lock = load_json(model_lock_path, "model source lock")
    components = {
        row.get("component_id"): row
        for row in (
            require_mapping(item, "model component")
            for item in require_list(model_lock.get("components"), "model source lock.components")
        )
    }
    for component_id in (*MODEL_COMPONENT_IDS, SOURCE_COMPONENT_ID):
        component = components.get(component_id)
        if not isinstance(component, dict):
            raise BenchmarkError(f"model source lock is missing {component_id}")
        revision = component.get("revision")
        if not isinstance(revision, str) or len(revision) != 40:
            raise BenchmarkError(f"{component_id} does not have a pinned git revision")
        if component.get("download_allowed") is not True:
            raise BenchmarkError(f"{component_id} is not approved for controlled download")
        license_row = require_mapping(component.get("license"), f"{component_id}.license")
        if not str(license_row.get("status", "")).startswith("verified"):
            raise BenchmarkError(f"{component_id} license is not verified")

    return FrozenInputs(
        manifest=manifest,
        texts=text_by_id,
        model_lock=model_lock,
        fixture_manifest_path=fixture_manifest_path,
        model_lock_path=model_lock_path,
    )


def component_map(model_lock: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["component_id"]): row
        for row in model_lock["components"]
        if isinstance(row, dict) and "component_id" in row
    }


def find_component_root(model_root: Path, repository: str) -> Path:
    direct = model_root / repository.rsplit("/", 1)[-1]
    if direct.is_dir():
        return direct.resolve()
    if model_root.name == repository.rsplit("/", 1)[-1] and model_root.is_dir():
        return model_root.resolve()
    raise BenchmarkError("pinned model component directory is missing")


def validate_real_assets(
    frozen: FrozenInputs,
    *,
    model_root: Path,
    source_root: Path,
) -> ModelFingerprint:
    components = component_map(frozen.model_lock)
    observed: list[dict[str, str]] = []
    result_artifacts: list[dict[str, Any]] = []

    for component_id in MODEL_COMPONENT_IDS:
        component = components[component_id]
        local_root = find_component_root(model_root.resolve(), str(component["repository"]))
        for raw_artifact in component["artifacts"]:
            artifact = require_mapping(raw_artifact, f"{component_id}.artifact")
            relative = Path(str(artifact["path"]))
            local_path = (local_root / relative).resolve()
            try:
                local_path.relative_to(local_root)
            except ValueError as error:
                raise BenchmarkError("model artifact path escapes its component") from error
            if not local_path.is_file():
                raise BenchmarkError(f"missing pinned model artifact: {component_id}/{relative.name}")
            if local_path.stat().st_size != int(artifact["size"]):
                raise BenchmarkError(f"model artifact size mismatch: {component_id}/{relative.name}")
            algorithm = artifact.get("hash_algorithm")
            observed_lock_hash = (
                sha256_file(local_path)
                if algorithm == "sha256"
                else git_blob_sha1(local_path)
                if algorithm == "git-blob-sha1"
                else None
            )
            if observed_lock_hash is None or observed_lock_hash != artifact.get("hash"):
                raise BenchmarkError(f"model artifact hash mismatch: {component_id}/{relative.name}")
            actual_sha256 = sha256_file(local_path)
            artifact_name = f"{component_id}/{relative.as_posix()}"
            observed.append({"name": artifact_name, "sha256": actual_sha256})
            result_artifacts.append(
                {
                    "name": artifact_name,
                    "revision": str(component["revision"]),
                    "sha256": actual_sha256,
                    "hash_status": "verified",
                    "source": str(component["repository"]),
                }
            )

    source_component = components[SOURCE_COMPONENT_ID]
    source_root = source_root.resolve()
    source_observed: list[dict[str, str]] = []
    for raw_artifact in source_component["artifacts"]:
        artifact = require_mapping(raw_artifact, "source artifact")
        relative = Path(str(artifact["path"]))
        local_path = (source_root / relative).resolve()
        try:
            local_path.relative_to(source_root)
        except ValueError as error:
            raise BenchmarkError("source artifact path escapes source root") from error
        if not local_path.is_file():
            raise BenchmarkError(f"missing pinned source artifact: {relative.name}")
        if local_path.stat().st_size != int(artifact["size"]):
            raise BenchmarkError(f"source artifact size mismatch: {relative.name}")
        algorithm = artifact.get("hash_algorithm")
        lock_hash = sha256_file(local_path) if algorithm == "sha256" else git_blob_sha1(local_path)
        if lock_hash != artifact.get("hash"):
            raise BenchmarkError(f"source artifact hash mismatch: {relative.name}")
        source_observed.append({"path": relative.as_posix(), "sha256": sha256_file(local_path)})
    source_tree_sha256 = canonical_sha256(source_observed)
    result_artifacts.append(
        {
            "name": "moss-tts-nano-source-tree",
            "revision": str(source_component["revision"]),
            "sha256": source_tree_sha256,
            "hash_status": "verified",
            "source": str(source_component["repository"]),
        }
    )

    revisions = [
        f"{component_id}@{components[component_id]['revision']}"
        for component_id in (*MODEL_COMPONENT_IDS, SOURCE_COMPONENT_ID)
    ]
    model_tree_sha256 = canonical_sha256(sorted(observed, key=lambda row: row["name"]))
    fingerprint_payload = {
        "revisions": revisions,
        "model_tree_sha256": model_tree_sha256,
        "source_tree_sha256": source_tree_sha256,
    }
    return ModelFingerprint(
        revision="+".join(revisions),
        revision_sha256=canonical_sha256(fingerprint_payload),
        model_tree_sha256=model_tree_sha256,
        source_tree_sha256=source_tree_sha256,
        artifacts=result_artifacts,
    )


def process_peak_rss_bytes() -> int | None:
    try:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (AttributeError, ValueError):
        return None
    if peak <= 0:
        return None
    return int(peak if sys.platform == "darwin" else peak * 1024)


def child_rss_bytes(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip()) * 1024
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def environment_record() -> dict[str, Any]:
    hardware = platform.machine()
    physical_memory: int | None = None
    if sys.platform == "darwin":
        for key, target in (("machdep.cpu.brand_string", "hardware"), ("hw.memsize", "memory")):
            result = subprocess.run(
                ["sysctl", "-n", key],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                if target == "hardware" and result.stdout.strip():
                    hardware = result.stdout.strip()
                elif target == "memory" and result.stdout.strip().isdigit():
                    physical_memory = int(result.stdout.strip())
    if physical_memory is None:
        try:
            physical_memory = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (AttributeError, OSError, ValueError):
            physical_memory = 1
    return {
        "hardware": hardware,
        "os_name": platform.system() or "unknown",
        "os_version": platform.mac_ver()[0] or platform.release() or "unknown",
        "architecture": platform.machine() or "unknown",
        "python_version": platform.python_version(),
        "physical_memory_bytes": max(1, physical_memory),
    }


def import_t0i_module(module_name: str) -> Any:
    return importlib.import_module(module_name)


def inspect_audio(path: Path) -> dict[str, Any]:
    inspector = import_t0i_module("inspect_audio")
    return require_mapping(inspector.inspect_wav(path), "audio inspection")


def concatenate_wavs(paths: Sequence[Path], output_path: Path) -> Path:
    if not paths:
        raise BenchmarkError("no WAV segments were produced")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expected: tuple[int, int, int, str] | None = None
    frames: list[bytes] = []
    for path in paths:
        try:
            with wave.open(str(path), "rb") as wav_file:
                descriptor = (
                    wav_file.getnchannels(),
                    wav_file.getsampwidth(),
                    wav_file.getframerate(),
                    wav_file.getcomptype(),
                )
                if descriptor[3] != "NONE":
                    raise BenchmarkError("only uncompressed PCM WAV can be combined")
                if expected is None:
                    expected = descriptor
                elif descriptor != expected:
                    raise BenchmarkError("WAV segment formats differ")
                frames.append(wav_file.readframes(wav_file.getnframes()))
        except wave.Error as error:
            raise BenchmarkError("adapter produced an invalid WAV") from error
    assert expected is not None
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(expected[0])
        wav_file.setsampwidth(expected[1])
        wav_file.setframerate(expected[2])
        wav_file.setcomptype("NONE", "not compressed")
        for raw_frames in frames:
            wav_file.writeframes(raw_frames)
    return output_path


class TopologyAdapter:
    topology: str
    latency_semantics = "first playable WAV available at adapter boundary"
    supports_process_restart = False
    supports_inflight_crash = False
    cold_start_ms: float | None = None

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        seed: int | None = None,
        max_new_frames: int | None = None,
        sample_mode: str | None = None,
    ) -> SynthesisMeasurement:
        raise NotImplementedError

    def acknowledge_between_segment_cancel(self) -> bool:
        return True

    def restart(self) -> bool:
        return False

    def kill_during_synthesis(self, text: str, output_path: Path) -> dict[str, Any]:
        raise AdapterUnavailable("this adapter cannot isolate an in-flight crash")

    def telemetry(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


class FakeAdapter(TopologyAdapter):
    """Contract-only adapter.  It is never evidence of Nano inference."""

    def __init__(self, topology: str) -> None:
        self.topology = topology
        self.supports_process_restart = topology != "in_process_onnx_cpu"
        self._generation = 0
        self.cold_start_ms = 0.0

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        seed: int | None = None,
        max_new_frames: int | None = None,
        sample_mode: str | None = None,
    ) -> SynthesisMeasurement:
        started = time.perf_counter()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 16_000
        duration = max(0.08, min(0.35, len(text) / 180.0))
        frame_count = max(1, int(sample_rate * duration))
        frequency = 180 + (int(sha256_bytes(text.encode("utf-8"))[:4], 16) % 240)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            raw = bytearray()
            for index in range(frame_count):
                sample = int(4000 * math.sin(2 * math.pi * frequency * index / sample_rate))
                raw.extend(struct.pack("<h", sample))
            wav_file.writeframes(bytes(raw))
        wall_ms = max(0.001, (time.perf_counter() - started) * 1000.0)
        return SynthesisMeasurement(
            audio_path=output_path,
            first_packet_ms=wall_ms,
            wall_ms=wall_ms,
            peak_rss_bytes=process_peak_rss_bytes(),
            peak_accelerator_bytes=None,
        )

    def restart(self) -> bool:
        if not self.supports_process_restart:
            return False
        self._generation += 1
        return True


class InProcessOnnxAdapter(TopologyAdapter):
    topology = "in_process_onnx_cpu"

    def __init__(
        self,
        *,
        source_root: Path,
        model_root: Path,
        output_root: Path,
        cpu_threads: int,
        max_new_frames: int,
        sample_mode: str,
        seed: int,
        voice: str,
    ) -> None:
        cold_started = time.perf_counter()
        self._voice = voice
        self._max_new_frames = max_new_frames
        self._sample_mode = sample_mode
        self._seed = seed
        source_text = str(source_root.resolve())
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        try:
            runtime_module = importlib.import_module("onnx_tts_runtime")
            runtime_class = runtime_module.OnnxTtsRuntime
            self._runtime = runtime_class(
                model_dir=model_root.resolve(),
                thread_count=cpu_threads,
                max_new_frames=max_new_frames,
                sample_mode=sample_mode,
                execution_provider="cpu",
                output_dir=output_root.resolve(),
            )
        except Exception as error:
            raise AdapterUnavailable(
                "official in-process ONNX runtime could not be initialized"
            ) from error
        self.cold_start_ms = (time.perf_counter() - cold_started) * 1000.0

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        seed: int | None = None,
        max_new_frames: int | None = None,
        sample_mode: str | None = None,
    ) -> SynthesisMeasurement:
        started = time.perf_counter()
        try:
            result = self._runtime.synthesize(
                text=text,
                voice=voice or self._voice,
                output_audio_path=output_path,
                sample_mode=sample_mode or self._sample_mode,
                do_sample=(sample_mode or self._sample_mode) != "greedy",
                streaming=True,
                max_new_frames=max_new_frames or self._max_new_frames,
                enable_wetext=False,
                enable_normalize_tts_text=True,
                seed=self._seed if seed is None else seed,
            )
        except Exception as error:
            raise BenchmarkError("official ONNX synthesis failed") from error
        wall_ms = (time.perf_counter() - started) * 1000.0
        produced = Path(str(result["audio_path"])).resolve()
        if produced != output_path.resolve() or not produced.is_file():
            raise BenchmarkError("adapter returned an unexpected audio path")
        return SynthesisMeasurement(
            audio_path=produced,
            first_packet_ms=wall_ms,
            wall_ms=wall_ms,
            peak_rss_bytes=process_peak_rss_bytes(),
            peak_accelerator_bytes=None,
            internal_first_audio_ms=None,
            ready_wav_ms=wall_ms,
        )

    def close(self) -> None:
        # CPython refcounts release the ORT sessions here; gc also clears any
        # cycle created by the runtime's streaming callbacks before the next
        # topology is started under LOCK-NANO.
        import gc

        self._runtime = None
        gc.collect()


class ManagedSubprocessOnnxAdapter(TopologyAdapter):
    topology = "managed_subprocess_onnx_cpu"
    supports_process_restart = True
    supports_inflight_crash = True

    def __init__(
        self,
        *,
        source_root: Path,
        model_root: Path,
        output_root: Path,
        cpu_threads: int,
        max_new_frames: int,
        sample_mode: str,
        seed: int,
        voice: str,
        fake_worker: bool = False,
    ) -> None:
        self._settings = {
            "source_root": source_root.resolve(),
            "model_root": model_root.resolve(),
            "output_root": output_root.resolve(),
            "cpu_threads": cpu_threads,
            "max_new_frames": max_new_frames,
            "sample_mode": sample_mode,
            "seed": seed,
            "voice": voice,
            "fake_worker": fake_worker,
        }
        self._process: subprocess.Popen[str] | None = None
        self._stderr_stream: Any | None = None
        self._stdout_queue: queue.Queue[str | None] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._request_lock = threading.Lock()
        self._poisoned = False
        self._generation = 0
        self._pid_history: list[int] = []
        self._events: list[dict[str, Any]] = []
        self._synthesis_counts: dict[str, int] = {}
        self._last_restart: dict[str, Any] | None = None
        self.process_start_to_ready_ms: float | None = None
        self._event_log_path = Path(self._settings["output_root"]) / "managed-worker.events.jsonl"
        self._start()

    def _record_event(self, event: Mapping[str, Any]) -> None:
        row = dict(event)
        self._events.append(row)
        self._event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._event_log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()

    def _start(self) -> None:
        cold_started = time.perf_counter()
        settings = self._settings
        argv = [
            sys.executable,
            str(Path(__file__).resolve()),
            "__worker__",
            "--source-root",
            str(settings["source_root"]),
            "--model-root",
            str(settings["model_root"]),
            "--output-root",
            str(settings["output_root"]),
            "--cpu-threads",
            str(settings["cpu_threads"]),
            "--max-new-frames",
            str(settings["max_new_frames"]),
            "--sample-mode",
            str(settings["sample_mode"]),
            "--seed",
            str(settings["seed"]),
            "--voice",
            str(settings["voice"]),
            "--generation",
            str(self._generation + 1),
        ]
        if settings["fake_worker"]:
            argv.append("--fake-worker")
        stderr_path = Path(settings["output_root"]) / "managed-worker.stderr.log"
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_stream = stderr_path.open("a", encoding="utf-8")
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_stream,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        self._stdout_queue = queue.Queue()
        stdout_stream = self._process.stdout

        def pump_stdout() -> None:
            try:
                for line in stdout_stream:
                    assert self._stdout_queue is not None
                    self._stdout_queue.put(line)
            finally:
                if self._stdout_queue is not None:
                    self._stdout_queue.put(None)

        self._stdout_thread = threading.Thread(
            target=pump_stdout,
            name=f"moss-tts-worker-stdout-{self._process.pid}",
            daemon=True,
        )
        self._stdout_thread.start()
        response = self._read_response(timeout_seconds=180)
        if response.get("status") != "ready":
            self.close()
            raise AdapterUnavailable("managed ONNX worker did not become ready")
        observed_pid = int(response.get("pid", 0))
        observed_generation = int(response.get("generation", 0))
        if observed_pid != self._process.pid or observed_generation != self._generation + 1:
            self.close()
            raise AdapterUnavailable("managed ONNX worker identity handshake failed")
        self._generation = observed_generation
        self._pid_history.append(observed_pid)
        self.process_start_to_ready_ms = float(
            response.get("process_start_to_ready_ms", (time.perf_counter() - cold_started) * 1000.0)
        )
        self.cold_start_ms = (time.perf_counter() - cold_started) * 1000.0
        self._record_event(response)
        self._poisoned = False

    def _read_response(self, *, timeout_seconds: float) -> dict[str, Any]:
        process = self._process
        response_queue = self._stdout_queue
        if process is None or response_queue is None:
            raise AdapterUnavailable("managed worker is not running")
        # A dedicated blocking reader owns TextIOWrapper.  Mixing select() with
        # readline() is unsafe because readline may prefetch the following JSON
        # line into user-space while the OS descriptor becomes non-readable.
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(0.001, deadline - time.monotonic())
            try:
                raw = response_queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                if process.poll() is not None and response_queue.empty():
                    raise AdapterUnavailable("managed worker exited unexpectedly")
                continue
            if raw is None:
                raise AdapterUnavailable("managed worker closed stdout")
            try:
                return require_mapping(json.loads(raw), "managed worker response")
            except json.JSONDecodeError as error:
                raise AdapterUnavailable("managed worker returned invalid JSON") from error
        raise AdapterUnavailable("managed worker timed out")

    def _request(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        if self._poisoned:
            raise AdapterUnavailable("managed worker is poisoned; restart is required")
        if not self._request_lock.acquire(blocking=False):
            raise BenchmarkError("managed worker enforces single-flight requests")
        try:
            process = self._process
            if process is None or process.stdin is None or process.poll() is not None:
                raise AdapterUnavailable("managed worker is not available")
            request_id = str(payload.get("request_id", ""))
            if not request_id:
                raise BenchmarkError("managed worker request_id is required")
            process.stdin.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")
            process.stdin.flush()
            events: list[dict[str, Any]] = []
            request_deadline = time.monotonic() + timeout_seconds
            while True:
                response = self._read_response(
                    timeout_seconds=max(0.001, request_deadline - time.monotonic())
                )
                if response.get("request_id") != request_id:
                    raise AdapterUnavailable("managed worker response request_id mismatch")
                if int(response.get("pid", 0)) != process.pid:
                    raise AdapterUnavailable("managed worker response PID mismatch")
                if int(response.get("generation", 0)) != self._generation:
                    raise AdapterUnavailable("managed worker response generation mismatch")
                event = response.get("event")
                if isinstance(event, str):
                    events.append(dict(response))
                    self._record_event(response)
                if response.get("terminal") is True or response.get("status") in {
                    "ok",
                    "error",
                    "cancelled",
                    "bye",
                }:
                    return response, tuple(events)
        except (AdapterUnavailable, BenchmarkError, BrokenPipeError, OSError, ValueError):
            self._poisoned = True
            raise
        finally:
            self._request_lock.release()

    def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        seed: int | None = None,
        max_new_frames: int | None = None,
        sample_mode: str | None = None,
    ) -> SynthesisMeasurement:
        process = self._process
        if process is None:
            raise AdapterUnavailable("managed worker is not available")
        request_id = uuid.uuid4().hex
        request = {
            "operation": "synthesize",
            "request_id": request_id,
            "text": text,
            "output_path": str(output_path.resolve()),
            "voice": voice or self._settings["voice"],
            "seed": self._settings["seed"] if seed is None else seed,
            "max_new_frames": max_new_frames or self._settings["max_new_frames"],
            "sample_mode": sample_mode or self._settings["sample_mode"],
        }
        response, events = self._request(request, timeout_seconds=600)
        if response.get("status") != "ok":
            raise BenchmarkError("managed ONNX worker reported synthesis failure")
        produced = Path(str(response.get("audio_path", ""))).resolve()
        if produced != output_path.resolve() or not produced.is_file():
            raise BenchmarkError("managed worker returned an unexpected audio path")
        response_pid = int(response.get("pid", 0))
        response_generation = int(response.get("generation", 0))
        if response_pid != process.pid or response_generation != self._generation:
            raise BenchmarkError("managed worker changed identity within one request")
        names = [event.get("event") for event in events]
        if names != ["started", "inference_entered", "ready", "published"]:
            self._poisoned = True
            raise BenchmarkError(
                "managed worker event order was not started/inference_entered/ready/published"
            )
        wall_ms = float(response["wall_ms"])
        self._synthesis_counts[sha256_bytes(text.encode("utf-8"))] = (
            self._synthesis_counts.get(sha256_bytes(text.encode("utf-8")), 0) + 1
        )
        return SynthesisMeasurement(
            audio_path=produced,
            first_packet_ms=float(response.get("ready_wav_ms", wall_ms)),
            wall_ms=wall_ms,
            peak_rss_bytes=int(response["ru_maxrss_bytes"]),
            peak_accelerator_bytes=None,
            internal_first_audio_ms=(
                float(response["internal_first_audio_ms"])
                if response.get("internal_first_audio_ms") is not None
                else None
            ),
            ready_wav_ms=float(response["ready_wav_ms"]),
            process_start_to_ready_ms=self.process_start_to_ready_ms,
            worker_pid=response_pid,
            worker_generation=response_generation,
            request_id=request_id,
            events=events,
        )

    def acknowledge_between_segment_cancel(self) -> bool:
        request_id = uuid.uuid4().hex
        response, events = self._request(
            {"operation": "cancel", "request_id": request_id},
            timeout_seconds=10,
        )
        valid = (
            response.get("status") == "cancelled"
            and [event.get("event") for event in events] == ["cancelled"]
            and int(response.get("pid", 0)) == (self._process.pid if self._process else -1)
            and int(response.get("generation", 0)) == self._generation
        )
        if not valid:
            self._poisoned = True
        return valid

    def kill_during_synthesis(self, text: str, output_path: Path) -> dict[str, Any]:
        if self._poisoned:
            raise AdapterUnavailable("managed worker is poisoned; restart is required")
        if not self._request_lock.acquire(blocking=False):
            raise BenchmarkError("managed worker enforces single-flight requests")
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            self._request_lock.release()
            raise AdapterUnavailable("managed worker is not available")
        request_id = uuid.uuid4().hex
        request = {
            "operation": "synthesize",
            "request_id": request_id,
            "text": text,
            "output_path": str(output_path.resolve()),
            "voice": self._settings["voice"],
            "seed": self._settings["seed"],
            "max_new_frames": self._settings["max_new_frames"],
            "sample_mode": self._settings["sample_mode"],
        }
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
            started = self._read_response(timeout_seconds=30)
            entered = self._read_response(timeout_seconds=30)
            for response, expected_event in (
                (started, "started"),
                (entered, "inference_entered"),
            ):
                if (
                    response.get("event") != expected_event
                    or response.get("request_id") != request_id
                    or int(response.get("pid", 0)) != process.pid
                    or int(response.get("generation", 0)) != self._generation
                ):
                    self._poisoned = True
                    raise BenchmarkError("managed worker in-flight identity/event mismatch")
                self._record_event(response)
            # The worker emits inference_entered immediately before the runtime
            # call.  This delay makes SIGKILL land inside inference.
            time.sleep(0.05)
            old_pid = process.pid
            process.kill()
            process.wait(timeout=30)
            self._poisoned = True
            published = output_path.is_file()
            partials = sorted(
                output_path.parent.glob(f".{output_path.name}.{request_id}.*.part")
            )
            return {
                "request_id": request_id,
                "old_pid": old_pid,
                "generation": self._generation,
                "exit_code": process.returncode,
                "final_output_published": published,
                "partial_file_count": len(partials),
                "published_event_observed": any(
                    event.get("request_id") == request_id
                    and event.get("event") == "published"
                    for event in self._events
                ),
            }
        finally:
            self._request_lock.release()

    def restart(self) -> bool:
        old_pid = self._process.pid if self._process is not None else None
        self._stop(force=True)
        try:
            self._start()
            new_pid = self._process.pid if self._process is not None else None
            self._last_restart = {
                "old_pid": old_pid,
                "new_pid": new_pid,
                "generation": self._generation,
                "pid_changed": old_pid is not None and new_pid is not None and old_pid != new_pid,
            }
            return bool(self._last_restart["pid_changed"])
        except AdapterUnavailable:
            return False

    def telemetry(self) -> dict[str, Any]:
        return {
            "current_pid": self._process.pid if self._process is not None else None,
            "worker_generation": self._generation,
            "poisoned": self._poisoned,
            "pid_history": list(self._pid_history),
            "process_start_to_ready_ms": self.process_start_to_ready_ms,
            "last_restart": dict(self._last_restart) if self._last_restart else None,
            "events": list(self._events),
            "synthesis_counts_by_text_sha256": dict(self._synthesis_counts),
            "event_log": {
                "file_name": self._event_log_path.name,
                "event_count": len(self._events),
                "sha256": sha256_file(self._event_log_path)
                if self._event_log_path.is_file()
                else None,
            },
        }

    def _stop(self, *, force: bool) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            if not force and process.stdin is not None:
                try:
                    process.stdin.write('{"operation":"shutdown"}\n')
                    process.stdin.flush()
                    process.wait(timeout=5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                process.kill() if force else process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        reader = self._stdout_thread
        if reader is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                raise BenchmarkError("managed worker stdout reader did not terminate")
        self._stdout_thread = None
        self._stdout_queue = None
        if self._stderr_stream is not None:
            self._stderr_stream.close()
            self._stderr_stream = None

    def close(self) -> None:
        self._stop(force=False)


class JsonCommandAdapter(TopologyAdapter):
    """Narrow bridge for a separately audited Sidecar or browser harness."""

    supports_process_restart = True

    def __init__(
        self,
        *,
        topology: str,
        argv: Sequence[str],
        output_root: Path,
        timeout_seconds: int,
    ) -> None:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise AdapterUnavailable("external topology runner argv is invalid")
        self.topology = topology
        self._argv = list(argv)
        self._output_root = output_root.resolve()
        self._timeout_seconds = timeout_seconds
        cold_started = time.perf_counter()
        probe = self._invoke({"operation": "capabilities", "protocol_version": "1.0"})
        if probe.get("status") != "ok" or probe.get("protocol_version") != "1.0":
            raise AdapterUnavailable("external topology runner handshake failed")
        self.cold_start_ms = (time.perf_counter() - cold_started) * 1000.0

    def _invoke(self, request: Mapping[str, Any]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                self._argv,
                input=json.dumps(request, ensure_ascii=False) + "\n",
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise AdapterUnavailable("external topology runner could not be invoked") from error
        if completed.returncode != 0:
            raise AdapterUnavailable("external topology runner exited unsuccessfully")
        try:
            response = require_mapping(json.loads(completed.stdout), "external runner response")
        except json.JSONDecodeError as error:
            raise AdapterUnavailable("external topology runner returned invalid JSON") from error
        return response

    def synthesize(self, text: str, output_path: Path) -> SynthesisMeasurement:
        response = self._invoke(
            {
                "operation": "synthesize",
                "protocol_version": "1.0",
                "text": text,
                "output_path": str(output_path.resolve()),
            }
        )
        if response.get("status") != "ok":
            raise BenchmarkError("external topology runner reported synthesis failure")
        produced = Path(str(response.get("audio_path", ""))).resolve()
        try:
            produced.relative_to(self._output_root)
        except ValueError as error:
            raise BenchmarkError("external runner audio escaped the runtime directory") from error
        if produced != output_path.resolve() or not produced.is_file():
            raise BenchmarkError("external runner returned an unexpected audio path")
        return SynthesisMeasurement(
            audio_path=produced,
            first_packet_ms=float(response["first_packet_ms"]),
            wall_ms=float(response["wall_ms"]),
            peak_rss_bytes=(
                int(response["peak_rss_bytes"])
                if response.get("peak_rss_bytes") is not None
                else None
            ),
            peak_accelerator_bytes=(
                int(response["peak_accelerator_bytes"])
                if response.get("peak_accelerator_bytes") is not None
                else None
            ),
        )

    def restart(self) -> bool:
        try:
            response = self._invoke({"operation": "restart", "protocol_version": "1.0"})
            return response.get("status") == "ok"
        except AdapterUnavailable:
            return False


def default_runtime_dir() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "AI小说世界2026"
        / "tts-benchmarks"
        / WORK_PACKAGE_ID
    )


def load_topology_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"schema_version": TOPOLOGY_CONFIG_SCHEMA_VERSION, "runners": {}}
    config = load_json(path.resolve(), "topology config")
    if config.get("schema_version") != TOPOLOGY_CONFIG_SCHEMA_VERSION:
        raise BenchmarkError(f"topology config must use {TOPOLOGY_CONFIG_SCHEMA_VERSION}")
    require_mapping(config.get("runners"), "topology config.runners")
    return config


def build_adapter(
    topology: str,
    *,
    mode: str,
    source_root: Path | None,
    model_root: Path | None,
    output_root: Path,
    topology_config: Mapping[str, Any],
    args: argparse.Namespace,
) -> TopologyAdapter:
    if mode == "fake":
        return FakeAdapter(topology)
    if mode != "real":
        raise AdapterUnavailable("real adapter was not requested")
    if source_root is None or model_root is None:
        raise AdapterUnavailable("pinned source and model roots were not supplied")
    common = {
        "source_root": source_root,
        "model_root": model_root,
        "output_root": output_root,
        "cpu_threads": args.cpu_threads,
        "max_new_frames": args.max_new_frames,
        "sample_mode": args.sample_mode,
        "seed": args.seed,
        "voice": args.voice,
    }
    if topology == "in_process_onnx_cpu":
        return InProcessOnnxAdapter(**common)
    if topology == "managed_subprocess_onnx_cpu":
        return ManagedSubprocessOnnxAdapter(**common)
    runners = require_mapping(topology_config.get("runners", {}), "topology config.runners")
    runner = runners.get(topology)
    if not isinstance(runner, dict):
        raise AdapterUnavailable("an audited external runner was not configured")
    return JsonCommandAdapter(
        topology=topology,
        argv=require_list(runner.get("argv"), f"runner {topology}.argv"),
        output_root=output_root,
        timeout_seconds=int(runner.get("timeout_seconds", 600)),
    )


def listening_record(*, real_audio: bool, blocked: bool = False) -> dict[str, Any]:
    if real_audio and not blocked:
        status = "pending"
        skipped_reason = None
    else:
        status = "skipped_with_reason" if blocked else "not_required"
        skipped_reason = "no real Nano audio was produced" if blocked else None
    return {
        "status": status,
        "reviewer": None,
        "verdict": "not_reviewed",
        "defects": {key: None for key in DEFECT_KEYS},
        "notes_redacted": None,
        "skipped_reason": skipped_reason,
    }


def error_record(category: str, code: str, message: str) -> dict[str, str]:
    return {"category": category, "code": code, "message_redacted": message}


def empty_case(
    case: Mapping[str, Any],
    *,
    status: str,
    error: dict[str, str] | None,
    real_audio: bool,
    control: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    input_row = case["input"]
    defaults = {
        "cancel_requested": False,
        "cancel_acknowledged": False,
        "failure_injected": False,
        "crash_recovered": False,
        "ready_segments_reused": 0,
    }
    if control:
        defaults.update(control)
    return {
        "case_id": case["id"],
        "status": status,
        "input": {
            "text_ids": list(input_row["text_ids"]),
            "text_sha256": list(input_row["text_sha256"]),
            "combined_sha256": input_row["combined_sha256"],
            "reference_profile_id": case.get("reference_profile_id"),
            "reference_sha256": None,
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
        "control": defaults,
        "error": error,
        "listening": listening_record(real_audio=real_audio, blocked=status == "blocked"),
    }


def make_passed_case(
    case: Mapping[str, Any],
    *,
    measurements: Sequence[SynthesisMeasurement],
    final_audio_path: Path,
    ready_hashes: Sequence[str],
    real_audio: bool,
    crash_recovered: bool = False,
    reused: int = 0,
    recovery_details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inspection = inspect_audio(final_audio_path)
    wall_ms = sum(item.wall_ms for item in measurements)
    first_packet_ms = measurements[0].first_packet_ms
    duration = float(inspection["duration_seconds"])
    result = empty_case(case, status="passed", error=None, real_audio=real_audio)
    result["timing"] = {
        "first_packet_ms": round(first_packet_ms, 6),
        "synthesis_wall_ms": round(wall_ms, 6),
        "audio_duration_seconds": duration,
        "rtf": round(wall_ms / 1000.0 / duration, 12),
        "process_start_to_ready_ms": next(
            (
                round(item.process_start_to_ready_ms, 6)
                for item in measurements
                if item.process_start_to_ready_ms is not None
            ),
            None,
        ),
        "internal_first_audio_ms": (
            round(measurements[0].internal_first_audio_ms, 6)
            if measurements[0].internal_first_audio_ms is not None
            else None
        ),
        "ready_wav_ms": round(
            measurements[0].ready_wav_ms
            if measurements[0].ready_wav_ms is not None
            else measurements[0].wall_ms,
            6,
        ),
    }
    result["resources"] = {
        "peak_rss_bytes": max(
            (item.peak_rss_bytes for item in measurements if item.peak_rss_bytes is not None),
            default=process_peak_rss_bytes() or 1,
        ),
        "peak_accelerator_bytes": max(
            (
                item.peak_accelerator_bytes
                for item in measurements
                if item.peak_accelerator_bytes is not None
            ),
            default=None,
        ),
    }
    result["output"] = {
        "audio_sha256": inspection["source"]["sha256"],
        "audio_inspection": inspection,
        "ready_segment_sha256": list(ready_hashes),
    }
    result["control"] = {
        "cancel_requested": False,
        "cancel_acknowledged": False,
        "failure_injected": False,
        "crash_recovered": crash_recovered,
        "ready_segments_reused": reused,
        "worker_pids": [item.worker_pid for item in measurements if item.worker_pid is not None],
        "worker_generations": [
            item.worker_generation for item in measurements if item.worker_generation is not None
        ],
        "request_events": [event for item in measurements for event in item.events],
        "recovery_details": dict(recovery_details or {}),
    }
    return result


def case_texts(case: Mapping[str, Any], texts: Mapping[str, str]) -> list[str]:
    return [texts[text_id] for text_id in case["input"]["text_ids"]]


def execute_case(
    case: Mapping[str, Any],
    *,
    adapter: TopologyAdapter,
    texts: Mapping[str, str],
    case_root: Path,
    real_audio: bool,
) -> dict[str, Any]:
    if case.get("reference_profile_id") is not None:
        return empty_case(
            case,
            status="blocked",
            error=error_record(
                "authorization",
                "REFERENCE_AUDIO_NOT_AUTHORIZED",
                "the frozen reference profile is a placeholder without an authorized asset",
            ),
            real_audio=real_audio,
        )
    fault = case.get("fault_injection") or {}
    if fault.get("kind") == "adapter_error":
        return empty_case(
            case,
            status="failed",
            error=error_record(
                "injected_failure",
                "ADAPTER_FAILURE_INJECTED",
                "adapter failure was injected before the first segment",
            ),
            real_audio=real_audio,
            control={"failure_injected": True},
        )

    selected_texts = case_texts(case, texts)
    measurements: list[SynthesisMeasurement] = []
    ready_paths: list[Path] = []
    ready_hashes: list[str] = []
    recovery_details: dict[str, Any] = {}
    initial_synthesis_counts = dict(
        adapter.telemetry().get("synthesis_counts_by_text_sha256", {})
    )
    ready_text_count_after_publish: int | None = None
    try:
        for index, text in enumerate(selected_texts):
            segment_path = case_root / f"segment-{index + 1:02d}.wav"
            measurement = adapter.synthesize(text, segment_path)
            measurements.append(measurement)
            ready_paths.append(measurement.audio_path)
            ready_hashes.append(sha256_file(measurement.audio_path))

            after_ready = int(fault.get("after_ready_segments", -1))
            if fault.get("kind") == "cancel_request" and len(ready_paths) == after_ready:
                acknowledged = adapter.acknowledge_between_segment_cancel()
                result = empty_case(
                    case,
                    status="cancelled",
                    error=error_record(
                        "control",
                        "CANCEL_ACKNOWLEDGED_BETWEEN_SEGMENTS",
                        "queued work was cancelled after a completed segment",
                    ),
                    real_audio=real_audio,
                    control={
                        "cancel_requested": True,
                        "cancel_acknowledged": acknowledged,
                    },
                )
                result["output"]["ready_segment_sha256"] = ready_hashes
                result["control"]["worker_telemetry"] = adapter.telemetry()
                return result

            if fault.get("kind") == "worker_crash" and len(ready_paths) == after_ready:
                if not adapter.supports_process_restart:
                    result = empty_case(
                        case,
                        status="blocked",
                        error=error_record(
                            "capability",
                            "CRASH_RECOVERY_UNSUPPORTED",
                            "this topology cannot restart without taking down its owner process",
                        ),
                        real_audio=real_audio,
                    )
                    result["output"]["ready_segment_sha256"] = ready_hashes
                    return result
                ready_hash_before = sha256_file(ready_paths[-1])
                ready_text_hash = sha256_bytes(selected_texts[0].encode("utf-8"))
                ready_text_count_after_publish = int(
                    adapter.telemetry().get("synthesis_counts_by_text_sha256", {}).get(
                        ready_text_hash, 0
                    )
                )
                crash_probe: dict[str, Any] = {"kind": "between_segment_restart_only"}
                if adapter.supports_inflight_crash:
                    next_index = index + 1
                    if next_index >= len(selected_texts):
                        raise BenchmarkError("crash fixture must have a segment after the ready asset")
                    interrupted_path = case_root / f"segment-{next_index + 1:02d}.wav"
                    crash_probe = adapter.kill_during_synthesis(
                        selected_texts[next_index], interrupted_path
                    )
                    if crash_probe.get("final_output_published") or crash_probe.get(
                        "published_event_observed"
                    ):
                        raise BenchmarkError("crashed inference published an output")
                if not adapter.restart():
                    raise BenchmarkError("managed worker did not recover with a new PID")
                ready_hash_after = sha256_file(ready_paths[-1])
                if ready_hash_after != ready_hash_before:
                    raise BenchmarkError("ready asset hash changed across worker recovery")
                recovery_details = {
                    "kill_probe": crash_probe,
                    "ready_asset_sha256_before": ready_hash_before,
                    "ready_asset_sha256_after": ready_hash_after,
                    "ready_asset_rehashed": True,
                    "worker_after_restart": adapter.telemetry().get("last_restart"),
                }

        final_path = case_root / "final.wav"
        concatenate_wavs(ready_paths, final_path)
        recovered = fault.get("kind") == "worker_crash"
        if recovered and adapter.supports_inflight_crash:
            first_text_hash = sha256_bytes(selected_texts[0].encode("utf-8"))
            count = adapter.telemetry().get("synthesis_counts_by_text_sha256", {}).get(
                first_text_hash, 0
            )
            baseline_count = int(initial_synthesis_counts.get(first_text_hash, 0))
            recovery_details["ready_asset_synthesis_count_during_case"] = count - baseline_count
            recovery_details["ready_asset_not_resynthesized"] = (
                count == ready_text_count_after_publish and count - baseline_count == 1
            )
            if not recovery_details["ready_asset_not_resynthesized"]:
                raise BenchmarkError("ready segment was unexpectedly re-synthesized")
            recovery_details["worker_telemetry"] = adapter.telemetry()
        return make_passed_case(
            case,
            measurements=measurements,
            final_audio_path=final_path,
            ready_hashes=ready_hashes,
            real_audio=real_audio,
            crash_recovered=recovered,
            reused=int(fault.get("after_ready_segments", 0)) if recovered else 0,
            recovery_details=recovery_details,
        )
    except (BenchmarkError, OSError, ValueError, KeyError) as error:
        result = empty_case(
            case,
            status="failed",
            error=error_record(
                "adapter",
                "SYNTHESIS_FAILED",
                f"adapter failed with {type(error).__name__}; details were withheld",
            ),
            real_audio=real_audio,
        )
        result["output"]["ready_segment_sha256"] = ready_hashes
        return result


def run_managed_reuse_probe(
    adapter: TopologyAdapter,
    *,
    text: str,
    probe_root: Path,
    repetitions: int,
) -> dict[str, Any] | None:
    if repetitions <= 0:
        return None
    measurements: list[SynthesisMeasurement] = []
    hashes: list[str] = []
    for index in range(repetitions):
        output_path = probe_root / f"reuse-{index + 1:03d}.wav"
        measurement = adapter.synthesize(text, output_path)
        measurements.append(measurement)
        hashes.append(sha256_file(output_path))
    return {
        "kind": "same_worker_same_request_parameters",
        "repetitions": repetitions,
        "worker_pids": [item.worker_pid for item in measurements],
        "worker_generations": [item.worker_generation for item in measurements],
        "ready_wav_ms": [round(item.ready_wav_ms or item.wall_ms, 6) for item in measurements],
        "wall_ms": [round(item.wall_ms, 6) for item in measurements],
        "audio_sha256": hashes,
        "same_worker": len({item.worker_pid for item in measurements}) == 1,
        "same_generation": len({item.worker_generation for item in measurements}) == 1,
        "bit_exact_within_worker": len(set(hashes)) == 1,
        "interpretation": "same seed is probed, not assumed to be a content-addressing key",
    }


def run_managed_endurance(
    adapter: TopologyAdapter,
    *,
    text: str,
    probe_root: Path,
    duration_seconds: int,
) -> dict[str, Any] | None:
    if duration_seconds <= 0:
        return None
    started = time.monotonic()
    next_progress = started + 300.0
    timings: list[float] = []
    rss_values: list[int] = []
    hashes: set[str] = set()
    pids: set[int] = set()
    generations: set[int] = set()
    while time.monotonic() - started < duration_seconds:
        index = len(timings) + 1
        output_path = probe_root / f"endurance-{index:05d}.wav"
        measurement = adapter.synthesize(text, output_path)
        timings.append(measurement.wall_ms)
        if measurement.peak_rss_bytes is not None:
            rss_values.append(measurement.peak_rss_bytes)
        hashes.add(sha256_file(output_path))
        if measurement.worker_pid is not None:
            pids.add(measurement.worker_pid)
        if measurement.worker_generation is not None:
            generations.add(measurement.worker_generation)
        now = time.monotonic()
        if now >= next_progress:
            print(
                json.dumps(
                    {
                        "status": "endurance_progress",
                        "elapsed_seconds": round(now - started, 3),
                        "completed_requests": len(timings),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )
            next_progress += 300.0
    ordered = sorted(timings)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "requested_duration_seconds": duration_seconds,
        "actual_duration_seconds": round(time.monotonic() - started, 3),
        "completed_requests": len(timings),
        "worker_pids": sorted(pids),
        "worker_generations": sorted(generations),
        "same_worker": len(pids) == 1,
        "same_generation": len(generations) == 1,
        "wall_ms_min": round(min(timings), 6),
        "wall_ms_median": round(ordered[len(ordered) // 2], 6),
        "wall_ms_p95": round(ordered[p95_index], 6),
        "wall_ms_max": round(max(timings), 6),
        "peak_rss_bytes_min": min(rss_values) if rss_values else None,
        "peak_rss_bytes_max": max(rss_values) if rss_values else None,
        "distinct_audio_hash_count": len(hashes),
        "orphan_check_pending": True,
    }


def blocked_cases(
    cases: Sequence[Mapping[str, Any]], *, code: str, message: str
) -> list[dict[str, Any]]:
    return [
        empty_case(
            case,
            status="blocked",
            error=error_record("capability", code, message),
            real_audio=False,
        )
        for case in cases
    ]


def derive_run_status(cases: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(case["status"]) for case in cases}
    if statuses == {"passed"}:
        return "passed"
    if statuses == {"blocked"}:
        return "blocked"
    if "passed" in statuses and len(statuses) > 1:
        return "partial"
    if "failed" in statuses:
        return "failed"
    if "cancelled" in statuses:
        return "cancelled"
    return "blocked"


def topology_matches_fixture(
    cases: Sequence[Mapping[str, Any]], manifest_cases: Sequence[Mapping[str, Any]]
) -> bool:
    expected = {str(case["id"]): str(case["expected_terminal_status"]) for case in manifest_cases}
    return all(expected.get(str(case["case_id"])) == case["status"] for case in cases)


def fake_model_record(topology: str) -> dict[str, Any]:
    return {
        "name": "contract-only fake adapter",
        "revision": "fixture-only",
        "revision_sha256": None,
        "revision_hash_status": "not_applicable",
        "execution_backend": f"fake/{topology}",
        "artifacts": [
            {
                "name": "fake-contract-adapter",
                "revision": "fixture-only",
                "sha256": None,
                "hash_status": "not_applicable",
                "source": "repository test fixture",
            }
        ],
    }


def blocked_model_record(topology: str) -> dict[str, Any]:
    return {
        "name": "MOSS-TTS-Nano topology candidate",
        "revision": "pinned-assets-not-loaded",
        "revision_sha256": None,
        "revision_hash_status": "unavailable",
        "execution_backend": f"blocked/{topology}",
        "artifacts": [
            {
                "name": "pinned-assets",
                "revision": "not-loaded",
                "sha256": None,
                "hash_status": "unavailable",
                "source": "T0-A model source lock",
            }
        ],
    }


def real_model_record(fingerprint: ModelFingerprint, topology: str) -> dict[str, Any]:
    return {
        "name": "MOSS-TTS-Nano-100M ONNX + MOSS-Audio-Tokenizer-Nano ONNX",
        "revision": fingerprint.revision,
        "revision_sha256": fingerprint.revision_sha256,
        "revision_hash_status": "verified",
        "execution_backend": topology,
        "artifacts": fingerprint.artifacts,
    }


def run_one_topology(
    topology: str,
    *,
    mode: str,
    frozen: FrozenInputs,
    run_root: Path,
    source_root: Path | None,
    model_root: Path | None,
    fingerprint: ModelFingerprint | None,
    topology_config: Mapping[str, Any],
    args: argparse.Namespace,
    command_argv: Sequence[str],
    selected_cases: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], bool]:
    started = datetime.now().astimezone()
    run_id = f"T0-B-{topology}-{started.strftime('%Y%m%dT%H%M%S%z')}-{uuid.uuid4().hex[:8]}"
    audio_root = (run_root / "audio" / topology / run_id).resolve()
    audio_root.mkdir(parents=True, exist_ok=False)
    adapter: TopologyAdapter | None = None
    adapter_reason: str | None = None
    adapter_telemetry: dict[str, Any] | None = None
    managed_reuse_probe: dict[str, Any] | None = None
    managed_endurance: dict[str, Any] | None = None

    if mode == "contract":
        cases = blocked_cases(
            selected_cases,
            code="LOCK_NANO_NOT_RELEASED",
            message="real inference was not requested; this run validates contracts only",
        )
    else:
        try:
            adapter = build_adapter(
                topology,
                mode=mode,
                source_root=source_root,
                model_root=model_root,
                output_root=audio_root,
                topology_config=topology_config,
                args=args,
            )
        except AdapterUnavailable as error:
            adapter_reason = str(error)
            cases = blocked_cases(
                selected_cases,
                code="TOPOLOGY_ADAPTER_UNAVAILABLE",
                message=adapter_reason,
            )
        else:
            try:
                cases = [
                    execute_case(
                        case,
                        adapter=adapter,
                        texts=frozen.texts,
                        case_root=audio_root / str(case["id"]),
                        real_audio=mode == "real",
                    )
                    for case in selected_cases
                ]
                if topology == "managed_subprocess_onnx_cpu":
                    probe_text = frozen.texts[str(selected_cases[0]["input"]["text_ids"][0])]
                    managed_reuse_probe = run_managed_reuse_probe(
                        adapter,
                        text=probe_text,
                        probe_root=audio_root / "managed-reuse-probe",
                        repetitions=args.managed_probe_repetitions,
                    )
                    managed_endurance = run_managed_endurance(
                        adapter,
                        text=probe_text,
                        probe_root=audio_root / "managed-endurance",
                        duration_seconds=args.managed_endurance_seconds,
                    )
                adapter_telemetry = adapter.telemetry()
            finally:
                adapter.close()

    finished = datetime.now().astimezone()
    matches = topology_matches_fixture(cases, selected_cases)
    if mode == "fake":
        model = fake_model_record(topology)
    elif mode == "real" and fingerprint is not None and adapter_reason is None:
        model = real_model_record(fingerprint, topology)
    else:
        model = blocked_model_record(topology)
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "benchmark_id": f"nano-topology/{topology}",
            "work_package_id": WORK_PACKAGE_ID,
            "status": derive_run_status(cases),
            "started_at": started.isoformat(timespec="milliseconds"),
            "finished_at": finished.isoformat(timespec="milliseconds"),
            "environment": environment_record(),
            "model": model,
            "parameters": {
                "topology": topology,
                "mode": mode,
                "voice": args.voice,
                "cpu_threads": args.cpu_threads,
                "max_new_frames": args.max_new_frames,
                "sample_mode": args.sample_mode,
                "streaming_decode": True,
                "seed": args.seed,
                "wetext_enabled": False,
                "normalize_tts_text": True,
                "latency_semantics": (
                    adapter.latency_semantics if adapter is not None else "not measured"
                ),
                "adapter_cold_start_ms": (
                    round(adapter.cold_start_ms, 6)
                    if adapter is not None and adapter.cold_start_ms is not None
                    else None
                ),
                "model_tree_sha256": (
                    fingerprint.model_tree_sha256 if fingerprint is not None else None
                ),
                "source_tree_sha256": (
                    fingerprint.source_tree_sha256 if fingerprint is not None else None
                ),
                "accelerator": "none; ONNX CPU candidate",
                "fixture_manifest_sha256": sha256_file(frozen.fixture_manifest_path),
                "model_lock_sha256": sha256_file(frozen.model_lock_path),
                "expected_status_match": matches,
                "adapter_unavailable_reason": adapter_reason,
                "managed_reuse_probe": managed_reuse_probe,
                "managed_endurance": managed_endurance,
                "adapter_telemetry": adapter_telemetry,
            },
            "command": {"argv": list(command_argv), "exit_code": None},
            "privacy": {
                "fixture_only": True,
                "contains_user_text": False,
                "contains_private_reference_audio": False,
                "evidence_contains_audio": False,
            },
        },
        "cases": cases,
    }
    return result, matches


def ensure_output_boundary(output_dir: Path, runtime_dir: Path) -> None:
    output = output_dir.resolve()
    runtime = runtime_dir.resolve()
    if output == runtime:
        raise BenchmarkError("runtime directory must differ from the evidence directory")
    try:
        runtime.relative_to(output)
    except ValueError:
        pass
    else:
        raise BenchmarkError("runtime directory must not be inside the evidence directory")


def render_summary(repo_root: Path, raw_results: Sequence[Path], output_dir: Path, run_root: Path) -> None:
    report_script = repo_root / "scripts" / "tts" / "render_benchmark_report.py"
    markdown_path = run_root / "summary.md"
    command = [
        sys.executable,
        str(report_script),
        *(str(path) for path in raw_results),
        "--markdown-output",
        str(markdown_path),
        "--json-output",
        str(output_dir / "metrics.json"),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise BenchmarkError("strict T0-I report validation failed")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("auto", "contract", "fake", "real"),
        default="auto",
        help="auto selects real only when both pinned roots are supplied (default: %(default)s)",
    )
    parser.add_argument(
        "--topology",
        action="append",
        choices=TOPOLOGIES,
        help="topology to run; repeat to select several (default: all four)",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="exact frozen case ID to run; repeat to select several (default: all cases)",
    )
    parser.add_argument("--runtime-dir", type=Path, default=default_runtime_dir())
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--model-lock", type=Path, default=DEFAULT_MODEL_LOCK)
    parser.add_argument("--topology-config", type=Path)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--max-new-frames", type=int, default=375)
    parser.add_argument("--sample-mode", choices=("greedy", "fixed", "full"), default="fixed")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--managed-probe-repetitions", type=int, default=0)
    parser.add_argument("--managed-endurance-seconds", type=int, default=0)
    return parser.parse_args(argv)


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.cpu_threads <= 0 or args.cpu_threads > 64:
        raise BenchmarkError("cpu-threads must be between 1 and 64")
    if args.max_new_frames <= 0:
        raise BenchmarkError("max-new-frames must be positive")
    if args.managed_probe_repetitions < 0 or args.managed_probe_repetitions > 20:
        raise BenchmarkError("managed-probe-repetitions must be between 0 and 20")
    if args.managed_endurance_seconds < 0 or args.managed_endurance_seconds > 1800:
        raise BenchmarkError("managed-endurance-seconds must be between 0 and 1800")
    if not isinstance(args.voice, str) or not args.voice.strip():
        raise BenchmarkError("voice must be non-empty")
    if args.mode == "auto":
        args.mode = "real" if args.model_root is not None and args.source_root is not None else "contract"
    if args.mode == "real" and (args.model_root is None or args.source_root is None):
        raise BenchmarkError("real mode requires --model-root and --source-root")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    try:
        args = normalize_args(parse_args(raw_argv))
        repo_root = Path(__file__).resolve().parents[2]
        fixture_path = args.fixture_manifest.resolve()
        model_lock_path = (
            args.model_lock.resolve()
            if args.model_lock.is_absolute()
            else (repo_root / args.model_lock).resolve()
        )
        output_dir = args.output_dir.resolve()
        runtime_dir = args.runtime_dir.resolve()
        ensure_output_boundary(output_dir, runtime_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        frozen = validate_frozen_inputs(
            repo_root=repo_root,
            fixture_manifest_path=fixture_path,
            model_lock_path=model_lock_path,
        )
        topology_config = load_topology_config(args.topology_config)
        fingerprint = None
        if args.mode == "real":
            fingerprint = validate_real_assets(
                frozen,
                model_root=args.model_root.resolve(),
                source_root=args.source_root.resolve(),
            )

        selected = tuple(dict.fromkeys(args.topology or TOPOLOGIES))
        manifest_cases = list(frozen.manifest["cases"])
        if args.case_id:
            requested_case_ids = tuple(dict.fromkeys(args.case_id))
            cases_by_id = {str(case["id"]): case for case in manifest_cases}
            unknown_case_ids = [case_id for case_id in requested_case_ids if case_id not in cases_by_id]
            if unknown_case_ids:
                raise BenchmarkError("unknown frozen case id: " + ", ".join(unknown_case_ids))
            selected_cases = [cases_by_id[case_id] for case_id in requested_case_ids]
        else:
            selected_cases = manifest_cases
        group_id = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z") + "-" + uuid.uuid4().hex[:8]
        run_root = runtime_dir / group_id
        run_root.mkdir(parents=True, exist_ok=False)
        command_argv = [sys.executable, str(Path(__file__).resolve()), *raw_argv]
        runs: list[tuple[dict[str, Any], bool]] = [
            run_one_topology(
                topology,
                mode=args.mode,
                frozen=frozen,
                run_root=run_root,
                source_root=args.source_root.resolve() if args.source_root else None,
                model_root=args.model_root.resolve() if args.model_root else None,
                fingerprint=fingerprint,
                topology_config=topology_config,
                args=args,
                command_argv=command_argv,
                selected_cases=selected_cases,
            )
            for topology in selected
        ]
        overall_exit = 0 if args.mode in {"contract", "fake"} or all(match for _, match in runs) else 4
        raw_results: list[Path] = []
        for result, _matches in runs:
            result["run"]["command"]["exit_code"] = overall_exit
            result_path = run_root / f"{result['run']['run_id']}.json"
            atomic_write_json(result_path, result)
            raw_results.append(result_path)
        render_summary(repo_root, raw_results, output_dir, run_root)
        print(
            json.dumps(
                {
                    "schema_version": "moss-tts-topology-invocation/1.0",
                    "status": "recorded",
                    "mode": args.mode,
                    "topologies": list(selected),
                    "case_ids": [str(case["id"]) for case in selected_cases],
                    "run_group": group_id,
                    "result_count": len(raw_results),
                    "expected_status_match_count": sum(match for _, match in runs),
                    "evidence_file": "metrics.json",
                    "exit_code": overall_exit,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return overall_exit
    except (BenchmarkError, OSError, ValueError, KeyError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "moss-tts-topology-invocation/1.0",
                    "status": "error",
                    "error": {
                        "type": type(error).__name__,
                        "message_redacted": str(error),
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


def worker_parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cpu-threads", type=int, required=True)
    parser.add_argument("--max-new-frames", type=int, required=True)
    parser.add_argument("--sample-mode", choices=("greedy", "fixed", "full"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--fake-worker", action="store_true")
    return parser.parse_args(argv)


def fake_worker_synthesize(text: str, output_path: Path, *, seed: int, voice: str) -> None:
    """Write deterministic test audio; never used as real Nano evidence."""
    time.sleep(0.15)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16_000
    duration = 0.2
    frame_count = int(sample_rate * duration)
    fingerprint = sha256_bytes(f"{voice}\0{seed}\0{text}".encode("utf-8"))
    frequency = 160 + int(fingerprint[:4], 16) % 300
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(4000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        wav_file.writeframes(bytes(frames))


def worker_main(argv: Sequence[str]) -> int:
    process_started = time.perf_counter()
    try:
        args = worker_parse_args(argv)
        adapter = None
        if not args.fake_worker:
            adapter = InProcessOnnxAdapter(
                source_root=args.source_root,
                model_root=args.model_root,
                output_root=args.output_root,
                cpu_threads=args.cpu_threads,
                max_new_frames=args.max_new_frames,
                sample_mode=args.sample_mode,
                seed=args.seed,
                voice=args.voice,
            )
        output_root = args.output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        identity = {"pid": os.getpid(), "generation": args.generation}
        print(
            json.dumps(
                {
                    "status": "ready",
                    "event": "process_ready",
                    "process_start_to_ready_ms": (time.perf_counter() - process_started) * 1000.0,
                    "ru_maxrss_bytes": process_peak_rss_bytes(),
                    **identity,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        for raw_line in sys.stdin:
            request = require_mapping(json.loads(raw_line), "worker request")
            operation = request.get("operation")
            request_id = str(request.get("request_id", ""))
            if operation == "shutdown":
                print(json.dumps({"status": "bye", "terminal": True, **identity}, sort_keys=True), flush=True)
                return 0
            if operation == "cancel":
                print(
                    json.dumps(
                        {
                            "status": "cancelled",
                            "terminal": True,
                            "event": "cancelled",
                            "request_id": request_id,
                            **identity,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                continue
            if args.fake_worker and operation == "test_invalid_json":
                print("not-json", flush=True)
                continue
            if args.fake_worker and operation == "test_missing_request_id":
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "terminal": True,
                            "event": "test_fault",
                            **identity,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                continue
            if args.fake_worker and operation == "test_bad_identity":
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "terminal": True,
                            "event": "test_fault",
                            "request_id": request_id,
                            "pid": os.getpid() + 1,
                            "generation": args.generation + 1,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                continue
            if operation != "synthesize":
                print(json.dumps({"status": "error", "terminal": True, "code": "UNKNOWN_OPERATION", "request_id": request_id, **identity}), flush=True)
                continue
            output_path = Path(str(request.get("output_path", ""))).resolve()
            try:
                output_path.relative_to(output_root)
            except ValueError:
                print(json.dumps({"status": "error", "terminal": True, "code": "OUTPUT_BOUNDARY", "request_id": request_id, **identity}), flush=True)
                continue
            if not request_id:
                print(json.dumps({"status": "error", "terminal": True, "code": "REQUEST_ID_REQUIRED", **identity}), flush=True)
                continue
            if output_path.exists():
                print(json.dumps({"status": "error", "terminal": True, "code": "OUTPUT_ALREADY_EXISTS", "request_id": request_id, **identity}), flush=True)
                continue
            voice = str(request.get("voice", args.voice))
            seed = int(request.get("seed", args.seed))
            max_new_frames = int(request.get("max_new_frames", args.max_new_frames))
            sample_mode = str(request.get("sample_mode", args.sample_mode))
            if sample_mode not in {"greedy", "fixed", "full"} or max_new_frames <= 0:
                print(json.dumps({"status": "error", "terminal": True, "code": "INVALID_PARAMETERS", "request_id": request_id, **identity}), flush=True)
                continue
            request_started = time.perf_counter()
            print(
                json.dumps(
                    {
                        "status": "running",
                        "event": "started",
                        "request_id": request_id,
                        "voice": voice,
                        "seed": seed,
                        "max_new_frames": max_new_frames,
                        "sample_mode": sample_mode,
                        **identity,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
            temporary = output_path.with_name(
                f".{output_path.name}.{request_id}.{uuid.uuid4().hex}.part"
            )
            print(
                json.dumps(
                    {
                        "status": "running",
                        "event": "inference_entered",
                        "request_id": request_id,
                        **identity,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if args.fake_worker and request.get("text") == "__TEST_BAD_ORDER__":
                print(
                    json.dumps(
                        {
                            "status": "running",
                            "event": "ready",
                            "request_id": request_id,
                            **identity,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            if args.fake_worker:
                fake_worker_synthesize(str(request.get("text", "")), temporary, seed=seed, voice=voice)
                ready_wav_ms = (time.perf_counter() - request_started) * 1000.0
            else:
                assert adapter is not None
                measurement = adapter.synthesize(
                    str(request.get("text", "")),
                    temporary,
                    voice=voice,
                    seed=seed,
                    max_new_frames=max_new_frames,
                    sample_mode=sample_mode,
                )
                ready_wav_ms = measurement.ready_wav_ms or measurement.wall_ms
            ready_hash = sha256_file(temporary)
            print(
                json.dumps(
                    {
                        "status": "running",
                        "event": "ready",
                        "request_id": request_id,
                        "ready_wav_ms": ready_wav_ms,
                        "internal_first_audio_ms": None,
                        "audio_sha256": ready_hash,
                        "ru_maxrss_bytes": process_peak_rss_bytes(),
                        **identity,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            temporary.replace(output_path)
            wall_ms = (time.perf_counter() - request_started) * 1000.0
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "terminal": True,
                        "event": "published",
                        "request_id": request_id,
                        "audio_path": str(output_path),
                        "audio_sha256": ready_hash,
                        "internal_first_audio_ms": None,
                        "ready_wav_ms": ready_wav_ms,
                        "wall_ms": wall_ms,
                        "ru_maxrss_bytes": process_peak_rss_bytes(),
                        **identity,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": "WORKER_START_FAILED",
                    "error_type": type(error).__name__,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "__worker__":
        raise SystemExit(worker_main(sys.argv[2:]))
    raise SystemExit(main())
