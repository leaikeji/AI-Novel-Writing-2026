"""Authenticated loopback-only product host for MOSS VoiceGenerator.

The HTTP caller cannot choose model paths, output paths, preview text, Python
modules or commands.  Each accepted request is sealed to disk before work is
started; terminal receipts and completion evidence are written with fsync and
atomic rename.  The database remains authoritative for product state.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import threading
import time
from typing import Final, Mapping, Protocol, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from backend.narration.voice_generator_runtime import (
    AUDIO_BYTES_HEADER,
    AUDIO_FORMAT_HEADER,
    AUDIO_SHA256_HEADER,
    EXPECTED_AUDIO_FORMAT_HEADER,
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HOST_PROTOCOL_VERSION,
    MAX_AUDIO_BYTES,
    MAX_JSON_BYTES,
    PROTOCOL_HEADER,
    REQUEST_ID_HEADER,
    RUNTIME_FINGERPRINT_HEADER,
    HostGenerationReceipt,
    VoiceGeneratorAudioParameters,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeIdentity,
    inspect_generated_wav,
)


HOST = "127.0.0.1"
PORT = 18_765
AUTHORIZATION_HEADER = "Authorization"
REQUEST_MANIFEST = "request.json"
STATE_MANIFEST = "state.json"
COMPLETION_MANIFEST = "completion.json"
TERMINAL_MANIFEST = "manifest.json"
AUDIO_NAME = "audio.wav"
HOST_STORE_SCHEMA = "voice-generator-host-store/1"
BACKEND_RESULT_SCHEMA = "voice-generator-native-result/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")


class HostProtocolError(RuntimeError):
    def __init__(
        self,
        code: str,
        status: int,
        *,
        request_id: UUID | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code if _STABLE_CODE.fullmatch(code) else "HOST_ERROR_INVALID"
        self.status = status
        self.request_id = request_id
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class BackendGenerationResult:
    request_id: UUID
    request_digest: str
    token_sha256: str
    audio_bytes: bytes = field(repr=False)
    audio_sha256: str
    memory_summary: Mapping[str, int | bool]
    started_at: str
    completed_at: str
    runtime_fingerprint: str = EXPECTED_RUNTIME_FINGERPRINT
    exit_reason_code: str = "COMPLETED"

    def __post_init__(self) -> None:
        for value in (self.request_digest, self.token_sha256, self.audio_sha256):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError("backend result digest is invalid")
        if hashlib.sha256(self.audio_bytes).hexdigest() != self.audio_sha256:
            raise ValueError("backend audio digest changed")
        if self.runtime_fingerprint != EXPECTED_RUNTIME_FINGERPRINT:
            raise ValueError("backend runtime identity changed")
        if self.exit_reason_code != "COMPLETED":
            raise ValueError("successful backend exit reason changed")
        inspect_generated_wav(self.audio_bytes)
        _validate_memory_summary(self.memory_summary)
        if _parse_time(self.completed_at) < _parse_time(self.started_at):
            raise ValueError("backend result timestamps are reversed")


class GenerationBackend(Protocol):
    def readiness(self) -> bool: ...

    def generate(
        self,
        request: VoiceGeneratorHostRequest,
        run_directory: Path,
        cancel_event: threading.Event,
    ) -> BackendGenerationResult: ...


def read_bearer_token(path: Path) -> str:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("token file must be absolute")
    descriptor: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ValueError("token no-follow policy is unavailable")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | nofollow)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 32 <= before.st_size <= 128
        ):
            raise ValueError("token file identity is invalid")
        raw = os.read(descriptor, 129)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ValueError("token file changed while reading")
        value = raw.decode("ascii")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if any(not 0x21 <= byte <= 0x7E for byte in raw):
        raise ValueError("token value is invalid")
    return value


def parse_generation_request(value: object) -> VoiceGeneratorHostRequest:
    expected = {
        "schema_version",
        "protocol_version",
        "request_id",
        "request_digest",
        "instruction",
        "instruction_digest",
        "language",
        "seed",
        "audio_parameters",
        "runtime_identity",
    }
    if type(value) is not dict or set(value) != expected:
        raise HostProtocolError("REQUEST_SHAPE_INVALID", HTTPStatus.BAD_REQUEST)
    if value.get("protocol_version") != HOST_PROTOCOL_VERSION:
        raise HostProtocolError("PROTOCOL_MISMATCH", HTTPStatus.CONFLICT)
    try:
        request_id = UUID(str(value["request_id"]))
        parameters = VoiceGeneratorAudioParameters.from_wire(value["audio_parameters"])
        identity = VoiceGeneratorRuntimeIdentity.from_wire(value["runtime_identity"])
        request = VoiceGeneratorHostRequest(
            request_id=request_id,
            instruction=value["instruction"],
            instruction_digest=value["instruction_digest"],
            language=value["language"],
            seed=value["seed"],
            audio_parameters=parameters,
            runtime_identity=identity,
            schema_version=value["schema_version"],
        )
    except (TypeError, ValueError) as error:
        raise HostProtocolError(
            "REQUEST_VALUE_INVALID", HTTPStatus.BAD_REQUEST
        ) from error
    if (
        str(request_id) != value["request_id"]
        or hashlib.sha256(request.instruction.encode("utf-8")).hexdigest()
        != request.instruction_digest
        or request.request_digest != value["request_digest"]
    ):
        raise HostProtocolError(
            "REQUEST_DIGEST_MISMATCH",
            HTTPStatus.CONFLICT,
            request_id=request_id,
        )
    return request


class HostStore:
    """Single-process durable request store with a process-level file lock."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute() or root.is_symlink():
            raise ValueError("host store must be an absolute non-symlink directory")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        details = root.stat()
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) & 0o077
            or root.resolve(strict=True) != root
        ):
            raise ValueError("host store directory identity is invalid")
        self.root = root
        lock_path = root / ".host.lock"
        self._lock_descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        lock_details = os.fstat(self._lock_descriptor)
        if (
            not stat.S_ISREG(lock_details.st_mode)
            or lock_details.st_nlink != 1
            or lock_details.st_uid != os.geteuid()
            or stat.S_IMODE(lock_details.st_mode) != 0o600
        ):
            os.close(self._lock_descriptor)
            raise ValueError("host store lock identity is invalid")
        try:
            fcntl.flock(self._lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(self._lock_descriptor)
            raise RuntimeError("another VoiceGenerator host owns the store") from error

    def close(self) -> None:
        descriptor = getattr(self, "_lock_descriptor", None)
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            self._lock_descriptor = None

    def request_directory(self, request_id: UUID) -> Path:
        directory = self.root / str(request_id)
        if directory.exists() or directory.is_symlink():
            details = directory.lstat()
            if (
                not stat.S_ISDIR(details.st_mode)
                or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode) & 0o077
                or directory.resolve(strict=True) != directory
            ):
                raise RuntimeError("stored VoiceGenerator request directory is invalid")
        return directory

    def create_request(self, request: VoiceGeneratorHostRequest) -> dict[str, object]:
        directory = self.request_directory(request.request_id)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            existing = self.load_request(request.request_id)
            if existing.get("request_digest") != request.request_digest:
                raise HostProtocolError(
                    "REQUEST_ID_CONFLICT",
                    HTTPStatus.CONFLICT,
                    request_id=request.request_id,
                )
            return self.load_receipt(request.request_id)
        self.request_directory(request.request_id)
        request_manifest = {
            "schema_version": HOST_STORE_SCHEMA,
            "protocol_version": HOST_PROTOCOL_VERSION,
            "request_id": str(request.request_id),
            "request_digest": request.request_digest,
            "request": request.wire_payload(),
            "redacted": False,
            "created_at": _now(),
        }
        _write_new_json(directory / REQUEST_MANIFEST, request_manifest)
        receipt = _active_receipt(request, "accepted", request_manifest["created_at"])
        _replace_json(directory / STATE_MANIFEST, receipt)
        _fsync_directory(directory)
        return receipt

    def load_request(
        self,
        request_id: UUID,
        *,
        allow_redacted_completion_recovery: bool = False,
    ) -> dict[str, object]:
        value = _read_json(self.request_directory(request_id) / REQUEST_MANIFEST)
        if (
            set(value) != {
                "schema_version",
                "protocol_version",
                "request_id",
                "request_digest",
                "request",
                "redacted",
                "created_at",
            }
            or value.get("schema_version") != HOST_STORE_SCHEMA
            or value.get("protocol_version") != HOST_PROTOCOL_VERSION
            or value.get("request_id") != str(request_id)
        ):
            raise RuntimeError("stored VoiceGenerator request is invalid")
        if value["redacted"] is False:
            parsed = parse_generation_request(value["request"])
            if (
                parsed.request_id != request_id
                or parsed.request_digest != value["request_digest"]
            ):
                raise RuntimeError("stored VoiceGenerator request digest is invalid")
        else:
            directory = self.request_directory(request_id)
            terminal_exists = (directory / TERMINAL_MANIFEST).is_file()
            recoverable_completion_exists = (
                allow_redacted_completion_recovery
                and (directory / COMPLETION_MANIFEST).is_file()
                and (directory / AUDIO_NAME).is_file()
            )
            if (
                value["redacted"] is not True
                or value["request"] is not None
                or not (terminal_exists or recoverable_completion_exists)
            ):
                raise RuntimeError("stored VoiceGenerator request redaction is invalid")
        return value

    def load_typed_request(self, request_id: UUID) -> VoiceGeneratorHostRequest:
        request = self.load_request(request_id)["request"]
        if request is None:
            raise RuntimeError("terminal VoiceGenerator request is redacted")
        return parse_generation_request(request)

    def load_receipt(self, request_id: UUID) -> dict[str, object]:
        directory = self.request_directory(request_id)
        terminal = directory / TERMINAL_MANIFEST
        value = _read_json(terminal if terminal.is_file() else directory / STATE_MANIFEST)
        receipt = HostGenerationReceipt.from_wire(value)
        if receipt.request_id != request_id:
            raise RuntimeError("stored VoiceGenerator receipt identity is invalid")
        return value

    def replace_active_receipt(self, request: VoiceGeneratorHostRequest, status: str) -> None:
        original = self.load_request(request.request_id)
        _replace_json(
            self.request_directory(request.request_id) / STATE_MANIFEST,
            _active_receipt(request, status, original["created_at"]),
        )

    def publish_completion(
        self,
        request: VoiceGeneratorHostRequest,
        result: BackendGenerationResult,
    ) -> dict[str, object]:
        directory = self.request_directory(request.request_id)
        if result.request_id != request.request_id or result.request_digest != request.request_digest:
            raise RuntimeError("backend result request identity changed")
        metrics = inspect_generated_wav(result.audio_bytes)
        completion = {
            "schema_version": BACKEND_RESULT_SCHEMA,
            "protocol_version": HOST_PROTOCOL_VERSION,
            "request_id": str(request.request_id),
            "request_digest": request.request_digest,
            "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
            "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
            "token_sha256": result.token_sha256,
            "audio_sha256": result.audio_sha256,
            "audio_size_bytes": len(result.audio_bytes),
            "audio_metrics": dict(metrics.public_payload()),
            "memory_summary": dict(result.memory_summary),
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "exit_reason_code": result.exit_reason_code,
        }
        _write_new_json(directory / COMPLETION_MANIFEST, completion)
        _write_new_bytes(directory / AUDIO_NAME, result.audio_bytes)
        receipt = _completed_receipt(completion)
        _write_new_json(directory / TERMINAL_MANIFEST, receipt)
        self._redact_request(request.request_id)
        _fsync_directory(directory)
        return receipt

    def publish_failure(
        self,
        request: VoiceGeneratorHostRequest,
        *,
        code: str,
        retryable: bool,
        cancelled: bool = False,
        started_at: str | None = None,
    ) -> dict[str, object]:
        if _STABLE_CODE.fullmatch(code) is None:
            code = "BACKEND_FAILURE"
        created = self.load_request(request.request_id)["created_at"]
        receipt = {
            "protocol_version": HOST_PROTOCOL_VERSION,
            "request_id": str(request.request_id),
            "request_digest": request.request_digest,
            "status": "cancelled" if cancelled else "failed",
            "terminal": True,
            "cancellable": False,
            "retryable": False if cancelled else retryable,
            "failure_code": "USER_CANCELLED" if cancelled else code,
            "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
            "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
            "token_sha256": None,
            "audio_sha256": None,
            "audio_size_bytes": None,
            "memory_summary": None,
            "started_at": started_at or created,
            "completed_at": _now(),
        }
        _write_new_json(self.request_directory(request.request_id) / TERMINAL_MANIFEST, receipt)
        self._redact_request(request.request_id)
        return receipt

    def _redact_request(self, request_id: UUID) -> None:
        path = self.request_directory(request_id) / REQUEST_MANIFEST
        value = _read_json(path)
        value["request"] = None
        value["redacted"] = True
        _replace_json(path, value)

    def recover_interrupted(self) -> None:
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                request_id = UUID(directory.name)
            except ValueError:
                continue
            if (directory / TERMINAL_MANIFEST).is_file():
                self.load_receipt(request_id)
                request_manifest = self.load_request(request_id)
                if request_manifest["redacted"] is False:
                    self._redact_request(request_id)
                continue
            request_manifest = self.load_request(
                request_id,
                allow_redacted_completion_recovery=True,
            )
            completion_path = directory / COMPLETION_MANIFEST
            audio_path = directory / AUDIO_NAME
            if completion_path.is_file() and audio_path.is_file():
                completion = _read_json(completion_path)
                audio = _read_bytes(audio_path, MAX_AUDIO_BYTES)
                receipt = _validate_stored_completion(
                    completion,
                    request_id=request_id,
                    request_digest=str(request_manifest["request_digest"]),
                    audio=audio,
                )
                _write_new_json(directory / TERMINAL_MANIFEST, receipt)
                if request_manifest["redacted"] is False:
                    self._redact_request(request_id)
                continue
            request_payload = request_manifest["request"]
            if request_payload is None:
                raise RuntimeError("redacted VoiceGenerator request lost completion evidence")
            request = parse_generation_request(request_payload)
            self.publish_failure(
                request,
                code="HOST_RESTART_INTERRUPTED",
                retryable=True,
            )


