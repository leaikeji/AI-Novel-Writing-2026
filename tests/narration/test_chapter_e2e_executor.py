from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import UUID

import pytest

from scripts.tts import chapter_e2e_executor as executor
from scripts.tts import validate_chapter_e2e as runner


NOVEL_ID = UUID("10000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("10000000-0000-4000-8000-000000000002")
BASE_REVISION_ID = UUID("10000000-0000-4000-8000-000000000003")
BASE_EDITION_ID = UUID("10000000-0000-4000-8000-000000000004")
BASE_SCRIPT_ID = UUID("10000000-0000-4000-8000-000000000005")
BASE_REQUEST_ID = UUID("10000000-0000-4000-8000-000000000006")
AUTO_REQUEST_ID = UUID("20000000-0000-4000-8000-000000000001")
AUTO_SCRIPT_ID = UUID("20000000-0000-4000-8000-000000000002")
AUTO_EDITION_ID = UUID("20000000-0000-4000-8000-000000000003")
MANUAL_REQUEST_ID = UUID("30000000-0000-4000-8000-000000000001")
MANUAL_SCRIPT_ID = UUID("30000000-0000-4000-8000-000000000002")
MANUAL_PATCHED_SCRIPT_ID = UUID("30000000-0000-4000-8000-000000000003")
MANUAL_EDITION_ID = UUID("30000000-0000-4000-8000-000000000004")
CHARACTER_ONE = UUID("40000000-0000-4000-8000-000000000001")
CHARACTER_TWO = UUID("40000000-0000-4000-8000-000000000002")
RUN_ID = UUID("50000000-0000-4000-8000-000000000001")
BASE_TEXT = "这是执行前必须恢复的作者工作稿。"
AUTO_TEXT = "夜色落下。\n林晚：“我们出发。”\n顾川：“好。”"
MANUAL_TEXT = "风穿过长廊。\n林晚：“等等。”\n某人：“门后有声音。”\n顾川：“我去看看。”"
API_BASE = "http://127.0.0.1:18088/api/ai-novel-world-2026"
CAPABILITY_KEYS = (
    "narration_product",
    "reading_settings",
    "narration_synthesis",
    "product_player",
    "editor_production",
    "voice_preview",
    "preset_voice_source",
    "reference_clone",
    "generic_voice_pool",
    "automatic_generic_casting",
    "automatic_speaker_detection",
    "cloud_assisted_analysis",
    "voice_generator",
    "cache_cleanup",
)
T2_ENABLED = frozenset({"narration_product", "reading_settings"})
T4_ENABLED = frozenset(
    {
        *T2_ENABLED,
        "narration_synthesis",
        "product_player",
        "editor_production",
        "voice_preview",
        "preset_voice_source",
        "automatic_speaker_detection",
    }
)


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _derived_uuid(value: UUID, suffix: int) -> UUID:
    first, second, third, _fourth, _fifth = str(value).split("-")
    return UUID(f"{first}-{second}-{third}-8000-{suffix:012d}")


def _json_response(
    value: object,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> executor.HttpResponse:
    return executor.HttpResponse(
        status=status,
        headers={"Content-Type": "application/json", **dict(headers or {})},
        body=json.dumps(value, ensure_ascii=False).encode("utf-8"),
    )


def _overview_response(
    enabled: frozenset[str],
    *,
    novel_id: UUID = NOVEL_ID,
) -> executor.HttpResponse:
    return _json_response(
        {
            "contract_version": "narration-settings-api/1",
            "novel_id": str(novel_id),
            "capabilities": {
                "schema_version": "narration-capabilities/1",
                "items": [
                    {
                        "key": key,
                        "state": "enabled" if key in enabled else "hold",
                        "visible": key in enabled,
                        "actionable": key in enabled,
                        "reason_code": None if key in enabled else "GATE_REQUIRED",
                        "required_gate": None if key in enabled else "T4-GATE",
                    }
                    for key in CAPABILITY_KEYS
                ],
            },
            "runtime": {"product_visible": False},
        }
    )


def _hidden_gate_response() -> executor.HttpResponse:
    return _json_response(
        {
            "detail": {
                "code": "RESOURCE_NOT_FOUND",
                "message": "找不到请求的朗读资源。",
            }
        },
        status=404,
        headers={"Cache-Control": "no-store"},
    )


@dataclass(frozen=True)
class Call:
    method: str
    path: str
    headers: dict[str, str]
    body: object | None


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _segment(
    *,
    label: str,
    ordinal: int,
    source: str,
    source_text: str,
    speaker_kind: str,
    speaker_label: str,
    character_id: UUID | None,
    issue_codes: list[str] | None = None,
) -> dict[str, object]:
    start_codepoints = source.index(source_text)
    start_utf16 = _utf16_length(source[:start_codepoints])
    end_utf16 = start_utf16 + _utf16_length(source_text)
    return {
        "segment_id": str(
            UUID(
                f"{label}000000-0000-4000-8000-{ordinal + 1:012d}"
            )
        ),
        "ordinal": ordinal,
        "segment_kind": "narration" if speaker_kind == "narrator" else "dialogue",
        "source_block_key": f"sb1_{_sha(f'{label}:{ordinal}')}",
        "source_start_utf16": start_utf16,
        "source_end_utf16": end_utf16,
        "source_text": source_text,
        "spoken_text": source_text.strip("“”"),
        "local_hash": _sha(source_text),
        "speaker_kind": speaker_kind,
        "speaker_label": speaker_label,
        "character_id": str(character_id) if character_id is not None else None,
        "anonymous_speaker_id": None,
        "confidence": "unknown" if speaker_kind == "unknown" else "high",
        "casting_state": "unresolved" if speaker_kind == "unknown" else "resolved",
        "issue_codes": issue_codes or [],
        "editable": True,
    }


def _script_resource(
    *,
    script_id: UUID,
    request_id: UUID,
    source: str,
    segments: list[dict[str, object]],
    state: str,
    version_number: int,
    blocker: bool,
    approval_kind: str | None,
) -> dict[str, object]:
    issues: list[dict[str, object]] = []
    if blocker:
        blocked = next(item for item in segments if item["speaker_kind"] == "unknown")
        issues.append(
            {
                "taxonomy_version": "narration-review-taxonomy/1",
                "code": "B_SPEAKER_UNKNOWN",
                "severity": "blocker",
                "segment_id": blocked["segment_id"],
                "evidence_summary": None,
                "evidence_digest": None,
            }
        )
    approval = None
    if approval_kind is not None:
        approval = {
            "kind": approval_kind,
            "request_id": str(request_id),
            "actor_type": "owner" if approval_kind == "manual_after_review" else "system",
            "actor_id": "local-owner" if approval_kind == "manual_after_review" else "narration-service",
            "approved_at": "2026-08-27T12:00:00Z",
        }
    return {
        "contract_version": "narration-script-review-api/1",
        "taxonomy_version": "narration-review-taxonomy/1",
        "script_id": str(_derived_uuid(script_id, 99)),
        "script_version_id": str(script_id),
        "novel_id": str(NOVEL_ID),
        "document_id": str(DOCUMENT_ID),
        "revision_id": str(_derived_uuid(script_id, 98)),
        "source_content_hash": _sha(source),
        "immutable_hash": _sha(f"immutable:{script_id}:{version_number}"),
        "version_number": version_number,
        "state": state,
        "effective_policy": "blockers_only",
        "source_status": "current",
        "warning_count": 0,
        "blocker_count": len(issues),
        "allowed_actions": (
            []
            if state == "approved"
            else ["approve", "edit_segment", "reanalyze_segments"]
            if not blocker
            else ["edit_segment", "reanalyze_segments"]
        ),
        "segments": segments,
        "issues": issues,
        "approval": approval,
    }


class FakeHttpServer:
    def __init__(self, *, locator_mismatch: bool = False) -> None:
        self.calls: list[Call] = []
        self.document_version = 7
        self.document_text = BASE_TEXT
        self.document_hash = _sha(BASE_TEXT)
        self.pointer_version = 4
        self.current_edition = BASE_EDITION_ID
        self.current_script = BASE_SCRIPT_ID
        self.locator_mismatch = locator_mismatch
        self.poll_counts: dict[UUID, int] = {}
        self.workflow: dict[UUID, dict[str, object]] = {}
        self.scripts: dict[UUID, dict[str, object]] = {}
        self.editions: dict[UUID, dict[str, object]] = {}
        self.manifests: dict[UUID, tuple[dict[str, object], dict[str, object]]] = {}
        self.assets: dict[UUID, bytes] = {}
        self.edition_to_script: dict[UUID, UUID] = {BASE_EDITION_ID: BASE_SCRIPT_ID}
        self.history: list[dict[str, object]] = [
            {
                "edition_id": str(BASE_EDITION_ID),
                "request_id": str(BASE_REQUEST_ID),
                "source_revision_id": str(BASE_REVISION_ID),
                "source_content_hash": _sha(BASE_TEXT),
                "edition_fingerprint": _sha("base-edition"),
                "state": "ready",
                "manifest_revision": 1,
                "is_current": True,
            }
        ]
        self.auto_segments = [
            _segment(
                label="21",
                ordinal=0,
                source=AUTO_TEXT,
                source_text="夜色落下。",
                speaker_kind="narrator",
                speaker_label="旁白",
                character_id=None,
            ),
            _segment(
                label="21",
                ordinal=1,
                source=AUTO_TEXT,
                source_text="林晚：“我们出发。”",
                speaker_kind="character",
                speaker_label="林晚",
                character_id=CHARACTER_ONE,
            ),
            _segment(
                label="21",
                ordinal=2,
                source=AUTO_TEXT,
                source_text="顾川：“好。”",
                speaker_kind="character",
                speaker_label="顾川",
                character_id=CHARACTER_TWO,
            ),
        ]
        self.manual_segments = [
            _segment(
                label="31",
                ordinal=0,
                source=MANUAL_TEXT,
                source_text="风穿过长廊。",
                speaker_kind="narrator",
                speaker_label="旁白",
                character_id=None,
            ),
            _segment(
                label="31",
                ordinal=1,
                source=MANUAL_TEXT,
                source_text="林晚：“等等。”",
                speaker_kind="character",
                speaker_label="林晚",
                character_id=CHARACTER_ONE,
            ),
            _segment(
                label="31",
                ordinal=2,
                source=MANUAL_TEXT,
                source_text="某人：“门后有声音。”",
                speaker_kind="unknown",
                speaker_label="顾川",
                character_id=None,
                issue_codes=["B_SPEAKER_UNKNOWN"],
            ),
            _segment(
                label="31",
                ordinal=3,
                source=MANUAL_TEXT,
                source_text="顾川：“我去看看。”",
                speaker_kind="character",
                speaker_label="顾川",
                character_id=CHARACTER_TWO,
            ),
        ]
        if locator_mismatch:
            self.manual_segments[2]["local_hash"] = "f" * 64

    def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        timeout_seconds: float,
    ) -> executor.HttpResponse:
        assert 0 < timeout_seconds <= 120
        call_headers = dict(headers or {})
        self.calls.append(Call(method, path, call_headers, json_body))
        if method == "GET" and path == "/health":
            return _json_response(
                {
                    "status": "ready",
                    "database": {"connected": True},
                    "narration_production": {
                        "product_requested": True,
                        "lifecycle_status": "ready",
                        "playback_installed": True,
                        "digest_keyring_loaded": True,
                        "production_backend_installed": True,
                        "worker_running": True,
                        "reference_clone_ready": False,
                        "reason_code": None,
                    },
                }
            )
        if method == "GET" and path == f"/documents/{DOCUMENT_ID}":
            return _json_response(self._document())
        if method == "PATCH" and path == f"/documents/{DOCUMENT_ID}/draft":
            body = self._body(json_body)
            assert body["expected_draft_version"] == self.document_version
            assert body["content_hash"] == _sha(str(body["content_markdown"]))
            if body["content_hash"] != self.document_hash:
                self.document_version += 1
                self.document_text = str(body["content_markdown"])
                self.document_hash = str(body["content_hash"])
            return _json_response(self._document())
        if method == "GET" and path == f"/documents/{DOCUMENT_ID}/narration-playback-context":
            return _json_response(self._context())
        if method == "PUT" and path == f"/documents/{DOCUMENT_ID}/current-narration-edition":
            body = self._body(json_body)
            assert body["expected_version"] == self.pointer_version
            assert body["switch_mode"] == "next_playback"
            assert body["start_segment_id"] is None
            assert body["confirmed"] is True
            target = UUID(str(body["target_edition_id"]))
            self.pointer_version += 1
            self.current_edition = target
            self.current_script = self.edition_to_script[target]
            return _json_response(
                {
                    "contract_version": "document-narration-context/1",
                    "document_id": str(DOCUMENT_ID),
                    "current_edition_id": str(target),
                    "pointer_version": self.pointer_version,
                    "switch_mode": "next_playback",
                    "start_segment_id": None,
                    "manifest_revision": 2,
                    "playback_progress_id": None,
                }
            )
        if method == "GET" and path == f"/novels/{NOVEL_ID}/narration-settings":
            return _json_response(
                {
                    "novel_id": str(NOVEL_ID),
                    "exists": True,
                    "version": 3,
                    "values": {"script_review_policy": "blockers_only"},
                }
            )
        if method == "GET" and path == f"/novels/{NOVEL_ID}/characters":
            return _json_response(
                [
                    {
                        "id": str(CHARACTER_ONE),
                        "novel_id": str(NOVEL_ID),
                        "name": "林晚",
                        "lifecycle_state": "active",
                    },
                    {
                        "id": str(CHARACTER_TWO),
                        "novel_id": str(NOVEL_ID),
                        "name": "顾川",
                        "lifecycle_state": "active",
                    },
                ]
            )
        if method == "POST" and path == f"/documents/{DOCUMENT_ID}/narration-requests":
            return self._start_workflow(json_body, call_headers)
        request_match = _match_uuid_path(path, "/narration-requests/")
        if method == "GET" and request_match is not None:
            return _json_response(self._poll_workflow(request_match))
        script_match = _match_uuid_path(path, "/narration-script-versions/")
        if method == "GET" and script_match is not None:
            return _json_response(self.scripts[script_match])
        if method == "PATCH" and "/segments/" in path:
            return self._patch_script(path, json_body, call_headers)
        if method == "POST" and path.endswith("/approve"):
            return self._approve_script(path, json_body, call_headers)
        edition_match = _match_uuid_path(path, "/narration-editions/")
        if method == "GET" and edition_match is not None:
            return _json_response(self.editions[edition_match])
        if method == "GET" and path.endswith("/manifest"):
            return self._manifest_response(path)
        if method == "POST" and path.endswith("/prepare-range"):
            return self._prepare_range(path, json_body, call_headers)
        asset_match = _match_media_path(path)
        if asset_match is not None:
            return self._media(method, asset_match, call_headers)
        raise AssertionError(f"unhandled fake request: {method} {path}")

    def _document(self) -> dict[str, object]:
        return {
            "id": str(DOCUMENT_ID),
            "novel_id": str(NOVEL_ID),
            "draft_version": self.document_version,
            "base_revision_id": str(BASE_REVISION_ID),
            "content_markdown": self.document_text,
            "content_hash": self.document_hash,
        }

    def _context(self) -> dict[str, object]:
        rows = []
        for item in self.history:
            row = dict(item)
            row["is_current"] = row["edition_id"] == str(self.current_edition)
            rows.append(row)
        return {
            "contract_version": "document-narration-context/1",
            "document_id": str(DOCUMENT_ID),
            "novel_id": str(NOVEL_ID),
            "pointer_version": self.pointer_version,
            "current_script_version_id": str(self.current_script),
            "current_edition_id": str(self.current_edition),
            "working_copy_draft_version": self.document_version,
            "working_copy_content_hash": self.document_hash,
            "edition_history": {
                "document_id": str(DOCUMENT_ID),
                "pointer_version": self.pointer_version,
                "current_edition_id": str(self.current_edition),
                "editions": rows,
            },
        }

    def _start_workflow(
        self, json_body: object | None, headers: dict[str, str]
    ) -> executor.HttpResponse:
        body = self._body(json_body)
        assert body == {
            "intent": "update",
            "expected_draft_version": self.document_version,
            "expected_content_hash": self.document_hash,
            "expected_settings_version": 3,
            "force_review": False,
        }
        assert headers["Idempotency-Key"].startswith(f"t4k:{RUN_ID.hex}:")
        if self.document_hash == _sha(AUTO_TEXT):
            script = _script_resource(
                script_id=AUTO_SCRIPT_ID,
                request_id=AUTO_REQUEST_ID,
                source=AUTO_TEXT,
                segments=[dict(item) for item in self.auto_segments],
                state="approved",
                version_number=1,
                blocker=False,
                approval_kind="auto_no_blockers",
            )
            self.scripts[AUTO_SCRIPT_ID] = script
            workflow = self._workflow_resource(
                request_id=AUTO_REQUEST_ID,
                script_id=AUTO_SCRIPT_ID,
                edition_id=AUTO_EDITION_ID,
                source=AUTO_TEXT,
                state="queued",
                blocker_count=0,
                request_version=1,
            )
            self.workflow[AUTO_REQUEST_ID] = workflow
            self._create_edition(
                label="auto",
                request_id=AUTO_REQUEST_ID,
                script_id=AUTO_SCRIPT_ID,
                edition_id=AUTO_EDITION_ID,
                source=AUTO_TEXT,
                segments=self.auto_segments,
            )
            return _json_response(workflow, status=202)
        assert self.document_hash == _sha(MANUAL_TEXT)
        script = _script_resource(
            script_id=MANUAL_SCRIPT_ID,
            request_id=MANUAL_REQUEST_ID,
            source=MANUAL_TEXT,
            segments=[dict(item) for item in self.manual_segments],
            state="review_required",
            version_number=1,
            blocker=True,
            approval_kind=None,
        )
        self.scripts[MANUAL_SCRIPT_ID] = script
        workflow = self._workflow_resource(
            request_id=MANUAL_REQUEST_ID,
            script_id=MANUAL_SCRIPT_ID,
            edition_id=None,
            source=MANUAL_TEXT,
            state="review_required",
            blocker_count=1,
            request_version=1,
        )
        self.workflow[MANUAL_REQUEST_ID] = workflow
        return _json_response(workflow, status=202)

    def _workflow_resource(
        self,
        *,
        request_id: UUID,
        script_id: UUID,
        edition_id: UUID | None,
        source: str,
        state: str,
        blocker_count: int,
        request_version: int,
    ) -> dict[str, object]:
        job_base = "22" if request_id == AUTO_REQUEST_ID else "32"
        job_ids = [
            str(UUID(f"{job_base}000000-0000-4000-8000-{index:012d}"))
            for index in range(1, 5)
        ] if edition_id is not None else []
        return {
            "contract_version": "narration-production-api/1",
            "request_id": str(request_id),
            "intent": "update",
            "request_version": request_version,
            "workflow_state": state,
            "source_revision_id": str(_derived_uuid(script_id, 98)),
            "source_content_hash": _sha(source),
            "settings_fingerprint": _sha("settings"),
            "warning_count": 0,
            "blocker_count": blocker_count,
            "script_version_id": str(script_id),
            "edition_id": str(edition_id) if edition_id else None,
            "current_manifest_revision": None,
            "job_ids": job_ids,
            "replayed": False,
        }

    def _poll_workflow(self, request_id: UUID) -> dict[str, object]:
        resource = self.workflow[request_id]
        if resource["workflow_state"] == "review_required":
            return dict(resource)
        count = self.poll_counts.get(request_id, 0) + 1
        self.poll_counts[request_id] = count
        state = "partial_ready" if count == 1 else "ready"
        resource["workflow_state"] = state
        resource["current_manifest_revision"] = 1 if count == 1 else 2
        return dict(resource)

    def _patch_script(
        self,
        path: str,
        json_body: object | None,
        headers: dict[str, str],
    ) -> executor.HttpResponse:
        assert path.startswith(f"/narration-script-versions/{MANUAL_SCRIPT_ID}/segments/")
        assert headers["Idempotency-Key"].endswith("manual-patch-0")
        body = self._body(json_body)
        current = self.scripts[MANUAL_SCRIPT_ID]
        target = current["segments"][2]  # type: ignore[index]
        assert body["expected_request_version"] == 1
        assert body["expected_version_number"] == 1
        assert body["expected_immutable_hash"] == current["immutable_hash"]
        assert body["expected_local_hash"] == target["local_hash"]  # type: ignore[index]
        assert body["speaker_kind"] == "character"
        assert body["speaker_label"] == "顾川"
        assert body["character_id"] == str(CHARACTER_TWO)
        assert body["anonymous_speaker_id"] is None
        assert body["group_key"] is None
        patched_segments = [dict(item) for item in self.manual_segments]
        patched_segments[2].update(
            {
                "speaker_kind": "character",
                "speaker_label": "顾川",
                "character_id": str(CHARACTER_TWO),
                "confidence": "high",
                "casting_state": "resolved",
                "issue_codes": [],
                "spoken_text": body["spoken_text"],
            }
        )
        patched = _script_resource(
            script_id=MANUAL_PATCHED_SCRIPT_ID,
            request_id=MANUAL_REQUEST_ID,
            source=MANUAL_TEXT,
            segments=patched_segments,
            state="review_required",
            version_number=2,
            blocker=False,
            approval_kind=None,
        )
        self.scripts[MANUAL_PATCHED_SCRIPT_ID] = patched
        workflow = self.workflow[MANUAL_REQUEST_ID]
        workflow["script_version_id"] = str(MANUAL_PATCHED_SCRIPT_ID)
        workflow["request_version"] = 2
        workflow["blocker_count"] = 0
        return _json_response(patched, status=201)

    def _approve_script(
        self,
        path: str,
        json_body: object | None,
        headers: dict[str, str],
    ) -> executor.HttpResponse:
        assert path == f"/narration-script-versions/{MANUAL_PATCHED_SCRIPT_ID}/approve"
        assert headers["Idempotency-Key"].endswith("manual-approve")
        body = self._body(json_body)
        script = self.scripts[MANUAL_PATCHED_SCRIPT_ID]
        assert body["expected_request_version"] == 2
        assert body["expected_version_number"] == 2
        assert body["expected_immutable_hash"] == script["immutable_hash"]
        assert body["confirmed"] is True
        approved = dict(script)
        approved.update(
            {
                "state": "approved",
                "allowed_actions": [],
                "approval": {
                    "kind": "manual_after_review",
                    "request_id": str(MANUAL_REQUEST_ID),
                    "actor_type": "owner",
                    "actor_id": "local-owner",
                    "approved_at": "2026-08-27T12:00:00Z",
                },
            }
        )
        self.scripts[MANUAL_PATCHED_SCRIPT_ID] = approved
        workflow = self.workflow[MANUAL_REQUEST_ID]
        workflow.update(
            {
                "request_version": 3,
                "workflow_state": "queued",
                "edition_id": str(MANUAL_EDITION_ID),
                "job_ids": [
                    str(UUID(f"32000000-0000-4000-8000-{index:012d}"))
                    for index in range(1, 5)
                ],
            }
        )
        self._create_edition(
            label="manual",
            request_id=MANUAL_REQUEST_ID,
            script_id=MANUAL_PATCHED_SCRIPT_ID,
            edition_id=MANUAL_EDITION_ID,
            source=MANUAL_TEXT,
            segments=approved["segments"],  # type: ignore[arg-type]
        )
        return _json_response(approved)

    def _create_edition(
        self,
        *,
        label: str,
        request_id: UUID,
        script_id: UUID,
        edition_id: UUID,
        source: str,
        segments: list[dict[str, object]],
    ) -> None:
        job_base = "22" if label == "auto" else "32"
        jobs = [
            str(UUID(f"{job_base}000000-0000-4000-8000-{index:012d}"))
            for index in range(1, 5)
        ]
        self.editions[edition_id] = {
            "contract_version": "narration-production-api/1",
            "edition_id": str(edition_id),
            "request_id": str(request_id),
            "novel_id": str(NOVEL_ID),
            "document_id": str(DOCUMENT_ID),
            "script_version_id": str(script_id),
            "settings_fingerprint": _sha("settings"),
            "edition_fingerprint": _sha(f"edition:{edition_id}"),
            "state": "ready",
            "segment_count": len(segments),
            "pending_segment_count": 0,
            "queued_segment_count": 0,
            "rendering_segment_count": 0,
            "ready_segment_count": len(segments),
            "failed_segment_count": 0,
            "current_manifest_revision": 2,
            "job_ids": jobs,
        }
        partial, ready = self._make_manifests(label, edition_id, source, segments)
        self.manifests[edition_id] = (partial, ready)
        self.edition_to_script[edition_id] = script_id
        self.history.append(
            {
                "edition_id": str(edition_id),
                "request_id": str(request_id),
                "source_revision_id": str(_derived_uuid(script_id, 98)),
                "source_content_hash": _sha(source),
                "edition_fingerprint": _sha(f"edition:{edition_id}"),
                "state": "ready",
                "manifest_revision": 2,
                "is_current": False,
            }
        )

    def _make_manifests(
        self,
        label: str,
        edition_id: UUID,
        source: str,
        segments: list[dict[str, object]],
    ) -> tuple[dict[str, object], dict[str, object]]:
        final_segments: list[dict[str, object]] = []
        for index, segment in enumerate(segments):
            prefix = "23" if label == "auto" else "33"
            asset_id = UUID(f"{prefix}000000-0000-4000-8000-{index + 1:012d}")
            audio = f"{label}-audio-{index}-48khz-stereo".encode()
            self.assets[asset_id] = audio
            digest = _sha(audio)
            final_segments.append(
                {
                    "segment_id": segment["segment_id"],
                    "ordinal": index,
                    "render_status": "ready",
                    "audio": {
                        "url": f"{runner.API_PATH}/media-assets/{asset_id}/content",
                        "actual_sha256": digest,
                        "duration_ms": 1200 + index * 100,
                        "sample_rate": 48000,
                        "channels": 2,
                        "etag": f'"{digest}"',
                    },
                }
            )
        ready_etag = f'"{_sha(f"{label}:manifest:2")}"'
        ready = {
            "schema_version": "narration-manifest/2.0",
            "edition_id": str(edition_id),
            "chapter_id": str(DOCUMENT_ID),
            "source_revision_id": str(_derived_uuid(edition_id, 98)),
            "source_sha256": _sha(source),
            "manifest_revision": 2,
            "etag": ready_etag,
            "status": "ready",
            "segments": final_segments,
        }
        partial_segments = [dict(final_segments[0])]
        partial_segments.extend(
            {
                "segment_id": item["segment_id"],
                "ordinal": item["ordinal"],
                "render_status": "pending",
                "audio": None,
            }
            for item in final_segments[1:]
        )
        partial = {
            **ready,
            "manifest_revision": 1,
            "etag": f'"{_sha(f"{label}:manifest:1")}"',
            "status": "partial_ready",
            "segments": partial_segments,
        }
        return partial, ready

    def _manifest_response(self, path: str) -> executor.HttpResponse:
        edition_id = UUID(path.split("/")[2])
        workflow = next(
            item
            for item in self.workflow.values()
            if item.get("edition_id") == str(edition_id)
        )
        selected = self.manifests[edition_id][
            1 if workflow["workflow_state"] == "ready" else 0
        ]
        return _json_response(selected, headers={"ETag": str(selected["etag"])})

    def _prepare_range(
        self,
        path: str,
        json_body: object | None,
        headers: dict[str, str],
    ) -> executor.HttpResponse:
        edition_id = UUID(path.split("/")[2])
        body = self._body(json_body)
        assert body["reason"] == "user_seek"
        assert body["expected_manifest_revision"] == 2
        assert headers["Idempotency-Key"].startswith(f"t4k:{RUN_ID.hex}:")
        manifest = self.manifests[edition_id][1]
        segments = manifest["segments"]
        assert isinstance(segments, list)
        assert body["start_segment_id"] == segments[0]["segment_id"]
        return _json_response(
            {
                "contract_version": "narration-production-api/1",
                "edition_id": str(edition_id),
                "start_segment_id": body["start_segment_id"],
                "start_ordinal": 0,
                "state": "ready",
                "manifest_revision": 2,
                "manifest_etag": manifest["etag"],
                "ready_range": {
                    "start_ordinal": 0,
                    "end_ordinal_exclusive": len(segments),
                    "segment_count": len(segments),
                    "duration_ms": sum(
                        int(item["audio"]["duration_ms"]) for item in segments
                    ),
                    "last_playable_start_ordinal": len(segments) - 1,
                },
                "promoted_job_ids": [],
            }
        )

    def _media(
        self,
        method: str,
        asset_id: UUID,
        headers: dict[str, str],
    ) -> executor.HttpResponse:
        body = self.assets[asset_id]
        digest = _sha(body)
        assert headers["X-Narration-Edition-Id"] in {
            str(AUTO_EDITION_ID),
            str(MANUAL_EDITION_ID),
        }
        assert headers["X-Narration-Manifest-Revision"] == "2"
        common = {
            "ETag": f'"{digest}"',
            "Accept-Ranges": "bytes",
            "Content-Type": "audio/mp4",
        }
        if headers.get("If-None-Match") == f'"{digest}"':
            return executor.HttpResponse(304, common, b"")
        range_value = headers.get("Range")
        if range_value == "bytes=0-0":
            return executor.HttpResponse(
                206,
                {
                    **common,
                    "Content-Length": "1",
                    "Content-Range": f"bytes 0-0/{len(body)}",
                },
                body[:1],
            )
        if range_value == f"bytes={len(body)}-":
            return executor.HttpResponse(
                416,
                {**common, "Content-Range": f"bytes */{len(body)}"},
                b"",
            )
        assert range_value is None
        response_body = b"" if method == "HEAD" else body
        return executor.HttpResponse(
            200,
            {**common, "Content-Length": str(len(body))},
            response_body,
        )

    @staticmethod
    def _body(value: object | None) -> dict[str, object]:
        assert isinstance(value, dict)
        return value


def _match_uuid_path(path: str, prefix: str) -> UUID | None:
    if not path.startswith(prefix):
        return None
    remainder = path[len(prefix) :]
    if "/" in remainder:
        return None
    try:
        return UUID(remainder)
    except ValueError:
        return None


def _match_media_path(path: str) -> UUID | None:
    prefix = "/media-assets/"
    suffix = "/content"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    try:
        return UUID(path[len(prefix) : -len(suffix)])
    except ValueError:
        return None


class FakeRuntimeAuditProbe:
    def __init__(
        self,
        *,
        invalid_audit: bool = False,
        product_visible: bool = False,
        edition_fingerprint_override: str | None = None,
    ) -> None:
        self.invalid_audit = invalid_audit
        self.product_visible = product_visible
        self.edition_fingerprint_override = edition_fingerprint_override
        self.preflight_calls = 0
        self.audit_calls: list[tuple[UUID, UUID]] = []
        self.technical_context: executor.TechnicalProbeContext | None = None

    def preflight(self, config: runner.RunnerConfig) -> executor.RuntimePreflightEvidence:
        assert config.run_id == RUN_ID
        self.preflight_calls += 1
        return executor.RuntimePreflightEvidence(
            production_ready=True,
            sidecar_ready=True,
            product_visible=self.product_visible,
            model_fingerprint=_sha("moss-nano-model"),
        )

    def audit_chain(
        self,
        config: runner.RunnerConfig,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
    ) -> executor.ChainAuditEvidence:
        assert config.run_id == RUN_ID
        assert len(segment_ids) >= 3
        self.audit_calls.append((request_id, edition_id))
        return executor.ChainAuditEvidence(
            request_id=request_id,
            edition_id=edition_id,
            script_version_id=script_version_id,
            edition_fingerprint=(
                self.edition_fingerprint_override
                or _sha(f"edition:{edition_id}")
            ),
            distinct_voice_version_count=0 if self.invalid_audit else 3,
            uncached_nano_job_count=len(job_ids),
            model_run_fingerprints=(_sha("moss-nano-model"),),
        )

    def collect_technical(
        self,
        config: runner.RunnerConfig,
        fixture: runner.ChapterFixture,
        context: executor.TechnicalProbeContext,
    ) -> executor.RuntimeTechnicalEvidence:
        assert fixture.fixture_id == "fixture-v2"
        self.technical_context = context
        return executor.RuntimeTechnicalEvidence(
            stability_elapsed_seconds=config.duration_minutes * 60,
            peak_memory_bytes=2_000_000_000,
            pageout_delta=0,
            swapout_delta=0,
            memory_baseline_median_bytes=1_800_000_000,
            memory_tail_median_bytes=1_900_000_000,
            memory_growth_bytes=100_000_000,
            memory_growth_limit_bytes=134_217_728,
            sidecar_memory_growth_observed=False,
            seam_pairs_checked=4,
            sidecar_restart_count=0,
            health_failure_count=0,
            host_paging_observed=False,
            qwenpaw_slowdown_observed=False,
        )


class FakeBrowserProbe:
    def __init__(self, *, pass_gate: bool = True) -> None:
        self.pass_gate = pass_gate
        self.context: executor.TechnicalProbeContext | None = None
        self.begun: list[str] = []
        self.observations: list[executor.BrowserManifestObservation] = []
        self.completed: list[tuple[str, UUID, UUID]] = []

    def begin_chain(
        self,
        config: runner.RunnerConfig,
        chain_label: str,
    ) -> None:
        assert config.run_id == RUN_ID
        self.begun.append(chain_label)

    def observe_manifest(
        self,
        config: runner.RunnerConfig,
        observation: executor.BrowserManifestObservation,
    ) -> None:
        assert config.run_id == RUN_ID
        self.observations.append(observation)

    def complete_chain(
        self,
        config: runner.RunnerConfig,
        *,
        chain_label: str,
        request_id: UUID,
        edition_id: UUID,
    ) -> None:
        assert config.run_id == RUN_ID
        self.completed.append((chain_label, request_id, edition_id))

    def collect(
        self,
        config: runner.RunnerConfig,
        fixture: runner.ChapterFixture,
        context: executor.TechnicalProbeContext,
    ) -> executor.BrowserTechnicalEvidence:
        assert config.document_id == DOCUMENT_ID
        assert fixture.required_viewports == runner.ALLOWED_VIEWPORTS
        self.context = context
        observed_pending_gap = any(
            item.ready_segment_count < item.total_segment_count
            for item in self.observations
        )
        return executor.BrowserTechnicalEvidence(
            time_to_first_audio_ms=max(context.observed_http_first_audio_ms),
            seek_latest_wins=self.pass_gate,
            pending_gap_not_skipped=observed_pending_gap,
            edit_actions_created_tts_writes=0,
            browser_viewports=runner.ALLOWED_VIEWPORTS,
            browser_assistant_modes=("collapsed", "expanded"),
            browser_console_error_count=0,
            browser_overlap_count=0,
            collector_collected_at="2026-08-27T12:00:00Z",
        )


def _config(tmp_path: Path) -> runner.RunnerConfig:
    return runner.RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=tmp_path / "fixture.json",
        api_base=API_BASE,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id="automatic",
        manual_case_id="manual",
        private_work_dir=tmp_path / "private",
        output_dir=tmp_path / "output",
        duration_minutes=30.0,
        listening_record=None,
        resume=False,
    )


