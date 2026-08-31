from __future__ import annotations

from array import array
import asyncio
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import threading
import time
from uuid import UUID, uuid4
import wave

import pytest

from backend.narration.voice_generator_runtime import (
    EXPECTED_RUNTIME_FINGERPRINT,
    HOST_PROTOCOL_VERSION,
    PROTOCOL_HEADER,
    HostGenerationReceipt,
    HostGenerationStatus,
    NativeVoiceGeneratorHostClient,
    VoiceGeneratorHostConfig,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeError,
)
from scripts.tts.voice_generator.host_server import (
    AUTHORIZATION_HEADER,
    AUDIO_NAME,
    COMPLETION_MANIFEST,
    HOST,
    REQUEST_MANIFEST,
    STATE_MANIFEST,
    TERMINAL_MANIFEST,
    BackendGenerationResult,
    HostStore,
    VoiceGeneratorHTTPServer,
    VoiceGeneratorHostService,
    VoiceGeneratorRequestHandler,
    parse_generation_request,
    read_bearer_token,
)
from scripts.tts.voice_generator.native_runtime import _strict_runtime_python
from scripts.tts.voice_generator.native_worker import (
    MAX_GENERATED_AUDIO_FRAMES,
    MIN_GENERATED_AUDIO_FRAMES,
    _write_failure,
)


TOKEN = "h" * 48
REQUEST_ID = UUID("9a80a7ee-83f5-4e3e-8e8c-59ed092d9a98")


def test_product_audio_frame_bounds_follow_delayed_generation_budget() -> None:
    assert MIN_GENERATED_AUDIO_FRAMES == 25
    assert MAX_GENERATED_AUDIO_FRAMES == 240


