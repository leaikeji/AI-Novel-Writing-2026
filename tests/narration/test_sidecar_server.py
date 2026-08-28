from __future__ import annotations

import asyncio
import builtins
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from uuid import UUID, uuid4
import wave

import pytest

from backend.narration import runtime as narration_runtime
from backend.narration import sidecar_server
from backend.narration.adapters import FakeMossNanoTTSAdapter
from backend.narration.contracts import (
    AdapterHealthStatus,
    CancelDisposition,
    ContractError,
    NarrationRequestScope,
    ReferenceAudioInput,
    SynthesisRequest,
)
from backend.narration.runtime import (
    DockerComposeSidecarLifecycle,
    EXPECTED_PRODUCTION_ENTRYPOINT,
    EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256,
    NoopSidecarLifecycle,
    PROTOCOL_VERSION,
    SidecarMossNanoTTSAdapter,
    SidecarRuntimeConfig,
    SidecarRuntimeError,
    SupervisorManagedSidecarLifecycle,
    build_moss_adapter_from_environment,
    build_production_moss_adapter,
    ensure_production_adapter,
    read_secret_token,
    _validate_complete_pcm_wav,
)
from backend.narration.sidecar_server import (
    FakeBackend,
    NanoBackend,
    ParsedSynthesisRequest,
    ReferenceAudio,
    SidecarHandler,
    SidecarHTTPServer,
    SidecarProtocolError,
    SidecarState,
    _inspect_reference,
    _model_fingerprint_sha256,
    _validate_wav,
    load_official_preset_catalog,
    read_secret_token as read_server_secret_token,
)


TOKEN = "t1b-test-token-0123456789abcdef-0123456789"


class RecordingLifecycle:
    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.previous_generations: list[int | None] = []
        self.observed_poisoned: list[bool] = []
        self.state: SidecarState | None = None

    async def restart_after_poison(
        self,
        reason_code: str,
        *,
        previous_generation: int | None = None,
    ) -> None:
        self.reasons.append(reason_code)
        self.previous_generations.append(previous_generation)
        if self.state is not None:
            with self.state.lock:
                self.observed_poisoned.append(self.state.poisoned)
                self.state.generation += 1
                self.state.poisoned = False
                self.state.status = "unloaded"
                self.state.model_fingerprint = None
                self.state.model_fingerprint_sha256 = None
                self.state.worker_token = None
                self.state.worker_lease_deadline = None


@contextmanager
def running_server(*, step_delay_seconds: float = 0.0, fail_mode: str | None = None):
    state = SidecarState(TOKEN, FakeBackend(step_delay_seconds=step_delay_seconds, fail_mode=fail_mode))
    server = SidecarHTTPServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def token_file(tmp_path: Path, value: bytes = TOKEN.encode("ascii")) -> Path:
    path = tmp_path / "sidecar-token.secret"
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def adapter_for(
    tmp_path: Path,
    server: SidecarHTTPServer,
    *,
    lifecycle: RecordingLifecycle | None = None,
) -> SidecarMossNanoTTSAdapter:
    return SidecarMossNanoTTSAdapter(
        SidecarRuntimeConfig(
            host="127.0.0.1",
            port=server.server_port,
            token_file=token_file(tmp_path),
            timeout_seconds=3,
            allow_test_backend=True,
        ),
        lifecycle=lifecycle,
    )


def synthesis_request(*, request_id: UUID | None = None, reference: ReferenceAudioInput | None = None) -> SynthesisRequest:
    return SynthesisRequest(
        request_id=request_id or uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text="这是 T1-B 的隔离测试句段。",
        voice="narrator_neutral",
        seed=42,
        sample_mode="fixed",
        max_new_frames=64,
        reference_audio=reference,
    )


def reference_wav() -> ReferenceAudioInput:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x00\x00" * 1600)
    payload = output.getvalue()
    return ReferenceAudioInput(payload, hashlib.sha256(payload).hexdigest())


def pcm_wav(
    *,
    sample_rate: int = 48_000,
    channels: int = 2,
    frames: int = 480,
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * channels * frames)
    return output.getvalue()


OFFICIAL_PRESET_TEST_NAMES = (
    "Junhao",
    "Zhiming",
    "Weiguo",
    "Xiaoyu",
    "Yuewen",
    "Lingyu",
    "Trump",
    "Ava",
    "Bella",
    "Adam",
    "Nathan",
    "Soyo",
    "Saki",
    "Mortis",
    "Umiri",
    "Mei",
    "Anon",
    "Arisa",
)


def official_preset_manifest() -> dict[str, object]:
    return {
        "builtin_voices": [
            {
                "voice": voice,
                "display_name": voice,
                "group": "test",
                "audio_file": f"{index}.wav",
                "prompt_audio_codes": [
                    [987_654_321 + index + quantizer for quantizer in range(16)],
                    [123_456_789 + index + quantizer for quantizer in range(16)],
                ],
            }
            for index, voice in enumerate(OFFICIAL_PRESET_TEST_NAMES)
        ],
        "format_version": 1,
        "generation_defaults": {},
        "model_files": {},
        "prompt_templates": {},
        "text_samples": [],
        "tts_config": {},
    }


def write_test_preset_manifest(
    tmp_path: Path,
    manifest: dict[str, object] | None = None,
) -> tuple[Path, str]:
    path = tmp_path / "browser_poc_manifest.json"
    raw = json.dumps(
        manifest or official_preset_manifest(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def nano_request(
    voice: str,
    *,
    reference_audio: ReferenceAudio | None = None,
    seed: int = 42,
    sample_mode: str = "fixed",
) -> ParsedSynthesisRequest:
    return ParsedSynthesisRequest(
        request_id=str(uuid4()),
        scope_fingerprint=sidecar_server.LOCAL_SCOPE_FINGERPRINT,
        requested_model_fingerprint_sha256="0" * 64,
        text="official preset test",
        voice=voice,
        seed=seed,
        sample_mode=sample_mode,
        max_new_frames=64,
        reference_audio=reference_audio,
    )


def test_official_preset_catalog_keeps_all_18_exact_manifest_voices(
    tmp_path: Path,
) -> None:
    path, digest = write_test_preset_manifest(tmp_path)

    catalog = load_official_preset_catalog(path, expected_sha256=digest)

    assert len(catalog.presets) == 18
    assert tuple(catalog.voices) == tuple(
        f"onnx.{voice}" for voice in OFFICIAL_PRESET_TEST_NAMES
    )
    assert catalog.voices["onnx.Trump"] == "Trump"
    assert catalog.voices["onnx.Xiaoyu"] == "Xiaoyu"
    assert len(catalog.metadata_fingerprint_sha256) == 64
    assert all(row.prompt_frame_count == 2 for row in catalog.presets)
    assert "prompt_audio_codes" not in repr(catalog)
    assert "987654321" not in repr(catalog)


def test_sidecar_metadata_parser_accepts_external_onnx_preset_id() -> None:
    payload = {
        "request_id": str(uuid4()),
        "scope_fingerprint": sidecar_server.LOCAL_SCOPE_FINGERPRINT,
        "requested_model_fingerprint_sha256": "0" * 64,
        "text": "exact preset parser test",
        "voice": "onnx.Xiaoyu",
        "seed": 42,
        "sample_mode": "fixed",
        "max_new_frames": 64,
    }

    parsed = sidecar_server._parse_metadata(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        None,
    )

    assert parsed.voice == "onnx.Xiaoyu"


@pytest.mark.parametrize(
    "invalid_text",
    (
        "e\u0301",
        "替换字符\ufffd",
        "控制字符\u0000",
        "未配对代理\ud800",
    ),
)
def test_sidecar_metadata_parser_rejects_noncanonical_or_unsafe_unicode_text(
    invalid_text: str,
) -> None:
    payload = {
        "request_id": str(uuid4()),
        "scope_fingerprint": sidecar_server.LOCAL_SCOPE_FINGERPRINT,
        "requested_model_fingerprint_sha256": "0" * 64,
        "text": invalid_text,
        "voice": "onnx.Zhiming",
        "seed": 0,
        "sample_mode": "fixed",
        "max_new_frames": 64,
    }

    with pytest.raises(sidecar_server.SidecarProtocolError) as captured:
        sidecar_server._parse_metadata(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            ),
            None,
        )

    assert captured.value.code == "TEXT_INVALID"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("schema", "OFFICIAL_PRESET_MANIFEST_SCHEMA_INVALID"),
        ("count", "OFFICIAL_PRESET_COUNT_MISMATCH"),
        ("duplicate", "OFFICIAL_PRESET_DUPLICATE"),
        ("empty_codes", "OFFICIAL_PRESET_PROMPT_CODES_INVALID"),
        ("wrong_quantizers", "OFFICIAL_PRESET_PROMPT_CODES_INVALID"),
        ("bool_code", "OFFICIAL_PRESET_PROMPT_CODES_INVALID"),
    ],
)
def test_official_preset_catalog_fails_closed_on_semantic_drift(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    manifest = official_preset_manifest()
    rows = manifest["builtin_voices"]
    assert isinstance(rows, list)
    if mutation == "schema":
        manifest.pop("tts_config")
    elif mutation == "count":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1]["voice"] = rows[0]["voice"]
    elif mutation == "empty_codes":
        rows[0]["prompt_audio_codes"] = []
    elif mutation == "wrong_quantizers":
        rows[0]["prompt_audio_codes"] = [[1] * 15]
    else:
        rows[0]["prompt_audio_codes"] = [[False] * 16]
    path, digest = write_test_preset_manifest(tmp_path, manifest)

    with pytest.raises(SidecarProtocolError) as caught:
        load_official_preset_catalog(path, expected_sha256=digest)

    assert caught.value.code == expected_code
    assert "987654321" not in str(caught.value)