def _automatic_case() -> runner.ChapterCase:
    return runner.ChapterCase(
        case_id="automatic",
        mode="automatic_zero_blockers",
        source_text=AUTO_TEXT,
        source_sha256=_sha(AUTO_TEXT),
        review_policy="blockers_only",
        expected_initial_blocker_codes=(),
        corrections=(),
    )


def _manual_case() -> runner.ChapterCase:
    source_text = "某人：“门后有声音。”"
    start = _utf16_length(MANUAL_TEXT[: MANUAL_TEXT.index(source_text)])
    return runner.ChapterCase(
        case_id="manual",
        mode="manual_blocker_resolution",
        source_text=MANUAL_TEXT,
        source_sha256=_sha(MANUAL_TEXT),
        review_policy="blockers_only",
        expected_initial_blocker_codes=("B_SPEAKER_UNKNOWN",),
        corrections=(
            runner.Correction(
                segment_ordinal=2,
                expected_source_local_hash=_sha(source_text),
                expected_source_start_utf16=start,
                expected_source_end_utf16=start + _utf16_length(source_text),
                speaker_kind="character",
                speaker_label="顾川",
                spoken_text="门后有声音。",
                reason="授权 fixture 的确定性人物映射。",
            ),
        ),
    )


def _fixture() -> runner.ChapterFixture:
    return runner.ChapterFixture(
        fixture_id="fixture-v2",
        manifest_sha256=_sha("fixture"),
        authorization_reference="project-fixture-license-v2",
        voice_scope="isolated_test_only",
        production_eligible=False,
        commercial_distribution_status="not_evaluated",
        minimum_character_speakers=2,
        minimum_distinct_voice_versions=3,
        expected_formal_speakers=("林晚", "沈川"),
        require_uncached_nano_model_run=True,
        restoration_policy="dedicated_append_only_author_visible",
        automatic=_automatic_case(),
        manual=_manual_case(),
        required_viewports=runner.ALLOWED_VIEWPORTS,
    )