class VoiceGeneratorHostService:
    def __init__(self, store: HostStore, backend: GenerationBackend) -> None:
        self.store = store
        self.backend = backend
        self._lock = threading.RLock()
        self._active_request_id: UUID | None = None
        self._cancel_events: dict[UUID, threading.Event] = {}
        self._workers: dict[UUID, threading.Thread] = {}
        self._closing = False
        self.store.recover_interrupted()

    def health(self) -> dict[str, object]:
        with self._lock:
            ready = not self._closing and self._backend_ready()
            return {
                "protocol_version": HOST_PROTOCOL_VERSION,
                "status": "ready" if ready else "unavailable",
                "ready": ready,
                "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
                "active_request_id": str(self._active_request_id)
                if self._active_request_id
                else None,
            }

    def create(self, request: VoiceGeneratorHostRequest) -> tuple[int, dict[str, object]]:
        with self._lock:
            directory = self.store.request_directory(request.request_id)
            existed = directory.exists()
            receipt = self.store.create_request(request)
            if existed or receipt.get("terminal") is True:
                return HTTPStatus.OK, receipt
            if self._closing:
                return HTTPStatus.OK, self.store.publish_failure(
                    request,
                    code="HOST_SHUTTING_DOWN",
                    retryable=True,
                )
            if not self._backend_ready():
                return HTTPStatus.OK, self.store.publish_failure(
                    request,
                    code="HOST_RUNTIME_UNAVAILABLE",
                    retryable=True,
                )
            if self._active_request_id is not None:
                return HTTPStatus.OK, self.store.publish_failure(
                    request,
                    code="HOST_BUSY",
                    retryable=True,
                )
            self._active_request_id = request.request_id
            cancel_event = threading.Event()
            self._cancel_events[request.request_id] = cancel_event
            worker = threading.Thread(
                target=self._run,
                args=(request, cancel_event),
                name=f"voice-generator-{request.request_id}",
                daemon=True,
            )
            self._workers[request.request_id] = worker
            worker.start()
            return HTTPStatus.ACCEPTED, receipt

    def _backend_ready(self) -> bool:
        try:
            return self.backend.readiness() is True
        except Exception:
            return False

    def _run(self, request: VoiceGeneratorHostRequest, cancel_event: threading.Event) -> None:
        started_at = _now()
        try:
            self.store.replace_active_receipt(request, "generating")
            result = self.backend.generate(
                request,
                self.store.request_directory(request.request_id),
                cancel_event,
            )
            with self._lock:
                current = self.store.load_receipt(request.request_id)
                if current.get("terminal") is True:
                    return
                if cancel_event.is_set():
                    self.store.publish_failure(
                        request,
                        code="USER_CANCELLED",
                        retryable=False,
                        cancelled=True,
                        started_at=started_at,
                    )
                    return
                self.store.replace_active_receipt(request, "unloading")
                self.store.publish_completion(request, result)
        except HostProtocolError as error:
            with self._lock:
                if not (self.store.request_directory(request.request_id) / TERMINAL_MANIFEST).is_file():
                    self.store.publish_failure(
                        request,
                        code="USER_CANCELLED" if cancel_event.is_set() else error.code,
                        retryable=False if cancel_event.is_set() else error.retryable,
                        cancelled=cancel_event.is_set() or error.code == "USER_CANCELLED",
                        started_at=started_at,
                    )
        except Exception:
            with self._lock:
                if not (self.store.request_directory(request.request_id) / TERMINAL_MANIFEST).is_file():
                    self.store.publish_failure(
                        request,
                        code="USER_CANCELLED" if cancel_event.is_set() else "BACKEND_FAILURE",
                        retryable=not cancel_event.is_set(),
                        cancelled=cancel_event.is_set(),
                        started_at=started_at,
                    )
        finally:
            with self._lock:
                self._cancel_events.pop(request.request_id, None)
                self._workers.pop(request.request_id, None)
                if self._active_request_id == request.request_id:
                    self._active_request_id = None

    def get(self, request_id: UUID) -> dict[str, object]:
        try:
            return self.store.load_receipt(request_id)
        except FileNotFoundError as error:
            raise HostProtocolError(
                "REQUEST_NOT_FOUND", HTTPStatus.NOT_FOUND, request_id=request_id
            ) from error

    def cancel(self, request_id: UUID, request_digest: str) -> dict[str, object]:
        with self._lock:
            current = self.get(request_id)
            if current.get("request_digest") != request_digest:
                raise HostProtocolError(
                    "REQUEST_DIGEST_MISMATCH",
                    HTTPStatus.CONFLICT,
                    request_id=request_id,
                )
            if current.get("terminal") is True:
                return current
            request = self.store.load_typed_request(request_id)
            event = self._cancel_events.get(request_id)
            if event is None:
                return self.store.publish_failure(
                    request,
                    code="USER_CANCELLED",
                    retryable=False,
                    cancelled=True,
                )
            event.set()
            return current

    def audio(self, request_id: UUID) -> tuple[bytes, dict[str, object]]:
        receipt = self.get(request_id)
        if receipt.get("status") != "completed":
            raise HostProtocolError(
                "AUDIO_NOT_PUBLISHED", HTTPStatus.CONFLICT, request_id=request_id
            )
        payload = _read_bytes(self.store.request_directory(request_id) / AUDIO_NAME, MAX_AUDIO_BYTES)
        if (
            hashlib.sha256(payload).hexdigest() != receipt.get("audio_sha256")
            or len(payload) != receipt.get("audio_size_bytes")
        ):
            raise HostProtocolError(
                "AUDIO_EVIDENCE_MISMATCH",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                request_id=request_id,
            )
        inspect_generated_wav(payload)
        return payload, receipt

    def close(self) -> None:
        with self._lock:
            self._closing = True
            for event in self._cancel_events.values():
                event.set()
            workers = tuple(self._workers.values())
        deadline = time.monotonic() + 15.0
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))


class VoiceGeneratorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: VoiceGeneratorHostService,
        token: str,
        *,
        allow_test_port: bool = False,
    ) -> None:
        if address[0] != HOST or (not allow_test_port and address[1] != PORT):
            raise ValueError("VoiceGenerator host must use frozen loopback address")
        self.service = service
        self.token = token
        super().__init__(address, VoiceGeneratorRequestHandler)


class VoiceGeneratorRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MOSSVoiceGeneratorHost/1"
    sys_version = ""

    @property
    def app(self) -> VoiceGeneratorHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        request_id: UUID | None = None
        try:
            self._authenticate()
            if method == "GET":
                self._reject_request_body()
            split = urlsplit(self.path)
            if split.scheme or split.netloc or split.query or split.fragment:
                raise HostProtocolError("REQUEST_PATH_INVALID", HTTPStatus.BAD_REQUEST)
            parts = split.path.strip("/").split("/")
            if method == "GET" and split.path == "/v1/health":
                self._write_json(HTTPStatus.OK, self.app.service.health())
                return
            if method == "POST" and split.path == "/v1/generations":
                request = parse_generation_request(self._read_json_body())
                request_id = request.request_id
                status, receipt = self.app.service.create(request)
                self._write_json(status, receipt, request_id=request_id)
                return
            if len(parts) in {3, 4} and parts[:2] == ["v1", "generations"]:
                request_id = _parse_uuid(parts[2])
                if method == "GET" and len(parts) == 3:
                    self._write_json(
                        HTTPStatus.OK,
                        self.app.service.get(request_id),
                        request_id=request_id,
                    )
                    return
                if method == "GET" and parts[3:] == ["audio"]:
                    payload, receipt = self.app.service.audio(request_id)
                    self._write_audio(payload, receipt)
                    return
                if method == "POST" and parts[3:] == ["cancel"]:
                    body = self._read_json_body()
                    if set(body) != {"protocol_version", "request_id", "request_digest"}:
                        raise HostProtocolError(
                            "REQUEST_SHAPE_INVALID",
                            HTTPStatus.BAD_REQUEST,
                            request_id=request_id,
                        )
                    if (
                        body.get("protocol_version") != HOST_PROTOCOL_VERSION
                        or body.get("request_id") != str(request_id)
                        or not isinstance(body.get("request_digest"), str)
                    ):
                        raise HostProtocolError(
                            "REQUEST_VALUE_INVALID",
                            HTTPStatus.BAD_REQUEST,
                            request_id=request_id,
                        )
                    receipt = self.app.service.cancel(request_id, body["request_digest"])
                    self._write_json(HTTPStatus.OK, receipt, request_id=request_id)
                    return
            raise HostProtocolError("REQUEST_NOT_FOUND", HTTPStatus.NOT_FOUND, request_id=request_id)
        except HostProtocolError as error:
            self._write_error(error)
        except Exception:
            self._write_error(
                HostProtocolError(
                    "HOST_INTERNAL_ERROR",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    request_id=request_id,
                    retryable=True,
                )
            )

    def _authenticate(self) -> None:
        protocol_values = self.headers.get_all(PROTOCOL_HEADER, [])
        if protocol_values != [HOST_PROTOCOL_VERSION]:
            raise HostProtocolError("PROTOCOL_MISMATCH", HTTPStatus.CONFLICT)
        authorization_values = self.headers.get_all(AUTHORIZATION_HEADER, [])
        authorization = authorization_values[0] if len(authorization_values) == 1 else None
        expected = f"Bearer {self.app.token}"
        if not isinstance(authorization, str) or not hmac.compare_digest(authorization, expected):
            raise HostProtocolError("AUTHENTICATION_FAILED", HTTPStatus.UNAUTHORIZED)

    def _reject_request_body(self) -> None:
        if (
            self.headers.get_all("Transfer-Encoding", [])
            or self.headers.get_all("Content-Type", [])
            or self.headers.get_all("Content-Length", []) not in ([], ["0"])
        ):
            raise HostProtocolError("REQUEST_FRAMING_INVALID", HTTPStatus.BAD_REQUEST)

    def _read_json_body(self) -> dict[str, object]:
        transfer_values = self.headers.get_all("Transfer-Encoding", [])
        length_values = self.headers.get_all("Content-Length", [])
        content_type_values = self.headers.get_all("Content-Type", [])
        if transfer_values:
            raise HostProtocolError("REQUEST_FRAMING_INVALID", HTTPStatus.BAD_REQUEST)
        raw_length = length_values[0] if len(length_values) == 1 else None
        if (
            content_type_values != ["application/json"]
            or raw_length is None
            or not raw_length.isdigit()
            or not 1 <= int(raw_length) <= MAX_JSON_BYTES
        ):
            raise HostProtocolError("REQUEST_FRAMING_INVALID", HTTPStatus.BAD_REQUEST)
        body = self.rfile.read(int(raw_length))
        if len(body) != int(raw_length):
            raise HostProtocolError("REQUEST_SIZE_INVALID", HTTPStatus.BAD_REQUEST)
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HostProtocolError("REQUEST_JSON_INVALID", HTTPStatus.BAD_REQUEST) from error
        if type(value) is not dict:
            raise HostProtocolError("REQUEST_SHAPE_INVALID", HTTPStatus.BAD_REQUEST)
        return value

    def _base_headers(self, request_id: UUID | None = None) -> dict[str, str]:
        headers = {
            PROTOCOL_HEADER: HOST_PROTOCOL_VERSION,
            RUNTIME_FINGERPRINT_HEADER: EXPECTED_RUNTIME_FINGERPRINT,
            "Cache-Control": "no-store",
        }
        if request_id is not None:
            headers[REQUEST_ID_HEADER] = str(request_id)
        return headers

    def _write_json(
        self,
        status: int,
        value: Mapping[str, object],
        *,
        request_id: UUID | None = None,
    ) -> None:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(int(status))
        for name, header in self._base_headers(request_id).items():
            self.send_header(name, header)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_audio(self, payload: bytes, receipt: Mapping[str, object]) -> None:
        request_id = UUID(str(receipt["request_id"]))
        self.send_response(HTTPStatus.OK)
        for name, header in self._base_headers(request_id).items():
            self.send_header(name, header)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(AUDIO_SHA256_HEADER, hashlib.sha256(payload).hexdigest())
        self.send_header(AUDIO_BYTES_HEADER, str(len(payload)))
        self.send_header(AUDIO_FORMAT_HEADER, EXPECTED_AUDIO_FORMAT_HEADER)
        self.end_headers()
        self.wfile.write(payload)

    def _write_error(self, error: HostProtocolError) -> None:
        self.close_connection = True
        self._write_json(
            error.status,
            {
                "protocol_version": HOST_PROTOCOL_VERSION,
                "request_id": str(error.request_id) if error.request_id else None,
                "error": {"code": error.code, "retryable": error.retryable},
            },
            request_id=error.request_id,
        )


