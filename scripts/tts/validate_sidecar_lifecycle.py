#!/usr/bin/env python3
"""Replay the T1-B Sidecar lifecycle without broad Docker cleanup.

The default mode is a read-only dry run.  ``fake`` exercises the frozen
control-token/worker-lease protocol through an in-process HTTP server.
``real`` is deliberately cumbersome: it
requires two exact confirmations, an externally coordinated LOCK-NANO file,
an isolated resource prefix, pinned model assets, and a frozen image digest.
Only resources carrying this invocation's label and exact names are removed.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Final, Iterator, Mapping, Sequence
from uuid import uuid4


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.narration.model_assets import (  # noqa: E402
    MODEL_INVENTORY_SHA256,
    MODEL_TREE_SHA256,
    ModelAssetError,
    SOURCE_TREE_SHA256,
    verify_release,
)
from backend.narration.runtime import (  # noqa: E402
    DockerComposeSidecarLifecycle,
    SidecarRuntimeError,
    read_secret_token,
)
from backend.narration.sidecar_server import (  # noqa: E402
    FakeBackend,
    LOCAL_SCOPE_FINGERPRINT,
    SidecarHTTPServer,
    SidecarState,
    _model_fingerprint_sha256,
    _validate_wav,
)


SCHEMA_VERSION: Final = "t1-b-sidecar-lifecycle-transcript/1.2"
PROTOCOL_VERSION: Final = "moss-tts-sidecar/1.1"
EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256: Final = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
EXPECTED_TEST_MODEL_FINGERPRINT_SHA256: Final = (
    "9846cd5d051a8dc124441d6704cd7db1d27f3db91c493b176c4d1a5643876ed3"
)
CONTROL_TOKEN_HEADER: Final = "X-MOSS-Sidecar-Token"
WORKER_TOKEN_HEADER: Final = "X-MOSS-Worker-Token"
VERSION_HEADER: Final = "X-MOSS-Protocol-Version"
LEASE_TTL_SECONDS: Final = 60
WORKER_TOKEN_CHARS: Final = 43
RUNNER_CONFIRMATION: Final = "RUN-T1-B-REAL-NANO"
KILL_CONFIRMATION: Final = "KILL-DEDICATED-T1-B-SIDECAR"
PREBUILT_CONFIRMATION: Final = "USE-FROZEN-T1-B-PREBUILT-IMAGE"
SOURCE_MODEL_VOLUME_CONFIRMATION: Final = (
    "USE-LABELED-READONLY-MOSS-MODEL-VOLUME"
)
RUN_LABEL: Final = "ai.novel.world.validation-run"
PROJECT_LABEL: Final = "ai.novel.world.project"
PROJECT_LABEL_VALUE: Final = "AI小说世界2026"
PURPOSE_LABEL: Final = "ai.novel.world.purpose"
PURPOSE_LABEL_VALUE: Final = "tts-model-and-source-assets"
INIT_TOKEN_PATH: Final = "/moss_tts_sidecar_token.input"
RESOURCE_PREFIX = re.compile(r"^ai-novel-2026-t1b-[a-z0-9]{8,24}$")
LOCK_GRANT = re.compile(r"^LOCK-NANO/[A-Za-z0-9][A-Za-z0-9._-]{7,95}$")
SOURCE_MODEL_VOLUME = re.compile(
    r"^ai-novel-2026-[a-z0-9]+(?:[.-][a-z0-9]+)*$"
)
SAFE_IMAGE = re.compile(
    r"^ai-novel-world/moss-tts-sidecar:(ai-novel-2026-t1b-[a-z0-9]{8,24})$"
)


class RunnerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RealNames:
    prefix: str
    run_id: str
    sidecar: str
    network: str
    smoke_client: str
    fault_client: str
    init_client: str
    secret_volume: str
    model_volume: str


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _runner_sha256() -> str:
    return _sha256(Path(__file__).read_bytes())


def _base_transcript(mode: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "T1-B",
        "mode": mode,
        "status": "running",
        "runner_sha256": _runner_sha256(),
        "protocol_version": PROTOCOL_VERSION,
        "expected_model_fingerprint_sha256": (
            EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
        ),
        "expected_test_model_fingerprint_sha256": (
            EXPECTED_TEST_MODEL_FINGERPRINT_SHA256
        ),
        "worker_lease_ttl_seconds": LEASE_TTL_SECONDS,
        "model_inventory_sha256": MODEL_INVENTORY_SHA256,
        "started_unix_ns": time.time_ns(),
        "steps": [],
        "secrets_recorded": False,
        "audio_bytes_recorded": False,
        "text_recorded": False,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    if not path.is_absolute():
        raise RunnerError("TRANSCRIPT_PATH_INVALID", "transcript path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RunnerError("TRANSCRIPT_PATH_INVALID", "transcript path cannot be a symlink")
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(payload) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _record_step(
    transcript: dict[str, object],
    *,
    name: str,
    status: str,
    duration_ms: float,
    evidence: Mapping[str, object] | None = None,
) -> None:
    steps = transcript["steps"]
    assert isinstance(steps, list)
    steps.append(
        {
            "name": name,
            "status": status,
            "duration_ms": round(duration_ms, 3),
            "evidence": dict(evidence or {}),
        }
    )


def _command(
    transcript: dict[str, object],
    name: str,
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            list(argv),
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _record_step(
            transcript,
            name=name,
            status="failed",
            duration_ms=(time.perf_counter() - started) * 1000,
            evidence={"error_code": "COMMAND_EXECUTION_FAILED"},
        )
        raise RunnerError("COMMAND_EXECUTION_FAILED", "managed command failed") from error
    evidence = {
        "exit_code": result.returncode,
        "stdout_sha256": _sha256(result.stdout.encode("utf-8")),
        "stderr_sha256": _sha256(result.stderr.encode("utf-8")),
    }
    _record_step(
        transcript,
        name=name,
        status="passed" if result.returncode == 0 else "failed",
        duration_ms=(time.perf_counter() - started) * 1000,
        evidence=evidence,
    )
    if check and result.returncode != 0:
        raise RunnerError("COMMAND_FAILED", f"managed command failed: {name}")
    return result


def _validate_real_arguments(args: argparse.Namespace) -> RealNames:
    if args.confirm_real_nano != RUNNER_CONFIRMATION:
        raise RunnerError(
            "REAL_CONFIRMATION_REQUIRED", "real mode requires the exact Nano confirmation"
        )
    if args.confirm_active_kill != KILL_CONFIRMATION:
        raise RunnerError(
            "ACTIVE_KILL_CONFIRMATION_REQUIRED",
            "real mode requires the exact dedicated-container kill confirmation",
        )
    if (
        args.image_mode == "prebuilt"
        and args.confirm_prebuilt_image != PREBUILT_CONFIRMATION
    ):
        raise RunnerError(
            "PREBUILT_IMAGE_CONFIRMATION_REQUIRED",
            "prebuilt mode requires the exact frozen-image confirmation",
        )
    if not isinstance(args.resource_prefix, str) or not RESOURCE_PREFIX.fullmatch(
        args.resource_prefix
    ):
        raise RunnerError(
            "RESOURCE_PREFIX_INVALID", "real mode requires a narrow T1-B resource prefix"
        )
    image_match = SAFE_IMAGE.fullmatch(args.image_ref or "")
    if image_match is None or image_match.group(1) != args.resource_prefix:
        raise RunnerError(
            "IMAGE_REF_INVALID", "real mode image tag must be owned by the exact prefix"
        )
    if args.expected_image_digest is None or re.fullmatch(
        r"sha256:[0-9a-f]{64}", args.expected_image_digest
    ) is None:
        raise RunnerError(
            "IMAGE_DIGEST_REQUIRED", "real mode requires a frozen image digest"
        )
    if not isinstance(args.lock_grant, str) or LOCK_GRANT.fullmatch(args.lock_grant) is None:
        raise RunnerError(
            "LOCK_GRANT_REQUIRED", "real mode requires an explicit LOCK-NANO grant ID"
        )
    for name in ("lock_file", "token_file"):
        path = getattr(args, name)
        if not isinstance(path, Path) or not path.is_absolute():
            raise RunnerError(
                f"{name.upper()}_INVALID", f"real mode {name} must be absolute"
            )
        if "," in os.fspath(path):
            raise RunnerError(
                f"{name.upper()}_INVALID",
                f"real mode {name} cannot contain a Docker mount delimiter",
            )
    has_host_assets = args.assets_root is not None
    has_source_volume = args.source_model_volume is not None
    if has_host_assets == has_source_volume:
        raise RunnerError(
            "MODEL_INPUT_EXACTLY_ONE_REQUIRED",
            "real mode requires exactly one model input",
        )
    runner_owned_volumes = {
        f"{args.resource_prefix}-model",
        f"{args.resource_prefix}-secret",
    }
    if has_host_assets:
        if args.confirm_source_model_volume is not None:
            raise RunnerError(
                "SOURCE_MODEL_VOLUME_CONFIRMATION_UNEXPECTED",
                "host-assets mode rejects the source-volume confirmation",
            )
        assets_root = args.assets_root
        if not isinstance(assets_root, Path) or not assets_root.is_absolute():
            raise RunnerError(
                "ASSETS_ROOT_INVALID", "real mode assets_root must be absolute"
            )
        if "," in os.fspath(assets_root):
            raise RunnerError(
                "ASSETS_ROOT_INVALID",
                "real mode assets_root cannot contain a Docker mount delimiter",
            )
    else:
        source_volume = args.source_model_volume
        if (
            not isinstance(source_volume, str)
            or len(source_volume) > 64
            or SOURCE_MODEL_VOLUME.fullmatch(source_volume) is None
        ):
            raise RunnerError(
                "SOURCE_MODEL_VOLUME_INVALID",
                "source model volume name violates the narrow project policy",
            )
        if source_volume in runner_owned_volumes:
            raise RunnerError(
                "SOURCE_MODEL_VOLUME_COLLISION",
                "source model volume cannot equal a runner-owned target volume",
            )
        if args.confirm_source_model_volume != SOURCE_MODEL_VOLUME_CONFIRMATION:
            raise RunnerError(
                "SOURCE_MODEL_VOLUME_CONFIRMATION_REQUIRED",
                "source-volume mode requires the exact read-only confirmation",
            )
    run_id = uuid4().hex
    return RealNames(
        prefix=args.resource_prefix,
        run_id=run_id,
        sidecar=f"{args.resource_prefix}-sidecar",
        network=f"{args.resource_prefix}-net",
        smoke_client=f"{args.resource_prefix}-smoke",
        fault_client=f"{args.resource_prefix}-fault",
        init_client=f"{args.resource_prefix}-init",
        secret_volume=f"{args.resource_prefix}-secret",
        model_volume=f"{args.resource_prefix}-model",
    )


@contextmanager
def _lock_nano(path: Path) -> Iterator[None]:
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise RunnerError("LOCK_POLICY_UNAVAILABLE", "O_NOFOLLOW is required")
        descriptor = os.open(path, os.O_RDWR | os.O_CLOEXEC | nofollow)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise RunnerError("LOCK_FILE_INVALID", "LOCK-NANO file is not private")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError("LOCK_NANO_BUSY", "LOCK-NANO is held by another runner") from error
        yield
    except OSError as error:
        raise RunnerError("LOCK_FILE_INVALID", "LOCK-NANO file cannot be opened") from error
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _fake_http_call(
    port: int,
    method: str,
    path: str,
    *,
    control_token: str | None = None,
    worker_token: str | None = None,
    body: Mapping[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    if (control_token is None) == (worker_token is None):
        raise RunnerError(
            "FAKE_AUTH_HEADER_INVALID",
            "fake client must send exactly one authentication header",
        )
    payload = None if body is None else _canonical_bytes(body)
    headers = {VERSION_HEADER: PROTOCOL_VERSION}
    if control_token is not None:
        headers[CONTROL_TOKEN_HEADER] = control_token
    else:
        assert worker_token is not None
        headers[WORKER_TOKEN_HEADER] = worker_token
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(payload))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        response_payload = response.read()
        return response.status, dict(response.getheaders()), response_payload
    finally:
        connection.close()


def _fake_json(
    result: tuple[int, dict[str, str], bytes],
    *,
    expected_status: int,
    expected_keys: frozenset[str],
) -> tuple[dict[str, str], dict[str, object]]:
    status, headers, payload = result
    try:
        row = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunnerError("FAKE_RESPONSE_INVALID", "fake response is not JSON") from error
    if (
        status != expected_status
        or headers.get(VERSION_HEADER) != PROTOCOL_VERSION
        or not isinstance(row, dict)
        or frozenset(row) != expected_keys
        or row.get("protocol_version") != PROTOCOL_VERSION
    ):
        raise RunnerError(
            "FAKE_RESPONSE_MISMATCH", "fake response differs from the frozen wire shape"
        )
    return headers, row


def _run_fake(transcript: dict[str, object]) -> None:
    started = time.perf_counter()
    control_token = "x" * 32
    first = SidecarState(control_token, FakeBackend(step_delay_seconds=0.05))
    server = SidecarHTTPServer(("127.0.0.1", 0), first)
    server_thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        name="t1-b-fake-sidecar",
        daemon=True,
    )
    server_thread.start()
    port = int(server.server_address[1])
    worker_token: str | None = None
    released = False
    payload = b""
    digest = ""
    sample_rate = channels = sample_width = 0
    lease_generation = 0
    final_health: dict[str, object] | None = None
    try:
        _, before = _fake_json(
            _fake_http_call(
                port,
                "GET",
                "/v1/health",
                control_token=control_token,
            ),
            expected_status=200,
            expected_keys=frozenset(
                {
                    "protocol_version",
                    "status",
                    "ready",
                    "capabilities_sha256",
                    "model_fingerprint",
                    "model_fingerprint_sha256",
                    "worker",
                    "lease",
                }
            ),
        )
        before_lease = before.get("lease")
        if (
            before.get("status") != "unloaded"
            or before.get("ready") is not False
            or before.get("model_fingerprint") is not None
            or before.get("model_fingerprint_sha256") is not None
            or not isinstance(before_lease, dict)
            or frozenset(before_lease) != {"active", "generation"}
            or before_lease.get("active") is not False
            or not isinstance(before_lease.get("generation"), int)
            or isinstance(before_lease.get("generation"), bool)
            or before_lease.get("generation") != 0
        ):
            raise RunnerError(
                "FAKE_PRELEASE_STATE_INVALID",
                "fake Sidecar did not begin unloaded",
            )

        acquire_id = str(uuid4())
        _, acquired = _fake_json(
            _fake_http_call(
                port,
                "POST",
                "/v1/lease/acquire",
                control_token=control_token,
                body={"request_id": acquire_id},
            ),
            expected_status=200,
            expected_keys=frozenset(
                {
                    "protocol_version",
                    "request_id",
                    "status",
                    "worker_token",
                    "lease_ttl_seconds",
                    "lease_generation",
                    "worker",
                }
            ),
        )
        candidate_token = acquired.get("worker_token")
        if (
            acquired.get("request_id") != acquire_id
            or acquired.get("status") != "active"
            or acquired.get("lease_ttl_seconds") != LEASE_TTL_SECONDS
            or not isinstance(acquired.get("lease_generation"), int)
            or isinstance(acquired.get("lease_generation"), bool)
            or int(acquired["lease_generation"]) < 1
            or not isinstance(candidate_token, str)
            or len(candidate_token) != WORKER_TOKEN_CHARS
            or re.fullmatch(r"[A-Za-z0-9_-]+", candidate_token) is None
            or candidate_token == control_token
        ):
            raise RunnerError(
                "FAKE_LEASE_ACQUIRE_INVALID",
                "fake acquire response violates the worker lease contract",
            )
        worker_token = candidate_token
        lease_generation = int(acquired["lease_generation"])

        warmup_id = str(uuid4())
        _, warmed = _fake_json(
            _fake_http_call(
                port,
                "POST",
                "/v1/warmup",
                worker_token=worker_token,
                body={"request_id": warmup_id},
            ),
            expected_status=200,
            expected_keys=frozenset(
                {
                    "protocol_version",
                    "request_id",
                    "status",
                    "ready",
                    "capabilities_sha256",
                    "model_fingerprint",
                    "model_fingerprint_sha256",
                    "worker",
                    "lease",
                }
            ),
        )
        fingerprint = warmed.get("model_fingerprint")
        warmed_lease = warmed.get("lease")
        if not isinstance(fingerprint, dict):
            raise RunnerError(
                "FAKE_WARMUP_FAILED", "fake warmup did not publish model identity"
            )
        digest = _model_fingerprint_sha256(fingerprint)
        if (
            warmed.get("request_id") != warmup_id
            or warmed.get("status") != "ready"
            or warmed.get("ready") is not True
            or warmed.get("model_fingerprint_sha256") != digest
            or digest != EXPECTED_TEST_MODEL_FINGERPRINT_SHA256
            or not isinstance(warmed_lease, dict)
            or frozenset(warmed_lease) != {"active", "generation"}
            or warmed_lease.get("active") is not True
            or warmed_lease.get("generation") != lease_generation
        ):
            raise RunnerError(
                "FAKE_MODEL_FINGERPRINT_MISMATCH",
                "fake model fingerprint differs from the frozen identity",
            )

        synth_id = str(uuid4())
        synth_result: dict[str, tuple[int, dict[str, str], bytes]] = {}

        def synthesize() -> None:
            assert worker_token is not None
            synth_result["result"] = _fake_http_call(
                port,
                "POST",
                "/v1/synthesize",
                worker_token=worker_token,
                body={
                    "request_id": synth_id,
                    "scope_fingerprint": LOCAL_SCOPE_FINGERPRINT,
                    "requested_model_fingerprint_sha256": digest,
                    "text": "T1-B 固定 fake 生命周期验证句。",
                    "voice": "narrator_neutral",
                    "seed": 42,
                    "sample_mode": "fixed",
                    "max_new_frames": 64,
                },
            )

        synth_thread = threading.Thread(target=synthesize, name="t1-b-fake-synthesis")
        synth_thread.start()
        active_observed = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, health = _fake_json(
                _fake_http_call(
                    port,
                    "GET",
                    "/v1/health",
                    worker_token=worker_token,
                ),
                expected_status=200,
                expected_keys=frozenset(
                    {
                        "protocol_version",
                        "status",
                        "ready",
                        "capabilities_sha256",
                        "model_fingerprint",
                        "model_fingerprint_sha256",
                        "worker",
                        "lease",
                    }
                ),
            )
            health_worker = health.get("worker")
            health_lease = health.get("lease")
            if (
                isinstance(health_worker, dict)
                and health_worker.get("active_request_count") == 1
                and isinstance(health_lease, dict)
                and health_lease.get("active") is True
                and isinstance(health_lease.get("generation"), int)
                and not isinstance(health_lease.get("generation"), bool)
                and health_lease.get("generation") == lease_generation
            ):
                active_observed = True
                break
            time.sleep(0.01)
        if not active_observed:
            raise RunnerError(
                "FAKE_ACTIVE_REQUEST_NOT_OBSERVED",
                "fake synthesis did not stay active for lease renewal",
            )

        renew_id = str(uuid4())
        _, renewed = _fake_json(
            _fake_http_call(
                port,
                "POST",
                "/v1/lease/renew",
                worker_token=worker_token,
                body={"request_id": renew_id},
            ),
            expected_status=200,
            expected_keys=frozenset(
                {
                    "protocol_version",
                    "request_id",
                    "status",
                    "lease_ttl_seconds",
                    "lease_generation",
                    "worker",
                }
            ),
        )
        if (
            renewed.get("request_id") != renew_id
            or renewed.get("status") != "renewed"
            or renewed.get("lease_ttl_seconds") != LEASE_TTL_SECONDS
            or renewed.get("lease_generation") != lease_generation
        ):
            raise RunnerError(
                "FAKE_LEASE_RENEW_INVALID",
                "fake renewal response violates the worker lease contract",
            )
        synth_thread.join(5)
        if synth_thread.is_alive() or "result" not in synth_result:
            raise RunnerError(
                "FAKE_SYNTHESIS_TIMEOUT", "fake synthesis did not finish"
            )
        status, headers, payload = synth_result["result"]
        if (
            status != 200
            or headers.get(VERSION_HEADER) != PROTOCOL_VERSION
            or headers.get("X-MOSS-Request-ID") != synth_id
            or headers.get("X-MOSS-Actual-Model-Fingerprint-SHA256") != digest
            or headers.get("X-MOSS-Audio-SHA256") != _sha256(payload)
        ):
            raise RunnerError(
                "FAKE_SYNTHESIS_INVALID", "fake synthesis response is invalid"
            )
        sample_rate, channels, sample_width = _validate_wav(payload)

        release_id = str(uuid4())
        _, release = _fake_json(
            _fake_http_call(
                port,
                "POST",
                "/v1/lease/release",
                worker_token=worker_token,
                body={"request_id": release_id},
            ),
            expected_status=202,
            expected_keys=frozenset(
                {
                    "protocol_version",
                    "request_id",
                    "status",
                    "lease_generation",
                    "worker",
                }
            ),
        )
        released = True
        if (
            release.get("request_id") != release_id
            or release.get("status") != "release_requested"
            or release.get("lease_generation") != lease_generation
        ):
            raise RunnerError(
                "FAKE_LEASE_RELEASE_INVALID",
                "fake release response violates the worker lease contract",
            )

        _, stale = _fake_json(
            _fake_http_call(
                port,
                "GET",
                "/v1/health",
                worker_token=worker_token,
            ),
            expected_status=401,
            expected_keys=frozenset({"protocol_version", "request_id", "error"}),
        )
        stale_error = stale.get("error")
        if not isinstance(stale_error, dict) or stale_error.get("code") != "WORKER_LEASE_INVALID":
            raise RunnerError(
                "FAKE_STALE_WORKER_ACCEPTED",
                "released fake worker token was not rejected",
            )

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, health = _fake_json(
                _fake_http_call(
                    port,
                    "GET",
                    "/v1/health",
                    control_token=control_token,
                ),
                expected_status=200,
                expected_keys=frozenset(
                    {
                        "protocol_version",
                        "status",
                        "ready",
                        "capabilities_sha256",
                        "model_fingerprint",
                        "model_fingerprint_sha256",
                        "worker",
                        "lease",
                    }
                ),
            )
            health_worker = health.get("worker")
            health_lease = health.get("lease")
            if (
                health.get("status") == "unloaded"
                and health.get("ready") is False
                and health.get("model_fingerprint") is None
                and health.get("model_fingerprint_sha256") is None
                and isinstance(health_worker, dict)
                and health_worker.get("active_request_count") == 0
                and isinstance(health_lease, dict)
                and health_lease.get("active") is False
                and isinstance(health_lease.get("generation"), int)
                and not isinstance(health_lease.get("generation"), bool)
                and health_lease.get("generation") == lease_generation
            ):
                final_health = health
                break
            time.sleep(0.01)
        if final_health is None:
            raise RunnerError(
                "FAKE_UNLOAD_TIMEOUT", "fake Sidecar did not return to unloaded"
            )
    finally:
        if worker_token is not None and not released:
            try:
                _fake_http_call(
                    port,
                    "POST",
                    "/v1/lease/release",
                    worker_token=worker_token,
                    body={"request_id": str(uuid4())},
                )
            except (OSError, RunnerError):
                pass
        server.shutdown()
        server.server_close()
        server_thread.join(5)

    second = SidecarState("y" * 32, FakeBackend())
    if second.generation == first.generation:
        raise RunnerError("FAKE_GENERATION_REUSED", "fake restart reused a generation")
    _record_step(
        transcript,
        name="fake_worker_lease_protocol_and_restart",
        status="passed",
        duration_ms=(time.perf_counter() - started) * 1000,
        evidence={
            "test_backend": True,
            "model_fingerprint_sha256": digest,
            "audio_sha256": _sha256(payload),
            "audio_bytes": len(payload),
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "lease_ttl_seconds": LEASE_TTL_SECONDS,
            "lease_generation": lease_generation,
            "renewal_count": 1,
            "worker_token_recorded": False,
            "stale_worker_token_rejected": True,
            "final_status": "unloaded",
            "generation_changed": True,
        },
    )
    transcript["status"] = "fake_pass"


SMOKE_CLIENT_SCRIPT: Final = r'''
import hashlib, http.client, io, json, re, threading, time, uuid, wave
PROTO = "moss-tts-sidecar/1.1"
CONTROL_HEADER = "X-MOSS-Sidecar-Token"
WORKER_HEADER = "X-MOSS-Worker-Token"
TTL = 60
HEALTH_KEYS = {"protocol_version", "status", "ready", "capabilities_sha256", "model_fingerprint", "model_fingerprint_sha256", "worker", "lease"}
LEASE_WORKER_KEYS = {"pid", "generation", "test_backend"}
TOKEN_PATH = "/run/secrets/moss_tts_sidecar_token"
with open(TOKEN_PATH, "r", encoding="ascii", newline="") as stream:
    CONTROL_TOKEN = stream.read()
def call(method, path, body=None, content_type=None, *, control_token=None, worker_token=None, timeout=600):
    assert (control_token is None) != (worker_token is None)
    connection = http.client.HTTPConnection("tts-sidecar", 8765, timeout=timeout)
    headers = {"X-MOSS-Protocol-Version": PROTO}
    headers[CONTROL_HEADER if control_token is not None else WORKER_HEADER] = control_token if control_token is not None else worker_token
    if body is not None:
        headers["Content-Length"] = str(len(body)); headers["Content-Type"] = content_type
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse(); payload = response.read()
    row = (response.status, dict(response.getheaders()), payload)
    connection.close(); return row
def jbody(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
def checked_json(result, status, keys, request_id=None):
    observed, headers, payload = result
    assert observed == status and headers.get("X-MOSS-Protocol-Version") == PROTO
    row = json.loads(payload.decode()); assert set(row) == keys and row["protocol_version"] == PROTO
    if request_id is not None:
        assert row["request_id"] == request_id and headers["X-MOSS-Request-ID"] == request_id
    return headers, row
def checked_lease_worker(row):
    worker = row["worker"]
    assert set(worker) == LEASE_WORKER_KEYS
    assert isinstance(worker["pid"], int) and isinstance(worker["generation"], int) and isinstance(worker["test_backend"], bool)
    return worker
bad = ("A" if CONTROL_TOKEN[:1] != "A" else "B") + CONTROL_TOKEN[1:]
auth_status, _, _ = call("GET", "/v1/health", control_token=bad)
assert auth_status == 401
_, before = checked_json(call("GET", "/v1/health", control_token=CONTROL_TOKEN), 200, HEALTH_KEYS)
assert before["status"] == "unloaded" and before["ready"] is False
assert before["model_fingerprint"] is None and before["model_fingerprint_sha256"] is None
assert set(before["lease"]) == {"active", "generation"} and before["lease"]["active"] is False and before["lease"]["generation"] == 0
acquire_id = str(uuid.uuid4())
headers, acquired = checked_json(
    call("POST", "/v1/lease/acquire", jbody({"request_id":acquire_id}), "application/json", control_token=CONTROL_TOKEN),
    200,
    {"protocol_version", "request_id", "status", "worker_token", "lease_ttl_seconds", "lease_generation", "worker"},
    acquire_id,
)
lease_worker = checked_lease_worker(acquired)
WORKER_TOKEN = acquired["worker_token"]
assert acquired["status"] == "active" and acquired["lease_ttl_seconds"] == TTL
assert isinstance(acquired["lease_generation"], int) and not isinstance(acquired["lease_generation"], bool) and acquired["lease_generation"] > 0
assert isinstance(WORKER_TOKEN, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", WORKER_TOKEN) and WORKER_TOKEN != CONTROL_TOKEN
lease_generation = acquired["lease_generation"]; generation = lease_worker["generation"]
assert headers["X-MOSS-Worker-Generation"] == str(generation)
renew_stop = threading.Event(); renew_ready = threading.Event(); renew_count = [0]; renew_errors = []
def renew_once():
    request_id = str(uuid.uuid4())
    _, row = checked_json(
        call("POST", "/v1/lease/renew", jbody({"request_id":request_id}), "application/json", worker_token=WORKER_TOKEN, timeout=30),
        200,
        {"protocol_version", "request_id", "status", "lease_ttl_seconds", "lease_generation", "worker"},
        request_id,
    )
    worker = checked_lease_worker(row)
    assert row["status"] == "renewed" and row["lease_ttl_seconds"] == TTL and row["lease_generation"] == lease_generation
    assert worker["generation"] == generation
    renew_count[0] += 1
def renew_loop():
    try:
        renew_once(); renew_ready.set()
        while not renew_stop.wait(TTL / 3): renew_once()
    except BaseException as error:
        renew_errors.append(type(error).__name__); renew_ready.set()
renewer = threading.Thread(target=renew_loop, name="t1-b-worker-lease-renewer", daemon=True)
renewer.start(); assert renew_ready.wait(30) and not renew_errors and renew_count[0] >= 1
released = False
try:
    warm_id = str(uuid.uuid4())
    headers, warmed = checked_json(call("POST", "/v1/warmup", jbody({"request_id": warm_id}), "application/json", worker_token=WORKER_TOKEN), 200, {"protocol_version", "request_id", "status", "ready", "capabilities_sha256", "model_fingerprint", "model_fingerprint_sha256", "worker", "lease"}, warm_id)
    assert warmed["ready"] is True and warmed["status"] == "ready"
    assert set(warmed["lease"]) == {"active", "generation"} and warmed["lease"]["active"] is True and warmed["lease"]["generation"] == lease_generation
    assert headers["X-MOSS-Worker-Generation"] == str(generation)
    model = warmed["model_fingerprint_sha256"]
    assert headers["X-MOSS-Actual-Model-Fingerprint-SHA256"] == model
    def metadata(request_id, text, frames=64, reference=None):
        row = {"request_id": request_id, "scope_fingerprint": "8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095", "requested_model_fingerprint_sha256": model, "text": text, "voice": "Junhao", "seed": 42, "sample_mode": "fixed", "max_new_frames": frames}
        if reference is not None: row["reference_audio"] = {"content_type": "audio/wav", "actual_sha256": hashlib.sha256(reference).hexdigest(), "size_bytes": len(reference)}
        return row
    def validate_audio(result, request_id):
        status, headers, payload = result
        assert status == 200 and headers["X-MOSS-Protocol-Version"] == PROTO and headers["X-MOSS-Request-ID"] == request_id
        assert headers["X-MOSS-Worker-Generation"] == str(generation)
        assert headers["X-MOSS-Actual-Model-Fingerprint-SHA256"] == model
        digest = hashlib.sha256(payload).hexdigest(); assert headers["X-MOSS-Audio-SHA256"] == digest
        assert payload[:4] == b"RIFF" and int.from_bytes(payload[4:8], "little") == len(payload) - 8
        with wave.open(io.BytesIO(payload), "rb") as stream:
            frames = stream.getnframes(); decoded = stream.readframes(frames); extra = stream.readframes(1)
            assert (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) == (48000, 2, 2)
            assert len(decoded) == frames * 4 and not extra
        return payload, digest, frames
    ordinary_id = str(uuid.uuid4())
    ordinary, ordinary_hash, ordinary_frames = validate_audio(call("POST", "/v1/synthesize", jbody(metadata(ordinary_id, "T1-B 固定普通合成验证句。")), "application/json", worker_token=WORKER_TOKEN), ordinary_id)
    reference_id = str(uuid.uuid4()); boundary = "moss_" + uuid.uuid4().hex
    meta = jbody(metadata(reference_id, "T1-B 固定参考合成验证句。", reference=ordinary)); marker = ("--" + boundary).encode()
    multipart = b"\r\n".join([marker, b'Content-Disposition: form-data; name="metadata"', b"Content-Type: application/json", b"", meta, marker, b'Content-Disposition: form-data; name="reference_audio"', b"Content-Type: audio/wav", b"", ordinary, marker + b"--", b""])
    reference, reference_hash, reference_frames = validate_audio(call("POST", "/v1/synthesize", multipart, "multipart/form-data; boundary=" + boundary, worker_token=WORKER_TOKEN), reference_id)
    cancel_id = str(uuid.uuid4()); terminal = {}
    def long_call(): terminal["result"] = call("POST", "/v1/synthesize", jbody(metadata(cancel_id, "T1-B 固定取消验证句。" * 100, frames=2000)), "application/json", worker_token=WORKER_TOKEN)
    thread = threading.Thread(target=long_call); thread.start(); active = False
    for _ in range(300):
        _, health = checked_json(call("GET", "/v1/health", worker_token=WORKER_TOKEN), 200, HEALTH_KEYS)
        if health["worker"]["active_request_count"] == 1 and health["lease"]["active"] is True and health["lease"]["generation"] == lease_generation: active = True; break
        time.sleep(0.02)
    assert active
    _, cancelled = checked_json(call("POST", "/v1/cancel", jbody({"request_id": cancel_id}), "application/json", worker_token=WORKER_TOKEN), 200, {"protocol_version", "request_id", "disposition", "effective_at"}, cancel_id)
    assert cancelled["disposition"] == "requested" and cancelled["effective_at"] == "segment_boundary"
    thread.join(600); assert not thread.is_alive()
    terminal_status, terminal_headers, terminal_payload = terminal["result"]; terminal_row = json.loads(terminal_payload.decode())
    assert terminal_status == 409 and terminal_headers["X-MOSS-Protocol-Version"] == PROTO
    assert terminal_headers["X-MOSS-Request-ID"] == cancel_id and terminal_row["request_id"] == cancel_id
    assert terminal_row["error"]["code"] == "REQUEST_CANCELLED"
    renew_stop.set(); renewer.join(30); assert not renewer.is_alive() and not renew_errors and renew_count[0] >= 1
    release_id = str(uuid.uuid4())
    _, release = checked_json(
        call("POST", "/v1/lease/release", jbody({"request_id":release_id}), "application/json", worker_token=WORKER_TOKEN),
        202,
        {"protocol_version", "request_id", "status", "lease_generation", "worker"},
        release_id,
    )
    released = True; release_worker = checked_lease_worker(release)
    assert release["status"] == "release_requested" and release["lease_generation"] == lease_generation and release_worker["generation"] == generation
    stale_status, _, stale_payload = call("GET", "/v1/health", worker_token=WORKER_TOKEN)
    stale = json.loads(stale_payload.decode())
    assert stale_status == 401 and stale["protocol_version"] == PROTO and stale["error"]["code"] == "WORKER_LEASE_INVALID"
    final_health = None
    for _ in range(300):
        _, row = checked_json(call("GET", "/v1/health", control_token=CONTROL_TOKEN), 200, HEALTH_KEYS)
        if row["status"] == "unloaded" and row["ready"] is False and row["model_fingerprint"] is None and row["model_fingerprint_sha256"] is None and row["worker"]["active_request_count"] == 0 and row["lease"]["active"] is False and row["lease"]["generation"] == lease_generation:
            final_health = row; break
        time.sleep(0.02)
    assert final_health is not None
finally:
    renew_stop.set(); renewer.join(30)
    if not released:
        try:
            request_id = str(uuid.uuid4())
            call("POST", "/v1/lease/release", jbody({"request_id":request_id}), "application/json", worker_token=WORKER_TOKEN, timeout=30)
        except BaseException:
            pass
print(json.dumps({"status":"passed", "auth_negative_status":auth_status, "prewarm_ready":False, "generation":generation, "model_fingerprint_sha256":model, "lease":{"ttl_seconds":TTL,"lease_generation":lease_generation,"renewal_count":renew_count[0],"worker_token_recorded":False,"stale_worker_token_rejected":True,"final_status":"unloaded"}, "ordinary":{"bytes":len(ordinary),"sha256":ordinary_hash,"frames":ordinary_frames}, "reference":{"bytes":len(reference),"sha256":reference_hash,"frames":reference_frames}, "cancel":{"active_observed":active,"disposition":"requested","terminal_error_code":"REQUEST_CANCELLED"}}, sort_keys=True))
'''


FAULT_CLIENT_SCRIPT: Final = r'''
import http.client, json, threading, uuid
PROTO = "moss-tts-sidecar/1.1"; TTL = 60
with open("/run/secrets/moss_tts_sidecar_token", "r", encoding="ascii", newline="") as stream: control = stream.read()
def jbody(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
def call(path, body, *, control_token=None, worker_token=None, timeout=600):
    assert (control_token is None) != (worker_token is None)
    headers = {"X-MOSS-Protocol-Version":PROTO,"Content-Type":"application/json","Content-Length":str(len(body))}
    headers["X-MOSS-Sidecar-Token" if control_token is not None else "X-MOSS-Worker-Token"] = control_token if control_token is not None else worker_token
    connection = http.client.HTTPConnection("tts-sidecar", 8765, timeout=timeout)
    connection.request("POST", path, body=body, headers=headers)
    response = connection.getresponse(); payload = response.read(); row = (response.status, dict(response.getheaders()), payload)
    connection.close(); return row
acquire_id = str(uuid.uuid4())
status, headers, payload = call("/v1/lease/acquire", jbody({"request_id":acquire_id}), control_token=control, timeout=30)
acquired = json.loads(payload.decode()); assert status == 200 and acquired["request_id"] == acquire_id and acquired["status"] == "active" and acquired["lease_ttl_seconds"] == TTL
worker = acquired["worker_token"]; lease_generation = acquired["lease_generation"]
warm_id = str(uuid.uuid4())
status, headers, payload = call("/v1/warmup", jbody({"request_id":warm_id}), worker_token=worker)
warmed = json.loads(payload.decode()); assert status == 200 and warmed["ready"] is True and warmed["model_fingerprint_sha256"] == "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
stop = threading.Event(); renew_ready = threading.Event(); renew_errors = []
def renew_loop():
    try:
        while True:
            renew_id = str(uuid.uuid4())
            status, _, payload = call("/v1/lease/renew", jbody({"request_id":renew_id}), worker_token=worker, timeout=30)
            row = json.loads(payload.decode()); assert status == 200 and row["status"] == "renewed" and row["lease_ttl_seconds"] == TTL and row["lease_generation"] == lease_generation
            renew_ready.set()
            if stop.wait(TTL / 3): return
    except BaseException as error:
        renew_errors.append(type(error).__name__); renew_ready.set(); raise
renewer = threading.Thread(target=renew_loop, name="t1-b-fault-lease-renewer", daemon=True); renewer.start()
assert renew_ready.wait(30) and not renew_errors
request_id = str(uuid.uuid4())
body = jbody({"request_id":request_id,"scope_fingerprint":"8cd0df892dc4c7289e1182087e9ea8ec365c2d54d254d8aee5bd9252f5225095","requested_model_fingerprint_sha256":"3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d","text":"T1-B 固定活动故障验证句。"*200,"voice":"Junhao","seed":43,"sample_mode":"fixed","max_new_frames":2000})
try:
    response_status, _, response_payload = call("/v1/synthesize", body, worker_token=worker)
finally:
    stop.set(); renewer.join(30)
    try:
        release_id = str(uuid.uuid4()); call("/v1/lease/release", jbody({"request_id":release_id}), worker_token=worker, timeout=10)
    except BaseException:
        pass
print(json.dumps({"status":response_status,"bytes":len(response_payload)}, sort_keys=True))
'''


PROBE_CLIENT_SCRIPT: Final = r'''
import http.client, json
with open("/run/secrets/moss_tts_sidecar_token", "r", encoding="ascii", newline="") as stream: token = stream.read()
connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=5)
connection.request("GET", "/v1/health", headers={"X-MOSS-Protocol-Version":"moss-tts-sidecar/1.1","X-MOSS-Sidecar-Token":token})
response = connection.getresponse(); row = json.loads(response.read().decode()); connection.close()
assert response.status == 200 and row["protocol_version"] == "moss-tts-sidecar/1.1" and set(row["lease"]) == {"active", "generation"}
print(json.dumps({"status":response.status,"generation":row["worker"]["generation"],"active_request_count":row["worker"]["active_request_count"],"ready":row["ready"],"sidecar_status":row["status"],"lease_active":row["lease"]["active"],"lease_generation":row["lease"]["generation"]}, sort_keys=True))
'''


def _owned_absent(
    transcript: dict[str, object], kind: str, name: str, timeout: float
) -> None:
    result = _command(
        transcript,
        f"preflight_{kind}_absent",
        ["docker", kind, "inspect", name],
        timeout_seconds=timeout,
        check=False,
    )
    if result.returncode == 0:
        raise RunnerError(
            "RESOURCE_ALREADY_EXISTS", f"exact validation {kind} already exists"
        )
    diagnostic = (result.stdout + result.stderr).lower()
    if not _resource_is_absent(kind, name, diagnostic):
        raise RunnerError(
            "RESOURCE_PREFLIGHT_FAILED", f"exact validation {kind} could not be inspected"
        )


def _resource_is_absent(kind: str, name: str, diagnostic: str) -> bool:
    lowered_name = name.lower()
    if kind == "network":
        return "no such network" in diagnostic or (
            f"network {lowered_name}" in diagnostic and "not found" in diagnostic
        )
    return (
        f"no such {kind}" in diagnostic
        or f"no such object: {lowered_name}" in diagnostic
        or ("no such object" in diagnostic and lowered_name in diagnostic)
    )


def _ownership(
    transcript: dict[str, object],
    kind: str,
    name: str,
    run_id: str,
    timeout: float,
) -> str:
    format_value = (
        '{{ index .Config.Labels "' + RUN_LABEL + '" }}'
        if kind == "container"
        else '{{ index .Labels "' + RUN_LABEL + '" }}'
    )
    result = _command(
        transcript,
        f"inspect_{kind}_ownership",
        ["docker", kind, "inspect", name, "--format", format_value],
        timeout_seconds=timeout,
        check=False,
    )
    if result.returncode == 0:
        return "owned" if result.stdout.strip() == run_id else "foreign"
    diagnostic = (result.stdout + result.stderr).lower()
    return (
        "absent"
        if _resource_is_absent(kind, name, diagnostic)
        else "inspection_failed"
    )


def _inspect_source_model_volume(
    transcript: dict[str, object],
    source_volume: str,
    timeout: float,
    *,
    step_name: str = "inspect_source_model_volume",
) -> None:
    result = _command(
        transcript,
        step_name,
        [
            "docker",
            "volume",
            "inspect",
            source_volume,
            "--format",
            "{{json .}}",
        ],
        timeout_seconds=timeout,
    )
    try:
        row = json.loads(result.stdout)
        labels = row["Labels"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RunnerError(
            "SOURCE_MODEL_VOLUME_INSPECTION_INVALID",
            "source model volume inspection is invalid",
        ) from error
    if (
        not isinstance(row, dict)
        or row.get("Name") != source_volume
        or not isinstance(labels, dict)
        or labels.get(PROJECT_LABEL) != PROJECT_LABEL_VALUE
        or labels.get(PURPOSE_LABEL) != PURPOSE_LABEL_VALUE
    ):
        raise RunnerError(
            "SOURCE_MODEL_VOLUME_LABEL_MISMATCH",
            "source model volume does not carry the required project labels",
        )
    model_input = transcript.get("model_input")
    if isinstance(model_input, dict):
        model_input["source_labels_verified"] = True
        count = model_input.get("source_label_inspection_count", 0)
        if isinstance(count, int) and not isinstance(count, bool):
            model_input["source_label_inspection_count"] = count + 1


def _model_input_mount(args: argparse.Namespace) -> str:
    if args.source_model_volume is not None:
        return (
            f"type=volume,src={args.source_model_volume},"
            "dst=/input/assets,readonly"
        )
    assert isinstance(args.assets_root, Path)
    return (
        f"type=bind,src={args.assets_root},dst=/input/assets,readonly"
    )


def _initialization_script() -> str:
    installer = "/opt/ai-novel-world/tts-sidecar/runtime/install_models.py"
    lock = "/opt/ai-novel-world/tts-sidecar/model-source.lock.json"
    verify_source = (
        f"python {installer} --lock {lock} --assets-root /input/assets "
        "--verify --offline"
    )
    verify_target = (
        f"python {installer} --lock {lock} --assets-root /output/model "
        "--verify --offline --expected-uid 65532 --expected-gid 65532"
    )
    return (
        "set -eu; "
        f"trap 'rm -f {INIT_TOKEN_PATH}' EXIT; "
        f"{verify_source}; "
        "install -o 65532 -g 65532 -m 0400 "
        f"{INIT_TOKEN_PATH} /output/secret/moss_tts_sidecar_token; "
        "install -d -o 65532 -g 65532 -m 0755 /output/model/releases; "
        f"cp -a /input/assets/releases/{MODEL_INVENTORY_SHA256} "
        "/output/model/releases/; "
        "chown 65532:65532 /output/secret; chmod 0555 /output/secret; "
        "chown -R 65532:65532 /output/model; "
        "find /output/model -type f -exec chmod 0444 {} +; "
        "find /output/model -type d -exec chmod 0555 {} +; "
        f"{verify_target}"
    )


def _init_create_command(
    names: RealNames,
    args: argparse.Namespace,
) -> list[str]:
    return [
        "docker",
        "create",
        "--name",
        names.init_client,
        "--label",
        f"{RUN_LABEL}={names.run_id}",
        "--network",
        "none",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "FOWNER",
        "--cap-add",
        "DAC_OVERRIDE",
        "--security-opt",
        "no-new-privileges:true",
        "--mount",
        _model_input_mount(args),
        "--mount",
        f"type=volume,src={names.secret_volume},dst=/output/secret",
        "--mount",
        f"type=volume,src={names.model_volume},dst=/output/model",
        "--entrypoint",
        "/bin/sh",
        args.image_ref,
        "-c",
        _initialization_script(),
    ]


def _verify_initializer_security(
    transcript: dict[str, object],
    names: RealNames,
    args: argparse.Namespace,
) -> None:
    result = _command(
        transcript,
        "inspect_private_volume_initializer",
        [
            "docker",
            "container",
            "inspect",
            names.init_client,
            "--format",
            "{{json .}}",
        ],
        timeout_seconds=args.command_timeout_seconds,
    )
    try:
        row = json.loads(result.stdout)
        config = row["Config"]
        host = row["HostConfig"]
        mounts = row["Mounts"]
        state = row["State"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RunnerError(
            "INITIALIZER_INSPECTION_INVALID",
            "private-volume initializer inspection is invalid",
        ) from error
    if not isinstance(mounts, list):
        raise RunnerError(
            "INITIALIZER_INSPECTION_INVALID",
            "private-volume initializer mounts are invalid",
        )
    destinations = {
        item.get("Destination"): item
        for item in mounts
        if isinstance(item, dict)
    }
    source = destinations.get("/input/assets")
    secret = destinations.get("/output/secret")
    model = destinations.get("/output/model")
    labels = config.get("Labels") if isinstance(config, dict) else None
    source_matches = (
        isinstance(source, dict)
        and source.get("RW") is False
        and (
            (
                args.source_model_volume is not None
                and source.get("Type") == "volume"
                and source.get("Name") == args.source_model_volume
            )
            or (
                args.source_model_volume is None
                and source.get("Type") == "bind"
                and source.get("Source") == os.fspath(args.assets_root)
            )
        )
    )
    if (
        not isinstance(config, dict)
        or not isinstance(host, dict)
        or not isinstance(state, dict)
        or state.get("Running") is not False
        or state.get("Status") != "created"
        or config.get("User") != "0:0"
        or not isinstance(labels, dict)
        or labels.get(RUN_LABEL) != names.run_id
        or host.get("NetworkMode") != "none"
        or frozenset(destinations)
        != {"/input/assets", "/output/secret", "/output/model"}
        or not source_matches
        or not isinstance(secret, dict)
        or secret.get("RW") is not True
        or secret.get("Type") != "volume"
        or secret.get("Name") != names.secret_volume
        or not isinstance(model, dict)
        or model.get("RW") is not True
        or model.get("Type") != "volume"
        or model.get("Name") != names.model_volume
    ):
        raise RunnerError(
            "INITIALIZER_SECURITY_MISMATCH",
            "private-volume initializer mounts or identity are unsafe",
        )


def _token_copy_command(
    names: RealNames,
    args: argparse.Namespace,
) -> list[str]:
    assert isinstance(args.token_file, Path)
    return [
        "docker",
        "cp",
        os.fspath(args.token_file),
        f"{names.init_client}:{INIT_TOKEN_PATH}",
    ]


def _init_start_command(names: RealNames) -> list[str]:
    return ["docker", "start", "--attach", names.init_client]


def _client_command(
    names: RealNames,
    args: argparse.Namespace,
    *,
    client_name: str,
    script: str,
    remove: bool = True,
) -> list[str]:
    command = [
        "docker",
        "run",
    ]
    if remove:
        command.append("--rm")
    command.extend(
        [
            "--name",
            client_name,
            "--label",
            f"{RUN_LABEL}={names.run_id}",
            "--network",
            names.network,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            f"type=volume,src={names.secret_volume},dst=/run/secrets,readonly",
            "--entrypoint",
            "python",
            args.image_ref,
            "-c",
            script,
        ]
    )
    return command


def _parse_client_json(result: subprocess.CompletedProcess[str], name: str) -> dict[str, object]:
    try:
        row = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RunnerError("CLIENT_OUTPUT_INVALID", f"{name} client output is invalid") from error
    if not isinstance(row, dict) or row.get("status") != "passed":
        raise RunnerError("CLIENT_VALIDATION_FAILED", f"{name} client did not pass")
    return row


def _validate_smoke_lease_summary(row: Mapping[str, object], name: str) -> None:
    lease = row.get("lease")
    if (
        not isinstance(lease, dict)
        or frozenset(lease)
        != {
            "ttl_seconds",
            "lease_generation",
            "renewal_count",
            "worker_token_recorded",
            "stale_worker_token_rejected",
            "final_status",
        }
        or lease.get("ttl_seconds") != LEASE_TTL_SECONDS
        or not isinstance(lease.get("lease_generation"), int)
        or isinstance(lease.get("lease_generation"), bool)
        or int(lease["lease_generation"]) < 1
        or not isinstance(lease.get("renewal_count"), int)
        or isinstance(lease.get("renewal_count"), bool)
        or int(lease["renewal_count"]) < 1
        or lease.get("worker_token_recorded") is not False
        or lease.get("stale_worker_token_rejected") is not True
        or lease.get("final_status") != "unloaded"
    ):
        raise RunnerError(
            "CLIENT_LEASE_VALIDATION_FAILED",
            f"{name} client did not prove the frozen worker lease lifecycle",
        )


def _wait_local_probe(
    transcript: dict[str, object],
    names: RealNames,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + min(timeout, 60.0)
    last: subprocess.CompletedProcess[str] | None = None
    while time.monotonic() < deadline:
        last = _command(
            transcript,
            "probe_sidecar_state",
            ["docker", "exec", names.sidecar, "python", "-c", PROBE_CLIENT_SCRIPT],
            timeout_seconds=10,
            check=False,
        )
        if last.returncode == 0:
            try:
                row = json.loads(last.stdout)
            except json.JSONDecodeError:
                row = None
            if isinstance(row, dict) and row.get("status") == 200:
                return row
        time.sleep(0.2)
    raise RunnerError("SIDECAR_START_TIMEOUT", "dedicated Sidecar did not become live")


def _verify_container_security(
    transcript: dict[str, object],
    names: RealNames,
    args: argparse.Namespace,
) -> None:
    result = _command(
        transcript,
        "inspect_sidecar_security",
        ["docker", "container", "inspect", names.sidecar, "--format", "{{json .}}"],
        timeout_seconds=args.command_timeout_seconds,
    )
    try:
        row = json.loads(result.stdout)
        host = row["HostConfig"]
        config = row["Config"]
        ports = row["NetworkSettings"]["Ports"]
        networks = row["NetworkSettings"]["Networks"]
        mounts = row["Mounts"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise RunnerError("CONTAINER_INSPECTION_INVALID", "container inspection is invalid") from error
    destinations = {
        item.get("Destination"): (item.get("RW"), item.get("Name"), item.get("Type"))
        for item in mounts
        if isinstance(item, dict)
    }
    if (
        row.get("Image") != args.expected_image_id
        or config.get("Image") != args.image_ref
        or config.get("User") != "65532:65532"
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or "ALL" not in (host.get("CapDrop") or [])
        or not any("no-new-privileges" in item for item in (host.get("SecurityOpt") or []))
        or ports not in ({}, None)
        or frozenset(networks) != {names.network}
        or destinations.get("/opt/moss-assets")
        != (False, names.model_volume, "volume")
        or destinations.get("/run/secrets")
        != (False, names.secret_volume, "volume")
    ):
        raise RunnerError(
            "CONTAINER_SECURITY_MISMATCH",
            "dedicated Sidecar security or mount identity differs from the runner",
        )


def _cleanup_real(
    transcript: dict[str, object],
    names: RealNames,
    args: argparse.Namespace,
    *,
    image_created: bool,
) -> list[str]:
    failures: list[str] = []
    timeout = args.command_timeout_seconds
    for client in (names.fault_client, names.smoke_client, names.init_client):
        ownership = _ownership(
            transcript, "container", client, names.run_id, timeout
        )
        if ownership == "owned":
            result = _command(
                transcript,
                f"cleanup_{client}",
                ["docker", "container", "rm", "--force", client],
                timeout_seconds=timeout,
                check=False,
            )
            if result.returncode != 0:
                failures.append(client)
        elif ownership not in {"absent"}:
            failures.append(f"{client}:{ownership}")
    sidecar_ownership = _ownership(
        transcript, "container", names.sidecar, names.run_id, timeout
    )
    if sidecar_ownership == "owned":
        result = _command(
            transcript,
            "cleanup_sidecar",
            ["docker", "container", "rm", "--force", names.sidecar],
            timeout_seconds=timeout,
            check=False,
        )
        if result.returncode != 0:
            failures.append(names.sidecar)
    elif sidecar_ownership not in {"absent"}:
        failures.append(f"{names.sidecar}:{sidecar_ownership}")
    network_ownership = _ownership(
        transcript, "network", names.network, names.run_id, timeout
    )
    if network_ownership == "owned":
        result = _command(
            transcript,
            "cleanup_network",
            ["docker", "network", "rm", names.network],
            timeout_seconds=timeout,
            check=False,
        )
        if result.returncode != 0:
            failures.append(names.network)
    elif network_ownership not in {"absent"}:
        failures.append(f"{names.network}:{network_ownership}")
    for volume in (names.secret_volume, names.model_volume):
        volume_ownership = _ownership(
            transcript, "volume", volume, names.run_id, timeout
        )
        if volume_ownership == "owned":
            result = _command(
                transcript,
                f"cleanup_{volume}",
                ["docker", "volume", "rm", volume],
                timeout_seconds=timeout,
                check=False,
            )
            if result.returncode != 0:
                failures.append(volume)
        elif volume_ownership not in {"absent"}:
            failures.append(f"{volume}:{volume_ownership}")
    if image_created:
        inspection = _command(
            transcript,
            "inspect_cleanup_image_identity",
            ["docker", "image", "inspect", args.image_ref, "--format", "{{.Id}}"],
            timeout_seconds=timeout,
            check=False,
        )
        diagnostic = (inspection.stdout + inspection.stderr).lower()
        if inspection.returncode != 0 and "no such" in diagnostic:
            pass
        elif (
            inspection.returncode == 0
            and inspection.stdout.strip() == getattr(args, "expected_image_id", None)
        ):
            result = _command(
                transcript,
                "cleanup_image_tag",
                ["docker", "image", "rm", args.image_ref],
                timeout_seconds=timeout,
                check=False,
            )
            if result.returncode != 0:
                failures.append(args.image_ref)
        else:
            failures.append(f"{args.image_ref}:identity_mismatch")
    return failures


def _run_real(
    args: argparse.Namespace,
    transcript: dict[str, object],
    names: RealNames,
) -> None:
    try:
        read_secret_token(args.token_file)
        if args.assets_root is not None:
            verify_release(
                REPOSITORY_ROOT / "docker/tts-sidecar/model-source.lock.json",
                args.assets_root,
            )
    except (ModelAssetError, SidecarRuntimeError) as error:
        raise RunnerError(
            error.code,
            "real lifecycle preflight rejected local inputs",
        ) from error
    timeout = args.command_timeout_seconds
    image_created = False
    cleanup_failures: list[str] = []
    primary_failure: BaseException | None = None
    fault_process: subprocess.Popen[str] | None = None
    with _lock_nano(args.lock_file):
        transcript["lock_nano"] = {
            "acquired": True,
            "grant_id_sha256": _sha256(args.lock_grant.encode("utf-8")),
            "released": False,
        }
        try:
            _owned_absent(transcript, "container", names.sidecar, timeout)
            _owned_absent(transcript, "container", names.smoke_client, timeout)
            _owned_absent(transcript, "container", names.fault_client, timeout)
            _owned_absent(transcript, "container", names.init_client, timeout)
            _owned_absent(transcript, "network", names.network, timeout)
            _owned_absent(transcript, "volume", names.secret_volume, timeout)
            _owned_absent(transcript, "volume", names.model_volume, timeout)
            if args.image_mode == "build":
                _owned_absent(transcript, "image", args.image_ref, timeout)
                build = [
                    "docker",
                    "buildx",
                    "build",
                    "--pull",
                    "--no-cache",
                    "--platform",
                    "linux/arm64",
                    "--file",
                    "docker/tts-sidecar/Dockerfile",
                    "--target",
                    "production-runtime",
                    "--load",
                    "--tag",
                    args.image_ref,
                    ".",
                ]
                _command(
                    transcript,
                    "build_production_image",
                    build,
                    timeout_seconds=timeout,
                )
                image_created = True
                built_identity = _command(
                    transcript,
                    "inspect_built_image_id",
                    [
                        "docker",
                        "image",
                        "inspect",
                        args.image_ref,
                        "--format",
                        "{{.Id}}",
                    ],
                    timeout_seconds=timeout,
                ).stdout.strip()
                if re.fullmatch(r"sha256:[0-9a-f]{64}", built_identity) is None:
                    raise RunnerError(
                        "IMAGE_ID_INVALID",
                        "built image did not expose a local image ID",
                    )
                args.expected_image_id = built_identity
            verifier = DockerComposeSidecarLifecycle(
                repository_root=REPOSITORY_ROOT,
                image_ref=args.image_ref,
                expected_digest=args.expected_image_digest,
                digest_kind=args.digest_kind,
                command_timeout_seconds=timeout,
            )
            verification = verifier.verify_image()
            args.expected_image_id = verification.observed_image_id
            _record_step(
                transcript,
                name=(
                    "verify_prebuilt_production_image"
                    if args.image_mode == "prebuilt"
                    else "verify_production_image"
                ),
                status="passed",
                duration_ms=0,
                evidence={
                    "digest_kind": verification.digest_kind,
                    "observed_image_id": verification.observed_image_id,
                    "repo_digests_sha256": _sha256(
                        _canonical_bytes(verification.observed_repo_digests)
                    ),
                    "architecture": verification.architecture,
                },
            )
            for volume, step_name in (
                (names.secret_volume, "create_secret_volume"),
                (names.model_volume, "create_model_volume"),
            ):
                _command(
                    transcript,
                    step_name,
                    [
                        "docker",
                        "volume",
                        "create",
                        "--label",
                        f"{RUN_LABEL}={names.run_id}",
                        volume,
                    ],
                    timeout_seconds=timeout,
                )
            if args.source_model_volume is not None:
                _inspect_source_model_volume(
                    transcript,
                    args.source_model_volume,
                    timeout,
                    step_name="inspect_source_model_volume_before_initializer",
                )
            _command(
                transcript,
                "create_private_volume_initializer",
                _init_create_command(names, args),
                timeout_seconds=timeout,
            )
            if args.source_model_volume is not None:
                _inspect_source_model_volume(
                    transcript,
                    args.source_model_volume,
                    timeout,
                    step_name="inspect_source_model_volume_after_initializer",
                )
            _verify_initializer_security(transcript, names, args)
            _command(
                transcript,
                "copy_token_to_stopped_initializer",
                _token_copy_command(names, args),
                timeout_seconds=timeout,
            )
            _command(
                transcript,
                "initialize_private_volumes",
                _init_start_command(names),
                timeout_seconds=timeout,
            )
            _command(
                transcript,
                "create_internal_network",
                [
                    "docker",
                    "network",
                    "create",
                    "--internal",
                    "--label",
                    f"{RUN_LABEL}={names.run_id}",
                    names.network,
                ],
                timeout_seconds=timeout,
            )
            sidecar_command = [
                "docker",
                "run",
                "--detach",
                "--name",
                names.sidecar,
                "--label",
                f"{RUN_LABEL}={names.run_id}",
                "--network",
                names.network,
                "--network-alias",
                "tts-sidecar",
                "--restart",
                "no",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777",
                "--user",
                "65532:65532",
                "--init",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "256",
                "--memory",
                "4g",
                "--cpus",
                "4",
                "--env",
                f"MOSS_MODEL_TREE_SHA256={MODEL_TREE_SHA256}",
                "--env",
                f"MOSS_SOURCE_TREE_SHA256={SOURCE_TREE_SHA256}",
                "--mount",
                f"type=volume,src={names.model_volume},dst=/opt/moss-assets,readonly",
                "--mount",
                f"type=volume,src={names.secret_volume},dst=/run/secrets,readonly",
                args.image_ref,
            ]
            _command(
                transcript,
                "start_dedicated_sidecar",
                sidecar_command,
                timeout_seconds=timeout,
            )
            initial_probe = _wait_local_probe(transcript, names, timeout)
            if (
                initial_probe.get("sidecar_status") != "unloaded"
                or initial_probe.get("ready") is not False
                or initial_probe.get("lease_active") is not False
                or initial_probe.get("lease_generation") != 0
            ):
                raise RunnerError(
                    "INITIAL_LEASE_STATE_INVALID",
                    "dedicated Sidecar did not begin unloaded without a worker lease",
                )
            _verify_container_security(transcript, names, args)
            smoke = _command(
                transcript,
                "authenticated_smoke",
                _client_command(
                    names,
                    args,
                    client_name=names.smoke_client,
                    script=SMOKE_CLIENT_SCRIPT,
                ),
                timeout_seconds=max(timeout, 1_200),
            )
            smoke_row = _parse_client_json(smoke, "initial")
            _validate_smoke_lease_summary(smoke_row, "initial")
            if (
                smoke_row.get("model_fingerprint_sha256")
                != EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
            ):
                raise RunnerError(
                    "MODEL_FINGERPRINT_MISMATCH",
                    "real client observed a different model fingerprint",
                )
            first_generation = int(smoke_row["generation"])
            fault_command = _client_command(
                names,
                args,
                client_name=names.fault_client,
                script=FAULT_CLIENT_SCRIPT,
                remove=False,
            )
            fault_started = time.perf_counter()
            fault_process = subprocess.Popen(
                fault_command,
                cwd=REPOSITORY_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            active = False
            for _ in range(300):
                probe = _wait_local_probe(transcript, names, timeout)
                if (
                    probe.get("active_request_count") == 1
                    and probe.get("lease_active") is True
                    and isinstance(probe.get("lease_generation"), int)
                    and not isinstance(probe.get("lease_generation"), bool)
                    and int(probe["lease_generation"]) >= 1
                ):
                    active = True
                    break
                time.sleep(0.02)
            if not active:
                raise RunnerError(
                    "ACTIVE_REQUEST_NOT_OBSERVED",
                    "dedicated fault request never became active",
                )
            _command(
                transcript,
                "kill_active_dedicated_sidecar",
                ["docker", "container", "kill", "--signal", "KILL", names.sidecar],
                timeout_seconds=timeout,
            )
            try:
                fault_stdout, fault_stderr = fault_process.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                fault_process.kill()
                fault_stdout, fault_stderr = fault_process.communicate(timeout=10)
            _record_step(
                transcript,
                name="fault_client_terminated",
                status="passed" if fault_process.returncode != 0 else "failed",
                duration_ms=(time.perf_counter() - fault_started) * 1000,
                evidence={
                    "exit_code": fault_process.returncode,
                    "stdout_sha256": _sha256(fault_stdout.encode()),
                    "stderr_sha256": _sha256(fault_stderr.encode()),
                    "active_observed": active,
                },
            )
            if fault_process.returncode == 0:
                raise RunnerError(
                    "FAULT_CLIENT_UNEXPECTED_SUCCESS",
                    "active fault client unexpectedly received a successful terminal result",
                )
            _command(
                transcript,
                "restart_dedicated_sidecar",
                ["docker", "container", "start", names.sidecar],
                timeout_seconds=timeout,
            )
            restarted = _wait_local_probe(transcript, names, timeout)
            if (
                restarted.get("sidecar_status") != "unloaded"
                or restarted.get("ready") is not False
                or restarted.get("lease_active") is not False
                or restarted.get("lease_generation") != 0
            ):
                raise RunnerError(
                    "RESTART_PREWARM_STATE_INVALID",
                    "restarted Sidecar retained model or worker lease state",
                )
            recovery = _command(
                transcript,
                "recovery_smoke",
                _client_command(
                    names,
                    args,
                    client_name=names.smoke_client,
                    script=SMOKE_CLIENT_SCRIPT,
                ),
                timeout_seconds=max(timeout, 1_200),
            )
            recovery_row = _parse_client_json(recovery, "recovery")
            _validate_smoke_lease_summary(recovery_row, "recovery")
            new_generation = int(recovery_row["generation"])
            if new_generation == first_generation:
                raise RunnerError(
                    "GENERATION_REUSED", "restarted Sidecar reused the old generation"
                )
            transcript["real_result"] = {
                "image_mode": args.image_mode,
                "image_id": verification.observed_image_id,
                "digest_kind": verification.digest_kind,
                "first_generation": first_generation,
                "recovery_generation": new_generation,
                "generation_changed": True,
                "initial_smoke": smoke_row,
                "recovery_smoke": recovery_row,
            }
            transcript["status"] = "real_pass"
        except BaseException as error:
            primary_failure = error
        finally:
            cleanup_failures = _cleanup_real(
                transcript,
                names,
                args,
                image_created=image_created,
            )
            if fault_process is not None and fault_process.poll() is None:
                try:
                    fault_process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    fault_process.kill()
                    fault_process.communicate(timeout=10)
            lock_row = transcript.get("lock_nano")
            if isinstance(lock_row, dict):
                lock_row["released"] = True
            transcript["cleanup"] = {
                "exact_resources_only": True,
                "failures": cleanup_failures,
            }
    if cleanup_failures:
        raise RunnerError(
            "EXACT_CLEANUP_FAILED", "one or more exact runner-owned resources remain"
        )
    if primary_failure is not None:
        if isinstance(primary_failure, RunnerError):
            raise primary_failure
        raise RunnerError("REAL_VALIDATION_FAILED", "real lifecycle validation failed") from primary_failure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay the T1-B Sidecar lifecycle with exact-resource cleanup",
    )
    parser.add_argument(
        "--mode", choices=("dry-run", "fake", "real"), default="dry-run"
    )
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--resource-prefix")
    parser.add_argument("--image-ref")
    parser.add_argument("--expected-image-digest")
    parser.add_argument(
        "--image-mode", choices=("build", "prebuilt"), default="build"
    )
    parser.add_argument(
        "--digest-kind",
        choices=("registry_manifest", "local_image_id"),
        default="local_image_id",
    )
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--lock-grant")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--assets-root", type=Path)
    parser.add_argument("--source-model-volume")
    parser.add_argument("--confirm-real-nano")
    parser.add_argument("--confirm-active-kill")
    parser.add_argument("--confirm-prebuilt-image")
    parser.add_argument("--confirm-source-model-volume")
    parser.add_argument("--command-timeout-seconds", type=float, default=1_800.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    transcript = _base_transcript(args.mode)
    exit_code = 0
    try:
        if (
            not isinstance(args.command_timeout_seconds, (int, float))
            or isinstance(args.command_timeout_seconds, bool)
            or not (1 <= args.command_timeout_seconds <= 3_600)
        ):
            raise RunnerError("TIMEOUT_INVALID", "command timeout is invalid")
        if args.mode == "dry-run":
            transcript["status"] = "dry_run"
            transcript["real_requirements"] = {
                "confirm_real_nano": RUNNER_CONFIRMATION,
                "confirm_active_kill": KILL_CONFIRMATION,
                "lock_nano_required": True,
                "exact_resource_prefix_required": True,
                "fixed_digest_kind_required": True,
                "prebuilt_confirmation": PREBUILT_CONFIRMATION,
                "model_input_exactly_one_of": [
                    "--assets-root",
                    "--source-model-volume",
                ],
                "host_assets_verified_before_docker": True,
                "source_model_volume_confirmation": (
                    SOURCE_MODEL_VOLUME_CONFIRMATION
                ),
                "source_model_volume_required_labels": {
                    PROJECT_LABEL: PROJECT_LABEL_VALUE,
                    PURPOSE_LABEL: PURPOSE_LABEL_VALUE,
                },
                "source_model_volume_mount": "readonly",
                "source_model_volume_inspection": "before_and_after_initializer_create",
                "source_model_volume_cleanup_permitted": False,
                "source_model_volume_verified_offline_in_container": True,
                "offline_artifact_verification_count": 29,
                "token_transport": (
                    "docker_create_then_cp_single_file_then_start_attach"
                ),
                "token_host_bind_permitted": False,
                "broad_cleanup_permitted": False,
                "worker_lease_required": True,
                "control_token_business_requests_permitted": False,
                "worker_token_recording_permitted": False,
                "lease_release_must_unload_model": True,
            }
        elif args.mode == "fake":
            _run_fake(transcript)
        else:
            names = _validate_real_arguments(args)
            transcript["model_input"] = {
                "kind": (
                    "existing_labeled_volume"
                    if args.source_model_volume is not None
                    else "host_assets"
                ),
                "source_volume": args.source_model_volume,
                "source_mount_readonly": args.source_model_volume is not None,
                "source_cleanup_permitted": False,
                "source_labels_verified": False,
                "source_label_inspection_count": 0,
                "offline_artifact_verification_count": 29,
            }
            transcript["resource_names"] = {
                "prefix": names.prefix,
                "sidecar": names.sidecar,
                "network": names.network,
                "smoke_client": names.smoke_client,
                "fault_client": names.fault_client,
                "init_client": names.init_client,
                "secret_volume": names.secret_volume,
                "model_volume": names.model_volume,
            }
            _run_real(args, transcript, names)
    except RunnerError as error:
        transcript["status"] = "failed"
        transcript["error_code"] = error.code
        exit_code = 2
    finally:
        transcript["finished_unix_ns"] = time.time_ns()
        transcript["transcript_sha256"] = _sha256(
            _canonical_bytes(
                {key: value for key, value in transcript.items() if key != "transcript_sha256"}
            )
        )
        if args.transcript is not None:
            try:
                _atomic_write_json(args.transcript, transcript)
            except RunnerError as error:
                transcript["status"] = "failed"
                transcript["error_code"] = error.code
                exit_code = 2
        print(json.dumps(transcript, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