def _executor(
    tmp_path: Path,
    server: FakeHttpServer,
    *,
    browser: FakeBrowserProbe | None = None,
    audit: FakeRuntimeAuditProbe | None = None,
    checkpoint: Any | None = None,
) -> tuple[
    executor.RealChapterE2EExecutor,
    runner.RunnerConfig,
    FakeClock,
    FakeBrowserProbe,
    FakeRuntimeAuditProbe,
]:
    config = _config(tmp_path)
    clock = FakeClock()
    browser = browser or FakeBrowserProbe()
    audit = audit or FakeRuntimeAuditProbe()
    value = executor.RealChapterE2EExecutor(
        config,
        transport=server,
        browser_probe=browser,
        runtime_audit_probe=audit,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        request_timeout_seconds=5,
        workflow_timeout_seconds=20,
        poll_interval_seconds=1,
    )
    value.set_recovery_checkpoint(
        checkpoint or (lambda _fence, _intent: None)
    )
    return value, config, clock, browser, audit


def _partial_manifest_fixture() -> tuple[
    executor._ManifestSnapshot,
    executor._ManifestSnapshot,
]:
    audio = tuple(
        executor._ManifestAudio(
            asset_id=UUID(f"60000000-0000-4000-8000-{index + 1:012d}"),
            path=(
                f"/media-assets/60000000-0000-4000-8000-"
                f"{index + 1:012d}/content"
            ),
            sha256=_sha(f"cached-audio-{index}"),
            etag=f'"{_sha(f"cached-audio-{index}")}"',
            duration_ms=3_000,
        )
        for index in range(5)
    )
    segment_ids = tuple(
        UUID(f"61000000-0000-4000-8000-{index + 1:012d}")
        for index in range(5)
    )
    ready = executor._ManifestSnapshot(
        edition_id=AUTO_EDITION_ID,
        revision=2,
        etag=f'"{_sha("prior-manifest")}"',
        status="ready",
        source_sha256=_sha(AUTO_TEXT),
        payload_sha256=_sha("prior-payload"),
        segment_ids=segment_ids,
        audio=audio,
        audio_by_ordinal=audio,
        render_statuses=("ready",) * 5,
    )
    partial = executor._ManifestSnapshot(
        edition_id=UUID("70000000-0000-4000-8000-000000000003"),
        revision=3,
        etag=f'"{_sha("partial-manifest")}"',
        status="partial_ready",
        source_sha256=_sha("partial-source"),
        payload_sha256=_sha("partial-payload"),
        segment_ids=segment_ids,
        audio=audio[:3],
        audio_by_ordinal=(*audio[:3], None, None),
        render_statuses=("ready", "ready", "ready", "pending", "queued"),
    )
    return ready, partial


