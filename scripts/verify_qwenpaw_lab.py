"""Verify the installed AI小说世界2026 contract against a local QwenPaw lab."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID


APP_ID = "ai-novel-world-2026"
APP_VERSION = "0.4.0"
NOVEL_AGENT_ID = "ai-novel-writer"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from backend.writing_skills.catalog import (
    load_catalog, packaged_approvals, published_skill_ids,
)
from backend.writing_skills.loader import CatalogError, load_primary_blocks
from backend.writing_skills.primary import (
    CREATIVE_PRIMARY_BY_KIND,
    PRIMARY_REFERENCES_BY_SKILL,
    SELECTION_PRIMARY_BY_OPERATION,
)
from backend.narration.official_presets import (
    CANONICAL_CHAPTER_VERIFIED_PRESET_IDS,
    OFFICIAL_PRESET_IDS,
    OFFICIAL_PRESETS_BY_ID,
)

NOVEL_SKILLS = set(published_skill_ids(_PROJECT_ROOT / "skills"))
SKILLS_ROOT = _PROJECT_ROOT / "skills"
NOVEL_TOOLS = {
    "novel_get_context",
    "novel_get_document",
    "novel_search",
    "novel_get_workspace_context",
    "novel_prepare_selection_edit",
    "novel_library_query",
    "novel_library_prepare_change",
    "novel_library_apply_change",
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
        "voice_design",
        "unavailable",
        True,
        False,
        "QWEN_VOICE_DESIGN_NOT_RELEASED",
        "QWEN-TTS",
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
    ("cache_cleanup", "hold", True, False, "T2_GATE_REQUIRED", "T2-F"),
    (
        "private_voice_deletion",
        "unavailable",
        True,
        False,
        "TTS_FEATURE_STARTING",
        "TTS35-CORE",
    ),
)
T2_CAPABILITY_MATRIX = {
    "schema_version": "narration-capabilities/5",
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
    assert response.payload.get("schema_version") == "qwen-tts-preset-catalog/2"
    items = response.payload.get("items")
    assert isinstance(items, list)
    assert [item.get("preset_id") for item in items if isinstance(item, dict)] == list(
        OFFICIAL_PRESET_IDS
    )
    assert len(items) == len(OFFICIAL_PRESET_IDS) == 9

    item_keys = {
        "preset_id",
        "display_name",
        "official_speaker",
        "native_language",
        "dialect",
        "group",
        "language",
        "local_use_status",
        "commercial_distribution_status",
        "validation_tier",
        "language_scope",
        "selectable_now",
        "previewable_now",
        "renderable_existing",
        "usage_notice",
        "provenance",
    }
    provenance_keys = {
        "schema_version",
        "catalog_id",
        "preset_id",
        "local_model_id",
        "local_model_revision",
        "provider_voice_ids",
        "model_fingerprint_sha256",
        "provenance_fingerprint_sha256",
    }
    for item in items:
        assert isinstance(item, dict) and set(item) == item_keys
        assert item.get("local_use_status") == "available"
        assert item.get("commercial_distribution_status") == "not_evaluated"
        assert item.get("validation_tier") == (
            "canonical_chapter_verified"
            if item.get("preset_id") in CANONICAL_CHAPTER_VERIFIED_PRESET_IDS
            else "pinned_catalog_unreviewed"
        )
        assert item.get("language_scope") == item.get("language")
        assert item.get("selectable_now") is True
        assert item.get("previewable_now") is True
        assert item.get("renderable_existing") is True
        assert item.get("usage_notice") == "private_local_writing_tool"
        assert all(
            isinstance(item.get(key), str) and bool(item[key])
            for key in (
                "display_name",
                "official_speaker",
                "native_language",
                "group",
                "language",
            )
        )
        provenance = item.get("provenance")
        assert isinstance(provenance, dict) and set(provenance) == provenance_keys
        assert provenance.get("schema_version") == "qwen-tts-preset-provenance/1"
        assert provenance.get("preset_id") == item.get("preset_id")
        preset = OFFICIAL_PRESETS_BY_ID[str(item.get("preset_id"))]
        assert provenance == preset.provenance()
        provider_voice_ids = provenance.get("provider_voice_ids")
        assert isinstance(provider_voice_ids, dict)
        assert provider_voice_ids.get("local_qwen3_tts") == preset.local_voice_id
        assert set(provider_voice_ids) <= {
            "local_qwen3_tts",
            "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus",
            "aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash",
        }
        for key in (
            "model_fingerprint_sha256",
            "provenance_fingerprint_sha256",
        ):
            _assert_sha256(provenance.get(key))
    return {
        "schema_version": response.payload["schema_version"],
        "metadata_only": True,
        "preset_count": len(items),
        "preset_ids": list(OFFICIAL_PRESET_IDS),
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
    skills: dict[str, dict[str, object]] = {}
    for item in payload:
        if not isinstance(item, dict) or item.get("source") != f"plugin:{APP_ID}":
            continue
        name = item.get("name")
        assert isinstance(name, str) and name, "invalid public Skill name"
        assert name not in skills, "duplicate public Skill name"
        assert type(item.get("enabled")) is bool, "unknown public Skill state"
        skills[name] = item
    return skills


def _agent_ids() -> set[str]:
    payload = get_json("/api/agents")
    assert isinstance(payload, dict) and isinstance(payload.get("agents"), list)
    agent_ids: set[str] = set()
    for agent in payload["agents"]:
        assert isinstance(agent, dict)
        agent_id = agent.get("id")
        assert isinstance(agent_id, str) and agent_id
        assert agent_id not in agent_ids, "duplicate public Agent id"
        agent_ids.add(agent_id)
    return agent_ids


def verify_skill_state(previous: dict[str, bool] | None = None) -> dict[str, object]:
    """Read public Agent scopes and trusted local methods; never restore state.

    Readiness covers method availability only, not model execution or quality.
    Scope isolation is the current public state; lifecycle callers must retain
    their before/after inventories to prove other Agents were unchanged.
    """
    return _verify_skill_state(previous, agent_ids=_agent_ids())


def _verify_skill_state(
    previous: dict[str, bool] | None, *, agent_ids: set[str],
) -> dict[str, object]:
    if previous is not None and (
        not isinstance(previous, dict) or not previous
        or any(not isinstance(name, str) or not name or type(enabled) is not bool
               for name, enabled in previous.items())
    ):
        raise ValueError("previous Skill state must be a nonempty explicit boolean snapshot")
    scopes = {agent_id: plugin_skills(agent_id) for agent_id in sorted(agent_ids)}
    target = scopes.get(NOVEL_AGENT_ID, {})
    current = {name: item["enabled"] for name, item in target.items()}
    enabled_scope = {
        agent_id: sorted(name for name, item in skills.items() if item["enabled"] is True)
        for agent_id, skills in scopes.items()
    }
    differences = {
        name: {"previous": previous[name], "current": current.get(name)}
        for name in sorted(set(previous or {}) & NOVEL_SKILLS)
        if current.get(name) is not previous[name]
    }
    # Only supported old items participate; absent supported items are failures.
    state_preserved = None if previous is None else not differences
    task_skills = {
        "chapter_body": "prose-writing",
        **CREATIVE_PRIMARY_BY_KIND,
        **{f"selection_edit:{operation}": skill
           for operation, skill in SELECTION_PRIMARY_BY_OPERATION.items()},
    }
    primary_status: dict[str, dict[str, object]] = {}
    missing_methods: dict[str, str] = {}
    for skill_id in sorted(set(task_skills.values())):
        reason = None
        references = PRIMARY_REFERENCES_BY_SKILL.get(skill_id)
        try:
            if references is None:
                raise CatalogError("unsupported_primary_skill")
            load_primary_blocks(SKILLS_ROOT, skill_id, references)
        except CatalogError as error:
            missing_methods[skill_id] = str(error)
            reason = str(error)
        if skill_id not in target:
            reason = "not_registered"
        elif current[skill_id] is not True:
            reason = "disabled"
        primary_status[skill_id] = {"ready": reason is None, "reason": reason}
    task_readiness = {
        task: {"primary_skill": skill_id, **primary_status[skill_id]}
        for task, skill_id in sorted(task_skills.items())
    }
    # Optional classification methods retain their own approval/file checks;
    # disabling one never turns every unrelated writing task into a failure.
    approvals = packaged_approvals()
    optional_ids = {record.skill_id for record in approvals}
    optional_errors: dict[str, str] = {}
    try:
        catalog = load_catalog(SKILLS_ROOT, approvals, frozenset(optional_ids))
        available_optional = {item.declaration.skill_id for item in catalog.capabilities}
        optional_errors = dict(item.split(":", 1) for item in catalog.rejected)
    except CatalogError as error:
        available_optional = set()
        optional_errors = {name: str(error) for name in optional_ids}
    optional_status = {
        name: {
            "registered": name in target,
            "enabled": current.get(name),
            "method_available": name in available_optional,
            "ready": current.get(name) is True and name in available_optional,
            "method_error": optional_errors.get(name),
        }
        for name in sorted(optional_ids)
    }
    return {
        "state_preserved": state_preserved,
        "writing_skills_ready": all(item["ready"] for item in primary_status.values()),
        "scope_isolated": all(not names for agent_id, names in enabled_scope.items()
                              if agent_id != NOVEL_AGENT_ID),
        "current_skill_state": current,
        "skill_state_differences": differences,
        "added_skills": sorted(NOVEL_SKILLS - set(previous)) if previous is not None else [],
        "removed_skills": sorted(set(previous) - NOVEL_SKILLS) if previous is not None else [],
        "missing_primary_skills": sorted(name for name, item in primary_status.items()
                                         if not item["ready"]),
        "missing_methods": missing_methods,
        "task_readiness": task_readiness,
        "optional_skill_status": optional_status,
        "registered_novel_skills": {agent_id: sorted(skills) for agent_id, skills in scopes.items()},
        "enabled_novel_skills": enabled_scope,
    }


def _assert_skills_ready(result: dict[str, object]) -> None:
    assert (
        result["writing_skills_ready"] is True
        and result["state_preserved"] is not False
        and result["scope_isolated"] is True
    ), "Skill verification failed: " + json.dumps(result, ensure_ascii=False)


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


def verify(previous: dict[str, bool] | None = None) -> dict[str, object]:
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
    assert set(narration) == {
        "product_requested",
        "lifecycle_status",
        "playback_installed",
        "digest_keyring_loaded",
        "production_backend_installed",
        "worker_running",
        "reference_clone_ready",
        "provider_selection_fingerprint_sha256",
        "reason_code",
    }
    assert narration.get("product_requested") is (
        EXPECTED_TTS_PRODUCT == "ready" or EXPECTED_TTS_VALIDATION == "ready"
    )
    if EXPECTED_TTS_RUNTIME == "disabled":
        assert narration == {
            **expected_narration_production(),
            "provider_selection_fingerprint_sha256": None,
        }
    else:
        assert narration.get("lifecycle_status") == "ready"
        assert narration.get("playback_installed") is True
        assert narration.get("digest_keyring_loaded") is True
        assert narration.get("production_backend_installed") is True
        assert narration.get("worker_running") is True
        _assert_sha256(narration.get("provider_selection_fingerprint_sha256"))
        assert narration.get("reference_clone_ready") is (
            EXPECTED_TTS_REFERENCE_CLONE == "ready"
        )
        assert narration.get("reason_code") is None

    narration_production = health.get("narration_production")
    assert isinstance(narration_production, dict)
    production_without_selection = dict(narration_production)
    production_selection_fingerprint = production_without_selection.pop(
        "provider_selection_fingerprint_sha256",
        None,
    )
    assert production_without_selection == expected_narration_production()
    if EXPECTED_TTS_RUNTIME == "ready":
        _assert_sha256(production_selection_fingerprint)
        assert production_selection_fingerprint == narration.get(
            "provider_selection_fingerprint_sha256"
        )
    else:
        assert production_selection_fingerprint is None
    tts_http_contracts = verify_tts_http_contracts()

    agent_ids = _agent_ids()
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

    skill_result = _verify_skill_state(previous, agent_ids=agent_ids)
    _assert_skills_ready(skill_result)
    registered = skill_result["registered_novel_skills"]
    for agent_id in ("default", "QwenPaw_QA_Agent_0.2", NOVEL_AGENT_ID):
        assert set(registered[agent_id]) == NOVEL_SKILLS, f"unexpected novel skills in {agent_id}"

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
    assert "私有库维护、收藏、分类、启用、停用或撤销" in prompt_content
    assert "`private-library-maintenance`" in prompt_content
    assert "`novel_library_apply_change`" in prompt_content
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
        **skill_result,
        "enabled_novel_tools": enabled_tools,
        "system_prompt_files": system_prompt_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-only", action="store_true")
    parser.add_argument("--previous-skill-state", type=Path)
    args = parser.parse_args()
    try:
        previous = None
        if args.previous_skill_state is not None:
            from scripts import configure_qwenpaw_novel_agent as configuration

            configuration.BASE_URL = BASE_URL
            previous = configuration.load_previous_skill_state(args.previous_skill_state)
        result = verify_skill_state(previous) if args.skills_only else verify(previous)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        _assert_skills_ready(result)
    except (AssertionError, OSError, ValueError, RuntimeError) as error:
        print(f"QwenPaw lab verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
