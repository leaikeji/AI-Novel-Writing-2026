"""Thin adapters for the three frozen Plan 74 maintenance tool names."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from ..assistant_context import TARGET_AGENT_ID
from .access_context import LibraryAccessEvidence, current_library_access
from .errors import PrivateLibraryValidationError
from .hashing import canonical_json
from .maintenance import (
    ChangeRequestStore,
    MaintenanceActionExecutor,
    P1MaintenanceActionExecutor,
    SqlAlchemyChangeRequestStore,
    apply_library_change,
    classify_author_intent,
    prepare_library_change,
    query_library,
    undo_library_change,
)
from .maintenance_contracts import (
    MAX_CHANGE_REQUEST_BYTES,
    LibraryCaptureSource,
    LibraryChangeAction,
)


MODEL_AUTHORITY_FIELDS = frozenset({
    "authorized",
    "write_authorized",
    "session_id",
    "request_id",
    "author_text_hash",
    "author_text_sha256",
    "scope",
    "scope_kind",
    "scope_novel_id",
    "novel_id",
    "requires_review",
    "review_accepted",
    "accepted",
})


def _payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PrivateLibraryValidationError("tool payload must be an object")
    result = dict(value)
    if MODEL_AUTHORITY_FIELDS.intersection(result):
        raise PrivateLibraryValidationError(
            "tool payload cannot provide authorization or trusted scope"
        )
    if len(canonical_json(result).encode("utf-8")) > MAX_CHANGE_REQUEST_BYTES:
        raise PrivateLibraryValidationError("tool payload is too large")
    return result


def _access() -> LibraryAccessEvidence:
    access = current_library_access()
    if (
        access is None
        or access.agent_id != TARGET_AGENT_ID
        or not access.session_id.strip()
        or not access.author_text.strip()
    ):
        raise PrivateLibraryValidationError(
            "trusted private-library request context is required"
        )
    expires_at = access.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise PrivateLibraryValidationError(
            "private-library request context has expired"
        )
    return access


class LibraryMaintenanceTools:
    """Injectable adapter; registration and transaction ownership stay external."""

    def __init__(
        self,
        session: Session,
        *,
        store: ChangeRequestStore | None = None,
        executor: MaintenanceActionExecutor | None = None,
    ) -> None:
        self.session = session
        self.store = store or SqlAlchemyChangeRequestStore(session)
        self.executor = executor or P1MaintenanceActionExecutor(session)

    def novel_library_query(
        self, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        access = _access()
        query = _payload(payload)
        allowed = {
            "kind", "proposal_id", "asset_id", "asset_type",
            "include_archived", "search", "limit",
            "offset", "scope_filter", "enabled_filter", "projection",
        }
        _reject_extra(query, allowed)
        return query_library(self.store, access, query)

    def novel_library_prepare_change(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        access = _access()
        request = _payload(payload)
        _reject_extra(request, {"actions", "source", "idempotency_key"})
        try:
            actions = tuple(
                LibraryChangeAction.model_validate(item)
                for item in request.get("actions", [])
            )
            source_payload = request.get("source")
            source = (
                LibraryCaptureSource.model_validate(source_payload)
                if source_payload is not None
                else None
            )
        except PydanticValidationError as error:
            raise PrivateLibraryValidationError(
                "maintenance change payload is invalid"
            ) from error
        intent = classify_author_intent(access.author_text)
        return prepare_library_change(
            self.store,
            access,
            actions=actions,
            intent=intent,
            idempotency_key=(
                str(request["idempotency_key"])
                if request.get("idempotency_key") is not None
                else None
            ),
            source=source,
        )

    def novel_library_apply_change(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        access = _access()
        request = _payload(payload)
        _reject_extra(request, {"proposal_id", "proposal_version", "mode"})
        raw_version = request.get("proposal_version")
        try:
            proposal_id = UUID(str(request["proposal_id"]))
            if isinstance(raw_version, bool) or not isinstance(raw_version, int):
                raise ValueError
            proposal_version = raw_version
        except (KeyError, TypeError, ValueError) as error:
            raise PrivateLibraryValidationError(
                "proposal_id and proposal_version are required"
            ) from error
        if proposal_version <= 0:
            raise PrivateLibraryValidationError("proposal_version must be positive")
        mode = str(request.get("mode", "apply"))
        intent = classify_author_intent(access.author_text)
        if mode == "undo":
            return undo_library_change(
                self.store,
                self.executor,
                access,
                proposal_id=proposal_id,
                expected_version=proposal_version,
                intent=intent,
            )
        if mode != "apply":
            raise PrivateLibraryValidationError("apply mode is not supported")
        return apply_library_change(
            self.store,
            self.executor,
            access,
            proposal_id=proposal_id,
            expected_version=proposal_version,
            intent=intent,
        )


def _reject_extra(payload: Mapping[str, Any], allowed: set[str]) -> None:
    extra = set(payload) - allowed
    if extra:
        raise PrivateLibraryValidationError(
            "unsupported tool payload fields: " + ",".join(sorted(extra))
        )


def novel_library_query(
    session: Session, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return LibraryMaintenanceTools(session).novel_library_query(payload)


def novel_library_prepare_change(
    session: Session, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return LibraryMaintenanceTools(session).novel_library_prepare_change(payload)


def novel_library_apply_change(
    session: Session, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return LibraryMaintenanceTools(session).novel_library_apply_change(payload)


__all__ = [
    "LibraryMaintenanceTools",
    "novel_library_apply_change",
    "novel_library_prepare_change",
    "novel_library_query",
]
