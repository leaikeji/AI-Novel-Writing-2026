from __future__ import annotations

import asyncio
from array import array
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from uuid import UUID, uuid4
import wave

import pytest

from backend.narration.voice_generator_runtime import (
    AUDIO_BYTES_HEADER,
    AUDIO_FORMAT_HEADER,
    AUDIO_SHA256_HEADER,
    CODEC_REVISION,
    EXPECTED_AUDIO_FORMAT_HEADER,
    EXPECTED_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    HOST_PROTOCOL_VERSION,
    HOST_TOKEN_HEADER,
    HttpResponseEnvelope,
    NativeVoiceGeneratorHostClient,
    PRODUCTION_HOST,
    PRODUCTION_PORT,
    PROTOCOL_HEADER,
    REQUEST_ID_HEADER,
    RUNTIME_FINGERPRINT_HEADER,
    RUNTIME_TOPOLOGY,
    MAX_GENERATED_AUDIO_MILLISECONDS,
    MIN_GENERATED_AUDIO_MILLISECONDS,
    VOICE_GENERATOR_REVISION,
    HostGenerationReceipt,
    HostGenerationStatus,
    VoiceGeneratorAudioParameters,
    VoiceGeneratorHostConfig,
    VoiceGeneratorHostRequest,
    VoiceGeneratorRuntimeError,
    inspect_generated_wav,
    read_host_token,
)


TOKEN = "v" * 48
REQUEST_ID = UUID("7bcd9011-e5c0-4f60-a8ec-138e2eb49bb7")
INSTRUCTION = "声音沉静而克制，语速稍慢，质感清晰。"
INSTRUCTION_DIGEST = hashlib.sha256(INSTRUCTION.encode("utf-8")).hexdigest()
STARTED_AT = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)
COMPLETED_AT = datetime(2026, 8, 30, 8, 1, tzinfo=timezone.utc)


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "voice-generator-token.secret"
    path.write_text(TOKEN, encoding="ascii")
    path.chmod(0o600)
    return path


def _request() -> VoiceGeneratorHostRequest:
    return VoiceGeneratorHostRequest(
        request_id=REQUEST_ID,
        instruction=INSTRUCTION,
        instruction_digest=INSTRUCTION_DIGEST,
        language="zh-CN",
        seed=104729,
    )


def _wav_bytes(*, seconds: int = 3) -> bytes:
    samples = array("h")
    for index in range(48_000 * seconds):
        sample = 3_000 if (index // 80) % 2 == 0 else -3_000
        samples.extend((sample, sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48_000)
        target.writeframes(samples.tobytes())
    return output.getvalue()


def _memory() -> dict[str, object]:
    return {
        "minimum_available_memory_bytes": 1_900_000_000,
        "maximum_swap_delta_bytes": 510_000_000,
        "maximum_pageouts_per_second": 12,
        "critical_pressure_milliseconds": 0,
        "stage_pid_overlap": False,
        "recovered_within_60_seconds": True,
    }


def _receipt_payload(
    request: VoiceGeneratorHostRequest,
    *,
    status: str = "accepted",
    audio: bytes | None = None,
    failure_code: str | None = None,
    retryable: bool = False,
) -> dict[str, object]:
    terminal = status in {"completed", "failed", "cancelled"}
    completed = COMPLETED_AT.isoformat().replace("+00:00", "Z") if terminal else None
    return {
        "protocol_version": HOST_PROTOCOL_VERSION,
        "request_id": str(request.request_id),
        "request_digest": request.request_digest,
        "status": status,
        "terminal": terminal,
        "cancellable": not terminal,
        "retryable": retryable,
        "failure_code": failure_code,
        "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
        "token_sha256": hashlib.sha256(b"tokens").hexdigest()
        if status == "completed"
        else None,
        "audio_sha256": hashlib.sha256(audio).hexdigest() if audio else None,
        "audio_size_bytes": len(audio) if audio else None,
        "memory_summary": _memory() if status == "completed" else None,
        "started_at": STARTED_AT.isoformat().replace("+00:00", "Z"),
        "completed_at": completed,
    }


def _json_envelope(
    payload: dict[str, object],
    *,
    status: int = 200,
    request_id: UUID | None = REQUEST_ID,
) -> HttpResponseEnvelope:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        (PROTOCOL_HEADER, HOST_PROTOCOL_VERSION),
        (RUNTIME_FINGERPRINT_HEADER, EXPECTED_RUNTIME_FINGERPRINT),
    ]
    if request_id is not None:
        headers.append((REQUEST_ID_HEADER, str(request_id)))
    return HttpResponseEnvelope(status=status, headers=tuple(headers), body=body)


class FakeTransport:
    def __init__(self, *responses: HttpResponseEnvelope):
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        maximum_response_bytes: int,
    ) -> HttpResponseEnvelope:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": body,
                "maximum": maximum_response_bytes,
            }
        )
        return self.responses.pop(0)