def test_official_preset_catalog_rejects_missing_and_raw_hash_drift(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(SidecarProtocolError) as missing_caught:
        load_official_preset_catalog(missing)
    assert missing_caught.value.code == "OFFICIAL_PRESET_MANIFEST_MISSING"

    path, _ = write_test_preset_manifest(tmp_path)
    with pytest.raises(SidecarProtocolError) as hash_caught:
        load_official_preset_catalog(path, expected_sha256="0" * 64)
    assert hash_caught.value.code == "OFFICIAL_PRESET_MANIFEST_HASH_MISMATCH"


def test_dependency_verifier_projects_only_official_preset_count_and_hashes(
    tmp_path: Path,
) -> None:
    verifier_path = (
        Path(__file__).resolve().parents[2]
        / "docker"
        / "tts-sidecar"
        / "verify_runtime.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tts_sidecar_verify_runtime_test",
        verifier_path,
    )
    assert spec is not None and spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    path, digest = write_test_preset_manifest(tmp_path)
    verifier.EXPECTED_OFFICIAL_PRESET_MANIFEST_SHA256 = digest

    result = verifier.validate_official_preset_manifest(path)

    assert set(result) == {
        "preset_count",
        "manifest_sha256",
        "metadata_sha256",
    }
    assert result["preset_count"] == 18
    assert result["manifest_sha256"] == digest
    assert "prompt_audio_codes" not in repr(result)
    assert "987654321" not in repr(result)


class RecordingNanoRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def synthesize(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        output = Path(str(kwargs["output_audio_path"]))
        output.write_bytes(pcm_wav())
        return {"audio_path": output}


def ready_nano_backend(tmp_path: Path) -> tuple[NanoBackend, RecordingNanoRuntime]:
    path, digest = write_test_preset_manifest(tmp_path)
    backend = NanoBackend(lock_path=tmp_path / "unused.lock", assets_root=tmp_path)
    runtime = RecordingNanoRuntime()
    backend._runtime = runtime
    backend._official_preset_catalog = load_official_preset_catalog(
        path,
        expected_sha256=digest,
    )
    return backend, runtime


@pytest.mark.parametrize(
    "external",
    [f"onnx.{voice}" for voice in OFFICIAL_PRESET_TEST_NAMES],
)
def test_nano_backend_maps_exact_external_preset_to_manifest_voice(
    tmp_path: Path,
    external: str,
) -> None:
    backend, runtime = ready_nano_backend(tmp_path)

    backend.synthesize(nano_request(external), threading.Event())

    assert runtime.calls[-1]["voice"] == external.removeprefix("onnx.")
    assert runtime.calls[-1]["prompt_audio_path"] is None


@pytest.mark.parametrize(
    ("sample_mode", "seed", "expected_do_sample"),
    [
        ("fixed", 1, True),
        ("greedy", 0, False),
    ],
)
def test_nano_backend_forwards_candidate_decode_strategy_exactly(
    tmp_path: Path,
    sample_mode: str,
    seed: int,
    expected_do_sample: bool,
) -> None:
    backend, runtime = ready_nano_backend(tmp_path)

    backend.synthesize(
        nano_request(
            "onnx.Zhiming",
            seed=seed,
            sample_mode=sample_mode,
        ),
        threading.Event(),
    )

    assert runtime.calls[-1] == {
        "text": "official preset test",
        "voice": "Zhiming",
        "prompt_audio_path": None,
        "output_audio_path": runtime.calls[-1]["output_audio_path"],
        "sample_mode": sample_mode,
        "do_sample": expected_do_sample,
        "streaming": True,
        "max_new_frames": 64,
        "enable_wetext": False,
        "enable_normalize_tts_text": True,
        "seed": seed,
        "voice_clone_max_text_tokens": 750,
    }


@pytest.mark.parametrize(
    ("voice", "expected_code"),
    [
        ("Junhao", "OFFICIAL_PRESET_ID_INVALID"),
        ("onnx.Unknown", "OFFICIAL_PRESET_NOT_FOUND"),
        ("onnx.junhao", "OFFICIAL_PRESET_NOT_FOUND"),
    ],
)
def test_nano_backend_rejects_bare_unknown_and_case_guessed_presets(
    tmp_path: Path,
    voice: str,
    expected_code: str,
) -> None:
    backend, runtime = ready_nano_backend(tmp_path)

    with pytest.raises(SidecarProtocolError) as caught:
        backend.synthesize(nano_request(voice), threading.Event())

    assert caught.value.code == expected_code
    assert runtime.calls == []


def test_nano_backend_reference_audio_branch_keeps_existing_voice_semantics(
    tmp_path: Path,
) -> None:
    backend, runtime = ready_nano_backend(tmp_path)
    reference = ReferenceAudio(
        content_type="audio/wav",
        actual_sha256="0" * 64,
        payload=b"reference bytes",
        duration_seconds=1.0,
    )

    backend.synthesize(
        nano_request("custom_reference_voice", reference_audio=reference),
        threading.Event(),
    )

    assert runtime.calls[-1]["voice"] == "custom_reference_voice"
    prompt_path = runtime.calls[-1]["prompt_audio_path"]
    assert isinstance(prompt_path, Path)
    assert not prompt_path.exists()


def raw_response(
    server: SidecarHTTPServer,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    *,
    token: str | None = TOKEN,
    worker_token: str | None = None,
    version: str = PROTOCOL_VERSION,
    content_type: str = "application/json",
) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    headers = {"X-MOSS-Protocol-Version": version}
    if token is not None:
        headers["X-MOSS-Sidecar-Token"] = token
    if worker_token is not None:
        headers["X-MOSS-Worker-Token"] = worker_token
    if body is not None:
        headers.update({"Content-Type": content_type, "Content-Length": str(len(body))})
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def raw_json(
    server: SidecarHTTPServer,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    *,
    token: str | None = TOKEN,
    worker_token: str | None = None,
    version: str = PROTOCOL_VERSION,
    content_type: str = "application/json",
) -> tuple[int, dict[str, str], dict[str, object]]:
    status, headers, body = raw_response(
        server,
        method,
        path,
        payload,
        token=token,
        worker_token=worker_token,
        version=version,
        content_type=content_type,
    )
    return status, headers, json.loads(body.decode())


def acquire_worker(server: SidecarHTTPServer) -> tuple[str, int]:
    request_id = uuid4()
    status, _, row = raw_json(
        server,
        "POST",
        "/v1/lease/acquire",
        {"request_id": str(request_id)},
    )
    assert status == 200
    assert row["request_id"] == str(request_id)
    token = row["worker_token"]
    generation = row["lease_generation"]
    assert isinstance(token, str)
    assert isinstance(generation, int)
    return token, generation


def warmup_worker(
    server: SidecarHTTPServer,
    worker_token: str,
) -> dict[str, object]:
    status, _, row = raw_json(
        server,
        "POST",
        "/v1/warmup",
        {"request_id": str(uuid4())},
        token=None,
        worker_token=worker_token,
    )
    assert status == 200
    assert row["status"] == "ready"
    return row


def synthesis_payload(
    model_fingerprint_sha256: str,
    *,
    request_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "request_id": str(request_id or uuid4()),
        "scope_fingerprint": sidecar_server.LOCAL_SCOPE_FINGERPRINT,
        "requested_model_fingerprint_sha256": model_fingerprint_sha256,
        "text": "租约时序测试句段。",
        "voice": "narrator_neutral",
        "seed": 42,
        "sample_mode": "fixed",
        "max_new_frames": 64,
    }


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (b"short", "TOKEN_CONFIGURATION_INVALID"),
        (TOKEN.encode() + b"\n", "TOKEN_CONFIGURATION_INVALID"),
        (("x" * 257).encode(), "TOKEN_FILE_INVALID"),
        (b"x" * 129, "TOKEN_FILE_INVALID"),
        (b"x" * 31 + b" ", "TOKEN_CONFIGURATION_INVALID"),
        (b"x" * 31 + b"\x00", "TOKEN_CONFIGURATION_INVALID"),
        (b"x" * 31 + b"\x7f", "TOKEN_CONFIGURATION_INVALID"),
    ],
)
def test_secret_token_is_exact_and_rejects_weak_or_newline(tmp_path: Path, value: bytes, code: str) -> None:
    path = token_file(tmp_path, value)
    for reader, error_type in (
        (read_secret_token, SidecarRuntimeError),
        (read_server_secret_token, SidecarProtocolError),
    ):
        with pytest.raises(error_type) as caught:
            reader(path)
        assert caught.value.code == code


