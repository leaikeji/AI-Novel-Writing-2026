"""Verify the installed AI小说世界2026 contract against a local QwenPaw lab."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID


APP_ID = "ai-novel-world-2026"
APP_VERSION = "0.4.0"
NOVEL_AGENT_ID = "ai-novel-writer"
NOVEL_SKILLS = {
    "novel-direction",
    "story-foundation",
    "character-craft",
    "chapter-outline",
    "scene-craft",
    "dialogue-craft",
    "prose-writing",
    "continuity-check",
    "style-review",
}
NOVEL_TOOLS = {
    "novel_get_context",
    "novel_get_document",
    "novel_search",
    "novel_get_workspace_context",
    "novel_prepare_selection_edit",
}
NOVEL_PROMPT_FILE = "AI_NOVEL_WORLD.md"
SELECTION_EDIT_OPERATIONS = [
    "polish",
    "rewrite",
    "expand",
    "shorten",
    "dialogue",
    "review",
    "custom",
]
BASE_URL = os.environ.get("QWENPAW_BASE_URL", "http://127.0.0.1:18088").rstrip("/")
EXPECTED_TTS_RUNTIME = os.environ.get(
    "QWENPAW_EXPECT_TTS_RUNTIME",
    "disabled",
)
EXPECTED_TTS_PRODUCT = os.environ.get(
    "QWENPAW_EXPECT_TTS_PRODUCT",
    "disabled",
)
EXPECTED_TTS_VALIDATION = os.environ.get(
    "QWENPAW_EXPECT_TTS_VALIDATION",
    "disabled",
)
EXPECTED_TTS_REFERENCE_CLONE = os.environ.get(
    "QWENPAW_EXPECT_TTS_REFERENCE_CLONE",
    "disabled",
)
TTS_PROTOCOL_VERSION = "moss-tts-sidecar/1.1"
TTS_MODEL_FINGERPRINT_SHA256 = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
TTS_VALIDATION_NOVEL_ID = os.environ.get(
    "AI_NOVEL_TTS_VALIDATION_NOVEL_ID",
    "",
)
TTS_VALIDATION_DOCUMENT_ID = os.environ.get(
    "AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID",
    "",
)
TTS_VALIDATION_HEADER = "X-AI-Novel-TTS-Validation"
WRONG_TTS_VALIDATION_TOKEN = "A" * 43
HIDDEN_TTS_NOT_FOUND = {
    "detail": {
        "code": "RESOURCE_NOT_FOUND",
        "message": "找不到请求的朗读资源。",
    }
}
PRODUCT_OFFICIAL_PRESET_IDS = (
    "onnx.Junhao",
    "onnx.Zhiming",
    "onnx.Weiguo",
    "onnx.Xiaoyu",
    "onnx.Yuewen",
    "onnx.Lingyu",
)
OFFICIAL_PRESET_REPOSITORY = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
OFFICIAL_PRESET_REVISION = "f52645cb467506d8e18e746ddd59482685b74e58"
OFFICIAL_PRESET_MANIFEST_PATH = "browser_poc_manifest.json"
OFFICIAL_PRESET_MANIFEST_SHA256 = (
    "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee"
)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

_T2_CAPABILITY_ROWS = (
    ("narration_product", "enabled", True, True, None, None),
    ("reading_settings", "enabled", True, True, None, None),
    (
        "narration_synthesis",
        "hold",
        False,
        False,
        "T4_GATE_REQUIRED",
        "T4-GATE",
    ),
    ("product_player", "hold", False, False, "T4_GATE_REQUIRED", "T4-GATE"),
    (
        "editor_production",
        "hold",
        False,
        False,
        "T4_GATE_REQUIRED",
        "T4-GATE",
    ),
    (
        "voice_preview",
        "unavailable",
        True,
        False,
        "VOICE_SOURCE_NOT_APPROVED",
        "T2-D",
    ),
    (
        "preset_voice_source",
        "unavailable",
        True,
        False,
        "OFFICIAL_PRESET_CATALOG_NOT_RELEASED",
        "T4-PRESET",
    ),
    (
        "reference_clone",
        "hold",
        False,
        False,
        "REFERENCE_CLONE_PRODUCT_GATE_HOLD",
        "T2-D",
    ),
    (
        "generic_voice_pool",
        "unavailable",
        True,
        False,
        "GENERIC_VOICE_ASSETS_UNAVAILABLE",
        "T2-E",
    ),
    (
        "automatic_generic_casting",
        "unavailable",
        False,
        False,
        "GENERIC_VOICE_POOL_UNAVAILABLE",
        "T2-E",
    ),
    (
        "automatic_speaker_detection",
        "hold",
        False,
        False,
        "T3_GATE_REQUIRED",
        "T3-GATE",
    ),
    (
        "cloud_assisted_analysis",
        "unavailable",
        True,
        False,
        "CLOUD_CONSENT_FLOW_NOT_READY",
        "T2-G",
    ),
    (
        "voice_generator",
        "unavailable",
        False,
        False,
        "VOICE_GENERATOR_NO_GO",
        "T5-GATE",
    ),
    ("cache_cleanup", "hold", True, False, "T2_GATE_REQUIRED", "T2-F"),
)
T2_CAPABILITY_MATRIX = {
    "schema_version": "narration-capabilities/1",
    "items": [
        {
            "key": key,
            "state": state,
            "visible": visible,
            "actionable": actionable,
            "reason_code": reason_code,
            "required_gate": required_gate,
        }
        for key, state, visible, actionable, reason_code, required_gate in (
            _T2_CAPABILITY_ROWS
        )
    ],
}


class JsonHttpResponse:
    __slots__ = ("status", "headers", "payload")

    def __init__(
        self,
        *,
        status: int,
        headers: Mapping[str, str],
        payload: object,
    ) -> None:
        self.status = status
        self.headers = headers
        self.payload = payload


def request_json(
    path: str,
    *,
    agent_id: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JsonHttpResponse:
    request_headers = {"Accept": "application/json"}
    if agent_id:
        request_headers["X-Agent-Id"] = agent_id
    if headers:
        request_headers.update(headers)
    request = Request(f"{BASE_URL}{path}", headers=request_headers)
    try:
        response = urlopen(request, timeout=10)  # noqa: S310 - fixed local lab URL
    except HTTPError as error:
        response = error
    try:
        raw = response.read()
        payload = json.loads(raw.decode("utf-8", errors="strict"))
        return JsonHttpResponse(
            status=int(response.status),
            headers={key.lower(): value for key, value in response.headers.items()},
            payload=payload,
        )
    finally:
        response.close()


def get_json(path: str, *, agent_id: str | None = None) -> object:
    response = request_json(path, agent_id=agent_id)
    assert response.status == 200, f"GET {path} returned HTTP {response.status}"
    return response.payload


def _canonical_uuid(value: str, *, name: str) -> str:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise AssertionError(f"{name} must be a canonical UUID") from error
    assert str(parsed) == value, f"{name} must be a canonical UUID"
    return value


def _assert_t2_overview(response: JsonHttpResponse, *, novel_id: str) -> None:
    assert response.status == 200
    assert isinstance(response.payload, dict)
    assert response.payload.get("contract_version") == "narration-settings-api/1"
    assert response.payload.get("novel_id") == novel_id
    assert response.payload.get("capabilities") == T2_CAPABILITY_MATRIX
    runtime = response.payload.get("runtime")
    assert isinstance(runtime, dict)
    assert runtime.get("product_visible") is False


def _assert_hidden_tts_route(response: JsonHttpResponse) -> None:
    assert response.status == 404
    assert response.headers.get("cache-control") == "no-store"
    assert response.payload == HIDDEN_TTS_NOT_FOUND


def verify_hidden_validation_http() -> dict[str, object]:
    novel_id = _canonical_uuid(
        TTS_VALIDATION_NOVEL_ID,
        name="AI_NOVEL_TTS_VALIDATION_NOVEL_ID",
    )
    document_id = _canonical_uuid(
        TTS_VALIDATION_DOCUMENT_ID,
        name="AI_NOVEL_TTS_VALIDATION_DOCUMENT_ID",
    )
    prefix = f"/api/{APP_ID}"
    overview_path = f"{prefix}/novels/{novel_id}/narration-overview"
    _assert_t2_overview(request_json(overview_path), novel_id=novel_id)

    hidden_paths = (
        f"{prefix}/narration-requests/{document_id}",
        f"{prefix}/narration-script-versions/{document_id}",
        f"{prefix}/narration-editions/{document_id}/manifest",
    )
    for request_headers in (
        {},
        {TTS_VALIDATION_HEADER: WRONG_TTS_VALIDATION_TOKEN},
    ):
        for path in hidden_paths:
            _assert_hidden_tts_route(request_json(path, headers=request_headers))
    return {
        "ordinary_overview_tier": "T2",
        "negative_validation_token_classes": ["missing", "wrong"],
        "hidden_route_classes": ["narration", "script", "playback"],
    }


def _assert_sha256(value: object) -> None:
    assert isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def verify_official_preset_catalog() -> dict[str, object]:
    response = request_json(f"/api/{APP_ID}/voice-presets")
    assert response.status == 200
    assert isinstance(response.payload, dict)
    assert set(response.payload) == {"schema_version", "items"}
    assert response.payload.get("schema_version") == (
        "moss-tts-official-preset-catalog/1.0"
    )
    items = response.payload.get("items")
    assert isinstance(items, list)
    assert [item.get("preset_id") for item in items if isinstance(item, dict)] == list(
        PRODUCT_OFFICIAL_PRESET_IDS
    )
    assert len(items) == len(PRODUCT_OFFICIAL_PRESET_IDS)
    assert "onnx.Xiaoyu" in PRODUCT_OFFICIAL_PRESET_IDS

    item_keys = {
        "preset_id",
        "display_name",
        "group",
        "language",
        "local_use_status",
        "commercial_distribution_status",
        "provenance",
    }
    provenance_keys = {
        "schema_version",
        "repository",
        "revision",
        "manifest_path",
        "manifest_sha256",
        "preset_id",
        "manifest_voice",
        "prompt_codes_sha256",
        "prompt_frame_count",
        "prompt_quantizer_count",
        "model_fingerprint_sha256",
        "provenance_fingerprint_sha256",
    }
    for item in items:
        assert isinstance(item, dict) and set(item) == item_keys
        assert item.get("local_use_status") == "available"
        assert item.get("commercial_distribution_status") == "not_evaluated"
        assert all(
            isinstance(item.get(key), str) and bool(item[key])
            for key in ("display_name", "group", "language")
        )
        provenance = item.get("provenance")
        assert isinstance(provenance, dict) and set(provenance) == provenance_keys
        assert provenance.get("schema_version") == (
            "moss-tts-official-preset-provenance/1.0"
        )
        assert provenance.get("repository") == OFFICIAL_PRESET_REPOSITORY
        assert provenance.get("revision") == OFFICIAL_PRESET_REVISION
        assert provenance.get("manifest_path") == OFFICIAL_PRESET_MANIFEST_PATH
        assert provenance.get("manifest_sha256") == OFFICIAL_PRESET_MANIFEST_SHA256
        assert provenance.get("preset_id") == item.get("preset_id")
        assert provenance.get("manifest_voice") == str(item.get("preset_id"))[5:]
        assert provenance.get("prompt_quantizer_count") == 16
        assert (
            isinstance(provenance.get("prompt_frame_count"), int)
            and not isinstance(provenance.get("prompt_frame_count"), bool)
            and provenance["prompt_frame_count"] > 0
        )
        for key in (
            "prompt_codes_sha256",
            "model_fingerprint_sha256",
            "provenance_fingerprint_sha256",
        ):
            _assert_sha256(provenance.get(key))
        assert provenance.get("model_fingerprint_sha256") == (
            TTS_MODEL_FINGERPRINT_SHA256
        )
    return {
        "schema_version": response.payload["schema_version"],
        "metadata_only": True,
        "preset_count": len(items),
        "preset_ids": list(PRODUCT_OFFICIAL_PRESET_IDS),
    }


def verify_tts_http_contracts() -> dict[str, object]:
    result: dict[str, object] = {}
    if EXPECTED_TTS_VALIDATION == "ready":
        result["hidden_validation"] = verify_hidden_validation_http()
    if EXPECTED_TTS_PRODUCT == "ready":
        result["official_preset_catalog"] = verify_official_preset_catalog()
    return result


def plugin_skills(agent_id: str) -> dict[str, dict[str, object]]:
    payload = get_json("/api/skills", agent_id=agent_id)
    assert isinstance(payload, list)
    return {
        str(item["name"]): item
        for item in payload
        if isinstance(item, dict) and item.get("source") == f"plugin:{APP_ID}"
    }


def expected_narration_production() -> dict[str, object]:
    if (
        EXPECTED_TTS_PRODUCT == "disabled"
        and EXPECTED_TTS_VALIDATION == "disabled"
    ):
        return {
            "product_requested": False,
            "lifecycle_status": "playback_only",
            "playback_installed": True,
            "digest_keyring_loaded": False,
            "production_backend_installed": False,
            "worker_running": False,
            "reference_clone_ready": False,
            "reason_code": None,
        }
    return {
        "product_requested": True,
        "lifecycle_status": "ready",
        "playback_installed": True,
        "digest_keyring_loaded": True,
        "production_backend_installed": True,
        "worker_running": True,
        "reference_clone_ready": EXPECTED_TTS_REFERENCE_CLONE == "ready",
        "reason_code": None,
    }


def verify() -> dict[str, object]:
    assert EXPECTED_TTS_RUNTIME in {"disabled", "ready"}
    assert EXPECTED_TTS_PRODUCT in {"disabled", "ready"}
    assert EXPECTED_TTS_VALIDATION in {"disabled", "ready"}
    assert EXPECTED_TTS_REFERENCE_CLONE in {"disabled", "ready"}
    assert not (
        EXPECTED_TTS_PRODUCT == "ready" and EXPECTED_TTS_VALIDATION == "ready"
    ), "product-ready and hidden-validation verification are mutually exclusive"
    assert not (
        EXPECTED_TTS_VALIDATION == "ready"
        and EXPECTED_TTS_REFERENCE_CLONE == "ready"
    ), "reference clone requires a separately approved validation gate"
    assert not (
        (
            EXPECTED_TTS_PRODUCT == "ready"
            or EXPECTED_TTS_VALIDATION == "ready"
        )
        and EXPECTED_TTS_RUNTIME != "ready"
    ), "a ready production pipeline requires a ready technical runtime"
    assert not (
        EXPECTED_TTS_REFERENCE_CLONE == "ready"
        and EXPECTED_TTS_PRODUCT != "ready"
        and EXPECTED_TTS_VALIDATION != "ready"
    ), "reference clone requires a ready product or hidden-validation pipeline"
    pawapps = get_json("/api/pawapps")
    assert isinstance(pawapps, dict)
    installed = [app for app in pawapps.get("apps", []) if app.get("id") == APP_ID]
    assert len(installed) == 1, f"expected one installed PawApp, got {len(installed)}"
    assert installed[0].get("version") == APP_VERSION

    health = get_json(f"/api/{APP_ID}/health")
    assert isinstance(health, dict)
    assert health.get("app_id") == APP_ID
    assert health.get("ai_candidate_generation_enabled") is True
    assert health.get("ai_authoritative_write_enabled") is False
    assert health.get("generation_agent_id") == NOVEL_AGENT_ID
    assert health.get("generation_model_policy") == "follow-agent-effective"
    assert health.get("model_verification_mode") == "preflight-effective+provider-usage"
    assert health.get("selection_edit_enabled") is True
    assert health.get("selection_edit_operations") == SELECTION_EDIT_OPERATIONS
    narration = health.get("narration")
    assert isinstance(narration, dict)
    assert narration.get("product_visible") is (EXPECTED_TTS_PRODUCT == "ready")
    assert narration.get("protocol_version") == TTS_PROTOCOL_VERSION
    if EXPECTED_TTS_RUNTIME == "disabled":
        assert narration == {
            "technical_enabled": False,
            "lifecycle_status": "disabled",
            "sidecar_reachable": False,
            "model_ready": False,
            "product_visible": False,
            "protocol_version": TTS_PROTOCOL_VERSION,
            "worker_generation": None,
            "lease_generation": None,
            "model_fingerprint_sha256": None,
            "reason_code": None,
        }
    else:
        assert narration.get("technical_enabled") is True
        assert narration.get("lifecycle_status") == "ready"
        assert narration.get("sidecar_reachable") is True
        assert narration.get("model_ready") is True
        assert narration.get("model_fingerprint_sha256") == (
            TTS_MODEL_FINGERPRINT_SHA256
        )
        for field in ("worker_generation", "lease_generation"):
            value = narration.get(field)
            assert isinstance(value, int) and not isinstance(value, bool) and value > 0
        assert narration.get("reason_code") is None

    narration_production = health.get("narration_production")
    assert isinstance(narration_production, dict)
    assert narration_production == expected_narration_production()
    tts_http_contracts = verify_tts_http_contracts()

    agent_payload = get_json("/api/agents")
    assert isinstance(agent_payload, dict)
    agents = {agent["id"]: agent for agent in agent_payload.get("agents", [])}
    agent_ids = set(agents)
    assert NOVEL_AGENT_ID in agent_ids
    assert {"default", "QwenPaw_QA_Agent_0.2"}.issubset(agent_ids)
    effective_model = get_json(
        f"/api/models/active?scope=effective&agent_id={NOVEL_AGENT_ID}"
    )
    assert isinstance(effective_model, dict)
    active_llm = effective_model.get("active_llm")
    assert isinstance(active_llm, dict)
    assert str(active_llm.get("provider_id") or "").strip()
    assert str(active_llm.get("model") or "").strip()
    runtime_model = get_json(f"/api/{APP_ID}/generation-model")
    assert isinstance(runtime_model, dict)
    assert runtime_model.get("agent_id") == NOVEL_AGENT_ID
    assert runtime_model.get("policy") == "follow-agent-effective"
    assert runtime_model.get("provider_id") == active_llm.get("provider_id")
    assert runtime_model.get("model_id") == active_llm.get("model")

    enabled_scope: dict[str, list[str]] = {}
    for agent_id in ("default", "QwenPaw_QA_Agent_0.2", NOVEL_AGENT_ID):
        skills = plugin_skills(agent_id)
        assert set(skills) == NOVEL_SKILLS, f"unexpected novel skills in {agent_id}"
        enabled_scope[agent_id] = sorted(
            name for name, item in skills.items() if item.get("enabled") is True
        )

    assert enabled_scope["default"] == []
    assert enabled_scope["QwenPaw_QA_Agent_0.2"] == []
    assert set(enabled_scope[NOVEL_AGENT_ID]) == NOVEL_SKILLS

    enabled_tools: dict[str, list[str]] = {}
    for agent_id in sorted(agent_ids):
        tools = get_json("/api/tools", agent_id=agent_id)
        assert isinstance(tools, list)
        novel_tools = {
            str(tool["name"]): tool
            for tool in tools
            if isinstance(tool, dict) and str(tool.get("name", "")).startswith("novel_")
        }
        assert set(novel_tools).issubset(NOVEL_TOOLS)
        if agent_id == NOVEL_AGENT_ID:
            assert set(novel_tools) == NOVEL_TOOLS
        enabled_tools[agent_id] = sorted(
            name for name, item in novel_tools.items() if item.get("enabled") is True
        )
    for agent_id, tool_names in enabled_tools.items():
        if agent_id != NOVEL_AGENT_ID:
            assert tool_names == [], f"novel tools enabled for {agent_id}"
    assert set(enabled_tools[NOVEL_AGENT_ID]) == NOVEL_TOOLS

    system_prompt_files = get_json(
        "/api/workspace/system-prompt-files",
        agent_id=NOVEL_AGENT_ID,
    )
    assert isinstance(system_prompt_files, list)
    assert NOVEL_PROMPT_FILE in system_prompt_files
    prompt_payload = get_json(
        f"/api/workspace/files/{NOVEL_PROMPT_FILE}",
        agent_id=NOVEL_AGENT_ID,
    )
    assert isinstance(prompt_payload, dict)
    assert "正文生成或重写必须调用 `prose-writing`" in str(
        prompt_payload.get("content", "")
    )
    prompt_content = str(prompt_payload.get("content", ""))
    assert "每条命令最多一次成功调用 `novel_prepare_selection_edit`" in prompt_content
    assert "insufficient-shortening" in prompt_content
    assert "insufficient-expansion" in prompt_content
    assert "review-size-mismatch" in prompt_content
    workspace_files = get_json("/api/workspace/files", agent_id=NOVEL_AGENT_ID)
    assert isinstance(workspace_files, list)
    workspace_names = {
        str(item.get("filename")) for item in workspace_files if isinstance(item, dict)
    }
    assert "BOOTSTRAP.md" not in workspace_names

    return {
        "base_url": BASE_URL,
        "pawapp": f"{APP_ID}@{APP_VERSION}",
        "health": health.get("status"),
        "narration": narration,
        "narration_production": narration_production,
        "tts_http_contracts": tts_http_contracts,
        "agents": sorted(agent_ids),
        "novel_model": active_llm,
        "enabled_novel_skills": enabled_scope,
        "enabled_novel_tools": enabled_tools,
        "system_prompt_files": system_prompt_files,
    }


def main() -> None:
    try:
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
    except (AssertionError, HTTPError, URLError, TimeoutError) as error:
        print(f"QwenPaw lab verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
