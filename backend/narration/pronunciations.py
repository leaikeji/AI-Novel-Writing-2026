"""Versioned pronunciation profiles and fail-closed cache cleanup handlers.

Pronunciation PUT is a full CAS replacement that creates a new immutable
profile and entry set.  Existing profiles/entries are never updated or deleted,
so historical Editions retain the profile they froze.

Cache inspection and deletion are separated behind ``NarrationCacheRuntime``.
The production runtime uses independent short transactions around T1-E's GC
primitives and performs physical unlink outside every database transaction.
Until T2-GATE injects that runtime and enables ``cache_cleanup``, cache mutation
fails closed instead of reporting fabricated bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import re
from typing import Callable, Final, Protocol, TypeVar
import unicodedata
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    Document,
    MediaAsset,
    Novel,
    PronunciationEntry,
    PronunciationProfile,
    Volume,
)

from . import schemas as wire
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .disk_guard import secure_media_disk_usage
from .media import (
    ACTIVE_JOB_STATES,
    DERIVABLE_CLASSES,
    GcPolicy,
    MediaConflict,
    MediaNotEligible,
    MediaPolicyError,
    ReferenceRoots,
    begin_gc_deletion_in_session,
    evaluate_gc,
    execute_gc_delete,
    finalize_gc_deletion_in_session,
    load_reference_roots_in_session,
)
from .services import (
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    SqlAlchemyNarrationStore,
    canonical_sha256,
    require_local_novel,
)
from .settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from .storage import NarrationStorage, StorageError


PRONUNCIATION_PROFILE_FINGERPRINT_SCHEMA: Final = "pronunciation-profile/1"
CACHE_SNAPSHOT_SCHEMA: Final = "narration-cache-snapshot/1"
CACHE_TOKEN_VERSION: Final = "v1"
CACHE_TOKEN_TTL: Final = timedelta(minutes=5)
CACHE_ROOT_BATCH_SIZE: Final = 1_000
PRONUNCIATION_OPERATIONS: Final = frozenset(
    {
        NarrationSettingsOperation.GET_PRONUNCIATION_PROFILE,
        NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE,
        NarrationSettingsOperation.GET_CACHE_STATUS,
        NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP,
        NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP,
    }
)
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}$")
_TOKEN = re.compile(r"^v1\.([0-9]{1,12})\.([a-f0-9]{32})\.([a-f0-9]{64})\.([a-f0-9]{64})$")
_PayloadModel = TypeVar("_PayloadModel", bound=BaseModel)
SessionFactory = Callable[[], Session]
DiskUsageProvider = Callable[[], tuple[int, int]]


class PronunciationValidationError(NarrationServiceError):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class CacheRuntimeUnavailable(NarrationServiceError):
    pass


class CacheCleanupDisabled(NarrationServiceError):
    pass


class CacheSnapshotChanged(NarrationServiceError):
    pass


class CacheCleanupTokenInvalid(NarrationServiceError):
    pass


class CacheCleanupStorageFailure(NarrationServiceError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedPronunciationEntry:
    source_text: str
    normalized_source: str
    action: wire.PronunciationAction
    spoken_text: str
    language: str
    scope_kind: str
    scope_id: UUID
    priority: int

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "language": self.language,
            "normalized_source": self.normalized_source,
            "priority": self.priority,
            "scope_id": str(self.scope_id),
            "scope_kind": self.scope_kind,
            "source_text": self.source_text,
            "spoken_text": None
            if self.action is wire.PronunciationAction.SKIP
            else self.spoken_text,
        }


def _bounded_clean_text(
    value: str,
    *,
    field: str,
    maximum: int,
) -> str:
    if type(value) is not str:
        raise PronunciationValidationError(f"{field} must be text", field=field)
    cleaned = value.strip()
    if (
        not cleaned
        or len(cleaned) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in cleaned)
    ):
        raise PronunciationValidationError(
            f"{field} must be bounded non-control text",
            field=field,
        )
    return cleaned


def normalize_pronunciation_source(value: str) -> str:
    source = _bounded_clean_text(value, field="source_text", maximum=160)
    normalized = " ".join(unicodedata.normalize("NFKC", source).casefold().split())
    if not normalized:
        raise PronunciationValidationError(
            "source_text normalizes to an empty value",
            field="source_text",
        )
    return normalized


def _validate_scope(
    store: NarrationStore,
    *,
    novel_id: UUID,
    scope_kind: str,
    scope_id: UUID,
) -> None:
    if scope_kind == "novel":
        if scope_id != novel_id:
            raise NarrationScopeMismatch("novel pronunciation scope id mismatch")
        return
    if scope_kind == "volume":
        volume = store.get(Volume, scope_id, for_update=True)
        if volume is None:
            raise NarrationNotFound("pronunciation volume scope not found")
        if volume.novel_id != novel_id:
            raise NarrationScopeMismatch("pronunciation volume belongs to another novel")
        return
    if scope_kind == "chapter":
        document = store.get(Document, scope_id, for_update=True)
        if document is None:
            raise NarrationNotFound("pronunciation chapter scope not found")
        if document.novel_id != novel_id or document.kind != "chapter":
            raise NarrationScopeMismatch("pronunciation chapter belongs to another scope")
        return
    raise PronunciationValidationError("unsupported pronunciation scope", field="scope_kind")


def prepare_pronunciation_entries(
    store: NarrationStore,
    *,
    novel_id: UUID,
    entries: list[wire.PronunciationEntryResource],
) -> tuple[PreparedPronunciationEntry, ...]:
    prepared: list[PreparedPronunciationEntry] = []
    scopes = sorted(
        {(entry.scope_kind, entry.scope_id) for entry in entries},
        key=lambda item: (item[0], str(item[1])),
    )
    for scope_kind, scope_id in scopes:
        _validate_scope(
            store,
            novel_id=novel_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
        )
    for index, entry in enumerate(entries):
        source = _bounded_clean_text(
            entry.source_text,
            field=f"entries[{index}].source_text",
            maximum=160,
        )
        language = entry.language.strip()
        if not _LANGUAGE.fullmatch(language):
            raise PronunciationValidationError(
                "language must be a conservative BCP-47 tag",
                field=f"entries[{index}].language",
            )
        if entry.action is wire.PronunciationAction.REPLACE:
            if entry.spoken_text is None:
                raise PronunciationValidationError(
                    "replace requires spoken_text",
                    field=f"entries[{index}].spoken_text",
                )
            spoken = _bounded_clean_text(
                entry.spoken_text,
                field=f"entries[{index}].spoken_text",
                maximum=240,
            )
        else:
            if entry.spoken_text is not None:
                raise PronunciationValidationError(
                    "skip cannot carry spoken_text",
                    field=f"entries[{index}].spoken_text",
                )
            # The T1 schema has a non-null spoken_text column.  Exact empty text
            # is the server-owned representation for the frozen skip action.
            spoken = ""
        prepared.append(
            PreparedPronunciationEntry(
                source_text=source,
                normalized_source=normalize_pronunciation_source(source),
                action=entry.action,
                spoken_text=spoken,
                language=language,
                scope_kind=entry.scope_kind,
                scope_id=entry.scope_id,
                priority=entry.priority,
            )
        )
    prepared.sort(
        key=lambda item: (
            item.scope_kind,
            str(item.scope_id),
            item.normalized_source,
            -item.priority,
            item.action.value,
            item.spoken_text,
        )
    )
    keys = [
        (item.scope_kind, item.scope_id, item.normalized_source, item.priority)
        for item in prepared
    ]
    if len(keys) != len(set(keys)):
        raise PronunciationValidationError(
            "pronunciation entries contain a duplicate scope/source/priority match",
            field="entries",
        )
    return tuple(prepared)


def pronunciation_fingerprint(
    novel_id: UUID,
    entries: tuple[PreparedPronunciationEntry, ...],
) -> str:
    return canonical_sha256(
        {
            "schema_version": PRONUNCIATION_PROFILE_FINGERPRINT_SCHEMA,
            "novel_id": str(novel_id),
            "entries": [entry.fingerprint_payload() for entry in entries],
        }
    )


def _entry_resource(row: PronunciationEntry) -> wire.PronunciationEntryResource:
    if not isinstance(row.id, UUID):
        raise NarrationServiceError("persisted pronunciation entry lacks identity")
    action = (
        wire.PronunciationAction.SKIP
        if row.spoken_text == ""
        else wire.PronunciationAction.REPLACE
    )
    return wire.PronunciationEntryResource(
        entry_id=row.id,
        source_text=row.source_text,
        action=action,
        spoken_text=None if action is wire.PronunciationAction.SKIP else row.spoken_text,
        language=row.language,
        scope_kind=row.scope_kind,
        scope_id=row.scope_id,
        priority=row.priority,
    )


def pronunciation_profile_resource(
    store: NarrationStore,
    *,
    novel_id: UUID,
    profile: PronunciationProfile | None,
) -> wire.PronunciationProfileResource:
    if profile is None:
        return wire.PronunciationProfileResource(
            novel_id=novel_id,
            profile_id=None,
            version=0,
            fingerprint=None,
            entries=[],
        )
    if profile.novel_id != novel_id:
        raise NarrationScopeMismatch("pronunciation profile belongs to another novel")
    rows = store.find_all(PronunciationEntry, profile_id=profile.id)
    rows.sort(
        key=lambda row: (
            row.scope_kind,
            str(row.scope_id),
            row.normalized_source,
            -row.priority,
            str(row.id),
        )
    )
    return wire.PronunciationProfileResource(
        novel_id=novel_id,
        profile_id=profile.id,
        version=profile.version_number,
        fingerprint=profile.fingerprint,
        entries=[_entry_resource(row) for row in rows],
    )


def get_pronunciation_profile(
    store: NarrationStore,
    *,
    novel_id: UUID,
) -> wire.PronunciationProfileResource:
    require_local_novel(store, novel_id)
    profiles = store.find_all(
        PronunciationProfile,
        novel_id=novel_id,
        order_by=("version_number",),
    )
    return pronunciation_profile_resource(
        store,
        novel_id=novel_id,
        profile=profiles[-1] if profiles else None,
    )


def put_pronunciation_profile(
    store: NarrationStore,
    *,
    novel_id: UUID,
    request: wire.PutPronunciationProfileRequest,
) -> wire.PronunciationProfileResource:
    # The novel lock serializes the max-version read and all scope validation.
    require_local_novel(store, novel_id, for_update=True)
    profiles = store.find_all(
        PronunciationProfile,
        novel_id=novel_id,
        order_by=("version_number",),
        for_update=True,
    )
    current = profiles[-1] if profiles else None
    version_numbers = [profile.version_number for profile in profiles]
    if (
        len(version_numbers) != len(set(version_numbers))
        or any(version < 1 for version in version_numbers)
        or version_numbers != list(range(1, len(version_numbers) + 1))
    ):
        raise NarrationServiceError("pronunciation profile history is inconsistent")
    current_version = current.version_number if current is not None else 0
    if current_version != request.expected_version:
        raise NarrationCasConflict(f"pronunciation profile changed:{current_version}")
    prepared = prepare_pronunciation_entries(
        store,
        novel_id=novel_id,
        entries=request.entries,
    )
    fingerprint = pronunciation_fingerprint(novel_id, prepared)
    if current is not None and current.fingerprint == fingerprint:
        return pronunciation_profile_resource(
            store,
            novel_id=novel_id,
            profile=current,
        )
    if any(profile.fingerprint == fingerprint for profile in profiles):
        # There is no current-profile pointer in the frozen T1 schema.  Returning
        # a historical row would not make it current, while reusing the digest
        # violates the database uniqueness guard.  Fail closed until a later
        # schema decision explicitly supports exact historical reversion.
        raise PronunciationValidationError(
            "exact historical pronunciation reversion is not representable safely",
            field="entries",
        )
    profile = PronunciationProfile(
        id=uuid4(),
        novel_id=novel_id,
        version_number=current_version + 1,
        fingerprint=fingerprint,
        created_at=datetime.now(UTC),
    )
    store.add(profile)
    for entry in prepared:
        store.add(
            PronunciationEntry(
                id=uuid4(),
                profile_id=profile.id,
                scope_kind=entry.scope_kind,
                scope_id=entry.scope_id,
                source_text=entry.source_text,
                normalized_source=entry.normalized_source,
                spoken_text=entry.spoken_text,
                language=entry.language,
                priority=entry.priority,
                source_kind="manual",
            )
        )
    store.flush()
    return pronunciation_profile_resource(
        store,
        novel_id=novel_id,
        profile=profile,
    )


@dataclass(frozen=True, slots=True)
class CacheCandidate:
    asset_id: UUID
    generation: int
    byte_size: int


@dataclass(frozen=True, slots=True)
class CacheInventory:
    novel_id: UUID
    snapshot_fingerprint: str
    source_asset_bytes: int
    locked_voice_bytes: int
    referenced_edition_bytes: int
    derived_cache_bytes: int
    reclaimable_bytes: int
    pending_job_count: int
    protected_asset_count: int
    candidates: tuple[CacheCandidate, ...]


def _combine_roots(parts: list[ReferenceRoots]) -> ReferenceRoots:
    field_names = (
        "novel_cover",
        "render_assets",
        "export_assets",
        "voice_references",
        "locked_voice_assets",
        "manifest_assets",
        "active_job_assets",
        "uploaded_originals",
    )
    values = {
        name: frozenset().union(*(getattr(part, name) for part in parts))
        for name in field_names
    }
    return ReferenceRoots(**values)


def _load_roots(session: Session, assets: list[MediaAsset]) -> ReferenceRoots:
    if not assets:
        return ReferenceRoots()
    parts = [
        load_reference_roots_in_session(
            session,
            asset_ids=(asset.id for asset in assets[index:index + CACHE_ROOT_BATCH_SIZE]),
        )
        for index in range(0, len(assets), CACHE_ROOT_BATCH_SIZE)
    ]
    return _combine_roots(parts)


def build_cache_inventory(
    *,
    novel_id: UUID,
    assets: list[MediaAsset],
    roots: ReferenceRoots,
    pending_job_count: int,
    now: datetime,
    policy: GcPolicy = GcPolicy(),
) -> CacheInventory:
    if now.tzinfo is None:
        raise NarrationServiceError("cache inventory clock must be timezone-aware")
    source_bytes = 0
    locked_bytes = 0
    referenced_bytes = 0
    derived_bytes = 0
    protected_count = 0
    candidates: list[CacheCandidate] = []
    snapshot_assets: list[dict[str, object]] = []
    for asset in sorted(assets, key=lambda row: str(row.id)):
        if asset.novel_id != novel_id:
            raise NarrationScopeMismatch("cache asset belongs to another novel")
        if asset.owner_id != LOCAL_OWNER_ID or asset.workspace_id != LOCAL_WORKSPACE_ID:
            raise NarrationScopeMismatch("cache asset is outside fixed local scope")
        if asset.asset_class is None or asset.state == "deleted":
            continue
        byte_size = asset.byte_size or 0
        if type(byte_size) is not int or byte_size < 0:
            raise NarrationServiceError("cache asset byte size is invalid")
        categories = roots.categories_for(asset.id)
        if asset.id in roots.locked_voice_assets:
            locked_bytes += byte_size
        elif asset.asset_class in {"source", "voice_reference"}:
            source_bytes += byte_size
        elif asset.id in roots.all:
            referenced_bytes += byte_size
        elif asset.asset_class in DERIVABLE_CLASSES:
            derived_bytes += byte_size
        else:
            source_bytes += byte_size
        decision = evaluate_gc(asset, roots, now=now, policy=policy)
        if (
            asset.asset_class in DERIVABLE_CLASSES
            and asset.id not in roots.all
            and decision.action in {"delete", "resume_delete"}
        ):
            candidates.append(
                CacheCandidate(
                    asset_id=asset.id,
                    generation=asset.gc_generation,
                    byte_size=byte_size,
                )
            )
        else:
            protected_count += 1
        snapshot_assets.append(
            {
                "asset_class": asset.asset_class,
                "asset_id": str(asset.id),
                "byte_size": byte_size,
                "expires_at": asset.expires_at.isoformat()
                if asset.expires_at is not None
                else None,
                "gc_generation": asset.gc_generation,
                "gc_marked_at": asset.gc_marked_at.isoformat()
                if asset.gc_marked_at is not None
                else None,
                # The signed snapshot must bind the time-dependent eligibility
                # decision, not only the underlying row.  Otherwise an asset
                # could cross a grace boundary between preview and execute
                # without changing the fingerprint.
                "gc_action": decision.action,
                "gc_eligible": decision.eligible,
                "gc_reason": decision.reason,
                "reference_categories": list(categories),
                "retention_policy": asset.retention_policy,
                "state": asset.state,
            }
        )
    candidates.sort(key=lambda item: str(item.asset_id))
    fingerprint = canonical_sha256(
        {
            "schema_version": CACHE_SNAPSHOT_SCHEMA,
            "novel_id": str(novel_id),
            "assets": snapshot_assets,
        }
    )
    return CacheInventory(
        novel_id=novel_id,
        snapshot_fingerprint=fingerprint,
        source_asset_bytes=source_bytes,
        locked_voice_bytes=locked_bytes,
        referenced_edition_bytes=referenced_bytes,
        derived_cache_bytes=derived_bytes,
        reclaimable_bytes=sum(item.byte_size for item in candidates),
        pending_job_count=pending_job_count,
        protected_asset_count=protected_count,
        candidates=tuple(candidates),
    )


class NarrationCacheRuntime(Protocol):
    def status(self, novel_id: UUID) -> wire.NarrationCacheStatus: ...

    def preview(
        self,
        novel_id: UUID,
        request: wire.PreviewNarrationCacheCleanupRequest,
    ) -> wire.NarrationCacheCleanupPreview: ...

    def execute(
        self,
        novel_id: UUID,
        request: wire.ExecuteNarrationCacheCleanupRequest,
    ) -> wire.NarrationCacheCleanupResult: ...


class UnavailableNarrationCacheRuntime:
    def status(self, novel_id: UUID) -> wire.NarrationCacheStatus:
        del novel_id
        raise CacheRuntimeUnavailable("cache runtime is not installed")

    def preview(
        self,
        novel_id: UUID,
        request: wire.PreviewNarrationCacheCleanupRequest,
    ) -> wire.NarrationCacheCleanupPreview:
        del novel_id, request
        raise CacheRuntimeUnavailable("cache runtime is not installed")

    def execute(
        self,
        novel_id: UUID,
        request: wire.ExecuteNarrationCacheCleanupRequest,
    ) -> wire.NarrationCacheCleanupResult:
        del novel_id, request
        raise CacheRuntimeUnavailable("cache runtime is not installed")


def _default_disk_usage(storage: NarrationStorage) -> tuple[int, int]:
    try:
        return secure_media_disk_usage(storage)
    except (OSError, StorageError) as error:
        raise CacheCleanupStorageFailure("media disk usage is unavailable") from error


class SqlAlchemyNarrationCacheRuntime:
    """Cross-transaction orchestrator for the already-frozen T1-E GC protocol."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        storage: NarrationStorage,
        cleanup_capability: wire.FeatureCapability,
        token_secret: bytes,
        tombstone_digest_key_id: str,
        tombstone_digest_key: bytes,
        disk_usage_provider: DiskUsageProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        gc_policy: GcPolicy = GcPolicy(),
    ) -> None:
        if cleanup_capability.key is not wire.CapabilityKey.CACHE_CLEANUP:
            raise ValueError("cleanup capability must be cache_cleanup")
        if type(token_secret) is not bytes or len(token_secret) < 32:
            raise ValueError("cache token secret must contain at least 32 bytes")
        if type(tombstone_digest_key) is not bytes or len(tombstone_digest_key) < 32:
            raise ValueError("tombstone digest key must contain at least 32 bytes")
        if not tombstone_digest_key_id.strip() or len(tombstone_digest_key_id) > 80:
            raise ValueError("tombstone digest key id is required and bounded")
        self.session_factory = session_factory
        self.storage = storage
        self.cleanup_capability = cleanup_capability
        self.token_secret = token_secret
        self.tombstone_digest_key_id = tombstone_digest_key_id.strip()
        self.tombstone_digest_key = tombstone_digest_key
        self.disk_usage_provider = disk_usage_provider or (lambda: _default_disk_usage(storage))
        self.clock = clock or (lambda: datetime.now(UTC))
        self.gc_policy = gc_policy

    def _require_enabled(self) -> None:
        capability = self.cleanup_capability
        if not (
            capability.state is wire.CapabilityState.ENABLED
            and capability.visible
            and capability.actionable
        ):
            raise CacheCleanupDisabled("cache cleanup capability is not enabled")

    def _inventory(self, novel_id: UUID) -> CacheInventory:
        try:
            with self.session_factory() as session:
                store = SqlAlchemyNarrationStore(session)
                require_local_novel(store, novel_id)
                assets = list(
                    session.scalars(
                        select(MediaAsset)
                        .where(
                            MediaAsset.novel_id == novel_id,
                            MediaAsset.owner_id == LOCAL_OWNER_ID,
                            MediaAsset.workspace_id == LOCAL_WORKSPACE_ID,
                            MediaAsset.asset_class.is_not(None),
                            MediaAsset.state != "deleted",
                        )
                        .order_by(MediaAsset.id)
                    )
                )
                roots = _load_roots(session, assets)
                pending = session.scalar(
                    select(func.count())
                    .select_from(BackgroundJob)
                    .where(
                        BackgroundJob.novel_id == novel_id,
                        BackgroundJob.owner_id == LOCAL_OWNER_ID,
                        BackgroundJob.workspace_id == LOCAL_WORKSPACE_ID,
                        BackgroundJob.state.in_(ACTIVE_JOB_STATES),
                    )
                )
                return build_cache_inventory(
                    novel_id=novel_id,
                    assets=assets,
                    roots=roots,
                    pending_job_count=int(pending or 0),
                    now=self.clock(),
                    policy=self.gc_policy,
                )
        except NarrationServiceError:
            raise
        except MediaPolicyError as error:
            raise CacheRuntimeUnavailable("cache root inspection failed") from error
        except Exception as error:
            raise CacheRuntimeUnavailable("cache inventory query failed") from error

    def _token(self, novel_id: UUID, fingerprint: str, expires_at: datetime) -> str:
        expiry = int(expires_at.timestamp())
        unsigned = f"{CACHE_TOKEN_VERSION}.{expiry}.{novel_id.hex}.{fingerprint}"
        signature = hmac.new(
            self.token_secret,
            unsigned.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return f"{unsigned}.{signature}"

    def _verify_token(
        self,
        token: str,
        *,
        novel_id: UUID,
        fingerprint: str,
    ) -> None:
        match = _TOKEN.fullmatch(token)
        if match is None:
            raise CacheCleanupTokenInvalid("cache cleanup token is malformed")
        expiry_text, novel_hex, token_fingerprint, supplied_signature = match.groups()
        unsigned = f"{CACHE_TOKEN_VERSION}.{expiry_text}.{novel_hex}.{token_fingerprint}"
        expected_signature = hmac.new(
            self.token_secret,
            unsigned.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise CacheCleanupTokenInvalid("cache cleanup token signature is invalid")
        if novel_hex != novel_id.hex or token_fingerprint != fingerprint:
            raise CacheCleanupTokenInvalid("cache cleanup token scope changed")
        now = self.clock()
        if now.tzinfo is None:
            raise CacheRuntimeUnavailable("cache clock must be timezone-aware")
        if int(expiry_text) <= int(now.timestamp()):
            raise CacheCleanupTokenInvalid("cache cleanup token expired")

    def status(self, novel_id: UUID) -> wire.NarrationCacheStatus:
        inventory = self._inventory(novel_id)
        try:
            free_bytes, total_bytes = self.disk_usage_provider()
        except CacheCleanupStorageFailure:
            raise
        except Exception as error:
            raise CacheCleanupStorageFailure("media disk usage failed") from error
        if (
            type(free_bytes) is not int
            or type(total_bytes) is not int
            or total_bytes < 1
            or free_bytes < 0
            or free_bytes > total_bytes
        ):
            raise CacheCleanupStorageFailure("media disk usage returned invalid totals")
        return wire.NarrationCacheStatus(
            novel_id=novel_id,
            snapshot_fingerprint=inventory.snapshot_fingerprint,
            source_asset_bytes=inventory.source_asset_bytes,
            locked_voice_bytes=inventory.locked_voice_bytes,
            referenced_edition_bytes=inventory.referenced_edition_bytes,
            derived_cache_bytes=inventory.derived_cache_bytes,
            reclaimable_bytes=inventory.reclaimable_bytes,
            pending_job_count=inventory.pending_job_count,
            disk_free_bytes=free_bytes,
            disk_total_bytes=total_bytes,
            cleanup_capability=self.cleanup_capability,
        )

    def preview(
        self,
        novel_id: UUID,
        request: wire.PreviewNarrationCacheCleanupRequest,
    ) -> wire.NarrationCacheCleanupPreview:
        self._require_enabled()
        inventory = self._inventory(novel_id)
        if request.snapshot_fingerprint != inventory.snapshot_fingerprint:
            raise CacheSnapshotChanged("cache snapshot changed before preview")
        now = self.clock()
        if now.tzinfo is None:
            raise CacheRuntimeUnavailable("cache clock must be timezone-aware")
        expires_at = now + CACHE_TOKEN_TTL
        return wire.NarrationCacheCleanupPreview(
            novel_id=novel_id,
            snapshot_fingerprint=inventory.snapshot_fingerprint,
            cleanup_token=self._token(novel_id, inventory.snapshot_fingerprint, expires_at),
            expires_at=expires_at,
            reclaimable_bytes=inventory.reclaimable_bytes,
            protected_asset_count=inventory.protected_asset_count,
            candidate_asset_count=len(inventory.candidates),
        )

    def execute(
        self,
        novel_id: UUID,
        request: wire.ExecuteNarrationCacheCleanupRequest,
    ) -> wire.NarrationCacheCleanupResult:
        self._require_enabled()
        self._verify_token(
            request.cleanup_token,
            novel_id=novel_id,
            fingerprint=request.snapshot_fingerprint,
        )
        inventory = self._inventory(novel_id)
        if request.snapshot_fingerprint != inventory.snapshot_fingerprint:
            raise CacheSnapshotChanged("cache snapshot changed before execution")
        deleted_count = 0
        reclaimed_bytes = 0
        for candidate in inventory.candidates:
            try:
                with self.session_factory() as session:
                    with session.begin():
                        plan = begin_gc_deletion_in_session(
                            session,
                            self.storage,
                            asset_id=candidate.asset_id,
                            expected_generation=candidate.generation,
                            policy=self.gc_policy,
                        )
            except (MediaNotEligible, MediaConflict):
                # A new structured reference or generation change before the
                # durable deletion plan makes this candidate protected.
                continue
            except MediaPolicyError as error:
                raise CacheRuntimeUnavailable("cache deletion policy inspection failed") from error
            except (StorageError, OSError) as error:
                raise CacheCleanupStorageFailure("cache deletion planning failed") from error
            try:
                result = execute_gc_delete(self.storage, plan)
            except (StorageError, OSError) as error:
                raise CacheCleanupStorageFailure("cache physical deletion failed") from error
            try:
                with self.session_factory() as session:
                    with session.begin():
                        finalize_gc_deletion_in_session(
                            session,
                            self.storage,
                            asset_id=candidate.asset_id,
                            digest_key_id=self.tombstone_digest_key_id,
                            digest_key=self.tombstone_digest_key,
                            deleted_actor="narration-cache-cleanup",
                        )
            except (MediaConflict, StorageError, OSError) as error:
                # The blob may already be absent here.  Never turn a failed
                # tombstone/finalization into a successful or skipped claim.
                raise CacheCleanupStorageFailure("cache deletion finalization failed") from error
            deleted_count += 1
            if result.removed:
                reclaimed_bytes += plan.byte_size
        return wire.NarrationCacheCleanupResult(
            novel_id=novel_id,
            deleted_asset_count=deleted_count,
            reclaimed_bytes=reclaimed_bytes,
            source_asset_deleted_count=0,
            locked_voice_deleted_count=0,
            referenced_asset_deleted_count=0,
        )


def _payload(
    command: NarrationSettingsApiCommand,
    model: type[_PayloadModel],
) -> _PayloadModel:
    if type(command.payload) is not model:
        raise PronunciationValidationError("command payload type mismatch")
    return command.payload


def _current_version_from_error(error: NarrationCasConflict) -> int | None:
    try:
        return int(str(error).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _api_fault(error: NarrationServiceError) -> NarrationApiFault:
    if isinstance(error, NarrationCasConflict):
        return NarrationApiFault(
            wire.NarrationErrorCode.VERSION_CONFLICT,
            "发音配置已经变化，请刷新后重试。",
            current_version=_current_version_from_error(error),
        )
    if isinstance(error, NarrationNotFound):
        return NarrationApiFault(
            wire.NarrationErrorCode.RESOURCE_NOT_FOUND,
            "作品或发音作用域不存在。",
        )
    if isinstance(error, NarrationScopeMismatch):
        return NarrationApiFault(
            wire.NarrationErrorCode.SCOPE_VIOLATION,
            "发音或缓存资源不属于当前作品。",
        )
    if isinstance(error, PronunciationValidationError):
        return NarrationApiFault(
            wire.NarrationErrorCode.VALIDATION_FAILED,
            "发音配置未通过领域校验。",
            field=error.field,
        )
    if isinstance(error, CacheCleanupDisabled):
        return NarrationApiFault(
            wire.NarrationErrorCode.CAPABILITY_DISABLED,
            "缓存清理能力尚未开放。",
            capability=wire.CapabilityKey.CACHE_CLEANUP,
        )
    if isinstance(error, CacheSnapshotChanged):
        return NarrationApiFault(
            wire.NarrationErrorCode.VERSION_CONFLICT,
            "缓存状态已经变化，请重新预览。",
            capability=wire.CapabilityKey.CACHE_CLEANUP,
        )
    if isinstance(error, CacheCleanupTokenInvalid):
        return NarrationApiFault(
            wire.NarrationErrorCode.INVALID_STATE,
            "缓存清理确认已失效，请重新预览。",
            capability=wire.CapabilityKey.CACHE_CLEANUP,
        )
    if isinstance(
        error,
        (CacheRuntimeUnavailable, CacheCleanupStorageFailure, MediaPolicyError),
    ):
        return NarrationApiFault(
            wire.NarrationErrorCode.STORAGE_UNAVAILABLE,
            "缓存存储暂不可用。",
            retryable=True,
            capability=wire.CapabilityKey.CACHE_CLEANUP,
        )
    raise error


class PronunciationSettingsHandler:
    """Narrow T2-F owner for the final single settings dispatcher."""

    operations = PRONUNCIATION_OPERATIONS

    def __init__(
        self,
        store: NarrationStore,
        *,
        cache_runtime: NarrationCacheRuntime | None = None,
    ) -> None:
        self.store = store
        self.cache_runtime = cache_runtime or UnavailableNarrationCacheRuntime()

    @classmethod
    def handles(cls, operation: NarrationSettingsOperation) -> bool:
        return operation in cls.operations

    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        if command.operation not in self.operations:
            raise KeyError(f"operation is not owned by T2-F: {command.operation.value}")
        if command.novel_id is None:
            raise NarrationApiFault(
                wire.NarrationErrorCode.REQUEST_VALIDATION_FAILED,
                "缺少作品标识。",
                field="novel_id",
            )
        try:
            if command.operation is NarrationSettingsOperation.GET_PRONUNCIATION_PROFILE:
                return get_pronunciation_profile(self.store, novel_id=command.novel_id)
            if command.operation is NarrationSettingsOperation.PUT_PRONUNCIATION_PROFILE:
                return put_pronunciation_profile(
                    self.store,
                    novel_id=command.novel_id,
                    request=_payload(command, wire.PutPronunciationProfileRequest),
                )
            if command.operation is NarrationSettingsOperation.GET_CACHE_STATUS:
                return self.cache_runtime.status(command.novel_id)
            if command.operation is NarrationSettingsOperation.PREVIEW_CACHE_CLEANUP:
                return self.cache_runtime.preview(
                    command.novel_id,
                    _payload(command, wire.PreviewNarrationCacheCleanupRequest),
                )
            if command.operation is NarrationSettingsOperation.EXECUTE_CACHE_CLEANUP:
                return self.cache_runtime.execute(
                    command.novel_id,
                    _payload(command, wire.ExecuteNarrationCacheCleanupRequest),
                )
        except NarrationApiFault:
            raise
        except NarrationServiceError as error:
            raise _api_fault(error) from error
        raise AssertionError("unreachable T2-F operation")


__all__ = [
    "CACHE_SNAPSHOT_SCHEMA",
    "CACHE_TOKEN_TTL",
    "CacheCandidate",
    "CacheCleanupDisabled",
    "CacheCleanupStorageFailure",
    "CacheCleanupTokenInvalid",
    "CacheInventory",
    "CacheRuntimeUnavailable",
    "CacheSnapshotChanged",
    "NarrationCacheRuntime",
    "PRONUNCIATION_OPERATIONS",
    "PRONUNCIATION_PROFILE_FINGERPRINT_SCHEMA",
    "PreparedPronunciationEntry",
    "PronunciationSettingsHandler",
    "PronunciationValidationError",
    "SqlAlchemyNarrationCacheRuntime",
    "UnavailableNarrationCacheRuntime",
    "build_cache_inventory",
    "get_pronunciation_profile",
    "normalize_pronunciation_source",
    "prepare_pronunciation_entries",
    "pronunciation_fingerprint",
    "pronunciation_profile_resource",
    "put_pronunciation_profile",
]
