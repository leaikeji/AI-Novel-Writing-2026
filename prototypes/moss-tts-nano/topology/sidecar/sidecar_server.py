"""Private-network HTTP Sidecar with bounded byte responses and no media mount."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import struct
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid
import wave

from sidecar_protocol import (
    ID_PATTERN,
    MAX_AUDIO_BYTES,
    MAX_MULTIPART_BYTES,
    MAX_REQUEST_BYTES,
    MAX_REFERENCE_AUDIO_BYTES,
    MAX_REFERENCE_DURATION_SECONDS,
    PROTOCOL_VERSION,
    TOKEN_HEADER,
    VERSION_HEADER,
    ProtocolError,
    SynthesisRequest,
    authenticate,
    canonical_json_bytes,
    error_payload,
    parse_multipart_body,
    parse_request_bytes,
    require_protocol_version,
    sha256_bytes,
    validate_token,
)


@dataclass(frozen=True)
class AudioResult:
    payload: bytes
    sample_rate: int
    channels: int
    sample_width: int
    inference_entered_ms: float
    ready_wav_ms: float
    wall_ms: float
    peak_rss_bytes: int


def peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


class FakeBackend:
    """Protocol/control evidence only; never Nano quality or performance evidence."""

    def __init__(self, *, step_delay_seconds: float = 0.0) -> None:
        self.step_delay_seconds = step_delay_seconds

    def synthesize(self, request: SynthesisRequest, cancelled: threading.Event) -> AudioResult:
        started = time.perf_counter()
        sample_rate = 16_000
        frame_count = sample_rate // 5
        frequency = 160 + int(sha256_bytes(f"{request.voice}:{request.seed}:{request.text}".encode())[:4], 16) % 300
        raw = bytearray()
        for index in range(frame_count):
            if cancelled.is_set():
                raise ProtocolError("control", "REQUEST_CANCELLED", "request was cancelled", retryable=True)
            if self.step_delay_seconds and index % 100 == 0:
                time.sleep(self.step_delay_seconds)
            value = int(4000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            raw.extend(struct.pack("<h", value))
        stream = io.BytesIO()
        with wave.open(stream, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(raw))
        payload = stream.getvalue()
        ready_ms = (time.perf_counter() - started) * 1000.0
        return AudioResult(payload, sample_rate, 1, 2, 0.0, ready_ms, ready_ms, peak_rss_bytes())


class NanoBackend:
    def __init__(self, source_root: Path, model_root: Path, *, expected_source_hash: str, expected_model_hash: str) -> None:
        if not source_root.is_dir() or not model_root.is_dir():
            raise RuntimeError("read-only source/model mounts are missing")
        if not expected_source_hash or not expected_model_hash:
            raise RuntimeError("source/model fingerprints are required")
        lock_path = Path(os.environ.get("MOSS_MODEL_LOCK_PATH", "/app/model-sources.lock.json"))
        observed_source_hash, observed_model_hash = verify_pinned_trees(lock_path, source_root, model_root)
        if observed_source_hash != expected_source_hash or observed_model_hash != expected_model_hash:
            raise RuntimeError("source/model fingerprint mismatch")
        self.source_tree_sha256 = observed_source_hash
        self.model_tree_sha256 = observed_model_hash
        sys.path.insert(0, str(source_root.resolve()))
        from onnx_tts_runtime import OnnxTtsRuntime

        self._runtime = OnnxTtsRuntime(
            model_dir=model_root.resolve(),
            thread_count=int(os.environ.get("MOSS_CPU_THREADS", "4")),
            max_new_frames=375,
            sample_mode="fixed",
            execution_provider="cpu",
            output_dir=Path("/tmp/moss-output"),
        )

    def synthesize(self, request: SynthesisRequest, cancelled: threading.Event) -> AudioResult:
        if cancelled.is_set():
            raise ProtocolError("control", "REQUEST_CANCELLED", "request was cancelled", retryable=True)
        started = time.perf_counter()
        output_path = Path("/tmp/moss-output") / f"{uuid.uuid4().hex}.wav"
        reference_path: Path | None = None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if request.reference_audio is not None:
                reference_root = Path("/tmp/moss-reference")
                reference_root.mkdir(parents=True, exist_ok=True)
                reference_path = reference_root / f"{uuid.uuid4().hex}.{request.reference_audio.audio_format}"
                with reference_path.open("xb") as stream:
                    stream.write(request.reference_audio.payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            inference_entered_ms = (time.perf_counter() - started) * 1000.0
            result = self._runtime.synthesize(
                text=request.text,
                voice=request.voice,
                prompt_audio_path=reference_path,
                output_audio_path=output_path,
                sample_mode=request.sample_mode,
                do_sample=request.sample_mode != "greedy",
                streaming=True,
                max_new_frames=request.max_new_frames,
                enable_wetext=False,
                enable_normalize_tts_text=True,
                seed=request.seed,
                voice_clone_max_text_tokens=750,
            )
            ready_ms = (time.perf_counter() - started) * 1000.0
            produced = Path(str(result["audio_path"])).resolve()
            if produced != output_path.resolve():
                raise ProtocolError("backend", "OUTPUT_IDENTITY_MISMATCH", "backend output identity mismatch")
            payload = produced.read_bytes()
            if cancelled.is_set():
                raise ProtocolError("control", "REQUEST_CANCELLED", "request was cancelled", retryable=True)
            with wave.open(io.BytesIO(payload), "rb") as wav_file:
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
            return AudioResult(
                payload,
                sample_rate,
                channels,
                sample_width,
                inference_entered_ms,
                ready_ms,
                (time.perf_counter() - started) * 1000.0,
                peak_rss_bytes(),
            )
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            if reference_path is not None:
                try:
                    reference_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(rows: object) -> str:
    return sha256_bytes(canonical_json_bytes(rows))


def verify_pinned_trees(lock_path: Path, source_root: Path, model_root: Path) -> tuple[str, str]:
    """Verify every pinned runtime artifact before importing untrusted source."""

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        components = {
            str(row["component_id"]): row
            for row in lock["components"]
            if isinstance(row, dict) and "component_id" in row
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("model source lock is invalid") from error

    def verify_artifact(root: Path, artifact: dict[str, object]) -> tuple[str, str]:
        relative = Path(str(artifact.get("path", "")))
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise RuntimeError("pinned artifact escapes mount root") from error
        if not path.is_file() or path.stat().st_size != int(artifact.get("size", -1)):
            raise RuntimeError("pinned artifact is missing or has wrong size")
        algorithm = artifact.get("hash_algorithm")
        lock_hash = _sha256_file(path) if algorithm == "sha256" else _git_blob_sha1(path) if algorithm == "git-blob-sha1" else None
        if lock_hash != artifact.get("hash"):
            raise RuntimeError("pinned artifact hash mismatch")
        return relative.as_posix(), _sha256_file(path)

    source_component = components.get("moss-tts-nano-source")
    if not isinstance(source_component, dict):
        raise RuntimeError("pinned source component is missing")
    source_rows = [
        {"path": name, "sha256": digest}
        for name, digest in (
            verify_artifact(source_root, artifact)
            for artifact in source_component.get("artifacts", [])
            if isinstance(artifact, dict)
        )
    ]
    if len(source_rows) != len(source_component.get("artifacts", [])):
        raise RuntimeError("pinned source artifact list is invalid")

    model_rows: list[dict[str, str]] = []
    for component_id in ("moss-tts-nano-100m-onnx", "moss-audio-tokenizer-nano-onnx"):
        component = components.get(component_id)
        if not isinstance(component, dict):
            raise RuntimeError("pinned model component is missing")
        repository_name = str(component.get("repository", "")).rsplit("/", 1)[-1]
        candidate = model_root / repository_name
        component_root = candidate if candidate.is_dir() else model_root if model_root.name == repository_name else None
        if component_root is None:
            raise RuntimeError("pinned model component directory is missing")
        artifacts = component.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise RuntimeError("pinned model artifact list is invalid")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise RuntimeError("pinned model artifact entry is invalid")
            name, digest = verify_artifact(component_root, artifact)
            model_rows.append({"name": f"{component_id}/{name}", "sha256": digest})
    return _canonical_hash(source_rows), _canonical_hash(sorted(model_rows, key=lambda row: row["name"]))


@dataclass(frozen=True)
class ActiveRequest:
    asset_id: str
    cancelled: threading.Event


class SidecarState:
    def __init__(self, token: str, backend: FakeBackend | NanoBackend) -> None:
        self.token = validate_token(token)
        self.backend = backend
        self.active: dict[str, ActiveRequest] = {}
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.pid = os.getpid()
        self.generation = uuid.uuid4().hex
        self.accepted_request_count = 0
        self.completed_request_count = 0


class SidecarHandler(BaseHTTPRequestHandler):
    server_version = "MOSSProductionSidecar/1.0"

    @property
    def state(self) -> SidecarState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _authenticate(self) -> None:
        require_protocol_version(self.headers)
        authenticate(self.state.token, self.headers.get(TOKEN_HEADER))

    def _read_body(self, maximum: int) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            raise ProtocolError("request", "CONTENT_LENGTH_REQUIRED", "content length is required")
        length = int(raw_length)
        if length <= 0 or length > maximum:
            raise ProtocolError("request", "REQUEST_SIZE_INVALID", "request size is outside the limit")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ProtocolError("request", "REQUEST_BODY_TRUNCATED", "request body is truncated")
        return body

    def _send_json(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(VERSION_HEADER, PROTOCOL_VERSION)
        self.end_headers()
        self.wfile.write(payload)

    def _handle_error(self, error: ProtocolError, request_id: str | None = None) -> None:
        status = HTTPStatus.UNAUTHORIZED if error.category == "authentication" else HTTPStatus.BAD_REQUEST
        if error.code == "REQUEST_CANCELLED":
            status = HTTPStatus.CONFLICT
        self._send_json(int(status), error_payload(error, request_id))

    def do_GET(self) -> None:
        try:
            if self.path == "/health/live":
                self._send_json(200, canonical_json_bytes({"status": "live"}))
                return
            self._authenticate()
            if self.path != "/v1/capabilities":
                raise ProtocolError("protocol", "ENDPOINT_NOT_FOUND", "endpoint not found")
            payload = canonical_json_bytes(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "status": "ready",
                    "process": {
                        "pid": self.state.pid,
                        "generation": self.state.generation,
                        "uptime_ms": round((time.monotonic() - self.state.started_at) * 1000.0, 6),
                        "accepted_request_count": self.state.accepted_request_count,
                        "completed_request_count": self.state.completed_request_count,
                        "active_request_count": len(self.state.active),
                    },
                    "limits": {
                        "request_bytes": MAX_REQUEST_BYTES,
                        "audio_bytes": MAX_AUDIO_BYTES,
                        "reference_audio_bytes": MAX_REFERENCE_AUDIO_BYTES,
                        "reference_audio_duration_seconds": MAX_REFERENCE_DURATION_SECONDS,
                    },
                    "model": {
                        "source_sha256": os.environ.get("MOSS_SOURCE_TREE_SHA256"),
                        "model_sha256": os.environ.get("MOSS_MODEL_TREE_SHA256"),
                        "ffmpeg_build": os.environ.get("MOSS_FFMPEG_BUILD_ID"),
                    },
                }
            )
            self._send_json(200, payload)
        except ProtocolError as error:
            self._handle_error(error)

    def do_POST(self) -> None:
        request_id: str | None = None
        try:
            self._authenticate()
            if self.path == "/v1/synthesize":
                content_type = self.headers.get("Content-Type", "")
                if content_type == "application/json":
                    body = self._read_body(MAX_REQUEST_BYTES)
                    request = parse_request_bytes(body)
                elif content_type.startswith("multipart/form-data;"):
                    body = self._read_body(MAX_MULTIPART_BYTES)
                    metadata, reference_bytes, media_format = parse_multipart_body(body, content_type)
                    request = parse_request_bytes(metadata, reference_audio_bytes=reference_bytes)
                    if request.reference_audio is None or request.reference_audio.audio_format != media_format:
                        raise ProtocolError("reference_audio", "REFERENCE_MEDIA_TYPE_MISMATCH", "reference media type mismatch")
                else:
                    raise ProtocolError("request", "CONTENT_TYPE_INVALID", "content type is invalid")
                request_id = request.request_id
                with self.state.lock:
                    if self.state.active:
                        raise ProtocolError("control", "SIDECAR_BUSY", "sidecar allows one active inference", retryable=True)
                    if request.request_id in self.state.active:
                        raise ProtocolError("control", "DUPLICATE_ACTIVE_REQUEST", "request is already active")
                    cancelled = threading.Event()
                    self.state.active[request.request_id] = ActiveRequest(request.asset_id, cancelled)
                    self.state.accepted_request_count += 1
                try:
                    result = self.state.backend.synthesize(request, cancelled)
                    with self.state.lock:
                        self.state.completed_request_count += 1
                finally:
                    with self.state.lock:
                        self.state.active.pop(request.request_id, None)
                if len(result.payload) > MAX_AUDIO_BYTES:
                    raise ProtocolError("backend", "AUDIO_SIZE_EXCEEDED", "audio exceeds response limit")
                digest = sha256_bytes(result.payload)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(result.payload)))
                self.send_header(VERSION_HEADER, PROTOCOL_VERSION)
                self.send_header("X-MOSS-Request-ID", request.request_id)
                self.send_header("X-MOSS-Asset-ID", request.asset_id)
                self.send_header("X-MOSS-Audio-SHA256", digest)
                self.send_header("X-MOSS-Sample-Rate", str(result.sample_rate))
                self.send_header("X-MOSS-Channels", str(result.channels))
                self.send_header("X-MOSS-Sample-Width", str(result.sample_width))
                self.send_header("X-MOSS-Inference-Entered-Ms", f"{result.inference_entered_ms:.6f}")
                self.send_header("X-MOSS-Ready-Wav-Ms", f"{result.ready_wav_ms:.6f}")
                self.send_header("X-MOSS-Wall-Ms", f"{result.wall_ms:.6f}")
                self.send_header("X-MOSS-Peak-RSS-Bytes", str(result.peak_rss_bytes))
                self.send_header("X-MOSS-Worker-PID", str(self.state.pid))
                self.send_header("X-MOSS-Worker-Generation", self.state.generation)
                self.end_headers()
                self.wfile.write(result.payload)
                return
            if self.path == "/v1/cancel":
                if self.headers.get("Content-Type") != "application/json":
                    raise ProtocolError("request", "CONTENT_TYPE_INVALID", "content type is invalid")
                body = self._read_body(MAX_REQUEST_BYTES)
                row = json.loads(body.decode("utf-8"))
                if not isinstance(row, dict) or frozenset(row) != {"request_id", "asset_id"}:
                    raise ProtocolError("request", "CANCEL_FIELDS_INVALID", "cancel fields are invalid")
                request_id = str(row.get("request_id", ""))
                asset_id = str(row.get("asset_id", ""))
                if not ID_PATTERN.fullmatch(request_id) or not ID_PATTERN.fullmatch(asset_id):
                    raise ProtocolError("request", "IDENTIFIER_INVALID", "cancel identifiers are invalid")
                with self.state.lock:
                    active = self.state.active.get(request_id)
                    if active is not None and active.asset_id != asset_id:
                        raise ProtocolError("control", "ASSET_ID_MISMATCH", "cancel asset identity mismatch")
                    if active is not None:
                        active.cancelled.set()
                self._send_json(
                    200,
                    canonical_json_bytes(
                        {
                            "protocol_version": PROTOCOL_VERSION,
                            "request_id": request_id,
                            "asset_id": asset_id,
                            "status": "cancel_requested" if active is not None else "not_active",
                        }
                    ),
                )
                return
            raise ProtocolError("protocol", "ENDPOINT_NOT_FOUND", "endpoint not found")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._handle_error(ProtocolError("request", "INVALID_JSON", "request is not valid JSON"), request_id)
        except ProtocolError as error:
            self._handle_error(error, request_id)
        except Exception:
            self._handle_error(ProtocolError("backend", "BACKEND_FAILURE", "backend failed", retryable=True), request_id)


class SidecarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: SidecarState):
        super().__init__(address, SidecarHandler)
        self.state = state


def build_state() -> SidecarState:
    token_path = os.environ.get("MOSS_SIDECAR_TOKEN_FILE")
    if token_path:
        token_file = Path(token_path)
        if not token_file.is_file():
            raise RuntimeError("token secret file is missing")
        token = token_file.read_text(encoding="utf-8").rstrip("\r\n")
    else:
        token = os.environ.get("MOSS_SIDECAR_TOKEN", "")
    backend_name = os.environ.get("MOSS_SIDECAR_BACKEND", "fake")
    if backend_name == "fake":
        backend: FakeBackend | NanoBackend = FakeBackend(
            step_delay_seconds=float(os.environ.get("MOSS_FAKE_STEP_DELAY_SECONDS", "0"))
        )
    elif backend_name == "nano":
        backend = NanoBackend(
            Path("/source"),
            Path("/models"),
            expected_source_hash=os.environ.get("MOSS_SOURCE_TREE_SHA256", ""),
            expected_model_hash=os.environ.get("MOSS_MODEL_TREE_SHA256", ""),
        )
    else:
        raise RuntimeError("unsupported backend")
    return SidecarState(token, backend)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = SidecarHTTPServer((args.host, args.port), build_state())
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