def test_secret_token_rejects_symlink(tmp_path: Path) -> None:
    real = token_file(tmp_path)
    link = tmp_path / "linked.secret"
    link.symlink_to(real)
    with pytest.raises(SidecarRuntimeError) as caught:
        read_secret_token(link)
    assert caught.value.code == "TOKEN_FILE_INVALID"
    with pytest.raises(SidecarProtocolError) as server_caught:
        read_server_secret_token(link)
    assert server_caught.value.code == "TOKEN_FILE_INVALID"


def test_both_token_readers_reject_group_or_world_accessible_mode(
    tmp_path: Path,
) -> None:
    path = token_file(tmp_path)
    path.chmod(0o640)

    with pytest.raises(SidecarRuntimeError) as runtime_caught:
        read_secret_token(path)
    with pytest.raises(SidecarProtocolError) as server_caught:
        read_server_secret_token(path)

    assert runtime_caught.value.code == "TOKEN_FILE_INVALID"
    assert server_caught.value.code == "TOKEN_FILE_INVALID"


def test_auth_version_and_query_token_fail_closed() -> None:
    with running_server() as (server, _):
        status, _, row = raw_json(server, "GET", "/v1/health", token=None)
        assert status == 401
        assert row["error"]["code"] == "AUTHENTICATION_FAILED"

        status, _, row = raw_json(server, "GET", "/v1/health", token="x" * len(TOKEN))
        assert status == 401
        assert row["error"]["code"] == "AUTHENTICATION_FAILED"

        status, _, row = raw_json(server, "GET", "/v1/health", version="wrong/1")
        assert status == 426
        assert row["error"]["code"] == "VERSION_MISMATCH"

        status, _, row = raw_json(server, "GET", f"/v1/health?token={TOKEN}", token=None)
        assert status == 400
        assert row["error"]["code"] == "QUERY_FORBIDDEN"


@pytest.mark.asyncio
async def test_adapter_projects_live_health_as_fixed_validation_metrics(
    tmp_path: Path,
) -> None:
    with running_server() as (server, state):
        adapter = adapter_for(tmp_path, server)
        await adapter.activate()
        assert (await adapter.warmup()).status is AdapterHealthStatus.HEALTHY
        with state.lock:
            state.active[str(uuid4())] = sidecar_server.ActiveRequest(
                threading.Event()
            )

        metrics = await adapter.observe_validation_metrics()

        assert metrics.model_ready is True
        assert metrics.worker_ready is True
        assert metrics.active_syntheses == 1
        assert metrics.queued_jobs == 0


def test_lease_acquire_renew_release_shapes_and_final_unload() -> None:
    with running_server() as (server, state):
        acquire_id = uuid4()
        status, headers, acquired = raw_json(
            server,
            "POST",
            "/v1/lease/acquire",
            {"request_id": str(acquire_id)},
        )

        assert status == 200
        assert frozenset(acquired) == {
            "protocol_version",
            "request_id",
            "status",
            "worker_token",
            "lease_ttl_seconds",
            "lease_generation",
            "worker",
        }
        assert acquired["protocol_version"] == PROTOCOL_VERSION
        assert acquired["request_id"] == str(acquire_id)
        assert acquired["status"] == "active"
        assert acquired["lease_ttl_seconds"] == sidecar_server.WORKER_LEASE_TTL_SECONDS
        assert frozenset(acquired["worker"]) == {
            "pid",
            "generation",
            "test_backend",
        }
        worker_token = acquired["worker_token"]
        lease_generation = acquired["lease_generation"]
        assert isinstance(worker_token, str) and len(worker_token) == 43
        assert isinstance(lease_generation, int) and lease_generation > 0
        assert headers["X-MOSS-Protocol-Version"] == PROTOCOL_VERSION
        assert headers["X-MOSS-Worker-Generation"] == str(state.generation)

        warmup_worker(server, worker_token)
        renew_id = uuid4()
        status, _, renewed = raw_json(
            server,
            "POST",
            "/v1/lease/renew",
            {"request_id": str(renew_id)},
            token=None,
            worker_token=worker_token,
        )
        assert status == 200
        assert frozenset(renewed) == {
            "protocol_version",
            "request_id",
            "status",
            "lease_ttl_seconds",
            "lease_generation",
            "worker",
        }
        assert renewed["protocol_version"] == PROTOCOL_VERSION
        assert renewed["request_id"] == str(renew_id)
        assert renewed["status"] == "renewed"
        assert renewed["lease_ttl_seconds"] == sidecar_server.WORKER_LEASE_TTL_SECONDS
        assert renewed["lease_generation"] == lease_generation
        assert frozenset(renewed["worker"]) == {
            "pid",
            "generation",
            "test_backend",
        }

        release_id = uuid4()
        status, _, released = raw_json(
            server,
            "POST",
            "/v1/lease/release",
            {"request_id": str(release_id)},
            token=None,
            worker_token=worker_token,
        )
        assert status == 202
        assert frozenset(released) == {
            "protocol_version",
            "request_id",
            "status",
            "lease_generation",
            "worker",
        }
        assert released["protocol_version"] == PROTOCOL_VERSION
        assert released["request_id"] == str(release_id)
        assert released["status"] == "release_requested"
        assert released["lease_generation"] == lease_generation
        assert frozenset(released["worker"]) == {
            "pid",
            "generation",
            "test_backend",
        }

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with state.lock:
                if state.status == "unloaded":
                    break
            time.sleep(0.005)
        status, _, health = raw_json(server, "GET", "/v1/health")
        assert status == 200
        assert health["status"] == "unloaded"
        assert health["ready"] is False
        assert health["lease"] == {
            "active": False,
            "generation": lease_generation,
        }
        assert health["model_fingerprint"] is None
        assert health["model_fingerprint_sha256"] is None
        assert state.backend.unload_count == 1


