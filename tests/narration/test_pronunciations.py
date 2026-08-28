from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TypeVar, cast
from uuid import UUID, uuid4

import pytest

from backend.models import (
    Document,
    MediaAsset,
    Novel,
    PronunciationEntry,
    PronunciationProfile,
    Volume,
)
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.media import MediaConflict, MediaNotEligible, ReferenceRoots
from backend.narration.pronunciations import (
    CacheCandidate,
    CacheCleanupDisabled,
    CacheCleanupStorageFailure,
    CacheCleanupTokenInvalid,
    CacheInventory,
    CacheSnapshotChanged,
    PronunciationSettingsHandler,
    PronunciationValidationError,
    SqlAlchemyNarrationCacheRuntime,
    build_cache_inventory,
    get_pronunciation_profile,
    normalize_pronunciation_source,
    put_pronunciation_profile,
)
from backend.narration.services import NarrationCasConflict, NarrationScopeMismatch
from backend.narration.settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from backend.narration.storage import NarrationStorage


T = TypeVar("T")
NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


class MemoryNarrationStore:
    """Transaction-shaped fake; it performs no database or media I/O."""

    def __init__(self) -> None:
        self.rows: dict[type[object], list[object]] = defaultdict(list)
        self.flush_count = 0

    def add(self, row: object) -> None:
        self.rows[type(row)].append(row)

    def flush(self) -> None:
        self.flush_count += 1

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None:
        del for_update
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
        result = [
            row
            for row in self.rows[model]
            if all(getattr(row, key) == value for key, value in filters.items())
        ]
        if order_by:
            result.sort(key=lambda row: tuple(getattr(row, key) for key in order_by))
        return result  # type: ignore[return-value]


def novel(novel_id: UUID | None = None) -> Novel:
    return Novel(
        id=novel_id or uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        title="book",
        author_name="author",
        description="",
        writing_type="novel",
        audience="general",
        genre="fiction",
        subgenre="",
        idea="",
        template_name="",
        template_data={},
        cover_mode="none",
        cover_image_data="",
        outline_target_chapters=0,
        highlight="",
        background="",
        main_plot="",
        story_ledger_version=1,
        version=1,
    )


def entry(
    novel_id: UUID,
    *,
    source_text: str = "MOSS",
    action: wire.PronunciationAction = wire.PronunciationAction.REPLACE,
    spoken_text: str | None = "摩斯",
    priority: int = 0,
    scope_kind: str = "novel",
    scope_id: UUID | None = None,
) -> wire.PronunciationEntryResource:
    return wire.PronunciationEntryResource(
        source_text=source_text,
        action=action,
        spoken_text=spoken_text,
        language="zh-CN",
        scope_kind=scope_kind,
        scope_id=scope_id or novel_id,
        priority=priority,
    )


def request(
    expected_version: int,
    entries: list[wire.PronunciationEntryResource],
) -> wire.PutPronunciationProfileRequest:
    return wire.PutPronunciationProfileRequest(
        expected_version=expected_version,
        entries=entries,
    )


def capability(enabled: bool) -> wire.FeatureCapability:
    return wire.FeatureCapability(
        key=wire.CapabilityKey.CACHE_CLEANUP,
        state=(wire.CapabilityState.ENABLED if enabled else wire.CapabilityState.HOLD),
        visible=True,
        actionable=enabled,
        reason_code=None if enabled else "T2_GATE_REQUIRED",
        required_gate=None if enabled else "T2-GATE",
    )


def test_missing_profile_is_exact_empty_version_zero() -> None:
    store = MemoryNarrationStore()
    book = novel()
    store.add(book)

    resource = get_pronunciation_profile(store, novel_id=book.id)

    assert resource.novel_id == book.id
    assert resource.profile_id is None
    assert resource.version == 0
    assert resource.fingerprint is None
    assert resource.entries == []


