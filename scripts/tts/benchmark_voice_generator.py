#!/usr/bin/env python3
"""Produce the T0-D VoiceGenerator feasibility audit without loading a model.

The default command is intentionally safe: it validates the frozen T0-I fixture,
the T0-A model lock and the repository-owned metadata baseline, then emits a
contract-valid *blocked* benchmark record.  It never downloads weights, imports
Torch/Transformers, starts a model process or writes audio.  A real model probe is
performed later under the two model locks and is deliberately not hidden behind
this metadata audit.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from typing import Any
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = (
    REPOSITORY_ROOT
    / "prototypes"
    / "moss-tts-nano"
    / "voice-generator"
    / "metadata-baseline.json"
)
DEFAULT_MODEL_LOCK = (
    REPOSITORY_ROOT / "prototypes" / "moss-tts-nano" / "model-sources.lock.json"
)
RESULT_SCHEMA = "moss-tts-benchmark-result/1.0"
MANIFEST_SCHEMA = "moss-tts-benchmark-manifest/1.0"
AUTHORIZED_SCHEMA = "moss-tts-authorized-texts/1.0"
BASELINE_SCHEMA = "moss-tts-voice-generator-metadata/1.0"
SEGMENT_SEPARATOR = "\n<SEGMENT>\n"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFECT_KEYS = (
    "missing_text",
    "repeated_text",
    "voice_drift",
    "abnormal_pauses",
    "seam_artifacts",
    "clipping_or_noise",
    "loudness_inconsistent",
)
REFERENCE_DURATIONS = {3, 5, 8, 12}


class AuditError(RuntimeError):
    """Raised when an input cannot be trusted as T0-D evidence."""


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


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AuditError(f"required JSON file is missing: {path.name}") from error
    except json.JSONDecodeError as error:
        raise AuditError(f"invalid JSON in {path.name}: line {error.lineno}") from error
    if not isinstance(value, dict):
        raise AuditError(f"top-level JSON must be an object: {path.name}")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def resolve_authorized_texts(manifest_path: Path, declared_path: object) -> Path:
    if not isinstance(declared_path, str) or not declared_path:
        raise AuditError("manifest authorized_texts.path must be a non-empty string")
    relative_path = Path(declared_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise AuditError("manifest authorized_texts.path must be repository-relative and safe")
    candidates = (REPOSITORY_ROOT / relative_path, manifest_path.parent / relative_path)
    existing: list[Path] = []
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() not in {
            item.resolve() for item in existing
        }:
            existing.append(candidate)
    if not existing:
        raise AuditError("declared authorized texts file does not exist")
    if len(existing) > 1:
        raise AuditError("declared authorized texts path resolves ambiguously")
    return existing[0]


def validate_fixture_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate all T0-I hashes before any optional source inspection."""

    manifest = load_json_object(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise AuditError(f"manifest schema must be {MANIFEST_SCHEMA}")
    fixture_set_id = manifest.get("fixture_set_id")
    if not isinstance(fixture_set_id, str) or not fixture_set_id:
        raise AuditError("manifest fixture_set_id is missing")

    contract = manifest.get("authorized_texts")
    if not isinstance(contract, dict):
        raise AuditError("manifest authorized_texts contract is missing")
    if contract.get("schema_version") != AUTHORIZED_SCHEMA:
        raise AuditError(f"authorized text contract must require {AUTHORIZED_SCHEMA}")
    authorized_path = resolve_authorized_texts(manifest_path, contract.get("path"))
    authorized = load_json_object(authorized_path)
    if authorized.get("schema_version") != AUTHORIZED_SCHEMA:
        raise AuditError(f"authorized text schema must be {AUTHORIZED_SCHEMA}")
    if authorized.get("fixture_set_id") != contract.get("required_fixture_set_id"):
        raise AuditError("authorized text fixture_set_id does not match manifest")

    raw_texts = authorized.get("texts")
    if not isinstance(raw_texts, list) or not raw_texts:
        raise AuditError("authorized texts must be a non-empty array")
    texts: dict[str, dict[str, Any]] = {}
    for index, raw_text in enumerate(raw_texts):
        if not isinstance(raw_text, dict):
            raise AuditError(f"authorized text #{index} must be an object")
        text_id = raw_text.get("id")
        text = raw_text.get("text")
        if not isinstance(text_id, str) or not text_id or text_id in texts:
            raise AuditError(f"authorized text #{index} has a missing or duplicate id")
        if not isinstance(text, str) or not text:
            raise AuditError(f"authorized text {text_id} has no exact text")
        if raw_text.get("sha256") != sha256_text(text):
            raise AuditError(f"authorized text hash drift: {text_id}")
        for key in ("author", "source", "license", "purpose"):
            if key not in raw_text:
                raise AuditError(f"authorized text {text_id} is missing {key}")
        texts[text_id] = raw_text

    raw_references = manifest.get("reference_profiles")
    if not isinstance(raw_references, list):
        raise AuditError("reference_profiles must be an array")
    references: dict[str, dict[str, Any]] = {}
    observed_reference_durations: set[int] = set()
    for raw_reference in raw_references:
        if not isinstance(raw_reference, dict):
            raise AuditError("reference profile must be an object")
        reference_id = raw_reference.get("id")
        duration = raw_reference.get("target_duration_seconds")
        if (
            not isinstance(reference_id, str)
            or not reference_id
            or reference_id in references
        ):
            raise AuditError("reference profile id is missing or duplicated")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise AuditError(f"reference profile {reference_id} has invalid duration")
        if raw_reference.get("asset_state") != "placeholder_only":
            raise AuditError(
                f"reference profile {reference_id} must remain placeholder_only in T0-I"
            )
        if raw_reference.get("asset_path") is not None or raw_reference.get("sha256") is not None:
            raise AuditError(f"placeholder reference {reference_id} must not claim an asset")
        if raw_reference.get("authorization_state") != "not_supplied":
            raise AuditError(
                f"placeholder reference {reference_id} must remain unauthorized/not supplied"
            )
        references[reference_id] = raw_reference
        observed_reference_durations.add(duration)
    if not REFERENCE_DURATIONS.issubset(observed_reference_durations):
        raise AuditError("reference profiles must cover 3, 5, 8 and 12 seconds")

    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise AuditError("manifest cases must be a non-empty array")
    cases: dict[str, dict[str, Any]] = {}
    observed_coverage: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise AuditError(f"case #{index} must be an object")
        case_id = raw_case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in cases:
            raise AuditError(f"case #{index} has a missing or duplicate id")
        case_input = raw_case.get("input")
        if not isinstance(case_input, dict):
            raise AuditError(f"case {case_id} has no input object")
        text_ids = case_input.get("text_ids")
        text_hashes = case_input.get("text_sha256")
        if (
            not isinstance(text_ids, list)
            or not text_ids
            or not isinstance(text_hashes, list)
            or len(text_ids) != len(text_hashes)
        ):
            raise AuditError(f"case {case_id} has invalid text id/hash arrays")
        exact_texts: list[str] = []
        observed_hashes: list[str] = []
        for text_id in text_ids:
            if not isinstance(text_id, str) or text_id not in texts:
                raise AuditError(f"case {case_id} references an unknown text id")
            exact_texts.append(str(texts[text_id]["text"]))
            observed_hashes.append(str(texts[text_id]["sha256"]))
        if text_hashes != observed_hashes:
            raise AuditError(f"case text hash drift: {case_id}")
        combined = sha256_text(SEGMENT_SEPARATOR.join(exact_texts))
        if case_input.get("combined_sha256") != combined:
            raise AuditError(f"case combined hash drift: {case_id}")
        reference_id = raw_case.get("reference_profile_id")
        if reference_id is not None and reference_id not in references:
            raise AuditError(f"case {case_id} references an unknown reference profile")
        covers = raw_case.get("covers")
        if not isinstance(covers, list) or not covers:
            raise AuditError(f"case {case_id} has invalid coverage")
        if not all(isinstance(item, str) and item for item in covers):
            raise AuditError(f"case {case_id} has invalid coverage entries")
        observed_coverage.update(covers)
        cases[case_id] = raw_case

    required_coverage = manifest.get("required_coverage")
    if (
        not isinstance(required_coverage, list)
        or not required_coverage
        or not all(isinstance(item, str) and item for item in required_coverage)
        or len(required_coverage) != len(set(required_coverage))
    ):
        raise AuditError("required_coverage must be a unique non-empty string array")
    missing_coverage = set(required_coverage) - observed_coverage
    unknown_coverage = observed_coverage - set(required_coverage)
    if missing_coverage:
        raise AuditError("manifest coverage is incomplete")
    if unknown_coverage:
        raise AuditError("manifest contains unknown coverage values")

    privacy = manifest.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("fixture_only") is not True:
        raise AuditError("manifest privacy must require fixture_only=true")
    result_contract = manifest.get("result_contract")
    if not isinstance(result_contract, dict) or result_contract.get("schema_version") != RESULT_SCHEMA:
        raise AuditError(f"manifest result contract must be {RESULT_SCHEMA}")
    return manifest, texts, cases


def _require_int(mapping: dict[str, Any], key: str, *, positive: bool = True) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuditError(f"metadata {key} must be an integer")
    if positive and value <= 0:
        raise AuditError(f"metadata {key} must be positive")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise AuditError(f"{field} must be a lowercase SHA-256")
    return value


def validate_metadata_baseline(
    baseline_path: Path,
    model_lock_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = load_json_object(baseline_path)
    if baseline.get("schema_version") != BASELINE_SCHEMA:
        raise AuditError(f"metadata baseline schema must be {BASELINE_SCHEMA}")
    model_lock = load_json_object(model_lock_path)
    raw_components = model_lock.get("components")
    if not isinstance(raw_components, list):
        raise AuditError("model source lock components must be an array")
    components = {
        component.get("component_id"): component
        for component in raw_components
        if isinstance(component, dict) and isinstance(component.get("component_id"), str)
    }
    locked = components.get("moss-voice-generator")
    if not isinstance(locked, dict):
        raise AuditError("model source lock has no moss-voice-generator component")
    voice = baseline.get("voice_generator")
    if not isinstance(voice, dict):
        raise AuditError("metadata baseline has no voice_generator object")
    for key in ("repository", "revision", "selected_bytes", "snapshot_bytes"):
        if voice.get(key) != locked.get(key):
            raise AuditError(f"VoiceGenerator metadata drift: {key}")
    revision = voice.get("revision")
    if not isinstance(revision, str) or not GIT_SHA_RE.fullmatch(revision):
        raise AuditError("VoiceGenerator revision must be a fixed 40-character commit")

    weight = voice.get("model_weight")
    if not isinstance(weight, dict):
        raise AuditError("VoiceGenerator model_weight metadata is missing")
    expected_weight = next(
        (
            artifact
            for artifact in locked.get("artifacts", [])
            if isinstance(artifact, dict) and artifact.get("path") == "model.safetensors"
        ),
        None,
    )
    if not isinstance(expected_weight, dict):
        raise AuditError("VoiceGenerator lock has no model.safetensors")
    if weight.get("bytes") != expected_weight.get("size"):
        raise AuditError("VoiceGenerator weight size drift")
    if weight.get("sha256") != expected_weight.get("hash"):
        raise AuditError("VoiceGenerator weight hash drift")
    _require_sha256(weight.get("sha256"), "VoiceGenerator model weight hash")

    source_lock = components.get("moss-tts-source-for-voice-generator")
    official_audit = baseline.get("official_example_audit")
    if not isinstance(source_lock, dict) or not isinstance(official_audit, dict):
        raise AuditError("official source audit metadata is missing")
    if official_audit.get("source_revision") != source_lock.get("revision"):
        raise AuditError("official source audit revision drift")
    source_card = next(
        (
            artifact
            for artifact in source_lock.get("artifacts", [])
            if isinstance(artifact, dict)
            and artifact.get("path") == "docs/moss_voice_generator_model_card.md"
        ),
        None,
    )
    if not isinstance(source_card, dict) or official_audit.get(
        "source_model_card_git_blob_sha1"
    ) != source_card.get("hash"):
        raise AuditError("official source model card blob drift")
    if official_audit.get("device_selection") != "cuda_if_available_else_cpu":
        raise AuditError("official device selection metadata drift")
    if official_audit.get("mps_branch_present") is not False:
        raise AuditError("baseline must not claim an official MPS branch")

    codec = baseline.get("default_audio_tokenizer")
    if not isinstance(codec, dict):
        raise AuditError("default_audio_tokenizer metadata is missing")
    if codec.get("repository") != "OpenMOSS-Team/MOSS-Audio-Tokenizer":
        raise AuditError("unexpected default codec repository")
    codec_revision = codec.get("observed_revision")
    if not isinstance(codec_revision, str) or not GIT_SHA_RE.fullmatch(codec_revision):
        raise AuditError("default codec observation needs a fixed revision")
    if codec_revision in {component.get("revision") for component in raw_components if isinstance(component, dict)}:
        raise AuditError("codec revision state says unfrozen but revision is already in T0-A lock")
    weights = codec.get("weight_files")
    if not isinstance(weights, list) or len(weights) != 2:
        raise AuditError("default codec must list both weight shards")
    for item in weights:
        if not isinstance(item, dict):
            raise AuditError("default codec weight item must be an object")
        _require_int(item, "bytes")
        _require_sha256(item.get("sha256"), "default codec weight hash")
    codec_snapshot = _require_int(codec, "snapshot_bytes")
    if sum(int(item["bytes"]) for item in weights) >= codec_snapshot:
        raise AuditError("codec snapshot must include metadata in addition to weight shards")

    prompts = baseline.get("project_owned_prompt_profiles")
    if not isinstance(prompts, list) or not prompts:
        raise AuditError("at least one project-owned voice prompt profile is required")
    seen_prompt_ids: set[str] = set()
    for prompt in prompts:
        if not isinstance(prompt, dict):
            raise AuditError("prompt profile must be an object")
        prompt_id = prompt.get("id")
        if not isinstance(prompt_id, str) or not prompt_id or prompt_id in seen_prompt_ids:
            raise AuditError("prompt profile id is missing or duplicated")
        description = prompt.get("description")
        case_id = prompt.get("fixture_case_id")
        if not isinstance(description, str) or not description.strip():
            raise AuditError(f"prompt profile {prompt_id} has no description")
        if not isinstance(case_id, str) or not case_id:
            raise AuditError(f"prompt profile {prompt_id} has no fixture case")
        seen_prompt_ids.add(prompt_id)

    policy = baseline.get("decision_policy")
    host_gate = baseline.get("host_gate")
    if not isinstance(policy, dict) or policy.get("default_until_all_pass") != "hide":
        raise AuditError("decision policy must fail closed to hide")
    if not isinstance(host_gate, dict):
        raise AuditError("host gate metadata is missing")
    _require_int(host_gate, "physical_memory_bytes")
    _require_int(host_gate, "minimum_free_memory_headroom_bytes")
    return baseline, model_lock


def audit_fixed_source_text(
    model_card_text: str,
    processor_text: str,
    config: dict[str, Any],
    pyproject_text: str,
) -> dict[str, Any]:
    """Inspect text only; this function never imports the inspected source."""

    compact_card = re.sub(r"\s+", " ", model_card_text)
    cuda_cpu_expression = (
        'device = "cuda" if torch.cuda.is_available() else "cpu"' in compact_card
    )
    cpu_float32 = (
        'dtype = torch.bfloat16 if device == "cuda" else torch.float32' in compact_card
    )
    mps_tokens = (
        "torch.backends.mps",
        'device = "mps"',
        "device == \"mps\"",
        "device == 'mps'",
    )
    explicit_mps_branch = any(token in model_card_text for token in mps_tokens)
    codec_default = bool(
        re.search(
            r"codec_path[^\n]{0,160}OpenMOSS-Team/MOSS-Audio-Tokenizer",
            processor_text,
            flags=re.MULTILINE,
        )
    )
    checks = {
        "cuda_or_cpu_only_expression_present": cuda_cpu_expression,
        "cpu_float32_expression_present": cpu_float32,
        "explicit_mps_branch_present": explicit_mps_branch,
        "default_full_codec_path_present": codec_default,
        "model_config_dtype_bfloat16": config.get("dtype") == "bfloat16",
        "model_config_backbone_qwen3_1_7b": (
            isinstance(config.get("language_config"), dict)
            and config["language_config"].get("_name_or_path") == "Qwen/Qwen3-1.7B"
        ),
        "pyproject_cuda_torch_pin_present": "torch==2.9.1+cu128" in pyproject_text,
        "pyproject_transformers_5_pin_present": "transformers==5.0.0" in pyproject_text,
    }
    checks["official_mps_path_supported"] = bool(
        explicit_mps_branch and not cuda_cpu_expression
    )
    checks["metadata_audit_passed"] = all(
        checks[key]
        for key in (
            "cuda_or_cpu_only_expression_present",
            "cpu_float32_expression_present",
            "default_full_codec_path_present",
            "model_config_dtype_bfloat16",
            "model_config_backbone_qwen3_1_7b",
            "pyproject_cuda_torch_pin_present",
            "pyproject_transformers_5_pin_present",
        )
    ) and not explicit_mps_branch
    return checks


def derive_feasibility(baseline: dict[str, Any]) -> dict[str, Any]:
    voice = baseline["voice_generator"]
    codec = baseline["default_audio_tokenizer"]
    host = baseline["host_gate"]
    voice_weight_bytes = int(voice["model_weight"]["bytes"])
    codec_weight_bytes = sum(int(item["bytes"]) for item in codec["weight_files"])
    physical_memory_bytes = int(host["physical_memory_bytes"])
    combined_snapshot_bytes = int(voice["selected_bytes"]) + int(codec["snapshot_bytes"])
    combined_weight_bytes = voice_weight_bytes + codec_weight_bytes
    # The fixed official example chooses float32 on CPU while the model config is
    # bfloat16.  Doubling the VoiceGenerator weight bytes is only a lower-bound
    # estimate; it excludes allocator, activations, KV cache, Python and OS memory.
    cpu_static_weight_estimate_bytes = voice_weight_bytes * 2 + codec_weight_bytes
    required_headroom = int(host["minimum_free_memory_headroom_bytes"])
    return {
        "decision": "hide",
        "decision_scope": "current product capability; revisit only after all real gates pass",
        "real_model_downloads": 0,
        "real_model_imports": 0,
        "real_model_loads": 0,
        "real_candidate_generations": 0,
        "real_nano_clone_runs": 0,
        "manual_listening_completed": 0,
        "voice_generator_selected_bytes": int(voice["selected_bytes"]),
        "default_codec_snapshot_bytes": int(codec["snapshot_bytes"]),
        "combined_snapshot_bytes": combined_snapshot_bytes,
        "combined_snapshot_gib": round(combined_snapshot_bytes / 1024**3, 6),
        "combined_weight_bytes": combined_weight_bytes,
        "combined_weight_fraction_of_16_gib": round(
            combined_weight_bytes / physical_memory_bytes, 6
        ),
        "cpu_static_weight_estimate_bytes": cpu_static_weight_estimate_bytes,
        "cpu_static_weight_estimate_gib": round(
            cpu_static_weight_estimate_bytes / 1024**3, 6
        ),
        "cpu_static_weight_fraction_of_16_gib": round(
            cpu_static_weight_estimate_bytes / physical_memory_bytes, 6
        ),
        "cpu_static_estimated_headroom_bytes": (
            physical_memory_bytes - cpu_static_weight_estimate_bytes
        ),
        "required_free_memory_headroom_bytes": required_headroom,
        "cpu_headroom_gate_passed": (
            physical_memory_bytes - cpu_static_weight_estimate_bytes >= required_headroom
        ),
        "official_device_paths": ["cuda", "cpu"],
        "official_mps_path_claimed": False,
        "host_torch_mps_available_is_not_model_support": True,
        "full_codec_revision_frozen_in_t0_a": False,
        "isolated_voice_generator_runtime_lock_ready": False,
        "metadata_only_cannot_measure": [
            "first_packet_ms",
            "rtf",
            "peak_rss_bytes",
            "peak_accelerator_bytes",
            "candidate_audio_quality",
            "nano_clone_retention",
        ],
        "fallback": baseline["decision_policy"]["fallback"],
    }


def physical_memory_bytes() -> int:
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            value = int(completed.stdout.strip())
            if value > 0:
                return value
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        value = int(page_size) * int(page_count)
        if value > 0:
            return value
    except (AttributeError, OSError, ValueError):
        pass
    raise AuditError("cannot determine physical memory without importing model libraries")


def hardware_name() -> str:
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            value = completed.stdout.strip()
            if value:
                return value
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or platform.machine() or "unknown hardware"


def make_case(case: dict[str, Any], *, prompt_id: str) -> dict[str, Any]:
    case_input = case["input"]
    return {
        "case_id": str(case["id"]),
        "status": "blocked",
        "input": {
            "text_ids": list(case_input["text_ids"]),
            "text_sha256": list(case_input["text_sha256"]),
            "combined_sha256": str(case_input["combined_sha256"]),
            "reference_profile_id": None,
            "reference_sha256": None,
        },
        "timing": {
            "first_packet_ms": None,
            "synthesis_wall_ms": None,
            "audio_duration_seconds": None,
            "rtf": None,
        },
        "resources": {
            "peak_rss_bytes": None,
            "peak_accelerator_bytes": None,
        },
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
        "error": {
            "category": "precondition",
            "code": "VOICE_GENERATOR_REAL_PROBE_NOT_AUTHORIZED_OR_RUN",
            "message_redacted": (
                "Real VoiceGenerator and Nano clone phases were not run; model locks, "
                "an isolated dependency lock and external media paths are required."
            ),
        },
        "listening": {
            "status": "skipped_with_reason",
            "reviewer": None,
            "verdict": "not_reviewed",
            "defects": {key: None for key in DEFECT_KEYS},
            "notes_redacted": None,
            "skipped_reason": "No candidate audio exists in this metadata-only audit.",
        },
        "diagnostics": {
            "voice_prompt_profile_id": prompt_id,
            "voice_generator_invocations": 0,
            "nano_clone_invocations": 0,
            "audio_files_created": 0,
        },
    }


def build_result(
    *,
    baseline_path: Path,
    baseline: dict[str, Any],
    manifest: dict[str, Any],
    cases: dict[str, dict[str, Any]],
    argv: list[str],
    source_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    started = datetime.now().astimezone()
    prompts = baseline["project_owned_prompt_profiles"]
    output_cases: list[dict[str, Any]] = []
    for prompt in prompts:
        case_id = prompt["fixture_case_id"]
        if case_id not in cases:
            raise AuditError(f"prompt profile references missing fixture case: {case_id}")
        output_cases.append(make_case(cases[case_id], prompt_id=prompt["id"]))
    finished = datetime.now().astimezone()
    feasibility = derive_feasibility(baseline)
    host_memory = physical_memory_bytes()
    target_memory = int(baseline["host_gate"]["physical_memory_bytes"])
    feasibility["observed_host_physical_memory_bytes"] = host_memory
    feasibility["host_matches_target_memory"] = host_memory == target_memory
    baseline_hash = sha256_file(baseline_path)
    voice = baseline["voice_generator"]
    codec = baseline["default_audio_tokenizer"]
    run_id = f"T0-D-{started.strftime('%Y%m%dT%H%M%S%z')}-{uuid.uuid4().hex[:8]}"
    return {
        "schema_version": RESULT_SCHEMA,
        "run": {
            "run_id": run_id,
            "benchmark_id": "voice-generator-metadata-feasibility",
            "work_package_id": "T0-D",
            "status": "blocked",
            "started_at": started.isoformat(timespec="milliseconds"),
            "finished_at": finished.isoformat(timespec="milliseconds"),
            "environment": {
                "hardware": hardware_name(),
                "os_name": platform.system(),
                "os_version": platform.mac_ver()[0] or platform.release(),
                "architecture": platform.machine(),
                "python_version": platform.python_version(),
                "physical_memory_bytes": host_memory,
            },
            "model": {
                "name": "OpenMOSS-Team/MOSS-VoiceGenerator",
                "revision": voice["revision"],
                "revision_sha256": None,
                "revision_hash_status": "unavailable",
                "execution_backend": "metadata-audit-no-model-import",
                "artifacts": [
                    {
                        "name": "T0-D metadata baseline",
                        "revision": BASELINE_SCHEMA,
                        "sha256": baseline_hash,
                        "hash_status": "verified",
                        "source": "repository-owned prototype metadata baseline",
                    },
                    {
                        "name": "MOSS-VoiceGenerator model.safetensors",
                        "revision": voice["revision"],
                        "sha256": None,
                        "hash_status": "unavailable",
                        "source": "official Hugging Face locked metadata; artifact not downloaded",
                    },
                    {
                        "name": "MOSS-Audio-Tokenizer full codec",
                        "revision": codec["observed_revision"],
                        "sha256": None,
                        "hash_status": "unavailable",
                        "source": "official Hugging Face observed metadata; revision not frozen in T0-A",
                    },
                ],
            },
            "parameters": {
                "fixture_set_id": manifest["fixture_set_id"],
                "mode": "metadata-only-dry-run",
                "expected_voice_generator_weight_sha256": voice["model_weight"]["sha256"],
                "expected_voice_generator_weight_bytes": voice["model_weight"]["bytes"],
                "expected_codec_weight_sha256": [
                    item["sha256"] for item in codec["weight_files"]
                ],
                "metadata_source_audit": source_audit,
                "feasibility": feasibility,
            },
            "command": {"argv": argv, "exit_code": 0},
            "privacy": {
                "fixture_only": True,
                "contains_user_text": False,
                "contains_private_reference_audio": False,
                "evidence_contains_audio": False,
            },
        },
        "cases": output_cases,
    }


def inspect_source_directory(source_dir: Path) -> dict[str, Any]:
    """Optionally inspect an already-authorized small source snapshot, read-only."""

    if not source_dir.is_dir():
        raise AuditError("source audit directory does not exist")
    paths = {
        "model_card": source_dir / "docs" / "moss_voice_generator_model_card.md",
        "processor": source_dir / "processing_moss_tts.py",
        "config": source_dir / "config.json",
        "pyproject": source_dir / "pyproject.toml",
    }
    missing = [key for key, path in paths.items() if not path.is_file()]
    if missing:
        raise AuditError("source audit directory is missing: " + ", ".join(sorted(missing)))
    for path in paths.values():
        if path.stat().st_size > 2 * 1024 * 1024:
            raise AuditError("source audit refuses files larger than 2 MiB")
    config = load_json_object(paths["config"])
    result = audit_fixed_source_text(
        paths["model_card"].read_text(encoding="utf-8"),
        paths["processor"].read_text(encoding="utf-8"),
        config,
        paths["pyproject"].read_text(encoding="utf-8"),
    )
    result["files"] = {
        key: {"name": path.name, "sha256": sha256_file(path)}
        for key, path in paths.items()
    }
    result["imports_executed"] = 0
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate T0-D VoiceGenerator metadata and emit blocked, audio-free "
            "moss-tts-benchmark-result/1.0 evidence."
        )
    )
    parser.add_argument("--fixture-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--metadata-baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--model-lock", type=Path, default=DEFAULT_MODEL_LOCK)
    parser.add_argument(
        "--source-audit-dir",
        type=Path,
        help=(
            "Optional existing, authorized small source snapshot to inspect as text. "
            "No module is imported and no download occurs."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit alias for the safe default metadata-only run.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Atomically replace an existing T0-D metrics.json after validating its owner/schema.",
    )
    return parser.parse_args(argv)


def validate_output_path(output_dir: Path) -> Path:
    resolved = output_dir.resolve()
    if resolved == REPOSITORY_ROOT.resolve():
        raise AuditError("output directory cannot be the repository root")
    metrics_path = output_dir / "metrics.json"
    if metrics_path.exists() and not metrics_path.is_file():
        raise AuditError("metrics.json exists but is not a regular file")
    return metrics_path


def validate_replace_target(metrics_path: Path) -> None:
    existing = load_json_object(metrics_path)
    if existing.get("schema_version") != RESULT_SCHEMA:
        raise AuditError("refusing to replace an unknown metrics schema")
    run = existing.get("run")
    if not isinstance(run, dict) or run.get("work_package_id") != "T0-D":
        raise AuditError("refusing to replace metrics owned by another work package")
    privacy = run.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("evidence_contains_audio") is not False:
        raise AuditError("refusing to replace metrics that may claim embedded audio")


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw_argv)
        # The fixture is deliberately validated before metadata/source inspection.
        manifest, _texts, cases = validate_fixture_manifest(args.fixture_manifest)
        baseline, _model_lock = validate_metadata_baseline(
            args.metadata_baseline, args.model_lock
        )
        source_audit = (
            inspect_source_directory(args.source_audit_dir)
            if args.source_audit_dir is not None
            else {
                "mode": "fixed-official-URL-manual-audit-recorded-in-baseline",
                "imports_executed": 0,
                "official_mps_path_supported": False,
                "runtime_result": False,
            }
        )
        metrics_path = validate_output_path(args.output_dir)
        if metrics_path.exists():
            if not args.replace_existing:
                raise AuditError("metrics.json already exists; use --replace-existing explicitly")
            validate_replace_target(metrics_path)
        command_argv = [sys.executable, str(Path(__file__).resolve()), *raw_argv]
        result = build_result(
            baseline_path=args.metadata_baseline,
            baseline=baseline,
            manifest=manifest,
            cases=cases,
            argv=command_argv,
            source_audit=source_audit,
        )
        atomic_write_json(metrics_path, result)
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "decision": "hide",
                    "metrics": str(metrics_path),
                    "real_model_downloads": 0,
                    "real_model_loads": 0,
                    "audio_files_created": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except AuditError as error:
        print(
            json.dumps(
                {"error": {"category": "input", "code": "T0D_AUDIT_ERROR", "message": str(error)}},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