def test_control_and_worker_credentials_are_endpoint_scoped() -> None:
    with running_server() as (server, _):
        worker_token, _ = acquire_worker(server)

        for route in ("/v1/warmup", "/v1/cancel", "/v1/synthesize"):
            status, _, row = raw_json(
                server,
                "POST",
                route,
                {"request_id": str(uuid4())},
            )
            assert status == 401
            assert row["error"]["code"] == "WORKER_LEASE_INVALID"

        for route, payload in (
            ("/v1/lease/acquire", {"request_id": str(uuid4())}),
            (
                "/v1/restart",
                {"request_id": str(uuid4()), "reason_code": "AUTH_SCOPE_TEST"},
            ),
        ):
            status, _, row = raw_json(
                server,
                "POST",
                route,
                payload,
                token=None,
                worker_token=worker_token,
            )
            assert status == 401
            assert row["error"]["code"] == "AUTHENTICATION_FAILED"

        status, _, renewed = raw_json(
            server,
            "POST",
            "/v1/lease/renew",
            {"request_id": str(uuid4())},
            token=None,
            worker_token=worker_token,
        )
        assert status == 200
        assert renewed["status"] == "renewed"


def test_replacing_idle_lease_fences_old_token_without_aba_reuse() -> None:
    with running_server() as (server, _):
        old_token, old_generation = acquire_worker(server)
        current_token, current_generation = acquire_worker(server)

        assert current_token != old_token
        assert current_generation == old_generation + 1

        for method, route, payload in (
            ("GET", "/v1/health", None),
            ("POST", "/v1/lease/renew", {"request_id": str(uuid4())}),
            ("POST", "/v1/warmup", {"request_id": str(uuid4())}),
        ):
            status, _, row = raw_json(
                server,
                method,
                route,
                payload,
                token=None,
                worker_token=old_token,
            )
            assert status == 401
            assert row["error"]["code"] == "WORKER_LEASE_INVALID"

        status, _, renewed = raw_json(
            server,
            "POST",
            "/v1/lease/renew",
            {"request_id": str(uuid4())},
            token=None,
            worker_token=current_token,
        )
        assert status == 200
        assert renewed["lease_generation"] == current_generation


def test_watchdog_expires_lease_without_request_and_unloads_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_TTL_SECONDS", 0.08)
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_WATCHDOG_SECONDS", 0.005)
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_DRAIN_GRACE_SECONDS", 0.5)

    with running_server() as (server, state):
        worker_token, lease_generation = acquire_worker(server)
        warmup_worker(server, worker_token)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with state.lock:
                inert = state.worker_token is None and state.status == "unloaded"
            if inert and state.backend.unload_count == 1:
                break
            time.sleep(0.005)

        with state.lock:
            assert state.worker_token is None
            assert state.status == "unloaded"
            assert state.worker_lease_generation == lease_generation
        assert state.backend.unload_count == 1

        status, _, row = raw_json(
            server,
            "GET",
            "/v1/health",
            token=None,
            worker_token=worker_token,
        )
        assert status == 401
        assert row["error"]["code"] == "WORKER_LEASE_INVALID"

        status, _, health = raw_json(server, "GET", "/v1/health")
        assert status == 200
        assert health["lease"] == {
            "active": False,
            "generation": lease_generation,
        }
        assert health["status"] == "unloaded"


def test_active_request_expiry_never_publishes_audio_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_TTL_SECONDS", 0.12)
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_WATCHDOG_SECONDS", 0.005)
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_DRAIN_GRACE_SECONDS", 0.75)

    with running_server(step_delay_seconds=0.05) as (server, state):
        worker_token, _ = acquire_worker(server)
        warmed = warmup_worker(server, worker_token)
        fingerprint = warmed["model_fingerprint_sha256"]
        assert isinstance(fingerprint, str)
        result: list[tuple[int, dict[str, str], bytes]] = []

        thread = threading.Thread(
            target=lambda: result.append(
                raw_response(
                    server,
                    "POST",
                    "/v1/synthesize",
                    synthesis_payload(fingerprint),
                    token=None,
                    worker_token=worker_token,
                )
            )
        )
        thread.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with state.lock:
                if state.active:
                    break
            time.sleep(0.002)
        with state.lock:
            assert state.active
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert len(result) == 1
        status, headers, body = result[0]
        assert status != 200
        assert headers["Content-Type"] == "application/json"
        assert not body.startswith(b"RIFF")
        error = json.loads(body.decode())["error"]
        assert error["code"] in {"REQUEST_CANCELLED", "WORKER_LEASE_INVALID"}


def test_unload_scheduler_replays_release_that_arrives_during_prior_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with running_server() as (server, state):
        first_token, _ = acquire_worker(server)
        warmup_worker(server, first_token)
        original_finish_deactivate = state.finish_deactivate
        first_unload_finished = threading.Event()
        allow_first_teardown_to_return = threading.Event()
        calls = 0

        def reordered_finish_deactivate(timeout_seconds: float) -> bool:
            nonlocal calls
            calls += 1
            result = original_finish_deactivate(timeout_seconds)
            if calls == 1:
                first_unload_finished.set()
                assert allow_first_teardown_to_return.wait(timeout=2)
            return result

        monkeypatch.setattr(state, "finish_deactivate", reordered_finish_deactivate)
        try:
            status, _, _ = raw_json(
                server,
                "POST",
                "/v1/lease/release",
                {"request_id": str(uuid4())},
                token=None,
                worker_token=first_token,
            )
            assert status == 202
            assert first_unload_finished.wait(timeout=2)

            second_token, second_generation = acquire_worker(server)
            status, _, released = raw_json(
                server,
                "POST",
                "/v1/lease/release",
                {"request_id": str(uuid4())},
                token=None,
                worker_token=second_token,
            )
            assert status == 202
            assert released["lease_generation"] == second_generation
        finally:
            allow_first_teardown_to_return.set()

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with state.lock:
                unloaded = state.status == "unloaded" and state.worker_token is None
            if unloaded and state.backend.unload_count == 2:
                break
            time.sleep(0.005)

        with state.lock:
            assert state.status == "unloaded"
            assert state.worker_token is None
            assert state.worker_lease_generation == second_generation
        assert state.backend.unload_count == 2
        assert calls == 2


def test_stalled_backend_unload_is_bounded_and_forces_poison_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sidecar_server, "WORKER_LEASE_DRAIN_GRACE_SECONDS", 0.05)
    unload_entered = threading.Event()
    allow_unload_to_return = threading.Event()
    unload_returned = threading.Event()

    with running_server() as (server, state):
        worker_token, _ = acquire_worker(server)
        warmup_worker(server, worker_token)

        def stalled_unload() -> None:
            unload_entered.set()
            allow_unload_to_return.wait(timeout=2)
            unload_returned.set()

        monkeypatch.setattr(state.backend, "unload", stalled_unload)
        started_at = time.monotonic()
        try:
            status, _, released = raw_json(
                server,
                "POST",
                "/v1/lease/release",
                {"request_id": str(uuid4())},
                token=None,
                worker_token=worker_token,
            )
            assert status == 202
            assert released["status"] == "release_requested"
            assert unload_entered.wait(timeout=1)

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                with state.lock:
                    poisoned = state.poisoned and state.status == "poisoned"
                if poisoned and server._restart_scheduled:
                    break
                time.sleep(0.002)

            elapsed = time.monotonic() - started_at
            with state.lock:
                assert state.poisoned is True
                assert state.status == "poisoned"
                assert state.worker_token is None
                assert state.model_fingerprint is None
                assert state.model_fingerprint_sha256 is None
            assert server._restart_scheduled is True
            assert elapsed < 0.75
        finally:
            allow_unload_to_return.set()
            assert unload_returned.wait(timeout=1)


