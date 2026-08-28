#!/usr/bin/env python3
"""Prepare the dedicated T4-K-D chapter data through the hidden HTTP API.

This client is intentionally narrow.  It only connects to the fixed loopback
QwenPaw endpoint, only sends the T4-K-D allowlisted requests, and reads the
validation credential with the existing owner-only token reader.  The first
run creates and probes three official-preset previews.  Locking voices,
binding characters, changing narration settings, and starting the baseline
chapter require an explicit second-run quality confirmation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Callable, Final, Mapping, Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import RFC_4122, UUID


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.narration.official_presets import (  # noqa: E402
    OFFICIAL_PRESET_MAX_NEW_FRAMES,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
    OFFICIAL_PRESET_SAMPLE_MODE,
    PRODUCT_OFFICIAL_PRESET_IDS,
    official_preset_version_fingerprint,
)
from scripts.tts.provision_validation_token import (  # noqa: E402
    TokenProvisionError,
    read_private_host_token,
)


FIXED_HOST: Final = "127.0.0.1"
FIXED_PORT: Final = 18088
FIXED_API_PREFIX: Final = "/api/ai-novel-world-2026"
VALIDATION_HEADER: Final = "X-AI-Novel-TTS-Validation"
QUALITY_CONFIRMATION: Final = "T4-K-OFFICIAL-PRESETS-HEARD-AND-ACCEPTED"
DEFAULT_PRESETS: Final = (
    "onnx.Zhiming",
    "onnx.Xiaoyu",
    "onnx.Junhao",
)
_UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_TERMINAL_REQUEST_STATES: Final = frozenset(
    {"ready", "review_required", "cancelled", "failed"}
)
_TERMINAL_PREVIEW_STATES: Final = frozenset(
    {"ready", "failed", "cancelled", "unavailable"}
)
MAX_LISTENING_SAMPLE_BYTES: Final = 16 * 1024 * 1024


class T4KDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover - argparse owns text
        del message
        raise T4KDataError("ARGUMENTS_INVALID")


@dataclass(frozen=True, slots=True)
class T4KScope:
    novel_id: UUID
    document_id: UUID
    lin_wan_character_id: UUID
    shen_chuan_character_id: UUID


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        maximum_bytes: int,
    ) -> HttpResult: ...


class FixedLoopbackTransport:
    """No-redirect transport whose network authority is not configurable."""

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        maximum_bytes: int,
    ) -> HttpResult:
        connection = http.client.HTTPConnection(FIXED_HOST, FIXED_PORT, timeout=30)
        try:
            connection.request(method, f"{FIXED_API_PREFIX}{path}", body=body, headers=dict(headers))
            response = connection.getresponse()
            raw = response.read(maximum_bytes + 1)
            if len(raw) > maximum_bytes:
                raise T4KDataError("HTTP_RESPONSE_TOO_LARGE")
            return HttpResult(
                status=response.status,
                headers={key.lower(): value for key, value in response.getheaders()},
                body=raw,
            )
        except T4KDataError:
            raise
        except (OSError, http.client.HTTPException) as error:
            raise T4KDataError("LOOPBACK_HTTP_UNAVAILABLE") from error
        finally:
            connection.close()


def _canonical_uuid(value: str, code: str) -> UUID:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as error:
        raise T4KDataError(code) from error
    if (
        str(parsed) != value
        or parsed.variant != RFC_4122
        or parsed.version not in {1, 2, 3, 4, 5}
    ):
        raise T4KDataError(code)
    return parsed


def _required_mapping(value: object, code: str) -> dict[str, object]:
    if type(value) is not dict:
        raise T4KDataError(code)
    return value


def _required_string(mapping: Mapping[str, object], key: str, code: str) -> str:
    value = mapping.get(key)
    if type(value) is not str or not value:
        raise T4KDataError(code)
    return value


def _required_int(mapping: Mapping[str, object], key: str, code: str) -> int:
    value = mapping.get(key)
    if type(value) is not int or value < 0:
        raise T4KDataError(code)
    return value


def _idempotency_key(label: str, *parts: object) -> str:
    canonical = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(canonical.encode("utf-8", errors="strict")).hexdigest()
    return f"t4kd:{label}:{digest[:40]}"


class T4KDataClient:
    def __init__(
        self,
        scope: T4KScope,
        token: str,
        *,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.scope = scope
        self._token = token
        self._transport = transport or FixedLoopbackTransport()
        self._sleep = sleep

    def _validate_route(self, method: str, path: str) -> None:
        if method not in {"GET", "POST", "PUT"}:
            raise T4KDataError("HTTP_METHOD_NOT_ALLOWED")
        split = urlsplit(path)
        if split.scheme or split.netloc or split.fragment or not split.path.startswith("/"):
            raise T4KDataError("HTTP_ROUTE_NOT_ALLOWED")
        novel = str(self.scope.novel_id)
        document = str(self.scope.document_id)
        query = parse_qsl(split.query, keep_blank_values=True, strict_parsing=True)
        voice_route = bool(
            re.fullmatch(r"/voice-presets", split.path)
            or re.fullmatch(rf"/voice-profiles(?:/{_UUID_PATH}(?:/versions/preset|/previews|/lock)?)?", split.path)
            or re.fullmatch(rf"/voice-previews/{_UUID_PATH}", split.path)
        )
        if voice_route and query != [("novel_id", novel)]:
            raise T4KDataError("VOICE_ROUTE_SCOPE_REQUIRED")

        allowed: set[tuple[str, str]] = {
            ("GET", "/voice-presets"),
            ("GET", "/voice-profiles"),
            ("POST", "/voice-profiles"),
            ("GET", f"/novels/{novel}/narration-settings"),
            ("PUT", f"/novels/{novel}/narration-settings"),
            ("POST", f"/documents/{document}/narration-requests"),
            ("GET", f"/documents/{document}/narration-playback-context"),
            ("PUT", f"/documents/{document}/current-narration-edition"),
        }
        for character_id in (
            self.scope.lin_wan_character_id,
            self.scope.shen_chuan_character_id,
        ):
            allowed.add(
                (
                    "GET",
                    f"/novels/{novel}/characters/{character_id}/voice-binding",
                )
            )
            allowed.add(
                (
                    "PUT",
                    f"/novels/{novel}/characters/{character_id}/voice-binding",
                )
            )
        if (method, split.path) in allowed:
            if not voice_route and query:
                raise T4KDataError("HTTP_ROUTE_NOT_ALLOWED")
            return
        dynamic_patterns = (
            ("GET", rf"/voice-profiles/{_UUID_PATH}"),
            ("POST", rf"/voice-profiles/{_UUID_PATH}/versions/preset"),
            ("POST", rf"/voice-profiles/{_UUID_PATH}/previews"),
            ("POST", rf"/voice-profiles/{_UUID_PATH}/lock"),
            ("GET", rf"/voice-previews/{_UUID_PATH}"),
            ("GET", rf"/media-assets/{_UUID_PATH}/content"),
            ("GET", rf"/narration-requests/{_UUID_PATH}"),
            ("GET", rf"/narration-editions/{_UUID_PATH}/manifest"),
        )
        if not any(method == expected and re.fullmatch(pattern, split.path) for expected, pattern in dynamic_patterns):
            raise T4KDataError("HTTP_ROUTE_NOT_ALLOWED")
        if not voice_route:
            if re.fullmatch(rf"/narration-editions/{_UUID_PATH}/manifest", split.path):
                if len(query) != 1 or query[0][0] != "manifest_revision" or not query[0][1].isdigit():
                    raise T4KDataError("HTTP_ROUTE_NOT_ALLOWED")
            elif query:
                raise T4KDataError("HTTP_ROUTE_NOT_ALLOWED")

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        preview_id: UUID | None = None,
        media_probe: bool = False,
    ) -> dict[str, object] | HttpResult:
        self._validate_route(method, path)
        headers: dict[str, str] = {VALIDATION_HEADER: self._token}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        if preview_id is not None:
            headers["X-Narration-Voice-Preview-Id"] = str(preview_id)
        if media_probe:
            headers["Range"] = "bytes=0-0"
        if sum(key.lower() == VALIDATION_HEADER.lower() for key in headers) != 1:
            raise T4KDataError("VALIDATION_HEADER_POLICY_VIOLATION")
        result = self._transport.request(
            method,
            path,
            headers=headers,
            body=body,
            maximum_bytes=1 if media_probe else 4 * 1024 * 1024,
        )
        if media_probe:
            if result.status not in {200, 206} or len(result.body) != 1:
                raise T4KDataError(f"MEDIA_PROBE_HTTP_{result.status}")
            return result
        if result.status < 200 or result.status >= 300:
            raise T4KDataError(f"HTTP_STATUS_{result.status}")
        try:
            decoded = json.loads(result.body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise T4KDataError("HTTP_JSON_INVALID") from error
        return _required_mapping(decoded, "HTTP_JSON_INVALID")

    def _voice_path(self, path: str) -> str:
        return f"{path}?{urlencode({'novel_id': str(self.scope.novel_id)})}"

    def _download_preview_media(self, asset_id: UUID, preview_id: UUID) -> bytes:
        path = f"/media-assets/{asset_id}/content"
        self._validate_route("GET", path)
        result = self._transport.request(
            "GET",
            path,
            headers={
                VALIDATION_HEADER: self._token,
                "X-Narration-Voice-Preview-Id": str(preview_id),
            },
            body=None,
            maximum_bytes=MAX_LISTENING_SAMPLE_BYTES,
        )
        content_type = result.headers.get("content-type", "").split(";", 1)[0]
        content_length = result.headers.get("content-length", "")
        digest = hashlib.sha256(result.body).hexdigest()
        if (
            result.status != 200
            or content_type != "audio/wav"
            or result.headers.get("accept-ranges") != "bytes"
            or not content_length.isdigit()
            or int(content_length) != len(result.body)
            or result.headers.get("etag") != f'"{digest}"'
            or not result.body.startswith(b"RIFF")
            or result.body[8:12] != b"WAVE"
        ):
            raise T4KDataError("LISTENING_SAMPLE_INVALID")
        return result.body

    def write_listening_samples(
        self,
        voices: Mapping[str, object],
        destination: Path,
    ) -> tuple[str, ...]:
        roles = ("narrator", "lin_wan", "shen_chuan")
        if type(voices) is not dict or set(voices) != set(roles):
            raise T4KDataError("LISTENING_SAMPLE_INPUT_INVALID")
        destination.mkdir(mode=0o700, parents=False, exist_ok=True)
        details = os.lstat(destination)
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise T4KDataError("LISTENING_SAMPLE_DIRECTORY_INVALID")
        written: list[str] = []
        for role in roles:
            values = _required_mapping(
                voices.get(role), "LISTENING_SAMPLE_INPUT_INVALID"
            )
            asset_id = _canonical_uuid(
                _required_string(values, "asset_id", "LISTENING_SAMPLE_INPUT_INVALID"),
                "LISTENING_SAMPLE_INPUT_INVALID",
            )
            preview_id = _canonical_uuid(
                _required_string(
                    values, "preview_id", "LISTENING_SAMPLE_INPUT_INVALID"
                ),
                "LISTENING_SAMPLE_INPUT_INVALID",
            )
            payload = self._download_preview_media(asset_id, preview_id)
            target = destination / f"{role}.wav"
            temporary = destination / f".{role}.{preview_id}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    descriptor = -1
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                os.chmod(target, 0o600, follow_symlinks=False)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                temporary.unlink(missing_ok=True)
            written.append(target.name)
        return tuple(written)

    def _catalog(self, selected: Sequence[str]) -> None:
        payload = self._request("GET", self._voice_path("/voice-presets"))
        assert isinstance(payload, dict)
        items = payload.get("items")
        if type(items) is not list:
            raise T4KDataError("OFFICIAL_PRESET_CATALOG_INVALID")
        catalog: dict[str, Mapping[str, object]] = {}
        for raw in items:
            if type(raw) is not dict:
                raise T4KDataError("OFFICIAL_PRESET_CATALOG_INVALID")
            preset_id = raw.get("preset_id")
            if type(preset_id) is not str or preset_id in catalog:
                raise T4KDataError("OFFICIAL_PRESET_CATALOG_INVALID")
            catalog[preset_id] = raw
        if tuple(catalog) != PRODUCT_OFFICIAL_PRESET_IDS:
            raise T4KDataError("OFFICIAL_PRESET_CATALOG_INVALID")
        for preset_id in selected:
            item = catalog.get(preset_id)
            provenance = item.get("provenance") if item is not None else None
            if (
                type(item) is not dict
                or item.get("local_use_status") != "available"
                or type(provenance) is not dict
                or provenance.get("preset_id") != preset_id
                or provenance.get("model_fingerprint_sha256")
                != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
            ):
                raise T4KDataError("OFFICIAL_PRESET_CATALOG_INVALID")

    def _profile_list(self) -> list[dict[str, object]]:
        payload = self._request("GET", self._voice_path("/voice-profiles"))
        assert isinstance(payload, dict)
        items = payload.get("items")
        if type(items) is not list or any(type(item) is not dict for item in items):
            raise T4KDataError("VOICE_PROFILE_LIST_INVALID")
        return items

    def _get_or_create_profile(
        self,
        *,
        name: str,
        existing: Sequence[dict[str, object]],
    ) -> dict[str, object]:
        matches = [
            item
            for item in existing
            if item.get("name") == name
            and item.get("novel_id") == str(self.scope.novel_id)
            and item.get("status") != "archived"
        ]
        if len(matches) > 1:
            raise T4KDataError("VOICE_PROFILE_AMBIGUOUS")
        if matches:
            profile_id = _canonical_uuid(
                _required_string(matches[0], "profile_id", "VOICE_PROFILE_INVALID"),
                "VOICE_PROFILE_INVALID",
            )
            result = self._request(
                "GET", self._voice_path(f"/voice-profiles/{profile_id}")
            )
            assert isinstance(result, dict)
            return result
        result = self._request(
            "POST",
            self._voice_path("/voice-profiles"),
            payload={"novel_id": str(self.scope.novel_id), "name": name},
            idempotency_key=_idempotency_key("profile", self.scope.novel_id, name),
        )
        assert isinstance(result, dict)
        return result

    def _get_or_create_version(
        self, profile: dict[str, object], preset_id: str
    ) -> dict[str, object]:
        versions = profile.get("versions")
        if type(versions) is not list or any(type(item) is not dict for item in versions):
            raise T4KDataError("VOICE_PROFILE_INVALID")
        profile_id = _canonical_uuid(
            _required_string(profile, "profile_id", "VOICE_PROFILE_INVALID"),
            "VOICE_PROFILE_INVALID",
        )
        matches: list[dict[str, object]] = []
        for item in versions:
            if not (
                item.get("source_type") == "preset"
                and item.get("preset_key") == preset_id
                and isinstance(item.get("official_preset"), dict)
                and item["official_preset"].get("preset_id") == preset_id
            ):
                continue
            try:
                version_id = _canonical_uuid(
                    _required_string(item, "version_id", "VOICE_VERSION_INVALID"),
                    "VOICE_VERSION_INVALID",
                )
                expected_fingerprint = official_preset_version_fingerprint(
                    profile_id=profile_id,
                    version_id=version_id,
                    preset_id=preset_id,
                )
            except (T4KDataError, TypeError, ValueError):
                continue
            if item.get("fingerprint") == expected_fingerprint:
                matches.append(item)
        if len(matches) > 1:
            raise T4KDataError("VOICE_VERSION_AMBIGUOUS")
        if matches:
            return matches[0]
        expected = _required_int(profile, "version", "VOICE_PROFILE_INVALID")
        result = self._request(
            "POST",
            self._voice_path(f"/voice-profiles/{profile_id}/versions/preset"),
            payload={
                "expected_profile_version": expected,
                "preset_id": preset_id,
            },
            idempotency_key=_idempotency_key(
                "preset-version-official-default-v1",
                self.scope.novel_id,
                profile_id,
                preset_id,
                OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
                OFFICIAL_PRESET_SAMPLE_MODE,
                OFFICIAL_PRESET_MAX_NEW_FRAMES,
            ),
        )
        assert isinstance(result, dict)
        result_version_id = _canonical_uuid(
            _required_string(result, "version_id", "VOICE_VERSION_INVALID"),
            "VOICE_VERSION_INVALID",
        )
        if result.get("fingerprint") != official_preset_version_fingerprint(
            profile_id=profile_id,
            version_id=result_version_id,
            preset_id=preset_id,
        ):
            raise T4KDataError("VOICE_VERSION_DEFAULTS_MISMATCH")
        return result

    def _ready_preview(
        self,
        *,
        profile_id: UUID,
        version_id: UUID,
        preview_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            self._voice_path(f"/voice-profiles/{profile_id}/previews"),
            payload={"version_id": str(version_id), "preview_text": preview_text},
            idempotency_key=_idempotency_key(
                "preview-v2",
                self.scope.novel_id,
                profile_id,
                version_id,
                preview_text,
            ),
        )
        assert isinstance(result, dict)
        preview_id = _canonical_uuid(
            _required_string(result, "preview_id", "VOICE_PREVIEW_INVALID"),
            "VOICE_PREVIEW_INVALID",
        )
        deadline = time.monotonic() + timeout_seconds
        while result.get("status") not in _TERMINAL_PREVIEW_STATES:
            if time.monotonic() >= deadline:
                raise T4KDataError("VOICE_PREVIEW_TIMEOUT")
            self._sleep(1.0)
            result = self._request(
                "GET", self._voice_path(f"/voice-previews/{preview_id}")
            )
            assert isinstance(result, dict)
        if result.get("status") != "ready":
            raise T4KDataError("VOICE_PREVIEW_NOT_READY")
        asset = result.get("asset")
        if type(asset) is not dict:
            raise T4KDataError("VOICE_PREVIEW_INVALID")
        asset_id = _canonical_uuid(
            _required_string(asset, "asset_id", "VOICE_PREVIEW_INVALID"),
            "VOICE_PREVIEW_INVALID",
        )
        if asset.get("content_path") != f"/media-assets/{asset_id}/content":
            raise T4KDataError("VOICE_PREVIEW_INVALID")
        self._request(
            "GET",
            f"/media-assets/{asset_id}/content",
            preview_id=preview_id,
            media_probe=True,
        )
        return result

    def _lock_profile(
        self, profile_id: UUID, version_id: UUID
    ) -> dict[str, object]:
        current = self._request(
            "GET", self._voice_path(f"/voice-profiles/{profile_id}")
        )
        assert isinstance(current, dict)
        if current.get("current_version_id") == str(version_id):
            versions = current.get("versions")
            if type(versions) is list and any(
                type(item) is dict
                and item.get("version_id") == str(version_id)
                and item.get("state") == "locked"
                for item in versions
            ):
                return current
        expected = _required_int(current, "version", "VOICE_PROFILE_INVALID")
        result = self._request(
            "POST",
            self._voice_path(f"/voice-profiles/{profile_id}/lock"),
            payload={
                "expected_profile_version": expected,
                "version_id": str(version_id),
                "quality_confirmed": True,
            },
        )
        assert isinstance(result, dict)
        return result

    def _bind_character(
        self, character_id: UUID, profile_id: UUID, version_id: UUID
    ) -> dict[str, object]:
        path = f"/novels/{self.scope.novel_id}/characters/{character_id}/voice-binding"
        current = self._request("GET", path)
        assert isinstance(current, dict)
        if (
            current.get("binding_policy") == "dedicated"
            and current.get("profile_id") == str(profile_id)
            and current.get("version_id") == str(version_id)
            and current.get("language") == "zh-CN"
        ):
            return current
        result = self._request(
            "PUT",
            path,
            payload={
                "expected_version": _required_int(
                    current, "version", "VOICE_BINDING_INVALID"
                ),
                "binding_policy": "dedicated",
                "profile_id": str(profile_id),
                "version_id": str(version_id),
                "language": "zh-CN",
            },
        )
        assert isinstance(result, dict)
        return result

    def _set_narrator(self, profile_id: UUID, version_id: UUID) -> dict[str, object]:
        path = f"/novels/{self.scope.novel_id}/narration-settings"
        current = self._request("GET", path)
        assert isinstance(current, dict)
        values = current.get("values")
        if type(values) is not dict:
            raise T4KDataError("NARRATION_SETTINGS_INVALID")
        narrator = {"profile_id": str(profile_id), "version_id": str(version_id)}
        if values.get("narrator") == narrator and current.get("exists") is True:
            return current
        updated_values = dict(values)
        updated_values["narrator"] = narrator
        result = self._request(
            "PUT",
            path,
            payload={
                "expected_version": _required_int(
                    current, "version", "NARRATION_SETTINGS_INVALID"
                ),
                "values": updated_values,
            },
        )
        assert isinstance(result, dict)
        return result

    def _baseline(self, settings_version: int, timeout_seconds: int) -> dict[str, object]:
        context_path = (
            f"/documents/{self.scope.document_id}/narration-playback-context"
        )
        context = self._request("GET", context_path)
        assert isinstance(context, dict)
        if (
            context.get("document_id") != str(self.scope.document_id)
            or context.get("novel_id") != str(self.scope.novel_id)
        ):
            raise T4KDataError("DOCUMENT_CONTEXT_SCOPE_INVALID")
        draft_version = _required_int(
            context, "working_copy_draft_version", "DOCUMENT_CONTEXT_INVALID"
        )
        content_hash = _required_string(
            context, "working_copy_content_hash", "DOCUMENT_CONTEXT_INVALID"
        )
        if not re.fullmatch(r"[a-f0-9]{64}", content_hash):
            raise T4KDataError("DOCUMENT_CONTEXT_INVALID")
        result = self._request(
            "POST",
            f"/documents/{self.scope.document_id}/narration-requests",
            payload={
                "intent": "create",
                "expected_draft_version": draft_version,
                "expected_content_hash": content_hash,
                "expected_settings_version": settings_version,
                "force_review": False,
            },
            idempotency_key=_idempotency_key(
                "baseline",
                self.scope.novel_id,
                self.scope.document_id,
                draft_version,
                content_hash,
                settings_version,
            ),
        )
        assert isinstance(result, dict)
        request_id = _canonical_uuid(
            _required_string(result, "request_id", "NARRATION_REQUEST_INVALID"),
            "NARRATION_REQUEST_INVALID",
        )
        deadline = time.monotonic() + timeout_seconds
        while result.get("workflow_state") not in _TERMINAL_REQUEST_STATES:
            if time.monotonic() >= deadline:
                raise T4KDataError("NARRATION_REQUEST_TIMEOUT")
            self._sleep(1.0)
            result = self._request("GET", f"/narration-requests/{request_id}")
            assert isinstance(result, dict)
        if result.get("workflow_state") != "ready":
            raise T4KDataError("BASELINE_NARRATION_NOT_READY")
        edition_id = _canonical_uuid(
            _required_string(result, "edition_id", "NARRATION_REQUEST_INVALID"),
            "NARRATION_REQUEST_INVALID",
        )
        manifest_revision = _required_int(
            result, "current_manifest_revision", "NARRATION_REQUEST_INVALID"
        )
        if manifest_revision < 1:
            raise T4KDataError("NARRATION_REQUEST_INVALID")
        final_context = self._request("GET", context_path)
        assert isinstance(final_context, dict)
        if (
            final_context.get("document_id") != str(self.scope.document_id)
            or final_context.get("novel_id") != str(self.scope.novel_id)
        ):
            raise T4KDataError("DOCUMENT_CONTEXT_SCOPE_INVALID")
        pointer_version = _required_int(
            final_context, "pointer_version", "DOCUMENT_CONTEXT_INVALID"
        )
        current_edition_id = final_context.get("current_edition_id")
        if current_edition_id is not None:
            if type(current_edition_id) is not str:
                raise T4KDataError("DOCUMENT_CONTEXT_EDITION_INVALID")
            _canonical_uuid(
                current_edition_id, "DOCUMENT_CONTEXT_EDITION_INVALID"
            )
        if current_edition_id != str(edition_id):
            switch_result = self._request(
                "PUT",
                f"/documents/{self.scope.document_id}/current-narration-edition",
                payload={
                    "target_edition_id": str(edition_id),
                    "expected_version": pointer_version,
                    "switch_mode": "next_playback",
                    "start_segment_id": None,
                    "playback_rate_millis": 1000,
                    "confirmed": True,
                },
            )
            assert isinstance(switch_result, dict)
            expected_switch_keys = {
                "contract_version",
                "document_id",
                "current_edition_id",
                "pointer_version",
                "switch_mode",
                "start_segment_id",
                "manifest_revision",
                "playback_progress_id",
            }
            if (
                set(switch_result) != expected_switch_keys
                or switch_result.get("contract_version")
                != "document-narration-context/1"
                or switch_result.get("document_id")
                != str(self.scope.document_id)
                or switch_result.get("current_edition_id") != str(edition_id)
                or switch_result.get("pointer_version") != pointer_version + 1
                or switch_result.get("switch_mode") != "next_playback"
                or switch_result.get("start_segment_id") is not None
                or switch_result.get("manifest_revision") != manifest_revision
                or switch_result.get("playback_progress_id") is not None
            ):
                raise T4KDataError("DOCUMENT_EDITION_SWITCH_INVALID")
            confirmed_context = self._request("GET", context_path)
            assert isinstance(confirmed_context, dict)
            if (
                confirmed_context.get("document_id")
                != str(self.scope.document_id)
                or confirmed_context.get("novel_id") != str(self.scope.novel_id)
            ):
                raise T4KDataError("DOCUMENT_CONTEXT_SCOPE_INVALID")
            if (
                confirmed_context.get("current_edition_id") != str(edition_id)
                or _required_int(
                    confirmed_context,
                    "pointer_version",
                    "DOCUMENT_CONTEXT_INVALID",
                )
                != pointer_version + 1
            ):
                raise T4KDataError("DOCUMENT_CONTEXT_EDITION_INVALID")
        manifest = self._request(
            "GET",
            f"/narration-editions/{edition_id}/manifest?"
            + urlencode({"manifest_revision": manifest_revision}),
        )
        assert isinstance(manifest, dict)
        if (
            manifest.get("edition_id") != str(edition_id)
            or manifest.get("manifest_revision") != manifest_revision
        ):
            raise T4KDataError("NARRATION_MANIFEST_INVALID")
        return {
            "request_id": str(request_id),
            "edition_id": str(edition_id),
            "manifest_revision": manifest_revision,
        }

    def prepare(
        self,
        *,
        presets: Sequence[str] = DEFAULT_PRESETS,
        quality_confirmation: str | None = None,
        timeout_seconds: int = 900,
    ) -> dict[str, object]:
        if (
            len(presets) != 3
            or len(set(presets)) != 3
            or any(preset not in PRODUCT_OFFICIAL_PRESET_IDS for preset in presets)
        ):
            raise T4KDataError("OFFICIAL_PRESETS_INVALID")
        if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 3600:
            raise T4KDataError("POLL_TIMEOUT_INVALID")
        if quality_confirmation not in {None, QUALITY_CONFIRMATION}:
            raise T4KDataError("QUALITY_CONFIRMATION_INVALID")

        self._catalog(presets)
        roles = (
            (
                "narrator",
                "T4-K 专用旁白（official_preset）",
                presets[0],
                (
                    "夜色从城西缓缓漫过来，远处的钟声穿过薄雾，在长街尽头一声声散开。"
                    "林晚推开旧书店的木门，风铃轻轻摇响，尘封多年的纸页气息迎面而来。"
                    "她不知道，柜台后那盏昏黄的灯，将照见一封改变所有人命运的信；"
                    "也不知道沈川已经站在雨幕之外，沉默地等了整整三个小时。"
                    "故事就在这个看似平常的夜晚，悄然转向了无人预料的方向。"
                ),
            ),
            (
                "lin_wan",
                "T4-K 专用林晚（official_preset）",
                presets[1],
                (
                    "沈川，我不是不相信你，只是这些年我已经习惯了独自做决定。"
                    "那封信出现得太突然，每个人都说自己知道真相，可他们看我的眼神，"
                    "又像是在等我犯错。如果你真的愿意陪我查下去，就不要替我选择，"
                    "也不要把危险都藏起来。我要亲眼看见答案，亲口问清当年离开的人。"
                    "等天亮以后，我们一起去旧车站；无论在那里等着我们的是什么，"
                    "这一次我都不会再逃。"
                ),
            ),
            (
                "shen_chuan",
                "T4-K 专用沈川（official_preset）",
                presets[2],
                (
                    "林晚，你先别急着回答我。过去那些误会，我会一件一件查清楚，"
                    "也会把该承担的责任全部承担起来。我今天来，不是要逼你原谅谁，"
                    "更不是想替自己找借口。我只是希望，当危险再次靠近的时候，"
                    "你能相信我一次，把手交给我。无论前面是旧城的暗巷，"
                    "还是所有人都不肯说出的真相，我都会陪你走到最后。"
                    "等一切结束以后，你想去哪里，我就送你去哪里。"
                ),
            ),
        )
        existing = self._profile_list()
        prepared: dict[str, dict[str, object]] = {}
        for role, name, preset_id, preview_text in roles:
            profile = self._get_or_create_profile(name=name, existing=existing)
            profile_id = _canonical_uuid(
                _required_string(profile, "profile_id", "VOICE_PROFILE_INVALID"),
                "VOICE_PROFILE_INVALID",
            )
            version = self._get_or_create_version(profile, preset_id)
            version_id = _canonical_uuid(
                _required_string(version, "version_id", "VOICE_VERSION_INVALID"),
                "VOICE_VERSION_INVALID",
            )
            preview = self._ready_preview(
                profile_id=profile_id,
                version_id=version_id,
                preview_text=preview_text,
                timeout_seconds=timeout_seconds,
            )
            prepared[role] = {
                "preset_id": preset_id,
                "profile_id": str(profile_id),
                "version_id": str(version_id),
                "preview_id": _required_string(
                    preview, "preview_id", "VOICE_PREVIEW_INVALID"
                ),
                "asset_id": _required_string(
                    _required_mapping(
                        preview.get("asset"), "VOICE_PREVIEW_INVALID"
                    ),
                    "asset_id",
                    "VOICE_PREVIEW_INVALID",
                ),
            }

        if quality_confirmation is None:
            return {
                "schema_version": "t4-k-data-preparation/1.0",
                "status": "QUALITY_CONFIRMATION_REQUIRED",
                "quality_confirmation_phrase": QUALITY_CONFIRMATION,
                "voices": prepared,
                "secret_values_emitted": False,
                "request_bodies_emitted": False,
            }

        locked: dict[str, tuple[UUID, UUID]] = {}
        for role, values in prepared.items():
            profile_id = _canonical_uuid(
                str(values["profile_id"]), "VOICE_PROFILE_INVALID"
            )
            version_id = _canonical_uuid(
                str(values["version_id"]), "VOICE_VERSION_INVALID"
            )
            self._lock_profile(profile_id, version_id)
            locked[role] = (profile_id, version_id)

        self._bind_character(
            self.scope.lin_wan_character_id, *locked["lin_wan"]
        )
        self._bind_character(
            self.scope.shen_chuan_character_id, *locked["shen_chuan"]
        )
        settings = self._set_narrator(*locked["narrator"])
        settings_version = _required_int(
            settings, "version", "NARRATION_SETTINGS_INVALID"
        )
        if settings_version < 1:
            raise T4KDataError("NARRATION_SETTINGS_INVALID")
        baseline = self._baseline(settings_version, timeout_seconds)
        return {
            "schema_version": "t4-k-data-preparation/1.0",
            "status": "BASELINE_READY",
            "voices": prepared,
            "settings_version": settings_version,
            "baseline": baseline,
            "quality_confirmation_recorded": True,
            "secret_values_emitted": False,
            "request_bodies_emitted": False,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--lin-wan-character-id", required=True)
    parser.add_argument("--shen-chuan-character-id", required=True)
    choices = PRODUCT_OFFICIAL_PRESET_IDS
    parser.add_argument("--narrator-preset", choices=choices, default=DEFAULT_PRESETS[0])
    parser.add_argument("--lin-wan-preset", choices=choices, default=DEFAULT_PRESETS[1])
    parser.add_argument("--shen-chuan-preset", choices=choices, default=DEFAULT_PRESETS[2])
    parser.add_argument("--poll-timeout-seconds", type=int, default=900)
    parser.add_argument("--write-listening-samples", action="store_true")
    parser.add_argument("--confirm-quality-after-listening")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        scope = T4KScope(
            novel_id=_canonical_uuid(args.novel_id, "NOVEL_ID_INVALID"),
            document_id=_canonical_uuid(args.document_id, "DOCUMENT_ID_INVALID"),
            lin_wan_character_id=_canonical_uuid(
                args.lin_wan_character_id, "LIN_WAN_CHARACTER_ID_INVALID"
            ),
            shen_chuan_character_id=_canonical_uuid(
                args.shen_chuan_character_id, "SHEN_CHUAN_CHARACTER_ID_INVALID"
            ),
        )
        if scope.lin_wan_character_id == scope.shen_chuan_character_id:
            raise T4KDataError("CHARACTER_IDS_MUST_BE_DISTINCT")
        try:
            token = read_private_host_token(args.token_file)
        except TokenProvisionError as error:
            raise T4KDataError("VALIDATION_TOKEN_FILE_INVALID") from error
        client = T4KDataClient(scope, token)
        result = client.prepare(
            presets=(
                args.narrator_preset,
                args.lin_wan_preset,
                args.shen_chuan_preset,
            ),
            quality_confirmation=args.confirm_quality_after_listening,
            timeout_seconds=args.poll_timeout_seconds,
        )
        if args.write_listening_samples:
            client.write_listening_samples(
                _required_mapping(result.get("voices"), "LISTENING_SAMPLE_INPUT_INVALID"),
                args.token_file.resolve().parent / "t4-k-listening-samples",
            )
            result["listening_sample_files"] = [
                "narrator.wav",
                "lin_wan.wav",
                "shen_chuan.wav",
            ]
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        return 0 if result["status"] == "BASELINE_READY" else 2
    except T4KDataError as error:
        print(error.code, file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
