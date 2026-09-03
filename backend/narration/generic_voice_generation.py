"""Pure domain contracts for the Plan 55 workspace generic-voice pack.

The checked-in catalog provides one deterministic VoiceGenerator design per
existing taxonomy slot.  It does not claim that audio exists.  The durable ORM
service introduced by migration 0040 may use these plans to enqueue exactly one
heavy job at a time, then call :meth:`GenericVoiceGenerationService.validate`
only after both VoiceGenerator and Nano evidence have been persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Final
from uuid import UUID

from .contracts import LOCAL_WORKSPACE_ID
from .runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
from .services import NarrationServiceError, canonical_sha256
from .voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_FINGERPRINT,
    VoiceGeneratorHostRequest,
)
from .voice_pool import (
    VOICE_POOL_REQUIRED_SLOT_COUNT,
    VoicePoolCatalog,
    WorkspaceGenericVoiceSlot,
    load_voice_pool_catalog,
)


GENERIC_VOICE_DESIGN_SCHEMA_VERSION: Final = "generic-voice-design-catalog/1"
GENERIC_VOICE_DESIGN_FINGERPRINT_SCHEMA: Final = "generic-voice-design-fingerprint/1"
GENERIC_VOICE_DESIGN_PATH: Final = (
    Path(__file__).with_name("resources") / "generic_voice_design_v1.json"
)
GENERIC_VOICE_LANGUAGE: Final = "zh-CN"
GENERIC_VOICE_USAGE_SCOPE: Final = "workspace_library_private_use"
GENERIC_VOICE_SOURCE_KIND: Final = "voice_generator"
GENERIC_VOICE_JOB_KIND: Final = "narration.generic_voice_generate"

GENERIC_VOICE_PACK_NOT_READY: Final = "GENERIC_VOICE_PACK_NOT_READY"
GENERIC_VOICE_PACK_INCOMPLETE: Final = "GENERIC_VOICE_PACK_INCOMPLETE"
GENERIC_VOICE_PACK_LANGUAGE_UNAVAILABLE: Final = (
    "GENERIC_VOICE_PACK_LANGUAGE_UNAVAILABLE"
)
GENERIC_VOICE_PACK_SCOPE_MISMATCH: Final = "GENERIC_VOICE_PACK_SCOPE_MISMATCH"
GENERIC_VOICE_PACK_VERSION_CONFLICT: Final = "GENERIC_VOICE_PACK_VERSION_CONFLICT"
GENERIC_VOICE_PACK_SLOT_REJECTED: Final = "GENERIC_VOICE_PACK_SLOT_REJECTED"
GENERIC_VOICE_PACK_GENERATION_FAILED: Final = "GENERIC_VOICE_PACK_GENERATION_FAILED"

_ROOT_KEYS: Final = frozenset(
    {
        "schema_version",
        "catalog_id",
        "taxonomy_catalog_id",
        "taxonomy_sha256",
        "language",
        "usage_scope",
        "source_kind",
        "slots",
    }
)
_SLOT_KEYS: Final = frozenset({"slot_key", "seed", "instruction"})
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,159}$")
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,159}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_SEED: Final = 2**63 - 1


class GenericVoiceGenerationError(ValueError):
    """Stable and redacted error for generic voice design/validation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GenericVoiceGenerationState(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    VALIDATED = "validated"
    REUSED = "reused"
    REJECTED = "rejected"
    FAILED = "failed"


_TRANSITIONS: Final = {
    GenericVoiceGenerationState.PENDING: frozenset(
        {
            GenericVoiceGenerationState.GENERATING,
            GenericVoiceGenerationState.REUSED,
            GenericVoiceGenerationState.REJECTED,
        }
    ),
    GenericVoiceGenerationState.GENERATING: frozenset(
        {
            GenericVoiceGenerationState.VALIDATED,
            GenericVoiceGenerationState.FAILED,
            GenericVoiceGenerationState.REJECTED,
        }
    ),
    GenericVoiceGenerationState.FAILED: frozenset(
        {
            GenericVoiceGenerationState.GENERATING,
            GenericVoiceGenerationState.REJECTED,
        }
    ),
    GenericVoiceGenerationState.VALIDATED: frozenset(
        {GenericVoiceGenerationState.REJECTED}
    ),
    GenericVoiceGenerationState.REUSED: frozenset(
        {GenericVoiceGenerationState.REJECTED}
    ),
}


def ensure_generation_transition(
    current: GenericVoiceGenerationState,
    target: GenericVoiceGenerationState,
) -> GenericVoiceGenerationState:
    if type(current) is not GenericVoiceGenerationState or type(
        target
    ) is not GenericVoiceGenerationState:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice generation state is invalid",
        )
    if current is target:
        return target
    if target not in _TRANSITIONS.get(current, frozenset()):
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice generation transition is invalid",
        )
    return target


