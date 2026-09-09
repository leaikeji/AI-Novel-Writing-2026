"""Database-backed idempotency receipts for voice profile creation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from ..models import VoiceActionReceipt
from .contracts import NarrationRequestScope
from .services import IdempotencyConflict, InvalidNarrationState
from .voices import VoiceProfileCreationReceipt


_VOICE_RECORD_SCHEMA_VERSION = "qwen-tts-voice/1"


@dataclass(frozen=True, slots=True)
class VoiceActionReceiptReservation:
    row_id: UUID
    resource_id: UUID
    state: Literal["reserved", "completed"]
    replay: bool


def stable_voice_action_uuid(operation: str, key: str) -> UUID:
    scope = NarrationRequestScope.fixed_local()
    return uuid5(
        NAMESPACE_URL,
        (
            "ai-novel-world-2026/narration/voice-product/"
            f"{scope.owner_id}/{scope.workspace_id}/{operation}/{key}"
        ),
    )


def database_now(session: Session) -> datetime:
    if session.get_bind().dialect.name == "postgresql":
        value = session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise InvalidNarrationState("database clock did not return a timestamp")
        return value
    return datetime.now(UTC)


def reserve_voice_action_receipt(
    session: Session,
    *,
    operation: str,
    idempotency_key: str,
    request_hash: str,
    resource_id: UUID,
) -> VoiceActionReceiptReservation:
    scope = NarrationRequestScope.fixed_local()
    receipt_id = uuid5(
        resource_id,
        f"{_VOICE_RECORD_SCHEMA_VERSION}/receipt:{operation}",
    )
    created = False
    if session.get_bind().dialect.name == "postgresql":
        statement = (
            postgresql_insert(VoiceActionReceipt.__table__)
            .values(
                id=receipt_id,
                owner_id=scope.owner_id,
                workspace_id=scope.workspace_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=resource_id,
                state="reserved",
                reserved_at=func.clock_timestamp(),
                completed_at=None,
            )
            .on_conflict_do_nothing()
            .returning(VoiceActionReceipt.id)
        )
        created = session.scalar(statement) == receipt_id
    else:
        existing = session.scalar(
            select(VoiceActionReceipt).where(
                VoiceActionReceipt.owner_id == scope.owner_id,
                VoiceActionReceipt.workspace_id == scope.workspace_id,
                VoiceActionReceipt.operation == operation,
                VoiceActionReceipt.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            session.add(
                VoiceActionReceipt(
                    id=receipt_id,
                    owner_id=scope.owner_id,
                    workspace_id=scope.workspace_id,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    resource_id=resource_id,
                    state="reserved",
                    reserved_at=database_now(session),
                    completed_at=None,
                )
            )
            session.flush()
            created = True
    row = session.scalar(
        select(VoiceActionReceipt)
        .where(
            VoiceActionReceipt.owner_id == scope.owner_id,
            VoiceActionReceipt.workspace_id == scope.workspace_id,
            VoiceActionReceipt.operation == operation,
            VoiceActionReceipt.idempotency_key == idempotency_key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise InvalidNarrationState("voice action receipt reservation disappeared")
    if (
        row.resource_id != resource_id
        or row.request_hash != request_hash
        or row.state not in {"reserved", "completed"}
    ):
        raise IdempotencyConflict("voice action key already names another request")
    return VoiceActionReceiptReservation(
        row_id=row.id,
        resource_id=row.resource_id,
        state=row.state,  # type: ignore[arg-type]
        replay=not created,
    )


def complete_voice_action_receipt(
    session: Session,
    row_id: UUID,
    *,
    at: datetime,
) -> None:
    row = session.scalar(
        select(VoiceActionReceipt)
        .where(VoiceActionReceipt.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise InvalidNarrationState("voice action receipt disappeared")
    if row.state == "completed":
        return
    if row.state != "reserved" or row.completed_at is not None:
        raise InvalidNarrationState("voice action receipt cannot be completed")
    row.state = "completed"
    row.completed_at = max(at, row.reserved_at)


class SqlAlchemyVoiceActionReceiptPort:
    """Serialize one profile-creation key inside the caller transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._reserved_by_profile: dict[UUID, UUID] = {}

    def reserve(
        self,
        *,
        idempotency_key: str,
        payload_sha256: str,
        profile_id: UUID,
    ) -> VoiceProfileCreationReceipt:
        reservation = reserve_voice_action_receipt(
            self._session,
            operation="create_voice_profile",
            idempotency_key=idempotency_key,
            request_hash=payload_sha256,
            resource_id=profile_id,
        )
        self._reserved_by_profile[profile_id] = reservation.row_id
        return VoiceProfileCreationReceipt(
            profile_id=profile_id,
            payload_sha256=payload_sha256,
            replay=reservation.replay,
        )

    def complete(self, *, profile_id: UUID) -> None:
        receipt_id = self._reserved_by_profile.get(profile_id)
        if receipt_id is None:
            raise InvalidNarrationState("profile receipt was not reserved")
        complete_voice_action_receipt(
            self._session,
            receipt_id,
            at=database_now(self._session),
        )
