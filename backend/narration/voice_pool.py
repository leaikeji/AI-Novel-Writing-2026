"""Fail-closed generic voice-pool projections for T2.

The bundled JSON is a 24-slot product taxonomy, not an audio asset pack.  T0-E
found no pack with sufficient redistribution, quality, and production evidence,
so this module may report coverage but must never create or auto-bind voices.
The caller owns the database transaction; these functions do no media/model I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Final
from uuid import UUID

from ..models import GenericVoicePool, VoiceCastingRule

from . import schemas as wire
from .services import (
    NarrationServiceError,
    NarrationStore,
    canonical_sha256,
    require_local_novel,
)


VOICE_POOL_CATALOG_SCHEMA_VERSION: Final = "generic-voice-pack-catalog/1"
VOICE_POOL_CATALOG_PATH: Final = Path(__file__).with_name("resources") / "voice_pool_v1.json"
VOICE_POOL_REQUIRED_SLOT_COUNT: Final = 24
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
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


class GenericVoicePoolUnavailable(NarrationServiceError):
    """The approved production pack/capability does not exist."""


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
    """Return truth about the missing pack without creating or binding rows."""

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


def put_generic_voice_pool(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.PutGenericVoicePoolRequest,
) -> wire.GenericVoicePoolResource:
    del request
    require_local_novel(store, novel_id, for_update=True)
    load_voice_pool_catalog()
    raise GenericVoicePoolUnavailable(
        "no rights/quality/production-approved 24-slot voice pack is available"
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


def put_voice_casting_rules(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.PutVoiceCastingRulesRequest,
) -> wire.VoiceCastingRulesResource:
    del request
    require_local_novel(store, novel_id, for_update=True)
    raise GenericCastingUnavailable(
        "automatic generic casting remains unavailable before T3-GATE"
    )


@dataclass(frozen=True, slots=True)
class VoicePoolHandlers:
    """Narrow methods for the final T2 settings dispatcher."""

    store: NarrationStore

    def get_pool(self, novel_id: UUID) -> wire.GenericVoicePoolResource:
        return get_generic_voice_pool(self.store, novel_id=novel_id)

    def put_pool(
        self,
        novel_id: UUID,
        request: wire.PutGenericVoicePoolRequest,
    ) -> wire.GenericVoicePoolResource:
        return put_generic_voice_pool(self.store, novel_id=novel_id, request=request)

    def get_casting_rules(self, novel_id: UUID) -> wire.VoiceCastingRulesResource:
        return get_voice_casting_rules(self.store, novel_id=novel_id)

    def put_casting_rules(
        self,
        novel_id: UUID,
        request: wire.PutVoiceCastingRulesRequest,
    ) -> wire.VoiceCastingRulesResource:
        return put_voice_casting_rules(self.store, novel_id=novel_id, request=request)


__all__ = [
    "GenericCastingUnavailable",
    "GenericVoicePoolUnavailable",
    "VOICE_POOL_CATALOG_PATH",
    "VOICE_POOL_CATALOG_SCHEMA_VERSION",
    "VOICE_POOL_REQUIRED_SLOT_COUNT",
    "VoicePoolCatalog",
    "VoicePoolCatalogSlot",
    "VoicePoolHandlers",
    "get_generic_voice_pool",
    "get_voice_casting_rules",
    "load_voice_pool_catalog",
    "parse_voice_pool_catalog",
    "put_generic_voice_pool",
    "put_voice_casting_rules",
]