def _object(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT, f"{label} must be an object"
        )
    return value  # type: ignore[return-value]


def _text(value: object, *, label: str, maximum: int) -> str:
    if (
        type(value) is not str
        or value != value.strip()
        or not value
        or len(value) > maximum
        or any(ord(character) < 0x20 for character in value)
    ):
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT, f"{label} is invalid"
        )
    return value


@dataclass(frozen=True, slots=True)
class GenericVoiceDesign:
    slot_key: str
    seed: int
    instruction: str = field(repr=False)
    language: str
    instruction_sha256: str
    design_fingerprint: str


@dataclass(frozen=True, slots=True)
class GenericVoiceDesignCatalog:
    schema_version: str
    catalog_id: str
    taxonomy_catalog_id: str
    taxonomy_sha256: str
    language: str
    usage_scope: str
    source_kind: str
    slots: tuple[GenericVoiceDesign, ...]
    catalog_sha256: str


def _design_fingerprint(
    *,
    catalog_id: str,
    taxonomy_sha256: str,
    slot_key: str,
    seed: int,
    instruction_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "schema_version": GENERIC_VOICE_DESIGN_FINGERPRINT_SCHEMA,
            "catalog_id": catalog_id,
            "taxonomy_sha256": taxonomy_sha256,
            "slot_key": slot_key,
            "language": GENERIC_VOICE_LANGUAGE,
            "seed": seed,
            "instruction_sha256": instruction_sha256,
            "voice_generator_runtime": EXPECTED_RUNTIME_FINGERPRINT,
            "voice_generator_audio_parameters": EXPECTED_AUDIO_PARAMETERS.wire_payload(),
            "nano_model_fingerprint": EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256,
        }
    )


def parse_generic_voice_design_catalog(
    value: object,
    *,
    taxonomy: VoicePoolCatalog | None = None,
) -> GenericVoiceDesignCatalog:
    root = _object(value, label="generic voice design catalog")
    if set(root) != _ROOT_KEYS:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design catalog has an unexpected shape",
        )
    if root["schema_version"] != GENERIC_VOICE_DESIGN_SCHEMA_VERSION:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design schema is unsupported",
        )
    catalog_id = _text(root["catalog_id"], label="catalog_id", maximum=160)
    if _SAFE_ID.fullmatch(catalog_id) is None:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design catalog identity is invalid",
        )
    frozen = taxonomy or load_voice_pool_catalog()
    if (
        root["taxonomy_catalog_id"] != frozen.catalog_id
        or root["taxonomy_sha256"] != frozen.catalog_sha256
    ):
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design taxonomy identity changed",
        )
    if root["language"] != GENERIC_VOICE_LANGUAGE:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_LANGUAGE_UNAVAILABLE,
            "generic voice design language is unavailable",
        )
    if root["usage_scope"] != GENERIC_VOICE_USAGE_SCOPE:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_SCOPE_MISMATCH,
            "generic voice design usage scope changed",
        )
    if root["source_kind"] != GENERIC_VOICE_SOURCE_KIND:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_SCOPE_MISMATCH,
            "generic voice design source kind changed",
        )

    raw_slots = root["slots"]
    if type(raw_slots) is not list or len(raw_slots) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_INCOMPLETE,
            "generic voice design catalog must contain 24 slots",
        )
    slots: list[GenericVoiceDesign] = []
    for index, raw_slot in enumerate(raw_slots):
        item = _object(raw_slot, label=f"generic voice design {index}")
        if set(item) != _SLOT_KEYS:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice design slot has an unexpected shape",
            )
        slot_key = _text(item["slot_key"], label="slot_key", maximum=80)
        if _SAFE_KEY.fullmatch(slot_key) is None:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice design slot key is invalid",
            )
        seed = item["seed"]
        if type(seed) is not int or not 0 <= seed <= _MAX_SEED:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice design seed is invalid",
            )
        instruction = _text(item["instruction"], label="instruction", maximum=1_200)
        instruction_sha256 = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
        slots.append(
            GenericVoiceDesign(
                slot_key=slot_key,
                seed=seed,
                instruction=instruction,
                language=GENERIC_VOICE_LANGUAGE,
                instruction_sha256=instruction_sha256,
                design_fingerprint=_design_fingerprint(
                    catalog_id=catalog_id,
                    taxonomy_sha256=frozen.catalog_sha256,
                    slot_key=slot_key,
                    seed=seed,
                    instruction_sha256=instruction_sha256,
                ),
            )
        )

    expected_keys = tuple(slot.slot_key for slot in frozen.slots)
    actual_keys = tuple(slot.slot_key for slot in slots)
    if actual_keys != expected_keys:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_INCOMPLETE,
            "generic voice design slots must exactly follow the taxonomy",
        )
    if len({slot.seed for slot in slots}) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design seeds must be unique",
        )
    if len(
        {slot.instruction_sha256 for slot in slots}
    ) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice instructions must be unique",
        )
    if len(
        {slot.design_fingerprint for slot in slots}
    ) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design fingerprints must be unique",
        )
    return GenericVoiceDesignCatalog(
        schema_version=GENERIC_VOICE_DESIGN_SCHEMA_VERSION,
        catalog_id=catalog_id,
        taxonomy_catalog_id=frozen.catalog_id,
        taxonomy_sha256=frozen.catalog_sha256,
        language=GENERIC_VOICE_LANGUAGE,
        usage_scope=GENERIC_VOICE_USAGE_SCOPE,
        source_kind=GENERIC_VOICE_SOURCE_KIND,
        slots=tuple(slots),
        catalog_sha256=canonical_sha256(root),
    )


