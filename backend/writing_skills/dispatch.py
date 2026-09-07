"""Local deterministic preparation, deliberately not a runtime activation switch."""
from collections.abc import Callable

from sqlalchemy.orm import Session

from .contracts import ActionIdentity, FrozenRouteRequest, Scope, SkillInjectionPacketV1
from .persistence import Claim, PendingAction, StaleFence, advance, claim_action


def prepare_action(*, session_factory: Callable[[], Session], identity: ActionIdentity,
                   scope: Scope, client_input_hash: str,
                   authorize: Callable[[Session, Scope], None],
                   freeze: Callable[[], FrozenRouteRequest],
                   compose: Callable[[FrozenRouteRequest], SkillInjectionPacketV1],
                   still_current: Callable[[FrozenRouteRequest], bool]) -> Claim | PendingAction:
    """Only the winning action prepares; compose must be local deterministic IO.

This function never sends to a model. Runtime adapters require independent
entry-specific public load-policy gates before dispatch_started. Replays return
the existing state, including pending/unknown, without re-running callbacks.
"""
    with session_factory() as session:
        current = claim_action(session, identity, scope, client_input_hash,
                               authorize=authorize, freeze=freeze)
    if not current.acquired:
        return current
    try:
        packet = compose(current.request)
        with session_factory() as session:
            authorize(session, scope)
        if not still_current(current.request):
            with session_factory() as session:
                return advance(session, current, "stale", error_code="source_or_config_changed")
        with session_factory() as session:
            current = advance(session, current, "route_ready")
        with session_factory() as session:
            return advance(session, current, "assembled", packet=packet)
    except StaleFence:
        raise
    except Exception:
        # No external execution occurred; a local deterministic failure is known.
        with session_factory() as session:
            try:
                advance(session, current, "failed", error_code="preparation_failed")
            except StaleFence:
                pass  # a concurrent cancellation retains authority
        raise
