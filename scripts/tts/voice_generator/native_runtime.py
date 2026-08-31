"""Fixed two-process macOS MPS/BF16 backend for the product host."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import threading
import time
from typing import Final
from uuid import UUID

from backend.narration.voice_generator_runtime import (
    CODEC_REVISION,
    EXPECTED_RUNTIME_FINGERPRINT,
    VOICE_GENERATOR_REVISION,
    VoiceGeneratorHostRequest,
    inspect_generated_wav,
)
from scripts.tts.voice_generator.host_server import (
    BackendGenerationResult,
    HostProtocolError,
)
from scripts.tts.voice_generator.product_adapters import (
    CODEC_ADAPTER_SCHEMA,
    GENERATION_ADAPTER_SCHEMA,
)


GENERATOR_TIMEOUT_SECONDS: Final = 180.0
CODEC_TIMEOUT_SECONDS: Final = 180.0
CRITICAL_GRACE_SECONDS: Final = 20.0
RECOVERY_TIMEOUT_SECONDS: Final = 60.0
_VM_LINE = re.compile(r"^([^:]+):\s+([0-9]+)\.")
_SWAP_VALUE = re.compile(r"used\s*=\s*([0-9.]+)([KMGTP])", re.IGNORECASE)
GENERATOR_FILES: Final = {
    "config.json": "5b6ccfbf309a5844c130d09c9b5fa8b9eef55db27f1b7072695483b6f5524685",
    "model.safetensors": "dbe345257ff9f6cc84195bed830a268b39d5e0b728ff3ba90e715150a49b16d4",
    "processing_moss_tts.py": "16dda5233f9f752518d07a6b780d6555945b48547fba0b4e7faf6eb2c4ed0038",
}
CODEC_FILES: Final = {
    "config.json": "0f669e288d39c9c0ffae4e39babe5167b57e89d3132f0785655d1096a8da8e45",
    "model.safetensors.index.json": "e107e83fee64adc3ccdb993975290cecb00fcf7d72cdaa388011abad16bcc82d",
    "model-00001-of-00002.safetensors": "037f441ed30a0ab59f6049de83b824a1b3bd6feb7dbd46c3fbca41fc2f649f28",
    "model-00002-of-00002.safetensors": "a187d73d2cda1c2d0676586d9d03c09c0a5813450266af32029c871493fc9582",
}
GENERATOR_SNAPSHOT_PATH: Final = (
    "OpenMOSS-Team--MOSS-VoiceGenerator",
    VOICE_GENERATOR_REVISION,
)
CODEC_SNAPSHOT_PATH: Final = (
    "OpenMOSS-Team--MOSS-Audio-Tokenizer",
    CODEC_REVISION,
)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    available_bytes: int
    swap_used_bytes: int
    pageouts: int
    pressure: str
    observed_monotonic: float


class NativeRuntimeBackend:
    """Run the two fixed product workers without accepting caller paths."""

    def __init__(self, *, runtime_python: Path, model_root: Path) -> None:
        # Invoke the venv entry path itself. Resolving it to the base interpreter
        # bypasses pyvenv.cfg and silently drops the pinned Torch environment.
        self.runtime_python = _strict_runtime_python(runtime_python)
        self._runtime_python_identity = _runtime_executable_identity(
            self.runtime_python
        )
        self.model_root = _strict_directory(model_root)
        self.generator_directory = _strict_directory(
            model_root.joinpath(*GENERATOR_SNAPSHOT_PATH)
        )
        self.codec_directory = _strict_directory(
            model_root.joinpath(*CODEC_SNAPSHOT_PATH)
        )
        self.worker_path = _strict_file(Path(__file__).with_name("native_worker.py"))
        self.repository_root = _strict_directory(Path(__file__).parents[3])
        _require_files(self.generator_directory, GENERATOR_FILES)
        _require_files(self.codec_directory, CODEC_FILES)
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise ValueError("native VoiceGenerator backend requires macOS arm64")
        self._model_file_identities = _model_file_identities(
            (self.generator_directory, GENERATOR_FILES),
            (self.codec_directory, CODEC_FILES),
        )

    def readiness(self) -> bool:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            return False
        try:
            if (
                _runtime_executable_identity(self.runtime_python)
                != self._runtime_python_identity
            ):
                return False
            current = _model_file_identities(
                (self.generator_directory, GENERATOR_FILES),
                (self.codec_directory, CODEC_FILES),
            )
        except (OSError, ValueError):
            return False
        return current == self._model_file_identities

    def generate(
        self,
        request: VoiceGeneratorHostRequest,
        run_directory: Path,
        cancel_event: threading.Event,
    ) -> BackendGenerationResult:
        run_directory = _strict_directory(run_directory)
        if run_directory.name != str(request.request_id):
            raise HostProtocolError("RUN_DIRECTORY_INVALID", 500)
        _require_files(self.generator_directory, GENERATOR_FILES)
        _require_files(self.codec_directory, CODEC_FILES)
        try:
            baseline = _sample()
        except Exception as error:
            raise HostProtocolError(
                "MEMORY_MEASUREMENT_UNAVAILABLE",
                503,
                request_id=request.request_id,
                retryable=True,
            ) from error
        if baseline.pressure in {"critical", "unknown"}:
            raise HostProtocolError(
                "MEMORY_BASELINE_CRITICAL", 503, request_id=request.request_id, retryable=True
            )
        started_at = _now()
        samples = [baseline]
        self._run_stage(
            stage="generator",
            model_directory=self.generator_directory,
            run_directory=run_directory,
            timeout_seconds=GENERATOR_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
            samples=samples,
            request_id=request.request_id,
        )
        if cancel_event.is_set():
            raise HostProtocolError("USER_CANCELLED", 409, request_id=request.request_id)
        generator = _read_json(run_directory / "generator-result.json")
        _validate_generator_result(generator, request)
        if not _wait_for_recovery(samples, cancel_event):
            raise HostProtocolError(
                "MEMORY_RECOVERY_FAILED", 503, request_id=request.request_id, retryable=True
            )
        _require_files(self.codec_directory, CODEC_FILES)
        self._run_stage(
            stage="codec",
            model_directory=self.codec_directory,
            run_directory=run_directory,
            timeout_seconds=CODEC_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
            samples=samples,
            request_id=request.request_id,
        )
        if cancel_event.is_set():
            raise HostProtocolError("USER_CANCELLED", 409, request_id=request.request_id)
        codec = _read_json(run_directory / "codec-result.json")
        _validate_codec_result(codec, request, generator)
        recovered = _wait_for_recovery(samples, cancel_event)
        if not recovered:
            raise HostProtocolError(
                "MEMORY_RECOVERY_FAILED", 503, request_id=request.request_id, retryable=True
            )
        audio_path = run_directory / ".backend-audio.wav"
        payload = _read_file(audio_path, 4 * 1024 * 1024)
        metrics = inspect_generated_wav(payload)
        if (
            codec.get("audio_sha256") != hashlib.sha256(payload).hexdigest()
            or codec.get("audio_size_bytes") != len(payload)
            or codec.get("audio_metrics") != dict(metrics.public_payload())
        ):
            raise HostProtocolError(
                "AUDIO_EVIDENCE_MISMATCH", 500, request_id=request.request_id
            )
        completed_at = _now()
        return BackendGenerationResult(
            request_id=request.request_id,
            request_digest=request.request_digest,
            token_sha256=str(generator["token_sha256"]),
            audio_bytes=payload,
            audio_sha256=hashlib.sha256(payload).hexdigest(),
            memory_summary=_memory_summary(samples, recovered=recovered),
            started_at=started_at,
            completed_at=completed_at,
        )

    def _run_stage(
        self,
        *,
        stage: str,
        model_directory: Path,
        run_directory: Path,
        timeout_seconds: float,
        cancel_event: threading.Event,
        samples: list[_Snapshot],
        request_id: UUID,
    ) -> None:
        if (
            _runtime_executable_identity(self.runtime_python)
            != self._runtime_python_identity
        ):
            raise HostProtocolError(
                "RUNTIME_PYTHON_IDENTITY_CHANGED",
                503,
                request_id=request_id,
                retryable=False,
            )
        command = (
            str(self.runtime_python),
            "-m",
            "scripts.tts.voice_generator.native_worker",
            stage,
            "--run-directory",
            str(run_directory),
            "--model-directory",
            str(model_directory),
            "--host-pid",
            str(os.getpid()),
        )
        cache_root = run_directory / ".runtime-cache"
        cache_root.mkdir(mode=0o700, exist_ok=True)
        process = subprocess.Popen(
            command,
            cwd=self.repository_root,
            env=_child_environment(cache_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_seconds
        critical_started: float | None = None
        stop_code: str | None = None
        try:
            while process.poll() is None:
                now = time.monotonic()
                if cancel_event.is_set():
                    stop_code = "USER_CANCELLED"
                    break
                if now >= deadline:
                    stop_code = "RUNTIME_TIMEOUT"
                    break
                snapshot = _sample()
                samples.append(snapshot)
                if snapshot.pressure == "critical":
                    critical_started = critical_started or now
                    if now - critical_started >= CRITICAL_GRACE_SECONDS:
                        stop_code = "MEMORY_PRESSURE_CRITICAL"
                        break
                elif snapshot.pressure == "unknown":
                    stop_code = "MEMORY_MEASUREMENT_UNAVAILABLE"
                    break
                else:
                    critical_started = None
                time.sleep(1.0)
            if stop_code is not None:
                _terminate_group(process)
                raise HostProtocolError(
                    stop_code,
                    503 if stop_code != "USER_CANCELLED" else 409,
                    request_id=request_id,
                    retryable=stop_code != "USER_CANCELLED",
                )
            return_code = process.wait(timeout=1)
            if return_code != 0:
                result_name = "generator-result.json" if stage == "generator" else "codec-result.json"
                failure = _read_json_optional(run_directory / result_name)
                code = failure.get("failure_code") if failure else None
                raise HostProtocolError(
                    str(code) if isinstance(code, str) and code.isupper() else "WORKER_FAILED",
                    500,
                    request_id=request_id,
                    retryable=True,
                )
        finally:
            if process.poll() is None:
                _terminate_group(process)


def _sample() -> _Snapshot:
    available, pageouts = _vm_stat()
    swap = _swap_used()
    try:
        raw_pressure = subprocess.run(
            ("/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
        ).stdout.strip()
        pressure = {"1": "normal", "2": "warning", "4": "critical"}.get(
            raw_pressure, "unknown"
        )
    except (OSError, subprocess.SubprocessError):
        pressure = "unknown"
    return _Snapshot(available, swap, pageouts, pressure, time.monotonic())


def _vm_stat() -> tuple[int, int]:
    output = subprocess.run(
        ("/usr/bin/vm_stat",),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
    ).stdout
    first, *lines = output.splitlines()
    match = re.search(r"page size of ([0-9]+) bytes", first)
    if match is None:
        raise RuntimeError("vm_stat page size missing")
    page_size = int(match.group(1))
    values: dict[str, int] = {}
    for line in lines:
        parsed = _VM_LINE.match(line.strip())
        if parsed:
            values[parsed.group(1)] = int(parsed.group(2))
    required = ("Pages free", "Pages inactive", "Pageouts")
    if any(name not in values for name in required):
        raise RuntimeError("vm_stat counters missing")
    pages = values["Pages free"] + values["Pages inactive"] + values.get("Pages speculative", 0)
    return pages * page_size, values["Pageouts"]


def _swap_used() -> int:
    output = subprocess.run(
        ("/usr/sbin/sysctl", "-n", "vm.swapusage"),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
    ).stdout
    match = _SWAP_VALUE.search(output)
    if match is None:
        raise RuntimeError("swap usage missing")
    multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}[match.group(2).upper()]
    return int(float(match.group(1)) * multiplier)


def _wait_for_recovery(
    samples: list[_Snapshot],
    cancel_event: threading.Event,
) -> bool:
    deadline = time.monotonic() + RECOVERY_TIMEOUT_SECONDS
    critical_started: float | None = None
    while True:
        if cancel_event.is_set():
            return False
        snapshot = _sample()
        samples.append(snapshot)
        now = time.monotonic()
        if snapshot.pressure == "unknown":
            return False
        if snapshot.pressure == "critical":
            critical_started = critical_started or now
            if now - critical_started >= CRITICAL_GRACE_SECONDS:
                return False
        else:
            critical_started = None
        if now >= deadline:
            return True
        time.sleep(min(2.0, max(0.0, deadline - now)))


def _memory_summary(samples: list[_Snapshot], *, recovered: bool) -> dict[str, int | bool]:
    minimum = min(item.available_bytes for item in samples)
    initial_swap = samples[0].swap_used_bytes
    maximum_swap = max(max(0, item.swap_used_bytes - initial_swap) for item in samples)
    maximum_pageout_rate = 0
    critical_ms = 0
    for before, after in zip(samples, samples[1:]):
        elapsed = max(after.observed_monotonic - before.observed_monotonic, 0.001)
        maximum_pageout_rate = max(
            maximum_pageout_rate,
            round(max(0, after.pageouts - before.pageouts) / elapsed),
        )
        if before.pressure == "critical":
            critical_ms += round(elapsed * 1_000)
    return {
        "minimum_available_memory_bytes": minimum,
        "maximum_swap_delta_bytes": maximum_swap,
        "maximum_pageouts_per_second": maximum_pageout_rate,
        "critical_pressure_milliseconds": critical_ms,
        "stage_pid_overlap": False,
        "recovered_within_60_seconds": recovered,
    }


def _validate_generator_result(value: dict[str, object], request: VoiceGeneratorHostRequest) -> None:
    expected = {
        "schema_version",
        "passed",
        "request_id",
        "request_digest",
        "revision",
        "runtime_fingerprint",
        "adapter_schema",
        "token_schema",
        "token_sha256",
        "token_bytes",
        "token_shape",
        "observed_at",
    }
    if (
        set(value) != expected
        or value.get("schema_version") != "voice-generator-product-stage/1"
        or value.get("passed") is not True
        or value.get("request_id") != str(request.request_id)
        or value.get("request_digest") != request.request_digest
        or value.get("revision") != VOICE_GENERATOR_REVISION
        or value.get("runtime_fingerprint") != EXPECTED_RUNTIME_FINGERPRINT
        or value.get("adapter_schema") != GENERATION_ADAPTER_SCHEMA
        or not isinstance(value.get("token_sha256"), str)
    ):
        raise HostProtocolError("GENERATOR_EVIDENCE_MISMATCH", 500, request_id=request.request_id)


def _validate_codec_result(
    value: dict[str, object],
    request: VoiceGeneratorHostRequest,
    generator: dict[str, object],
) -> None:
    expected = {
        "schema_version",
        "passed",
        "request_id",
        "request_digest",
        "revision",
        "runtime_fingerprint",
        "adapter_schema",
        "token_sha256",
        "audio_sha256",
        "audio_size_bytes",
        "audio_metrics",
        "observed_at",
    }
    if (
        set(value) != expected
        or value.get("schema_version") != "voice-generator-product-codec/1"
        or value.get("passed") is not True
        or value.get("request_id") != str(request.request_id)
        or value.get("request_digest") != request.request_digest
        or value.get("revision") != CODEC_REVISION
        or value.get("runtime_fingerprint") != EXPECTED_RUNTIME_FINGERPRINT
        or value.get("adapter_schema") != CODEC_ADAPTER_SCHEMA
        or value.get("token_sha256") != generator.get("token_sha256")
    ):
        raise HostProtocolError("CODEC_EVIDENCE_MISMATCH", 500, request_id=request.request_id)


def _strict_file(path: Path, *, executable: bool = False) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError("native runtime file identity is invalid")
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or (executable and not os.access(path, os.X_OK)):
        raise ValueError("native runtime file is not executable")
    return path


def _strict_runtime_python(path: Path) -> Path:
    """Validate an owner-private venv entry while preserving venv discovery."""

    if not path.is_absolute() or not path.exists():
        raise ValueError("native runtime Python identity is invalid")
    parent = path.parent
    if parent.is_symlink() or parent.resolve(strict=True) != parent:
        raise ValueError("native runtime Python parent is invalid")
    parent_details = parent.stat()
    if (
        parent_details.st_uid != os.getuid()
        or stat.S_IMODE(parent_details.st_mode) & 0o022
    ):
        raise ValueError("native runtime Python parent is not private")
    target = path.resolve(strict=True)
    target_details = target.stat()
    if (
        not stat.S_ISREG(target_details.st_mode)
        or not os.access(path, os.X_OK)
        or path.lstat().st_uid != os.getuid()
    ):
        raise ValueError("native runtime Python target is invalid")
    return path


def _runtime_executable_identity(path: Path) -> tuple[object, ...]:
    checked = _strict_runtime_python(path)
    link = checked.lstat()
    target_path = checked.resolve(strict=True)
    target = target_path.stat()
    return (
        str(checked),
        link.st_dev,
        link.st_ino,
        link.st_size,
        link.st_mtime_ns,
        str(target_path),
        target.st_dev,
        target.st_ino,
        target.st_size,
        target.st_mtime_ns,
    )


def _strict_directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError("native runtime directory identity is invalid")
    return path


def _require_files(root: Path, expected: dict[str, str]) -> None:
    for name, digest in expected.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or _file_sha256(path) != digest:
            raise ValueError("native model snapshot identity changed")


def _model_file_identities(
    *snapshots: tuple[Path, dict[str, str]],
) -> tuple[tuple[str, int, int, int, int, int, int], ...]:
    identities: list[tuple[str, int, int, int, int, int, int]] = []
    for root, expected in snapshots:
        for name in sorted(expected):
            file_name = root / name
            if file_name.is_symlink() or not file_name.is_file():
                raise ValueError("native model snapshot identity changed")
            details = file_name.stat()
            identities.append(
                (
                    str(file_name),
                    details.st_dev,
                    details.st_ino,
                    details.st_size,
                    details.st_mtime_ns,
                    stat.S_IMODE(details.st_mode),
                    details.st_uid,
                )
            )
    return tuple(identities)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _child_environment(cache_root: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LC_ALL": "C",
        "LANG": "C",
        "HF_HOME": str(cache_root),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTORCH_ENABLE_MPS_FALLBACK": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONHASHSEED": "0",
    }


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def _read_json(path: Path) -> dict[str, object]:
    payload = _read_file(path, 64 * 1024)
    value = json.loads(payload.decode("utf-8"))
    if type(value) is not dict:
        raise RuntimeError("worker result shape is invalid")
    return value


def _read_json_optional(path: Path) -> dict[str, object] | None:
    try:
        return _read_json(path)
    except (FileNotFoundError, ValueError, RuntimeError, json.JSONDecodeError):
        return None


def _read_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path.name)
    details = path.stat()
    if (
        not 1 <= details.st_size <= maximum
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise FileNotFoundError(path.name)
    payload = path.read_bytes()
    if len(payload) != details.st_size:
        raise RuntimeError("worker output changed while reading")
    return payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
