"""Atomic claims. No model calls and no automatic replay of uncertain work.

Callers must use a dedicated short-lived session: claim/advance commit their
own writes before returning authority to perform external work.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..novel_lifecycle import lock_active_novel
from .contracts import ActionIdentity, FrozenModel, FrozenRouteRequest, Scope, SkillInjectionPacketV1
from .models import WritingSkillDispatch


class ActionConflict(ValueError):
    """An action ID was reused with different author input or scope."""


class StaleFence(ValueError):
    """Another worker or cancellation already moved the action forward."""


@dataclass(frozen=True)
class Claim:
    id: UUID
    request: FrozenRouteRequest
    state: str
    fence: int
    acquired: bool
    packet: SkillInjectionPacketV1 | None
    job_ref: str | None

    @property
    def scope(self) -> Scope:
        return self.request.projection.scope

    @property
    def identity(self) -> ActionIdentity:
        return self.request.identity


class PendingSnapshot(FrozenModel):
    schema_version: Literal["route-input-pending/1"] = "route-input-pending/1"
    identity: ActionIdentity
    scope: Scope


@dataclass(frozen=True)
class PendingAction:
    id: UUID
    identity: ActionIdentity
    scope: Scope
    state: str
    fence: int
    acquired: bool = False
    packet: None = None
    job_ref: None = None


def _view(row: WritingSkillDispatch, *, acquired: bool = False) -> Claim | PendingAction:
    if row.route_snapshot.get("schema_version") == "route-input-pending/1":
        pending = PendingSnapshot.model_validate(row.route_snapshot)
        if row.method_packet is not None or row.job_ref is not None:
            raise ValueError("pending input cannot contain dispatch results")
        return PendingAction(row.id, pending.identity, pending.scope, row.state, row.fence, acquired)
    return Claim(row.id, FrozenRouteRequest.model_validate(row.route_snapshot),
                 row.state, row.fence, acquired,
                 SkillInjectionPacketV1.model_validate(row.method_packet) if row.method_packet else None,
                 row.job_ref)


def _identity_query(identity: ActionIdentity):
    return select(WritingSkillDispatch).where(
        WritingSkillDispatch.owner_id == identity.owner_id,
        WritingSkillDispatch.workspace_id == identity.workspace_id,
        WritingSkillDispatch.agent_id == identity.agent_id,
        WritingSkillDispatch.entry == identity.entry,
        WritingSkillDispatch.action_id == identity.action_id,
    )


def _lock_scope_novel(session: Session, scope: Scope) -> None:
    if scope.kind == "novel":
        lock_active_novel(session, scope.scope_id)


def lookup_action(session: Session, identity: ActionIdentity, scope: Scope,
                  client_input_hash: str, *, authorize: Callable[[Session, Scope], None]) -> Claim | PendingAction | None:
    """Check stable identity BEFORE calling any projection/config/model supplier.