def test_put_is_cas_idempotent_and_creates_immutable_full_versions() -> None:
    store = MemoryNarrationStore()
    book = novel()
    store.add(book)
    first_request = request(
        0,
        [
            entry(book.id),
            entry(
                book.id,
                source_text="[END]",
                action=wire.PronunciationAction.SKIP,
                spoken_text=None,
                priority=2,
            ),
        ],
    )

    first = put_pronunciation_profile(store, novel_id=book.id, request=first_request)
    assert first.version == 1
    assert first.profile_id is not None
    assert first.fingerprint is not None
    assert len(first.entries) == 2
    assert next(item for item in first.entries if item.action == "skip").spoken_text is None
    assert len(store.rows[PronunciationProfile]) == 1
    assert len(store.rows[PronunciationEntry]) == 2

    idempotent = put_pronunciation_profile(
        store,
        novel_id=book.id,
        request=request(1, list(first_request.entries)),
    )
    assert idempotent.profile_id == first.profile_id
    assert len(store.rows[PronunciationProfile]) == 1
    assert len(store.rows[PronunciationEntry]) == 2

    old_profile = cast(PronunciationProfile, store.rows[PronunciationProfile][0])
    old_entries = tuple(
        (
            cast(PronunciationEntry, row).id,
            cast(PronunciationEntry, row).source_text,
            cast(PronunciationEntry, row).spoken_text,
        )
        for row in store.rows[PronunciationEntry]
    )
    second = put_pronunciation_profile(
        store,
        novel_id=book.id,
        request=request(1, [entry(book.id, spoken_text="MOSS 引擎")]),
    )

    assert second.version == 2
    assert second.profile_id != first.profile_id
    assert old_profile.version_number == 1
    assert tuple(
        (
            cast(PronunciationEntry, row).id,
            cast(PronunciationEntry, row).source_text,
            cast(PronunciationEntry, row).spoken_text,
        )
        for row in store.rows[PronunciationEntry][:2]
    ) == old_entries

    with pytest.raises(PronunciationValidationError, match="historical"):
        put_pronunciation_profile(
            store,
            novel_id=book.id,
            request=request(2, list(first_request.entries)),
        )


def test_put_rejects_stale_version_and_handler_reports_current_version() -> None:
    store = MemoryNarrationStore()
    book = novel()
    store.add(book)
    put_pronunciation_profile(
        store,
        novel_id=book.id,
        request=request(0, [entry(book.id)]),
    )

    with pytest.raises(NarrationCasConflict):
        put_pronunciation_profile(
            store,
            novel_id=book.id,
            request=request(0, [entry(book.id, spoken_text="新发音")]),
        )

    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE,
        novel_id=book.id,
        payload=request(0, [entry(book.id, spoken_text="新发音")]),
    )
    with pytest.raises(NarrationApiFault) as caught:
        PronunciationSettingsHandler(store).dispatch(command)
    assert caught.value.code is wire.NarrationErrorCode.VERSION_CONFLICT
    assert caught.value.current_version == 1


def test_scope_duplicate_and_action_validation_fail_closed() -> None:
    store = MemoryNarrationStore()
    book = novel()
    other = novel()
    store.add(book)
    store.add(other)
    foreign_chapter = Document(
        id=uuid4(),
        novel_id=other.id,
        kind="chapter",
        title="foreign",
        position=1,
        status="draft",
        version=1,
    )
    local_volume = Volume(
        id=uuid4(), novel_id=book.id, title="v1", position=1, version=1,
    )
    store.add(foreign_chapter)
    store.add(local_volume)

    with pytest.raises(NarrationScopeMismatch):
        put_pronunciation_profile(
            store,
            novel_id=book.id,
            request=request(
                0,
                [
                    entry(
                        book.id,
                        scope_kind="chapter",
                        scope_id=foreign_chapter.id,
                    )
                ],
            ),
        )

    assert normalize_pronunciation_source("ＡＩ  Agent") == "ai agent"
    with pytest.raises(PronunciationValidationError, match="duplicate"):
        put_pronunciation_profile(
            store,
            novel_id=book.id,
            request=request(
                0,
                [
                    entry(book.id, source_text="ＡＩ  Agent"),
                    entry(book.id, source_text="ai agent", spoken_text="人工智能"),
                ],
            ),
        )

    # A different priority is an explicit deterministic override, not a duplicate.
    valid = put_pronunciation_profile(
        store,
        novel_id=book.id,
        request=request(
            0,
            [
                entry(
                    book.id,
                    source_text="AI",
                    scope_kind="volume",
                    scope_id=local_volume.id,
                ),
                entry(
                    book.id,
                    source_text="ai",
                    priority=10,
                    scope_kind="volume",
                    scope_id=local_volume.id,
                    spoken_text="人工智能",
                ),
            ],
        ),
    )
    assert valid.version == 1


