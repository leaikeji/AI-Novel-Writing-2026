"""Pinned metadata-only catalog for the official MOSS-TTS-Nano ONNX presets.

The upstream manifest contains prompt audio codes.  Those codes and the
referenced audio are intentionally not copied into this repository.  This
module records only the immutable identity, shape, and SHA-256 evidence needed
to select and verify a preset against the pinned runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Final, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5


OFFICIAL_PRESET_REPOSITORY: Final = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
OFFICIAL_PRESET_REVISION: Final = "f52645cb467506d8e18e746ddd59482685b74e58"
OFFICIAL_PRESET_MANIFEST_PATH: Final = "browser_poc_manifest.json"
OFFICIAL_PRESET_MANIFEST_SHA256: Final = (
    "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee"
)
OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256: Final = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION: Final = (
    "moss-tts-official-preset-provenance/1.0"
)
OFFICIAL_PRESET_VERSION_SCHEMA_VERSION: Final = (
    "narration-official-preset-version/1.0"
)
# These values are the exact defaults in the pinned official ONNX manifest and
# runtime.  Product voice versions persist them so preview and chapter renders
# cannot silently drift with process-local defaults.
OFFICIAL_PRESET_SAMPLE_MODE: Final = "fixed"
OFFICIAL_PRESET_MAX_NEW_FRAMES: Final = 375
OFFICIAL_PRESET_RUNTIME_INITIAL_SEED: Final = 1234
OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION: Final = (
    "narration-voice-product/1"
)
OFFICIAL_PRESET_IDENTITY_CONTRACT_VERSION: Final = (
    "moss-tts-official-preset-identity/1.0"
)
OFFICIAL_PRESET_DIRECT_VERSION_IDENTITY_CONTRACT_VERSION: Final = (
    "moss-tts-official-preset-direct-version-identity/2.0"
)
OFFICIAL_PRESET_DIRECT_VERSION_FINGERPRINT_SCHEMA_VERSION: Final = (
    "narration-official-preset-direct-version/2.0"
)
OFFICIAL_PRESET_RIGHTS_POLICY_VERSION: Final = (
    "moss-tts-official-preset-local-use/1.0"
)
OFFICIAL_PRESET_IDENTITY_NAMESPACE: Final = uuid5(
    NAMESPACE_URL,
    "https://ai-novel-world-2026.local/voice/official-preset",
)
PRODUCT_PRESET_OUT_OF_SCOPE: Final = "PRODUCT_PRESET_OUT_OF_SCOPE"
PRODUCT_OFFICIAL_PRESET_IDS: Final[tuple[str, ...]] = (
    "onnx.Junhao",
    "onnx.Zhiming",
    "onnx.Weiguo",
    "onnx.Xiaoyu",
    "onnx.Yuewen",
    "onnx.Lingyu",
)
CANONICAL_CHAPTER_VERIFIED_PRESET_IDS: Final[frozenset[str]] = frozenset(
    {
        "onnx.Junhao",
        "onnx.Zhiming",
        "onnx.Xiaoyu",
    }
)
_EXPECTED_CANONICAL_CHAPTER_VERIFIED_PRESET_IDS: Final = frozenset(
    {"onnx.Junhao", "onnx.Zhiming", "onnx.Xiaoyu"}
)
if (
    CANONICAL_CHAPTER_VERIFIED_PRESET_IDS
    != _EXPECTED_CANONICAL_CHAPTER_VERIFIED_PRESET_IDS
):
    raise RuntimeError("official preset verified tier drifted")


class ProductPresetOutOfScope(ValueError):
    """A pinned runtime preset is not selectable in the current product."""

    code: Final = PRODUCT_PRESET_OUT_OF_SCOPE


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


def official_preset_decode_parameters_fingerprint(preset_id: str) -> str:
    """Fingerprint the exact pinned upstream defaults for one preset."""

    preset = require_official_preset(preset_id)
    return canonical_sha256(
        {
            "schema_version": OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION,
            "sample_mode": OFFICIAL_PRESET_SAMPLE_MODE,
            "max_new_frames": OFFICIAL_PRESET_MAX_NEW_FRAMES,
            "seed": OFFICIAL_PRESET_RUNTIME_INITIAL_SEED,
            "voice_key": preset.preset_id,
        }
    )


def official_preset_rights_policy_fingerprint() -> str:
    """Fingerprint the narrow local writing-tool rights record we persist."""

    return canonical_sha256(
        {
            "notice_version": OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
            "purpose": "private_novel_narration",
            "commercial_use": False,
            "redistribution": False,
            "voice_cloning": False,
            "risk_flags": ["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"],
        }
    )


def official_preset_canonical_profile_id(
    *, owner_id: UUID | str, workspace_id: UUID | str, novel_id: UUID | str, preset_id: str
) -> UUID:
    """Stable per-novel container identity for one pinned official preset."""

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
    """Stable immutable version identity for the current pinned inputs."""

    preset = require_official_preset(preset_id)
    name = canonical_sha256(
        {
            "identity_contract_version": (
                OFFICIAL_PRESET_DIRECT_VERSION_IDENTITY_CONTRACT_VERSION
            ),
            "profile_id": str(UUID(str(profile_id))),
            "activation_basis": "explicit_official_preset_selection",
            "validation_basis": "not_required",
            "model_revision": OFFICIAL_PRESET_REVISION,
            "manifest_sha256": OFFICIAL_PRESET_MANIFEST_SHA256,
            "preset_provenance_fingerprint": preset.provenance()[
                "provenance_fingerprint_sha256"
            ],
            "rights_policy_fingerprint": official_preset_rights_policy_fingerprint(),
            "decode_contract_version": OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION,
            "official_default_parameters_digest": (
                official_preset_decode_parameters_fingerprint(preset.preset_id)
            ),
        }
    )
    return uuid5(OFFICIAL_PRESET_IDENTITY_NAMESPACE, f"version:{name}")


def official_preset_direct_version_fingerprint(
    *,
    profile_id: UUID | str,
    version_id: UUID | str,
    preset_id: str,
) -> str:
    """Fingerprint a truthful direct-use version without colliding with v1."""

    preset = require_official_preset(preset_id)
    return canonical_sha256(
        {
            "schema_version": (
                OFFICIAL_PRESET_DIRECT_VERSION_FINGERPRINT_SCHEMA_VERSION
            ),
            "profile_id": str(UUID(str(profile_id))),
            "version_id": str(UUID(str(version_id))),
            "preset_id": preset.preset_id,
            "activation_basis": "explicit_official_preset_selection",
            "validation_basis": "not_required",
            "quality_state": "pending",
            "provenance_fingerprint_sha256": preset.provenance()[
                "provenance_fingerprint_sha256"
            ],
            "model_fingerprint_sha256": (
                OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
            ),
            "rights_policy_fingerprint": official_preset_rights_policy_fingerprint(),
            "decode_parameters_fingerprint": (
                official_preset_decode_parameters_fingerprint(preset.preset_id)
            ),
        }
    )


def official_preset_version_fingerprint(
    *,
    profile_id: UUID | str,
    version_id: UUID | str,
    preset_id: str,
) -> str:
    """Derive the immutable Voice Version identity expected by the product."""

    preset = require_official_preset(preset_id)
    profile = UUID(str(profile_id))
    version = UUID(str(version_id))
    return canonical_sha256(
        {
            "schema_version": OFFICIAL_PRESET_VERSION_SCHEMA_VERSION,
            "profile_id": str(profile),
            "version_id": str(version),
            "preset_id": preset.preset_id,
            "provenance_fingerprint_sha256": preset.provenance()[
                "provenance_fingerprint_sha256"
            ],
            "model_fingerprint_sha256": (
                OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
            ),
            "decode_parameters_fingerprint": (
                official_preset_decode_parameters_fingerprint(preset.preset_id)
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class OfficialPreset:
    manifest_voice: str
    display_name: str
    group: str
    language: str
    audio_file: str
    prompt_frame_count: int
    prompt_quantizer_count: int
    prompt_codes_sha256: str

    @property
    def preset_id(self) -> str:
        return f"onnx.{self.manifest_voice}"

    def provenance_without_fingerprint(self) -> dict[str, object]:
        return {
            "schema_version": OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION,
            "repository": OFFICIAL_PRESET_REPOSITORY,
            "revision": OFFICIAL_PRESET_REVISION,
            "manifest_path": OFFICIAL_PRESET_MANIFEST_PATH,
            "manifest_sha256": OFFICIAL_PRESET_MANIFEST_SHA256,
            "preset_id": self.preset_id,
            "manifest_voice": self.manifest_voice,
            "prompt_codes_sha256": self.prompt_codes_sha256,
            "prompt_frame_count": self.prompt_frame_count,
            "prompt_quantizer_count": self.prompt_quantizer_count,
            "model_fingerprint_sha256": OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        }

    def provenance(self) -> dict[str, object]:
        value = self.provenance_without_fingerprint()
        return {
            **value,
            "provenance_fingerprint_sha256": canonical_sha256(value),
        }


_PRESET_ROWS: Final = (
    ("Junhao", "CN 欢迎关注模思智能", "Chinese Male", "zh-CN", "zh_1.wav", 98, "395976042d458c44977c43b9b20a9945100cbf0302381e5d25e46b43304aa6d4"),
    ("Zhiming", "CN 京味胡同闲聊", "Chinese Male", "zh-CN", "zh_3.wav", 98, "6574897aab814be3b155f073683e4f19a3e5f1ab92ddfa66bec5b7911cf4099e"),
    ("Weiguo", "CN 说书", "Chinese Male", "zh-CN", "zh_10.wav", 140, "cbfa9212b4f8ec64172f7057c92dc8ec9a1731530b012bd9dfb3b1e297624ee6"),
    ("Xiaoyu", "CN 明星", "Chinese Female", "zh-CN", "zh_11.wav", 180, "847277bcef201396ef1aa6adbc8e55a25c9b0b8e3cfa3c72ac306053224022be"),
    ("Yuewen", "CN 机车", "Chinese Female", "zh-CN", "zh_4.wav", 102, "bed66ac01188f639b18f1a8cfd1520d6fbf0c319d27c282b1dc1cd3e9a8a888f"),
    ("Lingyu", "CN 深夜电台", "Chinese Female", "zh-CN", "zh_6.wav", 218, "761b4a0b0c3e0cec067c76b9a21560d8c8b0e302f67e16f0bf090e288c6fb3b0"),
    ("Trump", "EN Trump", "English Male", "en", "en_1.wav", 97, "3055948dd0646a7d1a72de824d33ab069ca3a2a5489a78f22818314a3d2e9d27"),
    ("Ava", "EN The Bitter Lesson", "English Female", "en", "en_2.wav", 98, "892a532b562d79fe683640e98f2e061683e4ea7bc93929d0866a1f5dae30ba48"),
    ("Bella", "EN A Gentle Reminder", "English Female", "en", "en_3.wav", 59, "d4def268888ebb0575d3bb8b1428bdea252af26e68281c43218432ddc9b0cda4"),
    ("Adam", "EN English News", "English Male", "en", "en_4.wav", 59, "14ffba3b57fdd50e16f431ba6631bf9b26d4c8ae1ec671ab73c1dea61e2835b7"),
    ("Nathan", "EN The Quiet Motion of the World", "English Male", "en", "en_8.wav", 168, "3e4bdb8ba9884ebf028efafb1535af784bb792a2695a25e571abc0a9cd18072e"),
    ("Soyo", "JP Soyo", "Japanese Female", "ja-JP", "jp_1.wav", 125, "d2079895cc7f2ec931a983e8f16150cc322c37bf0b62135507126736ee70e4e1"),
    ("Saki", "JP Saki", "Japanese Female", "ja-JP", "jp_2.wav", 32, "85f916c338c1a26f5e91b90b71f7942bfb3c465e999d97a12b24644258de18bd"),
    ("Mortis", "JP Mortis", "Japanese Female", "ja-JP", "jp_3.wav", 60, "9976030044c8746d488fa1cdf470e43760429bf73113819f9da15784bf4d4449"),
    ("Umiri", "JP Umiri", "Japanese Female", "ja-JP", "jp_4.wav", 77, "72bdf9fb4dfcd4405ec216030a73bf004856b6cf66b100c040fe36bea6165d43"),
    ("Mei", "JP Togawa", "Japanese Female", "ja-JP", "jp_5.wav", 49, "2068325ad43d3589bcffcb2f8a969eb7ff6570de4736aa3221553537c6232b1a"),
    ("Anon", "JP Anon", "Japanese Female", "ja-JP", "jp_6.wav", 47, "566b5098c19390f178cba0e1d16961ff45a225677adbb6f0bc2315c20954a5ee"),
    ("Arisa", "JP Arisa", "Japanese Female", "ja-JP", "jp_7.wav", 85, "2cf65c28e3bb62c93195a1d0778578d10c0ef71a42a66dcbe613592efb17dd5f"),
)

OFFICIAL_PRESETS: Final[tuple[OfficialPreset, ...]] = tuple(
    OfficialPreset(
        manifest_voice=voice,
        display_name=display_name,
        group=group,
        language=language,
        audio_file=audio_file,
        prompt_frame_count=frame_count,
        prompt_quantizer_count=16,
        prompt_codes_sha256=prompt_hash,
    )
    for voice, display_name, group, language, audio_file, frame_count, prompt_hash in _PRESET_ROWS
)
OFFICIAL_PRESETS_BY_ID: Final[Mapping[str, OfficialPreset]] = {
    item.preset_id: item for item in OFFICIAL_PRESETS
}
PRODUCT_OFFICIAL_PRESETS: Final[tuple[OfficialPreset, ...]] = tuple(
    OFFICIAL_PRESETS_BY_ID[preset_id]
    for preset_id in PRODUCT_OFFICIAL_PRESET_IDS
)


def require_official_preset(preset_id: str) -> OfficialPreset:
    try:
        return OFFICIAL_PRESETS_BY_ID[preset_id]
    except KeyError as error:
        raise ValueError("unknown official ONNX preset_id") from error


def require_product_official_preset(preset_id: str) -> OfficialPreset:
    """Resolve one currently actionable preset without narrowing inventory.

    The pinned runtime catalog remains authoritative for all 18 manifest rows.
    This separate product gate limits only current user-facing selection and
    creation to the six approved Chinese presets.
    """

    preset = require_official_preset(preset_id)
    if preset.preset_id not in PRODUCT_OFFICIAL_PRESET_IDS:
        raise ProductPresetOutOfScope(PRODUCT_PRESET_OUT_OF_SCOPE)
    return preset


def validate_official_preset_provenance(value: object) -> OfficialPreset:
    if type(value) is not dict:
        raise ValueError("official preset provenance must be an object")
    preset_id = value.get("preset_id")
    if type(preset_id) is not str:
        raise ValueError("official preset provenance has no exact preset_id")
    preset = require_official_preset(preset_id)
    if value != preset.provenance():
        raise ValueError("official preset provenance disagrees with pinned manifest")
    return preset


def official_preset_validation_tier(
    preset_id: str,
) -> str:
    preset = require_official_preset(preset_id)
    return (
        "canonical_chapter_verified"
        if preset.preset_id in CANONICAL_CHAPTER_VERIFIED_PRESET_IDS
        else "pinned_catalog_unreviewed"
    )


def validate_official_version_evidence(
    version: object,
    rights: object,
    *,
    expected_model_fingerprint: str,
) -> OfficialPreset:
    """Validate official Voice Version evidence without importing ORM models.

    Duck-typed inputs keep this catalog module below the persistence layer, so
    resource projection, preview/render checks, and direct selection can share
    one fail-closed policy without an import cycle.
    """

    if expected_model_fingerprint != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256:
        raise ValueError("official preset model fingerprint changed")
    preset_id = getattr(version, "preset_key", None)
    if type(preset_id) is not str:
        raise ValueError("official preset version has no exact preset ID")
    preset = require_official_preset(preset_id)
    parameters = getattr(version, "parameters_json", None)
    if type(parameters) is not dict or set(parameters) != {
        "schema_version",
        "official_preset",
        "sample_mode",
        "max_new_frames",
    }:
        raise ValueError("official preset version parameters are malformed")
    if (
        parameters.get("schema_version") != OFFICIAL_PRESET_VERSION_SCHEMA_VERSION
        or parameters.get("sample_mode") != OFFICIAL_PRESET_SAMPLE_MODE
        or parameters.get("max_new_frames") != OFFICIAL_PRESET_MAX_NEW_FRAMES
        or getattr(version, "seed", None)
        != OFFICIAL_PRESET_RUNTIME_INITIAL_SEED
    ):
        raise ValueError("official preset defaults changed")
    provenance_preset = validate_official_preset_provenance(
        parameters.get("official_preset")
    )
    if provenance_preset is not preset:
        raise ValueError("official preset provenance names another preset")

    if (
        getattr(version, "source_type", None) != "preset"
        or getattr(version, "provider_id", None) != "local-sidecar"
        or getattr(version, "model_id", None) != OFFICIAL_PRESET_REPOSITORY
        or getattr(version, "model_revision", None) != OFFICIAL_PRESET_REVISION
        or getattr(version, "reference_asset_id", None) is not None
        or getattr(version, "language", None) != preset.language
    ):
        raise ValueError("official preset runtime identity changed")

    expected_source_identifier = (
        f"hf://{OFFICIAL_PRESET_REPOSITORY}@{OFFICIAL_PRESET_REVISION}/"
        f"{OFFICIAL_PRESET_MANIFEST_PATH}#{preset.preset_id}"
    )
    if (
        getattr(rights, "source_kind", None) != "official_preset"
        or getattr(rights, "source_identifier", None)
        != expected_source_identifier
        or getattr(rights, "notice_version", None)
        != OFFICIAL_PRESET_RIGHTS_POLICY_VERSION
        or getattr(rights, "purpose", None) != "private_novel_narration"
        or getattr(rights, "commercial_use", None) is not False
        or getattr(rights, "redistribution", None) is not False
        or getattr(rights, "voice_cloning", None) is not False
        or getattr(rights, "subject_consent_reference", None) is not None
        or getattr(rights, "expires_at", None) is not None
        or getattr(rights, "risk_flags_json", None)
        != ["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"]
        or type(getattr(rights, "confirmed_actor", None)) is not str
        or not getattr(rights, "confirmed_actor", "")
        or not isinstance(getattr(rights, "confirmed_at", None), datetime)
        or getattr(rights, "owner_id", None) != getattr(version, "owner_id", None)
        or getattr(rights, "workspace_id", None)
        != getattr(version, "workspace_id", None)
    ):
        raise ValueError("official preset rights policy changed")

    activation_basis = getattr(version, "activation_basis", "preview_confirmed")
    direct_selection = activation_basis == "explicit_official_preset_selection"
    expected_fingerprint = (
        official_preset_direct_version_fingerprint(
            profile_id=getattr(version, "profile_id"),
            version_id=getattr(version, "id"),
            preset_id=preset.preset_id,
        )
        if direct_selection
        else official_preset_version_fingerprint(
            profile_id=getattr(version, "profile_id"),
            version_id=getattr(version, "id"),
            preset_id=preset.preset_id,
        )
    )
    if getattr(version, "fingerprint", None) != expected_fingerprint:
        raise ValueError("official preset version fingerprint changed")
    if direct_selection and (
        getattr(version, "state", None) != "locked"
        or getattr(version, "validation_basis", None) != "not_required"
        or getattr(version, "quality_state", None) != "pending"
        or getattr(version, "locked_actor", None) is not None
        or getattr(version, "locked_at", None) is not None
    ):
        raise ValueError("official direct-use activation evidence changed")
    return preset


__all__ = [
    "OFFICIAL_PRESET_MANIFEST_PATH",
    "OFFICIAL_PRESET_MANIFEST_SHA256",
    "OFFICIAL_PRESET_DECODE_PARAMETERS_SCHEMA_VERSION",
    "OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256",
    "OFFICIAL_PRESET_MAX_NEW_FRAMES",
    "OFFICIAL_PRESET_PROVENANCE_SCHEMA_VERSION",
    "OFFICIAL_PRESET_REPOSITORY",
    "OFFICIAL_PRESET_REVISION",
    "OFFICIAL_PRESET_RUNTIME_INITIAL_SEED",
    "OFFICIAL_PRESET_SAMPLE_MODE",
    "OFFICIAL_PRESET_VERSION_SCHEMA_VERSION",
    "OFFICIAL_PRESET_IDENTITY_CONTRACT_VERSION",
    "OFFICIAL_PRESET_DIRECT_VERSION_IDENTITY_CONTRACT_VERSION",
    "OFFICIAL_PRESET_DIRECT_VERSION_FINGERPRINT_SCHEMA_VERSION",
    "OFFICIAL_PRESET_RIGHTS_POLICY_VERSION",
    "OFFICIAL_PRESETS",
    "OFFICIAL_PRESETS_BY_ID",
    "CANONICAL_CHAPTER_VERIFIED_PRESET_IDS",
    "PRODUCT_OFFICIAL_PRESET_IDS",
    "PRODUCT_OFFICIAL_PRESETS",
    "PRODUCT_PRESET_OUT_OF_SCOPE",
    "ProductPresetOutOfScope",
    "OfficialPreset",
    "canonical_sha256",
    "official_preset_decode_parameters_fingerprint",
    "official_preset_direct_version_fingerprint",
    "official_preset_rights_policy_fingerprint",
    "official_preset_canonical_profile_id",
    "official_preset_canonical_version_id",
    "official_preset_version_fingerprint",
    "official_preset_validation_tier",
    "require_official_preset",
    "require_product_official_preset",
    "validate_official_preset_provenance",
    "validate_official_version_evidence",
]
