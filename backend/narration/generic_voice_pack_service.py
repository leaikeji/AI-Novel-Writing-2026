"""Durable 24-slot generic voice-pack integration for Plan 55.

One immutable Pack Version is the public build-command identity.  Internal
``generic_voice_generation_commands`` remain one-slot jobs so the existing
single-concurrency VoiceGenerator/Nano scheduler can process them safely.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    BackgroundJob,
    GenericVoiceDesignDraft,
    GenericVoiceGenerationCommand,
    GenericVoicePackVersion,
    GenericVoicePackVersionSlot,
    GenericVoicePool,
    GenericVoiceSlot,
    MediaAsset,
    ModelRunRecord,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from . import schemas as wire
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NarrationRequestScope
from .generic_voice_generation import (
    GENERIC_VOICE_JOB_KIND,
    GenericVoiceGenerationService,
)
from .jobs import (
    JobFenceError,
    JobLease,
    acknowledge_cancel,
    complete_attempt,
    fail_attempt,
    heartbeat_attempt,
    lock_result_publish_fences,
)
from .nano_experiments import production_nano_experiment_identity
from .runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
from .services import (
    InvalidNarrationState,
    NarrationNotFound,
    NarrationServiceError,
    SqlAlchemyNarrationStore,
    canonical_sha256,
    require_local_novel,
)
from .storage import NarrationStorage
from .voice_generator_processor import (
    NANO_MODEL_ID,
    VOICE_GENERATOR_MODEL_ID,
    PreparedVoiceGeneratorPublication,
    VoiceGeneratorWorkItem,
)
from .voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_FINGERPRINT,
    EXPECTED_RUNTIME_IDENTITY,
    VOICE_GENERATOR_REVISION,
    HostGenerationReceipt,
    VoiceGeneratorHostRequest,
)
from .voice_generator_service import VoiceGeneratorCommandState
from .jobs import enqueue_job
from .voices import voice_preview_media_link


SessionFactory = Callable[[], Session]
GENERIC_RESOURCE_CLASS = "moss-nano"
GENERIC_PACK_RUNTIME_UNAVAILABLE = "GENERIC_VOICE_PACK_RUNTIME_UNAVAILABLE"
GENERIC_PACK_GENERATION_FAILED = "GENERIC_VOICE_PACK_GENERATION_FAILED"


def _public_slot_category(category: str) -> str:
    if "child" in category:
        return "child"
    if "teen" in category or "young" in category:
        return "youth"
    if "middle" in category:
        return "middle_age"
    if "elderly" in category or "older" in category:
        return "older"
    return "neutral_group"


def _transaction(factory: SessionFactory, operation):
    with factory() as session:
        try:
            result = operation(session)
            session.commit()
            return result
        except BaseException:
            session.rollback()
            raise


def _latest_pack(session: Session) -> GenericVoicePackVersion | None:
    return session.scalar(
        select(GenericVoicePackVersion)
        .where(
            GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
            GenericVoicePackVersion.language == "zh-CN",
        )
        .order_by(
            GenericVoicePackVersion.version_number.desc(),
            GenericVoicePackVersion.id.desc(),
        )
        .limit(1)
    )


def _slots(session: Session, pack_id: UUID, *, for_update: bool = False):
    statement = (
        select(GenericVoicePackVersionSlot)
        .where(GenericVoicePackVersionSlot.pack_version_id == pack_id)
        .order_by(GenericVoicePackVersionSlot.position)
    )
    if for_update:
        statement = statement.with_for_update()
    return tuple(session.scalars(statement))


def _slot_resource(
    session: Session,
    row: GenericVoicePackVersionSlot,
) -> wire.GenericVoicePackSlotResource:
    profile = (
        session.get(VoiceProfile, row.voice_profile_id)
        if row.voice_profile_id is not None
        else None
    )
    version = (
        session.get(VoiceProfileVersion, row.voice_version_id)
        if row.voice_version_id is not None
        else None
    )
    preview_asset = None
    if row.state in {"validated", "reused"}:
        if (
            profile is None
            or version is None
            or version.profile_id != profile.id
            or profile.current_version_id != version.id
            or profile.owner_id != LOCAL_OWNER_ID
            or profile.workspace_id != LOCAL_WORKSPACE_ID
            or profile.novel_id is not None
            or profile.status != "active"
            or version.owner_id != LOCAL_OWNER_ID
            or version.workspace_id != LOCAL_WORKSPACE_ID
            or version.state != "locked"
            or version.source_type != "generated"
            or version.activation_basis != "generic_voice_pack_generation"
            or version.validation_basis != "machine_validated"
            or version.quality_state != "accepted"
        ):
            raise InvalidNarrationState("generic voice slot publication is inconsistent")
        preview_asset = voice_preview_media_link(
            SqlAlchemyNarrationStore(session),
            profile,
            version.preview_asset_id,
        )
        if preview_asset is None:
            raise InvalidNarrationState("generic voice slot preview asset is absent")
    return wire.GenericVoicePackSlotResource(
        slot_id=row.id,
        slot_key=row.slot_key,
        label=row.label,
        category=row.category,
        state=row.state,
        preview_available=preview_asset is not None,
        preview_asset=preview_asset,
        voice_profile_id=row.voice_profile_id,
        voice_version_id=row.voice_version_id,
        failure_code=row.failure_code,
    )


def _preload_slot_publications(
    session: Session,
    rows: tuple[GenericVoicePackVersionSlot, ...],
) -> tuple[tuple[VoiceProfile, ...], tuple[VoiceProfileVersion, ...], tuple[MediaAsset, ...]]:
    """Bound pack projection to three publication queries instead of per-slot N+1 reads."""

    profile_ids = tuple(
        row.voice_profile_id for row in rows if row.voice_profile_id is not None
    )
    version_ids = tuple(
        row.voice_version_id for row in rows if row.voice_version_id is not None
    )
    profiles = (
        tuple(session.scalars(select(VoiceProfile).where(VoiceProfile.id.in_(profile_ids))))
        if profile_ids
        else ()
    )
    versions = (
        tuple(
            session.scalars(
                select(VoiceProfileVersion).where(VoiceProfileVersion.id.in_(version_ids))
            )
        )
        if version_ids
        else ()
    )
    asset_ids = tuple(
        version.preview_asset_id
        for version in versions
        if version.preview_asset_id is not None
    )
    assets = (
        tuple(session.scalars(select(MediaAsset).where(MediaAsset.id.in_(asset_ids))))
        if asset_ids
        else ()
    )
    return profiles, versions, assets


def resolve_generic_voice_slot_media(
    session: Session,
    slot_id: UUID,
    asset_id: UUID,
) -> MediaAsset:
    """Resolve only the immutable Nano validation asset for one valid pack slot."""

    slot = session.get(GenericVoicePackVersionSlot, slot_id)
    if slot is None or slot.workspace_id != LOCAL_WORKSPACE_ID:
        raise NarrationNotFound("generic voice slot media not found")
    pack = session.get(GenericVoicePackVersion, slot.pack_version_id)
    if (
        pack is None
        or pack.workspace_id != LOCAL_WORKSPACE_ID
        or pack.language != "zh-CN"
        or slot.state not in {"validated", "reused"}
        or slot.voice_profile_id is None
        or slot.voice_version_id is None
    ):
        raise NarrationNotFound("generic voice slot media not found")
    resource = _slot_resource(session, slot)
    link = resource.preview_asset
    if link is None or link.asset_id != asset_id:
        raise NarrationNotFound("generic voice slot media not found")
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise NarrationNotFound("generic voice slot media not found")
    return asset


def _cancel_active_pack_work(
    session: Session,
    *,
    pack_id: UUID,
    now: datetime,
) -> None:
    """Fence current work in the same lock order used by result publication."""

    jobs = tuple(
        session.scalars(
            select(BackgroundJob)
            .join(
                GenericVoiceGenerationCommand,
                GenericVoiceGenerationCommand.background_job_id == BackgroundJob.id,
            )
            .where(
                GenericVoiceGenerationCommand.pack_version_id == pack_id,
                BackgroundJob.state.in_(("queued", "running", "cancel_requested")),
            )
            .order_by(BackgroundJob.id)
            .with_for_update(of=BackgroundJob)
        )
    )
    for job in jobs:
        job.state = "cancel_requested" if job.state == "running" else "cancelled"
        job.updated_at = now
    commands = tuple(
        session.scalars(
            select(GenericVoiceGenerationCommand)
            .where(
                GenericVoiceGenerationCommand.pack_version_id == pack_id,
                GenericVoiceGenerationCommand.state.in_(("queued", "building")),
            )
            .order_by(GenericVoiceGenerationCommand.id)
            .with_for_update()
        )
    )
    for command in commands:
        command.state = "cancelled"
        command.completed_at = now
        command.updated_at = now


def _enqueue_next_slot(session: Session, pack: GenericVoicePackVersion) -> UUID | None:
    active = session.scalar(
        select(GenericVoiceGenerationCommand.id).where(
            GenericVoiceGenerationCommand.pack_version_id == pack.id,
            GenericVoiceGenerationCommand.state.in_(("queued", "building")),
        )
    )
    if active is not None:
        return active
    slot = session.scalar(
        select(GenericVoicePackVersionSlot)
        .where(
            GenericVoicePackVersionSlot.pack_version_id == pack.id,
            GenericVoicePackVersionSlot.state.in_(("pending", "failed")),
        )
        .order_by(GenericVoicePackVersionSlot.position)
        .with_for_update()
        .limit(1)
    )
    if slot is None:
        return None
    draft = session.get(GenericVoiceDesignDraft, slot.design_draft_id)
    if draft is None or draft.workspace_id != LOCAL_WORKSPACE_ID:
        raise InvalidNarrationState("generic voice design draft is missing")
    command_id = uuid4()
    request_hash = canonical_sha256(
        {
            "schema_version": "generic-voice-generation-request/1",
            "pack_version_id": str(pack.id),
            "slot_key": slot.slot_key,
            "design_fingerprint": draft.fingerprint,
        }
    )
    enqueued = enqueue_job(
        session,
        scope=NarrationRequestScope.fixed_local(),
        job_kind=GENERIC_VOICE_JOB_KIND,
        input_hash=draft.fingerprint,
        idempotency_key=f"generic-voice:{command_id}",
        resource_class=GENERIC_RESOURCE_CLASS,
        base_priority=60,
        max_attempts=1,
    )
    command = GenericVoiceGenerationCommand(
        id=command_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        pack_version_id=pack.id,
        design_draft_id=draft.id,
        background_job_id=enqueued.job_id,
        host_request_id=command_id,
        language="zh-CN",
        slot_key=slot.slot_key,
        idempotency_key=f"generic-voice-slot:{pack.id}:{slot.slot_key}",
        request_hash=request_hash,
        design_fingerprint=draft.fingerprint,
        state="queued",
        attempt=0,
        progress_current=0,
        progress_total=2,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(command)
    session.flush()
    slot.generation_command_id = command.id
    slot.state = "generating"
    slot.failure_code = None
    slot.updated_at = datetime.now(UTC)
    pack.state = "building"
    pack.failure_code = None
    pack.updated_at = datetime.now(UTC)
    session.flush()
    return command.id


class SqlAlchemyGenericVoicePackService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._designs = GenericVoiceGenerationService()

    def get_load_resource(self) -> wire.GenericVoicePackLoadResource:
        return _transaction(self._session_factory, self._load_resource)

    def get_build_resource(self, command_id: UUID) -> wire.GenericVoicePackLoadResource:
        def operation(session: Session):
            pack = session.get(GenericVoicePackVersion, command_id)
            if pack is None or pack.workspace_id != LOCAL_WORKSPACE_ID:
                raise NarrationNotFound("generic voice build command not found")
            return self._load_resource(session, pack=pack)

        return _transaction(self._session_factory, operation)

    def build(self, *, idempotency_key: str) -> wire.GenericVoicePackLoadResource:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("generic voice build idempotency key is invalid")

        def operation(session: Session):
            # The Pack Version is also the public build-command identity.  A
            # deterministic UUID makes the HTTP Idempotency-Key durable without
            # introducing a second, semantically duplicate parent-command table.
            pack_id = uuid5(
                LOCAL_WORKSPACE_ID,
                f"generic-voice-pack-build/1:{idempotency_key}",
            )
            replay = session.get(GenericVoicePackVersion, pack_id)
            if replay is not None:
                if replay.workspace_id != LOCAL_WORKSPACE_ID:
                    raise InvalidNarrationState("generic voice pack scope changed")
                return self._load_resource(session, pack=replay)
            latest = _latest_pack(session)
            if latest is not None and latest.state in {
                "building",
                "ready_to_activate",
                "active",
            }:
                return self._load_resource(session, pack=latest)
            version_number = 1 if latest is None else latest.version_number + 1
            catalog = self._designs.catalog
            now = datetime.now(UTC)
            pack = GenericVoicePackVersion(
                id=pack_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                language="zh-CN",
                catalog_id=catalog.catalog_id,
                taxonomy_sha256=catalog.taxonomy_sha256,
                design_catalog_sha256=catalog.catalog_sha256,
                version_number=version_number,
                predecessor_version_id=(latest.id if latest is not None else None),
                state="building",
                slot_total=24,
                validated_slot_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add(pack)
            session.flush()
            from .voice_pool import load_voice_pool_catalog

            labels = {item.slot_key: item for item in load_voice_pool_catalog().slots}
            predecessor_slots = (
                {
                    row.slot_key: row
                    for row in _slots(session, latest.id)
                }
                if latest is not None
                else {}
            )
            reused_count = 0
            for position, design in enumerate(self._designs.catalog.slots):
                draft = session.scalar(
                    select(GenericVoiceDesignDraft).where(
                        GenericVoiceDesignDraft.workspace_id == LOCAL_WORKSPACE_ID,
                        GenericVoiceDesignDraft.fingerprint == design.design_fingerprint,
                    )
                )
                if draft is None:
                    parameters = EXPECTED_AUDIO_PARAMETERS.wire_payload()
                    draft = GenericVoiceDesignDraft(
                        id=uuid4(),
                        owner_id=LOCAL_OWNER_ID,
                        workspace_id=LOCAL_WORKSPACE_ID,
                        language="zh-CN",
                        slot_key=design.slot_key,
                        instruction=design.instruction,
                        instruction_digest=design.instruction_sha256,
                        seed=design.seed,
                        parameters_json=parameters,
                        parameters_digest=canonical_sha256(parameters),
                        runtime_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
                        runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
                        fingerprint=design.design_fingerprint,
                        created_at=now,
                    )
                    session.add(draft)
                    session.flush()
                label = labels[design.slot_key]
                predecessor = predecessor_slots.get(design.slot_key)
                can_reuse = (
                    predecessor is not None
                    and predecessor.state in {"validated", "reused"}
                    and predecessor.design_fingerprint == design.design_fingerprint
                    and predecessor.voice_profile_id is not None
                    and predecessor.voice_version_id is not None
                    and predecessor.rights_approved
                    and predecessor.quality_approved
                )
                if can_reuse:
                    reused_count += 1
                session.add(
                    GenericVoicePackVersionSlot(
                        id=uuid4(),
                        pack_version_id=pack.id,
                        workspace_id=LOCAL_WORKSPACE_ID,
                        slot_key=design.slot_key,
                        label=label.label,
                        category=_public_slot_category(label.category),
                        position=position,
                        state="reused" if can_reuse else "pending",
                        design_draft_id=draft.id,
                        design_fingerprint=design.design_fingerprint,
                        generation_command_id=(
                            predecessor.generation_command_id if can_reuse else None
                        ),
                        voice_profile_id=(
                            predecessor.voice_profile_id if can_reuse else None
                        ),
                        voice_version_id=(
                            predecessor.voice_version_id if can_reuse else None
                        ),
                        rights_approved=can_reuse,
                        quality_approved=can_reuse,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.flush()
            pack.validated_slot_count = reused_count
            if reused_count == pack.slot_total:
                pack.state = "active"
                pack.activated_at = now
            else:
                _enqueue_next_slot(session, pack)
            return self._load_resource(session, pack=pack)

        return _transaction(self._session_factory, operation)

    def retry(self, command_id: UUID) -> wire.GenericVoicePackLoadResource:
        # A failed or superseded candidate is immutable; retry creates a fresh
        # successor and reuses any still-valid slots through regenerate logic.
        previous = self.get_build_resource(command_id).pack
        if previous.state not in {"failed", "superseded", "rejected", "retired_for_new_use"}:
            raise InvalidNarrationState("generic voice build command is not retryable")
        return self.build(idempotency_key=f"generic-pack-retry:{command_id}")

    def cancel(self, command_id: UUID) -> wire.GenericVoicePackLoadResource:
        def operation(session: Session):
            exists = session.scalar(
                select(GenericVoicePackVersion.id).where(
                    GenericVoicePackVersion.id == command_id,
                    GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                )
            )
            if exists is None:
                raise NarrationNotFound("generic voice build command not found")
            now = datetime.now(UTC)
            _cancel_active_pack_work(session, pack_id=command_id, now=now)
            pack = session.scalar(
                select(GenericVoicePackVersion)
                .where(
                    GenericVoicePackVersion.id == command_id,
                    GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                )
                .with_for_update()
            )
            if pack is None:
                raise NarrationNotFound("generic voice build command not found")
            if pack.state == "superseded":
                return self._load_resource(session, pack=pack)
            if pack.state != "building":
                raise InvalidNarrationState("generic voice build command is not cancellable")
            pack.state = "superseded"
            pack.updated_at = now
            return self._load_resource(session, pack=pack, cancelled=True)

        return _transaction(self._session_factory, operation)

    def regenerate(
        self,
        *,
        slot_key: str,
        expected_pack_version_id: UUID | None,
        idempotency_key: str,
    ) -> wire.GenericVoicePackLoadResource:
        current = self.get_load_resource().pack
        if expected_pack_version_id is not None and current.pack_version_id != expected_pack_version_id:
            raise InvalidNarrationState("generic voice pack version changed")
        # Rejecting an active slot first ensures the old pack cannot be used by
        # new chapters while its successor is incomplete.
        if current.pack_version_id is not None and current.state == "active":
            self.reject(
                slot_key=slot_key,
                expected_pack_version_id=current.pack_version_id,
            )
        return self.build(
            idempotency_key=f"generic-regenerate:{slot_key}:{idempotency_key}"
        )

    def reject(
        self,
        *,
        slot_key: str,
        expected_pack_version_id: UUID,
    ) -> wire.GenericVoicePackLoadResource:
        def operation(session: Session):
            exists = session.scalar(
                select(GenericVoicePackVersion.id).where(
                    GenericVoicePackVersion.id == expected_pack_version_id,
                    GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                )
            )
            if exists is None:
                raise NarrationNotFound("generic voice pack not found")
            now = datetime.now(UTC)
            _cancel_active_pack_work(
                session,
                pack_id=expected_pack_version_id,
                now=now,
            )
            pack = session.scalar(
                select(GenericVoicePackVersion)
                .where(
                    GenericVoicePackVersion.id == expected_pack_version_id,
                    GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                )
                .with_for_update()
            )
            if pack is None:
                raise NarrationNotFound("generic voice pack not found")
            slot = session.scalar(
                select(GenericVoicePackVersionSlot)
                .where(
                    GenericVoicePackVersionSlot.pack_version_id == pack.id,
                    GenericVoicePackVersionSlot.slot_key == slot_key,
                )
                .with_for_update()
            )
            if slot is None:
                raise NarrationNotFound("generic voice slot not found")
            if slot.state == "rejected":
                return self._load_resource(session, pack=pack)
            slot.state = "rejected"
            slot.failure_code = "GENERIC_VOICE_PACK_SLOT_REJECTED"
            slot.updated_at = now
            pack.state = (
                "retired_for_new_use" if pack.state == "active" else "rejected"
            )
            pack.failure_code = "GENERIC_VOICE_PACK_SLOT_REJECTED"
            pack.retired_at = now if pack.state == "retired_for_new_use" else None
            pack.updated_at = now
            return self._load_resource(session, pack=pack)

        return _transaction(self._session_factory, operation)

    def active_pack_ready(self) -> bool:
        return _transaction(
            self._session_factory,
            lambda session: session.scalar(
                select(GenericVoicePackVersion.id).where(
                    GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                    GenericVoicePackVersion.language == "zh-CN",
                    GenericVoicePackVersion.state == "active",
                    GenericVoicePackVersion.validated_slot_count == 24,
                )
            )
            is not None,
        )

    def ensure_novel_projection(self, novel_id: UUID) -> UUID:
        def operation(session: Session) -> UUID:
            require_local_novel(SqlAlchemyNarrationStore(session), novel_id, for_update=True)
            pack = session.scalar(
                select(GenericVoicePackVersion)
                .where(
                    GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                    GenericVoicePackVersion.language == "zh-CN",
                    GenericVoicePackVersion.state == "active",
                )
                .with_for_update()
            )
            if pack is None or pack.validated_slot_count != 24:
                raise NarrationServiceError("GENERIC_VOICE_PACK_NOT_READY")
            existing = session.scalar(
                select(GenericVoicePool).where(
                    GenericVoicePool.novel_id == novel_id,
                    GenericVoicePool.source_pack_version_id == pack.id,
                    GenericVoicePool.status == "active",
                )
            )
            if existing is not None:
                return existing.id
            rows = _slots(session, pack.id)
            if len(rows) != 24 or any(
                row.state not in {"validated", "reused"}
                or row.voice_version_id is None
                for row in rows
            ):
                raise NarrationServiceError("GENERIC_VOICE_PACK_INCOMPLETE")
            previous = tuple(
                session.scalars(
                    select(GenericVoicePool)
                    .where(
                        GenericVoicePool.novel_id == novel_id,
                        GenericVoicePool.status == "active",
                    )
                    .with_for_update()
                )
            )
            for row in previous:
                row.status = "retired"
            max_version = session.scalar(
                select(func.coalesce(func.max(GenericVoicePool.version_number), 0)).where(
                    GenericVoicePool.novel_id == novel_id,
                    GenericVoicePool.name == "中文通用角色音色",
                )
            )
            pool = GenericVoicePool(
                id=uuid4(),
                novel_id=novel_id,
                name="中文通用角色音色",
                version_number=int(max_version or 0) + 1,
                status="active",
                language="zh-CN",
                source_pack_version_id=pack.id,
                attributes_json={"schema_version": "generic-voice-pool-projection/1"},
            )
            session.add(pool)
            session.flush()
            for row in rows:
                session.add(
                    GenericVoiceSlot(
                        id=uuid4(),
                        pool_id=pool.id,
                        slot_key=row.slot_key,
                        position=row.position,
                        voice_version_id=row.voice_version_id,
                        labels_json=[row.label, row.category],
                        enabled=True,
                        priority=row.position,
                    )
                )
            session.flush()
            return pool.id

        return _transaction(self._session_factory, operation)

    def _load_resource(
        self,
        session: Session,
        *,
        pack: GenericVoicePackVersion | None = None,
        cancelled: bool = False,
    ) -> wire.GenericVoicePackLoadResource:
        pack = pack or _latest_pack(session)
        now = datetime.now(UTC)
        if pack is None:
            return wire.GenericVoicePackLoadResource(
                pack=wire.GenericVoicePackResource(
                    state="missing",
                    prepared_slots=0,
                    slots=[],
                    updated_at=now,
                )
            )
        rows = _slots(session, pack.id)
        publication_rows = _preload_slot_publications(session, rows)
        prepared = sum(row.state in {"validated", "reused"} for row in rows)
        pack_resource = wire.GenericVoicePackResource(
            pack_version_id=pack.id,
            state=pack.state,
            prepared_slots=prepared,
            slots=[_slot_resource(session, row) for row in rows],
            failure_code=pack.failure_code,
            updated_at=pack.updated_at,
        )
        # Keep preloaded ORM objects strongly referenced until every strict
        # slot projection has resolved through the Session identity map.
        del publication_rows
        current = next(
            (
                row.slot_key
                for row in rows
                if row.state == "generating"
            ),
            None,
        )
        has_cancelled_child = any(
            state == "cancelled"
            for state in session.scalars(
                select(GenericVoiceGenerationCommand.state).where(
                    GenericVoiceGenerationCommand.pack_version_id == pack.id
                )
            )
        )
        if cancelled or (pack.state == "superseded" and has_cancelled_child):
            command_state = "cancelled"
        elif pack.state == "active":
            command_state = "ready"
        elif pack.state == "building":
            command_state = "building" if current is not None else "queued"
        elif pack.state in {"failed", "rejected", "retired_for_new_use"}:
            command_state = "failed"
        else:
            command_state = "superseded"
        terminal = command_state not in {"queued", "building"}
        return wire.GenericVoicePackLoadResource(
            pack=pack_resource,
            command=wire.GenericVoiceBuildCommandResource(
                command_id=pack.id,
                pack_version_id=pack.id,
                state=command_state,
                progress_current=prepared,
                current_slot_key=current,
                cancellable=not terminal,
                retryable=command_state in {"failed", "superseded"},
                terminal=terminal,
                failure_code=(
                    pack.failure_code if command_state == "failed" else None
                ),
                updated_at=pack.updated_at,
            ),
        )


class SqlAlchemyGenericVoiceRepository:
    """Duck-typed repository consumed by the shared VoiceGeneratorProcessor."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._scope = NarrationRequestScope.fixed_local()

    def owns_job(self, job_id: UUID) -> bool:
        return _transaction(
            self._session_factory,
            lambda session: session.scalar(
                select(GenericVoiceGenerationCommand.id).where(
                    GenericVoiceGenerationCommand.background_job_id == job_id
                )
            )
            is not None,
        )

    @staticmethod
    def _command(session: Session, job_id: UUID, *, for_update: bool):
        statement = select(GenericVoiceGenerationCommand).where(
            GenericVoiceGenerationCommand.background_job_id == job_id
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise NarrationNotFound("generic voice command not found")
        return row

    def load_and_mark_generating(self, lease: JobLease) -> VoiceGeneratorWorkItem:
        def operation(session: Session):
            heartbeat_attempt(
                session,
                scope=self._scope,
                fence=lease.fence,
                progress_current=1,
                progress_total=2,
            )
            row = self._command(session, lease.fence.job_id, for_update=True)
            if row.state not in {"queued", "building"}:
                raise InvalidNarrationState("generic voice command is not runnable")
            draft = session.get(GenericVoiceDesignDraft, row.design_draft_id)
            if draft is None or draft.fingerprint != row.design_fingerprint:
                raise InvalidNarrationState("generic voice design changed")
            row.state = "building"
            row.attempt = lease.attempt_number
            row.progress_current = 1
            row.started_at = row.started_at or datetime.now(UTC)
            row.updated_at = datetime.now(UTC)
            return VoiceGeneratorWorkItem(
                lease=lease,
                command_id=row.id,
                novel_id=LOCAL_WORKSPACE_ID,
                character_id=LOCAL_WORKSPACE_ID,
                host_request=VoiceGeneratorHostRequest(
                    request_id=row.host_request_id,
                    instruction=draft.instruction,
                    instruction_digest=draft.instruction_digest,
                    language=draft.language,
                    seed=draft.seed,
                ),
                draft_fingerprint=draft.fingerprint,
                parameters_digest=draft.parameters_digest,
                language=draft.language,
                seed=draft.seed,
            )

        return _transaction(self._session_factory, operation)

    def advance(self, work: VoiceGeneratorWorkItem, target: VoiceGeneratorCommandState) -> None:
        del target
        _transaction(
            self._session_factory,
            lambda session: heartbeat_attempt(
                session, scope=self._scope, fence=work.lease.fence
            ),
        )

    def heartbeat_and_job_state(self, work: VoiceGeneratorWorkItem) -> str:
        def operation(session: Session):
            job = session.get(BackgroundJob, work.lease.fence.job_id)
            if job is None:
                raise NarrationNotFound("generic voice job not found")
            if job.state == "running":
                heartbeat_attempt(session, scope=self._scope, fence=work.lease.fence)
            return job.state

        return _transaction(self._session_factory, operation)

    def acknowledge_cancel(self, work: VoiceGeneratorWorkItem) -> None:
        _transaction(
            self._session_factory,
            lambda session: acknowledge_cancel(
                session, scope=self._scope, fence=work.lease.fence
            ),
        )

    def record_host_terminal(
        self, work: VoiceGeneratorWorkItem, receipt: HostGenerationReceipt
    ) -> None:
        del work, receipt

    def fail(
        self,
        work: VoiceGeneratorWorkItem,
        *,
        state: VoiceGeneratorCommandState,
        failure_code: str,
        classification: str = "non_retryable",
    ) -> None:
        del state

        def operation(session: Session):
            row = self._command(session, work.lease.fence.job_id, for_update=True)
            fail_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                classification=classification,
                error_code=failure_code,
            )
            now = datetime.now(UTC)
            row.state = "failed"
            row.failure_code = GENERIC_PACK_GENERATION_FAILED
            row.progress_current = 2
            row.completed_at = now
            row.updated_at = now
            slot = session.get(GenericVoicePackVersionSlot, _slot_id(session, row))
            pack = session.get(GenericVoicePackVersion, row.pack_version_id)
            if slot is not None:
                slot.state = "failed"
                slot.failure_code = GENERIC_PACK_GENERATION_FAILED
                slot.updated_at = now
            if pack is not None:
                pack.state = "failed"
                pack.failure_code = GENERIC_PACK_GENERATION_FAILED
                pack.updated_at = now

        _transaction(self._session_factory, operation)

    def terminalize_job_in_session(self, session: Session, *, job_id: UUID) -> None:
        row = self._command(session, job_id, for_update=True)
        if row.state in {"ready", "failed", "cancelled", "superseded"}:
            return
        job = session.get(BackgroundJob, job_id)
        if job is None or job.state not in {"failed", "dead_letter", "cancelled"}:
            return
        row.state = "cancelled" if job.state == "cancelled" else "failed"
        row.failure_code = None if job.state == "cancelled" else GENERIC_PACK_GENERATION_FAILED
        row.progress_current = 2
        row.completed_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)

    def publish(
        self,
        work: VoiceGeneratorWorkItem,
        prepared: PreparedVoiceGeneratorPublication,
    ) -> None:
        def operation(session: Session):
            if work.lease.resource_fence is None:
                raise InvalidNarrationState("generic voice lease lacks resource fence")
            context = lock_result_publish_fences(
                session,
                scope=self._scope,
                job_fence=work.lease.fence,
                resource_fence=work.lease.resource_fence,
            )
            row = self._command(session, work.lease.fence.job_id, for_update=True)
            draft = session.get(GenericVoiceDesignDraft, row.design_draft_id)
            pack = session.get(GenericVoicePackVersion, row.pack_version_id)
            slot = session.get(GenericVoicePackVersionSlot, _slot_id(session, row))
            if draft is None or pack is None or slot is None:
                raise InvalidNarrationState("generic voice publication scope changed")
            if (
                row.state != "building"
                or pack.state != "building"
                or slot.state != "generating"
                or slot.generation_command_id != row.id
            ):
                raise JobFenceError("generic voice publication was superseded")
            now = datetime.now(UTC)
            generated_asset = MediaAsset(
                id=prepared.generated.asset_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=None,
                kind="narration_voice_reference",
                asset_class="voice_reference",
                mime_type="audio/wav",
                byte_size=prepared.generated.byte_size,
                duration_ms=prepared.generator_result.audio_metrics.duration_milliseconds,
                sample_rate=prepared.generator_result.audio_metrics.sample_rate_hz,
                channels=prepared.generator_result.audio_metrics.channels,
                storage_backend="local",
                state="ready",
                retention_policy="private_voice_source",
                checksum_algorithm="sha256",
                validation_json={"schema_version": "generic-voice-reference/1"},
                verified_at=now,
                storage_path=prepared.generated.relative_path,
                content_hash=prepared.generated.actual_sha256,
                metadata_json={"slot_key": row.slot_key, "pack_version_id": str(pack.id)},
                created_at=now,
            )
            validation_asset = MediaAsset(
                id=prepared.validation.asset_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=None,
                kind="narration_voice_preview",
                asset_class="preview",
                mime_type="audio/wav",
                byte_size=prepared.validation.byte_size,
                duration_ms=prepared.nano_duration_ms,
                sample_rate=prepared.nano_sample_rate_hz,
                channels=prepared.nano_channels,
                storage_backend="local",
                state="ready",
                retention_policy="private_voice_validation",
                checksum_algorithm="sha256",
                validation_json={"schema_version": "generic-voice-nano-validation/1"},
                verified_at=now,
                storage_path=prepared.validation.relative_path,
                content_hash=prepared.validation.actual_sha256,
                metadata_json={"slot_key": row.slot_key, "pack_version_id": str(pack.id)},
                created_at=now,
            )
            generator_run = ModelRunRecord(
                id=uuid5(row.id, "generator-model-run"),
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id="local-native-host",
                requested_model_id=VOICE_GENERATOR_MODEL_ID,
                requested_revision=VOICE_GENERATOR_REVISION,
                actual_provider_id="local-native-host",
                actual_model_id=VOICE_GENERATOR_MODEL_ID,
                actual_revision=VOICE_GENERATOR_REVISION,
                model_fingerprint=prepared.generator_result.runtime_fingerprint,
                parameters_digest=draft.parameters_digest,
                input_digest_key_id="sha256-public-v1",
                input_digest=draft.instruction_digest,
                output_digest=prepared.generated.actual_sha256,
                duration_ms=max(
                    0,
                    int(
                        (
                            prepared.generator_result.completed_at
                            - prepared.generator_result.started_at
                        ).total_seconds()
                        * 1000
                    ),
                ),
                provider_request_id=str(prepared.generator_result.request_id),
                result_classification="success",
                created_at=now,
            )
            nano_identity = production_nano_experiment_identity()
            nano_run = ModelRunRecord(
                id=uuid5(row.id, "nano-model-run"),
                attempt_id=work.lease.fence.attempt_id,
                requested_provider_id="local-sidecar",
                requested_model_id=NANO_MODEL_ID,
                requested_revision=nano_identity.requested_revision,
                actual_provider_id=nano_identity.actual_provider_id,
                actual_model_id=nano_identity.actual_model_id,
                actual_revision=nano_identity.actual_revision,
                model_fingerprint=prepared.nano_model_fingerprint,
                parameters_digest=prepared.nano_parameters_digest,
                input_digest_key_id=prepared.nano_input_digest_key_id,
                input_digest=prepared.nano_input_digest,
                output_digest=prepared.validation.actual_sha256,
                duration_ms=prepared.nano_duration_ms,
                provider_request_id=str(work.lease.fence.attempt_id),
                result_classification="success",
                created_at=now,
            )
            profile = VoiceProfile(
                id=uuid5(row.id, "voice-profile"),
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=None,
                name=f"通用角色音色 · {slot.label}",
                status="draft",
                version=1,
                created_at=now,
                updated_at=now,
            )
            rights = VoiceRightsRecord(
                id=uuid5(row.id, "voice-rights"),
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=None,
                source_kind="voice_generator",
                source_identifier=f"local://generic-voice/{pack.id}/{slot.slot_key}",
                notice_version="voice-generator-private-use/1",
                purpose="private_novel_narration",
                commercial_use=False,
                redistribution=False,
                voice_cloning=False,
                confirmed_actor="local-owner",
                confirmed_at=now,
                risk_flags_json=[],
            )
            version = VoiceProfileVersion(
                id=uuid5(row.id, "voice-version"),
                profile_id=profile.id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                version_number=1,
                source_type="generated",
                state="locked",
                provider_id="local-native-host",
                model_id=VOICE_GENERATOR_MODEL_ID,
                model_revision=VOICE_GENERATOR_REVISION,
                reference_asset_id=generated_asset.id,
                preview_asset_id=validation_asset.id,
                model_run_id=nano_run.id,
                rights_record_id=rights.id,
                description_digest_key_id="sha256-public-v1",
                description_digest=draft.instruction_digest,
                language="zh-CN",
                seed=draft.seed,
                parameters_json={
                    "schema_version": "generic-voice-version/1",
                    "design_fingerprint": draft.fingerprint,
                },
                fingerprint=canonical_sha256(
                    {
                        "schema_version": "generic-voice-version/1",
                        "design_fingerprint": draft.fingerprint,
                        "reference_audio_sha256": prepared.generated.actual_sha256,
                        "validation_audio_sha256": prepared.validation.actual_sha256,
                    }
                ),
                quality_state="accepted",
                activation_basis="generic_voice_pack_generation",
                validation_basis="machine_validated",
                created_at=now,
            )
            rights_event = VoiceRightsEvent(
                id=uuid5(row.id, "voice-rights-event"),
                rights_record_id=rights.id,
                event_key=f"generic-voice-confirmed:{row.id.hex}",
                event_type="confirmed",
                actor="local-owner",
                reason_code=None,
                occurred_at=now,
            )
            session.add_all(
                [generated_asset, validation_asset, generator_run, nano_run, profile, rights]
            )
            session.flush()
            session.add_all([rights_event, version])
            session.flush()
            profile.current_version_id = version.id
            profile.status = "active"
            profile.version = 2
            row.generated_reference_asset_id = generated_asset.id
            row.nano_validation_asset_id = validation_asset.id
            row.generator_model_run_id = generator_run.id
            row.nano_model_run_id = nano_run.id
            row.voice_profile_id = profile.id
            row.voice_version_id = version.id
            row.state = "ready"
            row.progress_current = 2
            row.completed_at = now
            row.updated_at = now
            slot.voice_profile_id = profile.id
            slot.voice_version_id = version.id
            slot.reference_audio_sha256 = prepared.generated.actual_sha256
            slot.validation_audio_sha256 = prepared.validation.actual_sha256
            slot.rights_approved = True
            slot.quality_approved = True
            slot.state = "validated"
            slot.failure_code = None
            slot.updated_at = now
            pack.validated_slot_count = sum(
                candidate.state in {"validated", "reused"}
                for candidate in _slots(session, pack.id, for_update=True)
            )
            if pack.validated_slot_count == 24:
                previous = tuple(
                    session.scalars(
                        select(GenericVoicePackVersion)
                        .where(
                            GenericVoicePackVersion.workspace_id == LOCAL_WORKSPACE_ID,
                            GenericVoicePackVersion.language == "zh-CN",
                            GenericVoicePackVersion.state == "active",
                            GenericVoicePackVersion.id != pack.id,
                        )
                        .with_for_update()
                    )
                )
                for item in previous:
                    item.state = "retired_for_new_use"
                    item.retired_at = now
                    item.updated_at = now
                pack.state = "active"
                pack.ready_at = now
                pack.activated_at = now
            else:
                _enqueue_next_slot(session, pack)
            pack.updated_at = now
            result_digest = canonical_sha256(
                {
                    "schema_version": "generic-voice-generation-result/1",
                    "command_id": str(row.id),
                    "voice_version_id": str(version.id),
                    "reference_audio_sha256": prepared.generated.actual_sha256,
                    "validation_audio_sha256": prepared.validation.actual_sha256,
                }
            )
            complete_attempt(
                session,
                scope=self._scope,
                fence=work.lease.fence,
                actual_result_digest=result_digest,
                publication_context=context,
            )
            session.flush()

        _transaction(self._session_factory, operation)


def _slot_id(session: Session, row: GenericVoiceGenerationCommand) -> UUID:
    identifier = session.scalar(
        select(GenericVoicePackVersionSlot.id).where(
            GenericVoicePackVersionSlot.pack_version_id == row.pack_version_id,
            GenericVoicePackVersionSlot.slot_key == row.slot_key,
        )
    )
    if identifier is None:
        raise NarrationNotFound("generic voice pack slot not found")
    return identifier


__all__ = [
    "SqlAlchemyGenericVoicePackService",
    "SqlAlchemyGenericVoiceRepository",
    "resolve_generic_voice_slot_media",
]