@pytest.mark.asyncio
async def test_health_does_not_claim_ready_until_warmup(tmp_path: Path) -> None:
    with running_server() as (server, _):
        adapter = adapter_for(tmp_path, server)
        await adapter.activate()
        before = await adapter.health()
        assert before.status is AdapterHealthStatus.DEGRADED
        assert before.model_fingerprint_sha256 is None

        warmed = await adapter.warmup()
        assert warmed.status is AdapterHealthStatus.HEALTHY
        assert warmed.model_fingerprint_sha256 is not None
        assert (await adapter.model_fingerprint()) is not None


@pytest.mark.asyncio
async def test_adapter_activate_renew_warmup_and_deactivate_is_inert(
    tmp_path: Path,
) -> None:
    with running_server() as (server, state):
        adapter = adapter_for(tmp_path, server)

        lease_generation = await adapter.activate()
        assert adapter.worker_lease_active is True
        assert await adapter.renew_lease() == lease_generation
        assert (await adapter.warmup()).status is AdapterHealthStatus.HEALTHY

        await adapter.deactivate()

        assert adapter.worker_lease_active is False
        assert adapter.lease_generation is None
        health = await adapter.health()
        assert health.status is AdapterHealthStatus.UNAVAILABLE
        assert health.reason_code == "WORKER_LEASE_INACTIVE"
        with state.lock:
            assert state.worker_token is None
            assert state.status == "unloaded"
        assert state.backend.unload_count == 1


@pytest.mark.asyncio
async def test_deactivate_accepts_lost_release_response_only_with_same_lease_inert_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = RecordingLifecycle()
    with running_server() as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        lease_generation = await adapter.activate()
        await adapter.warmup()
        worker_generation = state.generation
        original_request_json = adapter._request_json

        def lose_release_response(method, path, payload=None, **kwargs):  # noqa: ANN001, ANN003
            result = original_request_json(method, path, payload, **kwargs)
            if path == "/v1/lease/release":
                raise TimeoutError("injected response loss after accepted release")
            return result

        monkeypatch.setattr(adapter, "_request_json", lose_release_response)

        await adapter.deactivate()

        assert lifecycle.reasons == []
        assert state.generation == worker_generation
        with state.lock:
            assert state.worker_token is None
            assert state.worker_lease_generation == lease_generation
            assert state.status == "unloaded"
        assert state.backend.unload_count == 1


@pytest.mark.asyncio
async def test_deactivate_restarts_when_lost_release_has_different_lease_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = RecordingLifecycle()
    with running_server() as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        lease_generation = await adapter.activate()
        await adapter.warmup()
        original_request_json = adapter._request_json

        def replace_lease_then_lose_release(
            method, path, payload=None, **kwargs  # noqa: ANN001, ANN003
        ):
            if path == "/v1/lease/release":
                with state.lock:
                    state.worker_token = None
                    state.worker_lease_deadline = None
                    state.worker_lease_generation = lease_generation + 1
                    state.status = "unloaded"
                    state.model_fingerprint = None
                    state.model_fingerprint_sha256 = None
                raise TimeoutError("injected lost response with different lease evidence")
            return original_request_json(method, path, payload, **kwargs)

        monkeypatch.setattr(adapter, "_request_json", replace_lease_then_lose_release)

        await adapter.deactivate()

        assert lifecycle.reasons == ["WORKER_LEASE_RELEASE_FAILED"]
        assert lifecycle.previous_generations == [None]
        assert state.worker_lease_generation == lease_generation + 1


def test_ready_model_header_matches_body_when_state_changes_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_json = SidecarHandler._json
    transitioned = threading.Event()

    def drain_after_payload_snapshot(self, status, payload):  # noqa: ANN001
        if (
            not transitioned.is_set()
            and payload.get("status") == "ready"
            and isinstance(payload.get("model_fingerprint_sha256"), str)
        ):
            transitioned.set()
            with self.state.lock:
                self.state._begin_deactivate_locked()
        return original_json(self, status, payload)

    monkeypatch.setattr(SidecarHandler, "_json", drain_after_payload_snapshot)
    with running_server() as (server, state):
        worker_token, _ = acquire_worker(server)
        status, headers, row = raw_json(
            server,
            "POST",
            "/v1/warmup",
            {"request_id": str(uuid4())},
            token=None,
            worker_token=worker_token,
        )

        assert transitioned.is_set()
        assert status == 200
        assert row["status"] == "ready"
        assert row["ready"] is True
        assert isinstance(row["model_fingerprint_sha256"], str)
        assert (
            headers["X-MOSS-Actual-Model-Fingerprint-SHA256"]
            == row["model_fingerprint_sha256"]
        )
        with state.lock:
            assert state.status == "draining"
            assert state.model_fingerprint_sha256 is None
        server.schedule_unload()


@pytest.mark.asyncio
async def test_ordinary_synthesis_returns_verified_actual_bytes_and_generation(tmp_path: Path) -> None:
    with running_server() as (server, state):
        adapter = adapter_for(tmp_path, server)
        await adapter.activate()
        assert (await adapter.warmup()).status is AdapterHealthStatus.HEALTHY
        request = synthesis_request()

        result = await adapter.synthesize(request)

        assert result.request_id == request.request_id
        assert result.actual_output_sha256 == hashlib.sha256(result.audio_bytes).hexdigest()
        assert (result.sample_rate_hz, result.channels, result.sample_width_bytes) == (48_000, 2, 2)
        assert result.worker_generation == state.generation
        assert not state.active


@pytest.mark.asyncio
async def test_reference_audio_uses_inline_bytes_and_actual_hash(tmp_path: Path) -> None:
    with running_server() as (server, _):
        adapter = adapter_for(tmp_path, server)
        await adapter.activate()
        await adapter.warmup()

        result = await adapter.synthesize(synthesis_request(reference=reference_wav()))

        assert result.actual_output_sha256 == hashlib.sha256(result.audio_bytes).hexdigest()


@pytest.mark.asyncio
async def test_cancel_not_found_inflight_segment_boundary_and_success_terminal(tmp_path: Path) -> None:
    with running_server(step_delay_seconds=0.05) as (server, state):
        adapter = adapter_for(tmp_path, server)
        await adapter.activate()
        await adapter.warmup()
        unknown = uuid4()
        assert await adapter.cancel(unknown) is CancelDisposition.NOT_FOUND

        request = synthesis_request()
        task = asyncio.create_task(adapter.synthesize(request))
        for _ in range(100):
            if str(request.request_id) in state.active:
                break
            await asyncio.sleep(0.005)
        assert str(request.request_id) in state.active
        assert await adapter.cancel(request.request_id) is CancelDisposition.REQUESTED
        with pytest.raises(SidecarRuntimeError) as caught:
            await task
        assert caught.value.code == "REQUEST_CANCELLED"
        assert await adapter.cancel(request.request_id) is CancelDisposition.ALREADY_TERMINAL

        completed = synthesis_request()
        await adapter.synthesize(completed)
        assert await adapter.cancel(completed.request_id) is CancelDisposition.ALREADY_TERMINAL


def test_strict_request_uuid_content_type_and_body_fields() -> None:
    with running_server() as (server, _):
        worker_token, _ = acquire_worker(server)
        for payload, expected in (
            ({"request_id": "not-a-uuid"}, "REQUEST_ID_INVALID"),
            ({"request_id": str(uuid4()), "extra": True}, "REQUEST_FIELDS_INVALID"),
        ):
            status, _, row = raw_json(
                server,
                "POST",
                "/v1/warmup",
                payload,
                token=None,
                worker_token=worker_token,
            )
            assert status == 400
            assert row["error"]["code"] == expected
        status, _, row = raw_json(
            server,
            "POST",
            "/v1/warmup",
            {"request_id": str(uuid4())},
            token=None,
            worker_token=worker_token,
            content_type="text/plain",
        )
        assert status == 415
        assert row["error"]["code"] == "CONTENT_TYPE_INVALID"