def _client(tmp_path: Path, transport: FakeTransport) -> NativeVoiceGeneratorHostClient:
    return NativeVoiceGeneratorHostClient(
        VoiceGeneratorHostConfig(
            host="127.0.0.1",
            port=18_765,
            token_file=_token_file(tmp_path),
            allow_test_backend=True,
        ),
        transport=transport,
    )


def test_production_config_and_request_freeze_the_only_allowed_inputs(tmp_path: Path) -> None:
    config = VoiceGeneratorHostConfig(
        host=PRODUCTION_HOST,
        port=PRODUCTION_PORT,
        token_file=_token_file(tmp_path),
    )
    assert config.host == "host.docker.internal"
    assert config.port == 18_765
    with pytest.raises(ValueError):
        VoiceGeneratorHostConfig(
            host="127.0.0.1",
            port=PRODUCTION_PORT,
            token_file=config.token_file,
        )
    with pytest.raises(ValueError):
        VoiceGeneratorHostConfig(
            host=PRODUCTION_HOST,
            port=8765,
            token_file=config.token_file,
        )

    request = _request()
    wire = request.wire_payload()
    assert set(wire) == {
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
    rendered = json.dumps(wire, ensure_ascii=False)
    assert "path" not in wire and "url" not in wire and "model_name" not in wire
    assert VOICE_GENERATOR_REVISION in rendered
    assert CODEC_REVISION in rendered
    assert RUNTIME_TOPOLOGY in rendered
    assert wire["audio_parameters"] == {
        "schema_version": "voice-generator-audio-parameters/1",
        "audio_temperature_milli": 1500,
        "audio_top_p_milli": 600,
        "audio_top_k": 50,
        "audio_repetition_penalty_milli": 1100,
    }
    assert request.request_digest == request.wire_payload()["request_digest"]
    assert "沉静" not in repr(request)


def test_request_rejects_arbitrary_parameters_language_seed_and_runtime_identity() -> None:
    with pytest.raises(ValueError, match="instruction digest changed"):
        VoiceGeneratorHostRequest(
            request_id=uuid4(),
            instruction="valid",
            instruction_digest=hashlib.sha256(b"another instruction").hexdigest(),
            language="zh-CN",
            seed=1,
        )
    with pytest.raises(ValueError):
        VoiceGeneratorAudioParameters(audio_top_k=51)
    with pytest.raises(ValueError):
        VoiceGeneratorHostRequest(
            request_id=uuid4(),
            instruction="valid",
            instruction_digest=INSTRUCTION_DIGEST,
            language="fr",
            seed=1,
        )
    with pytest.raises(ValueError):
        VoiceGeneratorHostRequest(
            request_id=uuid4(),
            instruction="valid",
            instruction_digest=INSTRUCTION_DIGEST,
            language="en",
            seed=2**63,
        )


def test_token_must_be_owned_0600_regular_file(tmp_path: Path) -> None:
    valid = _token_file(tmp_path)
    assert read_host_token(valid) == TOKEN
    valid.chmod(0o644)
    with pytest.raises(VoiceGeneratorRuntimeError, match="invalid") as failure:
        read_host_token(valid)
    assert failure.value.code == "TOKEN_FILE_INVALID"

    valid.chmod(0o600)
    alias = tmp_path / "token-link"
    alias.symlink_to(valid)
    with pytest.raises(VoiceGeneratorRuntimeError) as linked:
        read_host_token(alias)
    assert linked.value.code == "TOKEN_FILE_INVALID"


def test_client_sends_secret_only_in_header_and_validates_health(tmp_path: Path) -> None:
    health = {
        "protocol_version": HOST_PROTOCOL_VERSION,
        "status": "ready",
        "ready": True,
        "runtime_identity": EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT,
        "active_request_id": None,
    }
    transport = FakeTransport(_json_envelope(health, request_id=None))
    client = _client(tmp_path, transport)
    result = asyncio.run(client.health())
    assert result.ready is True
    sent = transport.requests[0]
    assert sent["path"] == "/v1/health"
    assert sent["headers"][HOST_TOKEN_HEADER] == f"Bearer {TOKEN}"
    assert sent["body"] is None
    assert TOKEN not in repr(client.config)


def test_create_get_and_cancel_close_request_id_and_digest(tmp_path: Path) -> None:
    request = _request()
    accepted = _json_envelope(_receipt_payload(request))
    running = _json_envelope(_receipt_payload(request, status="generating"))
    cancelled = _json_envelope(
        _receipt_payload(
            request,
            status="cancelled",
            failure_code="USER_CANCELLED",
        )
    )
    transport = FakeTransport(accepted, running, cancelled)
    client = _client(tmp_path, transport)
    first = asyncio.run(client.create(request))
    second = asyncio.run(client.get(request))
    third = asyncio.run(client.cancel(request))
    assert first.status is HostGenerationStatus.ACCEPTED
    assert second.status is HostGenerationStatus.GENERATING
    assert third.status is HostGenerationStatus.CANCELLED
    assert [row["path"] for row in transport.requests] == [
        "/v1/generations",
        f"/v1/generations/{REQUEST_ID}",
        f"/v1/generations/{REQUEST_ID}/cancel",
    ]
    create_body = transport.requests[0]["body"]
    assert isinstance(create_body, bytes)
    assert TOKEN.encode() not in create_body
    assert b"model_path" not in create_body and b"http://" not in create_body


def test_completed_audio_is_rehashed_and_machine_validated(tmp_path: Path) -> None:
    request = _request()
    audio = _wav_bytes()
    receipt = HostGenerationReceipt.from_wire(
        _receipt_payload(request, status="completed", audio=audio)
    )
    audio_response = HttpResponseEnvelope(
        status=200,
        headers=(
            ("Content-Type", "audio/wav"),
            ("Content-Length", str(len(audio))),
            (PROTOCOL_HEADER, HOST_PROTOCOL_VERSION),
            (REQUEST_ID_HEADER, str(REQUEST_ID)),
            (RUNTIME_FINGERPRINT_HEADER, EXPECTED_RUNTIME_FINGERPRINT),
            (AUDIO_SHA256_HEADER, hashlib.sha256(audio).hexdigest()),
            (AUDIO_BYTES_HEADER, str(len(audio))),
            (AUDIO_FORMAT_HEADER, EXPECTED_AUDIO_FORMAT_HEADER),
        ),
        body=audio,
    )
    client = _client(tmp_path, FakeTransport(audio_response))
    result = asyncio.run(client.download_audio(request, receipt))
    assert result.audio_sha256 == hashlib.sha256(audio).hexdigest()
    assert result.metrics.duration_milliseconds == 3000
    assert result.metrics.sample_rate_hz == 48_000
    assert result.metrics.channels == 2
    assert result.metrics.sample_width_bytes == 2


def test_machine_validation_accepts_product_duration_budget() -> None:
    metrics = inspect_generated_wav(_wav_bytes(seconds=7))
    assert metrics.duration_milliseconds == 7_000
    assert MIN_GENERATED_AUDIO_MILLISECONDS == 2_000
    assert MAX_GENERATED_AUDIO_MILLISECONDS == 19_200

    with pytest.raises(VoiceGeneratorRuntimeError) as too_short:
        inspect_generated_wav(_wav_bytes(seconds=1))
    assert too_short.value.code == "AUDIO_MACHINE_VALIDATION_FAILED"


def test_audio_hash_header_and_wav_identity_fail_closed(tmp_path: Path) -> None:
    request = _request()
    audio = _wav_bytes()
    receipt = HostGenerationReceipt.from_wire(
        _receipt_payload(request, status="completed", audio=audio)
    )
    bad_headers = HttpResponseEnvelope(
        status=200,
        headers=(
            ("Content-Type", "audio/wav"),
            (PROTOCOL_HEADER, HOST_PROTOCOL_VERSION),
            (REQUEST_ID_HEADER, str(REQUEST_ID)),
            (RUNTIME_FINGERPRINT_HEADER, EXPECTED_RUNTIME_FINGERPRINT),
            (AUDIO_SHA256_HEADER, "0" * 64),
            (AUDIO_BYTES_HEADER, str(len(audio))),
            (AUDIO_FORMAT_HEADER, EXPECTED_AUDIO_FORMAT_HEADER),
        ),
        body=audio,
    )
    client = _client(tmp_path, FakeTransport(bad_headers))
    with pytest.raises(VoiceGeneratorRuntimeError) as failure:
        asyncio.run(client.download_audio(request, receipt))
    assert failure.value.code == "AUDIO_EVIDENCE_MISMATCH"

    with pytest.raises(VoiceGeneratorRuntimeError) as invalid:
        inspect_generated_wav(audio[:100])
    assert invalid.value.code in {"AUDIO_SIZE_MISMATCH", "AUDIO_FORMAT_INVALID"}


def test_receipt_rejects_runtime_identity_drift_and_incomplete_recovery() -> None:
    request = _request()
    audio = _wav_bytes()
    drift = _receipt_payload(request, status="completed", audio=audio)
    drift["runtime_identity"] = {
        **EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        "codec_revision": "0" * 40,
    }
    with pytest.raises(VoiceGeneratorRuntimeError) as identity_failure:
        HostGenerationReceipt.from_wire(drift)
    assert identity_failure.value.code == "RUNTIME_IDENTITY_MISMATCH"

    unsafe = _receipt_payload(request, status="completed", audio=audio)
    unsafe["memory_summary"] = {**_memory(), "stage_pid_overlap": True}
    with pytest.raises(VoiceGeneratorRuntimeError) as recovery_failure:
        HostGenerationReceipt.from_wire(unsafe)
    assert recovery_failure.value.code == "GENERATION_RECEIPT_INVALID"