def serve(
    *,
    token_file: Path,
    store_root: Path,
    backend: GenerationBackend,
) -> int:
    token = read_bearer_token(token_file)
    store = HostStore(store_root)
    service = VoiceGeneratorHostService(store, backend)
    server = VoiceGeneratorHTTPServer((HOST, PORT), service, token)

    def stop(signum: int, frame: object) -> None:
        del signum, frame
        service.close()
        threading.Thread(target=server.shutdown, daemon=True).start()

    previous = {
        signum: signal.signal(signum, stop) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        service.close()
        server.server_close()
        store.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0


def _active_receipt(
    request: VoiceGeneratorHostRequest,
    status: str,
    started_at: str,
) -> dict[str, object]:
    if status not in {"accepted", "generating", "unloading"}:
        raise ValueError("active host status is invalid")
    return {
        "protocol_version": HOST_PROTOCOL_VERSION,
        "request_id": str(request.request_id),
        "request_digest": request.request_digest,
        "status": status,
        "terminal": False,
        "cancellable": True,
        "retryable": False,
        "failure_code": None,
        "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
        "token_sha256": None,
        "audio_sha256": None,
        "audio_size_bytes": None,
        "memory_summary": None,
        "started_at": started_at,
        "completed_at": None,
    }


def _completed_receipt(completion: Mapping[str, object]) -> dict[str, object]:
    return {
        "protocol_version": HOST_PROTOCOL_VERSION,
        "request_id": completion["request_id"],
        "request_digest": completion["request_digest"],
        "status": "completed",
        "terminal": True,
        "cancellable": False,
        "retryable": False,
        "failure_code": None,
        "runtime_identity": completion["runtime_identity"],
        "runtime_fingerprint": completion["runtime_fingerprint"],
        "token_sha256": completion["token_sha256"],
        "audio_sha256": completion["audio_sha256"],
        "audio_size_bytes": completion["audio_size_bytes"],
        "memory_summary": completion["memory_summary"],
        "started_at": completion["started_at"],
        "completed_at": completion["completed_at"],
    }


def _validate_stored_completion(
    completion: Mapping[str, object],
    *,
    request_id: UUID,
    request_digest: str,
    audio: bytes,
) -> dict[str, object]:
    expected = {
        "schema_version",
        "protocol_version",
        "request_id",
        "request_digest",
        "runtime_identity",
        "runtime_fingerprint",
        "token_sha256",
        "audio_sha256",
        "audio_size_bytes",
        "audio_metrics",
        "memory_summary",
        "started_at",
        "completed_at",
        "exit_reason_code",
    }
    audio_metrics = inspect_generated_wav(audio)
    if (
        set(completion) != expected
        or completion.get("schema_version") != BACKEND_RESULT_SCHEMA
        or completion.get("protocol_version") != HOST_PROTOCOL_VERSION
        or completion.get("request_id") != str(request_id)
        or completion.get("request_digest") != request_digest
        or completion.get("runtime_identity")
        != EXPECTED_RUNTIME_IDENTITY.wire_payload()
        or completion.get("runtime_fingerprint") != EXPECTED_RUNTIME_FINGERPRINT
        or completion.get("exit_reason_code") != "COMPLETED"
        or completion.get("audio_sha256") != hashlib.sha256(audio).hexdigest()
        or completion.get("audio_size_bytes") != len(audio)
        or completion.get("audio_metrics") != dict(audio_metrics.public_payload())
    ):
        raise RuntimeError("stored VoiceGenerator completion is invalid")
    for name in ("request_digest", "token_sha256", "audio_sha256"):
        value = completion.get(name)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise RuntimeError("stored VoiceGenerator completion digest is invalid")
    memory_summary = completion.get("memory_summary")
    if not isinstance(memory_summary, Mapping):
        raise RuntimeError("stored VoiceGenerator memory evidence is invalid")
    _validate_memory_summary(memory_summary)
    started_at = completion.get("started_at")
    completed_at = completion.get("completed_at")
    if (
        not isinstance(started_at, str)
        or not isinstance(completed_at, str)
        or _parse_time(completed_at) < _parse_time(started_at)
    ):
        raise RuntimeError("stored VoiceGenerator completion timestamps are invalid")
    receipt = _completed_receipt(completion)
    parsed = HostGenerationReceipt.from_wire(receipt)
    if parsed.request_id != request_id or parsed.request_digest != request_digest:
        raise RuntimeError("stored VoiceGenerator completion receipt is invalid")
    return receipt


def _validate_memory_summary(value: Mapping[str, int | bool]) -> None:
    expected = {
        "minimum_available_memory_bytes",
        "maximum_swap_delta_bytes",
        "maximum_pageouts_per_second",
        "critical_pressure_milliseconds",
        "stage_pid_overlap",
        "recovered_within_60_seconds",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("memory summary shape is invalid")
    for name in expected - {"stage_pid_overlap", "recovered_within_60_seconds"}:
        item = value[name]
        if type(item) is not int or item < 0:
            raise ValueError("memory summary scalar is invalid")
    if type(value["stage_pid_overlap"]) is not bool or type(value["recovered_within_60_seconds"]) is not bool:
        raise ValueError("memory summary flag is invalid")
    if value["stage_pid_overlap"] or not value["recovered_within_60_seconds"]:
        raise ValueError("backend did not prove staged recovery")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp is invalid")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _parse_uuid(value: str) -> UUID:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise HostProtocolError("REQUEST_ID_INVALID", HTTPStatus.BAD_REQUEST) from error
    if str(parsed) != value or parsed.int == 0:
        raise HostProtocolError("REQUEST_ID_INVALID", HTTPStatus.BAD_REQUEST)
    return parsed


def _read_json(path: Path) -> dict[str, object]:
    raw = _read_bytes(path, MAX_JSON_BYTES)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("stored JSON is invalid") from error
    if type(value) is not dict:
        raise RuntimeError("stored JSON shape is invalid")
    return value


def _read_bytes(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path.name)
    details = path.stat()
    if not 1 <= details.st_size <= maximum or stat.S_IMODE(details.st_mode) & 0o077:
        raise RuntimeError("stored file identity is invalid")
    payload = path.read_bytes()
    if len(payload) != details.st_size:
        raise RuntimeError("stored file changed while reading")
    return payload


def _write_new_json(path: Path, value: Mapping[str, object]) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("manifest is too large")
    _write_new_bytes(path, payload)


def _replace_json(path: Path, value: Mapping[str, object]) -> None:
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write(path, payload, replace=True)


def _write_new_bytes(path: Path, payload: bytes) -> None:
    _atomic_write(path, payload, replace=False)


def _atomic_write(path: Path, payload: bytes, *, replace: bool) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        if not replace and (path.exists() or path.is_symlink()):
            raise FileExistsError(path.name)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    from scripts.tts.voice_generator.native_runtime import NativeRuntimeBackend

    backend = NativeRuntimeBackend(
        runtime_python=arguments.runtime_python,
        model_root=arguments.model_root,
    )
    return serve(token_file=arguments.token_file, store_root=arguments.store_root, backend=backend)


if __name__ == "__main__":
    raise SystemExit(main())