authorize is the entry's existing authoritative scope checker, including draft
expiry/tab and document visibility. Values in Scope alone confer no authority.
"""
    if (identity.owner_id, identity.workspace_id) != (scope.owner_id, scope.workspace_id):
        raise ActionConflict("action_scope_mismatch")
    if len(client_input_hash) != 64 or any(c not in "0123456789abcdef" for c in client_input_hash):
        raise ValueError("invalid client input hash")
    authorize(session, scope)
    row = session.scalar(_identity_query(identity))
    if row is None:
        return None
    result = _view(row)
    if result.scope != scope or row.client_input_hash != client_input_hash:
        raise ActionConflict("action_input_conflict")
    return result


def read_action(session: Session, identity: ActionIdentity, scope: Scope, *,
                authorize: Callable[[Session, Scope], None]) -> Claim | PendingAction | None:
    """Read-only recovery: scope authorization, no input/config/model supplier."""
    if (identity.owner_id, identity.workspace_id) != (scope.owner_id, scope.workspace_id):
        raise ActionConflict("action_scope_mismatch")
    authorize(session, scope)
    row = session.scalar(_identity_query(identity))
    if row is None:
        return None
    result = _view(row)
    # Do not disclose whether this ID exists in another document or tab.
    return result if result.scope == scope else None


def claim_pending_action(session: Session, identity: ActionIdentity, scope: Scope,
                         client_input_hash: str, *, authorize: Callable[[Session, Scope], None]) -> Claim | PendingAction:
    """Commit the stable identity BEFORE input/configuration/network preparation."""
    _lock_scope_novel(session, scope)
    existing = lookup_action(session, identity, scope, client_input_hash, authorize=authorize)
    if existing is not None:
        session.commit()
        return existing
    snapshot = PendingSnapshot(identity=identity, scope=scope)
    inserted = session.execute(insert(WritingSkillDispatch).values(
        id=uuid4(), **identity.model_dump(), scope_kind=scope.kind,
        scope_id=scope.scope_id, novel_id=scope.scope_id if scope.kind == "novel" else None,
        client_input_hash=client_input_hash, route_request_key="0" * 64,
        route_snapshot=snapshot.model_dump(mode="json"), state="claimed", fence=1,
    ).on_conflict_do_nothing(constraint="uq_writing_skill_action")
      .returning(WritingSkillDispatch.id)).scalar_one_or_none()
    result = lookup_action(session, identity, scope, client_input_hash, authorize=authorize)
    if result is None:
        raise RuntimeError("pending claim vanished")
    session.commit()
    return replace(result, acquired=inserted is not None)


def freeze_prepared_action(session: Session, pending: PendingAction,
                           request: FrozenRouteRequest) -> Claim:
    """One-time fenced freeze. A failed/cancelled pending action cannot resume."""
    if not isinstance(pending, PendingAction) or pending.state != "claimed":
        raise StaleFence("input is no longer pending")
    _lock_scope_novel(session, pending.scope)
    if request.identity != pending.identity or request.projection.scope != pending.scope:
        raise ActionConflict("frozen_scope_mismatch")
    row = session.execute(update(WritingSkillDispatch).where(
        WritingSkillDispatch.id == pending.id, WritingSkillDispatch.state == "claimed",
        WritingSkillDispatch.fence == pending.fence,
        WritingSkillDispatch.route_snapshot == PendingSnapshot(identity=pending.identity, scope=pending.scope).model_dump(mode="json"),
    ).values(route_snapshot=request.model_dump(mode="json"), route_request_key=request.route_request_key,
             fence=pending.fence + 1, updated_at=func.now()).returning(WritingSkillDispatch)
       .execution_options(populate_existing=True)).scalar_one_or_none()
    if row is None:
        session.rollback()
        raise StaleFence("stale input freeze")
    result = _view(row, acquired=pending.acquired)
    session.commit()
    return result


def claim_action(session: Session, identity: ActionIdentity, scope: Scope,
                 client_input_hash: str, *, authorize: Callable[[Session, Scope], None],
                 freeze: Callable[[], FrozenRouteRequest]) -> Claim | PendingAction:
    _lock_scope_novel(session, scope)
    existing = lookup_action(session, identity, scope, client_input_hash, authorize=authorize)
    if existing:
        session.commit()
        return existing
    request = freeze()  # local snapshot only; NEVER a model/network operation
    if request.identity != identity or request.projection.scope != scope:
        raise ActionConflict("frozen_scope_mismatch")
    claim_id = uuid4()
    inserted = session.execute(insert(WritingSkillDispatch).values(
        id=claim_id, **identity.model_dump(), scope_kind=scope.kind,
        scope_id=scope.scope_id, novel_id=scope.scope_id if scope.kind == "novel" else None,
        client_input_hash=client_input_hash, route_request_key=request.route_request_key,
        route_snapshot=request.model_dump(mode="json"), state="claimed", fence=1,
    ).on_conflict_do_nothing(constraint="uq_writing_skill_action").returning(WritingSkillDispatch.id)).scalar_one_or_none()
    # A concurrent winner's frozen config wins, even if ours is newer.
    result = lookup_action(session, identity, scope, client_input_hash, authorize=authorize)
    if result is None:
        raise RuntimeError("claim vanished")
    session.commit()
    return replace(result, acquired=inserted is not None)


TRANSITIONS = {
    "claimed": frozenset({"routing_started", "route_ready", "cancelled", "stale", "failed"}),
    "routing_started": frozenset({"route_ready", "unknown", "failed", "cancelled", "stale"}),
    "route_ready": frozenset({"assembled", "cancelled", "stale", "failed"}),
    "assembled": frozenset({"dispatch_started", "cancelled", "stale", "failed"}),
    "dispatch_started": frozenset({"dispatched", "unknown", "failed", "cancelled", "stale"}),
}


def advance(session: Session, claim: Claim | PendingAction, target: str, *,
            packet: SkillInjectionPacketV1 | None = None, job_ref: str | None = None,
            error_code: str | None = None) -> Claim | PendingAction:
    """CAS fence; external-effect states are committed before callers send.

