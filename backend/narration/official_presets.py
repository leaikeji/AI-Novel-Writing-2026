"""Pinned, provider-aware Qwen TTS voices used by the lightweight selector.

Every logical voice pins one official local Qwen3-TTS speaker.  Cloud mappings
are deliberately sparse: only mappings verified by product policy are
published, and their presence does not claim acoustic equivalence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Final, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5


OFFICIAL_PRESET_REPOSITORY: Final = (
    "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
)
OFFICIAL_PRESET_REVISION: Final = "41d3337e8b7f2843a75841595fc14e4b9a7a4b96"
OFFICIAL_PRESET_MANIFEST_PATH: Final = "qwen-provider-voice-map/1"
OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256: Final = (
    "728e8b60b4cdb195a1379faf033b428bf93feaceccbdcf3c3a4bd3a6698b4fb6"
)
OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION: Final = "qwen-tts-preset-provenance/1"
OFFICIAL_PRESET_VERSION_SCHEMA_VERSION: Final = "qwen-tts-voice/1"
OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION: Final = "qwen-tts-voice/1"
OFFICIAL_PRESET_IDENTITY_CONTRACT_VERSION: Final = "qwen-tts-preset-identity/1"
OFFICIAL_PRESET_DIRECT_VERSION_IDENTITY_CONTRACT_VERSION: Final = (
    "qwen-tts-preset-direct-version/1"
)
OFFICIAL_PRESET_PREVIEW_VERSION_IDENTITY_CONTRACT_VERSION: Final = (
    "qwen-tts-preset-preview-version/1"
)
OFFICIAL_PRESET_DIRECT_VERSION_FINGERPRINT_SCHEMA_VERSION: Final = (
    "qwen-tts-preset-direct-fingerprint/1"
)
OFFICIAL_PRESET_RIGHTS_POLICY_VERSION: Final = "qwen-tts-built-in-voice-use/1"
OFFICIAL_PRESET_SAMPLE_MODE: Final = "provider_default"
OFFICIAL_PRESET_MAX_NEW_FRAMES: Final = 0
OFFICIAL_PRESET_RUNTIME_INITIAL_SEED: Final = 1234
OFFICIAL_PRESET_IDENTITY_NAMESPACE: Final = uuid5(
    NAMESPACE_URL,
    "https://ai-novel-world-2026.local/voice/qwen-preset",
)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class OfficialPreset:
    preset_id: str
    display_name: str
    group: str
    language: str
    official_speaker: str
    native_language: str
    dialect: str | None
    local_voice_id: str
    description: str
    aliyun_plus_voice_id: str | None = None
    aliyun_flash_voice_id: str | None = None

    @property
    def provider_voice_ids(self) -> dict[str, str]:
        mappings = {"local_qwen3_tts": self.local_voice_id}
        if self.aliyun_plus_voice_id is not None:
            mappings["aliyun_qwen_audio_tts:qwen-audio-3.0-tts-plus"] = (
                self.aliyun_plus_voice_id
            )
        if self.aliyun_flash_voice_id is not None:
            mappings["aliyun_qwen_audio_tts:qwen-audio-3.0-tts-flash"] = (
                self.aliyun_flash_voice_id
            )
        return mappings

    def provenance_without_fingerprint(self) -> dict[str, object]:
        return {
            "schema_version": OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION,
            "catalog_id": OFFICIAL_PRESET_MANIFEST_PATH,
            "preset_id": self.preset_id,
            "local_model_id": OFFICIAL_PRESET_REPOSITORY,
            "local_model_revision": OFFICIAL_PRESET_REVISION,
            "provider_voice_ids": self.provider_voice_ids,
            "model_fingerprint_sha256": OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        }

    def provenance(self) -> dict[str, object]:
        value = self.provenance_without_fingerprint()
        return {**value, "provenance_fingerprint_sha256": canonical_sha256(value)}


# Product IDs and ordering are a public catalog contract.  The two legacy
# entries retain their old language, Provider maps, and provenance bytes.
OFFICIAL_PRESETS: Final[tuple[OfficialPreset, ...]] = (
    OfficialPreset(
        preset_id="qwen.WarmFemale",
        display_name="温暖女声",
        group="中文女声",
        language="zh-CN",
        official_speaker="Serena",
        native_language="zh-CN",
        dialect=None,
        local_voice_id="Serena",
        aliyun_plus_voice_id="longanlingxin",
        aliyun_flash_voice_id="longanhuan_v3.6",
        description="温暖、自然，适合旁白与日常对话。",
    ),
    OfficialPreset(
        preset_id="qwen.Vivian",
        display_name="Vivian｜明亮年轻女声",
        group="中文女声",
        language="zh-CN",
        official_speaker="Vivian",
        native_language="zh-CN",
        dialect=None,
        local_voice_id="Vivian",
        description="明亮、年轻的中文女声。",
    ),
    OfficialPreset(
        preset_id="qwen.UncleFu",
        display_name="Uncle_Fu｜成熟低沉男声",
        group="中文男声",
        language="zh-CN",
        official_speaker="Uncle_Fu",
        native_language="zh-CN",
        dialect=None,
        local_voice_id="Uncle_Fu",
        description="成熟、低沉的中文男声。",
    ),
    OfficialPreset(
        preset_id="qwen.Dylan",
        display_name="Dylan｜北京口音年轻男声",
        group="中文男声",
        language="zh-CN",
        official_speaker="Dylan",
        native_language="zh-CN",
        dialect="北京口音",
        local_voice_id="Dylan",
        description="带北京口音的年轻中文男声。",
    ),
    OfficialPreset(
        preset_id="qwen.Eric",
        display_name="Eric｜四川口音男声",
        group="中文男声",
        language="zh-CN",
        official_speaker="Eric",
        native_language="zh-CN",
        dialect="四川口音",
        local_voice_id="Eric",
        description="带四川口音的中文男声。",
    ),
    OfficialPreset(
        preset_id="qwen.ClearMale",
        display_name="明亮男声",
        group="中文男声",
        language="zh-CN",
        official_speaker="Aiden",
        native_language="en",
        dialect=None,
        local_voice_id="Aiden",
        aliyun_plus_voice_id="longanlufeng",
        aliyun_flash_voice_id="loongjohn",
        description="清晰、明亮，适合旁白与青年角色。",
    ),
    OfficialPreset(
        preset_id="qwen.Ryan",
        display_name="Ryan｜节奏感男声",
        group="英语男声",
        language="en",
        official_speaker="Ryan",
        native_language="en",
        dialect=None,
        local_voice_id="Ryan",
        description="富有节奏感的英语男声。",
    ),
    OfficialPreset(
        preset_id="qwen.OnoAnna",
        display_name="Ono_Anna｜轻快女声",
        group="日语女声",
        language="ja-JP",
        official_speaker="Ono_Anna",
        native_language="ja-JP",
        dialect=None,
        local_voice_id="Ono_Anna",
        description="轻快的日语女声。",
    ),
    OfficialPreset(
        preset_id="qwen.Sohee",
        display_name="Sohee｜温暖女声",
        group="韩语女声",
        language="ko-KR",
        official_speaker="Sohee",
        native_language="ko-KR",
        dialect=None,
        local_voice_id="Sohee",
        description="温暖的韩语女声。",
    ),
)
OFFICIAL_PRESETS_BY_ID: Final[Mapping[str, OfficialPreset]] = {
    item.preset_id: item for item in OFFICIAL_PRESETS
}
OFFICIAL_PRESET_IDS: Final[tuple[str, ...]] = tuple(
    item.preset_id for item in OFFICIAL_PRESETS
)
CANONICAL_CHAPTER_VERIFIED_PRESET_IDS: Final[frozenset[str]] = frozenset(
    {"qwen.WarmFemale", "qwen.ClearMale"}
)


def require_official_preset(preset_id: str) -> OfficialPreset:
    try:
        return OFFICIAL_PRESETS_BY_ID[preset_id]
    except KeyError as error:
        raise ValueError("unknown Qwen TTS preset_id") from error


def validate_official_preset_provenance(value: object) -> OfficialPreset:
    if type(value) is not dict:
        raise ValueError("Qwen preset provenance must be an object")
    preset_id = value.get("preset_id")
    if type(preset_id) is not str:
        raise ValueError("Qwen preset provenance has no exact preset_id")
    preset = require_official_preset(preset_id)
    if value != preset.provenance():
        raise ValueError("Qwen preset provenance disagrees with the pinned catalog")
    return preset


def official_preset_validation_tier(preset_id: str) -> str:
    require_official_preset(preset_id)
    return (
        "canonical_chapter_verified"
        if preset_id in CANONICAL_CHAPTER_VERIFIED_PRESET_IDS
        else "pinned_catalog_unreviewed"
    )


def official_preset_provider_voice_id(
    preset_id: str,
    *,
    provider_id: str,
    aliyun_model_id: str | None = None,
) -> str | None:
    """Return an exact verified mapping, never an inferred substitute voice."""

    preset = require_official_preset(preset_id)
    if provider_id == "local_qwen3_tts":
        provider_key = provider_id
    elif provider_id == "aliyun_qwen_audio_tts" and aliyun_model_id in {
        "qwen-audio-3.0-tts-plus",
        "qwen-audio-3.0-tts-flash",
    }:
        provider_key = f"{provider_id}:{aliyun_model_id}"
    else:
        raise ValueError("unsupported Qwen TTS Provider selection")
    return preset.provider_voice_ids.get(provider_key)


def official_preset_decode_parameters_fingerprint(preset_id: str) -> str:
    preset = require_official_preset(preset_id)
    return canonical_sha256(
        {
            "schema_version": OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION,
            "voice_kind": "preset",
            "provider_voice_ids": preset.provider_voice_ids,
            "seed": OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
        }
    )


def official_preset_rights_policy_fingerprint() -> str:
    return canonical_sha256(
        {
            "notice_version": OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
            "purpose": "private_novel_narration",
            "commercial_use": False,
            "redistribution": False,
            "voice_cloning": False,
        }
    )


def official_preset_canonical_profile_id(
    *, owner_id: UUID | str, workspace_id: UUID | str, novel_id: UUID | str, preset_id: str
) -> UUID:
    preset = require_official_preset(preset_id)
    name = canonical_sha256(
        {
            "identity_contract_version": OFFICIAL_PRESET_IDENTITY_CONTRACT_VERSION,
            "owner_id": str(UUID(str(owner_id))),
            "workspace_id": str(UUID(str(workspace_id))),
            "novel_id": str(UUID(str(novel_id))),
            "preset_id": preset.preset_id,
        }
    )
    return uuid5(OFFICIAL_PRESET_IDENTITY_NAMESPACE, f"profile:{name}")


def official_preset_canonical_version_id(
    *, profile_id: UUID | str, preset_id: str
) -> UUID:
    preset = require_official_preset(preset_id)
    name = canonical_sha256(
        {
            "identity_contract_version": (
                OFFICIAL_PRESET_DIRECT_VERSION_IDENTITY_CONTRACT_VERSION
            ),
            "profile_id": str(UUID(str(profile_id))),
            "preset_id": preset.preset_id,
            "parameters": official_preset_decode_parameters_fingerprint(
                preset.preset_id
            ),
        }
    )
    return uuid5(OFFICIAL_PRESET_IDENTITY_NAMESPACE, f"version:{name}")


def official_preset_preview_version_id(
    *, profile_id: UUID | str, preset_id: str
) -> UUID:
    preset = require_official_preset(preset_id)
    name = canonical_sha256(
        {
            "identity_contract_version": (
                OFFICIAL_PRESET_PREVIEW_VERSION_IDENTITY_CONTRACT_VERSION
            ),
            "profile_id": str(UUID(str(profile_id))),
            "preset_id": preset.preset_id,
        }
    )
    return uuid5(OFFICIAL_PRESET_IDENTITY_NAMESPACE, f"preview-version:{name}")


def _version_fingerprint(
    *, profile_id: UUID | str, version_id: UUID | str, preset_id: str, direct: bool
) -> str:
    preset = require_official_preset(preset_id)
    return canonical_sha256(
        {
            "schema_version": (
                OFFICIAL_PRESET_DIRECT_VERSION_FINGERPRINT_SCHEMA_VERSION
            ),
            "profile_id": str(UUID(str(profile_id))),
            "version_id": str(UUID(str(version_id))),
            "preset_id": preset.preset_id,
            "direct_selection": direct,
            "provenance": preset.provenance(),
            "rights_policy_fingerprint": official_preset_rights_policy_fingerprint(),
        }
    )


def official_preset_direct_version_fingerprint(
    *, profile_id: UUID | str, version_id: UUID | str, preset_id: str
) -> str:
    return _version_fingerprint(
        profile_id=profile_id,
        version_id=version_id,
        preset_id=preset_id,
        direct=True,
    )


def official_preset_version_fingerprint(
    *, profile_id: UUID | str, version_id: UUID | str, preset_id: str
) -> str:
    return _version_fingerprint(
        profile_id=profile_id,
        version_id=version_id,
        preset_id=preset_id,
        direct=False,
    )


def validate_official_version_evidence(
    version: object,
    rights: object,
    *,
    expected_model_fingerprint: str,
) -> OfficialPreset:
    if expected_model_fingerprint != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256:
        raise ValueError("Qwen preset model fingerprint changed")
    preset_id = getattr(version, "preset_key", None)
    if type(preset_id) is not str:
        raise ValueError("Qwen preset version has no exact preset ID")
    preset = require_official_preset(preset_id)
    expected_parameters = {
        "schema_version": OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
        "voice_kind": "preset",
        "provider_voice_ids": preset.provider_voice_ids,
        "official_preset": preset.provenance(),
    }
    if getattr(version, "parameters_json", None) != expected_parameters:
        raise ValueError("Qwen preset version parameters are malformed")
    if (
        getattr(version, "source_type", None) != "preset"
        or getattr(version, "provider_id", None) != "qwen-tts"
        or getattr(version, "model_id", None) != OFFICIAL_PRESET_REPOSITORY
        or getattr(version, "model_revision", None) != OFFICIAL_PRESET_REVISION
        or getattr(version, "reference_asset_id", None) is not None
        or getattr(version, "language", None) != preset.language
        or getattr(rights, "source_kind", None) != "official_preset"
        or getattr(rights, "source_identifier", None)
        != f"qwen-tts-catalog://{preset.preset_id}"
        or getattr(rights, "notice_version", None)
        != OFFICIAL_PRESET_RIGHTS_POLICY_VERSION
        or getattr(rights, "purpose", None) != "private_novel_narration"
        or getattr(rights, "commercial_use", None) is not False
        or getattr(rights, "redistribution", None) is not False
        or getattr(rights, "voice_cloning", None) is not False
        or getattr(rights, "subject_consent_reference", None) is not None
        or getattr(rights, "expires_at", None) is not None
        or getattr(rights, "risk_flags_json", None) != []
        or type(getattr(rights, "confirmed_actor", None)) is not str
        or not isinstance(getattr(rights, "confirmed_at", None), datetime)
        or getattr(rights, "owner_id", None) != getattr(version, "owner_id", None)
        or getattr(rights, "workspace_id", None)
        != getattr(version, "workspace_id", None)
    ):
        raise ValueError("Qwen preset rights or runtime identity changed")
    direct = (
        getattr(version, "activation_basis", None)
        == "explicit_official_preset_selection"
    )
    expected_fingerprint = (
        official_preset_direct_version_fingerprint(
            profile_id=getattr(version, "profile_id"),
            version_id=getattr(version, "id"),
            preset_id=preset.preset_id,
        )
        if direct
        else official_preset_version_fingerprint(
            profile_id=getattr(version, "profile_id"),
            version_id=getattr(version, "id"),
            preset_id=preset.preset_id,
        )
    )
    if getattr(version, "fingerprint", None) != expected_fingerprint:
        raise ValueError("Qwen preset version fingerprint changed")
    if direct and (
        getattr(version, "state", None) != "locked"
        or getattr(version, "validation_basis", None) != "not_required"
        or getattr(version, "quality_state", None) != "pending"
    ):
        raise ValueError("Qwen direct-use activation evidence changed")
    return preset


__all__ = [name for name in globals() if name.startswith("OFFICIAL_PRESET")]
__all__ += [
    "CANONICAL_CHAPTER_VERIFIED_PRESET_IDS",
    "OfficialPreset",
    "canonical_sha256",
    "official_preset_canonical_profile_id",
    "official_preset_canonical_version_id",
    "official_preset_decode_parameters_fingerprint",
    "official_preset_direct_version_fingerprint",
    "official_preset_preview_version_id",
    "official_preset_rights_policy_fingerprint",
    "official_preset_validation_tier",
    "official_preset_version_fingerprint",
    "require_official_preset",
    "validate_official_preset_provenance",
    "validate_official_version_evidence",
]