def _exercise_partial_ready_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_release_fails: bool = False,
    restore_conflict: bool = False,
) -> tuple[list[str], list[tuple[str, executor.PartialReadyValidationEvidence]]]:
    config = _config(tmp_path)
    prior, partial = _partial_manifest_fixture()
    partial_request = UUID("70000000-0000-4000-8000-000000000001")
    partial_script = UUID("70000000-0000-4000-8000-000000000002")
    partial_edition = partial.edition_id
    events: list[str] = []
    records: list[tuple[str, executor.PartialReadyValidationEvidence]] = []

    class Coordinator:
        release_calls = 0

        def arm(self, observed: runner.RunnerConfig):
            assert observed == config
            events.append("arm")
            return executor.ValidationClaimGateEvidence(
                "VALIDATION_SEGMENT_CLAIM_GATE_ARMED",
                "armed",
                1,
                0,
                1,
                "2026-08-27T13:00:00Z",
                "a" * 64,
                "b" * 64,
            )

        def read(self, _observed: runner.RunnerConfig):
            raise AssertionError("poll helper is frozen in this unit test")

        def release(self, observed: runner.RunnerConfig):
            assert observed == config
            self.release_calls += 1
            events.append(f"release-{self.release_calls}")
            if first_release_fails and self.release_calls == 1:
                raise runner.RunnerError("TRANSIENT_RELEASE_FAILURE")
            return executor.ValidationClaimGateEvidence(
                "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
                "default_allow",
                1,
                1,
                0,
                "2026-08-27T13:00:00Z",
                "a" * 64,
                "b" * 64,
            )

        def record(self, observed, *, state, evidence):  # type: ignore[no-untyped-def]
            assert observed == config
            events.append(f"record-{state}")
            records.append((state, evidence))

    coordinator = Coordinator()
    value = executor.RealChapterE2EExecutor.__new__(
        executor.RealChapterE2EExecutor
    )
    value._config = config
    value._partial_ready_coordinator = coordinator
    value._automatic = SimpleNamespace(manifest=prior)
    value._manual = object()
    value._owned_fence = runner.RecoveryFence(
        draft_version=9,
        content_hash=_sha(MANUAL_TEXT),
        current_edition_id=MANUAL_EDITION_ID,
        current_script_version_id=MANUAL_PATCHED_SCRIPT_ID,
        pointer_version=6,
    )
    value._recovery_checkpoint = lambda _fence, _intent: None
    value._workflow_timeout_seconds = 20.0
    value._poll_interval_seconds = 1.0
    value._monotonic = lambda: 100.0
    value._sleeper = lambda _seconds: None
    monkeypatch.setattr(
        value,
        "_read_document",
        lambda: {
            "content_markdown": MANUAL_TEXT,
            "content_hash": _sha(MANUAL_TEXT),
        },
    )

    def save_text(source: str, source_hash: str) -> dict[str, object]:
        assert _sha(source) == source_hash
        events.append("save-partial" if source != MANUAL_TEXT else "restore-content")
        fence = value._owned_fence
        value._owned_fence = replace(
            fence,
            draft_version=fence.draft_version + 1,
            content_hash=source_hash,
        )
        return {}

    monkeypatch.setattr(value, "_save_text", save_text)

    def start(case: runner.ChapterCase, label: str) -> dict[str, object]:
        assert label == "partial-ready"
        assert "本地朗读验收甲号" in case.source_text
        events.append("start-workflow")
        return {
            "request_id": str(partial_request),
            "request_version": 1,
            "workflow_state": "queued",
            "source_content_hash": case.source_sha256,
            "script_version_id": str(partial_script),
            "edition_id": str(partial_edition),
            "current_manifest_revision": 1,
            "job_ids": [
                "71000000-0000-4000-8000-000000000001",
                "71000000-0000-4000-8000-000000000002",
            ],
            "blocker_count": 0,
        }

    monkeypatch.setattr(value, "_start_workflow", start)
    monkeypatch.setattr(
        value,
        "_read_script",
        lambda observed: {
            "script_version_id": str(observed),
            "state": "approved",
            "blocker_count": 0,
            "approval": {"kind": "auto_no_blockers"},
        },
    )
    monkeypatch.setattr(
        value,
        "_validate_script_scope",
        lambda _script, _case, observed: (
            None
            if observed == partial_script
            else (_ for _ in ()).throw(AssertionError("wrong script"))
        ),
    )

    def poll(*_args: object, **_kwargs: object):
        events.append("verify-real-partial")
        return partial, executor.ValidationClaimGateEvidence(
            "VALIDATION_SEGMENT_CLAIM_GATE_PAUSED",
            "paused",
            1,
            1,
            0,
            "2026-08-27T13:00:00Z",
            "a" * 64,
            "b" * 64,
        )

    monkeypatch.setattr(value, "_poll_partial_ready", poll)

    def switch(edition_id: UUID, script_id: UUID) -> None:
        events.append(
            "switch-partial" if edition_id == partial_edition else "restore-edition"
        )
        if restore_conflict and edition_id == MANUAL_EDITION_ID:
            raise runner.RunnerError("RECOVERY_CONFLICT")
        fence = value._owned_fence
        value._owned_fence = replace(
            fence,
            current_edition_id=edition_id,
            current_script_version_id=script_id,
            pointer_version=fence.pointer_version + 1,
        )

    monkeypatch.setattr(value, "_switch_edition", switch)
    monkeypatch.setattr(
        value,
        "_wait_partial_completion",
        lambda **_kwargs: events.append("wait-ready") or partial,
    )

    class Browser:
        def collect(self, *_args: object) -> executor.BrowserTechnicalEvidence:
            assert value._owned_fence.current_edition_id == partial_edition
            events.append("browser-collect-current-partial")
            return executor.BrowserTechnicalEvidence(
                time_to_first_audio_ms=250,
                seek_latest_wins=True,
                pending_gap_not_skipped=True,
                edit_actions_created_tts_writes=0,
                browser_viewports=runner.ALLOWED_VIEWPORTS,
                browser_assistant_modes=("collapsed", "expanded"),
                browser_console_error_count=0,
                browser_overlap_count=0,
                collector_collected_at="2026-08-27T12:00:00Z",
            )

    value._browser_probe = Browser()
    context = executor.TechnicalProbeContext(
        automatic_request_id=AUTO_REQUEST_ID,
        automatic_edition_id=AUTO_EDITION_ID,
        automatic_edition_fingerprint=_sha(f"edition:{AUTO_EDITION_ID}"),
        automatic_manifest_revision=2,
        manual_request_id=MANUAL_REQUEST_ID,
        manual_edition_id=MANUAL_EDITION_ID,
        manual_edition_fingerprint=_sha(f"edition:{MANUAL_EDITION_ID}"),
        manual_manifest_revision=2,
        request_to_ready_seconds=(1.0, 2.0),
        observed_http_first_audio_ms=(100, 200),
        chapter_audio_duration_seconds=15.0,
        range_status_codes=(200, 206, 304, 416),
        listening_output_hashes=("c" * 64,),
    )
    expected_error = (
        "TRANSIENT_RELEASE_FAILURE"
        if first_release_fails
        else "RECOVERY_CONFLICT" if restore_conflict else None
    )
    if expected_error is not None:
        with pytest.raises(runner.RunnerError, match=expected_error):
            value._collect_browser_with_partial_ready(config, _fixture(), context)
    else:
        result = value._collect_browser_with_partial_ready(
            config,
            _fixture(),
            context,
        )
        assert result.pending_gap_not_skipped is True
    assert value._owned_fence.content_hash == _sha(MANUAL_TEXT)
    if not restore_conflict:
        assert value._owned_fence.current_edition_id == MANUAL_EDITION_ID
    return events, records