cancelled after dispatch_started is only valid after confirmed remote stop;
otherwise use unknown. Terminal states have no automatic retry transitions.
"""
    try:
        result = advance_in_transaction(session, claim, target, packet=packet,
                                        job_ref=job_ref, error_code=error_code)
    except StaleFence:
        session.rollback()
        raise
    session.commit()
    return result


def lock_assembled_action(session: Session, claim: Claim, *,
                          authorize: Callable[[Session, Scope], None]) -> Claim:
    """Lock before the business job lock; caller owns this short transaction.

    Never dispatch from the returned value until the caller has committed both
    job and dispatch. A cancellation or another worker wins by the same fence.
    """
    _lock_scope_novel(session, claim.request.projection.scope)
    authorize(session, claim.request.projection.scope)
    row = session.scalar(_identity_query(claim.request.identity).with_for_update())
    if row is None:
        raise StaleFence("missing_dispatch")
    current = _view(row)
    if (current.id != claim.id or current.fence != claim.fence
            or current.state != "assembled" or current.packet is None
            or current.request != claim.request or current.packet != claim.packet):
        raise StaleFence("stale_dispatch_fence")
    return current


def advance_in_transaction(session: Session, claim: Claim | PendingAction, target: str, *,
                           packet: SkillInjectionPacketV1 | None = None,
                           job_ref: str | None = None,
                           error_code: str | None = None) -> Claim | PendingAction:
    """Flush a fenced transition without committing any caller-owned writes.

    Business entry services use this to create/associate their existing job in
    the SAME transaction. The returned value is not dispatch authority until
    that transaction commits. Ordinary callers should use ``advance``.
    """
    _lock_scope_novel(session, claim.scope)
    if isinstance(claim, PendingAction) and (target not in {"failed", "cancelled", "stale"}
                                            or packet is not None or job_ref is not None):
        raise ValueError("pending input must be frozen before routing")
    if target not in TRANSITIONS.get(claim.state, ()):
        raise ValueError("illegal dispatch transition")
    if (
        claim.state == "dispatch_started"
        and target == "cancelled"
        and error_code != "remote_stop_confirmed"
    ):
        raise ValueError("dispatch cancellation needs confirmed remote stop")
    if (target == "assembled") != (packet is not None):
        raise ValueError("packet must be frozen exactly when assembled")
    if packet is not None and (
        packet.plan.source_hash != claim.request.projection.source_hash
        or packet.plan.catalog_version != claim.request.catalog_version
        or packet.plan.task != claim.request.projection.task
    ):
        raise ValueError("packet does not belong to frozen request")
    if target == "dispatched" and not (job_ref or claim.job_ref):
        raise ValueError("dispatched needs a job reference")
    values: dict = {"state": target, "fence": claim.fence + 1, "updated_at": func.now()}
    if packet is not None:
        values["method_packet"] = packet.model_dump(mode="json")
    if job_ref is not None:
        if target not in {"dispatch_started", "dispatched"} or not job_ref.strip() or len(job_ref) > 240:
            raise ValueError("invalid job reference")
        if claim.job_ref is not None and claim.job_ref != job_ref:
            raise ValueError("job reference is immutable")
        values["job_ref"] = job_ref
    if error_code is not None:
        if len(error_code) > 80:
            raise ValueError("error code too long")
        values["error_code"] = error_code
    updated = session.execute(update(WritingSkillDispatch).where(
        WritingSkillDispatch.id == claim.id,
        WritingSkillDispatch.owner_id == claim.identity.owner_id,
        WritingSkillDispatch.workspace_id == claim.identity.workspace_id,
        WritingSkillDispatch.state == claim.state, WritingSkillDispatch.fence == claim.fence,
    ).values(**values).returning(WritingSkillDispatch).execution_options(populate_existing=True)).scalar_one_or_none()
    if updated is None:
        raise StaleFence("stale_dispatch_fence")
    result = _view(updated)
    return result
