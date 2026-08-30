"""Strict character voice briefs and deterministic official-preset matching.

The language model is allowed to describe a character voice, but it is never
allowed to select a preset.  This module validates that narrow description and
scores it against a pinned, objectively extracted acoustic baseline.  Loading
fails closed unless the checked-in baseline contains measurements for all 18
fixed presets and passes the evidence checks produced by
``scripts/tts/build_official_voice_casting_baseline.py``.

No ORM, model-runtime, binding, or HTTP concerns live here.  The caller owns
those phases and must preserve its pre-model CAS snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping

from .official_presets import (
    OFFICIAL_PRESET_MANIFEST_PATH,
    OFFICIAL_PRESET_MANIFEST_SHA256,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESETS,
)


BRIEF_SCHEMA_VERSION: Final = "character-voice-brief/1"
BASELINE_SCHEMA_VERSION: Final = "official-voice-casting-baseline/1"
EXTRACTOR_SCHEMA_VERSION: Final = "official-voice-acoustic-extractor/1"
CHARACTER_VOICE_BRIEF_INVALID: Final = "CHARACTER_VOICE_BRIEF_INVALID"
CHARACTER_VOICE_BASELINE_INVALID: Final = "CHARACTER_VOICE_BASELINE_INVALID"
CHARACTER_VOICE_NO_CANDIDATE: Final = "CHARACTER_VOICE_NO_CANDIDATE"

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_EVIDENCE_PATH = re.compile(
    r"^(language|presentation|pitch|pace|energy|texture):"
    r"(character|selected_instance|aliases|relationships|projected_state)"
    r"(?:\.|\[)[A-Za-z0-9_\-\[\].]+$"
)
_IDENTITY_ONLY_EVIDENCE = re.compile(
    r"^[a-z_]+:(?:character\.name|selected_instance\.display_label|aliases(?:\[|\.))"
)
_BRIEF_DIMENSIONS: Final = (
    "language",
    "presentation",
    "pitch",
    "pace",
    "energy",
    "texture",
)
_DIMENSION_WEIGHTS: Final[Mapping[str, int]] = {
    "presentation": 4,
    "pitch": 3,
    "pace": 2,
    "energy": 2,
    "texture": 1,
}
ACOUSTIC_EXTRACTOR_SPEC: Final[Mapping[str, object]] = MappingProxyType(
    {
        "schema_version": EXTRACTOR_SCHEMA_VERSION,
        "input": "RIFF_PCM_S16_LE",
        "channel_policy": "integer_mean_to_mono",
        "active_frame_ms": 20,
        "active_floor_dbfs_milli": -45_000,
        "active_relative_db_milli": -30_000,
        "pitch_resample_hz": 8_000,
        "pitch_window_ms": 40,
        "pitch_hop_ms": 20,
        "pitch_min_hz": 60,
        "pitch_max_hz": 400,
        "pitch_min_periodicity_millionths": 250_000,
        "pitch_max_windows": 60,
        "bucket_policy": "midrank_quintile_-2_to_2",
        "pitch_cohort": "presentation",
        "pace_cohort": "language_inverse_voiced_duration",
        "energy_cohort": "language_active_rms_dbfs",
        "texture_policy": "objective_rank_rules_v1",
    }
)
_EXPECTED_BASELINE_ROOT_KEYS: Final = frozenset(
    {
        "schema_version",
        "status",
        "reason_code",
        "official_manifest",
        "extractor",
        "source",
        "items",
    }
)
_EXPECTED_MANIFEST_KEYS: Final = frozenset(
    {"repository", "revision", "path", "sha256"}
)
_EXPECTED_EXTRACTOR_KEYS: Final = frozenset(
    {"schema_version", "spec_sha256", "implementation_sha256"}
)
_EXPECTED_SOURCE_KEYS: Final = frozenset(
    {
        "schema_version",
        "kind",
        "model_fingerprint_sha256",
        "model_revision",
        "sidecar_protocol_version",
        "sample_mode",
        "max_new_frames",
        "seed",
        "input_manifest_sha256",
        "aggregate_audio_sha256",
        "prompts",
    }
)
_EXPECTED_ITEM_KEYS: Final = frozenset(
    {
        "preset_id",
        "language",
        "presentation",
        "source_audio_sha256",
        "sample_rate_hz",
        "duration_ms",
        "voiced_duration_ms",
        "pitch_hz_milli",
        "rms_dbfs_milli",
        "zero_crossing_rate_millionths",
        "periodicity_millionths",
        "crest_factor_milli",
        "pitch",
        "pace",
        "energy",
        "texture",
    }
)


class CharacterVoiceLanguage(str, Enum):
    ZH_CN = "zh-CN"
    EN = "en"
    JA_JP = "ja-JP"


class CharacterVoicePresentation(str, Enum):
    MASCULINE = "masculine"
    FEMININE = "feminine"
    ANDROGYNOUS = "androgynous"


class CharacterVoiceTexture(str, Enum):
    CLEAR = "clear"
    WARM = "warm"
    AIRY = "airy"
    HUSKY = "husky"
    FIRM = "firm"
    SOFT = "soft"
    BRIGHT = "bright"
    DARK = "dark"


class CharacterVoiceMatchingError(ValueError):
    """Stable fail-closed error for brief or baseline validation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid_brief(message: str) -> CharacterVoiceMatchingError:
    return CharacterVoiceMatchingError(CHARACTER_VOICE_BRIEF_INVALID, message)