@pytest.mark.asyncio
async def test_backend_failure_poisons_and_requests_managed_restart(tmp_path: Path) -> None:
    lifecycle = RecordingLifecycle()
    with running_server(fail_mode="crash") as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        await adapter.activate()
        await adapter.warmup()
        failed_generation = state.generation

        with pytest.raises(SidecarRuntimeError) as caught:
            await adapter.synthesize(synthesis_request())

        assert caught.value.code == "BACKEND_FAILURE"
        assert lifecycle.observed_poisoned == [True]
        assert lifecycle.reasons == ["BACKEND_FAILURE"]
        assert lifecycle.previous_generations == [failed_generation]
        assert state.generation == failed_generation + 1
        assert state.poisoned is False


def test_authenticated_restart_endpoint_poison_exits_server() -> None:
    with running_server() as (server, state):
        request_id = uuid4()
        status, _, row = raw_json(
            server,
            "POST",
            "/v1/restart",
            {"request_id": str(request_id), "reason_code": "TEST_RESTART"},
        )

        assert status == 202
        assert row["request_id"] == str(request_id)
        assert row["status"] == "restart_requested"
        assert row["worker"]["generation"] == state.generation
        assert state.poisoned is True
        assert server._restart_scheduled is True


@pytest.mark.asyncio
async def test_supervisor_lifecycle_requires_new_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = SupervisorManagedSidecarLifecycle(
        SidecarRuntimeConfig(
            host="tts-sidecar",
            port=8765,
            token_file=token_file(tmp_path),
            timeout_seconds=1,
        ),
        restart_timeout_seconds=2,
        poll_interval_seconds=0.05,
    )
    generations = iter((41, 41, 42))
    requested: list[str] = []
    monkeypatch.setattr(lifecycle, "_probe_generation", lambda: next(generations))
    monkeypatch.setattr(
        lifecycle,
        "_request_restart",
        lambda reason: requested.append(reason) or 41,
    )

    await lifecycle.restart_after_poison(
        "BACKEND_FAILURE", previous_generation=41
    )

    assert requested == ["BACKEND_FAILURE"]


def test_environment_factory_is_disabled_by_default_and_frozen_when_enabled(
    tmp_path: Path,
) -> None:
    assert build_moss_adapter_from_environment({}) is None
    environment = {
        "AI_NOVEL_TTS_RUNTIME_ENABLED": "true",
        "MOSS_TTS_PROTOCOL_VERSION": PROTOCOL_VERSION,
        "MOSS_TTS_EXPECTED_MODEL_FINGERPRINT_SHA256": (
            EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
        ),
        "MOSS_TTS_LIFECYCLE": "compose_on_failure_supervisor",
        "MOSS_TTS_SIDECAR_HOST": "tts-sidecar",
        "MOSS_TTS_SIDECAR_PORT": "8765",
        "MOSS_TTS_SIDECAR_TOKEN_FILE": str(token_file(tmp_path)),
        "MOSS_TTS_REQUEST_TIMEOUT_SECONDS": "120",
    }

    adapter = build_moss_adapter_from_environment(environment)

    assert isinstance(adapter, SidecarMossNanoTTSAdapter)
    assert adapter.capabilities.product_visible is False
    assert adapter.capabilities.production_ready is False
    with pytest.raises(ContractError):
        build_moss_adapter_from_environment(
            {**environment, "MOSS_TTS_PROTOCOL_VERSION": "moss-tts-sidecar/0"}
        )


def test_disabled_environment_factory_reads_no_token_and_opens_no_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_reads = 0
    connection_attempts = 0

    def forbidden_token_read(_path: Path) -> str:
        nonlocal token_reads
        token_reads += 1
        raise AssertionError("disabled factory must not read the bootstrap token")

    def forbidden_connection(*_args, **_kwargs):  # noqa: ANN002, ANN003
        nonlocal connection_attempts
        connection_attempts += 1
        raise AssertionError("disabled factory must not access the Sidecar")

    monkeypatch.setattr(narration_runtime, "read_secret_token", forbidden_token_read)
    monkeypatch.setattr(narration_runtime, "HTTPConnection", forbidden_connection)

    adapter = narration_runtime.build_moss_adapter_from_environment(
        {
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "false",
            "MOSS_TTS_SIDECAR_TOKEN_FILE": "/must/not/be/read",
            "MOSS_TTS_SIDECAR_HOST": "must-not-be-contacted",
        }
    )

    assert adapter is None
    assert token_reads == 0
    assert connection_attempts == 0


def test_enabled_environment_factory_reads_bootstrap_token_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = token_file(tmp_path)
    reads: list[Path] = []
    connection_attempts = 0

    def counted_token_read(candidate: Path) -> str:
        reads.append(candidate)
        return TOKEN

    def forbidden_connection(*_args, **_kwargs):  # noqa: ANN002, ANN003
        nonlocal connection_attempts
        connection_attempts += 1
        raise AssertionError("factory construction must not access the Sidecar")

    monkeypatch.setattr(narration_runtime, "read_secret_token", counted_token_read)
    monkeypatch.setattr(narration_runtime, "HTTPConnection", forbidden_connection)
    adapter = narration_runtime.build_moss_adapter_from_environment(
        {
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "true",
            "MOSS_TTS_PROTOCOL_VERSION": PROTOCOL_VERSION,
            "MOSS_TTS_EXPECTED_MODEL_FINGERPRINT_SHA256": (
                EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
            ),
            "MOSS_TTS_LIFECYCLE": "compose_on_failure_supervisor",
            "MOSS_TTS_SIDECAR_HOST": "tts-sidecar",
            "MOSS_TTS_SIDECAR_PORT": "8765",
            "MOSS_TTS_SIDECAR_TOKEN_FILE": str(path),
            "MOSS_TTS_REQUEST_TIMEOUT_SECONDS": "120",
        }
    )

    assert isinstance(adapter, SidecarMossNanoTTSAdapter)
    assert reads == [path]
    assert connection_attempts == 0
    assert adapter._bootstrap_token == TOKEN
    assert isinstance(adapter._lifecycle, SupervisorManagedSidecarLifecycle)
    assert adapter._lifecycle._token == TOKEN


@pytest.mark.asyncio
async def test_restart_creates_new_generation_and_old_adapter_observes_change(tmp_path: Path) -> None:
    with running_server() as (first, first_state):
        first_adapter = adapter_for(tmp_path, first)
        await first_adapter.activate()
        await first_adapter.warmup()
        first_generation = first_state.generation
    with running_server() as (second, second_state):
        second_adapter = adapter_for(tmp_path, second)
        await second_adapter.activate()
        await second_adapter.warmup()
        assert second_state.generation != first_generation


def test_production_factory_and_di_reject_test_double(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="test backend"):
        build_production_moss_adapter(
            SidecarRuntimeConfig(
                host="127.0.0.1",
                port=8765,
                token_file=token_file(tmp_path),
                allow_test_backend=True,
            )
        )
    with pytest.raises(ContractError, match="test-double"):
        ensure_production_adapter(FakeMossNanoTTSAdapter())

    production = SidecarRuntimeConfig(
        host="tts-sidecar",
        port=8765,
        token_file=token_file(tmp_path),
    )
    with pytest.raises(ContractError, match="managed lifecycle"):
        build_production_moss_adapter(production)
    with pytest.raises(ContractError, match="managed lifecycle"):
        build_production_moss_adapter(
            production,
            lifecycle=NoopSidecarLifecycle(),
        )
    assert isinstance(
        build_production_moss_adapter(
            production,
            lifecycle=RecordingLifecycle(),
        ),
        SidecarMossNanoTTSAdapter,
    )


def test_production_config_rejects_loopback_and_ip(tmp_path: Path) -> None:
    for host in (
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "10.0.0.2",
        "attacker.example",
        "tts-sidecar.internal",
    ):
        with pytest.raises(ContractError):
            SidecarRuntimeConfig(host=host, port=8765, token_file=token_file(tmp_path))
    with pytest.raises(ContractError):
        SidecarRuntimeConfig(
            host="tts-sidecar",
            port=8766,
            token_file=token_file(tmp_path),
        )

    accepted = SidecarRuntimeConfig(
        host="tts-sidecar",
        port=8765,
        token_file=token_file(tmp_path),
    )
    assert (accepted.host, accepted.port) == ("tts-sidecar", 8765)