def test_partial_ready_browser_runs_only_after_real_partial_switch_and_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, records = _exercise_partial_ready_lifecycle(tmp_path, monkeypatch)
    assert events.index("save-partial") < events.index("arm")
    assert events.index("arm") < events.index("start-workflow")
    assert events.index("verify-real-partial") < events.index("switch-partial")
    assert events.index("switch-partial") < events.index(
        "browser-collect-current-partial"
    )
    assert events.index("release-1") < events.index("wait-ready")
    assert events.index("wait-ready") < events.index("restore-content")
    assert events.index("restore-content") < events.index("restore-edition")
    assert records[-1][0] == "completed_restored"
    partial = next(value for state, value in records if state == "partial_ready")
    assert partial.ready_prefix_count == 3
    assert partial.ready_prefix_duration_ms == 9_000
    assert partial.cache_hit_prefix_count == 3
    assert partial.cache_miss_job_count == 2
    assert partial.gate_claimed_count == 1


def test_partial_ready_source_has_two_run_unique_chinese_suffix_paragraphs() -> None:
    first, first_hash = executor.RealChapterE2EExecutor._partial_ready_source(
        _automatic_case(),
        RUN_ID,
    )
    second, second_hash = executor.RealChapterE2EExecutor._partial_ready_source(
        _automatic_case(),
        UUID("50000000-0000-4000-8000-000000000002"),
    )
    first_suffix = first.split("\n\n")[-2:]
    second_suffix = second.split("\n\n")[-2:]
    assert len(first_suffix) == len(second_suffix) == 2
    assert all(value.startswith("本地朗读验收") for value in first_suffix)
    assert first_suffix[0] != first_suffix[1]
    assert first_suffix[0] != second_suffix[0]
    assert first_suffix[1] != second_suffix[1]
    assert first_hash == _sha(first) and second_hash == _sha(second)


def test_partial_ready_release_retries_before_wait_and_still_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, records = _exercise_partial_ready_lifecycle(
        tmp_path,
        monkeypatch,
        first_release_fails=True,
    )
    assert events.index("release-1") < events.index("release-2")
    assert events.index("release-2") < events.index("wait-ready")
    assert "restore-content" in events and "restore-edition" in events
    assert records[-1][0] == "recovery_required"
    assert records[-1][1].error_code == "TRANSIENT_RELEASE_FAILURE"


def test_partial_ready_restore_cas_conflict_fails_closed_and_marks_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, records = _exercise_partial_ready_lifecycle(
        tmp_path,
        monkeypatch,
        restore_conflict=True,
    )
    assert events.index("release-1") < events.index("wait-ready")
    assert events.index("restore-content") < events.index("restore-edition")
    assert records[-1][0] == "recovery_required"
    assert records[-1][1].error_code == "RECOVERY_CONFLICT"