def test_service_rechecks_replace_skip_and_language_even_for_internal_models() -> None:
    store = MemoryNarrationStore()
    book = novel()
    store.add(book)
    invalid_skip = wire.PronunciationEntryResource.model_construct(
        entry_id=None,
        source_text="silence",
        action=wire.PronunciationAction.SKIP,
        spoken_text="must-not-exist",
        language="zh-CN",
        scope_kind="novel",
        scope_id=book.id,
        priority=0,
    )
    with pytest.raises(PronunciationValidationError, match="skip"):
        put_pronunciation_profile(
            store,
            novel_id=book.id,
            request=wire.PutPronunciationProfileRequest.model_construct(
                expected_version=0,
                entries=[invalid_skip],
            ),
        )

    invalid_language = wire.PronunciationEntryResource.model_construct(
        entry_id=None,
        source_text="MOSS",
        action=wire.PronunciationAction.REPLACE,
        spoken_text="摩斯",
        language="not a tag",
        scope_kind="novel",
        scope_id=book.id,
        priority=0,
    )
    with pytest.raises(PronunciationValidationError, match="language"):
        put_pronunciation_profile(
            store,
            novel_id=book.id,
            request=wire.PutPronunciationProfileRequest.model_construct(
                expected_version=0,
                entries=[invalid_language],
            ),
        )


def media_asset(
    novel_id: UUID,
    *,
    asset_class: str,
    byte_size: int,
    marked: bool = False,
    generation: int = 0,
) -> MediaAsset:
    asset_id = uuid4()
    return MediaAsset(
        id=asset_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        source_revision_id=None,
        kind=f"narration_{asset_class}",
        asset_class=asset_class,
        mime_type="audio/mp4",
        byte_size=byte_size,
        duration_ms=100,
        sample_rate=24_000,
        channels=1,
        storage_backend="local",
        state="ready",
        retention_policy="temporary",
        checksum_algorithm="sha256",
        validation_json={},
        verified_at=NOW,
        last_accessed_at=NOW - timedelta(days=10),
        expires_at=NOW - timedelta(days=9),
        deleted_at=None,
        gc_generation=generation,
        gc_marked_at=NOW - timedelta(days=8) if marked else None,
        storage_path=f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{SHA_A}.m4a",
        content_hash=SHA_A,
        metadata_json={},
        created_at=NOW - timedelta(days=20),
    )