def load_generic_voice_design_catalog(
    path: Path = GENERIC_VOICE_DESIGN_PATH,
    *,
    taxonomy: VoicePoolCatalog | None = None,
) -> GenericVoiceDesignCatalog:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GenericVoiceGenerationError(
            GENERIC_VOICE_PACK_VERSION_CONFLICT,
            "generic voice design catalog cannot be loaded",
        ) from error
    return parse_generic_voice_design_catalog(raw, taxonomy=taxonomy)


@dataclass(frozen=True, slots=True)
class GenericVoiceGenerationPlan:
    command_id: UUID
    workspace_id: UUID
    slot_key: str
    job_kind: str
    design_fingerprint: str
    request: VoiceGeneratorHostRequest = field(repr=False)


@dataclass(frozen=True, slots=True)
class GenericVoiceCompletionEvidence:
    command_id: UUID
    workspace_id: UUID
    slot_key: str
    design_fingerprint: str
    request_id: UUID
    request_digest: str
    profile_id: UUID
    voice_version_id: UUID
    profile_novel_id: None
    language: str
    source_kind: str
    generator_model_fingerprint: str
    nano_model_fingerprint: str
    reference_audio_sha256: str
    validation_audio_sha256: str
    rights_approved: bool
    quality_approved: bool
    rejected: bool = False


