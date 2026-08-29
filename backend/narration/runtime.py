"""PawApp-side private Sidecar lifecycle and Moss Nano adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
from http.client import HTTPConnection, HTTPResponse
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Final, Literal, Mapping, Protocol
from uuid import UUID, uuid4
import wave

from .adapters import (
    AdapterUnavailableError,
    MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES,
    MossNanoTTSAdapter,
)
from .contracts import (
    AdapterCapabilities,
    AdapterHealth,
    AdapterHealthStatus,
    CancelDisposition,
    ContractError,
    ModelFingerprint,
    NanoDecodeParametersV2,
    NarrationRequestScope,
    PRODUCTION_NANO_MAX_NEW_FRAMES,
    PRODUCTION_NANO_MAX_SEED,
    PRODUCTION_NANO_SAMPLE_MODES,
    SynthesisRequest,
    SynthesisResult,
)
from .fingerprints import capabilities_fingerprint, model_fingerprint_sha256, scope_fingerprint


PROTOCOL_VERSION: Final = "moss-tts-sidecar/1.1"
TOKEN_HEADER: Final = "X-MOSS-Sidecar-Token"
WORKER_TOKEN_HEADER: Final = "X-MOSS-Worker-Token"
VERSION_HEADER: Final = "X-MOSS-Protocol-Version"
GENERATION_HEADER: Final = "X-MOSS-Worker-Generation"
CAPABILITIES_SHA256: Final = capabilities_fingerprint(MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES)
MAX_JSON_BYTES: Final = 64 * 1024
MAX_AUDIO_BYTES: Final = 16 * 1024 * 1024
MAX_REFERENCE_BYTES: Final = 12 * 1024 * 1024
MIN_TOKEN_CHARS: Final = 32
MAX_TOKEN_CHARS: Final = 128
PRODUCTION_SIDECAR_HOST: Final = "tts-sidecar"
PRODUCTION_SIDECAR_PORT: Final = 8765
EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256: Final = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
WORKER_LEASE_TTL_SECONDS: Final = 60
WORKER_LEASE_RENEW_INTERVAL_SECONDS: Final = 15
WORKER_LEASE_DEACTIVATE_TIMEOUT_SECONDS: Final = 15.0
WORKER_TOKEN_CHARS: Final = 43
EXPECTED_PRODUCTION_IMAGE_WORK_PACKAGE: Final = "T1-B"
EXPECTED_PRODUCTION_BUSINESS_RUNTIME: Final = "present"
EXPECTED_PRODUCTION_ENTRYPOINT: Final = (
    "python",
    "/opt/ai-novel-world/tts-sidecar/runtime/sidecar_server.py",
)
_CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")


class SidecarRuntimeError(AdapterUnavailableError):
    """Stable fail-closed runtime failure; messages contain no text or paths."""

    def __init__(self, code: str, message: str, *, poison: bool = False):
        super().__init__(message)
        self.code = code
        self.poison = poison


@dataclass(frozen=True, slots=True)
class SidecarRuntimeConfig:
    host: str
    port: int
    token_file: Path
    timeout_seconds: float = 120.0
    allow_test_backend: bool = False

    def __post_init__(self) -> None:
        if type(self.allow_test_backend) is not bool:
            raise ContractError("allow_test_backend must be an exact boolean")
        if self.allow_test_backend:
            if self.host not in {"127.0.0.1", "localhost"}:
                raise ContractError("test Sidecar host must be loopback")
        elif self.host != PRODUCTION_SIDECAR_HOST:
            raise ContractError("production Sidecar host must be the frozen Compose service identity")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            raise ContractError("Sidecar port is invalid")
        if not self.allow_test_backend and self.port != PRODUCTION_SIDECAR_PORT:
            raise ContractError("production Sidecar port must be the frozen private service port")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(self.timeout_seconds, bool) or not (0 < self.timeout_seconds <= 600):
            raise ContractError("Sidecar timeout is invalid")
        if not isinstance(self.token_file, Path) or not self.token_file.is_absolute():
            raise ContractError("Sidecar token_file must be an absolute path")


@dataclass(frozen=True, slots=True)
class SidecarValidationMetrics:
    """Secret-free metrics projected from one authenticated health read.

    The Sidecar has one inference slot and rejects concurrent synthesis with
    ``SIDECAR_BUSY``; it deliberately has no in-process queue.  ``queued_jobs``
    is therefore an exact zero rather than a database or scheduler estimate.
    """

    model_ready: bool
    worker_ready: bool
    active_syntheses: int
    queued_jobs: int = 0

    def __post_init__(self) -> None:
        if type(self.model_ready) is not bool or type(self.worker_ready) is not bool:
            raise ContractError("Sidecar validation readiness must be exact booleans")
        if (
            isinstance(self.active_syntheses, bool)
            or not isinstance(self.active_syntheses, int)
            or self.active_syntheses < 0
            or self.active_syntheses > 1
            or isinstance(self.queued_jobs, bool)
            or not isinstance(self.queued_jobs, int)
            or self.queued_jobs != 0
        ):
            raise ContractError("Sidecar validation metrics are invalid")


def read_secret_token(path: Path) -> str:
    if not isinstance(path, Path) or not path.is_absolute():
        raise SidecarRuntimeError("TOKEN_FILE_INVALID", "Sidecar token secret path is invalid")
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise SidecarRuntimeError("TOKEN_FILE_INVALID", "Sidecar token secret open policy is unavailable")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_size > MAX_TOKEN_CHARS
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise SidecarRuntimeError("TOKEN_FILE_INVALID", "Sidecar token secret file is invalid")
        chunks: list[bytes] = []
        remaining = MAX_TOKEN_CHARS + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (
                details.st_dev,
                details.st_ino,
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or len(raw) != details.st_size
        ):
            raise SidecarRuntimeError("TOKEN_FILE_INVALID", "Sidecar token secret changed while being read")
        token = raw.decode("ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise SidecarRuntimeError("TOKEN_FILE_INVALID", "Sidecar token secret file is unreadable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not (MIN_TOKEN_CHARS <= len(token) <= MAX_TOKEN_CHARS) or any(
        not (0x21 <= byte <= 0x7E) for byte in raw
    ):
        raise SidecarRuntimeError("TOKEN_CONFIGURATION_INVALID", "Sidecar token secret value is invalid")
    return token


class SidecarLifecycle(Protocol):
    async def restart_after_poison(
        self,
        reason_code: str,
        *,
        previous_generation: int | None = None,
    ) -> None: ...


class NoopSidecarLifecycle:
    async def restart_after_poison(
        self,
        reason_code: str,
        *,
        previous_generation: int | None = None,
    ) -> None:
        del reason_code, previous_generation


class SupervisorManagedSidecarLifecycle:
    """Exit the private Sidecar and wait for its supervisor generation.

    The PawApp never receives Docker access.  An authenticated control request
    makes the Sidecar exit non-zero; Compose's bounded ``on-failure`` policy
    recreates it.  Success requires a different worker generation.
    """

    def __init__(
        self,
        config: SidecarRuntimeConfig,
        *,
        bootstrap_token: str | None = None,
        restart_timeout_seconds: float = 90.0,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if config.allow_test_backend:
            raise ContractError("supervisor lifecycle is production-only")
        if (
            not isinstance(restart_timeout_seconds, (int, float))
            or isinstance(restart_timeout_seconds, bool)
            or not (1 <= restart_timeout_seconds <= 300)
        ):
            raise ContractError("supervisor restart timeout is invalid")
        if (
            not isinstance(poll_interval_seconds, (int, float))
            or isinstance(poll_interval_seconds, bool)
            or not (0.05 <= poll_interval_seconds <= 2)
        ):
            raise ContractError("supervisor poll interval is invalid")
        self.config = config
        self.restart_timeout_seconds = float(restart_timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._token = (
            read_secret_token(config.token_file)
            if bootstrap_token is None
            else bootstrap_token
        )

    def _connection(self) -> HTTPConnection:
        return HTTPConnection(
            self.config.host,
            self.config.port,
            timeout=min(float(self.config.timeout_seconds), 5.0),
        )

    def _headers(self, body: bytes | None = None) -> dict[str, str]:
        headers = {TOKEN_HEADER: self._token, VERSION_HEADER: PROTOCOL_VERSION}
        if body is not None:
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
            )
        return headers

    @staticmethod
    def _response_generation(response: HTTPResponse, row: Mapping[str, object]) -> int:
        headers = _response_headers(response)
        raw_header = _header(headers, GENERATION_HEADER)
        worker = row.get("worker")
        raw_payload = worker.get("generation") if isinstance(worker, dict) else None
        if (
            raw_header is None
            or not raw_header.isdigit()
            or isinstance(raw_payload, bool)
            or not isinstance(raw_payload, int)
            or raw_payload <= 0
            or int(raw_header) != raw_payload
        ):
            raise SidecarRuntimeError(
                "WORKER_GENERATION_INVALID",
                "Sidecar supervisor probe generation is invalid",
            )
        return raw_payload

    def _probe_generation(self) -> int:
        connection = self._connection()
        try:
            connection.request("GET", "/v1/health", headers=self._headers())
            response = connection.getresponse()
            row = _response_json(response)
            if (
                response.status != 200
                or row.get("protocol_version") != PROTOCOL_VERSION
                or _header(_response_headers(response), VERSION_HEADER) != PROTOCOL_VERSION
            ):
                raise SidecarRuntimeError(
                    "SUPERVISOR_PROBE_INVALID",
                    "Sidecar supervisor probe response is invalid",
                )
            return self._response_generation(response, row)
        finally:
            connection.close()

    def _request_restart(self, reason_code: str) -> int:
        request_id = uuid4()
        body = _canonical_bytes(
            {"request_id": str(request_id), "reason_code": reason_code}
        )
        connection = self._connection()
        try:
            connection.request(
                "POST",
                "/v1/restart",
                body=body,
                headers=self._headers(body),
            )
            response = connection.getresponse()
            row = _response_json(response)
            if (
                response.status != 202
                or row.get("protocol_version") != PROTOCOL_VERSION
                or row.get("request_id") != str(request_id)
                or row.get("status") != "restart_requested"
                or frozenset(row) != {
                    "protocol_version",
                    "request_id",
                    "status",
                    "worker",
                }
                or _header(_response_headers(response), VERSION_HEADER) != PROTOCOL_VERSION
            ):
                raise SidecarRuntimeError(
                    "SUPERVISOR_RESTART_RESPONSE_INVALID",
                    "Sidecar supervisor restart response is invalid",
                )
            return self._response_generation(response, row)
        finally:
            connection.close()

    async def restart_after_poison(
        self,
        reason_code: str,
        *,
        previous_generation: int | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", reason_code):
            raise SidecarRuntimeError(
                "RESTART_REASON_INVALID", "restart reason is invalid"
            )
        observed_before: int | None = previous_generation
        if observed_before is None:
            try:
                observed_before = await asyncio.to_thread(self._probe_generation)
            except (OSError, TimeoutError, SidecarRuntimeError):
                observed_before = None
        try:
            requested_generation = await asyncio.to_thread(
                self._request_restart, reason_code
            )
            if observed_before is None:
                observed_before = requested_generation
        except (OSError, TimeoutError, SidecarRuntimeError):
            # An internally poisoned Sidecar may already be exiting.  The
            # generation fence below remains the authority.
            pass

        deadline = asyncio.get_running_loop().time() + self.restart_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                generation = await asyncio.to_thread(self._probe_generation)
            except (OSError, TimeoutError, SidecarRuntimeError):
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            if observed_before is None or generation != observed_before:
                return
            await asyncio.sleep(self.poll_interval_seconds)
        raise SidecarRuntimeError(
            "SUPERVISOR_RESTART_TIMEOUT",
            "Sidecar supervisor did not publish a new worker generation",
        )


@dataclass(frozen=True, slots=True)
class DockerImageVerification:
    image_ref: str
    expected_digest: str
    digest_kind: Literal["registry_manifest", "local_image_id"]
    observed_image_id: str
    observed_repo_digests: tuple[str, ...]
    architecture: str
    work_package_label: str
    business_runtime_label: str
    running_container_id: str | None = None


class DockerComposeSidecarLifecycle:
    """Operations-only manager; PawApp need not receive a Docker socket.

    Build and image verification finish before ``compose up --no-build``.  The
    caller must explicitly declare whether its frozen digest is a registry
    manifest digest or a local image/config ID; the two are never conflated.
    """

    def __init__(
        self,
        *,
        repository_root: Path,
        image_ref: str,
        expected_digest: str,
        digest_kind: Literal["registry_manifest", "local_image_id"],
        command_timeout_seconds: float = 1_800.0,
    ) -> None:
        if not repository_root.is_absolute():
            raise ContractError("repository_root must be absolute")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest):
            raise ContractError("expected production image digest is invalid")
        if digest_kind not in {"registry_manifest", "local_image_id"}:
            raise ContractError("production image digest kind is invalid")
        if not isinstance(image_ref, str) or not image_ref or image_ref.startswith("-") or any(
            character.isspace() for character in image_ref
        ):
            raise ContractError("production image reference is invalid")
        if (
            not isinstance(command_timeout_seconds, (int, float))
            or isinstance(command_timeout_seconds, bool)
            or not (0 < command_timeout_seconds <= 3_600)
        ):
            raise ContractError("Docker lifecycle command timeout is invalid")
        self.repository_root = repository_root
        self.image_ref = image_ref
        self.expected_digest = expected_digest
        self.digest_kind = digest_kind
        self.command_timeout_seconds = command_timeout_seconds

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=self.command_timeout_seconds,
        )

    def _compose_prefix(self) -> list[str]:
        return ["docker", "compose", "--profile", "tts"]

    def _resolved_compose_image(self) -> str:
        result = self._run([*self._compose_prefix(), "config", "--format", "json"])
        try:
            row = json.loads(result.stdout)
            resolved = row["services"]["tts-sidecar"]["image"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise SidecarRuntimeError(
                "COMPOSE_INSPECTION_INVALID",
                "production Compose image configuration is invalid",
            ) from error
        if resolved != self.image_ref:
            raise SidecarRuntimeError(
                "COMPOSE_IMAGE_MISMATCH",
                "production Compose image differs from the frozen lifecycle image",
            )
        return str(resolved)

    @staticmethod
    def _repository_name(image_ref: str) -> str:
        without_digest = image_ref.split("@", 1)[0]
        final_slash = without_digest.rfind("/")
        final_colon = without_digest.rfind(":")
        return without_digest[:final_colon] if final_colon > final_slash else without_digest

    @staticmethod
    def _labels_and_entrypoint(row: Mapping[str, object]) -> tuple[Mapping[str, object], tuple[str, ...]]:
        try:
            config = row["Config"]
            if not isinstance(config, dict):
                raise TypeError
            labels = config.get("Labels") or {}
            entrypoint = config.get("Entrypoint")
            if not isinstance(labels, dict) or not isinstance(entrypoint, list) or not all(
                isinstance(item, str) for item in entrypoint
            ):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise SidecarRuntimeError(
                "IMAGE_INSPECTION_INVALID",
                "production image configuration is invalid",
            ) from error
        return labels, tuple(entrypoint)

    def _parse_and_verify_image(self, stdout: str) -> DockerImageVerification:
        try:
            row = json.loads(stdout)
            image_id = str(row["Id"])
            repo_digests = tuple(sorted(str(item) for item in (row.get("RepoDigests") or [])))
            architecture = str(row["Architecture"])
            labels, entrypoint = self._labels_and_entrypoint(row)
            work_package = str(labels.get("ai.novel.world.work-package", ""))
            business_runtime = str(labels.get("ai.novel.world.business-runtime", ""))
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise SidecarRuntimeError(
                "IMAGE_INSPECTION_INVALID",
                "production image inspection is invalid",
            ) from error
        if architecture != "arm64" or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise SidecarRuntimeError(
                "IMAGE_ARCHITECTURE_MISMATCH",
                "production image architecture or local identity is invalid",
            )
        if self.digest_kind == "local_image_id":
            digest_matches = image_id == self.expected_digest
        else:
            expected_repo_digest = (
                f"{self._repository_name(self.image_ref)}@{self.expected_digest}"
            )
            digest_matches = expected_repo_digest in repo_digests
        if not digest_matches:
            raise SidecarRuntimeError(
                "IMAGE_DIGEST_MISMATCH",
                "production image digest differs from its explicitly declared digest kind",
            )
        if work_package != EXPECTED_PRODUCTION_IMAGE_WORK_PACKAGE:
            raise SidecarRuntimeError(
                "IMAGE_LABEL_MISMATCH",
                "production image work-package label is invalid",
            )
        if business_runtime != EXPECTED_PRODUCTION_BUSINESS_RUNTIME:
            raise SidecarRuntimeError(
                "IMAGE_RUNTIME_ABSENT",
                "production image does not attest an installed business runtime",
            )
        if entrypoint != EXPECTED_PRODUCTION_ENTRYPOINT:
            raise SidecarRuntimeError(
                "IMAGE_ENTRYPOINT_MISMATCH",
                "production image entrypoint is not the frozen Sidecar server",
            )
        return DockerImageVerification(
            image_ref=self.image_ref,
            expected_digest=self.expected_digest,
            digest_kind=self.digest_kind,
            observed_image_id=image_id,
            observed_repo_digests=repo_digests,
            architecture=architecture,
            work_package_label=work_package,
            business_runtime_label=business_runtime,
        )

    def verify_image(self) -> DockerImageVerification:
        result = self._run(
            ["docker", "image", "inspect", self.image_ref, "--format", "{{json .}}"]
        )
        return self._parse_and_verify_image(result.stdout)

    def _inspect_running_container(
        self,
        verification: DockerImageVerification,
    ) -> DockerImageVerification:
        result = self._run([*self._compose_prefix(), "ps", "--quiet", "tts-sidecar"])
        identifiers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(identifiers) != 1 or _CONTAINER_ID.fullmatch(identifiers[0]) is None:
            raise SidecarRuntimeError(
                "CONTAINER_IDENTITY_INVALID",
                "production Sidecar container identity is invalid",
            )
        container_id = identifiers[0]
        inspected = self._run(
            ["docker", "container", "inspect", container_id, "--format", "{{json .}}"]
        )
        try:
            row = json.loads(inspected.stdout)
            running = row["State"]["Running"]
            container_image_id = row["Image"]
            configured_image_ref = row["Config"]["Image"]
            labels, entrypoint = self._labels_and_entrypoint(row)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise SidecarRuntimeError(
                "CONTAINER_INSPECTION_INVALID",
                "production Sidecar container inspection is invalid",
            ) from error
        if (
            running is not True
            or container_image_id != verification.observed_image_id
            or configured_image_ref != self.image_ref
        ):
            raise SidecarRuntimeError(
                "RUNNING_IMAGE_MISMATCH",
                "running Sidecar does not use the verified image object",
            )
        if (
            labels.get("ai.novel.world.work-package")
            != EXPECTED_PRODUCTION_IMAGE_WORK_PACKAGE
            or labels.get("ai.novel.world.business-runtime")
            != EXPECTED_PRODUCTION_BUSINESS_RUNTIME
            or entrypoint != EXPECTED_PRODUCTION_ENTRYPOINT
        ):
            raise SidecarRuntimeError(
                "RUNNING_IMAGE_LABEL_MISMATCH",
                "running Sidecar provenance differs from the verified image",
            )
        return replace(verification, running_container_id=container_id)

    def _cleanup_failed_start(self) -> None:
        try:
            self._run(
                [
                    *self._compose_prefix(),
                    "rm",
                    "--stop",
                    "--force",
                    "tts-sidecar",
                ]
            )
        except (OSError, subprocess.SubprocessError):
            # Preserve the primary fail-closed error.  The integration owner
            # must independently assert zero residuals after any failed gate.
            return

    def build_and_start(self, *, force_recreate: bool = False) -> DockerImageVerification:
        self._resolved_compose_image()
        self._run(
            [
                *self._compose_prefix(),
                "build",
                "--pull",
                "--no-cache",
                "tts-sidecar",
            ]
        )
        verification = self.verify_image()
        command = [
            "docker",
            "compose",
            "--profile",
            "tts",
            "up",
            "--detach",
            "--no-deps",
            "--no-build",
        ]
        if force_recreate:
            command.append("--force-recreate")
        command.append("tts-sidecar")
        try:
            self._run(command)
            return self._inspect_running_container(verification)
        except BaseException:
            self._cleanup_failed_start()
            raise

    async def restart_after_poison(
        self,
        reason_code: str,
        *,
        previous_generation: int | None = None,
    ) -> None:
        del previous_generation
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", reason_code):
            raise SidecarRuntimeError("RESTART_REASON_INVALID", "restart reason is invalid")
        await asyncio.to_thread(self.build_and_start, force_recreate=True)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sidecar_synthesis_metadata(
    *,
    request_id: UUID,
    scope: NarrationRequestScope,
    requested_model_fingerprint_sha256: str,
    text: str,
    voice: str,
    seed: int,
    sample_mode: str,
    max_new_frames: int,
    decode_parameters: NanoDecodeParametersV2 | None = None,
    reference_content_type: str | None = None,
    reference_actual_sha256: str | None = None,
    reference_size_bytes: int | None = None,
) -> bytes:
    """Build the exact canonical metadata sent to the private Sidecar.

    The worker also HMACs these bytes for model-run evidence.  Keeping one
    pure helper prevents the audit digest from silently drifting away from the
    actual Sidecar request shape.
    """

    if type(request_id) is not UUID or type(scope) is not NarrationRequestScope:
        raise ContractError("synthesis metadata identity is invalid")
    scope.ensure_fixed_local()
    if re.fullmatch(r"[0-9a-f]{64}", requested_model_fingerprint_sha256) is None:
        raise ContractError("requested model fingerprint is invalid")
    if not isinstance(text, str) or not text.strip():
        raise ContractError("synthesis metadata text is invalid")
    if not isinstance(voice, str) or not voice.strip():
        raise ContractError("synthesis metadata voice is invalid")
    if (
        type(seed) is not int
        or not 0 <= seed <= PRODUCTION_NANO_MAX_SEED
        or type(max_new_frames) is not int
        or not 1 <= max_new_frames <= PRODUCTION_NANO_MAX_NEW_FRAMES
    ):
        raise ContractError("synthesis metadata numeric values are invalid")
    if type(sample_mode) is not str or sample_mode not in PRODUCTION_NANO_SAMPLE_MODES:
        raise ContractError("synthesis metadata sample mode is invalid")
    if decode_parameters is not None:
        if type(decode_parameters) is not NanoDecodeParametersV2:
            raise ContractError("synthesis decode parameters are invalid")
        if sample_mode != "full":
            raise ContractError(
                "advanced Nano decode parameters are effective only in full mode"
            )
    reference_values = (
        reference_content_type,
        reference_actual_sha256,
        reference_size_bytes,
    )
    if any(value is not None for value in reference_values) and not all(
        value is not None for value in reference_values
    ):
        raise ContractError("synthesis reference metadata is incomplete")
    payload: dict[str, object] = {
        "request_id": str(request_id),
        "scope_fingerprint": scope_fingerprint(scope),
        "requested_model_fingerprint_sha256": requested_model_fingerprint_sha256,
        "text": text,
        "voice": voice,
        "seed": seed,
        "sample_mode": sample_mode,
        "max_new_frames": max_new_frames,
    }
    if decode_parameters is not None:
        payload["decode_parameters"] = dict(decode_parameters.wire_payload())
    if reference_content_type is not None:
        if reference_content_type not in {"audio/wav", "audio/flac"}:
            raise ContractError("synthesis reference content type is invalid")
        if (
            type(reference_actual_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", reference_actual_sha256) is None
            or type(reference_size_bytes) is not int
            or reference_size_bytes <= 0
        ):
            raise ContractError("synthesis reference evidence is invalid")
        payload["reference_audio"] = {
            "content_type": reference_content_type,
            "actual_sha256": reference_actual_sha256,
            "size_bytes": reference_size_bytes,
        }
    return _canonical_bytes(payload)


EXPECTED_PRODUCTION_MODEL_FINGERPRINT: Final = ModelFingerprint(
    adapter_contract_version="moss-nano-tts-adapter/1",
    model_name=(
        "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+"
        "MOSS-Audio-Tokenizer-Nano-ONNX"
    ),
    model_revision=(
        "f52645cb467506d8e18e746ddd59482685b74e58+"
        "ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae"
    ),
    artifact_tree_sha256=(
        "d0f173dbc661d0352825dd28a5b35a1c65d60be540badacf7ef3b1a57b0b416d"
    ),
    runtime_name="onnxruntime",
    runtime_version="1.24.3",
    execution_backend="cpu",
    protocol_version=PROTOCOL_VERSION,
    deployment_topology="linux_arm64_private_sidecar",
    parameters={
        "cpu_threads": 4,
        "source_tree_sha256": (
            "547f61c24427a59d802cc31dfe532e135303b6b9f71469be19a7f35acd5d4c94"
        ),
        "model_tree_sha256": (
            "92419b269673cd698afab06ef0e3f0b60673862c86190cc6c57ed010db9aca98"
        ),
    },
)
EXPECTED_TEST_MODEL_FINGERPRINT: Final = ModelFingerprint(
    adapter_contract_version="moss-nano-tts-adapter/1",
    model_name="fake-moss-nano-sidecar",
    model_revision="test-double/1",
    artifact_tree_sha256=(
        "508ec7374660c4840e0cf1c91ca3551db9b338616b731c95473c5ca0a0e76b6e"
    ),
    runtime_name="python-stdlib-fake",
    runtime_version="1",
    execution_backend="deterministic-test-double",
    protocol_version=PROTOCOL_VERSION,
    deployment_topology="test-only",
    parameters={"test_double": True},
)
EXPECTED_TEST_MODEL_FINGERPRINT_SHA256: Final = model_fingerprint_sha256(
    EXPECTED_TEST_MODEL_FINGERPRINT
)
assert (
    model_fingerprint_sha256(EXPECTED_PRODUCTION_MODEL_FINGERPRINT)
    == EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
)


def _parse_model_fingerprint(row: object) -> ModelFingerprint:
    if not isinstance(row, dict) or frozenset(row) != {
        "adapter_contract_version",
        "model_name",
        "model_revision",
        "artifact_tree_sha256",
        "runtime_name",
        "runtime_version",
        "execution_backend",
        "protocol_version",
        "deployment_topology",
        "parameters",
        "schema_version",
    }:
        raise SidecarRuntimeError("MODEL_FINGERPRINT_INVALID", "Sidecar model fingerprint shape is invalid", poison=True)
    try:
        return ModelFingerprint(**row)
    except (ContractError, TypeError) as error:
        raise SidecarRuntimeError("MODEL_FINGERPRINT_INVALID", "Sidecar model fingerprint value is invalid", poison=True) from error


def _response_json(response: HTTPResponse, *, maximum: int = MAX_JSON_BYTES) -> dict[str, object]:
    raw_length = response.getheader("Content-Length")
    if (
        response.getheader("Content-Type") != "application/json"
        or raw_length is None
        or not raw_length.isdigit()
        or not (1 <= int(raw_length) <= maximum)
    ):
        raise SidecarRuntimeError(
            "RESPONSE_SIZE_INVALID",
            "Sidecar JSON framing is invalid",
            poison=True,
        )
    body = response.read(int(raw_length) + 1)
    if len(body) != int(raw_length):
        raise SidecarRuntimeError(
            "RESPONSE_SIZE_INVALID",
            "Sidecar JSON response length differs from framing",
            poison=True,
        )
    try:
        row = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarRuntimeError("RESPONSE_JSON_INVALID", "Sidecar response is not valid JSON", poison=True) from error
    if not isinstance(row, dict):
        raise SidecarRuntimeError("RESPONSE_SHAPE_INVALID", "Sidecar response shape is invalid", poison=True)
    return row


_SECURITY_RESPONSE_HEADERS: Final = frozenset(
    {
        VERSION_HEADER.lower(),
        "x-moss-request-id",
        "x-moss-worker-generation",
        "x-moss-actual-model-fingerprint-sha256",
        "x-moss-audio-sha256",
        "x-moss-sample-rate",
        "x-moss-channels",
        "x-moss-sample-width",
    }
)


def _response_headers(response: HTTPResponse) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, value in response.getheaders():
        name = raw_name.lower()
        if name in _SECURITY_RESPONSE_HEADERS and name in headers:
            raise SidecarRuntimeError(
                "RESPONSE_HEADER_DUPLICATED",
                "Sidecar identity response header is duplicated",
                poison=True,
            )
        headers[name] = value
    return headers


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return headers.get(name.lower())


def _validate_complete_pcm_wav(payload: bytes) -> tuple[int, int, int]:
    """Validate a complete canonical PCM RIFF/WAV, including every frame."""

    if len(payload) < 44 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise SidecarRuntimeError(
            "AUDIO_FORMAT_INVALID", "Sidecar WAV container is invalid", poison=True
        )
    if int.from_bytes(payload[4:8], "little") != len(payload) - 8:
        raise SidecarRuntimeError(
            "AUDIO_TRAILING_OR_TRUNCATED",
            "Sidecar WAV RIFF length differs from actual bytes",
            poison=True,
        )
    offset = 12
    format_chunk: bytes | None = None
    data_chunk: bytes | None = None
    while offset < len(payload):
        if offset + 8 > len(payload):
            raise SidecarRuntimeError(
                "AUDIO_TRAILING_OR_TRUNCATED",
                "Sidecar WAV chunk header is truncated",
                poison=True,
            )
        chunk_name = payload[offset : offset + 4]
        chunk_size = int.from_bytes(payload[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        padded_end = chunk_end + (chunk_size & 1)
        if chunk_end > len(payload) or padded_end > len(payload):
            raise SidecarRuntimeError(
                "AUDIO_TRAILING_OR_TRUNCATED",
                "Sidecar WAV chunk is truncated",
                poison=True,
            )
        if chunk_name == b"fmt ":
            if format_chunk is not None or data_chunk is not None:
                raise SidecarRuntimeError(
                    "AUDIO_FORMAT_INVALID",
                    "Sidecar WAV format chunk ordering is invalid",
                    poison=True,
                )
            format_chunk = payload[chunk_start:chunk_end]
        elif chunk_name == b"data":
            if format_chunk is None or data_chunk is not None or padded_end != len(payload):
                raise SidecarRuntimeError(
                    "AUDIO_TRAILING_OR_TRUNCATED",
                    "Sidecar WAV data chunk is duplicated or has trailing chunks",
                    poison=True,
                )
            data_chunk = payload[chunk_start:chunk_end]
        else:
            raise SidecarRuntimeError(
                "AUDIO_FORMAT_INVALID",
                "Sidecar WAV contains a non-canonical chunk",
                poison=True,
            )
        offset = padded_end
    if format_chunk is None or data_chunk is None or len(format_chunk) != 16:
        raise SidecarRuntimeError(
            "AUDIO_FORMAT_INVALID", "Sidecar WAV chunks are incomplete", poison=True
        )
    audio_format = int.from_bytes(format_chunk[0:2], "little")
    channels = int.from_bytes(format_chunk[2:4], "little")
    sample_rate = int.from_bytes(format_chunk[4:8], "little")
    byte_rate = int.from_bytes(format_chunk[8:12], "little")
    block_align = int.from_bytes(format_chunk[12:14], "little")
    bits_per_sample = int.from_bytes(format_chunk[14:16], "little")
    sample_width = bits_per_sample // 8
    if (
        audio_format != 1
        or (sample_rate, channels, sample_width) != (48_000, 2, 2)
        or block_align != channels * sample_width
        or byte_rate != sample_rate * block_align
        or not data_chunk
        or len(data_chunk) % block_align
    ):
        raise SidecarRuntimeError(
            "AUDIO_FORMAT_DRIFT",
            "Sidecar WAV format differs from the frozen PCM contract",
            poison=True,
        )
    frames = len(data_chunk) // block_align
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav_file:
            decoded = wav_file.readframes(frames)
            exhausted = wav_file.readframes(1)
    except (wave.Error, EOFError) as error:
        raise SidecarRuntimeError(
            "AUDIO_FORMAT_INVALID", "Sidecar WAV cannot be decoded", poison=True
        ) from error
    if len(decoded) != len(data_chunk) or exhausted:
        raise SidecarRuntimeError(
            "AUDIO_FRAME_COUNT_MISMATCH",
            "Sidecar WAV decoded frame count differs from the data chunk",
            poison=True,
        )
    return sample_rate, channels, sample_width


def _multipart_body(request: SynthesisRequest, requested_model: str) -> tuple[bytes, str]:
    reference = request.reference_audio
    if reference is None:
        raise SidecarRuntimeError("REFERENCE_REQUIRED", "reference audio is required")
    if len(reference.audio_bytes) > MAX_REFERENCE_BYTES:
        raise SidecarRuntimeError("REFERENCE_SIZE_INVALID", "reference audio exceeds limit")
    boundary = f"moss_{secrets.token_hex(20)}"
    metadata = canonical_sidecar_synthesis_metadata(
        request_id=request.request_id,
        scope=request.scope,
        requested_model_fingerprint_sha256=requested_model,
        text=request.text,
        voice=request.voice,
        seed=request.seed,
        sample_mode=request.sample_mode,
        max_new_frames=request.max_new_frames,
        decode_parameters=request.decode_parameters,
        reference_content_type=reference.content_type,
        reference_actual_sha256=reference.actual_sha256,
        reference_size_bytes=len(reference.audio_bytes),
    )
    marker = f"--{boundary}".encode("ascii")
    body = b"\r\n".join(
        [
            marker,
            b'Content-Disposition: form-data; name="metadata"',
            b"Content-Type: application/json",
            b"",
            metadata,
            marker,
            b'Content-Disposition: form-data; name="reference_audio"',
            f"Content-Type: {reference.content_type}".encode("ascii"),
            b"",
            reference.audio_bytes,
            marker + b"--",
            b"",
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


class SidecarMossNanoTTSAdapter(MossNanoTTSAdapter):
    def __init__(
        self,
        config: SidecarRuntimeConfig,
        *,
        lifecycle: SidecarLifecycle | None = None,
        bootstrap_token: str | None = None,
    ):
        self.config = config
        self._bootstrap_token = (
            read_secret_token(config.token_file)
            if bootstrap_token is None
            else bootstrap_token
        )
        self._worker_token: str | None = None
        self._lease_generation: int | None = None
        self._capabilities = (
            replace(MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES, is_test_double=True)
            if config.allow_test_backend
            else MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES
        )
        if lifecycle is None:
            if not config.allow_test_backend:
                raise ContractError(
                    "production Sidecar adapter requires a managed lifecycle"
                )
            lifecycle = NoopSidecarLifecycle()
        if not config.allow_test_backend and isinstance(lifecycle, NoopSidecarLifecycle):
            raise ContractError("production Sidecar adapter rejects a no-op lifecycle")
        self._lifecycle = lifecycle
        self._expected_fingerprint = (
            EXPECTED_TEST_MODEL_FINGERPRINT
            if config.allow_test_backend
            else EXPECTED_PRODUCTION_MODEL_FINGERPRINT
        )
        self._expected_fingerprint_sha256 = (
            EXPECTED_TEST_MODEL_FINGERPRINT_SHA256
            if config.allow_test_backend
            else EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
        )
        self._fingerprint: ModelFingerprint | None = None
        self._fingerprint_sha256: str | None = None
        self._generation: int | None = None
        self._last_model_activity_at: float | None = None
        self._on_demand_warmup_enabled = False
        self._control_lock = asyncio.Lock()
        self._lease_lock = asyncio.Lock()
        self._synthesis_lock = asyncio.Lock()
        self._restart_lock = asyncio.Lock()

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    @property
    def worker_generation(self) -> int | None:
        return self._generation

    @property
    def lease_generation(self) -> int | None:
        return self._lease_generation

    @property
    def worker_lease_active(self) -> bool:
        return self._worker_token is not None and self._lease_generation is not None

    @property
    def expected_model_fingerprint(self) -> ModelFingerprint:
        """Return the frozen requested identity without claiming it is loaded."""

        return self._expected_fingerprint

    @property
    def expected_model_fingerprint_sha256(self) -> str:
        return self._expected_fingerprint_sha256

    @property
    def model_loaded(self) -> bool:
        return (
            self._fingerprint is not None
            and self._fingerprint_sha256 is not None
            and self._generation is not None
        )

    def enable_on_demand_warmup(self) -> None:
        """Allow the lifecycle owner to make the next synthesis load the model."""

        self._on_demand_warmup_enabled = True

    def _headers(
        self,
        *,
        authentication: Literal["control", "worker"] = "worker",
        worker_token: str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, str]:
        if authentication == "control":
            headers = {
                TOKEN_HEADER: self._bootstrap_token,
                VERSION_HEADER: PROTOCOL_VERSION,
            }
        else:
            active_worker_token = worker_token or self._worker_token
            if active_worker_token is None:
                raise SidecarRuntimeError(
                    "WORKER_LEASE_INACTIVE",
                    "Sidecar worker lease is inactive",
                )
            headers = {
                WORKER_TOKEN_HEADER: active_worker_token,
                VERSION_HEADER: PROTOCOL_VERSION,
            }
        if body is not None:
            headers["Content-Length"] = str(len(body))
            headers["Content-Type"] = content_type or "application/json"
        return headers

    def _connection(self) -> HTTPConnection:
        return HTTPConnection(self.config.host, self.config.port, timeout=float(self.config.timeout_seconds))

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        *,
        authentication: Literal["control", "worker"] = "worker",
        worker_token: str | None = None,
        expected_request_id: UUID | None = None,
        expected_generation: int | None = None,
        expected_model: str | None = None,
        expected_error_generation: int | None = None,
        expected_error_model: str | None = None,
    ) -> tuple[int, Mapping[str, str], dict[str, object]]:
        body = _canonical_bytes(payload) if payload is not None else None
        connection = self._connection()
        try:
            connection.request(
                method,
                path,
                body=body,
                headers=self._headers(
                    authentication=authentication,
                    worker_token=worker_token,
                    body=body,
                    content_type="application/json" if body is not None else None,
                ),
            )
            response = connection.getresponse()
            row = _response_json(response)
            headers = _response_headers(response)
            if (
                _header(headers, VERSION_HEADER) != PROTOCOL_VERSION
                or row.get("protocol_version") != PROTOCOL_VERSION
            ):
                raise SidecarRuntimeError(
                    "PROTOCOL_VERSION_MISMATCH",
                    "Sidecar protocol version mismatch",
                    poison=True,
                )
            raw_generation = _header(headers, "X-MOSS-Worker-Generation")
            if (
                raw_generation is None
                or not raw_generation.isdigit()
                or int(raw_generation) <= 0
            ):
                raise SidecarRuntimeError(
                    "WORKER_GENERATION_MISSING",
                    "Sidecar generation header is invalid",
                    poison=True,
                )
            generation = int(raw_generation)
            if expected_generation is not None and generation != expected_generation:
                raise SidecarRuntimeError(
                    "WORKER_GENERATION_MISMATCH",
                    "Sidecar response came from a different worker generation",
                    poison=True,
                )
            if expected_request_id is not None and (
                row.get("request_id") != str(expected_request_id)
                or _header(headers, "X-MOSS-Request-ID") != str(expected_request_id)
            ):
                raise SidecarRuntimeError(
                    "REQUEST_IDENTITY_MISMATCH",
                    "Sidecar response request identity mismatch",
                    poison=True,
                )
            if expected_request_id is None and path == "/v1/health" and (
                row.get("request_id") is not None
                or _header(headers, "X-MOSS-Request-ID") is not None
            ):
                raise SidecarRuntimeError(
                    "REQUEST_IDENTITY_MISMATCH",
                    "Sidecar health response unexpectedly carries a request identity",
                    poison=True,
                )
            if expected_model is not None and (
                response.status < 400
                and _header(
                    headers,
                    "X-MOSS-Actual-Model-Fingerprint-SHA256",
                )
                != expected_model
            ):
                raise SidecarRuntimeError(
                    "MODEL_FINGERPRINT_MISMATCH",
                    "Sidecar response model identity mismatch",
                    poison=True,
                )
            if response.status >= 400:
                if (
                    expected_error_generation is not None
                    and generation != expected_error_generation
                ):
                    raise SidecarRuntimeError(
                        "WORKER_GENERATION_MISMATCH",
                        "Sidecar error came from a different worker generation",
                        poison=True,
                    )
                raw_error = row.get("error")
                raw_error_code = (
                    raw_error.get("code") if isinstance(raw_error, dict) else None
                )
                if (
                    expected_error_model is not None
                    and raw_error_code != "WORKER_LEASE_INVALID"
                    and _header(
                        headers,
                        "X-MOSS-Actual-Model-Fingerprint-SHA256",
                    )
                    != expected_error_model
                ):
                    raise SidecarRuntimeError(
                        "MODEL_FINGERPRINT_MISMATCH",
                        "Sidecar error model identity mismatch",
                        poison=True,
                    )
                error = row.get("error")
                if (
                    frozenset(row) != {"protocol_version", "request_id", "error"}
                    or not isinstance(error, dict)
                    or frozenset(error)
                    != {"code", "retryable", "message_redacted"}
                    or type(error.get("retryable")) is not bool
                    or not isinstance(error.get("message_redacted"), str)
                    or not (1 <= len(str(error["message_redacted"])) <= 256)
                ):
                    raise SidecarRuntimeError(
                        "ERROR_PAYLOAD_INVALID",
                        "Sidecar error payload is invalid",
                        poison=True,
                    )
                code = error.get("code") if isinstance(error, dict) else None
                if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
                    raise SidecarRuntimeError(
                        "ERROR_PAYLOAD_INVALID",
                        "Sidecar error payload is invalid",
                        poison=True,
                    )
                raise SidecarRuntimeError(
                    code,
                    "Sidecar rejected request",
                    poison=code
                    in {
                        "SIDECAR_POISONED",
                        "BACKEND_FAILURE",
                        "MODEL_FINGERPRINT_MISMATCH",
                    },
                )
            return response.status, headers, row
        finally:
            connection.close()

    def _clear_identity(self) -> None:
        self._fingerprint = None
        self._fingerprint_sha256 = None
        self._generation = None
        self._last_model_activity_at = None

    async def _poison_and_restart(self, error: SidecarRuntimeError) -> None:
        previous_generation = self._generation
        self._on_demand_warmup_enabled = False
        self._clear_identity()
        self._worker_token = None
        self._lease_generation = None
        async with self._restart_lock:
            self._clear_identity()
            await self._lifecycle.restart_after_poison(
                error.code,
                previous_generation=previous_generation,
            )
            try:
                await self.activate()
            except (SidecarRuntimeError, OSError, TimeoutError) as restart_error:
                raise error from restart_error

    def _consume_worker(
        self,
        worker: object,
        headers: Mapping[str, str],
        *,
        allow_active_count: bool,
    ) -> int:
        if not isinstance(worker, dict):
            raise SidecarRuntimeError(
                "WORKER_IDENTITY_INVALID", "Sidecar worker identity is invalid", poison=True
            )
        expected_worker_keys = {"pid", "generation", "test_backend"}
        if allow_active_count:
            expected_worker_keys.add("active_request_count")
        if frozenset(worker) != expected_worker_keys:
            raise SidecarRuntimeError(
                "WORKER_IDENTITY_INVALID",
                "Sidecar worker identity shape is invalid",
                poison=True,
            )
        generation = worker.get("generation")
        test_backend = worker.get("test_backend")
        pid = worker.get("pid")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation <= 0
            or type(test_backend) is not bool
            or isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
        ):
            raise SidecarRuntimeError(
                "WORKER_IDENTITY_INVALID", "Sidecar worker identity is invalid", poison=True
            )
        if allow_active_count:
            active_count = worker.get("active_request_count")
            if (
                isinstance(active_count, bool)
                or not isinstance(active_count, int)
                or active_count < 0
            ):
                raise SidecarRuntimeError(
                    "WORKER_IDENTITY_INVALID",
                    "Sidecar active request count is invalid",
                    poison=True,
                )
        if test_backend != self.config.allow_test_backend:
            raise SidecarRuntimeError(
                "TEST_BACKEND_POLICY_MISMATCH",
                "Sidecar backend class violates adapter policy",
                poison=True,
            )
        if _header(headers, "X-MOSS-Worker-Generation") != str(generation):
            raise SidecarRuntimeError(
                "WORKER_GENERATION_MISMATCH",
                "Sidecar generation evidence mismatch",
                poison=True,
            )
        return generation

    def _consume_lease(
        self,
        lease: object,
        *,
        expected_active: bool,
        expected_generation: int | None = None,
    ) -> int:
        if not isinstance(lease, dict) or frozenset(lease) != {
            "active",
            "generation",
        }:
            raise SidecarRuntimeError(
                "WORKER_LEASE_RESPONSE_INVALID",
                "Sidecar worker lease response is invalid",
                poison=True,
            )
        active = lease.get("active")
        generation = lease.get("generation")
        if (
            type(active) is not bool
            or active is not expected_active
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 0
            or (expected_active and generation <= 0)
            or (
                expected_generation is not None
                and generation != expected_generation
            )
        ):
            raise SidecarRuntimeError(
                "WORKER_LEASE_RESPONSE_INVALID",
                "Sidecar worker lease response is invalid",
                poison=True,
            )
        return generation

    def _consume_ready(
        self,
        row: Mapping[str, object],
        headers: Mapping[str, str],
        *,
        expected_request_id: UUID | None = None,
    ) -> None:
        expected = {
            "protocol_version",
            "status",
            "ready",
            "capabilities_sha256",
            "model_fingerprint",
            "model_fingerprint_sha256",
            "lease",
            "worker",
        }
        if expected_request_id is not None:
            expected.add("request_id")
        if frozenset(row) != expected:
            raise SidecarRuntimeError(
                "HEALTH_RESPONSE_INVALID",
                "Sidecar ready response shape is invalid",
                poison=True,
            )
        if (
            row.get("protocol_version") != PROTOCOL_VERSION
            or row.get("ready") is not True
            or row.get("status") != "ready"
            or row.get("capabilities_sha256") != CAPABILITIES_SHA256
            or (
                expected_request_id is not None
                and row.get("request_id") != str(expected_request_id)
            )
        ):
            raise SidecarRuntimeError(
                "SIDECAR_NOT_READY", "Sidecar is not model-ready", poison=True
            )
        generation = self._consume_worker(
            row.get("worker"),
            headers,
            allow_active_count=expected_request_id is None,
        )
        self._consume_lease(
            row.get("lease"),
            expected_active=True,
            expected_generation=self._lease_generation,
        )
        fingerprint = _parse_model_fingerprint(row.get("model_fingerprint"))
        digest = model_fingerprint_sha256(fingerprint)
        if (
            fingerprint != self._expected_fingerprint
            or digest != self._expected_fingerprint_sha256
            or row.get("model_fingerprint_sha256") != digest
            or _header(headers, "X-MOSS-Actual-Model-Fingerprint-SHA256") != digest
        ):
            raise SidecarRuntimeError(
                "MODEL_FINGERPRINT_MISMATCH",
                "Sidecar model fingerprint differs from the frozen identity",
                poison=True,
            )
        if self._generation is not None and self._generation != generation:
            self._clear_identity()
        self._generation = generation
        self._fingerprint = fingerprint
        self._fingerprint_sha256 = digest

    def _consume_nonready(
        self,
        row: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> AdapterHealthStatus:
        if frozenset(row) != {
            "protocol_version",
            "status",
            "ready",
            "capabilities_sha256",
            "model_fingerprint",
            "model_fingerprint_sha256",
            "lease",
            "worker",
        }:
            raise SidecarRuntimeError(
                "HEALTH_RESPONSE_INVALID",
                "Sidecar non-ready response shape is invalid",
                poison=True,
            )
        if (
            row.get("protocol_version") != PROTOCOL_VERSION
            or row.get("ready") is not False
            or row.get("status") not in {"unloaded", "warming", "draining"}
            or row.get("capabilities_sha256") != CAPABILITIES_SHA256
            or row.get("model_fingerprint") is not None
            or row.get("model_fingerprint_sha256") is not None
            or _header(headers, "X-MOSS-Actual-Model-Fingerprint-SHA256") is not None
        ):
            raise SidecarRuntimeError(
                "SIDECAR_NOT_READY",
                "Sidecar non-ready identity is inconsistent",
                poison=True,
            )
        self._consume_worker(row.get("worker"), headers, allow_active_count=True)
        self._consume_lease(
            row.get("lease"),
            expected_active=True,
            expected_generation=self._lease_generation,
        )
        self._clear_identity()
        return AdapterHealthStatus.DEGRADED

    async def activate(self) -> int:
        """Acquire one short-lived worker token using the bootstrap secret."""

        async with self._lease_lock:
            if self._worker_token is not None and self._lease_generation is not None:
                return self._lease_generation
            request_id = uuid4()
            status_code, headers, row = await asyncio.to_thread(
                self._request_json,
                "POST",
                "/v1/lease/acquire",
                {"request_id": str(request_id)},
                authentication="control",
                expected_request_id=request_id,
            )
            if status_code != 200 or frozenset(row) != {
                "protocol_version",
                "request_id",
                "status",
                "worker_token",
                "lease_ttl_seconds",
                "lease_generation",
                "worker",
            }:
                raise SidecarRuntimeError(
                    "WORKER_LEASE_ACQUIRE_INVALID",
                    "Sidecar worker lease acquisition response is invalid",
                    poison=True,
                )
            worker_generation = self._consume_worker(
                row.get("worker"),
                headers,
                allow_active_count=False,
            )
            worker_token = row.get("worker_token")
            lease_generation = row.get("lease_generation")
            if (
                row.get("status") != "active"
                or row.get("lease_ttl_seconds") != WORKER_LEASE_TTL_SECONDS
                or not isinstance(worker_token, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", worker_token) is None
                or isinstance(lease_generation, bool)
                or not isinstance(lease_generation, int)
                or lease_generation <= 0
            ):
                raise SidecarRuntimeError(
                    "WORKER_LEASE_ACQUIRE_INVALID",
                    "Sidecar worker lease acquisition response is invalid",
                    poison=True,
                )
            self._clear_identity()
            self._worker_token = worker_token
            self._lease_generation = lease_generation
            self._generation = worker_generation
            return lease_generation

    async def renew_lease(self) -> int:
        """Renew the active lease; never silently reacquire an invalid token."""

        async with self._lease_lock:
            worker_token = self._worker_token
            lease_generation = self._lease_generation
            if worker_token is None or lease_generation is None:
                raise SidecarRuntimeError(
                    "WORKER_LEASE_INACTIVE",
                    "Sidecar worker lease is inactive",
                )
            request_id = uuid4()
            status_code, headers, row = await asyncio.to_thread(
                self._request_json,
                "POST",
                "/v1/lease/renew",
                {"request_id": str(request_id)},
                worker_token=worker_token,
                expected_request_id=request_id,
                expected_generation=self._generation,
                expected_model=self._fingerprint_sha256,
            )
            if status_code != 200 or frozenset(row) != {
                "protocol_version",
                "request_id",
                "status",
                "lease_ttl_seconds",
                "lease_generation",
                "worker",
            }:
                raise SidecarRuntimeError(
                    "WORKER_LEASE_RENEW_INVALID",
                    "Sidecar worker lease renewal response is invalid",
                    poison=True,
                )
            self._consume_worker(
                row.get("worker"),
                headers,
                allow_active_count=False,
            )
            if (
                row.get("status") != "renewed"
                or row.get("lease_ttl_seconds") != WORKER_LEASE_TTL_SECONDS
                or row.get("lease_generation") != lease_generation
            ):
                raise SidecarRuntimeError(
                    "WORKER_LEASE_RENEW_INVALID",
                    "Sidecar worker lease renewal response is invalid",
                    poison=True,
                )
            return lease_generation

    def _consume_control_health(
        self,
        row: Mapping[str, object],
        headers: Mapping[str, str],
        *,
        expected_lease_generation: int | None,
    ) -> bool:
        if frozenset(row) != {
            "protocol_version",
            "status",
            "ready",
            "capabilities_sha256",
            "model_fingerprint",
            "model_fingerprint_sha256",
            "lease",
            "worker",
        }:
            raise SidecarRuntimeError(
                "CONTROL_HEALTH_RESPONSE_INVALID",
                "Sidecar control health response is invalid",
                poison=True,
            )
        self._consume_worker(row.get("worker"), headers, allow_active_count=True)
        lease_generation = self._consume_lease(
            row.get("lease"),
            expected_active=False,
            expected_generation=expected_lease_generation,
        )
        del lease_generation
        worker = row.get("worker")
        active_count = worker.get("active_request_count") if isinstance(worker, dict) else None
        status = row.get("status")
        if (
            row.get("protocol_version") != PROTOCOL_VERSION
            or row.get("ready") is not False
            or status not in {"draining", "unloaded"}
            or row.get("capabilities_sha256") != CAPABILITIES_SHA256
            or row.get("model_fingerprint") is not None
            or row.get("model_fingerprint_sha256") is not None
            or _header(headers, "X-MOSS-Actual-Model-Fingerprint-SHA256") is not None
        ):
            raise SidecarRuntimeError(
                "CONTROL_HEALTH_RESPONSE_INVALID",
                "Sidecar control health response is invalid",
                poison=True,
            )
        return status == "unloaded" and active_count == 0

    async def _wait_for_unloaded(
        self,
        *,
        expected_lease_generation: int | None,
    ) -> None:
        deadline = (
            asyncio.get_running_loop().time()
            + WORKER_LEASE_DEACTIVATE_TIMEOUT_SECONDS
        )
        while asyncio.get_running_loop().time() < deadline:
            try:
                status_code, headers, row = await asyncio.to_thread(
                    self._request_json,
                    "GET",
                    "/v1/health",
                    authentication="control",
                )
            except (OSError, TimeoutError):
                await asyncio.sleep(0.1)
                continue
            if status_code != 200:
                raise SidecarRuntimeError(
                    "CONTROL_HEALTH_STATUS_INVALID",
                    "Sidecar control health returned an invalid status",
                    poison=True,
                )
            if self._consume_control_health(
                row,
                headers,
                expected_lease_generation=expected_lease_generation,
            ):
                return
            await asyncio.sleep(0.1)
        raise SidecarRuntimeError(
            "WORKER_LEASE_DRAIN_TIMEOUT",
            "Sidecar worker lease did not become inert in time",
            poison=True,
        )

    async def deactivate(self) -> None:
        """Fence the worker token first, then prove the Sidecar is unloaded."""

        async with self._lease_lock:
            worker_token = self._worker_token
            lease_generation = self._lease_generation
            self._worker_token = None
            self._lease_generation = None
            self._clear_identity()
            if worker_token is None or lease_generation is None:
                return
            request_id = uuid4()
            release_accepted = False
            try:
                status_code, headers, row = await asyncio.to_thread(
                    self._request_json,
                    "POST",
                    "/v1/lease/release",
                    {"request_id": str(request_id)},
                    worker_token=worker_token,
                    expected_request_id=request_id,
                )
                if status_code != 202 or frozenset(row) != {
                    "protocol_version",
                    "request_id",
                    "status",
                    "lease_generation",
                    "worker",
                }:
                    raise SidecarRuntimeError(
                        "WORKER_LEASE_RELEASE_INVALID",
                        "Sidecar worker lease release response is invalid",
                        poison=True,
                    )
                self._consume_worker(
                    row.get("worker"),
                    headers,
                    allow_active_count=False,
                )
                if (
                    row.get("status") != "release_requested"
                    or row.get("lease_generation") != lease_generation
                ):
                    raise SidecarRuntimeError(
                        "WORKER_LEASE_RELEASE_INVALID",
                        "Sidecar worker lease release response is invalid",
                        poison=True,
                    )
                release_accepted = True
                await self._wait_for_unloaded(
                    expected_lease_generation=lease_generation,
                )
            except (SidecarRuntimeError, OSError, TimeoutError) as error:
                # The release may have reached the Sidecar even when its HTTP
                # response was lost.  Accept only authenticated control-health
                # proof for that exact fenced lease before forcing a restart.
                if not release_accepted:
                    try:
                        await self._wait_for_unloaded(
                            expected_lease_generation=lease_generation,
                        )
                        return
                    except (SidecarRuntimeError, OSError, TimeoutError):
                        pass
                wrapped = (
                    error
                    if isinstance(error, SidecarRuntimeError)
                    else SidecarRuntimeError(
                        "WORKER_LEASE_RELEASE_FAILED",
                        "Sidecar worker lease release failed",
                        poison=True,
                    )
                )
                await self._lifecycle.restart_after_poison(
                    wrapped.code,
                    previous_generation=None,
                )
                await self._wait_for_unloaded(expected_lease_generation=None)

    async def health(self) -> AdapterHealth:
        if self._worker_token is None or self._lease_generation is None:
            self._clear_identity()
            return AdapterHealth(
                AdapterHealthStatus.UNAVAILABLE,
                CAPABILITIES_SHA256,
                None,
                "WORKER_LEASE_INACTIVE",
            )
        async with self._control_lock:
            try:
                status_code, headers, row = await asyncio.to_thread(
                    self._request_json,
                    "GET",
                    "/v1/health",
                    expected_error_generation=self._generation,
                    expected_error_model=self._fingerprint_sha256,
                )
                if status_code != 200:
                    raise SidecarRuntimeError(
                        "HEALTH_STATUS_INVALID",
                        "Sidecar health returned an invalid success status",
                        poison=True,
                    )
                if row.get("ready") is True:
                    self._consume_ready(row, headers)
                    if self._last_model_activity_at is None:
                        self._last_model_activity_at = (
                            asyncio.get_running_loop().time()
                        )
                    return AdapterHealth(
                        AdapterHealthStatus.HEALTHY,
                        CAPABILITIES_SHA256,
                        self._fingerprint_sha256,
                    )
                status = self._consume_nonready(row, headers)
                return AdapterHealth(status, CAPABILITIES_SHA256, None)
            except SidecarRuntimeError as error:
                self._clear_identity()
                if error.poison:
                    await self._poison_and_restart(error)
                return AdapterHealth(
                    AdapterHealthStatus.UNAVAILABLE,
                    CAPABILITIES_SHA256,
                    None,
                    error.code,
                )
            except (OSError, TimeoutError):
                error = SidecarRuntimeError(
                    "SIDECAR_TRANSPORT_FAILURE", "Sidecar transport failed", poison=True
                )
                await self._poison_and_restart(error)
                return AdapterHealth(
                    AdapterHealthStatus.UNAVAILABLE,
                    CAPABILITIES_SHA256,
                    None,
                    error.code,
                )

    async def observe_validation_metrics(self) -> SidecarValidationMetrics:
        """Read the private health endpoint and return only fixed safe metrics."""

        if self._worker_token is None or self._lease_generation is None:
            raise SidecarRuntimeError(
                "WORKER_LEASE_INACTIVE",
                "Sidecar validation observation is unavailable",
            )
        async with self._control_lock:
            try:
                status_code, headers, row = await asyncio.to_thread(
                    self._request_json,
                    "GET",
                    "/v1/health",
                    expected_error_generation=self._generation,
                    expected_error_model=self._fingerprint_sha256,
                )
                if status_code != 200:
                    raise SidecarRuntimeError(
                        "HEALTH_STATUS_INVALID",
                        "Sidecar health returned an invalid success status",
                        poison=True,
                    )
                ready = row.get("ready") is True
                if ready:
                    self._consume_ready(row, headers)
                else:
                    self._consume_nonready(row, headers)
                worker = row.get("worker")
                active_syntheses = (
                    worker.get("active_request_count")
                    if isinstance(worker, dict)
                    else None
                )
                if (
                    isinstance(active_syntheses, bool)
                    or not isinstance(active_syntheses, int)
                ):
                    raise SidecarRuntimeError(
                        "WORKER_IDENTITY_INVALID",
                        "Sidecar active request count is invalid",
                        poison=True,
                    )
                return SidecarValidationMetrics(
                    model_ready=ready,
                    worker_ready=True,
                    active_syntheses=active_syntheses,
                )
            except (SidecarRuntimeError, ContractError) as error:
                self._clear_identity()
                if isinstance(error, SidecarRuntimeError) and error.poison:
                    await self._poison_and_restart(error)
                raise SidecarRuntimeError(
                    "VALIDATION_OBSERVATION_UNAVAILABLE",
                    "Sidecar validation observation is unavailable",
                ) from error
            except (OSError, TimeoutError) as error:
                wrapped = SidecarRuntimeError(
                    "SIDECAR_TRANSPORT_FAILURE",
                    "Sidecar transport failed",
                    poison=True,
                )
                await self._poison_and_restart(wrapped)
                raise SidecarRuntimeError(
                    "VALIDATION_OBSERVATION_UNAVAILABLE",
                    "Sidecar validation observation is unavailable",
                ) from error

    async def model_fingerprint(self) -> ModelFingerprint | None:
        if self._fingerprint is None:
            await self.health()
        return self._fingerprint

    async def warmup(self) -> AdapterHealth:
        if self._worker_token is None or self._lease_generation is None:
            self._clear_identity()
            return AdapterHealth(
                AdapterHealthStatus.UNAVAILABLE,
                CAPABILITIES_SHA256,
                None,
                "WORKER_LEASE_INACTIVE",
            )
        async with self._control_lock:
            request_id = uuid4()
            try:
                status_code, headers, row = await asyncio.to_thread(
                    self._request_json,
                    "POST",
                    "/v1/warmup",
                    {"request_id": str(request_id)},
                    expected_request_id=request_id,
                    expected_error_generation=self._generation,
                    expected_error_model=self._fingerprint_sha256,
                )
                if status_code != 200:
                    raise SidecarRuntimeError(
                        "WARMUP_STATUS_INVALID",
                        "Sidecar warmup returned an invalid success status",
                        poison=True,
                    )
                self._consume_ready(
                    row, headers, expected_request_id=request_id
                )
                self._last_model_activity_at = asyncio.get_running_loop().time()
                return AdapterHealth(
                    AdapterHealthStatus.HEALTHY,
                    CAPABILITIES_SHA256,
                    self._fingerprint_sha256,
                )
            except SidecarRuntimeError as error:
                self._clear_identity()
                if error.poison:
                    await self._poison_and_restart(error)
                return AdapterHealth(
                    AdapterHealthStatus.UNAVAILABLE,
                    CAPABILITIES_SHA256,
                    None,
                    error.code,
                )
            except (OSError, TimeoutError):
                error = SidecarRuntimeError(
                    "SIDECAR_TRANSPORT_FAILURE", "Sidecar transport failed", poison=True
                )
                await self._poison_and_restart(error)
                return AdapterHealth(
                    AdapterHealthStatus.UNAVAILABLE,
                    CAPABILITIES_SHA256,
                    None,
                    error.code,
                )

    def _synthesize_sync(
        self,
        request: SynthesisRequest,
        fingerprint: ModelFingerprint,
        fingerprint_sha256: str,
        generation: int,
    ) -> SynthesisResult:
        if request.reference_audio is None:
            body = canonical_sidecar_synthesis_metadata(
                request_id=request.request_id,
                scope=request.scope,
                requested_model_fingerprint_sha256=fingerprint_sha256,
                text=request.text,
                voice=request.voice,
                seed=request.seed,
                sample_mode=request.sample_mode,
                max_new_frames=request.max_new_frames,
                decode_parameters=request.decode_parameters,
            )
            content_type = "application/json"
        else:
            body, content_type = _multipart_body(request, fingerprint_sha256)
        connection = self._connection()
        try:
            connection.request(
                "POST",
                "/v1/synthesize",
                body=body,
                headers=self._headers(body=body, content_type=content_type),
            )
            response = connection.getresponse()
            if response.status != 200:
                row = _response_json(response)
                headers = _response_headers(response)
                error = row.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                expected_error_model = (
                    None if code == "WORKER_LEASE_INVALID" else fingerprint_sha256
                )
                if (
                    _header(headers, VERSION_HEADER) != PROTOCOL_VERSION
                    or row.get("protocol_version") != PROTOCOL_VERSION
                    or row.get("request_id") != str(request.request_id)
                    or _header(headers, "X-MOSS-Request-ID")
                    != str(request.request_id)
                    or _header(headers, "X-MOSS-Worker-Generation")
                    != str(generation)
                    or _header(
                        headers, "X-MOSS-Actual-Model-Fingerprint-SHA256"
                    )
                    != expected_error_model
                    or frozenset(row)
                    != {"protocol_version", "request_id", "error"}
                    or not isinstance(error, dict)
                    or frozenset(error)
                    != {"code", "retryable", "message_redacted"}
                    or type(error.get("retryable")) is not bool
                    or not isinstance(error.get("message_redacted"), str)
                    or not (1 <= len(str(error["message_redacted"])) <= 256)
                    or not isinstance(code, str)
                    or re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code) is None
                ):
                    raise SidecarRuntimeError(
                        "SYNTHESIS_ERROR_IDENTITY_MISMATCH",
                        "Sidecar synthesis error evidence is invalid",
                        poison=True,
                    )
                raise SidecarRuntimeError(
                    code,
                    "Sidecar synthesis failed",
                    poison=code
                    in {
                        "SIDECAR_POISONED",
                        "BACKEND_FAILURE",
                        "MODEL_FINGERPRINT_MISMATCH",
                    },
                )
            headers = _response_headers(response)
            if response.getheader("Content-Type") != "audio/wav":
                raise SidecarRuntimeError(
                    "AUDIO_CONTENT_TYPE_INVALID",
                    "Sidecar audio content type is invalid",
                    poison=True,
                )
            raw_length = response.getheader("Content-Length")
            if (
                raw_length is None
                or not raw_length.isdigit()
                or not (1 <= int(raw_length) <= MAX_AUDIO_BYTES)
            ):
                raise SidecarRuntimeError(
                    "AUDIO_SIZE_INVALID",
                    "Sidecar audio size is invalid",
                    poison=True,
                )
            payload = response.read(int(raw_length) + 1)
            if len(payload) != int(raw_length):
                raise SidecarRuntimeError(
                    "AUDIO_SIZE_MISMATCH",
                    "Sidecar audio body length mismatch",
                    poison=True,
                )
            digest = hashlib.sha256(payload).hexdigest()
            if (
                _header(headers, VERSION_HEADER) != PROTOCOL_VERSION
                or _header(headers, "X-MOSS-Request-ID")
                != str(request.request_id)
                or _header(headers, "X-MOSS-Audio-SHA256") != digest
                or _header(headers, "X-MOSS-Worker-Generation") != str(generation)
                or _header(
                    headers, "X-MOSS-Actual-Model-Fingerprint-SHA256"
                )
                != fingerprint_sha256
            ):
                raise SidecarRuntimeError(
                    "SYNTHESIS_EVIDENCE_MISMATCH",
                    "Sidecar synthesis evidence mismatch",
                    poison=True,
                )
            sample_rate, channels, sample_width = _validate_complete_pcm_wav(payload)
            header_format = (
                _header(headers, "X-MOSS-Sample-Rate"),
                _header(headers, "X-MOSS-Channels"),
                _header(headers, "X-MOSS-Sample-Width"),
            )
            if header_format != (
                str(sample_rate),
                str(channels),
                str(sample_width),
            ):
                raise SidecarRuntimeError(
                    "AUDIO_FORMAT_DRIFT",
                    "Sidecar WAV header evidence differs from decoded bytes",
                    poison=True,
                )
            return SynthesisResult(
                request_id=request.request_id,
                audio_bytes=payload,
                actual_output_sha256=digest,
                sample_rate_hz=sample_rate,
                channels=channels,
                sample_width_bytes=sample_width,
                model_fingerprint=fingerprint,
                worker_generation=generation,
            )
        finally:
            connection.close()

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        request.scope.ensure_fixed_local()
        async with self._synthesis_lock:
            if not self.model_loaded and self._on_demand_warmup_enabled:
                warmed = await self.warmup()
                if warmed.status is not AdapterHealthStatus.HEALTHY:
                    raise SidecarRuntimeError(
                        warmed.reason_code or "SIDECAR_WARMUP_UNAVAILABLE",
                        "Sidecar on-demand warmup is unavailable",
                    )
            fingerprint = self._fingerprint
            fingerprint_sha256 = self._fingerprint_sha256
            generation = self._generation
            if (
                fingerprint is None
                or fingerprint_sha256 is None
                or generation is None
            ):
                raise SidecarRuntimeError("MODEL_NOT_READY", "Sidecar warmup is required")
            worker = asyncio.create_task(
                asyncio.to_thread(
                    self._synthesize_sync,
                    request,
                    fingerprint,
                    fingerprint_sha256,
                    generation,
                )
            )
            try:
                result = await asyncio.shield(worker)
                if (
                    self._generation != generation
                    or self._fingerprint_sha256 != fingerprint_sha256
                    or self._fingerprint != fingerprint
                ):
                    raise SidecarRuntimeError(
                        "STALE_SYNTHESIS_GENERATION",
                        "Sidecar identity changed while synthesis was in flight",
                        poison=True,
                    )
                self._last_model_activity_at = asyncio.get_running_loop().time()
                return result
            except asyncio.CancelledError:
                # ``to_thread`` cannot be stopped by coroutine cancellation.
                # Drain it while still owning the inference lock, then poison
                # the generation before another request can enter.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except BaseException:
                        break
                if worker.done():
                    try:
                        worker.result()
                    except BaseException:
                        pass
                cancelled = SidecarRuntimeError(
                    "SYNTHESIS_CALL_CANCELLED",
                    "Sidecar synthesis caller was cancelled",
                    poison=True,
                )
                await self._poison_and_restart(cancelled)
                raise
            except SidecarRuntimeError as error:
                if error.poison:
                    await self._poison_and_restart(error)
                raise
            except (OSError, TimeoutError) as error:
                wrapped = SidecarRuntimeError("SIDECAR_TRANSPORT_FAILURE", "Sidecar transport failed", poison=True)
                await self._poison_and_restart(wrapped)
                raise wrapped from error

    async def release_model_if_idle(
        self,
        idle_seconds: float,
        *,
        now: float | None = None,
    ) -> bool:
        """Unload one idle model while keeping this adapter authoritative.

        The existing lease release path first proves that the Sidecar is
        unloaded.  Its supervised process is replaced to return native allocator
        pages, then a fresh cold lease is acquired without rebuilding the
        production worker.
        """

        if (
            isinstance(idle_seconds, bool)
            or not isinstance(idle_seconds, (int, float))
            or idle_seconds <= 0
        ):
            raise ContractError("idle unload duration must be positive")
        if self._synthesis_lock.locked() or not self.model_loaded:
            return False
        current = asyncio.get_running_loop().time() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ContractError("idle unload clock must be numeric")
        last_activity = self._last_model_activity_at
        if last_activity is None or current - last_activity < float(idle_seconds):
            return False

        # There is no await between the lock observation above and acquisition,
        # so another coroutine cannot enter synthesis on this event loop first.
        async with self._synthesis_lock:
            last_activity = self._last_model_activity_at
            current = asyncio.get_running_loop().time() if now is None else now
            if (
                not self.model_loaded
                or last_activity is None
                or current - last_activity < float(idle_seconds)
            ):
                return False
            previous_generation = self._generation
            await self.deactivate()
            # ONNX Runtime may retain native allocator arenas even after all
            # sessions are dropped.  Replace the already-inert Sidecar process
            # so those pages are actually returned to the host.
            await self._lifecycle.restart_after_poison(
                "IDLE_MODEL_RELEASE",
                previous_generation=previous_generation,
            )
            await self.activate()
            health = await self.health()
            if health.status is AdapterHealthStatus.UNAVAILABLE:
                raise SidecarRuntimeError(
                    health.reason_code or "SIDECAR_UNAVAILABLE",
                    "Sidecar did not return after idle unload",
                )
            self._on_demand_warmup_enabled = True
            return True

    async def cancel(self, request_id: UUID) -> CancelDisposition:
        generation = self._generation
        fingerprint_sha256 = self._fingerprint_sha256
        if generation is None or fingerprint_sha256 is None:
            raise SidecarRuntimeError("MODEL_NOT_READY", "Sidecar warmup is required")
        try:
            status_code, _, row = await asyncio.to_thread(
                self._request_json,
                "POST",
                "/v1/cancel",
                {"request_id": str(request_id)},
                expected_request_id=request_id,
                expected_generation=generation,
                expected_model=fingerprint_sha256,
            )
            if status_code != 200 or frozenset(row) != {
                "protocol_version",
                "request_id",
                "disposition",
                "effective_at",
            }:
                raise SidecarRuntimeError(
                    "CANCEL_RESPONSE_INVALID",
                    "Sidecar cancel response shape is invalid",
                    poison=True,
                )
            disposition = row.get("disposition")
            mapping = {
                "requested": CancelDisposition.REQUESTED,
                "already_terminal": CancelDisposition.ALREADY_TERMINAL,
                "not_found": CancelDisposition.NOT_FOUND,
            }
            if (
                disposition not in mapping
                or (
                    disposition == "requested"
                    and row.get("effective_at") != "segment_boundary"
                )
                or (
                    disposition != "requested" and row.get("effective_at") is not None
                )
                or self._generation != generation
                or self._fingerprint_sha256 != fingerprint_sha256
            ):
                raise SidecarRuntimeError(
                    "CANCEL_RESPONSE_INVALID",
                    "Sidecar cancel response identity is invalid",
                    poison=True,
                )
            return mapping[str(disposition)]
        except SidecarRuntimeError as error:
            if error.poison:
                await self._poison_and_restart(error)
            raise
        except (OSError, TimeoutError) as error:
            wrapped = SidecarRuntimeError(
                "SIDECAR_TRANSPORT_FAILURE", "Sidecar transport failed", poison=True
            )
            await self._poison_and_restart(wrapped)
            raise wrapped from error


def ensure_production_adapter(adapter: MossNanoTTSAdapter) -> MossNanoTTSAdapter:
    capabilities = adapter.capabilities
    if capabilities.is_test_double:
        raise ContractError("production dependency injection rejects test-double TTS adapters")
    if capabilities != MOSS_NANO_SIDECAR_CONTRACT_CAPABILITIES:
        raise ContractError("production dependency injection requires the frozen Sidecar capabilities")
    return adapter


def build_production_moss_adapter(
    config: SidecarRuntimeConfig,
    *,
    lifecycle: SidecarLifecycle | None = None,
    bootstrap_token: str | None = None,
) -> SidecarMossNanoTTSAdapter:
    if config.allow_test_backend:
        raise ContractError("production adapter factory rejects test backend configuration")
    if lifecycle is None or isinstance(lifecycle, NoopSidecarLifecycle):
        raise ContractError("production adapter factory requires a managed lifecycle")
    adapter = SidecarMossNanoTTSAdapter(
        config,
        lifecycle=lifecycle,
        bootstrap_token=bootstrap_token,
    )
    ensure_production_adapter(adapter)
    return adapter


def build_moss_adapter_from_environment(
    environ: Mapping[str, str] | None = None,
) -> SidecarMossNanoTTSAdapter | None:
    """Build the production consumer only behind the explicit capability gate."""

    values = os.environ if environ is None else environ
    enabled = values.get("AI_NOVEL_TTS_RUNTIME_ENABLED", "false")
    if enabled == "false":
        return None
    if enabled != "true":
        raise ContractError("AI_NOVEL_TTS_RUNTIME_ENABLED must be true or false")
    if values.get("MOSS_TTS_PROTOCOL_VERSION") != PROTOCOL_VERSION:
        raise ContractError("configured Sidecar protocol version is not frozen")
    if (
        values.get("MOSS_TTS_EXPECTED_MODEL_FINGERPRINT_SHA256")
        != EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
    ):
        raise ContractError("configured Sidecar model fingerprint is not frozen")
    if values.get("MOSS_TTS_LIFECYCLE") != "compose_on_failure_supervisor":
        raise ContractError("configured Sidecar lifecycle is not supported")
    raw_port = values.get("MOSS_TTS_SIDECAR_PORT", "")
    raw_timeout = values.get("MOSS_TTS_REQUEST_TIMEOUT_SECONDS", "120")
    try:
        port = int(raw_port)
        timeout = float(raw_timeout)
    except ValueError as error:
        raise ContractError("configured Sidecar numeric value is invalid") from error
    config = SidecarRuntimeConfig(
        host=values.get("MOSS_TTS_SIDECAR_HOST", ""),
        port=port,
        token_file=Path(values.get("MOSS_TTS_SIDECAR_TOKEN_FILE", "")),
        timeout_seconds=timeout,
    )
    bootstrap_token = read_secret_token(config.token_file)
    lifecycle = SupervisorManagedSidecarLifecycle(
        config,
        bootstrap_token=bootstrap_token,
    )
    return build_production_moss_adapter(
        config,
        lifecycle=lifecycle,
        bootstrap_token=bootstrap_token,
    )