def test_cache_inventory_is_disjoint_and_never_reclaims_protected_assets() -> None:
    book_id = uuid4()
    source = media_asset(book_id, asset_class="source", byte_size=100)
    locked = media_asset(book_id, asset_class="preview", byte_size=200, marked=True)
    referenced = media_asset(
        book_id, asset_class="segment_playback", byte_size=300, marked=True,
    )
    reclaimable = media_asset(
        book_id,
        asset_class="segment_master",
        byte_size=400,
        marked=True,
        generation=7,
    )
    fresh = media_asset(
        book_id, asset_class="segment_playback", byte_size=500, marked=False,
    )
    roots = ReferenceRoots(
        locked_voice_assets=frozenset({locked.id}),
        manifest_assets=frozenset({referenced.id}),
    )

    inventory = build_cache_inventory(
        novel_id=book_id,
        assets=[fresh, source, referenced, reclaimable, locked],
        roots=roots,
        pending_job_count=2,
        now=NOW,
    )

    assert inventory.source_asset_bytes == 100
    assert inventory.locked_voice_bytes == 200
    assert inventory.referenced_edition_bytes == 300
    assert inventory.derived_cache_bytes == 900
    assert inventory.reclaimable_bytes == 400
    assert inventory.pending_job_count == 2
    assert inventory.protected_asset_count == 4
    assert [(item.asset_id, item.generation) for item in inventory.candidates] == [
        (reclaimable.id, 7)
    ]
    assert len(inventory.snapshot_fingerprint) == 64

    changed = build_cache_inventory(
        novel_id=book_id,
        assets=[fresh, source, referenced, reclaimable, locked],
        roots=ReferenceRoots(
            locked_voice_assets=frozenset({locked.id}),
            manifest_assets=frozenset({referenced.id, reclaimable.id}),
        ),
        pending_job_count=2,
        now=NOW,
    )
    assert changed.snapshot_fingerprint != inventory.snapshot_fingerprint
    assert changed.reclaimable_bytes == 0


def test_cache_fingerprint_changes_when_gc_grace_decision_changes() -> None:
    book_id = uuid4()
    derivative = media_asset(
        book_id,
        asset_class="segment_master",
        byte_size=400,
        marked=True,
        generation=3,
    )
    derivative.gc_marked_at = NOW - timedelta(days=7) + timedelta(seconds=1)

    before = build_cache_inventory(
        novel_id=book_id,
        assets=[derivative],
        roots=ReferenceRoots(),
        pending_job_count=0,
        now=NOW,
    )
    after = build_cache_inventory(
        novel_id=book_id,
        assets=[derivative],
        roots=ReferenceRoots(),
        pending_job_count=0,
        now=NOW + timedelta(seconds=2),
    )

    assert before.reclaimable_bytes == 0
    assert after.reclaimable_bytes == 400
    assert before.snapshot_fingerprint != after.snapshot_fingerprint


class InventoryRuntime(SqlAlchemyNarrationCacheRuntime):
    def __init__(
        self,
        inventory: CacheInventory,
        *,
        enabled: bool,
        clock: datetime = NOW,
    ) -> None:
        self.inventory = inventory
        super().__init__(
            session_factory=cast(object, lambda: None),
            storage=cast(NarrationStorage, object()),
            cleanup_capability=capability(enabled),
            token_secret=b"t" * 32,
            tombstone_digest_key_id="test-key",
            tombstone_digest_key=b"d" * 32,
            disk_usage_provider=lambda: (2_000, 10_000),
            clock=lambda: clock,
        )

    def _inventory(self, novel_id: UUID) -> CacheInventory:
        assert novel_id == self.inventory.novel_id
        return self.inventory


def empty_inventory(novel_id: UUID, fingerprint: str = SHA_A) -> CacheInventory:
    return CacheInventory(
        novel_id=novel_id,
        snapshot_fingerprint=fingerprint,
        source_asset_bytes=100,
        locked_voice_bytes=200,
        referenced_edition_bytes=300,
        derived_cache_bytes=0,
        reclaimable_bytes=0,
        pending_job_count=0,
        protected_asset_count=3,
        candidates=(),
    )


def candidate_inventory(novel_id: UUID) -> CacheInventory:
    return CacheInventory(
        novel_id=novel_id,
        snapshot_fingerprint=SHA_A,
        source_asset_bytes=100,
        locked_voice_bytes=200,
        referenced_edition_bytes=300,
        derived_cache_bytes=400,
        reclaimable_bytes=400,
        pending_job_count=0,
        protected_asset_count=3,
        candidates=(CacheCandidate(asset_id=uuid4(), generation=7, byte_size=400),),
    )


