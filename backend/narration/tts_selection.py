"""Small, deterministic bridge from frozen settings to Qwen TTS execution."""

from __future__ import annotations

import hashlib
from typing import Mapping

from pydantic import ValidationError

from . import schemas as wire
from .fingerprints import canonical_json_bytes


TTS_SELECTION_FINGERPRINT_VERSION = "qwen-tts-selection/1"
TTS_TOKENIZER_FINGERPRINT_VERSION = "qwen-tts-provider-tokenizer/1"


def selection_from_settings_snapshot(
    snapshot_json: Mapping[str, object],
) -> wire.TTSProviderSelection:
    """Read the immutable request selection; older snapshots default to local."""

    resolved = snapshot_json.get("resolved_settings")
    if not isinstance(resolved, Mapping):
        raise ValueError("narration settings snapshot has no resolved settings")
    settings = resolved.get("settings")
    if not isinstance(settings, Mapping):
        raise ValueError("narration settings snapshot has no settings payload")
    raw = settings.get("tts_provider", {})
    try:
        return wire.TTSProviderSelection.model_validate(raw)
    except ValidationError as error:
        raise ValueError("narration TTS Provider selection is invalid") from error


def selection_fingerprint(selection: wire.TTSProviderSelection) -> str:
    """Fingerprint the exact Provider/channel/model frozen for synthesis."""

    if type(selection) is not wire.TTSProviderSelection:
        raise TypeError("selection must use the TTS Provider wire contract")
    active_model_id = (
        selection.aliyun_model_id
        if selection.provider_id == "aliyun_qwen_audio_tts"
        else None
    )
    payload: dict[str, object] = {
        "schema_version": TTS_SELECTION_FINGERPRINT_VERSION,
        "provider_id": selection.provider_id,
        "model_id": active_model_id,
    }
    if selection.cloud_profile_id is not None:
        payload.update(
            {
                "cloud_profile_id": str(selection.cloud_profile_id),
                "cloud_profile_version": selection.cloud_profile_version,
                "cloud_protocol": selection.cloud_protocol,
                "cloud_actual_model_id": selection.cloud_actual_model_id,
                "cloud_base_url_fingerprint": selection.cloud_base_url_fingerprint,
                "cloud_verification_fingerprint": (
                    selection.cloud_verification_fingerprint
                ),
            }
        )
    return hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()


def tokenizer_fingerprint(selection: wire.TTSProviderSelection) -> str:
    """Fence Provider-owned tokenization without exposing its implementation."""

    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema_version": TTS_TOKENIZER_FINGERPRINT_VERSION,
                "selection_fingerprint": selection_fingerprint(selection),
                "tokenization": "provider_owned",
            }
        )
    ).hexdigest()


__all__ = [
    "TTS_SELECTION_FINGERPRINT_VERSION",
    "TTS_TOKENIZER_FINGERPRINT_VERSION",
    "selection_fingerprint",
    "selection_from_settings_snapshot",
    "tokenizer_fingerprint",
]