def test_partial_ready_poll_fails_immediately_when_gate_ttl_expired(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    prior, _partial = _partial_manifest_fixture()
    value = executor.RealChapterE2EExecutor.__new__(
        executor.RealChapterE2EExecutor
    )
    value._config = config
    value._workflow_timeout_seconds = 20.0
    value._poll_interval_seconds = 1.0
    value._monotonic = lambda: 100.0
    value._sleeper = lambda _seconds: (_ for _ in ()).throw(
        AssertionError("expired gate must not poll")
    )
    workflow = {
        "request_id": "72000000-0000-4000-8000-000000000001",
        "request_version": 1,
        "workflow_state": "queued",
        "source_content_hash": "d" * 64,
        "script_version_id": "72000000-0000-4000-8000-000000000002",
        "edition_id": "72000000-0000-4000-8000-000000000003",
        "current_manifest_revision": None,
        "job_ids": [
            "72000000-0000-4000-8000-000000000004",
            "72000000-0000-4000-8000-000000000005",
        ],
    }

    class Expired:
        def read(self, observed: runner.RunnerConfig):
            assert observed == config
            return executor.ValidationClaimGateEvidence(
                "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
                "default_allow",
                0,
                0,
                0,
                None,
                None,
                None,
            )

    with pytest.raises(runner.RunnerError, match="PARTIAL_READY_GATE_EXPIRED"):
        value._poll_partial_ready(
            workflow,
            source_sha256="d" * 64,
            prior_ready=prior,
            coordinator=Expired(),  # type: ignore[arg-type]
        )


def test_fake_ports_cover_automatic_manual_manifest_range_and_restore(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    value, config, _clock, browser, audit = _executor(tmp_path, server)

    baseline = value.capture_baseline(config)
    automatic = value.run_automatic(config, _automatic_case())
    manual = value.run_manual(config, _manual_case())
    technical = value.run_technical_checks(config, _fixture())
    fence = value.capture_recovery_fence(config)
    recovery = value.restore_baseline(config, baseline, fence, None)

    assert baseline == runner.BaselineSnapshot(
        draft_version=7,
        content_hash=_sha(BASE_TEXT),
        content_markdown=BASE_TEXT,
        base_revision_id=BASE_REVISION_ID,
        pointer_version=4,
        current_edition_id=BASE_EDITION_ID,
        current_script_version_id=BASE_SCRIPT_ID,
        edition_history_count=1,
    )
    assert automatic.approval_kind == "auto_no_blockers"
    assert automatic.edition_count_for_request == 1
    assert automatic.narrator_segment_count == 1
    assert automatic.character_segment_count == 2
    assert automatic.distinct_character_count == 2
    assert automatic.distinct_voice_version_count == 3
    assert automatic.uncached_nano_job_count == 4
    assert automatic.edition_fingerprint == _sha(
        f"edition:{AUTO_EDITION_ID}"
    )
    assert manual.approval_kind == "manual_after_review"
    assert manual.initial_blocker_count == 1
    assert manual.final_blocker_count == 0
    assert manual.script_version_id == MANUAL_PATCHED_SCRIPT_ID
    assert manual.distinct_character_count == 2
    assert manual.edition_fingerprint == _sha(
        f"edition:{MANUAL_EDITION_ID}"
    )
    assert set(technical.range_status_codes) == {200, 206, 304, 416}
    assert technical.browser_viewports == ((1920, 1080), (2560, 1440))
    assert technical.browser_assistant_modes == ("collapsed", "expanded")
    assert technical.sidecar_restart_count == 0
    assert technical.health_failure_count == 0
    assert technical.host_paging_observed is False
    assert technical.pageout_delta == 0
    assert technical.swapout_delta == 0
    assert technical.memory_baseline_median_bytes == 1_800_000_000
    assert technical.memory_tail_median_bytes == 1_900_000_000
    assert technical.memory_growth_bytes == 100_000_000
    assert technical.memory_growth_limit_bytes == 134_217_728
    assert technical.sidecar_memory_growth_observed is False
    assert technical.qwenpaw_slowdown_observed is False
    assert len(technical.listening_output_hashes) == 7
    assert browser.context is not None
    assert browser.begun == ["automatic", "manual"]
    assert [item.chain_label for item in browser.observations] == [
        "automatic",
        "automatic",
        "manual",
        "manual",
    ]
    assert any(
        item.ready_segment_count < item.total_segment_count
        for item in browser.observations
    )
    assert browser.completed == [
        ("automatic", AUTO_REQUEST_ID, AUTO_EDITION_ID),
        ("manual", MANUAL_REQUEST_ID, MANUAL_EDITION_ID),
    ]
    assert audit.technical_context == browser.context
    assert browser.context.automatic_edition_fingerprint == (
        automatic.edition_fingerprint
    )
    assert browser.context.manual_edition_fingerprint == (
        manual.edition_fingerprint
    )
    assert audit.preflight_calls == 1
    assert audit.audit_calls == [
        (AUTO_REQUEST_ID, AUTO_EDITION_ID),
        (MANUAL_REQUEST_ID, MANUAL_EDITION_ID),
    ]
    assert recovery.restored_content_hash == baseline.content_hash
    assert recovery.restored_current_edition_id == BASE_EDITION_ID
    assert recovery.restored_current_script_version_id == BASE_SCRIPT_ID
    assert recovery.restored_draft_version > baseline.draft_version
    assert recovery.pointer_version_after_restore == baseline.pointer_version + 3
    assert recovery.append_only_history_retained is True
    assert recovery.new_authoritative_record_count == 2
    assert server.document_text == BASE_TEXT
    assert server.current_edition == BASE_EDITION_ID
    assert len(server.history) == 3

    patch_calls = [call for call in server.calls if call.method == "PATCH"]
    assert any("/segments/" in call.path for call in patch_calls)
    assert any(call.path.endswith("/draft") and call.body == {
        "expected_draft_version": 9,
        "content_markdown": BASE_TEXT,
        "content_hash": _sha(BASE_TEXT),
    } for call in patch_calls)
    assert len([call for call in server.calls if call.path.endswith("/prepare-range")]) == 2
    range_headers = [
        call.headers.get("Range")
        for call in server.calls
        if call.path.startswith("/media-assets/")
    ]
    assert "bytes=0-0" in range_headers
    assert any(
        value is not None and value.endswith("-") and value != "bytes=0-0"
        for value in range_headers
    )
    assert all("?" not in call.path and "#" not in call.path for call in server.calls)


def test_first_write_uses_the_sealed_baseline_fence_and_rejects_a_race(
    tmp_path: Path,
) -> None:
    class RacingServer(FakeHttpServer):
        raced = False

        def request(self, **kwargs: object) -> executor.HttpResponse:
            if (
                kwargs["method"] == "PATCH"
                and kwargs["path"] == f"/documents/{DOCUMENT_ID}/draft"
                and not self.raced
            ):
                self.raced = True
                self.document_version += 1
                self.document_text = "作者在基线后保存的新稿。"
                self.document_hash = _sha(self.document_text)
                return _json_response({"detail": {"code": "STALE"}}, status=409)
            return super().request(**kwargs)  # type: ignore[arg-type]

    server = RacingServer()
    checkpoints: list[
        tuple[runner.RecoveryFence, runner.RecoveryWriteIntent | None]
    ] = []
    value, config, _clock, _browser, _audit = _executor(
        tmp_path,
        server,
        checkpoint=lambda fence, intent: checkpoints.append((fence, intent)),
    )
    baseline = value.capture_baseline(config)

    with pytest.raises(runner.RunnerError, match="RECOVERY_CONFLICT"):
        value.run_automatic(config, _automatic_case())

    assert server.document_text == "作者在基线后保存的新稿。"
    assert checkpoints
    assert checkpoints[-1][0].draft_version == baseline.draft_version
    assert checkpoints[-1][1] is not None
    assert checkpoints[-1][1].operation_kind == "DRAFT_WRITE"


def test_save_text_is_a_verified_noop_when_baseline_content_already_matches(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    server.document_text = AUTO_TEXT
    server.document_hash = _sha(AUTO_TEXT)
    checkpoints: list[
        tuple[runner.RecoveryFence, runner.RecoveryWriteIntent | None]
    ] = []
    value, config, _clock, _browser, _audit = _executor(
        tmp_path,
        server,
        checkpoint=lambda fence, intent: checkpoints.append((fence, intent)),
    )
    baseline = value.capture_baseline(config)

    saved = value._save_text(AUTO_TEXT, _sha(AUTO_TEXT))  # noqa: SLF001

    assert saved["draft_version"] == baseline.draft_version
    assert saved["content_hash"] == baseline.content_hash
    assert checkpoints == []
    assert all(
        not (call.method == "PATCH" and call.path.endswith("/draft"))
        for call in server.calls
    )


def test_save_text_noop_rejects_an_existing_pending_write_intent(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    server.document_text = AUTO_TEXT
    server.document_hash = _sha(AUTO_TEXT)
    value, config, _clock, _browser, _audit = _executor(tmp_path, server)
    baseline = value.capture_baseline(config)
    value._pending_write_intent = runner.RecoveryWriteIntent(  # noqa: SLF001
        operation_kind="DRAFT_WRITE",
        operation_fingerprint_sha256=_sha("pending-draft-write"),
        old_fence=baseline,
        next_fence=baseline,
    )

    with pytest.raises(runner.RunnerError, match="RECOVERY_WRITE_INTENT_INVALID"):
        value._save_text(AUTO_TEXT, _sha(AUTO_TEXT))  # noqa: SLF001

    assert all(
        not (call.method == "PATCH" and call.path.endswith("/draft"))
        for call in server.calls
    )


def test_capture_and_restore_never_adopt_an_author_drifted_fence(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    value, config, _clock, _browser, _audit = _executor(tmp_path, server)
    baseline = value.capture_baseline(config)
    value.run_automatic(config, _automatic_case())
    owned = value.capture_recovery_fence(config)
    server.document_version += 1
    server.document_text = "作者在链完成后保存的新稿。"
    server.document_hash = _sha(server.document_text)
    writes_before = len(
        [call for call in server.calls if call.method in {"PATCH", "PUT"}]
    )

    with pytest.raises(runner.RunnerError, match="RECOVERY_CONFLICT"):
        value.capture_recovery_fence(config)
    with pytest.raises(runner.RunnerError, match="RECOVERY_CONFLICT"):
        value.restore_baseline(config, baseline, owned, None)

    writes_after = len(
        [call for call in server.calls if call.method in {"PATCH", "PUT"}]
    )
    assert writes_after == writes_before
    assert server.document_text == "作者在链完成后保存的新稿。"


def test_restore_patch_checkpoint_survives_put_failure_and_second_resume(
    tmp_path: Path,
) -> None:
    class OnePutFailureServer(FakeHttpServer):
        fail_baseline_put = False

        def request(self, **kwargs: object) -> executor.HttpResponse:
            body = kwargs.get("json_body")
            if (
                self.fail_baseline_put
                and kwargs["method"] == "PUT"
                and kwargs["path"]
                == f"/documents/{DOCUMENT_ID}/current-narration-edition"
                and isinstance(body, dict)
                and body.get("target_edition_id") == str(BASE_EDITION_ID)
            ):
                self.fail_baseline_put = False
                raise RuntimeError("simulated transport loss after draft restore")
            return super().request(**kwargs)  # type: ignore[arg-type]

    server = OnePutFailureServer()
    first, config, _clock, _browser, _audit = _executor(tmp_path, server)
    baseline = first.capture_baseline(config)
    first.run_automatic(config, _automatic_case())
    first.run_manual(config, _manual_case())
    owned = first.capture_recovery_fence(config)
    server.fail_baseline_put = True
    head: list[runner.RecoveryFence | runner.RecoveryWriteIntent | None] = [
        owned,
        None,
    ]
    checkpoints: list[
        tuple[runner.RecoveryFence, runner.RecoveryWriteIntent | None]
    ] = []

    def checkpoint(
        fence: runner.RecoveryFence,
        intent: runner.RecoveryWriteIntent | None,
    ) -> None:
        checkpoints.append((fence, intent))
        head[:] = [fence, intent]

    resumed_config = replace(config, resume=True)
    recovery_factory = executor.build_real_recovery_executor_factory(
        transport_factory=lambda _config: server,
        request_timeout_seconds=5,
    )
    first_restore = recovery_factory(resumed_config)
    first_restore.set_recovery_checkpoint(checkpoint)
    with pytest.raises(runner.RunnerError, match="HTTP_TRANSPORT_FAILED"):
        first_restore.restore_baseline(
            resumed_config,
            baseline,
            owned,
            None,
        )

    assert checkpoints[-1][1] is not None
    assert checkpoints[-1][1].operation_kind == "EDITION_SWITCH"
    assert checkpoints[-1][0].content_hash == baseline.content_hash
    assert server.document_text == BASE_TEXT
    assert server.current_edition == MANUAL_EDITION_ID

    second_restore = recovery_factory(resumed_config)
    second_restore.set_recovery_checkpoint(checkpoint)
    recovery = second_restore.restore_baseline(
        resumed_config,
        baseline,
        head[0],  # type: ignore[arg-type]
        head[1],  # type: ignore[arg-type]
    )

    assert recovery.restored_current_edition_id == BASE_EDITION_ID
    assert server.current_edition == BASE_EDITION_ID
    assert server.document_text == BASE_TEXT


def test_prerelease_t4k_rejects_public_product_visibility(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    value, config, _clock, _browser, _audit = _executor(
        tmp_path,
        server,
        audit=FakeRuntimeAuditProbe(product_visible=True),
    )

    with pytest.raises(runner.RunnerError, match="RUNTIME_PREFLIGHT_FAILED"):
        value.capture_baseline(config)


def test_restore_only_executor_can_resume_without_normal_write_ports(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    first, config, _clock, _browser, _audit = _executor(tmp_path, server)
    baseline = first.capture_baseline(config)
    first.run_automatic(config, _automatic_case())
    first.run_manual(config, _manual_case())
    fence = first.capture_recovery_fence(config)
    assert server.current_edition == MANUAL_EDITION_ID

    resumed_config = replace(config, resume=True)
    recovery_factory = executor.build_real_recovery_executor_factory(
        transport_factory=lambda _config: server,
        request_timeout_seconds=5,
    )
    resumed = recovery_factory(resumed_config)
    resumed.set_recovery_checkpoint(lambda _fence, _intent: None)
    recovery = resumed.restore_baseline(
        resumed_config,
        baseline,
        fence,
        None,
    )

    assert isinstance(resumed, executor.RealChapterE2ERecoveryExecutor)
    assert not hasattr(resumed, "run_automatic")
    assert not hasattr(resumed, "run_manual")
    assert not hasattr(resumed, "run_technical_checks")
    assert recovery.restored_current_edition_id == BASE_EDITION_ID
    assert recovery.new_authoritative_record_count == 2
    assert server.document_text == BASE_TEXT
    assert server.current_edition == BASE_EDITION_ID


@pytest.mark.parametrize(
    ("missing", "code"),
    [
        ("transport", "REAL_HTTP_TRANSPORT_REQUIRED"),
        ("browser", "REAL_BROWSER_PROBE_REQUIRED"),
        ("audit", "REAL_RUNTIME_AUDIT_PROBE_REQUIRED"),
    ],
)
def test_executor_fails_closed_when_any_required_port_is_missing(
    tmp_path: Path,
    missing: str,
    code: str,
) -> None:
    config = _config(tmp_path)
    dependencies: dict[str, object | None] = {
        "transport": FakeHttpServer(),
        "browser": FakeBrowserProbe(),
        "audit": FakeRuntimeAuditProbe(),
    }
    dependencies[missing] = None

    with pytest.raises(runner.RunnerError, match=code) as caught:
        executor.RealChapterE2EExecutor(
            config,
            transport=dependencies["transport"],  # type: ignore[arg-type]
            browser_probe=dependencies["browser"],  # type: ignore[arg-type]
            runtime_audit_probe=dependencies["audit"],  # type: ignore[arg-type]
        )

    assert caught.value.code == code


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("transport_factory", "REAL_HTTP_TRANSPORT_REQUIRED"),
        ("browser_probe_factory", "REAL_BROWSER_PROBE_REQUIRED"),
        ("runtime_audit_probe_factory", "REAL_RUNTIME_AUDIT_PROBE_REQUIRED"),
    ],
)
def test_factory_builder_fails_closed_before_launcher_construction(
    field: str,
    code: str,
) -> None:
    kwargs: dict[str, Any] = {
        "transport_factory": lambda _config: FakeHttpServer(),
        "browser_probe_factory": lambda _config: FakeBrowserProbe(),
        "runtime_audit_probe_factory": lambda _config: FakeRuntimeAuditProbe(),
    }
    kwargs[field] = None

    with pytest.raises(runner.RunnerError, match=code):
        executor.build_real_executor_factory(**kwargs)


@pytest.mark.parametrize(
    "api_base",
    [
        "https://127.0.0.1:18088/api/ai-novel-world-2026",
        "http://example.com:18088/api/ai-novel-world-2026",
        "http://user:pass@127.0.0.1:18088/api/ai-novel-world-2026",
        "http://127.0.0.1:18088/api/ai-novel-world-2026?token=x",
        "http://127.0.0.1:18088/api/ai-novel-world-2026#fragment",
        "http://127.0.0.1:18088/api/other",
    ],
)
def test_loopback_transport_rejects_non_fixed_origins_without_network(
    api_base: str,
) -> None:
    with pytest.raises(runner.RunnerError, match="API_BASE_NOT_LOOPBACK"):
        executor.LoopbackHttpTransport(api_base)


def test_loopback_transport_injects_private_validation_header_without_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def getheader(self, name: str):  # type: ignore[no-untyped-def]
            return "2" if name == "Content-Length" else None

        def read(self, _maximum: int) -> bytes:
            return b"{}"

        def getheaders(self):  # type: ignore[no-untyped-def]
            return [("Content-Type", "application/json")]

        def close(self) -> None:
            observed["response_closed"] = True

    class FakeConnection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            observed["connection"] = (host, port, timeout)

        def request(
            self,
            method: str,
            target: str,
            *,
            body: bytes | None,
            headers: Mapping[str, str],
        ) -> None:
            observed["request"] = (method, target, body, dict(headers))

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            observed["connection_closed"] = True

    monkeypatch.setattr(executor.http.client, "HTTPConnection", FakeConnection)
    token = "v" * 43
    transport = executor.LoopbackHttpTransport(
        API_BASE,
        validation_token=token,
    )

    response = transport.request(
        method="GET",
        path="/health",
        timeout_seconds=1,
    )

    assert response.status == 200
    request = observed["request"]
    assert isinstance(request, tuple)
    headers = request[3]
    assert isinstance(headers, dict)
    assert headers[executor.VALIDATION_TOKEN_HEADER] == token
    assert token not in repr(response)
    assert observed["response_closed"] is True
    assert observed["connection_closed"] is True

    with pytest.raises(runner.RunnerError, match="HTTP_REQUEST_INVALID"):
        transport.request(
            method="GET",
            path="/health",
            headers={executor.VALIDATION_TOKEN_HEADER: token},
            timeout_seconds=1,
        )

    with pytest.raises(runner.RunnerError, match="VALIDATION_TOKEN_INVALID"):
        executor.LoopbackHttpTransport(API_BASE, validation_token="too-short")


def test_loopback_transport_can_emit_two_physical_validation_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {"headers": []}

    class FakeResponse:
        status = 200

        def getheader(self, name: str):  # type: ignore[no-untyped-def]
            return "2" if name == "Content-Length" else None

        def read(self, _maximum: int) -> bytes:
            return b"{}"

        def getheaders(self):  # type: ignore[no-untyped-def]
            return [("Content-Type", "application/json")]

        def close(self) -> None:
            observed["response_closed"] = True

    class FakeConnection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            observed["connection"] = (host, port, timeout)

        def putrequest(self, method: str, target: str) -> None:
            observed["request"] = (method, target)

        def putheader(self, name: str, value: str) -> None:
            headers = observed["headers"]
            assert isinstance(headers, list)
            headers.append((name, value))

        def endheaders(self, body: bytes | None) -> None:
            observed["body"] = body

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            observed["connection_closed"] = True

    monkeypatch.setattr(executor.http.client, "HTTPConnection", FakeConnection)
    token = "d" * 43
    transport = executor.LoopbackHttpTransport(
        API_BASE,
        explicit_validation_tokens=(token, token),
    )

    response = transport.request(
        method="GET",
        path=f"/novels/{NOVEL_ID}/narration-overview",
        timeout_seconds=1,
    )

    headers = observed["headers"]
    assert isinstance(headers, list)
    validation_headers = [
        value
        for name, value in headers
        if name.casefold() == executor.VALIDATION_TOKEN_HEADER.casefold()
    ]
    assert validation_headers == [token, token]
    assert response.status == 200
    assert observed["body"] is None
    assert observed["response_closed"] is True
    assert observed["connection_closed"] is True

    with pytest.raises(runner.RunnerError, match="HTTP_REQUEST_INVALID"):
        transport.request(
            method="GET",
            path="/health",
            headers={executor.VALIDATION_TOKEN_HEADER: token},
            timeout_seconds=1,
        )

    with pytest.raises(runner.RunnerError, match="VALIDATION_TOKEN_INVALID"):
        executor.LoopbackHttpTransport(
            API_BASE,
            validation_token=token,
            explicit_validation_tokens=(token, token),
        )


def test_t4k_hidden_gate_preflight_covers_all_negative_modes_before_t4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "v" * 43
    calls: list[tuple[str, str, str]] = []
    constructed_modes: list[str] = []

    class FakeGateTransport:
        def __init__(
            self,
            api_base: str,
            *,
            validation_token: str | None = None,
            explicit_validation_tokens: tuple[str, str] | None = None,
        ) -> None:
            assert api_base == API_BASE
            if explicit_validation_tokens is not None:
                assert explicit_validation_tokens == (token, token)
                self.mode = "duplicate"
            elif validation_token is None:
                self.mode = "none"
            elif validation_token == token:
                self.mode = "correct"
            else:
                assert validation_token != token
                self.mode = "wrong"
            constructed_modes.append(self.mode)

        def request(
            self,
            *,
            method: str,
            path: str,
            headers: Mapping[str, str] | None = None,
            json_body: object | None = None,
            timeout_seconds: float,
        ) -> executor.HttpResponse:
            assert headers is None
            assert json_body is None
            assert timeout_seconds == 30.0
            calls.append((self.mode, method, path))
            if path.endswith("/narration-overview"):
                return _overview_response(
                    T4_ENABLED if self.mode == "correct" else T2_ENABLED
                )
            assert self.mode != "correct"
            return _hidden_gate_response()

    monkeypatch.setattr(executor, "LoopbackHttpTransport", FakeGateTransport)

    executor.verify_t4k_hidden_release_gate(
        _config(tmp_path),
        validation_token=token,
    )

    assert constructed_modes == ["none", "wrong", "duplicate", "correct"]
    for mode in ("none", "wrong", "duplicate"):
        mode_calls = [call for call in calls if call[0] == mode]
        assert [call[1] for call in mode_calls] == ["GET"] * 4
        assert [call[2] for call in mode_calls] == [
            f"/narration-requests/{DOCUMENT_ID}",
            f"/narration-script-versions/{DOCUMENT_ID}",
            f"/narration-editions/{DOCUMENT_ID}/manifest",
            f"/novels/{NOVEL_ID}/narration-overview",
        ]
    assert [call for call in calls if call[0] == "correct"] == [
        ("correct", "GET", f"/novels/{NOVEL_ID}/narration-overview")
    ]


def test_t4k_hidden_gate_preflight_rejects_an_ordinary_resource_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOpenGateTransport:
        def __init__(self, _api_base: str, **_kwargs: object) -> None:
            pass

        def request(self, **_kwargs: object) -> executor.HttpResponse:
            return _json_response(
                {
                    "detail": {
                        "contract_version": "narration-production-api/1",
                        "code": "RESOURCE_NOT_FOUND",
                        "message": "找不到请求的朗读生产资源。",
                        "retryable": False,
                        "field": None,
                        "current_version": None,
                    }
                },
                status=404,
                headers={"Cache-Control": "no-store"},
            )

    monkeypatch.setattr(executor, "LoopbackHttpTransport", FakeOpenGateTransport)

    with pytest.raises(
        runner.RunnerError,
        match="T4_HIDDEN_ROUTE_GATE_FAILED",
    ) as caught:
        executor.verify_t4k_hidden_release_gate(
            _config(tmp_path),
            validation_token="v" * 43,
        )

    assert caught.value.code == "T4_HIDDEN_ROUTE_GATE_FAILED"


@pytest.mark.parametrize(
    ("drift", "expected_code"),
    [
        ("negative_t4", "T4_HIDDEN_OVERVIEW_T2_FAILED"),
        ("correct_t2", "T4_VALIDATION_OVERVIEW_T4_FAILED"),
    ],
)
def test_t4k_hidden_gate_preflight_rejects_overview_tier_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    expected_code: str,
) -> None:
    token = "v" * 43

    class FakeTierDriftTransport:
        def __init__(
            self,
            _api_base: str,
            *,
            validation_token: str | None = None,
            explicit_validation_tokens: tuple[str, str] | None = None,
        ) -> None:
            if explicit_validation_tokens is not None:
                self.mode = "duplicate"
            elif validation_token is None:
                self.mode = "none"
            elif validation_token == token:
                self.mode = "correct"
            else:
                self.mode = "wrong"

        def request(self, *, path: str, **_kwargs: object) -> executor.HttpResponse:
            if not path.endswith("/narration-overview"):
                return _hidden_gate_response()
            if self.mode == "correct":
                enabled = T2_ENABLED if drift == "correct_t2" else T4_ENABLED
            else:
                enabled = (
                    T4_ENABLED
                    if drift == "negative_t4" and self.mode == "none"
                    else T2_ENABLED
                )
            return _overview_response(enabled)

    monkeypatch.setattr(
        executor,
        "LoopbackHttpTransport",
        FakeTierDriftTransport,
    )

    with pytest.raises(runner.RunnerError, match=expected_code) as caught:
        executor.verify_t4k_hidden_release_gate(
            _config(tmp_path),
            validation_token=token,
        )

    assert caught.value.code == expected_code
    assert token not in str(caught.value)


@pytest.mark.parametrize(
    "path",
    [
        "/documents/10000000-0000-4000-8000-000000000002?token=x",
        "/documents/10000000-0000-4000-8000-000000000002#x",
        "//example.com/health",
        "/admin",
        "/media-assets/23000000-0000-4000-8000-000000000001/content/../secret",
    ],
)
def test_loopback_transport_rejects_paths_outside_allowlist_before_network(
    path: str,
) -> None:
    transport = executor.LoopbackHttpTransport(API_BASE)
    with pytest.raises(runner.RunnerError, match="HTTP_PATH_NOT_ALLOWED"):
        transport.request(
            method="GET",
            path=path,
            timeout_seconds=1,
        )


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "actual_status", "expected_code"),
    [
        (
            "POST",
            f"/narration-script-versions/{MANUAL_PATCHED_SCRIPT_ID}/approve",
            200,
            503,
            (
                "HTTP_STATUS_UNEXPECTED_S_APPROVE_M_POST_P_SCRIPT_APPROVE"
                "_E200_A503"
            ),
        ),
        (
            "GET",
            f"/narration-requests/{AUTO_REQUEST_ID}",
            200,
            502,
            (
                "HTTP_STATUS_UNEXPECTED_S_WORKFLOW_GET_M_GET_P_NARRATION_REQUEST"
                "_E200_A502"
            ),
        ),
        (
            "GET",
            f"/narration-editions/{AUTO_EDITION_ID}/manifest",
            200,
            504,
            (
                "HTTP_STATUS_UNEXPECTED_S_MANIFEST_GET_M_GET_P_EDITION_MANIFEST"
                "_E200_A504"
            ),
        ),
    ],
)
def test_unexpected_http_status_has_fixed_redacted_stage_diagnostics(
    method: str,
    path: str,
    expected_status: int,
    actual_status: int,
    expected_code: str,
) -> None:
    secret = "secret-token-must-not-leak"
    response = executor.HttpResponse(
        status=actual_status,
        headers={"Authorization": f"Bearer {secret}"},
        body=(f'{{"detail":"{secret}","text":"私密正文"}}').encode(),
    )

    with pytest.raises(runner.RunnerError) as caught:
        executor._response_json(
            response,
            expected_status,
            method=method,
            path=path,
        )

    assert caught.value.code == expected_code
    assert secret not in str(caught.value)
    assert "私密正文" not in str(caught.value)
    assert str(AUTO_REQUEST_ID) not in str(caught.value)
    assert str(AUTO_EDITION_ID) not in str(caught.value)
    assert str(MANUAL_PATCHED_SCRIPT_ID) not in str(caught.value)


def test_poll_ready_fails_fast_on_nonretryable_manifest_failure(
    tmp_path: Path,
) -> None:
    class NonRetryableManifestServer(FakeHttpServer):
        def _manifest_response(self, path: str) -> executor.HttpResponse:
            response = super()._manifest_response(path)
            payload = json.loads(response.body)
            if payload["status"] == "partial_ready":
                payload["segments"][1].update(
                    {
                        "render_status": "failed",
                        "audio": None,
                        "failure": {
                            "code": "NANO_AUDIO_INVALID",
                            "retryable": False,
                            "message": "私密正文与内部诊断不得进入错误码。",
                        },
                    }
                )
                return _json_response(
                    payload,
                    headers={"ETag": str(payload["etag"])},
                )
            return response

    server = NonRetryableManifestServer()
    value, config, clock, browser, _audit = _executor(tmp_path, server)
    value.capture_baseline(config)

    with pytest.raises(runner.RunnerError) as caught:
        value.run_automatic(config, _automatic_case())

    assert caught.value.code == (
        "MANIFEST_NONRETRYABLE_FAILURE_NANO_AUDIO_INVALID"
    )
    assert "私密正文" not in str(caught.value)
    assert clock.value == 101.0
    assert server.poll_counts[AUTO_REQUEST_ID] == 1
    assert browser.observations == []


def test_unrecognized_nonretryable_manifest_failure_is_redacted_to_digest() -> None:
    public_code = "FUTURE_PUBLIC_FAILURE"
    expected_digest = hashlib.sha256(public_code.encode("ascii")).hexdigest()[:12].upper()

    result = executor._manifest_nonretryable_error_code(public_code)

    assert result == f"MANIFEST_NONRETRYABLE_FAILURE_UNKNOWN_{expected_digest}"
    assert public_code not in result


def test_manual_locator_mismatch_stops_before_patch_or_approval(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer(locator_mismatch=True)
    value, config, _clock, _browser, _audit = _executor(tmp_path, server)
    value.capture_baseline(config)
    value.run_automatic(config, _automatic_case())

    with pytest.raises(runner.RunnerError, match="CORRECTION_SEGMENT_MISMATCH"):
        value.run_manual(config, _manual_case())

    assert not any("/segments/" in call.path for call in server.calls)
    assert not any(call.path.endswith("/approve") for call in server.calls)


def test_public_api_cannot_substitute_for_missing_nano_voice_audit(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    audit = FakeRuntimeAuditProbe(invalid_audit=True)
    value, config, _clock, _browser, _audit = _executor(
        tmp_path, server, audit=audit
    )
    value.capture_baseline(config)

    with pytest.raises(runner.RunnerError, match="NANO_AUDIT_EVIDENCE_INVALID"):
        value.run_automatic(config, _automatic_case())

    assert server.editions[AUTO_EDITION_ID]["state"] == "ready"
    assert server.current_edition == BASE_EDITION_ID


def test_chain_audit_must_match_the_preflight_model_fingerprint(
    tmp_path: Path,
) -> None:
    class DriftingRuntimeAuditProbe(FakeRuntimeAuditProbe):
        def audit_chain(self, *args: object, **kwargs: object) -> executor.ChainAuditEvidence:
            evidence = super().audit_chain(*args, **kwargs)  # type: ignore[arg-type]
            return executor.ChainAuditEvidence(
                request_id=evidence.request_id,
                edition_id=evidence.edition_id,
                script_version_id=evidence.script_version_id,
                edition_fingerprint=evidence.edition_fingerprint,
                distinct_voice_version_count=evidence.distinct_voice_version_count,
                uncached_nano_job_count=evidence.uncached_nano_job_count,
                model_run_fingerprints=(_sha("different-model"),),
            )

    server = FakeHttpServer()
    value, config, _clock, _browser, _audit = _executor(
        tmp_path,
        server,
        audit=DriftingRuntimeAuditProbe(),
    )
    value.capture_baseline(config)

    with pytest.raises(runner.RunnerError, match="NANO_AUDIT_EVIDENCE_INVALID"):
        value.run_automatic(config, _automatic_case())


@pytest.mark.parametrize("bad_fingerprint", [None, "f" * 63, "A" * 64])
def test_edition_api_requires_a_canonical_sha256_fingerprint(
    tmp_path: Path,
    bad_fingerprint: str | None,
) -> None:
    class InvalidEditionFingerprintServer(FakeHttpServer):
        def _create_edition(self, **kwargs: Any) -> None:
            super()._create_edition(**kwargs)
            edition_id = kwargs["edition_id"]
            assert isinstance(edition_id, UUID)
            if bad_fingerprint is None:
                self.editions[edition_id].pop("edition_fingerprint")
            else:
                self.editions[edition_id]["edition_fingerprint"] = bad_fingerprint

    server = InvalidEditionFingerprintServer()
    value, config, _clock, _browser, _audit = _executor(tmp_path, server)
    value.capture_baseline(config)

    with pytest.raises(runner.RunnerError, match="EDITION_FINGERPRINT_MISMATCH"):
        value.run_automatic(config, _automatic_case())

    assert server.current_edition == BASE_EDITION_ID


def test_edition_api_and_runtime_audit_fingerprints_must_match(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    audit = FakeRuntimeAuditProbe(
        edition_fingerprint_override=_sha("different-edition")
    )
    value, config, _clock, _browser, _audit = _executor(
        tmp_path,
        server,
        audit=audit,
    )
    value.capture_baseline(config)

    with pytest.raises(runner.RunnerError, match="EDITION_FINGERPRINT_MISMATCH"):
        value.run_automatic(config, _automatic_case())

    assert server.current_edition == BASE_EDITION_ID


def test_browser_probe_failure_is_not_synthesized_into_a_pass(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    browser = FakeBrowserProbe(pass_gate=False)
    value, config, _clock, _browser, _audit = _executor(
        tmp_path, server, browser=browser
    )
    value.capture_baseline(config)
    value.run_automatic(config, _automatic_case())
    value.run_manual(config, _manual_case())

    with pytest.raises(runner.RunnerError, match="BROWSER_PROBE_EVIDENCE_INVALID"):
        value.run_technical_checks(config, _fixture())


def test_factory_shape_is_directly_usable_by_future_fixed_launcher(
    tmp_path: Path,
) -> None:
    server = FakeHttpServer()
    clock = FakeClock()
    factory = executor.build_real_executor_factory(
        transport_factory=lambda _config: server,
        browser_probe_factory=lambda _config: FakeBrowserProbe(),
        runtime_audit_probe_factory=lambda _config: FakeRuntimeAuditProbe(),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        request_timeout_seconds=5,
        workflow_timeout_seconds=20,
        poll_interval_seconds=1,
    )

    value = factory(_config(tmp_path))

    assert isinstance(value, executor.RealChapterE2EExecutor)