def _invalid_baseline(message: str) -> CharacterVoiceMatchingError:
    return CharacterVoiceMatchingError(CHARACTER_VOICE_BASELINE_INVALID, message)


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


ACOUSTIC_EXTRACTOR_SPEC_SHA256: Final = canonical_sha256(
    dict(ACOUSTIC_EXTRACTOR_SPEC)
)


def _exact_enum(
    enum_type: type[Enum], value: object, *, field_name: str
) -> Enum | None:
    if value is None:
        return None
    if type(value) is not str:
        raise _invalid_brief(f"{field_name} must be exact text or null")
    try:
        return enum_type(value)
    except ValueError as error:
        raise _invalid_brief(f"{field_name} is outside the frozen vocabulary") from error


def _brief_axis(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value not in {-2, -1, 0, 1, 2}:
        raise _invalid_brief(f"{field_name} must be -2..2 or null")
    return value


@dataclass(frozen=True, slots=True)
class CharacterVoiceBrief:
    """Validated model output; unknown facts remain ``None``."""

    language: CharacterVoiceLanguage | None
    presentation: CharacterVoicePresentation | None
    pitch: int | None
    pace: int | None
    energy: int | None
    texture: CharacterVoiceTexture | None
    evidence_fields: tuple[str, ...]
    schema_version: str = BRIEF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BRIEF_SCHEMA_VERSION:
            raise _invalid_brief("character voice brief schema changed")
        if self.language is not None and type(self.language) is not CharacterVoiceLanguage:
            raise _invalid_brief("language must use the frozen enum")
        if self.presentation is not None and type(
            self.presentation
        ) is not CharacterVoicePresentation:
            raise _invalid_brief("presentation must use the frozen enum")
        for field_name in ("pitch", "pace", "energy"):
            _brief_axis(getattr(self, field_name), field_name=field_name)
        if self.texture is not None and type(self.texture) is not CharacterVoiceTexture:
            raise _invalid_brief("texture must use the frozen enum")
        if type(self.evidence_fields) is not tuple:
            raise _invalid_brief("evidence_fields must be a tuple")
        if len(self.evidence_fields) > 48 or len(set(self.evidence_fields)) != len(
            self.evidence_fields
        ):
            raise _invalid_brief("evidence_fields must be bounded and unique")

        dimensions_with_evidence: set[str] = set()
        for evidence in self.evidence_fields:
            if type(evidence) is not str or len(evidence) > 240:
                raise _invalid_brief("evidence field path is malformed")
            match = _EVIDENCE_PATH.fullmatch(evidence)
            if match is None:
                raise _invalid_brief("evidence field path is outside the workspace")
            if _IDENTITY_ONLY_EVIDENCE.match(evidence) is not None:
                raise _invalid_brief(
                    "names and aliases cannot evidence a voice characteristic"
                )
            dimensions_with_evidence.add(match.group(1))

        populated = {
            field_name
            for field_name in _BRIEF_DIMENSIONS
            if getattr(self, field_name) is not None
        }
        if dimensions_with_evidence != populated:
            raise _invalid_brief(
                "every known dimension needs evidence and unknown dimensions cannot claim it"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "language": self.language.value if self.language is not None else None,
            "presentation": (
                self.presentation.value if self.presentation is not None else None
            ),
            "pitch": self.pitch,
            "pace": self.pace,
            "energy": self.energy,
            "texture": self.texture.value if self.texture is not None else None,
            "evidence_fields": list(self.evidence_fields),
        }


def parse_character_voice_brief(value: object) -> CharacterVoiceBrief:
    """Parse an exact JSON model response without coercion or extra fields."""

    if type(value) is not dict:
        raise _invalid_brief("character voice brief must be an object")
    expected = {"schema_version", *_BRIEF_DIMENSIONS, "evidence_fields"}
    if set(value) != expected:
        raise _invalid_brief("character voice brief fields changed")
    evidence = value["evidence_fields"]
    if type(evidence) is not list:
        raise _invalid_brief("evidence_fields must be a JSON array")
    return CharacterVoiceBrief(
        schema_version=value["schema_version"],
        language=_exact_enum(
            CharacterVoiceLanguage, value["language"], field_name="language"
        ),
        presentation=_exact_enum(
            CharacterVoicePresentation,
            value["presentation"],
            field_name="presentation",
        ),
        pitch=_brief_axis(value["pitch"], field_name="pitch"),
        pace=_brief_axis(value["pace"], field_name="pace"),
        energy=_brief_axis(value["energy"], field_name="energy"),
        texture=_exact_enum(
            CharacterVoiceTexture, value["texture"], field_name="texture"
        ),
        evidence_fields=tuple(evidence),
    )


@dataclass(frozen=True, slots=True)
class OfficialVoiceAcousticProfile:
    preset_id: str
    language: CharacterVoiceLanguage
    presentation: CharacterVoicePresentation
    pitch: int
    pace: int
    energy: int
    texture: CharacterVoiceTexture


@dataclass(frozen=True, slots=True)
class OfficialVoiceCastingBaseline:
    source_path: Path
    file_sha256: str
    source: Mapping[str, object]
    items: tuple[OfficialVoiceAcousticProfile, ...]


@dataclass(frozen=True, slots=True)
class CharacterVoiceMatch:
    selected_preset_id: str
    score_milli: int
    compared_dimensions: tuple[str, ...]
    baseline_sha256: str


def _exact_keys(value: object, expected: frozenset[str], *, field_name: str) -> dict:
    if type(value) is not dict or set(value) != expected:
        raise _invalid_baseline(f"{field_name} fields changed")
    return value


def _sha(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _invalid_baseline(f"{field_name} must be lowercase SHA-256")
    return value


def _bounded_int(
    value: object, *, field_name: str, minimum: int, maximum: int
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid_baseline(f"{field_name} is outside its measured bounds")
    return value


def _baseline_enum(enum_type: type[Enum], value: object, *, field_name: str) -> Enum:
    if type(value) is not str:
        raise _invalid_baseline(f"{field_name} must be exact text")
    try:
        return enum_type(value)
    except ValueError as error:
        raise _invalid_baseline(f"{field_name} is outside the frozen vocabulary") from error


def load_official_voice_casting_baseline(
    path: Path | None = None,
) -> OfficialVoiceCastingBaseline:
    """Load and authenticate the exact 18-row baseline or fail closed."""

    source_path = path or Path(__file__).with_name("resources").joinpath(
        "official_voice_casting_v1.json"
    )
    try:
        payload_bytes = source_path.read_bytes()
        raw = json.loads(payload_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _invalid_baseline("official voice casting baseline is unreadable") from error

    root = _exact_keys(raw, _EXPECTED_BASELINE_ROOT_KEYS, field_name="baseline")
    if root["schema_version"] != BASELINE_SCHEMA_VERSION:
        raise _invalid_baseline("official voice casting baseline schema changed")
    if root["status"] != "ready" or root["reason_code"] is not None:
        raise _invalid_baseline("official voice casting baseline is not ready")

    manifest = _exact_keys(
        root["official_manifest"], _EXPECTED_MANIFEST_KEYS, field_name="manifest"
    )
    expected_manifest = {
        "repository": OFFICIAL_PRESET_REPOSITORY,
        "revision": OFFICIAL_PRESET_REVISION,
        "path": OFFICIAL_PRESET_MANIFEST_PATH,
        "sha256": OFFICIAL_PRESET_MANIFEST_SHA256,
    }
    if manifest != expected_manifest:
        raise _invalid_baseline("official manifest identity changed")

    extractor = _exact_keys(
        root["extractor"], _EXPECTED_EXTRACTOR_KEYS, field_name="extractor"
    )
    if extractor["schema_version"] != EXTRACTOR_SCHEMA_VERSION:
        raise _invalid_baseline("acoustic extractor schema changed")
    if extractor["spec_sha256"] != ACOUSTIC_EXTRACTOR_SPEC_SHA256:
        raise _invalid_baseline("acoustic extractor spec changed")
    _sha(extractor["implementation_sha256"], field_name="extractor implementation")

    source = _exact_keys(
        root["source"], _EXPECTED_SOURCE_KEYS, field_name="baseline source"
    )
    if (
        source["schema_version"] != "official-voice-casting-source/1"
        or source["kind"] != "nano_fixed_short_sentence"
        or source["model_fingerprint_sha256"]
        != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
        or source["model_revision"] != OFFICIAL_PRESET_REVISION
        or source["sidecar_protocol_version"] != "moss-tts-sidecar/1.1"
        or source["sample_mode"] != "fixed"
        or source["max_new_frames"] != 375
        or source["seed"] != 1234
    ):
        raise _invalid_baseline("fixed source identity changed")
    _sha(source["input_manifest_sha256"], field_name="input manifest")
    _sha(source["aggregate_audio_sha256"], field_name="aggregate audio")
    prompts = source["prompts"]
    if type(prompts) is not dict or set(prompts) != {
        item.language for item in OFFICIAL_PRESETS
    }:
        raise _invalid_baseline("fixed language prompt evidence is incomplete")
    for language, prompt in prompts.items():
        if (
            type(language) is not str
            or type(prompt) is not dict
            or set(prompt) != {"text_sha256", "codepoint_count"}
        ):
            raise _invalid_baseline("fixed language prompt evidence is malformed")
        _sha(prompt["text_sha256"], field_name="prompt text")
        _bounded_int(
            prompt["codepoint_count"],
            field_name="prompt codepoint_count",
            minimum=1,
            maximum=400,
        )

    rows = root["items"]
    if type(rows) is not list or len(rows) != len(OFFICIAL_PRESETS):
        raise _invalid_baseline("baseline must contain all 18 official presets")

    parsed: list[OfficialVoiceAcousticProfile] = []
    expected_ids = tuple(item.preset_id for item in OFFICIAL_PRESETS)
    for index, (row_value, preset) in enumerate(zip(rows, OFFICIAL_PRESETS, strict=True)):
        row = _exact_keys(
            row_value, _EXPECTED_ITEM_KEYS, field_name=f"baseline item {index}"
        )
        if row["preset_id"] != preset.preset_id or row["language"] != preset.language:
            raise _invalid_baseline("baseline order or preset language changed")
        presentation = _baseline_enum(
            CharacterVoicePresentation,
            row["presentation"],
            field_name="baseline presentation",
        )
        expected_presentation = (
            CharacterVoicePresentation.MASCULINE
            if preset.group.endswith("Male")
            else CharacterVoicePresentation.FEMININE
        )
        if presentation is not expected_presentation:
            raise _invalid_baseline("baseline presentation differs from manifest group")
        _sha(row["source_audio_sha256"], field_name="source audio")
        _bounded_int(
            row["sample_rate_hz"],
            field_name="sample rate",
            minimum=8_000,
            maximum=192_000,
        )
        duration_ms = _bounded_int(
            row["duration_ms"], field_name="duration", minimum=100, maximum=120_000
        )
        voiced_ms = _bounded_int(
            row["voiced_duration_ms"],
            field_name="voiced duration",
            minimum=1,
            maximum=duration_ms,
        )
        _bounded_int(
            row["pitch_hz_milli"],
            field_name="pitch_hz_milli",
            minimum=40_000,
            maximum=700_000,
        )
        _bounded_int(
            row["rms_dbfs_milli"],
            field_name="rms_dbfs_milli",
            minimum=-120_000,
            maximum=0,
        )
        _bounded_int(
            row["zero_crossing_rate_millionths"],
            field_name="zero_crossing_rate_millionths",
            minimum=0,
            maximum=1_000_000,
        )
        _bounded_int(
            row["periodicity_millionths"],
            field_name="periodicity_millionths",
            minimum=0,
            maximum=1_000_000,
        )
        _bounded_int(
            row["crest_factor_milli"],
            field_name="crest_factor_milli",
            minimum=1_000,
            maximum=100_000,
        )
        pitch = _bounded_int(row["pitch"], field_name="pitch", minimum=-2, maximum=2)
        pace = _bounded_int(row["pace"], field_name="pace", minimum=-2, maximum=2)
        energy = _bounded_int(row["energy"], field_name="energy", minimum=-2, maximum=2)
        texture = _baseline_enum(
            CharacterVoiceTexture, row["texture"], field_name="baseline texture"
        )
        parsed.append(
            OfficialVoiceAcousticProfile(
                preset_id=preset.preset_id,
                language=CharacterVoiceLanguage(preset.language),
                presentation=presentation,
                pitch=pitch,
                pace=pace,
                energy=energy,
                texture=texture,
            )
        )
    if tuple(item.preset_id for item in parsed) != expected_ids:
        raise _invalid_baseline("baseline preset order changed")
    if source["aggregate_audio_sha256"] != canonical_sha256(
        [row["source_audio_sha256"] for row in rows]
    ):
        raise _invalid_baseline("aggregate source audio digest changed")
    return OfficialVoiceCastingBaseline(
        source_path=source_path,
        file_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        source=source,
        items=tuple(parsed),
    )


def _presentation_similarity(
    requested: CharacterVoicePresentation,
    actual: CharacterVoicePresentation,
) -> int:
    if requested is actual:
        return 1000
    if CharacterVoicePresentation.ANDROGYNOUS in {requested, actual}:
        return 500
    return 0


def _axis_similarity(requested: int, actual: int) -> int:
    return max(0, 1000 - 250 * abs(requested - actual))


def match_official_voice(
    brief: CharacterVoiceBrief,
    *,
    baseline: OfficialVoiceCastingBaseline | None = None,
) -> CharacterVoiceMatch:
    """Choose one preset with fixed weights and manifest-order tie breaking."""

    if type(brief) is not CharacterVoiceBrief:
        raise _invalid_brief("brief must be a validated CharacterVoiceBrief")
    catalog = baseline or load_official_voice_casting_baseline()
    if type(catalog) is not OfficialVoiceCastingBaseline:
        raise _invalid_baseline("baseline must be validated before scoring")
    if tuple(item.preset_id for item in catalog.items) != tuple(
        preset.preset_id for preset in OFFICIAL_PRESETS
    ):
        raise _invalid_baseline("scoring baseline must retain all 18 manifest rows")
    _sha(catalog.file_sha256, field_name="baseline file")

    candidates = tuple(
        item
        for item in catalog.items
        if brief.language is None or item.language is brief.language
    )
    if not candidates:
        raise CharacterVoiceMatchingError(
            CHARACTER_VOICE_NO_CANDIDATE,
            "no official preset matches the requested language",
        )

    compared = tuple(
        field_name
        for field_name in _DIMENSION_WEIGHTS
        if getattr(brief, field_name) is not None
    )
    if not compared:
        raise CharacterVoiceMatchingError(
            CHARACTER_VOICE_NO_CANDIDATE,
            "character voice brief has no scoreable dimension",
        )

    best: OfficialVoiceAcousticProfile | None = None
    best_score = -1
    weight_total = sum(_DIMENSION_WEIGHTS[field_name] for field_name in compared)
    for candidate in candidates:
        weighted = 0
        for field_name in compared:
            weight = _DIMENSION_WEIGHTS[field_name]
            requested = getattr(brief, field_name)
            actual = getattr(candidate, field_name)
            if field_name == "presentation":
                similarity = _presentation_similarity(requested, actual)
            elif field_name in {"pitch", "pace", "energy"}:
                similarity = _axis_similarity(requested, actual)
            else:
                similarity = 1000 if requested is actual else 0
            weighted += weight * similarity
        score = (weighted + weight_total // 2) // weight_total
        if score > best_score:
            best = candidate
            best_score = score

    if best is None:
        raise CharacterVoiceMatchingError(
            CHARACTER_VOICE_NO_CANDIDATE, "no official voice candidate was scored"
        )
    return CharacterVoiceMatch(
        selected_preset_id=best.preset_id,
        score_milli=best_score,
        compared_dimensions=compared,
        baseline_sha256=catalog.file_sha256,
    )


__all__ = [
    "ACOUSTIC_EXTRACTOR_SPEC",
    "ACOUSTIC_EXTRACTOR_SPEC_SHA256",
    "BASELINE_SCHEMA_VERSION",
    "BRIEF_SCHEMA_VERSION",
    "CHARACTER_VOICE_BASELINE_INVALID",
    "CHARACTER_VOICE_BRIEF_INVALID",
    "CHARACTER_VOICE_NO_CANDIDATE",
    "EXTRACTOR_SCHEMA_VERSION",
    "CharacterVoiceBrief",
    "CharacterVoiceLanguage",
    "CharacterVoiceMatch",
    "CharacterVoiceMatchingError",
    "CharacterVoicePresentation",
    "CharacterVoiceTexture",
    "OfficialVoiceAcousticProfile",
    "OfficialVoiceCastingBaseline",
    "canonical_sha256",
    "load_official_voice_casting_baseline",
    "match_official_voice",
    "parse_character_voice_brief",
]