def test_cache_status_is_readable_on_hold_but_preview_and_execute_fail_closed() -> None:
    book_id = uuid4()
    runtime = InventoryRuntime(empty_inventory(book_id), enabled=False)

    status = runtime.status(book_id)
    assert status.disk_free_bytes == 2_000
    assert status.cleanup_capability.state is wire.CapabilityState.HOLD
    with pytest.raises(CacheCleanupDisabled):
        runtime.preview(
            book_id,
            wire.PreviewNarrationCacheCleanupRequest(snapshot_fingerprint=SHA_A),
        )
    with pytest.raises(CacheCleanupDisabled):
        runtime.execute(
            book_id,
            wire.ExecuteNarrationCacheCleanupRequest(
                snapshot_fingerprint=SHA_A,
                cleanup_token="x" * 32,
                confirmed=True,
            ),
        )

    handler = PronunciationSettingsHandler(MemoryNarrationStore(), cache_runtime=runtime)
    with pytest.raises(NarrationApiFault) as caught:
        handler.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
                novel_id=book_id,
                payload=wire.PreviewNarrationCacheCleanupRequest(
                    snapshot_fingerprint=SHA_A,
                ),
            )
        )
    assert caught.value.code is wire.NarrationErrorCode.CAPABILITY_DISABLED
    assert caught.value.capability is wire.CapabilityKey.CACHE_CLEANUP


def test_cache_preview_token_and_snapshot_are_both_required_for_execute() -> None:
    book_id = uuid4()
    runtime = InventoryRuntime(empty_inventory(book_id), enabled=True)

    with pytest.raises(CacheSnapshotChanged):
        runtime.preview(
            book_id,
            wire.PreviewNarrationCacheCleanupRequest(snapshot_fingerprint=SHA_B),
        )
    preview = runtime.preview(
        book_id,
        wire.PreviewNarrationCacheCleanupRequest(snapshot_fingerprint=SHA_A),
    )
    tampered_token = preview.cleanup_token[:-1] + (
        "0" if preview.cleanup_token[-1] != "0" else "1"
    )
    with pytest.raises(CacheCleanupTokenInvalid):
        runtime.execute(
            book_id,
            wire.ExecuteNarrationCacheCleanupRequest(
                snapshot_fingerprint=SHA_A,
                cleanup_token=tampered_token,
                confirmed=True,
            ),
        )

    runtime.inventory = empty_inventory(book_id, SHA_B)
    with pytest.raises(CacheSnapshotChanged):
        runtime.execute(
            book_id,
            wire.ExecuteNarrationCacheCleanupRequest(
                snapshot_fingerprint=SHA_A,
                cleanup_token=preview.cleanup_token,
                confirmed=True,
            ),
        )

    runtime.inventory = empty_inventory(book_id)
    result = runtime.execute(
        book_id,
        wire.ExecuteNarrationCacheCleanupRequest(
            snapshot_fingerprint=SHA_A,
            cleanup_token=preview.cleanup_token,
            confirmed=True,
        ),
    )
    assert result.deleted_asset_count == 0
    assert result.reclaimed_bytes == 0
    assert result.source_asset_deleted_count == 0
    assert result.locked_voice_deleted_count == 0
    assert result.referenced_asset_deleted_count == 0


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session

    def __enter__(self) -> None:
        assert self.session.open
        assert not self.session.in_transaction
        self.session.in_transaction = True

    def __exit__(self, *_args: object) -> None:
        self.session.in_transaction = False


class FakeSession:
    def __init__(self) -> None:
        self.open = False
        self.in_transaction = False

    def __enter__(self) -> "FakeSession":
        self.open = True
        return self

    def __exit__(self, *_args: object) -> None:
        assert not self.in_transaction
        self.open = False

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)


