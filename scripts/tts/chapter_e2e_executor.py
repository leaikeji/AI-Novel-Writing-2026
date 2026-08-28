#!/usr/bin/env python3
"""Fixed-loopback HTTP executor candidate for the guarded T4-K runner.

The module deliberately owns no CLI entry point.  A separately approved
launcher must construct all three external ports explicitly:

* :class:`HttpTransport` for the public PawApp HTTP contract;
* :class:`BrowserProbe` for real editor/player observations;
* :class:`RuntimeAuditProbe` for read-only Nano/voice/runtime evidence that the
  public product API intentionally does not expose.

Missing ports, non-loopback targets, unexpected response shapes, and missing
audit evidence all fail closed with stable ``RunnerError`` codes.  Chapter text
and audio bytes are used only in memory and are never included in errors.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import http.client
import json
import math
import re
import time
from typing import Callable, Final, Literal, Mapping, Protocol, Sequence, cast
from urllib.parse import urlsplit
from uuid import UUID

from backend.narration.release_gate import VALIDATION_TOKEN_HEADER
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    API_PATH,
    LOOPBACK_HOSTS,
    BaselineSnapshot,
    ChainOutcome,
    ChapterCase,
    ChapterFixture,
    ExecutorFactory,
    RecoveryExecutorFactory,
    RecoveryFence,
    RecoveryOutcome,
    RecoveryWriteIntent,
    RunnerConfig,
    RunnerError,
    TechnicalOutcome,
)


_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
_UTC_SECOND_RE: Final = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
_VALIDATION_TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_T2_ENABLED_CAPABILITIES: Final = frozenset(
    {"narration_product", "reading_settings"}
)
_T4_ENABLED_CAPABILITIES: Final = frozenset(
    {
        *_T2_ENABLED_CAPABILITIES,
        "narration_synthesis",
        "product_player",
        "editor_production",
        "voice_preview",
        "preset_voice_source",
        "automatic_speaker_detection",
    }
)
_ALL_CAPABILITIES: Final = frozenset(
    {
        *_T4_ENABLED_CAPABILITIES,
        "voice_preview",
        "preset_voice_source",
        "reference_clone",
        "generic_voice_pool",
        "automatic_generic_casting",
        "cloud_assisted_analysis",
        "voice_generator",
        "cache_cleanup",
    }
)
_UUID_PATH: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_ALLOWED_PATHS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    "GET": tuple(
        re.compile(pattern)
        for pattern in (
            r"^/health$",
            rf"^/documents/{_UUID_PATH}$",
            rf"^/documents/{_UUID_PATH}/narration-playback-context$",
            rf"^/novels/{_UUID_PATH}/narration-settings$",
            rf"^/novels/{_UUID_PATH}/narration-overview$",
            rf"^/novels/{_UUID_PATH}/characters$",
            rf"^/narration-requests/{_UUID_PATH}$",
            rf"^/narration-editions/{_UUID_PATH}$",
            rf"^/narration-script-versions/{_UUID_PATH}$",
            rf"^/narration-editions/{_UUID_PATH}/manifest$",
            rf"^/media-assets/{_UUID_PATH}/content$",
            (
                rf"^/novels/{_UUID_PATH}/documents/{_UUID_PATH}"
                r"/narration-validation-segment-claim-gate$"
            ),
        )
    ),
    "HEAD": (re.compile(rf"^/media-assets/{_UUID_PATH}/content$"),),
    "PATCH": (
        re.compile(rf"^/documents/{_UUID_PATH}/draft$"),
        re.compile(
            rf"^/narration-script-versions/{_UUID_PATH}/segments/{_UUID_PATH}$"
        ),
    ),
    "POST": (
        re.compile(rf"^/documents/{_UUID_PATH}/narration-requests$"),
        re.compile(rf"^/narration-script-versions/{_UUID_PATH}/approve$"),
        re.compile(rf"^/narration-editions/{_UUID_PATH}/prepare-range$"),
        re.compile(
            rf"^/novels/{_UUID_PATH}/documents/{_UUID_PATH}"
            r"/narration-validation-segment-claim-gate(?:/release)?$"
        ),
    ),
    "PUT": (
        re.compile(rf"^/documents/{_UUID_PATH}/current-narration-edition$"),
    ),
}
_TERMINAL_WORKFLOW_FAILURES: Final = frozenset(
    {"failed", "cancelled", "cancel_requested"}
)
_MANIFEST_FAILURE_CODE_ALLOWLIST: Final = frozenset(
    {
        "FAILURE_RECORDING_UNAVAILABLE",
        "NANO_ADAPTER_UNAVAILABLE",
        "NANO_AUDIO_INVALID",
        "RESOURCE_FENCE_MISSING",
        "SEGMENT_RENDER_FAILED",
        "STALE_WORKER_FENCE",
    }
)
_WORKFLOW_STATES: Final = frozenset(
    {
        "created",
        "analyzing",
        "analyzed",
        "review_required",
        "queued",
        "rendering",
        "partial_ready",
        "ready",
        "cancel_requested",
        "cancelled",
        "failed",
    }
)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Bounded HTTP response used by the executor and fake transports."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        wanted = name.casefold()
        matches = [value for key, value in self.headers.items() if key.casefold() == wanted]
        if len(matches) > 1:
            raise RunnerError("HTTP_RESPONSE_INVALID")
        return matches[0] if matches else None


class HttpTransport(Protocol):
    """Synchronous, no-redirect HTTP port restricted to executor-owned paths."""

    def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        timeout_seconds: float,
    ) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class RuntimePreflightEvidence:
    production_ready: bool
    sidecar_ready: bool
    product_visible: bool
    model_fingerprint: str


@dataclass(frozen=True, slots=True)
class ChainAuditEvidence:
    request_id: UUID
    edition_id: UUID
    script_version_id: UUID
    edition_fingerprint: str
    distinct_voice_version_count: int
    uncached_nano_job_count: int
    model_run_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TechnicalProbeContext:
    automatic_request_id: UUID
    automatic_edition_id: UUID
    automatic_edition_fingerprint: str
    automatic_manifest_revision: int
    manual_request_id: UUID
    manual_edition_id: UUID
    manual_edition_fingerprint: str
    manual_manifest_revision: int
    request_to_ready_seconds: tuple[float, float]
    observed_http_first_audio_ms: tuple[int, int]
    chapter_audio_duration_seconds: float
    range_status_codes: tuple[int, ...]
    listening_output_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BrowserManifestObservation:
    chain_label: Literal["automatic", "manual"]
    request_id: UUID
    edition_id: UUID
    workflow_state: str
    manifest_revision: int
    ready_segment_count: int
    total_segment_count: int
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class BrowserTechnicalEvidence:
    time_to_first_audio_ms: int
    seek_latest_wins: bool
    pending_gap_not_skipped: bool
    edit_actions_created_tts_writes: int
    browser_viewports: tuple[tuple[int, int], ...]
    browser_assistant_modes: tuple[Literal["collapsed", "expanded"], ...]
    browser_console_error_count: int
    browser_overlap_count: int
    collector_collected_at: str
    evidence_class: str | None = None
    evidence_root_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeTechnicalEvidence:
    stability_elapsed_seconds: float
    peak_memory_bytes: int
    pageout_delta: int
    swapout_delta: int
    memory_baseline_median_bytes: int
    memory_tail_median_bytes: int
    memory_growth_bytes: int
    memory_growth_limit_bytes: int
    sidecar_memory_growth_observed: bool
    seam_pairs_checked: int
    sidecar_restart_count: int
    health_failure_count: int
    host_paging_observed: bool
    qwenpaw_slowdown_observed: bool


@dataclass(frozen=True, slots=True)
class ValidationClaimGateEvidence:
    """Redacted exact-scope state from the hidden validation claim gate."""

    code: str
    state: Literal["default_allow", "armed", "paused"]
    claim_limit: int
    claimed_count: int
    remaining_count: int
    expires_at: str | None
    run_fingerprint_sha256: str | None
    scope_fingerprint_sha256: str | None


@dataclass(frozen=True, slots=True)
class PartialReadyValidationEvidence:
    """Secret-free append-only marker fields supplied by the real executor."""

    source_content_sha256: str
    return_fence_sha256: str
    request_id: UUID | None = None
    script_version_id: UUID | None = None
    edition_id: UUID | None = None
    manifest_revision: int | None = None
    manifest_etag_sha256: str | None = None
    manifest_payload_sha256: str | None = None
    ready_prefix_count: int | None = None
    ready_prefix_duration_ms: int | None = None
    cache_hit_prefix_count: int | None = None
    cache_miss_job_count: int | None = None
    gate_claimed_count: int | None = None
    gate_run_fingerprint_sha256: str | None = None
    gate_scope_fingerprint_sha256: str | None = None
    restored_fence_sha256: str | None = None
    error_code: str | None = None


class PartialReadyValidationCoordinator(Protocol):
    """Launcher-owned gate and private marker port; absent in normal runs."""

    def arm(self, config: RunnerConfig) -> ValidationClaimGateEvidence: ...

    def read(self, config: RunnerConfig) -> ValidationClaimGateEvidence: ...

    def release(self, config: RunnerConfig) -> ValidationClaimGateEvidence: ...

    def record(
        self,
        config: RunnerConfig,
        *,
        state: Literal[
            "staging",
            "gate_armed",
            "partial_ready",
            "browser_observed",
            "gate_released",
            "completed_restored",
            "recovery_required",
        ],
        evidence: PartialReadyValidationEvidence,
    ) -> None: ...


class BrowserProbe(Protocol):
    """Real-browser probe; it must not write narration authority directly."""

    def begin_chain(
        self,
        config: RunnerConfig,
        chain_label: Literal["automatic", "manual"],
    ) -> None: ...

    def observe_manifest(
        self,
        config: RunnerConfig,
        observation: BrowserManifestObservation,
    ) -> None: ...

    def complete_chain(
        self,
        config: RunnerConfig,
        *,
        chain_label: Literal["automatic", "manual"],
        request_id: UUID,
        edition_id: UUID,
    ) -> None: ...

    def collect(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
        context: TechnicalProbeContext,
    ) -> BrowserTechnicalEvidence: ...


class RuntimeAuditProbe(Protocol):
    """Narrow read-only port for evidence absent from public product DTOs."""

    def preflight(self, config: RunnerConfig) -> RuntimePreflightEvidence: ...

    def audit_chain(
        self,
        config: RunnerConfig,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
    ) -> ChainAuditEvidence: ...

    def collect_technical(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
        context: TechnicalProbeContext,
    ) -> RuntimeTechnicalEvidence: ...


TransportFactory = Callable[[RunnerConfig], HttpTransport]
BrowserProbeFactory = Callable[[RunnerConfig], BrowserProbe]
RuntimeAuditProbeFactory = Callable[[RunnerConfig], RuntimeAuditProbe]


class LoopbackHttpTransport:
    """No-redirect stdlib transport pinned to one loopback API origin/prefix."""

    def __init__(
        self,
        api_base: str,
        *,
        validation_token: str | None = None,
        explicit_validation_tokens: tuple[str, str] | None = None,
        maximum_response_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        parsed = _validated_api_base(api_base)
        if type(maximum_response_bytes) is not int or not (
            1024 <= maximum_response_bytes <= 1024 * 1024 * 1024
        ):
            raise RunnerError("HTTP_LIMIT_INVALID")
        assert parsed.hostname is not None and parsed.port is not None
        self._host = parsed.hostname
        self._port = parsed.port
        self._maximum_response_bytes = maximum_response_bytes
        if validation_token is not None and (
            type(validation_token) is not str
            or _VALIDATION_TOKEN_RE.fullmatch(validation_token) is None
        ):
            raise RunnerError("VALIDATION_TOKEN_INVALID")
        if (
            validation_token is not None
            and explicit_validation_tokens is not None
        ):
            raise RunnerError("VALIDATION_TOKEN_INVALID")
        if explicit_validation_tokens is not None and (
            type(explicit_validation_tokens) is not tuple
            or len(explicit_validation_tokens) != 2
            or explicit_validation_tokens[0] != explicit_validation_tokens[1]
            or any(
                type(value) is not str
                or _VALIDATION_TOKEN_RE.fullmatch(value) is None
                for value in explicit_validation_tokens
            )
        ):
            raise RunnerError("VALIDATION_TOKEN_INVALID")
        self._validation_token = validation_token
        self._explicit_validation_tokens = explicit_validation_tokens

    def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str] | None = None,
        json_body: object | None = None,
        timeout_seconds: float,
    ) -> HttpResponse:
        normalized_method = _validate_method_path(method, path)
        if type(timeout_seconds) not in {int, float} or not math.isfinite(
            float(timeout_seconds)
        ) or not (0 < float(timeout_seconds) <= 120):
            raise RunnerError("HTTP_TIMEOUT_INVALID")
        request_headers = _validated_headers(headers or {})
        if (
            self._validation_token is not None
            or self._explicit_validation_tokens is not None
        ):
            if any(
                key.casefold() == VALIDATION_TOKEN_HEADER.casefold()
                for key in request_headers
            ):
                raise RunnerError("HTTP_REQUEST_INVALID")
        if self._validation_token is not None:
            request_headers[VALIDATION_TOKEN_HEADER] = self._validation_token
        request_headers.setdefault("Accept", "application/json")
        body: bytes | None = None
        if json_body is not None:
            if normalized_method not in {"PATCH", "POST", "PUT"}:
                raise RunnerError("HTTP_REQUEST_INVALID")
            try:
                body = json.dumps(
                    json_body,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8", errors="strict")
            except (TypeError, ValueError, UnicodeError) as error:
                raise RunnerError("HTTP_REQUEST_INVALID") from error
            request_headers["Content-Type"] = "application/json"
        target = f"{API_PATH}{path}"
        connection = http.client.HTTPConnection(
            self._host,
            self._port,
            timeout=float(timeout_seconds),
        )
        response: http.client.HTTPResponse | None = None
        try:
            if self._explicit_validation_tokens is None:
                connection.request(
                    normalized_method,
                    target,
                    body=body,
                    headers=request_headers,
                )
            else:
                connection.putrequest(normalized_method, target)
                for key, value in request_headers.items():
                    connection.putheader(key, value)
                for value in self._explicit_validation_tokens:
                    connection.putheader(VALIDATION_TOKEN_HEADER, value)
                if body is not None:
                    connection.putheader("Content-Length", str(len(body)))
                connection.endheaders(body)
            response = connection.getresponse()
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    declared_length = int(declared)
                except ValueError as error:
                    raise RunnerError("HTTP_RESPONSE_INVALID") from error
                if declared_length < 0 or declared_length > self._maximum_response_bytes:
                    raise RunnerError("HTTP_RESPONSE_TOO_LARGE")
            data = response.read(self._maximum_response_bytes + 1)
            if len(data) > self._maximum_response_bytes:
                raise RunnerError("HTTP_RESPONSE_TOO_LARGE")
            response_headers: dict[str, str] = {}
            observed_header_names: set[str] = set()
            for key, value in response.getheaders():
                normalized_key = key.casefold()
                if normalized_key in observed_header_names:
                    raise RunnerError("HTTP_RESPONSE_INVALID")
                observed_header_names.add(normalized_key)
                response_headers[key] = value
            return HttpResponse(
                status=response.status,
                headers=response_headers,
                body=data,
            )
        except RunnerError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as error:
            raise RunnerError("HTTP_REQUEST_FAILED") from error
        finally:
            if response is not None:
                response.close()
            connection.close()


@dataclass(frozen=True, slots=True)
class _ManifestAudio:
    asset_id: UUID
    path: str
    sha256: str
    etag: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class _ManifestSnapshot:
    edition_id: UUID
    revision: int
    etag: str
    status: Literal["partial_ready", "ready"]
    source_sha256: str
    payload_sha256: str
    segment_ids: tuple[UUID, ...]
    audio: tuple[_ManifestAudio, ...]
    audio_by_ordinal: tuple[_ManifestAudio | None, ...]
    render_statuses: tuple[str, ...]
    nonretryable_failure_codes: tuple[str, ...] = ()

    @property
    def duration_seconds(self) -> float:
        return sum(item.duration_ms for item in self.audio) / 1000.0


@dataclass(frozen=True, slots=True)
class _ChainState:
    outcome: ChainOutcome
    manifest: _ManifestSnapshot
    request_to_ready_seconds: float
    observed_http_first_audio_ms: int


def _validated_api_base(value: str):  # type: ignore[no-untyped-def]
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise RunnerError("API_BASE_NOT_LOOPBACK") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != API_PATH
        or port is None
        or not 1 <= port <= 65535
    ):
        raise RunnerError("API_BASE_NOT_LOOPBACK")
    return parsed


def _validate_method_path(method: str, path: str) -> str:
    normalized = method.upper()
    if normalized not in _ALLOWED_PATHS or method != normalized:
        raise RunnerError("HTTP_PATH_NOT_ALLOWED")
    try:
        parsed = urlsplit(path)
    except ValueError as error:
        raise RunnerError("HTTP_PATH_NOT_ALLOWED") from error
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.path != path
        or "\\" in path
        or "//" in path
        or "/../" in f"{path}/"
        or not any(pattern.fullmatch(path) for pattern in _ALLOWED_PATHS[normalized])
    ):
        raise RunnerError("HTTP_PATH_NOT_ALLOWED")
    return normalized


def _validated_headers(headers: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    forbidden = {"host", "content-length", "transfer-encoding", "connection"}
    for key, value in headers.items():
        if (
            type(key) is not str
            or type(value) is not str
            or not key
            or key.casefold() in forbidden
            or any(character in key + value for character in "\r\n")
        ):
            raise RunnerError("HTTP_REQUEST_INVALID")
        result[key] = value
    return result


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _uuid(value: object, code: str = "HTTP_RESPONSE_INVALID") -> UUID:
    if type(value) is not str:
        raise RunnerError(code)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise RunnerError(code) from error
    if parsed.variant != "specified in RFC 4122" or parsed.version not in {1, 2, 3, 4, 5}:
        raise RunnerError(code)
    return parsed


def _positive_int(value: object, code: str = "HTTP_RESPONSE_INVALID") -> int:
    if type(value) is not int or value < 1:
        raise RunnerError(code)
    return value


def _nonnegative_int(value: object, code: str = "HTTP_RESPONSE_INVALID") -> int:
    if type(value) is not int or value < 0:
        raise RunnerError(code)
    return value


def _sha256(value: object, code: str = "HTTP_RESPONSE_INVALID") -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RunnerError(code)
    return value


def _object(value: object, code: str = "HTTP_RESPONSE_INVALID") -> dict[str, object]:
    if type(value) is not dict:
        raise RunnerError(code)
    return value


def _list(value: object, code: str = "HTTP_RESPONSE_INVALID") -> list[object]:
    if type(value) is not list:
        raise RunnerError(code)
    return value


def _recovery_fence_from_resources(
    document: Mapping[str, object],
    context: Mapping[str, object],
    config: RunnerConfig,
    *,
    code: str = "RECOVERY_FENCE_INVALID",
) -> RecoveryFence:
    draft_version = _positive_int(document.get("draft_version"), code)
    content_hash = _sha256(document.get("content_hash"), code)
    pointer_version = _positive_int(context.get("pointer_version"), code)
    current_edition = _uuid(context.get("current_edition_id"), code)
    current_script = _uuid(context.get("current_script_version_id"), code)
    if (
        _uuid(document.get("id"), code) != config.document_id
        or _uuid(document.get("novel_id"), code) != config.novel_id
        or _uuid(context.get("document_id"), code) != config.document_id
        or _uuid(context.get("novel_id"), code) != config.novel_id
        or context.get("working_copy_draft_version") != draft_version
        or context.get("working_copy_content_hash") != content_hash
    ):
        raise RunnerError(code)
    return RecoveryFence(
        draft_version=draft_version,
        content_hash=content_hash,
        current_edition_id=current_edition,
        current_script_version_id=current_script,
        pointer_version=pointer_version,
    )


def _assert_recovery_fence(
    document: Mapping[str, object],
    context: Mapping[str, object],
    config: RunnerConfig,
    fence: RecoveryFence,
) -> None:
    observed = _recovery_fence_from_resources(
        document,
        context,
        config,
        code="RECOVERY_CONFLICT",
    )
    if observed != fence:
        raise RunnerError("RECOVERY_CONFLICT")


def _http_diagnostic_labels(method: str, path: str) -> tuple[str, str]:
    """Return fixed redacted stage/path labels; never echo a dynamic URL."""

    parts = path.strip("/").split("/")
    if method == "GET" and path == "/health":
        return "HEALTH_GET", "HEALTH"
    if len(parts) == 2 and parts[0] == "documents":
        return "DOCUMENT_GET", "DOCUMENT"
    if len(parts) == 3 and parts[0] == "documents":
        if parts[2] == "draft":
            return "DRAFT_PATCH", "DOCUMENT_DRAFT"
        if parts[2] == "narration-playback-context":
            return "CONTEXT_GET", "PLAYBACK_CONTEXT"
        if parts[2] == "narration-requests":
            return "WORKFLOW_CREATE", "NARRATION_REQUESTS"
        if parts[2] == "current-narration-edition":
            return "EDITION_SWITCH", "CURRENT_EDITION"
    if len(parts) == 3 and parts[0] == "novels":
        labels = {
            "narration-settings": ("SETTINGS_GET", "NARRATION_SETTINGS"),
            "narration-overview": ("OVERVIEW_GET", "NARRATION_OVERVIEW"),
            "characters": ("CHARACTERS_GET", "NOVEL_CHARACTERS"),
        }
        if parts[2] in labels:
            return labels[parts[2]]
    if len(parts) == 2 and parts[0] == "narration-requests":
        return "WORKFLOW_GET", "NARRATION_REQUEST"
    if len(parts) == 2 and parts[0] == "narration-editions":
        return "EDITION_GET", "NARRATION_EDITION"
    if len(parts) == 2 and parts[0] == "narration-script-versions":
        return "SCRIPT_GET", "NARRATION_SCRIPT"
    if len(parts) == 3 and parts[0] == "narration-editions":
        if parts[2] == "manifest":
            return "MANIFEST_GET", "EDITION_MANIFEST"
        if parts[2] == "prepare-range":
            return "RANGE_PREPARE", "EDITION_PREPARE_RANGE"
    if len(parts) == 3 and parts[0] == "narration-script-versions":
        if parts[2] == "approve":
            return "APPROVE", "SCRIPT_APPROVE"
    if (
        len(parts) == 4
        and parts[0] == "narration-script-versions"
        and parts[2] == "segments"
    ):
        return "SEGMENT_PATCH", "SCRIPT_SEGMENT"
    if len(parts) == 3 and parts[0] == "media-assets" and parts[2] == "content":
        return "MEDIA_READ", "MEDIA_CONTENT"
    if (
        len(parts) in {5, 6}
        and parts[0] == "novels"
        and parts[2] == "documents"
        and parts[4] == "narration-validation-segment-claim-gate"
    ):
        if len(parts) == 6 and parts[5] == "release":
            return "CLAIM_RELEASE", "CLAIM_GATE_RELEASE"
        return "CLAIM_GATE", "CLAIM_GATE"
    return "ALLOWED_REQUEST", "ALLOWED_PATH"


def _status_label(value: object) -> str:
    if type(value) is int and 100 <= value <= 599:
        return str(value)
    return "INVALID"


def _manifest_nonretryable_error_code(public_code: str) -> str:
    if public_code in _MANIFEST_FAILURE_CODE_ALLOWLIST:
        suffix = public_code
    else:
        suffix = f"UNKNOWN_{hashlib.sha256(public_code.encode('ascii')).hexdigest()[:12].upper()}"
    return f"MANIFEST_NONRETRYABLE_FAILURE_{suffix}"


def _response_json(
    response: HttpResponse,
    expected_status: int,
    *,
    method: str | None = None,
    path: str | None = None,
) -> object:
    if type(response) is not HttpResponse:
        raise RunnerError("HTTP_STATUS_UNEXPECTED")
    if response.status != expected_status:
        if method is not None and path is not None:
            safe_method = method if method in _ALLOWED_PATHS else "INVALID"
            stage, path_template = _http_diagnostic_labels(safe_method, path)
            raise RunnerError(
                "HTTP_STATUS_UNEXPECTED"
                f"_S_{stage}_M_{safe_method}_P_{path_template}"
                f"_E{_status_label(expected_status)}_A{_status_label(response.status)}"
            )
        raise RunnerError("HTTP_STATUS_UNEXPECTED")
    content_type = response.header("Content-Type")
    if content_type is not None and content_type.split(";", 1)[0].strip() not in {
        "application/json",
        "application/problem+json",
    }:
        raise RunnerError("HTTP_RESPONSE_INVALID")
    try:
        return json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError("HTTP_RESPONSE_INVALID") from error


def _wrong_validation_token(validation_token: str) -> str:
    if (
        type(validation_token) is not str
        or _VALIDATION_TOKEN_RE.fullmatch(validation_token) is None
    ):
        raise RunnerError("VALIDATION_TOKEN_INVALID")
    replacement = "A" if validation_token[0] != "A" else "B"
    return f"{replacement}{validation_token[1:]}"


def _assert_hidden_t4_route(response: HttpResponse) -> None:
    code = "T4_HIDDEN_ROUTE_GATE_FAILED"
    try:
        if (
            type(response) is not HttpResponse
            or response.status != 404
            or response.header("Cache-Control") != "no-store"
        ):
            raise RunnerError(code)
        payload = _object(_response_json(response, 404), code)
        detail = _object(payload.get("detail"), code)
        if detail != {
            "code": "RESOURCE_NOT_FOUND",
            "message": "找不到请求的朗读资源。",
        }:
            raise RunnerError(code)
    except RunnerError as error:
        if error.code == code:
            raise
        raise RunnerError(code) from error


def _assert_overview_capability_tier(
    response: HttpResponse,
    *,
    novel_id: UUID,
    expected_enabled: frozenset[str],
    code: str,
) -> None:
    try:
        payload = _object(_response_json(response, 200), code)
        capabilities = _object(payload.get("capabilities"), code)
        runtime = _object(payload.get("runtime"), code)
        if (
            payload.get("contract_version") != "narration-settings-api/1"
            or payload.get("novel_id") != str(novel_id)
            or capabilities.get("schema_version") != "narration-capabilities/1"
            or runtime.get("product_visible") is not False
        ):
            raise RunnerError(code)
        items = _list(capabilities.get("items"), code)
        observed: dict[str, str] = {}
        for raw_item in items:
            item = _object(raw_item, code)
            key = item.get("key")
            state = item.get("state")
            visible = item.get("visible")
            actionable = item.get("actionable")
            reason_code = item.get("reason_code")
            required_gate = item.get("required_gate")
            if (
                type(key) is not str
                or key not in _ALL_CAPABILITIES
                or key in observed
                or type(state) is not str
                or state not in {"enabled", "disabled", "unavailable", "hold"}
                or type(visible) is not bool
                or type(actionable) is not bool
                or (
                    state == "enabled"
                    and (
                        visible is not True
                        or actionable is not True
                        or reason_code is not None
                        or required_gate is not None
                    )
                )
                or (
                    state != "enabled"
                    and (
                        actionable is not False
                        or type(reason_code) is not str
                        or (
                            required_gate is not None
                            and type(required_gate) is not str
                        )
                    )
                )
            ):
                raise RunnerError(code)
            observed[key] = state
        enabled = frozenset(
            key for key, state in observed.items() if state == "enabled"
        )
        if set(observed) != _ALL_CAPABILITIES or enabled != expected_enabled:
            raise RunnerError(code)
    except RunnerError as error:
        if error.code == code:
            raise
        raise RunnerError(code) from error


def verify_t4k_hidden_release_gate(
    config: RunnerConfig,
    *,
    validation_token: str,
    timeout_seconds: float = 30.0,
) -> None:
    """Prove the private T4 validation surface is hidden before a real run.

    All probes are read-only.  The cross-namespace resource identity is safe
    only because the exact gate-owned 404 body is checked in addition to status
    and ``Cache-Control``; an ordinary backend not-found cannot pass.
    """

    wrong_token = _wrong_validation_token(validation_token)
    negative_transports = (
        LoopbackHttpTransport(config.api_base),
        LoopbackHttpTransport(
            config.api_base,
            validation_token=wrong_token,
        ),
        LoopbackHttpTransport(
            config.api_base,
            explicit_validation_tokens=(validation_token, validation_token),
        ),
    )
    representative_id = config.document_id
    hidden_paths = (
        f"/narration-requests/{representative_id}",
        f"/narration-script-versions/{representative_id}",
        f"/narration-editions/{representative_id}/manifest",
    )
    overview_path = f"/novels/{config.novel_id}/narration-overview"
    for transport in negative_transports:
        for path in hidden_paths:
            _assert_hidden_t4_route(
                transport.request(
                    method="GET",
                    path=path,
                    timeout_seconds=timeout_seconds,
                )
            )
        _assert_overview_capability_tier(
            transport.request(
                method="GET",
                path=overview_path,
                timeout_seconds=timeout_seconds,
            ),
            novel_id=config.novel_id,
            expected_enabled=_T2_ENABLED_CAPABILITIES,
            code="T4_HIDDEN_OVERVIEW_T2_FAILED",
        )

    validation_transport = LoopbackHttpTransport(
        config.api_base,
        validation_token=validation_token,
    )
    _assert_overview_capability_tier(
        validation_transport.request(
            method="GET",
            path=overview_path,
            timeout_seconds=timeout_seconds,
        ),
        novel_id=config.novel_id,
        expected_enabled=_T4_ENABLED_CAPABILITIES,
        code="T4_VALIDATION_OVERVIEW_T4_FAILED",
    )


class RealChapterE2EExecutor:
    """Stateful implementation of the frozen ``ChapterE2EExecutor`` protocol."""

    def __init__(
        self,
        config: RunnerConfig,
        *,
        transport: HttpTransport | None,
        browser_probe: BrowserProbe | None,
        runtime_audit_probe: RuntimeAuditProbe | None,
        partial_ready_coordinator: PartialReadyValidationCoordinator | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        request_timeout_seconds: float = 30.0,
        workflow_timeout_seconds: float = 1800.0,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        _validated_api_base(config.api_base)
        if transport is None:
            raise RunnerError("REAL_HTTP_TRANSPORT_REQUIRED")
        if browser_probe is None:
            raise RunnerError("REAL_BROWSER_PROBE_REQUIRED")
        if runtime_audit_probe is None:
            raise RunnerError("REAL_RUNTIME_AUDIT_PROBE_REQUIRED")
        if not callable(getattr(transport, "request", None)):
            raise RunnerError("REAL_HTTP_TRANSPORT_REQUIRED")
        if any(
            not callable(getattr(browser_probe, method, None))
            for method in (
                "begin_chain",
                "observe_manifest",
                "complete_chain",
                "collect",
            )
        ):
            raise RunnerError("REAL_BROWSER_PROBE_REQUIRED")
        if any(
            not callable(getattr(runtime_audit_probe, method, None))
            for method in ("preflight", "audit_chain", "collect_technical")
        ):
            raise RunnerError("REAL_RUNTIME_AUDIT_PROBE_REQUIRED")
        if partial_ready_coordinator is not None and any(
            not callable(getattr(partial_ready_coordinator, method, None))
            for method in ("arm", "read", "release", "record")
        ):
            raise RunnerError("PARTIAL_READY_COORDINATOR_INVALID")
        if config.mode != "real":
            raise RunnerError("REAL_EXECUTOR_MODE_INVALID")
        if (
            type(request_timeout_seconds) not in {int, float}
            or not math.isfinite(float(request_timeout_seconds))
            or not 0 < float(request_timeout_seconds) <= 120
            or type(workflow_timeout_seconds) not in {int, float}
            or not math.isfinite(float(workflow_timeout_seconds))
            or not 1 <= float(workflow_timeout_seconds) <= 3600
            or type(poll_interval_seconds) not in {int, float}
            or not math.isfinite(float(poll_interval_seconds))
            or not 0 < float(poll_interval_seconds) <= 5
        ):
            raise RunnerError("REAL_EXECUTOR_LIMIT_INVALID")
        self._config = config
        self._transport = transport
        self._browser_probe = browser_probe
        self._runtime_audit_probe = runtime_audit_probe
        self._partial_ready_coordinator = partial_ready_coordinator
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._request_timeout_seconds = float(request_timeout_seconds)
        self._workflow_timeout_seconds = float(workflow_timeout_seconds)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._baseline: BaselineSnapshot | None = None
        self._automatic: _ChainState | None = None
        self._manual: _ChainState | None = None
        self._expected_model_fingerprint: str | None = None
        self._owned_fence: RecoveryFence | None = None
        self._pending_write_intent: RecoveryWriteIntent | None = None
        self._recovery_checkpoint: (
            Callable[[RecoveryFence, RecoveryWriteIntent | None], None] | None
        ) = None

    def capture_baseline(self, config: RunnerConfig) -> BaselineSnapshot:
        self._require_config(config)
        if self._baseline is not None:
            raise RunnerError("BASELINE_ALREADY_CAPTURED")
        self._validate_health()
        preflight = self._runtime_audit_probe.preflight(config)
        if (
            type(preflight) is not RuntimePreflightEvidence
            or preflight.production_ready is not True
            or preflight.sidecar_ready is not True
            # T4-K is deliberately pre-release: the hidden validation runtime
            # must be ready while public product capabilities remain closed.
            or preflight.product_visible is not False
            or _SHA256_RE.fullmatch(preflight.model_fingerprint) is None
        ):
            raise RunnerError("RUNTIME_PREFLIGHT_FAILED")
        self._expected_model_fingerprint = preflight.model_fingerprint
        document = self._read_document()
        context = self._read_context()
        self._read_settings_version()
        history = _object(context.get("edition_history"))
        editions = _list(history.get("editions"))
        current_edition = _uuid(context.get("current_edition_id"), "BASELINE_INVALID")
        current_script = _uuid(
            context.get("current_script_version_id"), "BASELINE_INVALID"
        )
        if (
            _uuid(document.get("id"), "BASELINE_INVALID") != config.document_id
            or _uuid(document.get("novel_id"), "BASELINE_INVALID") != config.novel_id
            or _uuid(context.get("document_id"), "BASELINE_INVALID")
            != config.document_id
            or _uuid(context.get("novel_id"), "BASELINE_INVALID") != config.novel_id
            or context.get("working_copy_content_hash") != document.get("content_hash")
            or context.get("working_copy_draft_version") != document.get("draft_version")
            or _uuid(history.get("current_edition_id"), "BASELINE_INVALID")
            != current_edition
            or history.get("pointer_version") != context.get("pointer_version")
            or len(editions) < 1
            or sum(
                1
                for item in editions
                if type(item) is dict and item.get("edition_id") == str(current_edition)
            )
            != 1
        ):
            raise RunnerError("BASELINE_INVALID")
        content = document.get("content_markdown")
        content_hash = document.get("content_hash")
        if (
            type(content) is not str
            or _sha256(content_hash, "BASELINE_INVALID") != _sha256_text(content)
        ):
            raise RunnerError("BASELINE_INVALID")
        base_revision_raw = document.get("base_revision_id")
        base_revision = (
            _uuid(base_revision_raw, "BASELINE_INVALID")
            if base_revision_raw is not None
            else None
        )
        baseline = BaselineSnapshot(
            draft_version=_positive_int(document.get("draft_version"), "BASELINE_INVALID"),
            content_hash=content_hash,
            content_markdown=content,
            base_revision_id=base_revision,
            pointer_version=_positive_int(
                context.get("pointer_version"), "BASELINE_INVALID"
            ),
            current_edition_id=current_edition,
            current_script_version_id=current_script,
            edition_history_count=len(editions),
        )
        self._baseline = baseline
        self._owned_fence = RecoveryFence(
            draft_version=baseline.draft_version,
            content_hash=baseline.content_hash,
            current_edition_id=baseline.current_edition_id,
            current_script_version_id=baseline.current_script_version_id,
            pointer_version=baseline.pointer_version,
        )
        return baseline

    def set_recovery_checkpoint(
        self,
        checkpoint: Callable[
            [RecoveryFence, RecoveryWriteIntent | None],
            None,
        ],
    ) -> None:
        if self._recovery_checkpoint is not None or not callable(checkpoint):
            raise RunnerError("RECOVERY_CHECKPOINT_INVALID")
        self._recovery_checkpoint = checkpoint

    def run_automatic(
        self,
        config: RunnerConfig,
        case: ChapterCase,
    ) -> ChainOutcome:
        self._require_config(config)
        self._require_baseline()
        if self._automatic is not None or case.mode != "automatic_zero_blockers":
            raise RunnerError("AUTOMATIC_CHAIN_STATE_INVALID")
        self._save_case(case)
        started = self._monotonic()
        self._browser_probe.begin_chain(config, "automatic")
        workflow = self._start_workflow(case, "automatic")
        if _nonnegative_int(workflow.get("blocker_count")) != 0:
            raise RunnerError("AUTOMATIC_BLOCKER_UNEXPECTED")
        script_id = _uuid(workflow.get("script_version_id"))
        script = self._read_script(script_id)
        self._validate_script_scope(script, case, script_id)
        if self._script_approval_kind(script) != "auto_no_blockers":
            raise RunnerError("AUTOMATIC_APPROVAL_INVALID")
        ready, elapsed, first_audio = self._poll_ready(
            workflow,
            chain_label="automatic",
            started_at=started,
            allow_review_required=False,
        )
        state = self._complete_chain(
            chain_label="automatic",
            case=case,
            workflow=ready,
            expected_approval="auto_no_blockers",
            initial_blocker_count=0,
            request_to_ready_seconds=elapsed,
            first_audio_ms=first_audio,
        )
        self._automatic = state
        return state.outcome

    def run_manual(
        self,
        config: RunnerConfig,
        case: ChapterCase,
    ) -> ChainOutcome:
        self._require_config(config)
        self._require_baseline()
        if (
            self._automatic is None
            or self._manual is not None
            or case.mode != "manual_blocker_resolution"
        ):
            raise RunnerError("MANUAL_CHAIN_STATE_INVALID")
        self._save_case(case)
        started = self._monotonic()
        self._browser_probe.begin_chain(config, "manual")
        workflow = self._start_workflow(case, "manual")
        if workflow.get("workflow_state") != "review_required":
            raise RunnerError("MANUAL_REVIEW_NOT_REQUIRED")
        request_id = _uuid(workflow.get("request_id"))
        version_id = _uuid(workflow.get("script_version_id"))
        script = self._read_script(version_id)
        self._validate_script_scope(script, case, version_id)
        initial_blockers = _positive_int(
            script.get("blocker_count"), "MANUAL_BLOCKERS_INVALID"
        )
        blocker_codes = sorted(
            {
                issue.get("code")
                for raw in _list(script.get("issues"))
                if (issue := _object(raw)).get("severity") == "blocker"
                and type(issue.get("code")) is str
            }
        )
        if tuple(blocker_codes) != case.expected_initial_blocker_codes:
            raise RunnerError("MANUAL_BLOCKER_SET_MISMATCH")
        for index, correction in enumerate(case.corrections):
            workflow = self._read_workflow(request_id)
            if workflow.get("workflow_state") != "review_required":
                raise RunnerError("MANUAL_REVIEW_STATE_CHANGED")
            current_id = _uuid(workflow.get("script_version_id"))
            if current_id != _uuid(script.get("script_version_id")):
                script = self._read_script(current_id)
                self._validate_script_scope(script, case, current_id)
            segment = self._locate_correction_segment(script, correction)
            target_id = self._resolve_correction_target(correction.speaker_kind, correction.speaker_label)
            body = {
                "expected_request_version": _positive_int(
                    workflow.get("request_version")
                ),
                "expected_version_number": _positive_int(script.get("version_number")),
                "expected_immutable_hash": _sha256(script.get("immutable_hash")),
                "expected_local_hash": _sha256(segment.get("local_hash")),
                "request_id": str(request_id),
                "speaker_kind": correction.speaker_kind,
                "speaker_label": correction.speaker_label,
                "character_id": str(target_id) if correction.speaker_kind == "character" else None,
                "anonymous_speaker_id": None,
                "group_key": None,
                "spoken_text": correction.spoken_text,
                "reason": correction.reason,
            }
            old_version = _positive_int(script.get("version_number"))
            old_version_id = _uuid(script.get("script_version_id"))
            updated = self._json_request(
                "PATCH",
                f"/narration-script-versions/{old_version_id}/segments/{_uuid(segment.get('segment_id'))}",
                expected_status=201,
                headers={"Idempotency-Key": self._idempotency(f"manual-patch-{index}")},
                body=body,
            )
            script = _object(updated)
            new_version_id = _uuid(script.get("script_version_id"))
            if (
                new_version_id == old_version_id
                or _positive_int(script.get("version_number")) != old_version + 1
            ):
                raise RunnerError("MANUAL_PATCH_VERSION_INVALID")
            self._validate_script_scope(script, case, new_version_id)
            corrected = self._locate_correction_segment(script, correction)
            if (
                corrected.get("speaker_kind") != correction.speaker_kind
                or corrected.get("speaker_label") != correction.speaker_label
                or corrected.get("spoken_text") != correction.spoken_text
                or (
                    correction.speaker_kind == "character"
                    and _uuid(corrected.get("character_id")) != target_id
                )
            ):
                raise RunnerError("MANUAL_PATCH_NOT_APPLIED")
        if _nonnegative_int(script.get("blocker_count")) != 0:
            raise RunnerError("MANUAL_BLOCKERS_REMAIN")
        workflow = self._read_workflow(request_id)
        current_version_id = _uuid(workflow.get("script_version_id"))
        if current_version_id != _uuid(script.get("script_version_id")):
            script = self._read_script(current_version_id)
            self._validate_script_scope(script, case, current_version_id)
        approved_raw = self._json_request(
            "POST",
            f"/narration-script-versions/{current_version_id}/approve",
            expected_status=200,
            headers={"Idempotency-Key": self._idempotency("manual-approve")},
            body={
                "request_id": str(request_id),
                "expected_request_version": _positive_int(
                    workflow.get("request_version")
                ),
                "expected_version_number": _positive_int(script.get("version_number")),
                "expected_immutable_hash": _sha256(script.get("immutable_hash")),
                "source_revision_id": str(_uuid(script.get("revision_id"))),
                "confirmed": True,
            },
        )
        approved = _object(approved_raw)
        self._validate_script_scope(approved, case, current_version_id)
        if self._script_approval_kind(approved) != "manual_after_review":
            raise RunnerError("MANUAL_APPROVAL_INVALID")
        ready, elapsed, first_audio = self._poll_ready(
            self._read_workflow(request_id),
            chain_label="manual",
            started_at=started,
            allow_review_required=False,
        )
        state = self._complete_chain(
            chain_label="manual",
            case=case,
            workflow=ready,
            expected_approval="manual_after_review",
            initial_blocker_count=initial_blockers,
            request_to_ready_seconds=elapsed,
            first_audio_ms=first_audio,
        )
        self._manual = state
        return state.outcome

    def run_technical_checks(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
    ) -> TechnicalOutcome:
        self._require_config(config)
        if self._automatic is None or self._manual is None:
            raise RunnerError("TECHNICAL_CHAIN_STATE_INVALID")
        range_codes: set[int] = set()
        output_hashes: set[str] = set()
        for label, chain in (("automatic", self._automatic), ("manual", self._manual)):
            statuses, hashes = self._exercise_manifest(label, chain.manifest)
            range_codes.update(statuses)
            output_hashes.update(hashes)
        chains = (self._automatic, self._manual)
        slowest = max(chains, key=lambda item: item.request_to_ready_seconds)
        context = TechnicalProbeContext(
            automatic_request_id=self._automatic.outcome.request_id,
            automatic_edition_id=self._automatic.outcome.edition_id,
            automatic_edition_fingerprint=(
                self._automatic.outcome.edition_fingerprint
            ),
            automatic_manifest_revision=self._automatic.outcome.manifest_revision,
            manual_request_id=self._manual.outcome.request_id,
            manual_edition_id=self._manual.outcome.edition_id,
            manual_edition_fingerprint=(
                self._manual.outcome.edition_fingerprint
            ),
            manual_manifest_revision=self._manual.outcome.manifest_revision,
            request_to_ready_seconds=tuple(
                item.request_to_ready_seconds for item in chains
            ),
            observed_http_first_audio_ms=tuple(
                item.observed_http_first_audio_ms for item in chains
            ),
            chapter_audio_duration_seconds=slowest.manifest.duration_seconds,
            range_status_codes=tuple(sorted(range_codes)),
            listening_output_hashes=tuple(sorted(output_hashes)),
        )
        if self._partial_ready_coordinator is None:
            browser = self._browser_probe.collect(config, fixture, context)
        else:
            browser = self._collect_browser_with_partial_ready(
                config,
                fixture,
                context,
            )
        runtime = self._runtime_audit_probe.collect_technical(config, fixture, context)
        self._validate_browser_evidence(browser)
        self._validate_runtime_evidence(runtime)
        return TechnicalOutcome(
            stability_elapsed_seconds=runtime.stability_elapsed_seconds,
            chapter_audio_duration_seconds=context.chapter_audio_duration_seconds,
            request_to_ready_seconds=slowest.request_to_ready_seconds,
            time_to_first_audio_ms=browser.time_to_first_audio_ms,
            peak_memory_bytes=runtime.peak_memory_bytes,
            pageout_delta=runtime.pageout_delta,
            swapout_delta=runtime.swapout_delta,
            memory_baseline_median_bytes=(
                runtime.memory_baseline_median_bytes
            ),
            memory_tail_median_bytes=runtime.memory_tail_median_bytes,
            memory_growth_bytes=runtime.memory_growth_bytes,
            memory_growth_limit_bytes=runtime.memory_growth_limit_bytes,
            sidecar_memory_growth_observed=(
                runtime.sidecar_memory_growth_observed
            ),
            range_status_codes=context.range_status_codes,
            seam_pairs_checked=runtime.seam_pairs_checked,
            seek_latest_wins=browser.seek_latest_wins,
            pending_gap_not_skipped=browser.pending_gap_not_skipped,
            edit_actions_created_tts_writes=browser.edit_actions_created_tts_writes,
            browser_viewports=browser.browser_viewports,
            browser_assistant_modes=browser.browser_assistant_modes,
            browser_console_error_count=browser.browser_console_error_count,
            browser_overlap_count=browser.browser_overlap_count,
            sidecar_restart_count=runtime.sidecar_restart_count,
            health_failure_count=runtime.health_failure_count,
            host_paging_observed=runtime.host_paging_observed,
            qwenpaw_slowdown_observed=runtime.qwenpaw_slowdown_observed,
            listening_output_hashes=context.listening_output_hashes,
            collector_collected_at=browser.collector_collected_at,
            evidence_class=browser.evidence_class,
            evidence_root_sha256=browser.evidence_root_sha256,
        )

    @staticmethod
    def _fence_sha256(fence: RecoveryFence) -> str:
        return _sha256_text(
            json.dumps(
                {
                    "draft_version": fence.draft_version,
                    "content_hash": fence.content_hash,
                    "current_edition_id": str(fence.current_edition_id),
                    "current_script_version_id": str(
                        fence.current_script_version_id
                    ),
                    "pointer_version": fence.pointer_version,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _partial_ready_source(case: ChapterCase, run_id: UUID) -> tuple[str, str]:
        alphabet = "零一二三四五六七八九甲乙丙丁戊己"
        run_code = "".join(alphabet[int(value, 16)] for value in run_id.hex)
        suffix = (
            f"本地朗读验收甲号{run_code}用于确认缓存边界前的声音保持稳定。\n\n"
            f"本地朗读验收乙号{run_code[::-1]}用于确认缺口之后的句段不得越过等待。"
        )
        source = f"{case.source_text.rstrip()}\n\n{suffix}"
        return source, _sha256_text(source)

    def _collect_browser_with_partial_ready(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
        context: TechnicalProbeContext,
    ) -> BrowserTechnicalEvidence:
        coordinator = self._partial_ready_coordinator
        automatic = self._automatic
        if coordinator is None or automatic is None or self._manual is None:
            raise RunnerError("PARTIAL_READY_COORDINATOR_INVALID")
        return_document = self._read_document()
        return_fence = self._require_owned_fence()
        return_content = return_document.get("content_markdown")
        if (
            type(return_content) is not str
            or return_document.get("content_hash") != return_fence.content_hash
            or _sha256_text(return_content) != return_fence.content_hash
        ):
            raise RunnerError("PARTIAL_READY_RETURN_FENCE_INVALID")
        return_fence_sha256 = self._fence_sha256(return_fence)
        partial_source, partial_source_sha256 = self._partial_ready_source(
            fixture.automatic,
            config.run_id,
        )
        evidence = PartialReadyValidationEvidence(
            source_content_sha256=partial_source_sha256,
            return_fence_sha256=return_fence_sha256,
        )
        request_id: UUID | None = None
        edition_id: UUID | None = None
        script_id: UUID | None = None
        browser: BrowserTechnicalEvidence | None = None
        primary_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        gate_was_armed = False
        coordinator.record(config, state="staging", evidence=evidence)
        try:
            self._save_text(partial_source, partial_source_sha256)
            gate = coordinator.arm(config)
            self._validate_gate_evidence(gate, expected_state="armed")
            gate_was_armed = True
            evidence = replace(
                evidence,
                gate_claimed_count=gate.claimed_count,
                gate_run_fingerprint_sha256=gate.run_fingerprint_sha256,
                gate_scope_fingerprint_sha256=gate.scope_fingerprint_sha256,
            )
            coordinator.record(config, state="gate_armed", evidence=evidence)
            partial_case = replace(
                fixture.automatic,
                source_text=partial_source,
                source_sha256=partial_source_sha256,
            )
            workflow = self._start_workflow(partial_case, "partial-ready")
            if (
                _nonnegative_int(workflow.get("blocker_count")) != 0
                or workflow.get("workflow_state") == "review_required"
            ):
                raise RunnerError("PARTIAL_READY_REVIEW_UNEXPECTED")
            request_id = _uuid(workflow.get("request_id"))
            script_id = _uuid(workflow.get("script_version_id"))
            edition_id = _uuid(workflow.get("edition_id"))
            partial_script = self._read_script(script_id)
            self._validate_script_scope(
                partial_script,
                partial_case,
                script_id,
            )
            if (
                partial_script.get("state") != "approved"
                or _nonnegative_int(partial_script.get("blocker_count")) != 0
                or self._script_approval_kind(partial_script)
                != "auto_no_blockers"
            ):
                raise RunnerError("PARTIAL_READY_SCRIPT_INVALID")
            miss_jobs = tuple(
                _uuid(item) for item in _list(workflow.get("job_ids"))
            )
            if len(miss_jobs) < 2 or len(miss_jobs) != len(set(miss_jobs)):
                raise RunnerError("PARTIAL_READY_CACHE_MISS_INVALID")
            partial_manifest, gate = self._poll_partial_ready(
                workflow,
                source_sha256=partial_source_sha256,
                prior_ready=automatic.manifest,
                coordinator=coordinator,
            )
            self._validate_gate_evidence(gate, expected_state="paused")
            cache_hits, cache_hit_duration_ms = self._matching_ready_prefix(
                prior=automatic.manifest,
                current=partial_manifest,
            )
            ready_prefix = self._ready_prefix_count(partial_manifest)
            ready_prefix_duration_ms = sum(
                item.duration_ms
                for item in partial_manifest.audio_by_ordinal[:ready_prefix]
                if item is not None
            )
            if (
                cache_hits < 3
                or cache_hit_duration_ms < 8_000
                or ready_prefix < 3
                or ready_prefix_duration_ms < 8_000
            ):
                raise RunnerError("PARTIAL_READY_CACHE_PREFIX_INVALID")
            self._switch_edition(edition_id, script_id)
            evidence = replace(
                evidence,
                request_id=request_id,
                script_version_id=script_id,
                edition_id=edition_id,
                manifest_revision=partial_manifest.revision,
                manifest_etag_sha256=_sha256_text(partial_manifest.etag),
                manifest_payload_sha256=partial_manifest.payload_sha256,
                ready_prefix_count=ready_prefix,
                ready_prefix_duration_ms=ready_prefix_duration_ms,
                cache_hit_prefix_count=cache_hits,
                cache_miss_job_count=len(miss_jobs),
                gate_claimed_count=gate.claimed_count,
                gate_run_fingerprint_sha256=gate.run_fingerprint_sha256,
                gate_scope_fingerprint_sha256=gate.scope_fingerprint_sha256,
            )
            coordinator.record(config, state="partial_ready", evidence=evidence)
            browser = self._browser_probe.collect(config, fixture, context)
            if browser.pending_gap_not_skipped is not True:
                raise RunnerError("BROWSER_PENDING_GAP_EVIDENCE_INVALID")
            coordinator.record(config, state="browser_observed", evidence=evidence)
        except BaseException as error:
            primary_error = error
        finally:
            released_successfully = False
            for _attempt in range(2):
                try:
                    released = coordinator.release(config)
                    self._validate_gate_evidence(
                        released,
                        expected_state="default_allow",
                    )
                    gate_was_armed = False
                    released_successfully = True
                    coordinator.record(
                        config,
                        state="gate_released",
                        evidence=evidence,
                    )
                    break
                except BaseException as error:
                    cleanup_error = cleanup_error or error
            if (
                released_successfully
                and request_id is not None
                and edition_id is not None
            ):
                try:
                    self._wait_partial_completion(
                        request_id=request_id,
                        edition_id=edition_id,
                        source_sha256=partial_source_sha256,
                    )
                except BaseException as error:
                    cleanup_error = cleanup_error or error
            try:
                owned = self._require_owned_fence()
                if owned.content_hash != return_fence.content_hash:
                    self._save_text(return_content, return_fence.content_hash)
                owned = self._require_owned_fence()
                if owned.current_edition_id != return_fence.current_edition_id:
                    self._switch_edition(
                        return_fence.current_edition_id,
                        return_fence.current_script_version_id,
                    )
                restored = self._require_owned_fence()
                if (
                    restored.content_hash != return_fence.content_hash
                    or restored.current_edition_id != return_fence.current_edition_id
                    or restored.current_script_version_id
                    != return_fence.current_script_version_id
                ):
                    raise RunnerError("PARTIAL_READY_RESTORE_FAILED")
                evidence = replace(
                    evidence,
                    restored_fence_sha256=self._fence_sha256(restored),
                )
            except BaseException as error:
                cleanup_error = cleanup_error or error
            final_error = primary_error or cleanup_error
            try:
                if final_error is None:
                    coordinator.record(
                        config,
                        state="completed_restored",
                        evidence=evidence,
                    )
                else:
                    code = (
                        final_error.code
                        if isinstance(final_error, RunnerError)
                        else "PARTIAL_READY_VALIDATION_FAILED"
                    )
                    coordinator.record(
                        config,
                        state="recovery_required",
                        evidence=replace(evidence, error_code=code),
                    )
            except BaseException as error:
                cleanup_error = cleanup_error or error
            if gate_was_armed:
                cleanup_error = cleanup_error or RunnerError(
                    "PARTIAL_READY_GATE_RELEASE_FAILED"
                )
        if primary_error is not None:
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
        if browser is None:
            raise RunnerError("BROWSER_EVIDENCE_INVALID")
        return browser

    @staticmethod
    def _validate_gate_evidence(
        gate: ValidationClaimGateEvidence,
        *,
        expected_state: Literal["default_allow", "armed", "paused"],
    ) -> None:
        if type(gate) is not ValidationClaimGateEvidence or gate.state != expected_state:
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        if expected_state == "armed":
            valid = (
                gate.code == "VALIDATION_SEGMENT_CLAIM_GATE_ARMED"
                and gate.claim_limit == 1
                and gate.claimed_count == 0
                and gate.remaining_count == 1
                and gate.expires_at is not None
                and gate.run_fingerprint_sha256 is not None
                and gate.scope_fingerprint_sha256 is not None
            )
        elif expected_state == "paused":
            valid = (
                gate.code == "VALIDATION_SEGMENT_CLAIM_GATE_PAUSED"
                and gate.claim_limit == 1
                and gate.claimed_count == 1
                and gate.remaining_count == 0
                and gate.expires_at is not None
                and gate.run_fingerprint_sha256 is not None
                and gate.scope_fingerprint_sha256 is not None
            )
        else:
            valid = (
                gate.code
                in {
                    "VALIDATION_SEGMENT_CLAIM_GATE_RELEASED",
                    "VALIDATION_SEGMENT_CLAIM_GATE_DEFAULT_ALLOW",
                }
                and gate.remaining_count == 0
            )
        if not valid:
            raise RunnerError("PARTIAL_READY_GATE_INVALID")
        for value in (
            gate.run_fingerprint_sha256,
            gate.scope_fingerprint_sha256,
        ):
            if value is not None and _SHA256_RE.fullmatch(value) is None:
                raise RunnerError("PARTIAL_READY_GATE_INVALID")

    @staticmethod
    def _ready_prefix_count(manifest: _ManifestSnapshot) -> int:
        count = 0
        for state in manifest.render_statuses:
            if state != "ready":
                break
            count += 1
        if any(state == "ready" for state in manifest.render_statuses[count:]):
            raise RunnerError("PARTIAL_READY_GAP_INVALID")
        return count

    @staticmethod
    def _matching_ready_prefix(
        *,
        prior: _ManifestSnapshot,
        current: _ManifestSnapshot,
    ) -> tuple[int, int]:
        count = 0
        duration_ms = 0
        for previous, observed in zip(
            prior.audio_by_ordinal,
            current.audio_by_ordinal,
            strict=False,
        ):
            if (
                previous is None
                or observed is None
                or previous.sha256 != observed.sha256
                or previous.duration_ms != observed.duration_ms
            ):
                break
            count += 1
            duration_ms += observed.duration_ms
        return count, duration_ms

    def _poll_partial_ready(
        self,
        initial: dict[str, object],
        *,
        source_sha256: str,
        prior_ready: _ManifestSnapshot,
        coordinator: PartialReadyValidationCoordinator,
    ) -> tuple[_ManifestSnapshot, ValidationClaimGateEvidence]:
        request_id = _uuid(initial.get("request_id"))
        edition_id = _uuid(initial.get("edition_id"))
        expected_jobs = tuple(_uuid(item) for item in _list(initial.get("job_ids")))
        deadline = self._monotonic() + self._workflow_timeout_seconds
        workflow = initial
        while True:
            self._validate_workflow(workflow)
            if workflow.get("workflow_state") in _TERMINAL_WORKFLOW_FAILURES:
                raise RunnerError("WORKFLOW_TERMINAL_FAILURE")
            if workflow.get("workflow_state") == "review_required":
                raise RunnerError("PARTIAL_READY_REVIEW_UNEXPECTED")
            if (
                _uuid(workflow.get("request_id")) != request_id
                or _uuid(workflow.get("edition_id")) != edition_id
                or tuple(
                    _uuid(item) for item in _list(workflow.get("job_ids"))
                )
                != expected_jobs
            ):
                raise RunnerError("PARTIAL_READY_WORKFLOW_INVALID")
            gate = coordinator.read(self._config)
            if gate.state == "default_allow":
                raise RunnerError("PARTIAL_READY_GATE_EXPIRED")
            self._validate_gate_evidence(
                gate,
                expected_state=(
                    "paused" if gate.state == "paused" else "armed"
                ),
            )
            revision_raw = workflow.get("current_manifest_revision")
            if revision_raw is not None:
                manifest = self._read_manifest(
                    edition_id,
                    expected_revision=_positive_int(revision_raw),
                    require_ready=False,
                    expected_source_hash=source_sha256,
                    allow_newer_revision=True,
                )
                cache_hits, cache_duration = self._matching_ready_prefix(
                    prior=prior_ready,
                    current=manifest,
                )
                ready_prefix = self._ready_prefix_count(manifest)
                if (
                    manifest.status == "partial_ready"
                    and gate.state == "paused"
                    and cache_hits >= 3
                    and cache_duration >= 8_000
                    and ready_prefix >= 3
                ):
                    edition = _object(
                        self._json_request(
                            "GET",
                            f"/narration-editions/{edition_id}",
                            expected_status=200,
                        )
                    )
                    if (
                        _uuid(edition.get("edition_id")) != edition_id
                        or _uuid(edition.get("request_id")) != request_id
                        or _uuid(edition.get("novel_id"))
                        != self._config.novel_id
                        or _uuid(edition.get("document_id"))
                        != self._config.document_id
                        or edition.get("state") != "partial_ready"
                        or _positive_int(edition.get("segment_count"))
                        != len(manifest.segment_ids)
                        or _positive_int(edition.get("ready_segment_count"))
                        != len(manifest.audio)
                        or _nonnegative_int(edition.get("failed_segment_count"))
                        != 0
                        or _positive_int(
                            edition.get("current_manifest_revision")
                        )
                        < manifest.revision
                        or tuple(
                            _uuid(item)
                            for item in _list(edition.get("job_ids"))
                        )
                        != expected_jobs
                    ):
                        raise RunnerError("PARTIAL_READY_EDITION_INVALID")
                    return manifest, gate
                if gate.state == "paused" and manifest.status == "partial_ready":
                    raise RunnerError("PARTIAL_READY_CACHE_PREFIX_INVALID")
                if workflow.get("workflow_state") == "ready":
                    raise RunnerError("PARTIAL_READY_GAP_NOT_OBSERVED")
            if self._monotonic() >= deadline:
                raise RunnerError("PARTIAL_READY_POLL_TIMEOUT")
            self._sleeper(self._poll_interval_seconds)
            workflow = self._read_workflow(request_id)

    def _wait_partial_completion(
        self,
        *,
        request_id: UUID,
        edition_id: UUID,
        source_sha256: str,
    ) -> _ManifestSnapshot:
        deadline = self._monotonic() + self._workflow_timeout_seconds
        while True:
            workflow = self._read_workflow(request_id)
            state = workflow.get("workflow_state")
            if state in _TERMINAL_WORKFLOW_FAILURES or state == "review_required":
                raise RunnerError("PARTIAL_READY_COMPLETION_FAILED")
            if (
                _uuid(workflow.get("edition_id")) != edition_id
                or _uuid(workflow.get("request_id")) != request_id
            ):
                raise RunnerError("PARTIAL_READY_WORKFLOW_INVALID")
            revision_raw = workflow.get("current_manifest_revision")
            if state == "ready" and revision_raw is not None:
                manifest = self._read_manifest(
                    edition_id,
                    expected_revision=_positive_int(revision_raw),
                    require_ready=True,
                    expected_source_hash=source_sha256,
                    allow_newer_revision=True,
                )
                edition = _object(
                    self._json_request(
                        "GET",
                        f"/narration-editions/{edition_id}",
                        expected_status=200,
                    )
                )
                if (
                    edition.get("state") != "ready"
                    or _positive_int(edition.get("segment_count"))
                    != _positive_int(edition.get("ready_segment_count"))
                ):
                    raise RunnerError("PARTIAL_READY_COMPLETION_FAILED")
                return manifest
            if self._monotonic() >= deadline:
                raise RunnerError("PARTIAL_READY_COMPLETION_TIMEOUT")
            self._sleeper(self._poll_interval_seconds)

    def capture_recovery_fence(
        self,
        config: RunnerConfig,
    ) -> RecoveryFence:
        self._require_config(config)
        self._require_baseline()
        owned = self._require_owned_fence()
        if self._pending_write_intent is not None:
            raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
        observed = _recovery_fence_from_resources(
            self._read_document(),
            self._read_context(),
            config,
            code="RECOVERY_CONFLICT",
        )
        if observed != owned:
            raise RunnerError("RECOVERY_CONFLICT")
        return owned

    def restore_baseline(
        self,
        config: RunnerConfig,
        baseline: BaselineSnapshot,
        fence: RecoveryFence,
        write_intent: RecoveryWriteIntent | None,
    ) -> RecoveryOutcome:
        self._require_config(config)
        # ``--resume`` constructs a fresh executor from the authenticated
        # recovery record, so no in-memory capture exists in that process.
        if (
            type(baseline) is not BaselineSnapshot
            or type(fence) is not RecoveryFence
        ):
            raise RunnerError("BASELINE_RESTORE_INPUT_INVALID")
        if self._baseline is None:
            self._baseline = baseline
        elif baseline != self._baseline:
            raise RunnerError("BASELINE_RESTORE_INPUT_INVALID")
        expected_fence = self._resolve_recovery_intent(
            config,
            fence,
            write_intent,
        )
        document = self._read_document()
        context = self._read_context()
        _assert_recovery_fence(document, context, config, expected_fence)
        if expected_fence.content_hash != baseline.content_hash:
            next_fence = RecoveryFence(
                draft_version=expected_fence.draft_version + 1,
                content_hash=baseline.content_hash,
                current_edition_id=expected_fence.current_edition_id,
                current_script_version_id=expected_fence.current_script_version_id,
                pointer_version=expected_fence.pointer_version,
            )
            body = {
                "expected_draft_version": expected_fence.draft_version,
                "content_markdown": baseline.content_markdown,
                "content_hash": baseline.content_hash,
            }
            self._begin_authority_write(
                kind="DRAFT_WRITE",
                next_fence=next_fence,
                method="PATCH",
                path=f"/documents/{self._config.document_id}/draft",
                headers=None,
                body=body,
            )
            response = self._request(
                "PATCH",
                f"/documents/{self._config.document_id}/draft",
                body=body,
            )
            if response.status in {409, 412}:
                raise RunnerError("RECOVERY_CONFLICT")
            saved = _object(
                _response_json(
                    response,
                    200,
                    method="PATCH",
                    path=f"/documents/{self._config.document_id}/draft",
                )
            )
            if (
                _uuid(saved.get("id"), "RECOVERY_CONFLICT")
                != self._config.document_id
                or _uuid(saved.get("novel_id"), "RECOVERY_CONFLICT")
                != self._config.novel_id
                or saved.get("draft_version") != next_fence.draft_version
                or saved.get("content_hash") != baseline.content_hash
                or saved.get("content_markdown") != baseline.content_markdown
            ):
                raise RunnerError("RECOVERY_CONFLICT")
            self._complete_authority_write(next_fence)
            expected_fence = next_fence
        document = self._read_document()
        context = self._read_context()
        _assert_recovery_fence(document, context, config, expected_fence)
        if expected_fence.current_edition_id != baseline.current_edition_id:
            next_fence = RecoveryFence(
                draft_version=expected_fence.draft_version,
                content_hash=expected_fence.content_hash,
                current_edition_id=baseline.current_edition_id,
                current_script_version_id=baseline.current_script_version_id,
                pointer_version=expected_fence.pointer_version + 1,
            )
            body = {
                "target_edition_id": str(baseline.current_edition_id),
                "expected_version": expected_fence.pointer_version,
                "switch_mode": "next_playback",
                "start_segment_id": None,
                "playback_rate_millis": 1000,
                "confirmed": True,
            }
            self._begin_authority_write(
                kind="EDITION_SWITCH",
                next_fence=next_fence,
                method="PUT",
                path=(
                    f"/documents/{self._config.document_id}"
                    "/current-narration-edition"
                ),
                headers=None,
                body=body,
            )
            response = self._request(
                "PUT",
                (
                    f"/documents/{self._config.document_id}"
                    "/current-narration-edition"
                ),
                body=body,
            )
            if response.status in {409, 412}:
                raise RunnerError("RECOVERY_CONFLICT")
            switched = _object(
                _response_json(
                    response,
                    200,
                    method="PUT",
                    path=(
                        f"/documents/{self._config.document_id}"
                        "/current-narration-edition"
                    ),
                )
            )
            if (
                switched.get("current_edition_id")
                != str(baseline.current_edition_id)
                or switched.get("pointer_version")
                != next_fence.pointer_version
            ):
                raise RunnerError("RECOVERY_CONFLICT")
            self._complete_authority_write(next_fence)
            expected_fence = next_fence
        restored_document = self._read_document()
        restored_context = self._read_context()
        _assert_recovery_fence(
            restored_document,
            restored_context,
            config,
            expected_fence,
        )
        history = _object(restored_context.get("edition_history"))
        editions = _list(history.get("editions"))
        edition_ids = {
            item.get("edition_id")
            for raw in editions
            if (item := _object(raw)).get("edition_id") is not None
        }
        generated = {
            str(state.outcome.edition_id)
            for state in (self._automatic, self._manual)
            if state is not None
        }
        history_retained = (
            str(baseline.current_edition_id) in edition_ids
            and generated.issubset(edition_ids)
            and len(editions) >= baseline.edition_history_count + len(generated)
        )
        if (
            restored_document.get("content_hash") != baseline.content_hash
            or restored_document.get("content_markdown") != baseline.content_markdown
            or restored_context.get("current_edition_id")
            != str(baseline.current_edition_id)
            or restored_context.get("current_script_version_id")
            != str(baseline.current_script_version_id)
            or not history_retained
        ):
            raise RunnerError("BASELINE_RESTORE_FAILED")
        return RecoveryOutcome(
            restored_draft_version=_positive_int(
                restored_document.get("draft_version"), "BASELINE_RESTORE_FAILED"
            ),
            restored_content_hash=baseline.content_hash,
            restored_current_edition_id=baseline.current_edition_id,
            restored_current_script_version_id=baseline.current_script_version_id,
            pointer_version_after_restore=_positive_int(
                restored_context.get("pointer_version"), "BASELINE_RESTORE_FAILED"
            ),
            append_only_history_retained=True,
            new_authoritative_record_count=len(editions)
            - baseline.edition_history_count,
        )

    def _require_config(self, config: RunnerConfig) -> None:
        if config != self._config:
            raise RunnerError("REAL_EXECUTOR_CONFIG_MISMATCH")

    def _require_baseline(self) -> BaselineSnapshot:
        if self._baseline is None:
            raise RunnerError("BASELINE_REQUIRED")
        return self._baseline

    def _require_owned_fence(self) -> RecoveryFence:
        if self._owned_fence is None or self._recovery_checkpoint is None:
            raise RunnerError("RECOVERY_CHECKPOINT_REQUIRED")
        return self._owned_fence

    def _begin_authority_write(
        self,
        *,
        kind: str,
        next_fence: RecoveryFence,
        method: str,
        path: str,
        headers: Mapping[str, str] | None,
        body: object | None,
    ) -> RecoveryWriteIntent:
        old_fence = self._require_owned_fence()
        if self._pending_write_intent is not None:
            raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
        fingerprint = _sha256_text(
            json.dumps(
                {
                    "method": method,
                    "path": path,
                    "headers": dict(headers or {}),
                    "body": body,
                    "old": {
                        "draft_version": old_fence.draft_version,
                        "content_hash": old_fence.content_hash,
                        "current_edition_id": str(old_fence.current_edition_id),
                        "current_script_version_id": str(
                            old_fence.current_script_version_id
                        ),
                        "pointer_version": old_fence.pointer_version,
                    },
                    "next": {
                        "draft_version": next_fence.draft_version,
                        "content_hash": next_fence.content_hash,
                        "current_edition_id": str(next_fence.current_edition_id),
                        "current_script_version_id": str(
                            next_fence.current_script_version_id
                        ),
                        "pointer_version": next_fence.pointer_version,
                    },
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        intent = RecoveryWriteIntent(
            operation_kind=kind,
            operation_fingerprint_sha256=fingerprint,
            old_fence=old_fence,
            next_fence=next_fence,
        )
        self._pending_write_intent = intent
        assert self._recovery_checkpoint is not None
        self._recovery_checkpoint(old_fence, intent)
        return intent

    def _complete_authority_write(self, next_fence: RecoveryFence) -> None:
        intent = self._pending_write_intent
        if (
            intent is None
            or intent.next_fence != next_fence
            or self._recovery_checkpoint is None
        ):
            raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
        self._recovery_checkpoint(next_fence, None)
        self._owned_fence = next_fence
        self._pending_write_intent = None

    def _resolve_recovery_intent(
        self,
        config: RunnerConfig,
        fence: RecoveryFence,
        write_intent: RecoveryWriteIntent | None,
    ) -> RecoveryFence:
        observed = _recovery_fence_from_resources(
            self._read_document(),
            self._read_context(),
            config,
            code="RECOVERY_CONFLICT",
        )
        if write_intent is None:
            if observed != fence:
                raise RunnerError("RECOVERY_CONFLICT")
            resolved = fence
        else:
            if write_intent.old_fence != fence:
                raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
            if observed == write_intent.old_fence:
                resolved = write_intent.old_fence
            elif observed == write_intent.next_fence:
                resolved = write_intent.next_fence
            else:
                raise RunnerError("RECOVERY_CONFLICT")
            if self._recovery_checkpoint is None:
                raise RunnerError("RECOVERY_CHECKPOINT_REQUIRED")
            self._pending_write_intent = write_intent
            self._recovery_checkpoint(resolved, None)
        self._owned_fence = resolved
        self._pending_write_intent = None
        return resolved

    def _idempotency(self, stage: str) -> str:
        return f"t4k:{self._config.run_id.hex}:{stage}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: object | None = None,
    ) -> HttpResponse:
        _validate_method_path(method, path)
        try:
            response = self._transport.request(
                method=method,
                path=path,
                headers=headers,
                json_body=body,
                timeout_seconds=self._request_timeout_seconds,
            )
        except RunnerError:
            raise
        except Exception as error:
            raise RunnerError("HTTP_TRANSPORT_FAILED") from error
        if type(response) is not HttpResponse:
            raise RunnerError("HTTP_RESPONSE_INVALID")
        return response

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        headers: Mapping[str, str] | None = None,
        body: object | None = None,
    ) -> object:
        mutation = method in {"PATCH", "POST", "PUT"}
        owned: RecoveryFence | None = None
        if mutation:
            owned = self._require_owned_fence()
            self._begin_authority_write(
                kind="AUTHORITY_WRITE",
                next_fence=owned,
                method=method,
                path=path,
                headers=headers,
                body=body,
            )
        value = _response_json(
            self._request(method, path, headers=headers, body=body),
            expected_status,
            method=method,
            path=path,
        )
        if owned is not None:
            self._complete_authority_write(owned)
        return value

    def _validate_health(self) -> None:
        health = _object(
            self._json_request("GET", "/health", expected_status=200),
            "RUNTIME_PREFLIGHT_FAILED",
        )
        database = _object(health.get("database"), "RUNTIME_PREFLIGHT_FAILED")
        production = _object(
            health.get("narration_production"), "RUNTIME_PREFLIGHT_FAILED"
        )
        if (
            health.get("status") != "ready"
            or database.get("connected") is not True
            or production.get("product_requested") is not True
            or production.get("lifecycle_status") != "ready"
            or any(
                production.get(field) is not True
                for field in (
                    "playback_installed",
                    "digest_keyring_loaded",
                    "production_backend_installed",
                    "worker_running",
                )
            )
            or production.get("reason_code") is not None
        ):
            raise RunnerError("RUNTIME_PREFLIGHT_FAILED")

    def _read_document(self) -> dict[str, object]:
        return _object(
            self._json_request(
                "GET",
                f"/documents/{self._config.document_id}",
                expected_status=200,
            )
        )

    def _read_context(self) -> dict[str, object]:
        context = _object(
            self._json_request(
                "GET",
                f"/documents/{self._config.document_id}/narration-playback-context",
                expected_status=200,
            )
        )
        if (
            _uuid(context.get("document_id")) != self._config.document_id
            or _uuid(context.get("novel_id")) != self._config.novel_id
        ):
            raise RunnerError("DOCUMENT_SCOPE_MISMATCH")
        return context

    def _read_settings_version(self) -> int:
        settings = _object(
            self._json_request(
                "GET",
                f"/novels/{self._config.novel_id}/narration-settings",
                expected_status=200,
            )
        )
        values = _object(settings.get("values"))
        if (
            _uuid(settings.get("novel_id")) != self._config.novel_id
            or settings.get("exists") is not True
            or values.get("script_review_policy") != "blockers_only"
        ):
            raise RunnerError("NARRATION_SETTINGS_INVALID")
        return _positive_int(settings.get("version"), "NARRATION_SETTINGS_INVALID")

    def _save_text(self, source_text: str, source_hash: str) -> dict[str, object]:
        if _sha256_text(source_text) != source_hash:
            raise RunnerError("CASE_SOURCE_HASH_MISMATCH")
        owned = self._require_owned_fence()
        if self._pending_write_intent is not None:
            raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
        document = self._read_document()
        _assert_recovery_fence(
            document,
            self._read_context(),
            self._config,
            owned,
        )
        if owned.content_hash == source_hash:
            if (
                document.get("content_hash") != source_hash
                or document.get("content_markdown") != source_text
                or document.get("draft_version") != owned.draft_version
            ):
                raise RunnerError("DRAFT_SAVE_VERIFICATION_FAILED")
            return document
        next_fence = RecoveryFence(
            draft_version=owned.draft_version + 1,
            content_hash=source_hash,
            current_edition_id=owned.current_edition_id,
            current_script_version_id=owned.current_script_version_id,
            pointer_version=owned.pointer_version,
        )
        body = {
            "expected_draft_version": owned.draft_version,
            "content_markdown": source_text,
            "content_hash": source_hash,
        }
        self._begin_authority_write(
            kind="DRAFT_WRITE",
            next_fence=next_fence,
            method="PATCH",
            path=f"/documents/{self._config.document_id}/draft",
            headers=None,
            body=body,
        )
        response = self._request(
            "PATCH",
            f"/documents/{self._config.document_id}/draft",
            body=body,
        )
        if response.status in {409, 412}:
            raise RunnerError("RECOVERY_CONFLICT")
        saved = _object(
            _response_json(
                response,
                200,
                method="PATCH",
                path=f"/documents/{self._config.document_id}/draft",
            )
        )
        if (
            _uuid(saved.get("id")) != self._config.document_id
            or _uuid(saved.get("novel_id")) != self._config.novel_id
            or saved.get("content_hash") != source_hash
            or saved.get("content_markdown") != source_text
            or saved.get("draft_version") != next_fence.draft_version
        ):
            raise RunnerError("DRAFT_SAVE_VERIFICATION_FAILED")
        self._complete_authority_write(next_fence)
        return saved

    def _save_case(self, case: ChapterCase) -> None:
        self._save_text(case.source_text, case.source_sha256)

    def _start_workflow(self, case: ChapterCase, label: str) -> dict[str, object]:
        document = self._read_document()
        context = self._read_context()
        if (
            document.get("content_hash") != case.source_sha256
            or context.get("working_copy_content_hash") != case.source_sha256
            or context.get("current_edition_id") is None
        ):
            raise RunnerError("WORKFLOW_INPUT_STALE")
        workflow = _object(
            self._json_request(
                "POST",
                f"/documents/{self._config.document_id}/narration-requests",
                expected_status=202,
                headers={"Idempotency-Key": self._idempotency(f"{label}-start")},
                body={
                    "intent": "update",
                    "expected_draft_version": _positive_int(
                        document.get("draft_version")
                    ),
                    "expected_content_hash": case.source_sha256,
                    "expected_settings_version": self._read_settings_version(),
                    "force_review": False,
                },
            )
        )
        self._validate_workflow(workflow, case)
        return workflow

    def _validate_workflow(
        self, workflow: dict[str, object], case: ChapterCase | None = None
    ) -> None:
        _uuid(workflow.get("request_id"))
        _positive_int(workflow.get("request_version"))
        state = workflow.get("workflow_state")
        if state not in _WORKFLOW_STATES:
            raise RunnerError("WORKFLOW_RESPONSE_INVALID")
        source_hash = _sha256(workflow.get("source_content_hash"))
        if case is not None and source_hash != case.source_sha256:
            raise RunnerError("WORKFLOW_SOURCE_MISMATCH")
        script_id = workflow.get("script_version_id")
        edition_id = workflow.get("edition_id")
        if script_id is not None:
            _uuid(script_id)
        if edition_id is not None:
            _uuid(edition_id)
        jobs = _list(workflow.get("job_ids"))
        job_ids = tuple(_uuid(item) for item in jobs)
        if len(job_ids) != len(set(job_ids)):
            raise RunnerError("WORKFLOW_RESPONSE_INVALID")

    def _read_workflow(self, request_id: UUID) -> dict[str, object]:
        workflow = _object(
            self._json_request(
                "GET", f"/narration-requests/{request_id}", expected_status=200
            )
        )
        self._validate_workflow(workflow)
        if _uuid(workflow.get("request_id")) != request_id:
            raise RunnerError("WORKFLOW_RESPONSE_INVALID")
        return workflow

    def _poll_ready(
        self,
        initial: dict[str, object],
        *,
        chain_label: Literal["automatic", "manual"],
        started_at: float,
        allow_review_required: bool,
    ) -> tuple[dict[str, object], float, int]:
        request_id = _uuid(initial.get("request_id"))
        deadline = self._monotonic() + self._workflow_timeout_seconds
        workflow = initial
        first_audio_ms: int | None = None
        observed_revisions: set[tuple[UUID, int]] = set()
        while True:
            self._validate_workflow(workflow)
            state = workflow.get("workflow_state")
            if state in _TERMINAL_WORKFLOW_FAILURES:
                raise RunnerError("WORKFLOW_TERMINAL_FAILURE")
            if state == "review_required" and not allow_review_required:
                raise RunnerError("WORKFLOW_REVIEW_UNEXPECTED")
            revision = workflow.get("current_manifest_revision")
            edition_raw = workflow.get("edition_id")
            if revision is not None and edition_raw is not None:
                manifest = self._read_manifest(
                    _uuid(edition_raw),
                    expected_revision=_positive_int(revision),
                    require_ready=False,
                    allow_newer_revision=True,
                )
                if manifest.nonretryable_failure_codes:
                    raise RunnerError(
                        sorted(manifest.nonretryable_failure_codes)[0]
                    )
                if manifest.audio and first_audio_ms is None:
                    first_audio_ms = max(
                        0, int(round((self._monotonic() - started_at) * 1000))
                    )
                observation_key = (manifest.edition_id, manifest.revision)
                if observation_key not in observed_revisions:
                    observed_revisions.add(observation_key)
                    self._browser_probe.observe_manifest(
                        self._config,
                        BrowserManifestObservation(
                            chain_label=chain_label,
                            request_id=request_id,
                            edition_id=manifest.edition_id,
                            workflow_state=str(state),
                            manifest_revision=manifest.revision,
                            ready_segment_count=len(manifest.audio),
                            total_segment_count=len(manifest.segment_ids),
                            elapsed_ms=max(
                                0,
                                int(
                                    round(
                                        (self._monotonic() - started_at) * 1000
                                    )
                                ),
                            ),
                        ),
                    )
            if state == "ready":
                elapsed = max(0.0, self._monotonic() - started_at)
                return workflow, elapsed, first_audio_ms or 0
            if self._monotonic() >= deadline:
                raise RunnerError("WORKFLOW_POLL_TIMEOUT")
            self._sleeper(self._poll_interval_seconds)
            workflow = self._read_workflow(request_id)

    def _read_script(self, version_id: UUID) -> dict[str, object]:
        script = _object(
            self._json_request(
                "GET",
                f"/narration-script-versions/{version_id}",
                expected_status=200,
            )
        )
        if _uuid(script.get("script_version_id")) != version_id:
            raise RunnerError("SCRIPT_RESPONSE_INVALID")
        return script

    def _validate_script_scope(
        self,
        script: dict[str, object],
        case: ChapterCase,
        version_id: UUID,
    ) -> None:
        if (
            _uuid(script.get("script_version_id")) != version_id
            or _uuid(script.get("novel_id")) != self._config.novel_id
            or _uuid(script.get("document_id")) != self._config.document_id
            or _sha256(script.get("source_content_hash")) != case.source_sha256
        ):
            raise RunnerError("SCRIPT_SCOPE_MISMATCH")
        _positive_int(script.get("version_number"))
        _sha256(script.get("immutable_hash"))
        _nonnegative_int(script.get("warning_count"))
        _nonnegative_int(script.get("blocker_count"))
        segments = _list(script.get("segments"))
        ordinals = [
            _nonnegative_int(_object(item).get("ordinal")) for item in segments
        ]
        if ordinals != list(range(len(segments))):
            raise RunnerError("SCRIPT_RESPONSE_INVALID")

    def _script_approval_kind(self, script: dict[str, object]) -> str | None:
        approval = script.get("approval")
        if approval is None:
            return None
        value = _object(approval).get("kind")
        return value if type(value) is str else None

    def _locate_correction_segment(self, script, correction):  # type: ignore[no-untyped-def]
        segments = _list(script.get("segments"))
        if correction.segment_ordinal >= len(segments):
            raise RunnerError("CORRECTION_SEGMENT_MISMATCH")
        segment = _object(segments[correction.segment_ordinal])
        source_text = segment.get("source_text")
        if (
            segment.get("ordinal") != correction.segment_ordinal
            or segment.get("source_start_utf16")
            != correction.expected_source_start_utf16
            or segment.get("source_end_utf16") != correction.expected_source_end_utf16
            or segment.get("local_hash") != correction.expected_source_local_hash
            or type(source_text) is not str
            or _sha256_text(source_text) != correction.expected_source_local_hash
            or segment.get("editable") is not True
        ):
            raise RunnerError("CORRECTION_SEGMENT_MISMATCH")
        _uuid(segment.get("segment_id"))
        return segment

    def _resolve_correction_target(
        self,
        speaker_kind: str,
        speaker_label: str,
    ) -> UUID | None:
        if speaker_kind == "narrator":
            return None
        if speaker_kind == "anonymous":
            raise RunnerError("ANONYMOUS_CORRECTION_UNSUPPORTED")
        if speaker_kind != "character":
            raise RunnerError("CORRECTION_SPEAKER_INVALID")
        raw = self._json_request(
            "GET",
            f"/novels/{self._config.novel_id}/characters",
            expected_status=200,
        )
        matches: list[UUID] = []
        for item in _list(raw):
            character = _object(item)
            if (
                character.get("name") == speaker_label
                and character.get("lifecycle_state") == "active"
                and _uuid(character.get("novel_id")) == self._config.novel_id
            ):
                matches.append(_uuid(character.get("id")))
        if len(matches) != 1:
            raise RunnerError("CHARACTER_TARGET_AMBIGUOUS")
        return matches[0]

    def _complete_chain(
        self,
        *,
        chain_label: Literal["automatic", "manual"],
        case: ChapterCase,
        workflow: dict[str, object],
        expected_approval: Literal["auto_no_blockers", "manual_after_review"],
        initial_blocker_count: int,
        request_to_ready_seconds: float,
        first_audio_ms: int,
    ) -> _ChainState:
        if workflow.get("workflow_state") != "ready":
            raise RunnerError("WORKFLOW_NOT_READY")
        request_id = _uuid(workflow.get("request_id"))
        script_id = _uuid(workflow.get("script_version_id"))
        edition_id = _uuid(workflow.get("edition_id"))
        revision = _positive_int(workflow.get("current_manifest_revision"))
        script = self._read_script(script_id)
        self._validate_script_scope(script, case, script_id)
        if (
            script.get("state") != "approved"
            or _nonnegative_int(script.get("blocker_count")) != 0
            or self._script_approval_kind(script) != expected_approval
        ):
            raise RunnerError("SCRIPT_APPROVAL_INVALID")
        edition = _object(
            self._json_request(
                "GET", f"/narration-editions/{edition_id}", expected_status=200
            )
        )
        if (
            _uuid(edition.get("edition_id")) != edition_id
            or _uuid(edition.get("request_id")) != request_id
            or _uuid(edition.get("script_version_id")) != script_id
            or _uuid(edition.get("novel_id")) != self._config.novel_id
            or _uuid(edition.get("document_id")) != self._config.document_id
            or edition.get("state") != "ready"
            or _positive_int(edition.get("current_manifest_revision")) != revision
            or _positive_int(edition.get("segment_count"))
            != _positive_int(edition.get("ready_segment_count"))
        ):
            raise RunnerError("EDITION_RESPONSE_INVALID")
        edition_fingerprint = _sha256(
            edition.get("edition_fingerprint"),
            "EDITION_FINGERPRINT_MISMATCH",
        )
        manifest = self._read_manifest(
            edition_id,
            expected_revision=revision,
            require_ready=True,
            expected_source_hash=case.source_sha256,
        )
        segments = tuple(_object(item) for item in _list(script.get("segments")))
        narrator_count = sum(item.get("speaker_kind") == "narrator" for item in segments)
        character_segments = [
            item for item in segments if item.get("speaker_kind") == "character"
        ]
        characters = {_uuid(item.get("character_id")) for item in character_segments}
        context = self._read_context()
        history_items = _list(_object(context.get("edition_history")).get("editions"))
        edition_count = sum(
            _object(item).get("request_id") == str(request_id) for item in history_items
        )
        job_ids = tuple(_uuid(item) for item in _list(workflow.get("job_ids")))
        audit = self._runtime_audit_probe.audit_chain(
            self._config,
            request_id=request_id,
            edition_id=edition_id,
            script_version_id=script_id,
            job_ids=job_ids,
            segment_ids=manifest.segment_ids,
        )
        self._validate_chain_audit(
            audit,
            request_id=request_id,
            edition_id=edition_id,
            script_version_id=script_id,
            edition_fingerprint=edition_fingerprint,
            maximum_job_count=len(job_ids),
        )
        self._switch_edition(edition_id, script_id)
        self._browser_probe.complete_chain(
            self._config,
            chain_label=chain_label,
            request_id=request_id,
            edition_id=edition_id,
        )
        outcome = ChainOutcome(
            request_id=request_id,
            script_version_id=script_id,
            edition_id=edition_id,
            edition_fingerprint=edition_fingerprint,
            approval_kind=expected_approval,
            initial_blocker_count=initial_blocker_count,
            final_blocker_count=0,
            edition_count_for_request=edition_count,
            manifest_revision=revision,
            narrator_segment_count=narrator_count,
            character_segment_count=len(character_segments),
            distinct_character_count=len(characters),
            distinct_voice_version_count=audit.distinct_voice_version_count,
            uncached_nano_job_count=audit.uncached_nano_job_count,
            model_run_fingerprints=audit.model_run_fingerprints,
        )
        return _ChainState(
            outcome=outcome,
            manifest=manifest,
            request_to_ready_seconds=request_to_ready_seconds,
            observed_http_first_audio_ms=first_audio_ms,
        )

    def _validate_chain_audit(
        self,
        audit: object,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        edition_fingerprint: str,
        maximum_job_count: int,
    ) -> None:
        expected_model_fingerprint = self._expected_model_fingerprint
        if type(audit) is not ChainAuditEvidence:
            raise RunnerError("NANO_AUDIT_EVIDENCE_INVALID")
        if (
            type(edition_fingerprint) is not str
            or _SHA256_RE.fullmatch(edition_fingerprint) is None
            or type(audit.edition_fingerprint) is not str
            or _SHA256_RE.fullmatch(audit.edition_fingerprint) is None
            or audit.edition_fingerprint != edition_fingerprint
        ):
            raise RunnerError("EDITION_FINGERPRINT_MISMATCH")
        if (
            audit.request_id != request_id
            or audit.edition_id != edition_id
            or audit.script_version_id != script_version_id
            or type(audit.distinct_voice_version_count) is not int
            or audit.distinct_voice_version_count < 1
            or type(audit.uncached_nano_job_count) is not int
            or audit.uncached_nano_job_count < 1
            or audit.uncached_nano_job_count > maximum_job_count
            or not audit.model_run_fingerprints
            or len(audit.model_run_fingerprints)
            != len(set(audit.model_run_fingerprints))
            or expected_model_fingerprint is None
            or audit.model_run_fingerprints != (expected_model_fingerprint,)
            or any(
                type(value) is not str or _SHA256_RE.fullmatch(value) is None
                for value in audit.model_run_fingerprints
            )
        ):
            raise RunnerError("NANO_AUDIT_EVIDENCE_INVALID")

    def _switch_edition(self, edition_id: UUID, script_version_id: UUID) -> None:
        owned = self._require_owned_fence()
        _assert_recovery_fence(
            self._read_document(),
            self._read_context(),
            self._config,
            owned,
        )
        if owned.current_edition_id == edition_id:
            if owned.current_script_version_id != script_version_id:
                raise RunnerError("EDITION_SWITCH_VERIFICATION_FAILED")
            return
        next_fence = RecoveryFence(
            draft_version=owned.draft_version,
            content_hash=owned.content_hash,
            current_edition_id=edition_id,
            current_script_version_id=script_version_id,
            pointer_version=owned.pointer_version + 1,
        )
        body = {
            "target_edition_id": str(edition_id),
            "expected_version": owned.pointer_version,
            "switch_mode": "next_playback",
            "start_segment_id": None,
            "playback_rate_millis": 1000,
            "confirmed": True,
        }
        self._begin_authority_write(
            kind="EDITION_SWITCH",
            next_fence=next_fence,
            method="PUT",
            path=(
                f"/documents/{self._config.document_id}"
                "/current-narration-edition"
            ),
            headers=None,
            body=body,
        )
        response = self._request(
            "PUT",
            (
                f"/documents/{self._config.document_id}"
                "/current-narration-edition"
            ),
            body=body,
        )
        if response.status in {409, 412}:
            raise RunnerError("RECOVERY_CONFLICT")
        switched = _object(
            _response_json(
                response,
                200,
                method="PUT",
                path=(
                    f"/documents/{self._config.document_id}"
                    "/current-narration-edition"
                ),
            )
        )
        if (
            switched.get("current_edition_id") != str(edition_id)
            or switched.get("pointer_version") != next_fence.pointer_version
        ):
            raise RunnerError("EDITION_SWITCH_VERIFICATION_FAILED")
        self._complete_authority_write(next_fence)
        after = self._read_context()
        if (
            after.get("current_edition_id") != str(edition_id)
            or after.get("current_script_version_id") != str(script_version_id)
        ):
            raise RunnerError("EDITION_SWITCH_VERIFICATION_FAILED")

    def _read_manifest(
        self,
        edition_id: UUID,
        *,
        expected_revision: int,
        require_ready: bool,
        expected_source_hash: str | None = None,
        allow_newer_revision: bool = False,
    ) -> _ManifestSnapshot:
        response = self._request(
            "GET", f"/narration-editions/{edition_id}/manifest"
        )
        raw = _object(
            _response_json(
                response,
                200,
                method="GET",
                path=f"/narration-editions/{edition_id}/manifest",
            ),
            "MANIFEST_INVALID",
        )
        status = raw.get("status")
        actual_revision = _positive_int(
            raw.get("manifest_revision"), "MANIFEST_INVALID"
        )
        revision_matches = (
            actual_revision >= expected_revision
            if allow_newer_revision
            else actual_revision == expected_revision
        )
        if (
            raw.get("schema_version") != "narration-manifest/2.0"
            or _uuid(raw.get("edition_id"), "MANIFEST_INVALID") != edition_id
            or _uuid(raw.get("chapter_id"), "MANIFEST_INVALID")
            != self._config.document_id
            or not revision_matches
            or raw.get("etag") != response.header("ETag")
            or type(raw.get("etag")) is not str
            or re.fullmatch(r'"[a-f0-9]{64}"', raw["etag"]) is None
            or status not in {"partial_ready", "ready"}
            or (expected_source_hash is not None and raw.get("source_sha256") != expected_source_hash)
            or (require_ready and raw.get("status") != "ready")
        ):
            raise RunnerError("MANIFEST_INVALID")
        source_sha256 = _sha256(raw.get("source_sha256"), "MANIFEST_INVALID")
        segment_ids: list[UUID] = []
        audio: list[_ManifestAudio] = []
        audio_by_ordinal: list[_ManifestAudio | None] = []
        render_statuses: list[str] = []
        nonretryable_failure_codes: list[str] = []
        segments = _list(raw.get("segments"), "MANIFEST_INVALID")
        for ordinal, item in enumerate(segments):
            segment = _object(item, "MANIFEST_INVALID")
            if segment.get("ordinal") != ordinal:
                raise RunnerError("MANIFEST_INVALID")
            segment_ids.append(_uuid(segment.get("segment_id"), "MANIFEST_INVALID"))
            render_status = segment.get("render_status")
            if type(render_status) is not str:
                raise RunnerError("MANIFEST_INVALID")
            render_statuses.append(render_status)
            audio_raw = segment.get("audio")
            failure_raw = segment.get("failure")
            if render_status == "ready":
                if failure_raw is not None:
                    raise RunnerError("MANIFEST_INVALID")
                entry = _object(audio_raw, "MANIFEST_INVALID")
                digest = _sha256(entry.get("actual_sha256"), "MANIFEST_INVALID")
                etag = entry.get("etag")
                duration = _positive_int(entry.get("duration_ms"), "MANIFEST_INVALID")
                if (
                    etag != f'"{digest}"'
                    or entry.get("sample_rate") != 48000
                    or entry.get("channels") != 2
                ):
                    raise RunnerError("MANIFEST_INVALID")
                asset_id, path = self._media_path(entry.get("url"))
                audio_entry = _ManifestAudio(
                    asset_id=asset_id,
                    path=path,
                    sha256=digest,
                    etag=etag,
                    duration_ms=duration,
                )
                audio.append(audio_entry)
                audio_by_ordinal.append(audio_entry)
            elif require_ready or audio_raw is not None or render_status not in {
                "pending",
                "queued",
                "rendering",
                "failed",
            }:
                raise RunnerError("MANIFEST_INVALID")
            else:
                if render_status == "failed":
                    failure = _object(failure_raw, "MANIFEST_INVALID")
                    public_code = failure.get("code")
                    retryable = failure.get("retryable")
                    if (
                        type(public_code) is not str
                        or re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", public_code)
                        is None
                        or type(retryable) is not bool
                    ):
                        raise RunnerError("MANIFEST_INVALID")
                    if retryable is False:
                        nonretryable_failure_codes.append(
                            _manifest_nonretryable_error_code(public_code)
                        )
                elif failure_raw is not None:
                    raise RunnerError("MANIFEST_INVALID")
                audio_by_ordinal.append(None)
        if not segments or not audio or (require_ready and len(audio) != len(segments)):
            raise RunnerError("MANIFEST_INVALID")
        return _ManifestSnapshot(
            edition_id=edition_id,
            revision=actual_revision,
            etag=raw["etag"],
            status=cast(Literal["partial_ready", "ready"], status),
            source_sha256=source_sha256,
            payload_sha256=_sha256_text(
                json.dumps(
                    raw,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            segment_ids=tuple(segment_ids),
            audio=tuple(audio),
            audio_by_ordinal=tuple(audio_by_ordinal),
            render_statuses=tuple(render_statuses),
            nonretryable_failure_codes=tuple(nonretryable_failure_codes),
        )

    def _media_path(self, value: object) -> tuple[UUID, str]:
        if type(value) is not str:
            raise RunnerError("MANIFEST_MEDIA_URL_INVALID")
        try:
            parsed = urlsplit(value)
        except ValueError as error:
            raise RunnerError("MANIFEST_MEDIA_URL_INVALID") from error
        prefix = f"{API_PATH}/media-assets/"
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or parsed.path != value
            or not value.startswith(prefix)
            or not value.endswith("/content")
        ):
            raise RunnerError("MANIFEST_MEDIA_URL_INVALID")
        relative = value[len(API_PATH) :]
        _validate_method_path("GET", relative)
        raw_id = relative.removeprefix("/media-assets/").removesuffix("/content")
        return _uuid(raw_id, "MANIFEST_MEDIA_URL_INVALID"), relative

    def _exercise_manifest(
        self,
        label: str,
        expected: _ManifestSnapshot,
    ) -> tuple[set[int], set[str]]:
        current = self._read_manifest(
            expected.edition_id,
            expected_revision=expected.revision,
            require_ready=True,
        )
        if current != expected:
            raise RunnerError("MANIFEST_CHANGED_AFTER_READY")
        first_segment = expected.segment_ids[0]
        prepared = _object(
            self._json_request(
                "POST",
                f"/narration-editions/{expected.edition_id}/prepare-range",
                expected_status=200,
                headers={"Idempotency-Key": self._idempotency(f"{label}-prepare-range")},
                body={
                    "start_segment_id": str(first_segment),
                    "reason": "user_seek",
                    "expected_manifest_revision": expected.revision,
                },
            )
        )
        if (
            prepared.get("edition_id") != str(expected.edition_id)
            or prepared.get("start_segment_id") != str(first_segment)
            or prepared.get("state") != "ready"
            or prepared.get("manifest_revision") != expected.revision
            or prepared.get("manifest_etag") != expected.etag
            or type(prepared.get("ready_range")) is not dict
        ):
            raise RunnerError("PREPARE_RANGE_INVALID")
        statuses: set[int] = set()
        hashes: set[str] = set()
        auth = {
            "X-Narration-Edition-Id": str(expected.edition_id),
            "X-Narration-Manifest-Revision": str(expected.revision),
            "Accept": "audio/*",
        }
        for index, audio in enumerate(expected.audio):
            full = self._request("GET", audio.path, headers=auth)
            self._validate_media_response(full, expected_status=200, audio=audio)
            if _sha256_bytes(full.body) != audio.sha256:
                raise RunnerError("MEDIA_HASH_MISMATCH")
            statuses.add(full.status)
            hashes.add(audio.sha256)
            if index != 0:
                continue
            total = len(full.body)
            head = self._request("HEAD", audio.path, headers=auth)
            self._validate_media_response(
                head, expected_status=200, audio=audio, expected_length=total
            )
            if head.body:
                raise RunnerError("MEDIA_RANGE_INVALID")
            statuses.add(head.status)
            partial = self._request(
                "GET", audio.path, headers={**auth, "Range": "bytes=0-0"}
            )
            self._validate_media_response(
                partial,
                expected_status=206,
                audio=audio,
                expected_length=1,
            )
            if partial.body != full.body[:1] or partial.header("Content-Range") != f"bytes 0-0/{total}":
                raise RunnerError("MEDIA_RANGE_INVALID")
            statuses.add(partial.status)
            unchanged = self._request(
                "GET", audio.path, headers={**auth, "If-None-Match": audio.etag}
            )
            self._validate_media_response(
                unchanged, expected_status=304, audio=audio
            )
            if unchanged.body:
                raise RunnerError("MEDIA_RANGE_INVALID")
            statuses.add(unchanged.status)
            unsatisfied = self._request(
                "GET", audio.path, headers={**auth, "Range": f"bytes={total}-"}
            )
            self._validate_media_response(
                unsatisfied, expected_status=416, audio=audio
            )
            if (
                unsatisfied.body
                or unsatisfied.header("Content-Range") != f"bytes */{total}"
            ):
                raise RunnerError("MEDIA_RANGE_INVALID")
            statuses.add(unsatisfied.status)
        return statuses, hashes

    def _validate_media_response(
        self,
        response: HttpResponse,
        *,
        expected_status: int,
        audio: _ManifestAudio,
        expected_length: int | None = None,
    ) -> None:
        if response.status != expected_status or response.header("ETag") != audio.etag:
            raise RunnerError("MEDIA_RANGE_INVALID")
        if expected_status in {200, 206}:
            content_type = response.header("Content-Type") or ""
            length = response.header("Content-Length")
            if (
                not content_type.split(";", 1)[0].startswith("audio/")
                or response.header("Accept-Ranges") != "bytes"
                or length is None
                or not length.isdigit()
                or int(length) != (len(response.body) if expected_length is None else expected_length)
            ):
                raise RunnerError("MEDIA_RANGE_INVALID")
        if expected_status == 206 and response.header("Content-Range") is None:
            raise RunnerError("MEDIA_RANGE_INVALID")
        if expected_status in {304, 416} and response.body:
            raise RunnerError("MEDIA_RANGE_INVALID")

    def _validate_browser_evidence(self, value: object) -> None:
        if (
            type(value) is not BrowserTechnicalEvidence
            or type(value.time_to_first_audio_ms) is not int
            or value.time_to_first_audio_ms < 0
            or value.seek_latest_wins is not True
            or value.pending_gap_not_skipped is not True
            or type(value.edit_actions_created_tts_writes) is not int
            or value.edit_actions_created_tts_writes != 0
            or value.browser_viewports != ALLOWED_VIEWPORTS
            or value.browser_assistant_modes != ("collapsed", "expanded")
            or type(value.browser_console_error_count) is not int
            or value.browser_console_error_count != 0
            or type(value.browser_overlap_count) is not int
            or value.browser_overlap_count != 0
            or type(value.collector_collected_at) is not str
            or _UTC_SECOND_RE.fullmatch(value.collector_collected_at) is None
        ):
            raise RunnerError("BROWSER_PROBE_EVIDENCE_INVALID")

    def _validate_runtime_evidence(self, value: object) -> None:
        if (
            type(value) is not RuntimeTechnicalEvidence
            or type(value.stability_elapsed_seconds) not in {int, float}
            or not math.isfinite(float(value.stability_elapsed_seconds))
            or value.stability_elapsed_seconds < self._config.duration_minutes * 60
            or type(value.peak_memory_bytes) is not int
            or value.peak_memory_bytes < 0
            or type(value.pageout_delta) is not int
            or value.pageout_delta < 0
            or type(value.swapout_delta) is not int
            or value.swapout_delta < 0
            or type(value.memory_baseline_median_bytes) is not int
            or value.memory_baseline_median_bytes < 0
            or type(value.memory_tail_median_bytes) is not int
            or value.memory_tail_median_bytes < 0
            or type(value.memory_growth_bytes) is not int
            or value.memory_growth_bytes < 0
            or type(value.memory_growth_limit_bytes) is not int
            or value.memory_growth_limit_bytes < 0
            or type(value.sidecar_memory_growth_observed) is not bool
            or type(value.seam_pairs_checked) is not int
            or value.seam_pairs_checked < 1
            or type(value.sidecar_restart_count) is not int
            or value.sidecar_restart_count != 0
            or type(value.health_failure_count) is not int
            or value.health_failure_count != 0
            or type(value.host_paging_observed) is not bool
            or type(value.qwenpaw_slowdown_observed) is not bool
        ):
            raise RunnerError("RUNTIME_PROBE_EVIDENCE_INVALID")


class RealChapterE2ERecoveryExecutor:
    """Narrow restore-only HTTP executor used exclusively by ``--resume``.

    It intentionally has no automatic/manual/technical-check methods and owns
    no browser or runtime-audit probe.  This prevents a recovery invocation
    from accidentally constructing or entering the normal destructive chain.
    """

    def __init__(
        self,
        config: RunnerConfig,
        *,
        transport: HttpTransport | None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        _validated_api_base(config.api_base)
        if config.mode != "real":
            raise RunnerError("REAL_EXECUTOR_MODE_INVALID")
        if transport is None or not callable(getattr(transport, "request", None)):
            raise RunnerError("REAL_HTTP_TRANSPORT_REQUIRED")
        if (
            type(request_timeout_seconds) not in {int, float}
            or not math.isfinite(float(request_timeout_seconds))
            or not 0 < float(request_timeout_seconds) <= 120
        ):
            raise RunnerError("REAL_EXECUTOR_LIMIT_INVALID")
        self._config = config
        self._transport = transport
        self._request_timeout_seconds = float(request_timeout_seconds)
        self._owned_fence: RecoveryFence | None = None
        self._pending_write_intent: RecoveryWriteIntent | None = None
        self._recovery_checkpoint: (
            Callable[[RecoveryFence, RecoveryWriteIntent | None], None] | None
        ) = None

    def set_recovery_checkpoint(
        self,
        checkpoint: Callable[
            [RecoveryFence, RecoveryWriteIntent | None],
            None,
        ],
    ) -> None:
        if self._recovery_checkpoint is not None or not callable(checkpoint):
            raise RunnerError("RECOVERY_CHECKPOINT_INVALID")
        self._recovery_checkpoint = checkpoint

    def _begin_recovery_write(
        self,
        *,
        kind: str,
        next_fence: RecoveryFence,
    ) -> None:
        old_fence = self._owned_fence
        if (
            old_fence is None
            or self._pending_write_intent is not None
            or self._recovery_checkpoint is None
        ):
            raise RunnerError("RECOVERY_CHECKPOINT_REQUIRED")
        intent = RecoveryWriteIntent(
            operation_kind=kind,
            operation_fingerprint_sha256=_sha256_text(
                json.dumps(
                    {
                        "run_id": str(self._config.run_id),
                        "kind": kind,
                        "old": {
                            "draft_version": old_fence.draft_version,
                            "content_hash": old_fence.content_hash,
                            "edition": str(old_fence.current_edition_id),
                            "script": str(old_fence.current_script_version_id),
                            "pointer_version": old_fence.pointer_version,
                        },
                        "next": {
                            "draft_version": next_fence.draft_version,
                            "content_hash": next_fence.content_hash,
                            "edition": str(next_fence.current_edition_id),
                            "script": str(next_fence.current_script_version_id),
                            "pointer_version": next_fence.pointer_version,
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            old_fence=old_fence,
            next_fence=next_fence,
        )
        self._pending_write_intent = intent
        self._recovery_checkpoint(old_fence, intent)

    def _complete_recovery_write(self, next_fence: RecoveryFence) -> None:
        if (
            self._pending_write_intent is None
            or self._pending_write_intent.next_fence != next_fence
            or self._recovery_checkpoint is None
        ):
            raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
        self._recovery_checkpoint(next_fence, None)
        self._owned_fence = next_fence
        self._pending_write_intent = None

    def _resolve_recovery_intent(
        self,
        config: RunnerConfig,
        fence: RecoveryFence,
        write_intent: RecoveryWriteIntent | None,
    ) -> RecoveryFence:
        observed = _recovery_fence_from_resources(
            self._read_document(),
            self._read_context(),
            config,
            code="RECOVERY_CONFLICT",
        )
        if write_intent is None:
            if observed != fence:
                raise RunnerError("RECOVERY_CONFLICT")
            resolved = fence
        else:
            if write_intent.old_fence != fence:
                raise RunnerError("RECOVERY_WRITE_INTENT_INVALID")
            if observed == write_intent.old_fence:
                resolved = write_intent.old_fence
            elif observed == write_intent.next_fence:
                resolved = write_intent.next_fence
            else:
                raise RunnerError("RECOVERY_CONFLICT")
            if self._recovery_checkpoint is None:
                raise RunnerError("RECOVERY_CHECKPOINT_REQUIRED")
            self._pending_write_intent = write_intent
            self._recovery_checkpoint(resolved, None)
        self._owned_fence = resolved
        self._pending_write_intent = None
        return resolved

    def restore_baseline(
        self,
        config: RunnerConfig,
        baseline: BaselineSnapshot,
        fence: RecoveryFence,
        write_intent: RecoveryWriteIntent | None,
    ) -> RecoveryOutcome:
        if (
            config != self._config
            or type(baseline) is not BaselineSnapshot
            or type(fence) is not RecoveryFence
        ):
            raise RunnerError("BASELINE_RESTORE_INPUT_INVALID")
        expected_fence = self._resolve_recovery_intent(
            config,
            fence,
            write_intent,
        )
        if expected_fence.content_hash != baseline.content_hash:
            next_fence = RecoveryFence(
                draft_version=expected_fence.draft_version + 1,
                content_hash=baseline.content_hash,
                current_edition_id=expected_fence.current_edition_id,
                current_script_version_id=expected_fence.current_script_version_id,
                pointer_version=expected_fence.pointer_version,
            )
            self._begin_recovery_write(
                kind="DRAFT_WRITE",
                next_fence=next_fence,
            )
            response = self._request(
                "PATCH",
                f"/documents/{self._config.document_id}/draft",
                body={
                    "expected_draft_version": expected_fence.draft_version,
                    "content_markdown": baseline.content_markdown,
                    "content_hash": baseline.content_hash,
                },
            )
            if response.status in {409, 412}:
                raise RunnerError("RECOVERY_CONFLICT")
            saved = _object(
                _response_json(
                    response,
                    200,
                    method="PATCH",
                    path=f"/documents/{self._config.document_id}/draft",
                )
            )
            if (
                _uuid(saved.get("id"), "RECOVERY_CONFLICT")
                != self._config.document_id
                or _uuid(saved.get("novel_id"), "RECOVERY_CONFLICT")
                != self._config.novel_id
                or saved.get("draft_version") != next_fence.draft_version
                or saved.get("content_hash") != baseline.content_hash
                or saved.get("content_markdown") != baseline.content_markdown
            ):
                raise RunnerError("RECOVERY_CONFLICT")
            self._complete_recovery_write(next_fence)
            expected_fence = next_fence
        document = self._read_document()
        context = self._read_context()
        _assert_recovery_fence(document, context, config, expected_fence)
        if expected_fence.current_edition_id != baseline.current_edition_id:
            next_fence = RecoveryFence(
                draft_version=expected_fence.draft_version,
                content_hash=expected_fence.content_hash,
                current_edition_id=baseline.current_edition_id,
                current_script_version_id=baseline.current_script_version_id,
                pointer_version=expected_fence.pointer_version + 1,
            )
            self._begin_recovery_write(
                kind="EDITION_SWITCH",
                next_fence=next_fence,
            )
            response = self._request(
                "PUT",
                (
                    f"/documents/{self._config.document_id}"
                    "/current-narration-edition"
                ),
                body={
                    "target_edition_id": str(baseline.current_edition_id),
                    "expected_version": expected_fence.pointer_version,
                    "switch_mode": "next_playback",
                    "start_segment_id": None,
                    "playback_rate_millis": 1000,
                    "confirmed": True,
                },
            )
            if response.status in {409, 412}:
                raise RunnerError("RECOVERY_CONFLICT")
            switched = _object(
                _response_json(
                    response,
                    200,
                    method="PUT",
                    path=(
                        f"/documents/{self._config.document_id}"
                        "/current-narration-edition"
                    ),
                )
            )
            if (
                switched.get("current_edition_id")
                != str(baseline.current_edition_id)
                or switched.get("pointer_version")
                != next_fence.pointer_version
            ):
                raise RunnerError("RECOVERY_CONFLICT")
            self._complete_recovery_write(next_fence)
            expected_fence = next_fence
        restored_document = self._read_document()
        restored_context = self._read_context()
        _assert_recovery_fence(
            restored_document,
            restored_context,
            config,
            expected_fence,
        )
        history = _object(restored_context.get("edition_history"))
        editions = _list(history.get("editions"))
        edition_ids = {
            item.get("edition_id")
            for raw in editions
            if (item := _object(raw)).get("edition_id") is not None
        }
        if (
            restored_document.get("content_hash") != baseline.content_hash
            or restored_document.get("content_markdown")
            != baseline.content_markdown
            or restored_context.get("current_edition_id")
            != str(baseline.current_edition_id)
            or restored_context.get("current_script_version_id")
            != str(baseline.current_script_version_id)
            or str(baseline.current_edition_id) not in edition_ids
            or len(editions) < baseline.edition_history_count
        ):
            raise RunnerError("BASELINE_RESTORE_FAILED")
        return RecoveryOutcome(
            restored_draft_version=_positive_int(
                restored_document.get("draft_version"),
                "BASELINE_RESTORE_FAILED",
            ),
            restored_content_hash=baseline.content_hash,
            restored_current_edition_id=baseline.current_edition_id,
            restored_current_script_version_id=baseline.current_script_version_id,
            pointer_version_after_restore=_positive_int(
                restored_context.get("pointer_version"),
                "BASELINE_RESTORE_FAILED",
            ),
            append_only_history_retained=True,
            new_authoritative_record_count=(
                len(editions) - baseline.edition_history_count
            ),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: object | None = None,
    ) -> HttpResponse:
        _validate_method_path(method, path)
        try:
            response = self._transport.request(
                method=method,
                path=path,
                headers=headers,
                json_body=body,
                timeout_seconds=self._request_timeout_seconds,
            )
        except RunnerError:
            raise
        except Exception as error:
            raise RunnerError("HTTP_TRANSPORT_FAILED") from error
        if type(response) is not HttpResponse:
            raise RunnerError("HTTP_RESPONSE_INVALID")
        return response

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        body: object | None = None,
    ) -> object:
        return _response_json(
            self._request(method, path, body=body),
            expected_status,
            method=method,
            path=path,
        )

    def _read_document(self) -> dict[str, object]:
        return _object(
            self._json_request(
                "GET",
                f"/documents/{self._config.document_id}",
                expected_status=200,
            )
        )

    def _read_context(self) -> dict[str, object]:
        context = _object(
            self._json_request(
                "GET",
                (
                    f"/documents/{self._config.document_id}"
                    "/narration-playback-context"
                ),
                expected_status=200,
            )
        )
        if (
            _uuid(context.get("document_id")) != self._config.document_id
            or _uuid(context.get("novel_id")) != self._config.novel_id
        ):
            raise RunnerError("DOCUMENT_SCOPE_MISMATCH")
        return context

def build_loopback_transport(config: RunnerConfig) -> LoopbackHttpTransport:
    """Explicit transport factory for a future fixed real-run launcher."""

    return LoopbackHttpTransport(config.api_base)


def build_real_executor_factory(
    *,
    transport_factory: TransportFactory | None,
    browser_probe_factory: BrowserProbeFactory | None,
    runtime_audit_probe_factory: RuntimeAuditProbeFactory | None,
    partial_ready_coordinator: PartialReadyValidationCoordinator | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    request_timeout_seconds: float = 30.0,
    workflow_timeout_seconds: float = 1800.0,
    poll_interval_seconds: float = 0.5,
) -> ExecutorFactory:
    """Build the only factory shape accepted by ``validate_chapter_e2e.main``."""

    if transport_factory is None:
        raise RunnerError("REAL_HTTP_TRANSPORT_REQUIRED")
    if browser_probe_factory is None:
        raise RunnerError("REAL_BROWSER_PROBE_REQUIRED")
    if runtime_audit_probe_factory is None:
        raise RunnerError("REAL_RUNTIME_AUDIT_PROBE_REQUIRED")

    def factory(config: RunnerConfig) -> RealChapterE2EExecutor:
        return RealChapterE2EExecutor(
            config,
            transport=transport_factory(config),
            browser_probe=browser_probe_factory(config),
            runtime_audit_probe=runtime_audit_probe_factory(config),
            partial_ready_coordinator=partial_ready_coordinator,
            monotonic=monotonic,
            sleeper=sleeper,
            request_timeout_seconds=request_timeout_seconds,
            workflow_timeout_seconds=workflow_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    return factory


def build_real_recovery_executor_factory(
    *,
    transport_factory: TransportFactory | None,
    request_timeout_seconds: float = 30.0,
) -> RecoveryExecutorFactory:
    """Build the fixed restore-only factory accepted by validator resume."""

    if transport_factory is None:
        raise RunnerError("REAL_HTTP_TRANSPORT_REQUIRED")

    def factory(config: RunnerConfig) -> RealChapterE2ERecoveryExecutor:
        return RealChapterE2ERecoveryExecutor(
            config,
            transport=transport_factory(config),
            request_timeout_seconds=request_timeout_seconds,
        )

    return factory


__all__ = [
    "BrowserProbe",
    "BrowserProbeFactory",
    "BrowserManifestObservation",
    "BrowserTechnicalEvidence",
    "ChainAuditEvidence",
    "HttpResponse",
    "HttpTransport",
    "LoopbackHttpTransport",
    "PartialReadyValidationCoordinator",
    "PartialReadyValidationEvidence",
    "RealChapterE2EExecutor",
    "RealChapterE2ERecoveryExecutor",
    "RuntimeAuditProbe",
    "RuntimeAuditProbeFactory",
    "RuntimePreflightEvidence",
    "RuntimeTechnicalEvidence",
    "TechnicalProbeContext",
    "TransportFactory",
    "ValidationClaimGateEvidence",
    "build_loopback_transport",
    "build_real_executor_factory",
    "build_real_recovery_executor_factory",
    "verify_t4k_hidden_release_gate",
]
