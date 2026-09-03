from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from typing import TypeVar
from uuid import UUID, uuid4, uuid5

import pytest

from backend.models import GenericVoicePool, Novel, VoiceCastingRule
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
from backend.narration.services import NarrationScopeMismatch, NarrationServiceError
from backend.narration.voice_generator_runtime import EXPECTED_RUNTIME_FINGERPRINT
from backend.narration.voice_pool import (
    GenericCastingUnavailable,
    GenericVoicePackState,
    VOICE_POOL_CATALOG_PATH,
    VoicePoolHandlers,
    WorkspaceGenericVoicePack,
    WorkspaceGenericVoiceSlot,
    get_generic_voice_pool,
    get_voice_casting_rules,
    load_voice_pool_catalog,
    parse_voice_pool_catalog,
    project_active_generic_voice_pack,
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


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def workspace_pack(
    *,
    state: GenericVoicePackState = GenericVoicePackState.ACTIVE,
    workspace_id: UUID = LOCAL_WORKSPACE_ID,
    count: int = 24,
    rejected_index: int | None = None,
) -> WorkspaceGenericVoicePack:
    catalog = load_voice_pool_catalog()
    slots = tuple(
        WorkspaceGenericVoiceSlot(
            slot_key=item.slot_key,
            profile_id=uuid5(UUID(int=1), f"profile:{item.slot_key}"),
            voice_version_id=uuid5(UUID(int=1), f"version:{item.slot_key}"),
            workspace_id=workspace_id,
            profile_novel_id=None,
            language="zh-CN",
            source_kind="voice_generator",
            design_fingerprint=_digest(f"design:{item.slot_key}"),
            generator_model_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
            nano_model_fingerprint=EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256,
            reference_audio_sha256=_digest(f"reference:{item.slot_key}"),
            validation_audio_sha256=_digest(f"validation:{item.slot_key}"),
            rights_approved=True,
            quality_approved=True,
            rejected=index == rejected_index,
        )
        for index, item in enumerate(catalog.slots[:count])
    )
    return WorkspaceGenericVoicePack(
        pack_version_id=uuid4(),
        workspace_id=workspace_id,
        language="zh-CN",
        state=state,
        taxonomy_sha256=catalog.catalog_sha256,
        slots=slots,
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


def test_cross_scope_novel_is_rejected_before_pool_projection() -> None:
    store = seeded_store(local=False)

    with pytest.raises(NarrationScopeMismatch):
        get_generic_voice_pool(store, novel_id=NOVEL_ID)


def test_casting_rules_remain_empty_or_unavailable_until_t3() -> None:
    store = seeded_store()

    empty = get_voice_casting_rules(store, novel_id=NOVEL_ID)
    assert empty.version == 0
    assert empty.items == []

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

def test_active_workspace_pack_projects_all_24_slots_in_taxonomy_order() -> None:
    catalog = load_voice_pool_catalog()
    pack = workspace_pack()

    result = project_active_generic_voice_pack(
        novel_id=NOVEL_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        pack=pack,
        catalog=catalog,
    )

    assert result.novel_id == NOVEL_ID
    assert result.workspace_id == LOCAL_WORKSPACE_ID
    assert result.source_pack_version_id == pack.pack_version_id
    assert result.language == "zh-CN"
    assert len(result.slots) == 24
    assert tuple(item.slot_key for item in result.slots) == tuple(
        item.slot_key for item in catalog.slots
    )
    assert tuple(item.position for item in result.slots) == tuple(range(24))
    assert all(item.labels[-1] == "zh-CN" for item in result.slots)


@pytest.mark.parametrize(
    ("pack", "reason"),
    [
        (workspace_pack(count=23), "GENERIC_VOICE_PACK_INCOMPLETE"),
        (
            workspace_pack(state=GenericVoicePackState.BUILDING),
            "GENERIC_VOICE_PACK_NOT_READY",
        ),
        (
            workspace_pack(state=GenericVoicePackState.RETIRED_FOR_NEW_USE),
            "GENERIC_VOICE_PACK_RETIRED",
        ),
        (workspace_pack(rejected_index=4), "GENERIC_VOICE_PACK_SLOT_REJECTED"),
    ],
)
def test_partial_retired_or_rejected_pack_cannot_project(
    pack: WorkspaceGenericVoicePack,
    reason: str,
) -> None:
    with pytest.raises(NarrationServiceError, match=reason):
        project_active_generic_voice_pack(
            novel_id=NOVEL_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            pack=pack,
        )


def test_workspace_pack_projection_rejects_cross_scope_and_taxonomy_drift() -> None:
    other_workspace = uuid4()
    with pytest.raises(NarrationServiceError, match="SCOPE_MISMATCH"):
        project_active_generic_voice_pack(
            novel_id=NOVEL_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            pack=workspace_pack(workspace_id=other_workspace),
        )

    pack = workspace_pack()
    drifted = WorkspaceGenericVoicePack(
        pack_version_id=pack.pack_version_id,
        workspace_id=pack.workspace_id,
        language=pack.language,
        state=pack.state,
        taxonomy_sha256="0" * 64,
        slots=pack.slots,
    )
    with pytest.raises(NarrationServiceError, match="VERSION_CONFLICT"):
        project_active_generic_voice_pack(
            novel_id=NOVEL_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            pack=drifted,
        )
