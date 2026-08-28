#!/usr/bin/env python3
"""Run redacted production-Sidecar smoke/recovery or endurance gates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
import wave


REFERENCE_PROFILES = (
    ("isolated-tech-ref-03s", "reference-3s.wav", 3.0),
    ("isolated-tech-ref-05s", "reference-5s.wav", 5.0),
    ("isolated-tech-ref-08s", "reference-8s.wav", 8.0),
    ("isolated-tech-ref-12s", "reference-12s.wav", 12.0),
)


class ReferenceManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ReferenceFixture:
    technical_profile_id: str
    file_name: str
    expected_sha256: str
    actual_sha256: str
    expected_size_bytes: int
    actual_size_bytes: int
    expected_duration_seconds: float
    actual_duration_seconds: float
    duration_tolerance_seconds: float
    audio_format: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int

    def evidence(self) -> dict[str, object]:
        return {
            "technical_profile_id": self.technical_profile_id,
            "file_name": self.file_name,
            "format": self.audio_format,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "expected_size_bytes": self.expected_size_bytes,
            "actual_size_bytes": self.actual_size_bytes,
            "expected_duration_seconds": self.expected_duration_seconds,
            "actual_duration_seconds": self.actual_duration_seconds,
            "duration_tolerance_seconds": self.duration_tolerance_seconds,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "sample_width_bytes": self.sample_width_bytes,
        }


def _manifest_error(message: str) -> ReferenceManifestError:
    return ReferenceManifestError(f"reference manifest validation failed: {message}")


def load_reference_manifest(manifest_path: Path, fixture_root: Path) -> list[ReferenceFixture]:
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _manifest_error("manifest is not readable UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise _manifest_error("schema root must be an object")
    required_top_level = {"schema_version", "status", "repository_contains_audio", "assets", "rights_and_scope"}
    if not required_top_level.issubset(document):
        raise _manifest_error("schema fields are incomplete")
    if document["schema_version"] != "moss-tts-reference-prep/1.0":
        raise _manifest_error("schema_version is not frozen")
    if document["status"] != "prepared_isolated_test_only":
        raise _manifest_error("status is not isolated-test-only")
    if document["repository_contains_audio"] is not False:
        raise _manifest_error("repository audio boundary is invalid")
    rights = document["rights_and_scope"]
    if not isinstance(rights, dict):
        raise _manifest_error("rights_and_scope must be an object")
    expected_rights = {
        "classification": "isolated-test-only technical reference candidate",
        "production_rights_granted": False,
        "product_voice_asset": False,
        "distribution_allowed": False,
    }
    if any(rights.get(key) != value for key, value in expected_rights.items()):
        raise _manifest_error("rights do not permit this isolated technical gate")
    assets = document["assets"]
    if not isinstance(assets, list) or len(assets) != len(REFERENCE_PROFILES):
        raise _manifest_error("assets must contain exactly the four profiles")

    try:
        root = fixture_root.resolve(strict=True)
    except OSError as error:
        raise _manifest_error("fixture root is unavailable") from error
    fixtures: list[ReferenceFixture] = []
    for index, (profile_id, expected_name, expected_duration) in enumerate(REFERENCE_PROFILES):
        row = assets[index]
        if not isinstance(row, dict):
            raise _manifest_error("asset schema row must be an object")
        required_asset_fields = {
            "technical_profile_id", "target_duration_seconds", "atrim_end_sample", "file_name",
            "file_size_bytes", "sha256", "pcm_sha256", "actual_duration_seconds", "frame_count",
            "sample_rate_hz", "channels", "sample_width_bytes", "codec", "container",
            "source_pcm_prefix_exact", "repeat_build_byte_exact",
        }
        if not required_asset_fields.issubset(row):
            raise _manifest_error("asset schema fields are incomplete")
        if row["technical_profile_id"] != profile_id:
            raise _manifest_error("technical profile identity or order is invalid")
        name = row["file_name"]
        if not isinstance(name, str) or Path(name).name != name or name != expected_name:
            raise _manifest_error("asset filename is invalid")
        if row["target_duration_seconds"] != int(expected_duration):
            raise _manifest_error("target duration profile is invalid")
        if row["container"] != "WAV" or row["codec"] != "pcm_sle" or not name.endswith(".wav"):
            raise _manifest_error("asset format is not frozen WAV PCM")
        if row["sample_rate_hz"] != 48_000 or row["channels"] != 2 or row["sample_width_bytes"] != 2:
            raise _manifest_error("asset audio descriptor is invalid")
        expected_frames = int(expected_duration * 48_000)
        if row["frame_count"] != expected_frames or row["atrim_end_sample"] != expected_frames:
            raise _manifest_error("asset frame count is invalid")
        if row["source_pcm_prefix_exact"] is not True or row["repeat_build_byte_exact"] is not True:
            raise _manifest_error("asset reproducibility flags are invalid")
        declared_hash = row["sha256"]
        if not isinstance(declared_hash, str) or re.fullmatch(r"[0-9a-f]{64}", declared_hash) is None:
            raise _manifest_error("declared SHA-256 is invalid")
        pcm_hash = row["pcm_sha256"]
        if not isinstance(pcm_hash, str) or re.fullmatch(r"[0-9a-f]{64}", pcm_hash) is None:
            raise _manifest_error("declared PCM SHA-256 is invalid")
        declared_size = row["file_size_bytes"]
        if isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size <= 0:
            raise _manifest_error("declared size is invalid")
        declared_duration = row["actual_duration_seconds"]
        if isinstance(declared_duration, bool) or not isinstance(declared_duration, (int, float)):
            raise _manifest_error("declared duration is invalid")
        tolerance = 1 / 48_000
        if not math.isclose(float(declared_duration), expected_duration, rel_tol=0.0, abs_tol=tolerance):
            raise _manifest_error("declared duration is outside one-frame tolerance")

        try:
            path = (root / name).resolve(strict=True)
        except OSError as error:
            raise _manifest_error("fixture file is unavailable") from error
        try:
            path.relative_to(root)
        except ValueError as error:
            raise _manifest_error("asset filename escapes fixture root") from error
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise _manifest_error("fixture file is unreadable") from error
        actual_size = len(payload)
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_size != declared_size:
            raise _manifest_error("actual size does not match manifest")
        if actual_hash != declared_hash:
            raise _manifest_error("actual SHA-256 does not match manifest")
        try:
            with wave.open(str(path), "rb") as stream:
                if stream.getcomptype() != "NONE":
                    raise _manifest_error("actual format is not uncompressed WAV")
                actual_rate = stream.getframerate()
                actual_channels = stream.getnchannels()
                actual_width = stream.getsampwidth()
                actual_frames = stream.getnframes()
        except (wave.Error, EOFError) as error:
            raise _manifest_error("actual format is not valid WAV") from error
        if (actual_rate, actual_channels, actual_width) != (48_000, 2, 2):
            raise _manifest_error("actual format descriptor does not match manifest")
        actual_duration = actual_frames / actual_rate
        if actual_frames != expected_frames or not math.isclose(actual_duration, expected_duration, rel_tol=0.0, abs_tol=tolerance):
            raise _manifest_error("actual duration is outside one-frame tolerance")
        fixtures.append(
            ReferenceFixture(
                technical_profile_id=profile_id,
                file_name=name,
                expected_sha256=declared_hash,
                actual_sha256=actual_hash,
                expected_size_bytes=declared_size,
                actual_size_bytes=actual_size,
                expected_duration_seconds=expected_duration,
                actual_duration_seconds=actual_duration,
                duration_tolerance_seconds=tolerance,
                audio_format="wav",
                sample_rate_hz=actual_rate,
                channels=actual_channels,
                sample_width_bytes=actual_width,
            )
        )
    return fixtures


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run(command: list[str], *, timeout: float = 60, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, input=input_bytes, capture_output=True, check=True, timeout=timeout)


class Gate:
    def __init__(self, compose_file: Path, qwenpaw_container: str) -> None:
        self.base = ["docker", "compose", "-f", str(compose_file.resolve())]
        self.qwenpaw_container = qwenpaw_container

    def compose(self, *arguments: str, timeout: float = 120) -> bytes:
        return run([*self.base, *arguments], timeout=timeout).stdout

    def harness(self, row: dict[str, object], *, timeout: float = 330) -> dict[str, Any]:
        completed = run(
            [*self.base, "exec", "-T", "pawapp-harness", "python", "/app/pawapp_harness.py"],
            input_bytes=json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            timeout=timeout,
        )
        value = json.loads(completed.stdout.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("harness response is invalid")
        return value

    def spawn_harness(self, row: dict[str, object]) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [*self.base, "exec", "-T", "pawapp-harness", "python", "/app/pawapp_harness.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        process.stdin.close()
        process.stdin = None
        return process

    def finish_background(self, process: subprocess.Popen[bytes], *, timeout: float = 330) -> dict[str, object]:
        process.wait(timeout=timeout)
        assert process.stdout is not None and process.stderr is not None
        stdout = process.stdout.read()
        stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        return {
            "returncode": process.returncode,
            "response": json.loads(stdout.decode("utf-8")) if process.returncode == 0 and stdout else None,
            "error_class": stderr.splitlines()[-1] if stderr else None,
        }

    def capability(self) -> dict[str, Any]:
        return self.harness({"operation": "capabilities"})

    def wait_healthy(self, timeout: float = 240) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            container = self.container_id("sidecar")
            if container:
                state = json.loads(run(["docker", "inspect", container], timeout=10).stdout)[0]["State"]
                if state.get("Health", {}).get("Status") == "healthy":
                    return
                if state.get("Status") == "exited":
                    raise RuntimeError("sidecar exited before becoming healthy")
            time.sleep(1)
        raise TimeoutError("sidecar health timeout")

    def wait_active(self, minimum_accepted: int, timeout: float = 30) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            capability = self.capability()
            process = capability["process"]
            if process["accepted_request_count"] >= minimum_accepted and process["active_request_count"] == 1:
                return capability
            time.sleep(0.05)
        raise TimeoutError("request did not remain active long enough for control probe")

    def container_id(self, service: str) -> str:
        return self.compose("ps", "-q", service, timeout=15).decode("ascii").strip()

    def inspect_sidecar(self) -> dict[str, object]:
        container = self.container_id("sidecar")
        row = json.loads(run(["docker", "inspect", container], timeout=15).stdout)[0]
        ports = row["NetworkSettings"].get("Ports") or {}
        mounts = [
            {"destination": item["Destination"], "read_write": item["RW"], "type": item["Type"]}
            for item in row.get("Mounts", [])
        ]
        return {
            "container_id_prefix": container[:12],
            "image": row["Image"],
            "platform": row.get("Platform"),
            "health": row["State"].get("Health", {}).get("Status"),
            "published_host_bindings": {
                key: value for key, value in ports.items() if value is not None
            },
            "networks": sorted(row["NetworkSettings"].get("Networks", {})),
            "mounts": mounts,
            "read_only_rootfs": row["HostConfig"].get("ReadonlyRootfs"),
            "privileged": row["HostConfig"].get("Privileged"),
            "cap_drop": row["HostConfig"].get("CapDrop"),
            "security_opt": row["HostConfig"].get("SecurityOpt"),
            "memory_limit_bytes": row["HostConfig"].get("Memory"),
            "pids_limit": row["HostConfig"].get("PidsLimit"),
        }

    def docker_stats(self, container: str) -> dict[str, object]:
        output = run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container], timeout=20).stdout
        return json.loads(output)

    def scratch_audit(self) -> dict[str, object]:
        program = (
            "import json,pathlib; roots=[pathlib.Path('/tmp/moss-output'),pathlib.Path('/tmp/moss-reference')]; "
            "files=[p for r in roots if r.exists() for p in r.rglob('*') if p.is_file()]; "
            "print(json.dumps({'scratch_file_count':len(files),'partial_count':sum('.part' in p.name for p in files)}))"
        )
        output = self.compose("exec", "-T", "sidecar", "python", "-c", program, timeout=20)
        return json.loads(output)

    def qwenpaw_snapshot(self) -> dict[str, object]:
        inspect = json.loads(run(["docker", "inspect", self.qwenpaw_container], timeout=15).stdout)[0]
        return {
            "container_id_prefix": inspect["Id"][:12],
            "status": inspect["State"]["Status"],
            "health": inspect["State"].get("Health", {}).get("Status"),
            "stats": self.docker_stats(self.qwenpaw_container),
        }

    def host_memory_snapshot(self) -> dict[str, object]:
        pressure = run(["memory_pressure", "-Q"], timeout=10).stdout.decode("utf-8", errors="replace")
        swap = run(["sysctl", "vm.swapusage"], timeout=10).stdout.decode("utf-8", errors="replace").strip()
        free_line = next((line for line in pressure.splitlines() if "free percentage" in line.lower()), "unavailable")
        return {"memory_pressure_free": free_line, "swapusage": swap, "causality": "snapshot_only"}


def synth_row(
    index: int,
    *,
    prefix: str,
    reference: ReferenceFixture | None = None,
    operation: str = "synthesize",
) -> dict[str, object]:
    return {
        "operation": operation,
        "request_id": f"{prefix}-request-{index:08d}",
        "asset_id": f"{prefix}-asset-{index:08d}",
        "text": "这是一段由项目拥有并授权用于技术验证的中文测试文本。",
        "voice": "Junhao",
        "seed": 42,
        "max_new_frames": 100,
        "sample_mode": "fixed",
        "reference_fixture_name": reference.file_name if reference else None,
        "reference_asset_id": f"reference-asset-{index:08d}" if reference else None,
    }


def write_result(path: Path, result: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def cleanup_test_media_root() -> dict[str, object]:
    raw_root = os.environ.get("MOSS_PAWAPP_MEDIA_ROOT")
    if not raw_root:
        raise RuntimeError("test media root is missing")
    root = Path(raw_root).resolve()
    marker = root / ".t0b-sidecar-test-root"
    if not root.name.startswith("T0-B-sidecar-") or not marker.is_file():
        raise RuntimeError("refusing to clean an unmarked media root")
    files = [path for path in root.rglob("*") if path.is_file()]
    if any(path != marker and path.suffix not in {".wav", ".part"} for path in files):
        raise RuntimeError("refusing to clean media root with unexpected files")
    removed_bytes = sum(path.stat().st_size for path in files if path != marker)
    for path in files:
        path.unlink()
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True):
        directory.rmdir()
    root.rmdir()
    return {"performed": True, "removed_file_count": len(files) - 1, "removed_bytes": removed_bytes}


def smoke(gate: Gate, references: list[ReferenceFixture]) -> dict[str, object]:
    gate.compose("up", "-d", "sidecar", "pawapp-harness", timeout=300)
    gate.wait_healthy()
    pre = {
        "captured_at": now(),
        "sidecar": gate.inspect_sidecar(),
        "sidecar_stats": gate.docker_stats(gate.container_id("sidecar")),
        "qwenpaw": gate.qwenpaw_snapshot(),
        "host": gate.host_memory_snapshot(),
        "capability": gate.capability(),
        "scratch": gate.scratch_audit(),
    }
    events: list[dict[str, object]] = []

    first = synth_row(1, prefix="smoke")
    first_result = gate.harness(first)
    events.append({"event": "published", "request_id": first["request_id"], "result": first_result})
    before_reuse = gate.capability()
    reuse = gate.harness(first)
    after_reuse = gate.capability()
    if reuse.get("status") != "reused" or not reuse.get("sidecar_request_skipped"):
        raise RuntimeError("ready asset was not reused by PawApp")
    if before_reuse["process"]["completed_request_count"] != after_reuse["process"]["completed_request_count"]:
        raise RuntimeError("ready reuse unexpectedly invoked Sidecar")
    events.append({"event": "ready_reused_without_synthesis", "request_id": first["request_id"], "result": reuse})

    for offset, fixture in enumerate(references, 10):
        row = synth_row(offset, prefix="reference", reference=fixture)
        result = gate.harness(row)
        events.append({
            "event": "reference_published",
            "request_id": row["request_id"],
            "fixture_profile": fixture.technical_profile_id,
            "reference_input": fixture.evidence(),
            "result": result,
        })
    if references:
        malicious = synth_row(90, prefix="negative", reference=references[0], operation="malicious_reference_hash_probe")
        rejection = gate.harness(malicious)
        if rejection != {"http_status": 400, "error_code": "REFERENCE_HASH_MISMATCH"}:
            raise RuntimeError("false reference hash was not rejected by Sidecar")
        events.append({"event": "false_reference_hash_rejected", "result": rejection})

    # A request accepted before cancel must return no audio to PawApp.
    cancel_row = synth_row(100, prefix="cancel")
    cancel_row["max_new_frames"] = 2000
    accepted_before = gate.capability()["process"]["accepted_request_count"]
    cancel_process = gate.spawn_harness(cancel_row)
    gate.wait_active(accepted_before + 1)
    cancel_ack = gate.harness({"operation": "cancel", "request_id": cancel_row["request_id"], "asset_id": cancel_row["asset_id"]})
    cancel_terminal = gate.finish_background(cancel_process)
    if cancel_terminal["returncode"] == 0:
        raise RuntimeError("cancelled request unexpectedly published")
    events.append({"event": "cancelled_without_publish", "ack": cancel_ack, "terminal": cancel_terminal})

    # SIGKILL after the request is observable as active. The public control
    # plane does not expose a distinct inference-entered event.
    crash_row = synth_row(110, prefix="crash")
    crash_row["max_new_frames"] = 2000
    before_crash_capability = gate.capability()
    crash_process = gate.spawn_harness(crash_row)
    gate.wait_active(before_crash_capability["process"]["accepted_request_count"] + 1)
    old_container = gate.container_id("sidecar")
    run(["docker", "kill", "--signal", "KILL", old_container], timeout=20)
    crash_terminal = gate.finish_background(crash_process, timeout=30)
    gate.compose("up", "-d", "--no-deps", "sidecar", timeout=120)
    gate.wait_healthy()
    after_crash_capability = gate.capability()
    if after_crash_capability["process"]["generation"] == before_crash_capability["process"]["generation"]:
        raise RuntimeError("SIGKILL recovery did not create a new Sidecar generation")
    recovery_row = synth_row(111, prefix="recovery")
    recovery = gate.harness(recovery_row)
    events.append({
        "event": "sigkill_recovered",
        "old_container_id_prefix": old_container[:12],
        "new_container_id_prefix": gate.container_id("sidecar")[:12],
        "old_generation": before_crash_capability["process"]["generation"],
        "new_generation": after_crash_capability["process"]["generation"],
        "crash_terminal": crash_terminal,
        "recovery": recovery,
    })

    before_restart = gate.capability()
    gate.compose("restart", "sidecar", timeout=120)
    gate.wait_healthy()
    after_restart = gate.capability()
    if before_restart["process"]["generation"] == after_restart["process"]["generation"]:
        raise RuntimeError("container restart did not create a new generation")
    post_restart_row = synth_row(120, prefix="restart")
    post_restart = gate.harness(post_restart_row)
    events.append({"event": "container_restart", "old_generation": before_restart["process"]["generation"], "new_generation": after_restart["process"]["generation"], "post_restart": post_restart})

    audit = gate.harness({"operation": "audit_storage"})
    expected_wav_count = len(references) + 3
    if audit["partial_count"] != 0 or audit["unexpected_file_count"] != 0 or audit["wav_count"] != expected_wav_count:
        raise RuntimeError("PawApp test media contains partial or unexpected files")
    scratch = gate.scratch_audit()
    if scratch["scratch_file_count"] != 0 or scratch["partial_count"] != 0:
        raise RuntimeError("Sidecar scratch was not cleaned")
    post = {
        "captured_at": now(),
        "sidecar": gate.inspect_sidecar(),
        "sidecar_stats": gate.docker_stats(gate.container_id("sidecar")),
        "qwenpaw": gate.qwenpaw_snapshot(),
        "host": gate.host_memory_snapshot(),
        "capability": gate.capability(),
        "storage": audit,
        "scratch": scratch,
    }
    return {
        "schema_version": "moss-tts-linux-sidecar-smoke/1.0",
        "status": "passed",
        "evidence_kind": "real_nano" if references else "fake_protocol",
        "contains_audio": False,
        "contains_private_reference_audio": False,
        "pre": pre,
        "events": events,
        "post": post,
    }


def reference_recheck(
    gate: Gate,
    references: list[ReferenceFixture],
    manifest_path: Path,
    fixture_root: Path,
) -> dict[str, object]:
    if len(references) != len(REFERENCE_PROFILES):
        raise RuntimeError("reference recheck requires exactly four validated fixtures")
    gate.compose("up", "-d", "sidecar", "pawapp-harness", timeout=300)
    gate.wait_healthy()
    pre = {
        "captured_at": now(),
        "sidecar": gate.inspect_sidecar(),
        "sidecar_stats": gate.docker_stats(gate.container_id("sidecar")),
        "qwenpaw": gate.qwenpaw_snapshot(),
        "host": gate.host_memory_snapshot(),
        "capability": gate.capability(),
        "scratch": gate.scratch_audit(),
    }
    events: list[dict[str, object]] = []
    for index, fixture in enumerate(references, 1):
        pre_request_fixture = load_reference_manifest(manifest_path, fixture_root)[index - 1]
        if pre_request_fixture.evidence() != fixture.evidence():
            raise RuntimeError("reference fixture changed before request")
        row = synth_row(index, prefix="reference-recheck", reference=fixture)
        result = gate.harness(row)
        post_request_fixture = load_reference_manifest(manifest_path, fixture_root)[index - 1]
        if post_request_fixture.evidence() != fixture.evidence():
            raise RuntimeError("reference fixture changed during request")
        events.append({
            "event": "reference_published",
            "request_id": row["request_id"],
            "fixture_profile": fixture.technical_profile_id,
            "reference_input": {
                "pre_request": pre_request_fixture.evidence(),
                "post_request": post_request_fixture.evidence(),
            },
            "result": result,
        })
    storage = gate.harness({"operation": "audit_storage"})
    scratch = gate.scratch_audit()
    if storage != {"wav_count": 4, "partial_count": 0, "unexpected_file_count": 0}:
        raise RuntimeError("reference recheck media audit failed")
    if scratch != {"scratch_file_count": 0, "partial_count": 0}:
        raise RuntimeError("reference recheck scratch audit failed")
    return {
        "schema_version": "moss-tts-linux-sidecar-reference-recheck/1.0",
        "status": "passed",
        "evidence_kind": "real_nano_reference_only",
        "contains_audio": False,
        "contains_private_reference_audio": False,
        "manifest_validation": {
            "schema_version": "moss-tts-reference-prep/1.0",
            "status": "prepared_isolated_test_only",
            "fixture_count": len(references),
            "production_rights_granted": False,
        },
        "pre": pre,
        "events": events,
        "post": {
            "captured_at": now(),
            "sidecar": gate.inspect_sidecar(),
            "sidecar_stats": gate.docker_stats(gate.container_id("sidecar")),
            "qwenpaw": gate.qwenpaw_snapshot(),
            "host": gate.host_memory_snapshot(),
            "capability": gate.capability(),
            "storage": storage,
            "scratch": scratch,
        },
    }


def endurance(gate: Gate, duration_seconds: int) -> dict[str, object]:
    gate.wait_healthy()
    started = time.monotonic()
    deadline = started + duration_seconds
    requests: list[dict[str, object]] = []
    resource_snapshots: list[dict[str, object]] = []
    generations: set[str] = set()
    failures: list[dict[str, object]] = []
    index = 0
    next_snapshot = started
    while time.monotonic() < deadline:
        index += 1
        row = synth_row(index, prefix="endurance")
        requested_at = time.monotonic()
        try:
            result = gate.harness(row)
            generations.add(str(result["worker_generation"]))
            requests.append({
                "request_id": row["request_id"],
                "wall_ms": result["wall_ms"],
                "ready_wav_ms": result["ready_wav_ms"],
                "peak_rss_bytes": result["peak_rss_bytes"],
                "worker_pid": result["worker_pid"],
                "worker_generation": result["worker_generation"],
                "actual_sha256": result["sha256"],
                "client_wall_ms": round((time.monotonic() - requested_at) * 1000.0, 6),
            })
        except Exception as error:
            failures.append({"request_id": row["request_id"], "error_class": type(error).__name__})
            break
        if time.monotonic() >= next_snapshot:
            resource_snapshots.append({
                "captured_at": now(),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "sidecar": gate.docker_stats(gate.container_id("sidecar")),
                "qwenpaw": gate.qwenpaw_snapshot(),
                "host": gate.host_memory_snapshot(),
            })
            next_snapshot += 60
    actual_duration = time.monotonic() - started
    audit = gate.harness({"operation": "audit_storage"})
    scratch = gate.scratch_audit()
    final_capability = gate.capability()
    status = "passed" if not failures and actual_duration >= duration_seconds and len(generations) == 1 and audit["partial_count"] == 0 and scratch["scratch_file_count"] == 0 else "failed"
    walls = sorted(float(row["wall_ms"]) for row in requests)
    return {
        "schema_version": "moss-tts-linux-sidecar-endurance/1.0",
        "status": status,
        "evidence_kind": "real_nano",
        "contains_audio": False,
        "requested_duration_seconds": duration_seconds,
        "actual_duration_seconds": round(actual_duration, 3),
        "completed_request_count": len(requests),
        "failure_count": len(failures),
        "failures": failures,
        "worker_generations": sorted(generations),
        "single_generation": len(generations) == 1,
        "worker_pids": sorted({int(row["worker_pid"]) for row in requests}),
        "peak_ru_maxrss_bytes": max((int(row["peak_rss_bytes"]) for row in requests), default=None),
        "ru_maxrss_semantics": "Linux getrusage(RUSAGE_SELF).ru_maxrss KiB converted to bytes; lifetime high-water mark, not current RSS",
        "wall_ms": {
            "minimum": walls[0] if walls else None,
            "median": walls[len(walls) // 2] if walls else None,
            "maximum": walls[-1] if walls else None,
        },
        "distinct_actual_audio_hash_count": len({row["actual_sha256"] for row in requests}),
        "storage": audit,
        "scratch": scratch,
        "final_capability": final_capability,
        "resource_snapshots": resource_snapshots,
        "qwenpaw_final": gate.qwenpaw_snapshot(),
        "host_final": gate.host_memory_snapshot(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "reference-recheck", "endurance"), required=True)
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--reference-manifest", type=Path)
    parser.add_argument("--qwenpaw-container", default="ai-novel-2026-qwenpaw-lab")
    parser.add_argument("--shutdown-after", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gate = Gate(args.compose_file, args.qwenpaw_container)
    result: dict[str, object]
    try:
        references: list[ReferenceFixture] = []
        if args.reference_manifest is not None:
            fixture_root = os.environ.get("MOSS_REFERENCE_FIXTURE_ROOT")
            if not fixture_root:
                raise ReferenceManifestError("reference fixture root is missing")
            references = load_reference_manifest(args.reference_manifest, Path(fixture_root))
        if args.mode == "reference-recheck" and not references:
            raise ReferenceManifestError("reference recheck requires the frozen four-case reference manifest")
        if args.mode == "smoke":
            result = smoke(gate, references)
        elif args.mode == "reference-recheck":
            result = reference_recheck(
                gate,
                references,
                args.reference_manifest,
                Path(os.environ["MOSS_REFERENCE_FIXTURE_ROOT"]),
            )
        else:
            result = endurance(gate, args.duration_seconds)
    except Exception as error:
        result = {
            "schema_version": "moss-tts-linux-sidecar-gate-failure/1.0",
            "status": "failed",
            "mode": args.mode,
            "error_class": type(error).__name__,
            "error_summary": str(error) if isinstance(error, (RuntimeError, TimeoutError)) else "redacted",
            "contains_audio": False,
        }
    if args.shutdown_after or args.mode == "endurance":
        try:
            gate.compose("down", "--timeout", "20", timeout=90)
            remaining = gate.compose("ps", "-aq", timeout=15).decode("ascii").split()
            result["shutdown"] = {
                "performed": True,
                "test_media_cleanup": cleanup_test_media_root(),
                "remaining_container_ids": remaining,
                "orphan_container_count": len(remaining),
            }
            if remaining:
                result["status"] = "failed"
        except Exception as error:
            result["shutdown"] = {"performed": False, "error_class": type(error).__name__}
            result["status"] = "failed"
    result["generated_at"] = now()
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write_result(args.output, result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