def _ready_response(
    fingerprint: dict[str, object],
    *,
    generation: int = 17,
) -> tuple[dict[str, object], dict[str, str]]:
    digest = _model_fingerprint_sha256(fingerprint)
    return (
        {
            "protocol_version": PROTOCOL_VERSION,
            "status": "ready",
            "ready": True,
            "capabilities_sha256": sidecar_server.CAPABILITIES_SHA256,
            "model_fingerprint": fingerprint,
            "model_fingerprint_sha256": digest,
            "lease": {"active": True, "generation": 1},
            "worker": {
                "pid": os.getpid(),
                "generation": generation,
                "test_backend": True,
                "active_request_count": 0,
            },
        },
        {
            "x-moss-worker-generation": str(generation),
            "x-moss-actual-model-fingerprint-sha256": digest,
        },
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_contract_version", "moss-nano-tts-adapter/2"),
        ("protocol_version", "moss-tts-sidecar/0.9"),
        ("deployment_topology", "public_cloud_endpoint"),
        ("runtime_version", "1.24.4"),
        ("execution_backend", "coreml"),
    ],
)
def test_ready_rejects_internally_consistent_but_unfrozen_model_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    adapter = SidecarMossNanoTTSAdapter(
        SidecarRuntimeConfig(
            host="127.0.0.1",
            port=1,
            token_file=token_file(tmp_path),
            allow_test_backend=True,
        )
    )
    fingerprint = dict(FakeBackend().warmup())
    fingerprint[field] = value
    row, headers = _ready_response(fingerprint)

    with pytest.raises(SidecarRuntimeError) as caught:
        adapter._consume_ready(row, headers)

    assert caught.value.code == "MODEL_FINGERPRINT_MISMATCH"
    assert caught.value.poison is True


def test_frozen_production_model_digest_is_the_reviewed_identity() -> None:
    assert EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256 == (
        "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
    )


@pytest.mark.asyncio
async def test_new_generation_unloaded_health_clears_cached_identity(
    tmp_path: Path,
) -> None:
    with running_server() as (server, state):
        adapter = adapter_for(tmp_path, server)
        await adapter.activate()
        assert (await adapter.warmup()).status is AdapterHealthStatus.HEALTHY
        old_generation = adapter._generation
        with state.lock:
            state.generation = state.generation + 1
            state.status = "unloaded"
            state.model_fingerprint = None
            state.model_fingerprint_sha256 = None

        health = await adapter.health()

        assert health.status is AdapterHealthStatus.DEGRADED
        assert old_generation is not None
        assert adapter._generation is None
        assert adapter._fingerprint is None
        assert adapter._fingerprint_sha256 is None
        assert await adapter.model_fingerprint() is None


@pytest.mark.asyncio
async def test_cancel_rejects_new_generation_even_when_disposition_is_not_found(
    tmp_path: Path,
) -> None:
    lifecycle = RecordingLifecycle()
    with running_server() as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        await adapter.activate()
        await adapter.warmup()
        with state.lock:
            state.generation += 1

        with pytest.raises(SidecarRuntimeError) as caught:
            await adapter.cancel(uuid4())

        assert caught.value.code == "WORKER_GENERATION_MISMATCH"
        assert lifecycle.reasons == ["WORKER_GENERATION_MISMATCH"]


@pytest.mark.asyncio
async def test_cancel_rejects_wrong_request_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = RecordingLifecycle()
    original_json = SidecarHandler._json

    def wrong_cancel_id(self, status, payload):  # noqa: ANN001
        if "disposition" in payload:
            payload = {**payload, "request_id": str(uuid4())}
        return original_json(self, status, payload)

    monkeypatch.setattr(SidecarHandler, "_json", wrong_cancel_id)
    with running_server() as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        await adapter.activate()
        await adapter.warmup()

        with pytest.raises(SidecarRuntimeError) as caught:
            await adapter.cancel(uuid4())

        assert caught.value.code == "REQUEST_IDENTITY_MISMATCH"
        assert lifecycle.reasons == ["REQUEST_IDENTITY_MISMATCH"]


@pytest.mark.asyncio
async def test_synthesis_error_rejects_wrong_request_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = RecordingLifecycle()
    original_error = SidecarHandler._error

    def wrong_error_id(self, error, request_id=None):  # noqa: ANN001
        return original_error(self, error, str(uuid4()))

    monkeypatch.setattr(SidecarHandler, "_error", wrong_error_id)
    with running_server(fail_mode="crash") as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        await adapter.activate()
        await adapter.warmup()

        with pytest.raises(SidecarRuntimeError) as caught:
            await adapter.synthesize(synthesis_request())

        assert caught.value.code == "SYNTHESIS_ERROR_IDENTITY_MISMATCH"
        assert lifecycle.reasons == ["SYNTHESIS_ERROR_IDENTITY_MISMATCH"]


@pytest.mark.parametrize("mutation", ["truncated", "trailing"])
def test_output_and_reference_wav_require_complete_frames_and_no_trailing_bytes(
    mutation: str,
) -> None:
    output = pcm_wav()
    reference = pcm_wav(sample_rate=16_000, channels=1, frames=1_600)
    if mutation == "truncated":
        output = output[:-1]
        reference = reference[:-1]
    else:
        output += b"x"
        reference += b"x"

    with pytest.raises(SidecarProtocolError) as output_caught:
        _validate_wav(output)
    with pytest.raises(SidecarRuntimeError) as client_caught:
        _validate_complete_pcm_wav(output)
    with pytest.raises(SidecarProtocolError) as reference_caught:
        _inspect_reference(reference, "audio/wav")

    assert output_caught.value.code == "AUDIO_TRAILING_OR_TRUNCATED"
    assert client_caught.value.code == "AUDIO_TRAILING_OR_TRUNCATED"
    assert reference_caught.value.code == "REFERENCE_TRAILING_OR_TRUNCATED"


def test_reference_wav_enforces_decoded_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = pcm_wav(sample_rate=16_000, channels=1, frames=100)
    monkeypatch.setattr(sidecar_server, "MAX_REFERENCE_DECODED_BYTES", 100)

    with pytest.raises(SidecarProtocolError) as caught:
        _inspect_reference(payload, "audio/wav")

    assert caught.value.code == "REFERENCE_FORMAT_INVALID"


def test_flac_reference_uses_bounded_complete_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSoundFile:
        samplerate = 16_000
        channels = 1
        frames = 4
        format = "FLAC"

        def __init__(self, _payload, mode):  # noqa: ANN001
            assert mode == "r"
            self.remaining = self.frames

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def buffer_read(self, frames, dtype):  # noqa: ANN001
            assert dtype == "int16"
            count = min(frames, self.remaining)
            self.remaining -= count
            return b"\x00\x00" * count

    class FakeSoundFileModule:
        SoundFile = FakeSoundFile

    monkeypatch.setattr(
        sidecar_server,
        "_load_soundfile",
        lambda: FakeSoundFileModule,
    )

    assert _inspect_reference(b"fake-compressed-flac", "audio/flac") == pytest.approx(
        4 / 16_000
    )


def test_flac_reference_fails_closed_without_fixed_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):  # noqa: ANN001
        if name == "soundfile":
            raise ImportError("injected missing fixed decoder")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SidecarProtocolError) as caught:
        sidecar_server._load_soundfile()

    assert caught.value.code == "REFERENCE_DECODER_UNAVAILABLE"


def test_sidecar_warmup_is_singleflight_across_concurrent_requests() -> None:
    class CountingBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self.active = 0
            self.maximum = 0
            self.counter_lock = threading.Lock()

        def warmup(self):
            with self.counter_lock:
                self.calls += 1
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(0.05)
            try:
                return super().warmup()
            finally:
                with self.counter_lock:
                    self.active -= 1

    backend = CountingBackend()
    state = SidecarState(TOKEN, backend)
    worker_token, _ = state.acquire_worker_lease()
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def invoke() -> None:
        barrier.wait()
        try:
            state.warmup(worker_token)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert not errors
    assert backend.calls == 1
    assert backend.maximum == 1
    assert state.status == "ready"


