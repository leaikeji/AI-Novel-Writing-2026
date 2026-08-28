"""Canonical JSON and SHA-256 helpers for narration fingerprints."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping
from uuid import UUID

from .contracts import (
    AdapterCapabilities,
    EDITION_FINGERPRINT_SCHEMA_VERSION,
    MODEL_FINGERPRINT_SCHEMA_VERSION,
    ModelFingerprint,
    NARRATION_SCOPE_CONTRACT_VERSION,
    NarrationRequestScope,
    RENDER_FINGERPRINT_SCHEMA_VERSION,
)

ADAPTER_CAPABILITIES_FINGERPRINT_SCHEMA_VERSION: Final = (
    "narration-adapter-capabilities-fingerprint/1"
)

SUPPORTED_FINGERPRINT_SCHEMA_VERSIONS: Final = frozenset(
    {
        NARRATION_SCOPE_CONTRACT_VERSION,
        MODEL_FINGERPRINT_SCHEMA_VERSION,
        EDITION_FINGERPRINT_SCHEMA_VERSION,
        RENDER_FINGERPRINT_SCHEMA_VERSION,
        ADAPTER_CAPABILITIES_FINGERPRINT_SCHEMA_VERSION,
    }
)


class FingerprintContractError(ValueError):
    """Raised for non-canonical or unknown fingerprint input."""


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a strict, stable JSON subset.

    Strings and mapping keys use Unicode NFC. Floats and bytes are rejected so
    callers must choose explicit integer/fixed-point and digest representations.
    """

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_fingerprint(schema_version: str, payload: Any) -> str:
    if schema_version not in SUPPORTED_FINGERPRINT_SCHEMA_VERSIONS:
        raise FingerprintContractError(
            f"unknown fingerprint schema version: {schema_version}"
        )
    envelope = {"schema_version": schema_version, "payload": payload}
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def scope_fingerprint(scope: NarrationRequestScope) -> str:
    scope.ensure_fixed_local()
    return canonical_fingerprint(
        NARRATION_SCOPE_CONTRACT_VERSION,
        {
            "owner_id": str(scope.owner_id),
            "workspace_id": str(scope.workspace_id),
            "app_id": scope.app_id,
            "is_local_only": scope.is_local_only,
        },
    )


def model_fingerprint_sha256(fingerprint: ModelFingerprint) -> str:
    payload = {
        "adapter_contract_version": fingerprint.adapter_contract_version,
        "model_name": fingerprint.model_name,
        "model_revision": fingerprint.model_revision,
        "artifact_tree_sha256": fingerprint.artifact_tree_sha256,
        "runtime_name": fingerprint.runtime_name,
        "runtime_version": fingerprint.runtime_version,
        "execution_backend": fingerprint.execution_backend,
        "protocol_version": fingerprint.protocol_version,
        "deployment_topology": fingerprint.deployment_topology,
        "parameters": fingerprint.parameters,
    }
    return canonical_fingerprint(MODEL_FINGERPRINT_SCHEMA_VERSION, payload)


def capabilities_fingerprint(capabilities: AdapterCapabilities) -> str:
    return canonical_fingerprint(
        ADAPTER_CAPABILITIES_FINGERPRINT_SCHEMA_VERSION,
        asdict(capabilities),
    )


def edition_fingerprint(payload: Mapping[str, Any]) -> str:
    return canonical_fingerprint(EDITION_FINGERPRINT_SCHEMA_VERSION, payload)


def render_fingerprint(payload: Mapping[str, Any]) -> str:
    return canonical_fingerprint(RENDER_FINGERPRINT_SCHEMA_VERSION, payload)


def readonly_payload(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a shallow immutable copy for exported fingerprint inputs."""

    return MappingProxyType(dict(value))


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise FingerprintContractError(
            "floats are not canonical fingerprint inputs; use integer/fixed-point values"
        )
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bytes):
        raise FingerprintContractError(
            "bytes are not fingerprint inputs; use a verified lowercase SHA-256"
        )
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise FingerprintContractError("fingerprint mapping keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in result:
                raise FingerprintContractError(
                    "fingerprint mapping has duplicate keys after Unicode normalization"
                )
            result[key] = _normalize(raw_value)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    raise FingerprintContractError(
        f"unsupported fingerprint value type: {type(value).__name__}"
    )
