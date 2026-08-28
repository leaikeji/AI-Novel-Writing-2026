from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
from typing import TypeVar
from uuid import UUID, uuid4

import pytest

from backend.models import GenericVoicePool, Novel, VoiceCastingRule
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.services import NarrationScopeMismatch, NarrationServiceError
from backend.narration.voice_pool import (
    GenericCastingUnavailable,
    GenericVoicePoolUnavailable,
    VOICE_POOL_CATALOG_PATH,
    VoicePoolHandlers,
    get_generic_voice_pool,
    get_voice_casting_rules,
    load_voice_pool_catalog,
    parse_voice_pool_catalog,
    put_generic_voice_pool,
    put_voice_casting_rules,
)


T = TypeVar("T")
NOVEL_ID = UUID("20000000-0000-4000-8000-000000000001")


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[type[object], list[object]] = defaultdict(list)
        self.add_count = 0
        self.flush_count = 0
        self.locked_novel_reads = 0

    def add(self, row: object) -> None:
        self.add_count += 1
        self.rows[type(row)].append(row)

    def flush(self) -> None:
        self.flush_count += 1

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None:
        if model is Novel and for_update:
            self.locked_novel_reads += 1
        return next(
            (row for row in self.rows[model] if getattr(row, "id") == row_id),
            None,
        )  # type: ignore[return-value]

    def find_one(
        self,
        model: type[T],
        *,
        for_update: bool = False,
        **filters: object,
    ) -> T | None:
        del for_update
        return next(
            (
                row
                for row in self.rows[model]
                if all(getattr(row, key) == value for key, value in filters.items())
            ),
            None,
        )  # type: ignore[return-value]

    def find_all(
        self,
        model: type[T],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[T]:
        del for_update
        rows = [
            row
            for row in self.rows[model]
            if all(getattr(row, key) == value for key, value in filters.items())
        ]
        if order_by:
            rows.sort(key=lambda row: tuple(getattr(row, key) for key in order_by))
        return rows  # type: ignore[return-value]

    def consume_render_publication_context(self, **_values: object) -> None:
        raise AssertionError("voice-pool settings must never publish render output")


def seeded_store(*, local: bool = True) -> MemoryStore:
    store = MemoryStore()
    store.rows[Novel].append(
        Novel(
            id=NOVEL_ID,
            owner_id=LOCAL_OWNER_ID if local else uuid4(),
            workspace_id=LOCAL_WORKSPACE_ID,
            title="测试作品",
        )
    )
    return store


def pool_request() -> wire.PutGenericVoicePoolRequest:
    return wire.PutGenericVoicePoolRequest(
        expected_version=0,
        slots=[
            wire.GenericVoiceSlotSelectionRequest(
                slot_key=f"slot_{index}",
                voice_version_id=uuid4(),
                enabled=True,
                priority=index,
            )
            for index in range(24)
        ],
    )


def test_catalog_is_taxonomy_only_and_contains_24_unique_slots() -> None:
    catalog = load_voice_pool_catalog()

    assert catalog.catalog_status == "taxonomy_only"
    assert catalog.asset_pack_id is None
    assert not catalog.rights_approved
    assert not catalog.quality_approved
    assert not catalog.production_ready
    assert len(catalog.slots) == 24
    assert len({slot.slot_key for slot in catalog.slots}) == 24
    assert len(catalog.catalog_sha256) == 64

    serialized = VOICE_POOL_CATALOG_PATH.read_text(encoding="utf-8").lower()
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert ".wav" not in serialized
    assert "model_id" not in serialized


def test_catalog_rejects_asset_or_approval_claims_without_a_new_gate() -> None:
    raw = json.loads(VOICE_POOL_CATALOG_PATH.read_text(encoding="utf-8"))

    for patch in (
        {"asset_pack_id": "unapproved-pack"},
        {"rights_approved": True},
        {"quality_approved": True},
        {"production_ready": True},
        {"catalog_status": "approved"},
    ):
        candidate = {**raw, **patch}
        with pytest.raises(NarrationServiceError, match="approved|false|asset pack"):
            parse_voice_pool_catalog(candidate)

    short = deepcopy(raw)
    short["slots"].pop()
    with pytest.raises(NarrationServiceError, match="24"):
        parse_voice_pool_catalog(short)


def test_missing_pool_projection_exposes_taxonomy_but_no_voice() -> None:
    store = seeded_store()

    result = get_generic_voice_pool(store, novel_id=NOVEL_ID)

    assert result.state is wire.GenericVoicePoolState.MISSING
    assert result.pool_id is None
    assert result.version == 0
    assert result.ready_slot_count == 0
    assert result.production_ready_slot_count == 0
    assert len(result.slots) == 24
    assert all(slot.state is wire.GenericVoiceSlotState.MISSING for slot in result.slots)
    assert all(slot.voice_version_id is None and not slot.enabled for slot in result.slots)
    assert store.add_count == 0
    assert store.flush_count == 0


def test_persisted_pool_stays_disabled_when_pack_is_not_approved() -> None:
    store = seeded_store()
    old = GenericVoicePool(
        id=uuid4(),
        novel_id=NOVEL_ID,
        name="legacy",
        version_number=1,
        status="draft",
        attributes_json={},
    )
    latest = GenericVoicePool(
        id=uuid4(),
        novel_id=NOVEL_ID,
        name="legacy",
        version_number=2,
        status="ready",
        attributes_json={"untrusted": "must-not-open-capability"},
    )
    store.rows[GenericVoicePool].extend([latest, old])

    result = VoicePoolHandlers(store).get_pool(NOVEL_ID)

    assert result.state is wire.GenericVoicePoolState.DISABLED
    assert result.pool_id == latest.id
    assert result.version == 2
    assert result.production_ready_slot_count == 0
    assert result.reason_codes == ["GENERIC_VOICE_PACK_NOT_APPROVED"]
    assert all(slot.state is wire.GenericVoiceSlotState.UNAVAILABLE for slot in result.slots)


def test_multiple_persisted_pool_identities_fail_closed() -> None:
    store = seeded_store()
    store.rows[GenericVoicePool].extend(
        [
            GenericVoicePool(
                id=uuid4(),
                novel_id=NOVEL_ID,
                name="legacy-a",
                version_number=1,
                status="draft",
                attributes_json={},
            ),
            GenericVoicePool(
                id=uuid4(),
                novel_id=NOVEL_ID,
                name="legacy-b",
                version_number=2,
                status="ready",
                attributes_json={},
            ),
        ]
    )

    with pytest.raises(NarrationServiceError, match="topology is ambiguous"):
        get_generic_voice_pool(store, novel_id=NOVEL_ID)


def test_put_pool_is_fail_closed_and_has_no_partial_write() -> None:
    store = seeded_store()

    with pytest.raises(GenericVoicePoolUnavailable, match="no rights/quality"):
        put_generic_voice_pool(
            store,
            novel_id=NOVEL_ID,
            request=pool_request(),
        )

    assert store.locked_novel_reads == 1
    assert store.add_count == 0
    assert store.flush_count == 0
    assert store.rows[GenericVoicePool] == []


def test_cross_scope_novel_is_rejected_before_pool_projection() -> None:
    store = seeded_store(local=False)

    with pytest.raises(NarrationScopeMismatch):
        get_generic_voice_pool(store, novel_id=NOVEL_ID)


def test_casting_rules_remain_empty_or_unavailable_until_t3() -> None:
    store = seeded_store()

    empty = get_voice_casting_rules(store, novel_id=NOVEL_ID)
    assert empty.version == 0
    assert empty.items == []

    request = wire.PutVoiceCastingRulesRequest(expected_version=0, items=[])
    with pytest.raises(GenericCastingUnavailable, match="before T3-GATE"):
        put_voice_casting_rules(store, novel_id=NOVEL_ID, request=request)

    store.rows[VoiceCastingRule].append(
        VoiceCastingRule(
            id=uuid4(),
            novel_id=NOVEL_ID,
            priority=1,
            version_number=1,
            condition_json={"speaker_kinds": ["anonymous"]},
            action="require_review",
        )
    )
    with pytest.raises(GenericCastingUnavailable, match="stay hidden"):
        VoicePoolHandlers(store).get_casting_rules(NOVEL_ID)


def test_handler_put_methods_preserve_no_go_boundary() -> None:
    handlers = VoicePoolHandlers(seeded_store())

    with pytest.raises(GenericVoicePoolUnavailable):
        handlers.put_pool(NOVEL_ID, pool_request())
    with pytest.raises(GenericCastingUnavailable):
        handlers.put_casting_rules(
            NOVEL_ID,
            wire.PutVoiceCastingRulesRequest(expected_version=0, items=[]),
        )