class GenericVoiceGenerationService:
    """Build exact host requests and close their machine evidence."""

    def __init__(
        self,
        catalog: GenericVoiceDesignCatalog | None = None,
        *,
        workspace_id: UUID = LOCAL_WORKSPACE_ID,
    ) -> None:
        if not isinstance(workspace_id, UUID) or workspace_id.int == 0:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_SCOPE_MISMATCH,
                "generic voice generation workspace is invalid",
            )
        if workspace_id != LOCAL_WORKSPACE_ID:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_SCOPE_MISMATCH,
                "generic voice generation is outside the local workspace",
            )
        self._catalog = catalog or load_generic_voice_design_catalog()
        self._workspace_id = workspace_id
        self._by_key = {item.slot_key: item for item in self._catalog.slots}

    @property
    def catalog(self) -> GenericVoiceDesignCatalog:
        return self._catalog

    def design_for(self, slot_key: str) -> GenericVoiceDesign:
        try:
            return self._by_key[slot_key]
        except (KeyError, TypeError) as error:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice slot is outside the frozen taxonomy",
            ) from error

    def plan(
        self,
        *,
        command_id: UUID,
        slot_key: str,
        workspace_id: UUID,
        language: str,
    ) -> GenericVoiceGenerationPlan:
        if workspace_id != self._workspace_id:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_SCOPE_MISMATCH,
                "generic voice generation workspace changed",
            )
        if language != GENERIC_VOICE_LANGUAGE:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_LANGUAGE_UNAVAILABLE,
                "generic voice generation language is unavailable",
            )
        if not isinstance(command_id, UUID) or command_id.int == 0:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice generation command is invalid",
            )
        design = self.design_for(slot_key)
        request = VoiceGeneratorHostRequest(
            request_id=command_id,
            instruction=design.instruction,
            instruction_digest=design.instruction_sha256,
            language=design.language,
            seed=design.seed,
        )
        return GenericVoiceGenerationPlan(
            command_id=command_id,
            workspace_id=workspace_id,
            slot_key=design.slot_key,
            job_kind=GENERIC_VOICE_JOB_KIND,
            design_fingerprint=design.design_fingerprint,
            request=request,
        )

    def validate(
        self,
        *,
        plan: GenericVoiceGenerationPlan,
        evidence: GenericVoiceCompletionEvidence,
    ) -> WorkspaceGenericVoiceSlot:
        if type(plan) is not GenericVoiceGenerationPlan or type(
            evidence
        ) is not GenericVoiceCompletionEvidence:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_GENERATION_FAILED,
                "generic voice generation evidence is invalid",
            )
        if (
            plan.command_id != evidence.command_id
            or plan.workspace_id != evidence.workspace_id
            or plan.workspace_id != self._workspace_id
            or plan.slot_key != evidence.slot_key
            or plan.design_fingerprint != evidence.design_fingerprint
            or plan.request.request_id != evidence.request_id
            or plan.request.request_digest != evidence.request_digest
        ):
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice generation evidence identity changed",
            )
        if (
            evidence.generator_model_fingerprint != EXPECTED_RUNTIME_FINGERPRINT
            or evidence.nano_model_fingerprint
            != EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
            or evidence.rights_approved is not True
            or evidence.quality_approved is not True
            or evidence.rejected is not False
        ):
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_GENERATION_FAILED,
                "generic voice machine validation is incomplete",
            )
        try:
            return WorkspaceGenericVoiceSlot(
                slot_key=evidence.slot_key,
                profile_id=evidence.profile_id,
                voice_version_id=evidence.voice_version_id,
                workspace_id=evidence.workspace_id,
                profile_novel_id=evidence.profile_novel_id,
                language=evidence.language,
                source_kind=evidence.source_kind,
                design_fingerprint=evidence.design_fingerprint,
                generator_model_fingerprint=evidence.generator_model_fingerprint,
                nano_model_fingerprint=evidence.nano_model_fingerprint,
                reference_audio_sha256=evidence.reference_audio_sha256,
                validation_audio_sha256=evidence.validation_audio_sha256,
                rights_approved=evidence.rights_approved,
                quality_approved=evidence.quality_approved,
                rejected=evidence.rejected,
            )
        except (NarrationServiceError, ValueError) as error:
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_GENERATION_FAILED,
                "generic voice validation evidence is malformed",
            ) from error

    def reuse(
        self,
        *,
        slot_key: str,
        existing: WorkspaceGenericVoiceSlot,
    ) -> WorkspaceGenericVoiceSlot:
        """Accept only an unchanged, still-approved immutable slot version."""

        design = self.design_for(slot_key)
        if type(existing) is not WorkspaceGenericVoiceSlot or (
            existing.slot_key != design.slot_key
            or existing.workspace_id != self._workspace_id
            or existing.profile_novel_id is not None
            or existing.language != GENERIC_VOICE_LANGUAGE
            or existing.source_kind != GENERIC_VOICE_SOURCE_KIND
            or existing.design_fingerprint != design.design_fingerprint
            or existing.generator_model_fingerprint != EXPECTED_RUNTIME_FINGERPRINT
            or existing.nano_model_fingerprint
            != EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
            or existing.rights_approved is not True
            or existing.quality_approved is not True
            or existing.rejected is not False
        ):
            raise GenericVoiceGenerationError(
                GENERIC_VOICE_PACK_VERSION_CONFLICT,
                "generic voice slot cannot be reused after identity drift",
            )
        return existing


__all__ = [
    "GENERIC_VOICE_DESIGN_PATH",
    "GENERIC_VOICE_DESIGN_SCHEMA_VERSION",
    "GENERIC_VOICE_JOB_KIND",
    "GENERIC_VOICE_LANGUAGE",
    "GENERIC_VOICE_SOURCE_KIND",
    "GenericVoiceCompletionEvidence",
    "GenericVoiceDesign",
    "GenericVoiceDesignCatalog",
    "GenericVoiceGenerationError",
    "GenericVoiceGenerationPlan",
    "GenericVoiceGenerationService",
    "GenericVoiceGenerationState",
    "ensure_generation_transition",
    "load_generic_voice_design_catalog",
    "parse_generic_voice_design_catalog",
]
