"""Fail-closed generic voice-pool catalogs and projection plans.

``voice_pool_v1.json`` remains a taxonomy rather than an audio asset pack.  A
separate, immutable workspace pack may satisfy that taxonomy after all 24
VoiceGenerator outputs have passed Nano validation.  This module validates that
boundary and creates a complete novel-scoped projection plan; it never performs
model, media, ORM, or transaction work itself.

The legacy settings read remains fail closed until migration 0040 and the
integration layer provide an active pack.  The old taxonomy-only write routes
were removed once the durable pack command became the sole mutation path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import re
from typing import Final
from uuid import UUID

from ..models import (
    GenericVoicePackVersion,
    GenericVoicePackVersionSlot,
    GenericVoicePool,
    GenericVoiceSlot,
    VoiceCastingRule,
)

from . import schemas as wire
from .contracts import LOCAL_WORKSPACE_ID
from .runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
from .services import (
    NarrationServiceError,
    NarrationStore,
    canonical_sha256,
    require_local_novel,
)
from .voice_generator_runtime import EXPECTED_RUNTIME_FINGERPRINT


VOICE_POOL_CATALOG_SCHEMA_VERSION: Final = "generic-voice-pack-catalog/1"
VOICE_POOL_CATALOG_PATH: Final = Path(__file__).with_name("resources") / "voice_pool_v1.json"
VOICE_POOL_REQUIRED_SLOT_COUNT: Final = 24
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CATALOG_KEYS: Final = frozenset(
    {
        "schema_version",
        "catalog_id",
        "catalog_status",
        "required_slot_count",
        "asset_pack_id",
        "rights_approved",
        "quality_approved",
        "production_ready",
        "reason_codes",
        "slots",
    }
)
_SLOT_KEYS: Final = frozenset({"slot_key", "label", "category"})


class GenericCastingUnavailable(NarrationServiceError):
    """Automatic generic casting remains gated until its later phase."""


@dataclass(frozen=True, slots=True)
class VoicePoolCatalogSlot:
    slot_key: str
    label: str
    category: str


@dataclass(frozen=True, slots=True)
class VoicePoolCatalog:
    schema_version: str
    catalog_id: str
    catalog_status: str
    required_slot_count: int
    asset_pack_id: None
    rights_approved: bool
    quality_approved: bool
    production_ready: bool
    reason_codes: tuple[str, ...]
    slots: tuple[VoicePoolCatalogSlot, ...]
    catalog_sha256: str


class GenericVoicePackState(str, Enum):
    BUILDING = "building"
    READY_TO_ACTIVATE = "ready_to_activate"
    ACTIVE = "active"
    RETIRED_FOR_NEW_USE = "retired_for_new_use"
    REJECTED = "rejected"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class WorkspaceGenericVoiceSlot:
    """One machine-validated library voice offered by a workspace pack.

    The profile deliberately has no novel scope.  Novel and character voices
    must continue to use their existing scoped binding paths.
    """

    slot_key: str
    profile_id: UUID
    voice_version_id: UUID
    workspace_id: UUID
    profile_novel_id: None
    language: str
    source_kind: str
    design_fingerprint: str
    generator_model_fingerprint: str
    nano_model_fingerprint: str
    reference_audio_sha256: str
    validation_audio_sha256: str
    rights_approved: bool
    quality_approved: bool
    rejected: bool = False

    def __post_init__(self) -> None:
        if not _SAFE_KEY.fullmatch(self.slot_key):
            raise NarrationServiceError("generic voice slot key is invalid")
        for field_name in ("profile_id", "voice_version_id", "workspace_id"):
            value = getattr(self, field_name)
            if not isinstance(value, UUID) or value.int == 0:
                raise NarrationServiceError(
                    f"generic voice slot {field_name} must be a non-zero UUID"
                )
        if self.profile_novel_id is not None:
            raise NarrationServiceError(
                "generic voice library profile must not have novel scope"
            )
        if self.language != "zh-CN":
            raise NarrationServiceError(
                "generic voice pack V1 only supports zh-CN"
            )
        if self.source_kind != "voice_generator":
            raise NarrationServiceError(
                "generic voice slot must originate from VoiceGenerator"
            )
        for field_name in (
            "design_fingerprint",
            "generator_model_fingerprint",
            "nano_model_fingerprint",
            "reference_audio_sha256",
            "validation_audio_sha256",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise NarrationServiceError(
                    f"generic voice slot {field_name} must be SHA-256"
                )
        for field_name in ("rights_approved", "quality_approved", "rejected"):
            if type(getattr(self, field_name)) is not bool:
                raise NarrationServiceError(
                    f"generic voice slot {field_name} must be an exact boolean"
                )


@dataclass(frozen=True, slots=True)
class WorkspaceGenericVoicePack:
    pack_version_id: UUID
    workspace_id: UUID
    language: str
    state: GenericVoicePackState
    taxonomy_sha256: str
    slots: tuple[WorkspaceGenericVoiceSlot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pack_version_id, UUID) or self.pack_version_id.int == 0:
            raise NarrationServiceError("generic voice pack version must be a non-zero UUID")
        if not isinstance(self.workspace_id, UUID) or self.workspace_id.int == 0:
            raise NarrationServiceError("generic voice pack workspace must be a non-zero UUID")
        if self.language != "zh-CN":
            raise NarrationServiceError("generic voice pack V1 only supports zh-CN")
        if type(self.state) is not GenericVoicePackState:
            raise NarrationServiceError("generic voice pack state is invalid")
        if type(self.taxonomy_sha256) is not str or _SHA256.fullmatch(
            self.taxonomy_sha256
        ) is None:
            raise NarrationServiceError("generic voice pack taxonomy digest is invalid")
        if type(self.slots) is not tuple:
            raise NarrationServiceError("generic voice pack slots must be immutable")
        if any(type(slot) is not WorkspaceGenericVoiceSlot for slot in self.slots):
            raise NarrationServiceError("generic voice pack slot projection is invalid")


@dataclass(frozen=True, slots=True)
class NovelGenericVoiceSlotProjection:
    slot_key: str
    position: int
    profile_id: UUID
    voice_version_id: UUID
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NovelGenericVoicePoolProjection:
    """Complete input for one short, atomic novel-pool transaction."""

    novel_id: UUID
    workspace_id: UUID
    source_pack_version_id: UUID
    language: str
    name: str
    slots: tuple[NovelGenericVoiceSlotProjection, ...]


def project_active_generic_voice_pack(
    *,
    novel_id: UUID,
    workspace_id: UUID,
    pack: WorkspaceGenericVoicePack,
    catalog: VoicePoolCatalog | None = None,
) -> NovelGenericVoicePoolProjection:
    """Project an exact active 24-slot library pack into one novel.

    This is intentionally all-or-nothing.  The integration layer may persist
    the returned plan in one transaction, but it must never trim or reorder it.
    """

    if not isinstance(novel_id, UUID) or novel_id.int == 0:
        raise NarrationServiceError("generic voice projection novel is invalid")
    if (
        not isinstance(workspace_id, UUID)
        or workspace_id.int == 0
        or workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationServiceError("generic voice projection workspace is invalid")
    frozen = catalog or load_voice_pool_catalog()
    if pack.workspace_id != workspace_id or any(
        slot.workspace_id != workspace_id for slot in pack.slots
    ):
        raise NarrationServiceError("GENERIC_VOICE_PACK_SCOPE_MISMATCH")
    if pack.language != "zh-CN":
        raise NarrationServiceError("GENERIC_VOICE_PACK_LANGUAGE_UNAVAILABLE")
    if pack.state is not GenericVoicePackState.ACTIVE:
        reason = (
            "GENERIC_VOICE_PACK_RETIRED"
            if pack.state is GenericVoicePackState.RETIRED_FOR_NEW_USE
            else "GENERIC_VOICE_PACK_NOT_READY"
        )
        raise NarrationServiceError(reason)
    if pack.taxonomy_sha256 != frozen.catalog_sha256:
        raise NarrationServiceError("GENERIC_VOICE_PACK_VERSION_CONFLICT")
    if len(pack.slots) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise NarrationServiceError("GENERIC_VOICE_PACK_INCOMPLETE")

    by_key = {slot.slot_key: slot for slot in pack.slots}
    expected_keys = tuple(item.slot_key for item in frozen.slots)
    if len(by_key) != VOICE_POOL_REQUIRED_SLOT_COUNT or set(by_key) != set(
        expected_keys
    ):
        raise NarrationServiceError("GENERIC_VOICE_PACK_INCOMPLETE")
    if len({slot.profile_id for slot in pack.slots}) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise NarrationServiceError("generic voice pack profiles must be unique")
    if len(
        {slot.voice_version_id for slot in pack.slots}
    ) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise NarrationServiceError("generic voice pack versions must be unique")
    if len(
        {slot.design_fingerprint for slot in pack.slots}
    ) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise NarrationServiceError("generic voice pack designs must be unique")

    projected: list[NovelGenericVoiceSlotProjection] = []
    for position, catalog_slot in enumerate(frozen.slots):
        slot = by_key[catalog_slot.slot_key]
        if slot.rejected:
            raise NarrationServiceError("GENERIC_VOICE_PACK_SLOT_REJECTED")
        if not slot.rights_approved or not slot.quality_approved:
            raise NarrationServiceError("GENERIC_VOICE_PACK_INCOMPLETE")
        if (
            slot.generator_model_fingerprint != EXPECTED_RUNTIME_FINGERPRINT
            or slot.nano_model_fingerprint
            != EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
        ):
            raise NarrationServiceError("GENERIC_VOICE_PACK_VERSION_CONFLICT")
        projected.append(
            NovelGenericVoiceSlotProjection(
                slot_key=slot.slot_key,
                position=position,
                profile_id=slot.profile_id,
                voice_version_id=slot.voice_version_id,
                labels=(catalog_slot.label, catalog_slot.category, pack.language),
            )
        )
    return NovelGenericVoicePoolProjection(
        novel_id=novel_id,
        workspace_id=workspace_id,
        source_pack_version_id=pack.pack_version_id,
        language=pack.language,
        name=f"generic-{pack.language}-{pack.pack_version_id}",
        slots=tuple(projected),
    )


def _record(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise NarrationServiceError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise NarrationServiceError(f"{label} keys must be strings")
    return value  # type: ignore[return-value]


def _bounded_text(value: object, *, label: str, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise NarrationServiceError(f"{label} must be bounded non-empty text")
    return value


def parse_voice_pool_catalog(value: object) -> VoicePoolCatalog:
    root = _record(value, label="voice pool catalog")
    if set(root) != _CATALOG_KEYS:
        raise NarrationServiceError("voice pool catalog has an unexpected shape")
    if root["schema_version"] != VOICE_POOL_CATALOG_SCHEMA_VERSION:
        raise NarrationServiceError("voice pool catalog schema version is unsupported")
    catalog_id = _bounded_text(root["catalog_id"], label="catalog_id", maximum=160)
    if root["catalog_status"] != "taxonomy_only":
        raise NarrationServiceError("voice pool catalog cannot claim an approved asset pack")
    if type(root["required_slot_count"]) is not int or root["required_slot_count"] != 24:
        raise NarrationServiceError("voice pool catalog must contain exactly 24 slots")
    if root["asset_pack_id"] is not None:
        raise NarrationServiceError("T2 catalog must not name an unapproved asset pack")
    for field in ("rights_approved", "quality_approved", "production_ready"):
        if type(root[field]) is not bool or root[field]:
            raise NarrationServiceError(f"{field} must remain exact false before a new gate")

    raw_reasons = root["reason_codes"]
    if type(raw_reasons) is not list or not raw_reasons:
        raise NarrationServiceError("voice pool catalog requires stable no-go reasons")
    reasons: list[str] = []
    for value in raw_reasons:
        if type(value) is not str or not _SAFE_CODE.fullmatch(value):
            raise NarrationServiceError("voice pool catalog reason is not a stable code")
        reasons.append(value)
    if len(reasons) != len(set(reasons)):
        raise NarrationServiceError("voice pool catalog reasons must be unique")
    required_reasons = {
        "GENERIC_VOICE_ASSETS_UNAVAILABLE",
        "GENERIC_VOICE_PACK_NOT_APPROVED",
    }
    if set(reasons) != required_reasons:
        raise NarrationServiceError("voice pool catalog no-go reasons drifted")

    raw_slots = root["slots"]
    if type(raw_slots) is not list or len(raw_slots) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise NarrationServiceError("voice pool catalog must publish 24 taxonomy slots")
    slots: list[VoicePoolCatalogSlot] = []
    for index, value in enumerate(raw_slots):
        item = _record(value, label=f"voice pool slot {index}")
        if set(item) != _SLOT_KEYS:
            raise NarrationServiceError("voice pool slot has an unexpected shape")
        slot_key = _bounded_text(item["slot_key"], label="slot_key", maximum=80)
        category = _bounded_text(item["category"], label="category", maximum=80)
        if not _SAFE_KEY.fullmatch(slot_key) or not _SAFE_KEY.fullmatch(category):
            raise NarrationServiceError("voice pool slot identifiers must be stable keys")
        slots.append(
            VoicePoolCatalogSlot(
                slot_key=slot_key,
                label=_bounded_text(item["label"], label="label", maximum=120),
                category=category,
            )
        )
    if len({item.slot_key for item in slots}) != VOICE_POOL_REQUIRED_SLOT_COUNT:
        raise NarrationServiceError("voice pool catalog slot keys must be unique")

    return VoicePoolCatalog(
        schema_version=VOICE_POOL_CATALOG_SCHEMA_VERSION,
        catalog_id=catalog_id,
        catalog_status="taxonomy_only",
        required_slot_count=VOICE_POOL_REQUIRED_SLOT_COUNT,
        asset_pack_id=None,
        rights_approved=False,
        quality_approved=False,
        production_ready=False,
        reason_codes=tuple(reasons),
        slots=tuple(slots),
        catalog_sha256=canonical_sha256(root),
    )


def load_voice_pool_catalog(path: Path = VOICE_POOL_CATALOG_PATH) -> VoicePoolCatalog:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise NarrationServiceError("voice pool catalog cannot be loaded") from error
    return parse_voice_pool_catalog(raw)


def _unavailable_slots(
    catalog: VoicePoolCatalog,
    *,
    reason_code: str,
) -> list[wire.GenericVoiceSlotResource]:
    return [
        wire.GenericVoiceSlotResource(
            slot_key=item.slot_key,
            label=item.label,
            category=item.category,
            state=wire.GenericVoiceSlotState.MISSING
            if reason_code == "GENERIC_VOICE_ASSETS_UNAVAILABLE"
            else wire.GenericVoiceSlotState.UNAVAILABLE,
            voice_version_id=None,
            enabled=False,
            priority=index,
            reason_code=reason_code,
        )
        for index, item in enumerate(catalog.slots)
    ]


def get_generic_voice_pool(
    store: NarrationStore,
    *,
    novel_id: UUID,
    catalog: VoicePoolCatalog | None = None,
) -> wire.GenericVoicePoolResource:
    """Return the latest complete novel projection, otherwise fail closed."""

    require_local_novel(store, novel_id)
    frozen = catalog or load_voice_pool_catalog()
    rows = store.find_all(
        GenericVoicePool,
        novel_id=novel_id,
        order_by=("version_number",),
    )
    if not rows:
        reason = "GENERIC_VOICE_ASSETS_UNAVAILABLE"
        return wire.GenericVoicePoolResource(
            novel_id=novel_id,
            pool_id=None,
            state=wire.GenericVoicePoolState.MISSING,
            version=0,
            ready_slot_count=0,
            rights_approved_slot_count=0,
            quality_approved_slot_count=0,
            production_ready_slot_count=0,
            slots=_unavailable_slots(frozen, reason_code=reason),
            reason_codes=[reason],
        )

    if len({row.name for row in rows}) != 1:
        raise NarrationServiceError(
            "persisted generic voice pool topology is ambiguous"
        )
    latest = rows[-1]
    if type(latest.version_number) is not int or latest.version_number < 1:
        raise NarrationServiceError("persisted generic voice pool has an invalid version")
    if (
        latest.status == "active"
        and latest.language == "zh-CN"
        and latest.source_pack_version_id is not None
    ):
        pack = store.get(GenericVoicePackVersion, latest.source_pack_version_id)
        pool_slots = store.find_all(
            GenericVoiceSlot,
            pool_id=latest.id,
            order_by=("position",),
        )
        pack_slots = store.find_all(
            GenericVoicePackVersionSlot,
            pack_version_id=latest.source_pack_version_id,
            order_by=("position",),
        )
        expected_keys = tuple(item.slot_key for item in frozen.slots)
        valid = (
            pack is not None
            and pack.workspace_id == LOCAL_WORKSPACE_ID
            and pack.state == "active"
            and pack.validated_slot_count == VOICE_POOL_REQUIRED_SLOT_COUNT
            and len(pool_slots) == VOICE_POOL_REQUIRED_SLOT_COUNT
            and len(pack_slots) == VOICE_POOL_REQUIRED_SLOT_COUNT
            and tuple(item.slot_key for item in pool_slots) == expected_keys
            and tuple(item.slot_key for item in pack_slots) == expected_keys
            and all(
                pool.enabled
                and pool.voice_version_id == source.voice_version_id
                and source.state in {"validated", "reused"}
                and source.rights_approved
                and source.quality_approved
                for pool, source in zip(pool_slots, pack_slots, strict=True)
            )
        )
        if valid:
            return wire.GenericVoicePoolResource(
                novel_id=novel_id,
                pool_id=latest.id,
                state=wire.GenericVoicePoolState.READY,
                version=latest.version_number,
                ready_slot_count=24,
                rights_approved_slot_count=24,
                quality_approved_slot_count=24,
                production_ready_slot_count=24,
                slots=[
                    wire.GenericVoiceSlotResource(
                        slot_key=pool.slot_key,
                        label=catalog_slot.label,
                        category=catalog_slot.category,
                        state=wire.GenericVoiceSlotState.READY,
                        voice_version_id=pool.voice_version_id,
                        enabled=True,
                        priority=pool.priority,
                        reason_code=None,
                    )
                    for pool, catalog_slot in zip(pool_slots, frozen.slots, strict=True)
                ],
                reason_codes=[],
            )
    reason = "GENERIC_VOICE_PACK_NOT_APPROVED"
    return wire.GenericVoicePoolResource(
        novel_id=novel_id,
        pool_id=latest.id,
        state=wire.GenericVoicePoolState.DISABLED,
        version=latest.version_number,
        ready_slot_count=0,
        rights_approved_slot_count=0,
        quality_approved_slot_count=0,
        production_ready_slot_count=0,
        slots=_unavailable_slots(frozen, reason_code=reason),
        reason_codes=[reason],
    )


def get_voice_casting_rules(
    store: NarrationStore,
    *,
    novel_id: UUID,
) -> wire.VoiceCastingRulesResource:
    require_local_novel(store, novel_id)
    existing = store.find_all(VoiceCastingRule, novel_id=novel_id)
    if existing:
        raise GenericCastingUnavailable(
            "persisted casting rules stay hidden until the T3 casting contract"
        )
    return wire.VoiceCastingRulesResource(novel_id=novel_id, version=0, items=[])


@dataclass(frozen=True, slots=True)
class VoicePoolHandlers:
    """Narrow methods for the final T2 settings dispatcher."""

    store: NarrationStore

    def get_pool(self, novel_id: UUID) -> wire.GenericVoicePoolResource:
        return get_generic_voice_pool(self.store, novel_id=novel_id)

    def get_casting_rules(self, novel_id: UUID) -> wire.VoiceCastingRulesResource:
        return get_voice_casting_rules(self.store, novel_id=novel_id)


__all__ = [
    "GenericCastingUnavailable",
    "GenericVoicePackState",
    "NovelGenericVoicePoolProjection",
    "NovelGenericVoiceSlotProjection",
    "VOICE_POOL_CATALOG_PATH",
    "VOICE_POOL_CATALOG_SCHEMA_VERSION",
    "VOICE_POOL_REQUIRED_SLOT_COUNT",
    "VoicePoolCatalog",
    "VoicePoolCatalogSlot",
    "VoicePoolHandlers",
    "WorkspaceGenericVoicePack",
    "WorkspaceGenericVoiceSlot",
    "get_generic_voice_pool",
    "get_voice_casting_rules",
    "load_voice_pool_catalog",
    "parse_voice_pool_catalog",
    "project_active_generic_voice_pack",
]