def test_worker_preserves_stable_audio_validation_failure_code(tmp_path: Path) -> None:
    result_path = tmp_path / "codec-result.json"
    _write_failure(
        result_path,
        "encode",
        VoiceGeneratorRuntimeError(
            "AUDIO_MACHINE_VALIDATION_FAILED",
            "redacted validation failure",
        ),
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["failure_code"] == "AUDIO_MACHINE_VALIDATION_FAILED"
    assert "redacted validation failure" not in result_path.read_text(encoding="utf-8")


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "host-token.secret"
    path.write_text(TOKEN, encoding="ascii")
    path.chmod(0o600)
    return path


def test_native_runtime_preserves_validated_venv_entry_symlink(
    tmp_path: Path,
) -> None:
    runtime_bin = tmp_path / "venv-bin"
    runtime_bin.mkdir(mode=0o700)
    entry = runtime_bin / "python"
    entry.symlink_to(Path(sys.executable))

    assert _strict_runtime_python(entry) == entry
    assert _strict_runtime_python(entry).is_symlink()


def _request(request_id: UUID = REQUEST_ID, instruction: str = "声音沉静而清晰。") -> VoiceGeneratorHostRequest:
    return VoiceGeneratorHostRequest(
        request_id=request_id,
        instruction=instruction,
        instruction_digest=hashlib.sha256(instruction.encode()).hexdigest(),
        language="zh-CN",
        seed=104729,
    )


def _wav() -> bytes:
    values = array("h")
    for index in range(48_000 * 3):
        sample = 2_800 if (index // 80) % 2 else -2_800
        values.extend((sample, sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48_000)
        target.writeframes(values.tobytes())
    return output.getvalue()


def _memory() -> dict[str, int | bool]:
    return {
        "minimum_available_memory_bytes": 1_900_000_000,
        "maximum_swap_delta_bytes": 500_000_000,
        "maximum_pageouts_per_second": 12,
        "critical_pressure_milliseconds": 0,
        "stage_pid_overlap": False,
        "recovered_within_60_seconds": True,
    }


class FakeBackend:
    def __init__(self, gate: threading.Event | None = None, *, ready: bool = True) -> None:
        self.gate = gate
        self.ready = ready
        self.started = threading.Event()
        self.calls = 0

    def readiness(self) -> bool:
        return self.ready

    def generate(
        self,
        request: VoiceGeneratorHostRequest,
        run_directory: Path,
        cancel_event: threading.Event,
    ) -> BackendGenerationResult:
        del run_directory
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if cancel_event.is_set():
                    raise RuntimeError("cancelled")
        payload = _wav()
        return BackendGenerationResult(
            request_id=request.request_id,
            request_digest=request.request_digest,
            token_sha256=hashlib.sha256(b"token-codes").hexdigest(),
            audio_bytes=payload,
            audio_sha256=hashlib.sha256(payload).hexdigest(),
            memory_summary=_memory(),
            started_at="2026-08-30T08:00:00Z",
            completed_at="2026-08-30T08:01:00Z",
        )


def _wait_terminal(service: VoiceGeneratorHostService, request_id: UUID) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        receipt = service.get(request_id)
        if receipt["terminal"] is True:
            return receipt
        time.sleep(0.01)
    raise AssertionError("host request did not become terminal")


def test_token_and_request_parser_fail_closed_on_permissions_or_extra_fields(tmp_path: Path) -> None:
    token = _token_file(tmp_path)
    assert read_bearer_token(token) == TOKEN
    token.chmod(0o644)
    with pytest.raises(ValueError):
        read_bearer_token(token)

    wire = _request().wire_payload()
    assert parse_generation_request(wire).request_digest == wire["request_digest"]
    with pytest.raises(Exception) as extra:
        parse_generation_request({**wire, "model_path": "/tmp/model"})
    assert getattr(extra.value, "code", None) == "REQUEST_SHAPE_INVALID"
    with pytest.raises(Exception) as changed:
        parse_generation_request({**wire, "request_digest": "0" * 64})
    assert getattr(changed.value, "code", None) == "REQUEST_DIGEST_MISMATCH"

    store = HostStore((tmp_path / "store").absolute())
    redirected = tmp_path / "redirected"
    redirected.mkdir(mode=0o700)
    store.request_directory(REQUEST_ID).symlink_to(redirected, target_is_directory=True)
    with pytest.raises(RuntimeError, match="request directory"):
        store.create_request(_request())
    store.close()


def test_store_persists_atomic_private_manifests_and_reuses_same_request(tmp_path: Path) -> None:
    root = (tmp_path / "store").absolute()
    store = HostStore(root)
    service = VoiceGeneratorHostService(store, FakeBackend())
    request = _request()
    status, accepted = service.create(request)
    assert status == 202
    assert accepted["status"] == "accepted"
    terminal = _wait_terminal(service, request.request_id)
    assert HostGenerationReceipt.from_wire(terminal).status.value == "completed"
    status, reused = service.create(request)
    assert status == 200
    assert reused == terminal
    assert service.backend.calls == 1

    directory = root / str(request.request_id)
    for name in (
        REQUEST_MANIFEST,
        STATE_MANIFEST,
        COMPLETION_MANIFEST,
        TERMINAL_MANIFEST,
        AUDIO_NAME,
    ):
        path = directory / name
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_mode & 0o077 == 0
    assert not list(directory.glob(".*.tmp"))
    assert hashlib.sha256((directory / AUDIO_NAME).read_bytes()).hexdigest() == terminal["audio_sha256"]
    sealed_request = json.loads((directory / REQUEST_MANIFEST).read_text(encoding="utf-8"))
    assert sealed_request["redacted"] is True
    assert sealed_request["request"] is None
    assert "声音沉静" not in (directory / REQUEST_MANIFEST).read_text(encoding="utf-8")
    store.close()


def test_same_request_id_with_different_digest_conflicts(tmp_path: Path) -> None:
    store = HostStore((tmp_path / "store").absolute())
    service = VoiceGeneratorHostService(store, FakeBackend(threading.Event()))
    service.create(_request())
    with pytest.raises(Exception) as failure:
        service.create(_request(instruction="完全不同的声音描述。"))
    assert getattr(failure.value, "code", None) == "REQUEST_ID_CONFLICT"
    service.cancel(REQUEST_ID, _request().request_digest)
    _wait_terminal(service, REQUEST_ID)
    store.close()


def test_unready_backend_fails_closed_without_running_generation(tmp_path: Path) -> None:
    store = HostStore((tmp_path / "store").absolute())
    backend = FakeBackend(ready=False)
    service = VoiceGeneratorHostService(store, backend)
    assert service.health()["ready"] is False
    status, receipt = service.create(_request())
    assert status == 200
    assert receipt["status"] == "failed"
    assert receipt["failure_code"] == "HOST_RUNTIME_UNAVAILABLE"
    assert receipt["retryable"] is True
    assert backend.calls == 0
    store.close()


def test_single_active_request_cancel_and_busy_request_are_durable(tmp_path: Path) -> None:
    gate = threading.Event()
    backend = FakeBackend(gate)
    store = HostStore((tmp_path / "store").absolute())
    service = VoiceGeneratorHostService(store, backend)
    first = _request()
    service.create(first)
    assert backend.started.wait(1)
    second = _request(uuid4())
    status, busy = service.create(second)
    assert status == 200
    assert busy["status"] == "failed"
    assert busy["failure_code"] == "HOST_BUSY"
    current = service.cancel(first.request_id, first.request_digest)
    assert current["terminal"] is False
    cancelled = _wait_terminal(service, first.request_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["failure_code"] == "USER_CANCELLED"
    assert not (store.request_directory(first.request_id) / AUDIO_NAME).exists()
    store.close()


def test_restart_recovers_unfinished_request_as_retryable_failure(tmp_path: Path) -> None:
    root = (tmp_path / "store").absolute()
    first_store = HostStore(root)
    request = _request()
    first_store.create_request(request)
    first_store.replace_active_receipt(request, "generating")
    first_store.close()

    recovered_store = HostStore(root)
    service = VoiceGeneratorHostService(recovered_store, FakeBackend())
    recovered = service.get(request.request_id)
    assert recovered["status"] == "failed"
    assert recovered["failure_code"] == "HOST_RESTART_INTERRUPTED"
    assert recovered["retryable"] is True
    assert service.backend.calls == 0
    recovered_store.close()


def test_restart_finishes_manifest_after_audio_publish_fence(tmp_path: Path) -> None:
    root = (tmp_path / "store").absolute()
    first_store = HostStore(root)
    request = _request()
    first_store.create_request(request)
    payload = _wav()
    result = BackendGenerationResult(
        request_id=request.request_id,
        request_digest=request.request_digest,
        token_sha256=hashlib.sha256(b"codes").hexdigest(),
        audio_bytes=payload,
        audio_sha256=hashlib.sha256(payload).hexdigest(),
        memory_summary=_memory(),
        started_at="2026-08-30T08:00:00Z",
        completed_at="2026-08-30T08:01:00Z",
    )
    first_store.publish_completion(request, result)
    (first_store.request_directory(request.request_id) / TERMINAL_MANIFEST).unlink()
    first_store.close()

    recovered_store = HostStore(root)
    service = VoiceGeneratorHostService(recovered_store, FakeBackend())
    recovered = service.get(request.request_id)
    assert recovered["status"] == "completed"
    assert recovered["audio_sha256"] == hashlib.sha256(payload).hexdigest()
    assert service.backend.calls == 0
    recovered_store.close()


def _json_request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    *,
    token: str = TOKEN,
) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() if payload else None
    headers = {
        PROTOCOL_HEADER: HOST_PROTOCOL_VERSION,
        AUTHORIZATION_HEADER: f"Bearer {token}",
    }
    if body is not None:
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
    connection = HTTPConnection(HOST, port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_http_host_requires_bearer_and_serves_create_get_audio(tmp_path: Path) -> None:
    store = HostStore((tmp_path / "store").absolute())
    service = VoiceGeneratorHostService(store, FakeBackend())
    server = VoiceGeneratorHTTPServer((HOST, 0), service, TOKEN, allow_test_port=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        status, _, body = _json_request(port, "GET", "/v1/health", None, token="wrong" * 8)
        assert status == 401
        assert json.loads(body)["error"]["code"] == "AUTHENTICATION_FAILED"

        status, headers, body = _json_request(port, "GET", "/v1/health", None)
        assert status == 200
        assert headers[PROTOCOL_HEADER] == HOST_PROTOCOL_VERSION
        assert json.loads(body)["runtime_fingerprint"] == EXPECTED_RUNTIME_FINGERPRINT

        request = _request()
        status, _, body = _json_request(port, "POST", "/v1/generations", request.wire_payload())
        assert status == 202
        assert json.loads(body)["request_id"] == str(request.request_id)
        _wait_terminal(service, request.request_id)

        status, headers, audio = _json_request(
            port,
            "GET",
            f"/v1/generations/{request.request_id}/audio",
            None,
        )
        assert status == 200
        assert headers["Content-Type"] == "audio/wav"
        assert headers["X-MOSS-Audio-SHA256"] == hashlib.sha256(audio).hexdigest()
    finally:
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        store.close()


def test_product_client_crosses_the_real_loopback_http_boundary(tmp_path: Path) -> None:
    token_file = _token_file(tmp_path)
    store = HostStore((tmp_path / "store").absolute())
    service = VoiceGeneratorHostService(store, FakeBackend())
    server = VoiceGeneratorHTTPServer((HOST, 0), service, TOKEN, allow_test_port=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = NativeVoiceGeneratorHostClient(
        VoiceGeneratorHostConfig(
            host=HOST,
            port=server.server_address[1],
            token_file=token_file.absolute(),
            timeout_seconds=3,
            allow_test_backend=True,
        )
    )
    request = _request()

    async def exercise() -> None:
        assert (await client.health()).ready is True
        receipt = await client.create(request)
        deadline = time.monotonic() + 3
        while not receipt.terminal and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
            receipt = await client.get(request)
        assert receipt.status is HostGenerationStatus.COMPLETED
        audio = await client.download_audio(request, receipt)
        assert audio.audio_sha256 == hashlib.sha256(_wav()).hexdigest()
        assert audio.metrics.duration_milliseconds == 3000

    try:
        asyncio.run(exercise())
    finally:
        service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        store.close()