def test_cache_physical_delete_is_outside_transactions_and_finalize_failure_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = uuid4()
    runtime = InventoryRuntime(candidate_inventory(book_id), enabled=True)
    sessions: list[FakeSession] = []

    def session_factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    runtime.session_factory = cast(object, session_factory)
    plan = SimpleNamespace(byte_size=400)

    def begin(session: FakeSession, *_args: object, **_kwargs: object) -> object:
        assert session.in_transaction
        return plan

    def physical(_storage: object, supplied_plan: object) -> object:
        assert supplied_plan is plan
        assert sessions and all(not session.in_transaction for session in sessions)
        return SimpleNamespace(removed=True)

    def finalize(session: FakeSession, *_args: object, **_kwargs: object) -> None:
        assert session.in_transaction
        raise MediaConflict("forced finalization race")

    monkeypatch.setattr("backend.narration.pronunciations.begin_gc_deletion_in_session", begin)
    monkeypatch.setattr("backend.narration.pronunciations.execute_gc_delete", physical)
    monkeypatch.setattr("backend.narration.pronunciations.finalize_gc_deletion_in_session", finalize)
    cleanup_preview = runtime.preview(
        book_id,
        wire.PreviewNarrationCacheCleanupRequest(snapshot_fingerprint=SHA_A),
    )

    with pytest.raises(CacheCleanupStorageFailure, match="finalization"):
        runtime.execute(
            book_id,
            wire.ExecuteNarrationCacheCleanupRequest(
                snapshot_fingerprint=SHA_A,
                cleanup_token=cleanup_preview.cleanup_token,
                confirmed=True,
            ),
        )

    assert len(sessions) == 2
    assert all(not session.open and not session.in_transaction for session in sessions)


def test_cache_reference_race_skips_before_physical_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book_id = uuid4()
    runtime = InventoryRuntime(candidate_inventory(book_id), enabled=True)
    sessions: list[FakeSession] = []

    def session_factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    runtime.session_factory = cast(object, session_factory)

    def begin(*_args: object, **_kwargs: object) -> object:
        raise MediaNotEligible("new manifest reference")

    physical = cast(object, pytest.fail)
    monkeypatch.setattr("backend.narration.pronunciations.begin_gc_deletion_in_session", begin)
    monkeypatch.setattr("backend.narration.pronunciations.execute_gc_delete", physical)
    cleanup_preview = runtime.preview(
        book_id,
        wire.PreviewNarrationCacheCleanupRequest(snapshot_fingerprint=SHA_A),
    )
    cleanup_result = runtime.execute(
        book_id,
        wire.ExecuteNarrationCacheCleanupRequest(
            snapshot_fingerprint=SHA_A,
            cleanup_token=cleanup_preview.cleanup_token,
            confirmed=True,
        ),
    )

    assert cleanup_result.deleted_asset_count == 0
    assert cleanup_result.reclaimed_bytes == 0
    assert len(sessions) == 1


def test_handler_default_cache_runtime_is_structured_storage_failure() -> None:
    store = MemoryNarrationStore()
    book = novel()
    store.add(book)
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.GET_CACHE_STATUS,
        novel_id=book.id,
    )

    with pytest.raises(NarrationApiFault) as caught:
        PronunciationSettingsHandler(store).dispatch(command)
    assert caught.value.code is wire.NarrationErrorCode.STORAGE_UNAVAILABLE
    assert caught.value.retryable is True
    assert caught.value.capability is wire.CapabilityKey.CACHE_CLEANUP


def test_handler_rejects_unowned_operation_and_missing_novel_scope() -> None:
    handler = PronunciationSettingsHandler(MemoryNarrationStore())
    with pytest.raises(KeyError):
        handler.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.GET_SETTINGS,
                novel_id=uuid4(),
            )
        )
    with pytest.raises(NarrationApiFault) as caught:
        handler.dispatch(
            NarrationSettingsApiCommand(
                operation=NarrationSettingsOperation.GET_PRONUNCIATION_PROFILE,
            )
        )
    assert caught.value.code is wire.NarrationErrorCode.REQUEST_VALIDATION_FAILED