@pytest.mark.asyncio
async def test_cancelled_to_thread_keeps_inference_fence_until_worker_finishes(
    tmp_path: Path,
) -> None:
    lifecycle = RecordingLifecycle()
    with running_server(step_delay_seconds=0.05) as (server, state):
        lifecycle.state = state
        adapter = adapter_for(tmp_path, server, lifecycle=lifecycle)
        await adapter.activate()
        await adapter.warmup()
        first = asyncio.create_task(adapter.synthesize(synthesis_request()))
        for _ in range(100):
            if state.active:
                break
            await asyncio.sleep(0.005)
        assert state.active

        first.cancel()
        second = asyncio.create_task(adapter.synthesize(synthesis_request()))
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(SidecarRuntimeError) as second_caught:
            await second

        assert second_caught.value.code == "MODEL_NOT_READY"
        assert not state.active
        assert lifecycle.reasons == ["SYNTHESIS_CALL_CANCELLED"]


@pytest.mark.asyncio
async def test_poison_restarts_are_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowLifecycle:
        def __init__(self) -> None:
            self.active = 0
            self.maximum = 0

        async def restart_after_poison(
            self,
            _reason_code: str,
            *,
            previous_generation: int | None = None,
        ) -> None:
            del previous_generation
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1

    lifecycle = SlowLifecycle()
    adapter = SidecarMossNanoTTSAdapter(
        SidecarRuntimeConfig(
            host="127.0.0.1",
            port=1,
            token_file=token_file(tmp_path),
            allow_test_backend=True,
        ),
        lifecycle=lifecycle,
    )

    async def reacquire_after_fake_restart() -> int:
        return 1

    monkeypatch.setattr(adapter, "activate", reacquire_after_fake_restart)

    await asyncio.gather(
        adapter._poison_and_restart(
            SidecarRuntimeError("FIRST_POISON", "redacted", poison=True)
        ),
        adapter._poison_and_restart(
            SidecarRuntimeError("SECOND_POISON", "redacted", poison=True)
        ),
    )

    assert lifecycle.maximum == 1


class FakeDockerLifecycle(DockerComposeSidecarLifecycle):
    def __init__(
        self,
        root: Path,
        *,
        image_ref: str = "example.invalid/moss-sidecar:production",
        expected_digest: str = "sha256:" + "a" * 64,
        digest_kind: str = "local_image_id",
    ) -> None:
        super().__init__(
            repository_root=root,
            image_ref=image_ref,
            expected_digest=expected_digest,
            digest_kind=digest_kind,  # type: ignore[arg-type]
        )
        self.commands: list[tuple[str, ...]] = []
        self.compose_image = image_ref
        self.container_id = "b" * 64
        self.image_row: dict[str, object] = {
            "Id": "sha256:" + "a" * 64,
            "RepoDigests": [],
            "Architecture": "arm64",
            "Config": {
                "Labels": {
                    "ai.novel.world.work-package": "T1-B",
                    "ai.novel.world.business-runtime": "present",
                },
                "Entrypoint": list(EXPECTED_PRODUCTION_ENTRYPOINT),
            },
        }
        self.container_row: dict[str, object] = {
            "State": {"Running": True},
            "Image": "sha256:" + "a" * 64,
            "Config": {
                "Image": image_ref,
                "Labels": {
                    "ai.novel.world.work-package": "T1-B",
                    "ai.novel.world.business-runtime": "present",
                },
                "Entrypoint": list(EXPECTED_PRODUCTION_ENTRYPOINT),
            },
        }
        self.fail_up = False

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(tuple(command))
        if command[-3:] == ["config", "--format", "json"]:
            output = json.dumps(
                {"services": {"tts-sidecar": {"image": self.compose_image}}}
            )
        elif command[:3] == ["docker", "image", "inspect"]:
            output = json.dumps(self.image_row)
        elif command[-3:] == ["ps", "--quiet", "tts-sidecar"]:
            output = self.container_id + "\n"
        elif command[:3] == ["docker", "container", "inspect"]:
            output = json.dumps(self.container_row)
        else:
            output = ""
        if self.fail_up and "up" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


def test_image_lifecycle_builds_verifies_starts_without_build_and_inspects_running_id(
    tmp_path: Path,
) -> None:
    lifecycle = FakeDockerLifecycle(tmp_path)

    verification = lifecycle.build_and_start()

    assert verification.digest_kind == "local_image_id"
    assert verification.observed_repo_digests == ()
    assert verification.running_container_id == "b" * 64
    build_index = next(i for i, command in enumerate(lifecycle.commands) if "build" in command)
    inspect_index = next(
        i
        for i, command in enumerate(lifecycle.commands)
        if command[:3] == ("docker", "image", "inspect")
    )
    up_index = next(i for i, command in enumerate(lifecycle.commands) if "up" in command)
    assert build_index < inspect_index < up_index
    assert "--pull" in lifecycle.commands[build_index]
    assert "--no-cache" in lifecycle.commands[build_index]
    assert "--no-build" in lifecycle.commands[up_index]
    assert "--build" not in lifecycle.commands[up_index]


@pytest.mark.parametrize(
    ("label", "value", "code"),
    [
        ("ai.novel.world.work-package", "T1-DEP", "IMAGE_LABEL_MISMATCH"),
        ("ai.novel.world.business-runtime", "absent", "IMAGE_RUNTIME_ABSENT"),
    ],
)
def test_image_lifecycle_rejects_dependency_or_absent_runtime_labels(
    tmp_path: Path,
    label: str,
    value: str,
    code: str,
) -> None:
    lifecycle = FakeDockerLifecycle(tmp_path)
    lifecycle.image_row["Config"]["Labels"][label] = value  # type: ignore[index]

    with pytest.raises(SidecarRuntimeError) as caught:
        lifecycle.build_and_start()

    assert caught.value.code == code
    assert not any("up" in command for command in lifecycle.commands)


def test_image_lifecycle_rejects_different_compose_image_before_build(
    tmp_path: Path,
) -> None:
    lifecycle = FakeDockerLifecycle(tmp_path)
    lifecycle.compose_image = "example.invalid/moss-sidecar:other"

    with pytest.raises(SidecarRuntimeError) as caught:
        lifecycle.build_and_start()

    assert caught.value.code == "COMPOSE_IMAGE_MISMATCH"
    assert len(lifecycle.commands) == 1


@pytest.mark.parametrize("failure", ["bad_container_id", "wrong_image_id", "up"])
def test_image_lifecycle_failed_start_is_cleaned(
    tmp_path: Path,
    failure: str,
) -> None:
    lifecycle = FakeDockerLifecycle(tmp_path)
    if failure == "bad_container_id":
        lifecycle.container_id = "not-a-container-id"
    elif failure == "wrong_image_id":
        lifecycle.container_row["Image"] = "sha256:" + "c" * 64
    else:
        lifecycle.fail_up = True

    with pytest.raises((SidecarRuntimeError, subprocess.CalledProcessError)):
        lifecycle.build_and_start()

    assert any(
        command[-4:] == ("rm", "--stop", "--force", "tts-sidecar")
        for command in lifecycle.commands
    )


def test_registry_manifest_digest_is_not_conflated_with_local_image_id(
    tmp_path: Path,
) -> None:
    digest = "sha256:" + "d" * 64
    lifecycle = FakeDockerLifecycle(
        tmp_path,
        expected_digest=digest,
        digest_kind="registry_manifest",
    )
    lifecycle.image_row["Id"] = "sha256:" + "a" * 64
    lifecycle.image_row["RepoDigests"] = [
        f"example.invalid/moss-sidecar@{digest}"
    ]

    verified = lifecycle.verify_image()

    assert verified.digest_kind == "registry_manifest"
    assert verified.observed_image_id != digest
    assert verified.observed_repo_digests == (
        f"example.invalid/moss-sidecar@{digest}",
    )
