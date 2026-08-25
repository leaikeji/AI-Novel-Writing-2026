"""Short-lived, process-local transport for novel page context snapshots.

The registry deliberately performs no database, file, log, HTTP, or QwenPaw
operations.  A later integration owner may share one instance between the
PawApp endpoint and the public AgentScope Middleware adapter.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import base64
import json
import re
import secrets
from threading import RLock
from typing import Any

from .assistant_context import (
    MAX_CONTEXT_CHARACTERS,
    MAX_SELECTION_CHARACTERS,
    TARGET_AGENT_ID,
)


CONTEXT_REF_RANDOM_BYTES = 32
CONTEXT_REF_MAX_TTL = timedelta(minutes=5)
CONTEXT_REF_IDEMPOTENT_LEASE = timedelta(seconds=30)
CONTEXT_REF_MAX_REQUEST_BYTES = 96 * 1024
CONTEXT_REF_MAX_PER_TAB = 8
CONTEXT_REF_MAX_PROCESS = 64
CONTEXT_REF_OWNER_RATE_LIMIT = 30
CONTEXT_REF_OWNER_RATE_WINDOW = timedelta(minutes=1)
CONTEXT_SCHEMA_VERSION = 2
CONTEXT_SNAPSHOT_MAX_TTL = timedelta(minutes=20)
CONTEXT_MAX_CLOCK_SKEW = timedelta(seconds=60)
SELECTION_CONTEXT_MAX_CHARACTERS = 1_500


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_CONTEXT_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_PAGE_SECTIONS = frozenset(
    {"chapters", "outline", "roles", "clues", "settings"},
)
_PAGE_VIEWS = frozenset(
    {
        "chapter-list",
        "chapter-editor",
        "title-editor",
        "chapter-outline-editor",
        "novel-outline",
        "character-list",
        "character-editor",
        "relationship-graph",
        "relationship-editor",
        "clue-list",
        "storyline-editor",
        "foreshadow-editor",
        "novel-settings",
    },
)
_ENTITY_TYPES = frozenset(
    {
        "novel",
        "volume",
        "document",
        "outline",
        "character",
        "relationship",
        "storyline",
        "foreshadow",
        "setting",
    },
)


class ContextRefCreateErrorCode(str, Enum):
    """Safe endpoint-facing rejection codes; none disclose registry state."""

    INVALID_BINDING = "invalid-binding"
    REQUEST_TOO_LARGE = "request-too-large"
    INVALID_SNAPSHOT = "invalid-snapshot"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    INVALID_TIME_WINDOW = "invalid-time-window"
    CONTEXT_TOO_LARGE = "context-too-large"
    SELECTION_TOO_LARGE = "selection-too-large"
    INVALID_BUDGET = "invalid-budget"
    RATE_LIMITED = "rate-limited"


class ContextRefCreateError(ValueError):
    """A bounded validation failure that never includes author content."""

    def __init__(self, code: ContextRefCreateErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ContextRefLeaseStatus(str, Enum):
    LEASED = "leased"
    INVALID = "invalid"


@dataclass(frozen=True)
class ContextRefBinding:
    """Scope repeated at creation and lease time.

    ``session_id`` may be absent while a new workbench chat is being prepared.
    The first successful lease then binds the entry to its concrete session.
    """

    owner_token: str
    tab_instance: str
    agent_id: str
    novel_id: str
    document_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class ContextRefCreated:
    context_ref: str = field(repr=False)
    expires_at: datetime
    context_revision: int
    payload_characters: int


@dataclass(frozen=True)
class ContextRefLeaseDiagnostic:
    status: ContextRefLeaseStatus
    payload_characters: int = 0
    context_revision: int | None = None


@dataclass(frozen=True)
class ContextRefLeaseResult:
    """Internal lease result whose repr intentionally omits page content."""

    status: ContextRefLeaseStatus
    payload_characters: int = 0
    context_revision: int | None = None
    expires_at: datetime | None = None
    lease_expires_at: datetime | None = None
    _serialized_snapshot: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def accepted(self) -> bool:
        return self.status is ContextRefLeaseStatus.LEASED

    @property
    def snapshot(self) -> dict[str, Any] | None:
        if self._serialized_snapshot is None:
            return None
        value = json.loads(self._serialized_snapshot)
        return value if isinstance(value, dict) else None

    def diagnostic(self) -> ContextRefLeaseDiagnostic:
        return ContextRefLeaseDiagnostic(
            status=self.status,
            payload_characters=self.payload_characters,
            context_revision=self.context_revision,
        )


@dataclass(frozen=True)
class ContextRefRegistryDiagnostic:
    """Aggregate-only observability with no refs, bindings, or page content."""

    active_entries: int
    leased_entries: int
    rate_owner_count: int
    created_total: int
    first_lease_total: int
    lease_success_total: int
    invalid_lease_total: int
    evicted_total: int
    expired_total: int


@dataclass(frozen=True)
class _ValidatedSnapshot:
    serialized: str = field(repr=False)
    expires_at: datetime
    context_revision: int
    payload_characters: int


@dataclass
class _ContextRefEntry:
    binding: ContextRefBinding
    serialized_snapshot: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    context_revision: int
    payload_characters: int
    lease_session_id: str | None = None
    lease_agent_id: str | None = None
    lease_expires_at: datetime | None = None


def _utc_now(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("registry clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _safe_integer(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 9_007_199_254_740_991
    )


def _bounded_string(
    value: object,
    minimum: int,
    maximum: int,
    *,
    stripped: bool = False,
) -> bool:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        return False
    return not stripped or value == value.strip()


def _optional_bounded_string(
    value: object,
    maximum: int = 200,
) -> bool:
    return value is None or _bounded_string(
        value,
        1,
        maximum,
        stripped=True,
    )


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _only_keys(
    value: Mapping[str, object],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> bool:
    keys = set(value)
    return required <= keys and keys <= required | optional


def _valid_binding(binding: ContextRefBinding, *, lease: bool) -> bool:
    return (
        isinstance(binding, ContextRefBinding)
        and isinstance(binding.owner_token, str)
        and bool(_TOKEN_PATTERN.fullmatch(binding.owner_token))
        and isinstance(binding.tab_instance, str)
        and bool(_TOKEN_PATTERN.fullmatch(binding.tab_instance))
        and binding.agent_id == TARGET_AGENT_ID
        and _bounded_string(binding.novel_id, 1, 200, stripped=True)
        and _optional_bounded_string(binding.document_id)
        and _optional_bounded_string(binding.session_id)
        and (not lease or binding.session_id is not None)
    )


def _validate_entity(value: object) -> bool:
    if not isinstance(value, Mapping) or not _only_keys(
        value,
        required=frozenset({"type"}),
        optional=frozenset({"id", "title"}),
    ):
        return False
    return (
        value.get("type") in _ENTITY_TYPES
        and (
            "id" not in value
            or _bounded_string(value.get("id"), 1, 200, stripped=True)
        )
        and (
            "title" not in value
            or _bounded_string(value.get("title"), 0, 500)
        )
    )


def _validate_document(value: object) -> bool:
    if not isinstance(value, Mapping) or not _only_keys(
        value,
        required=frozenset(
            {
                "id",
                "kind",
                "title",
                "draftVersion",
                "savedContentHash",
                "dirty",
            },
        ),
        optional=frozenset({"volumeId", "chapterNumber"}),
    ):
        return False
    return (
        _bounded_string(value.get("id"), 1, 200, stripped=True)
        and (
            "volumeId" not in value
            or _bounded_string(
                value.get("volumeId"),
                1,
                200,
                stripped=True,
            )
        )
        and _bounded_string(value.get("kind"), 1, 100, stripped=True)
        and _bounded_string(value.get("title"), 0, 500)
        and _safe_integer(value.get("draftVersion"))
        and _bounded_string(value.get("savedContentHash"), 0, 200)
        and isinstance(value.get("dirty"), bool)
        and (
            "chapterNumber" not in value
            or _safe_integer(value.get("chapterNumber"))
        )
    )


def _validate_editing(value: object) -> bool:
    if not isinstance(value, Mapping) or not _only_keys(
        value,
        required=frozenset({"fields"}),
        optional=frozenset({"focusedFieldId"}),
    ):
        return False
    fields = value.get("fields")
    if not isinstance(fields, list):
        return False
    field_ids: set[str] = set()
    for item in fields:
        if not isinstance(item, Mapping) or not _only_keys(
            item,
            required=frozenset(
                {
                    "id",
                    "label",
                    "value",
                    "dirty",
                    "truncated",
                    "characterCount",
                    "persistence",
                },
            ),
        ):
            return False
        field_id = item.get("id")
        if (
            not _bounded_string(field_id, 1, 200, stripped=True)
            or field_id in field_ids
            or not _bounded_string(item.get("label"), 1, 500)
            or not isinstance(item.get("value"), str)
            or not isinstance(item.get("dirty"), bool)
            or not isinstance(item.get("truncated"), bool)
            or not _safe_integer(item.get("characterCount"))
            or item.get("persistence")
            not in {"autosave", "explicit-save"}
        ):
            return False
        field_ids.add(field_id)
    return "focusedFieldId" not in value or (
        isinstance(value.get("focusedFieldId"), str)
        and value.get("focusedFieldId") in field_ids
    )


def _validate_selection(
    value: object,
    *,
    revision: int,
    now: datetime,
    snapshot_expires_at: datetime,
) -> ContextRefCreateErrorCode | None:
    if not isinstance(value, Mapping) or not _only_keys(
        value,
        required=frozenset(
            {
                "id",
                "fieldId",
                "text",
                "startUtf16",
                "endUtf16",
                "direction",
                "before",
                "after",
                "sourceValueSha256",
                "contextRevision",
                "createdAt",
                "expiresAt",
            },
        ),
    ):
        return ContextRefCreateErrorCode.INVALID_SNAPSHOT
    text = value.get("text")
    if not isinstance(text, str) or not text:
        return ContextRefCreateErrorCode.INVALID_SNAPSHOT
    if _utf16_length(text) > MAX_SELECTION_CHARACTERS:
        return ContextRefCreateErrorCode.SELECTION_TOO_LARGE
    before = value.get("before")
    after = value.get("after")
    start = value.get("startUtf16")
    end = value.get("endUtf16")
    created_at = _parse_timestamp(value.get("createdAt"))
    expires_at = _parse_timestamp(value.get("expiresAt"))
    if (
        not _bounded_string(value.get("id"), 1, 200, stripped=True)
        or not _bounded_string(
            value.get("fieldId"),
            1,
            200,
            stripped=True,
        )
        or not _safe_integer(start)
        or not _safe_integer(end)
        or end <= start
        or value.get("direction") not in {"forward", "backward", "none"}
        or not isinstance(before, str)
        or _utf16_length(before) > SELECTION_CONTEXT_MAX_CHARACTERS
        or not isinstance(after, str)
        or _utf16_length(after) > SELECTION_CONTEXT_MAX_CHARACTERS
        or not isinstance(value.get("sourceValueSha256"), str)
        or not _SHA256_PATTERN.fullmatch(value["sourceValueSha256"])
        or value.get("contextRevision") != revision
        or created_at is None
        or expires_at is None
        or expires_at <= created_at
        or expires_at - created_at > CONTEXT_SNAPSHOT_MAX_TTL
        or expires_at <= now
        or expires_at > snapshot_expires_at
    ):
        return ContextRefCreateErrorCode.INVALID_SNAPSHOT
    return None


def _validate_budget(value: object) -> bool:
    if not isinstance(value, Mapping) or not _only_keys(
        value,
        required=frozenset(
            {
                "maxCharacters",
                "usedCharacters",
                "truncated",
                "omittedFieldIds",
            },
        ),
    ):
        return False
    omitted = value.get("omittedFieldIds")
    return (
        value.get("maxCharacters") == MAX_CONTEXT_CHARACTERS
        and _safe_integer(value.get("usedCharacters"))
        and value["usedCharacters"] <= MAX_CONTEXT_CHARACTERS
        and isinstance(value.get("truncated"), bool)
        and isinstance(omitted, list)
        and all(
            _bounded_string(item, 1, 200, stripped=True)
            for item in omitted
        )
        and len(omitted) == len(set(omitted))
    )


def _validate_snapshot(
    snapshot: Mapping[str, object],
    binding: ContextRefBinding,
    now: datetime,
) -> _ValidatedSnapshot:
    if not isinstance(snapshot, Mapping) or not _only_keys(
        snapshot,
        required=frozenset(
            {
                "schemaVersion",
                "contextRevision",
                "capturedAt",
                "expiresAt",
                "agentId",
                "novel",
                "page",
                "budget",
            },
        ),
        optional=frozenset(
            {"sessionId", "entity", "document", "editing", "selection"},
        ),
    ):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        )
    if snapshot.get("schemaVersion") != CONTEXT_SCHEMA_VERSION:
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.UNSUPPORTED_SCHEMA,
        )
    revision = snapshot.get("contextRevision")
    if not _safe_integer(revision):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        )
    captured_at = _parse_timestamp(snapshot.get("capturedAt"))
    expires_at = _parse_timestamp(snapshot.get("expiresAt"))
    if (
        captured_at is None
        or expires_at is None
        or expires_at <= captured_at
        or captured_at > now + CONTEXT_MAX_CLOCK_SKEW
        or expires_at - captured_at > CONTEXT_SNAPSHOT_MAX_TTL
        or expires_at <= now
    ):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_TIME_WINDOW,
        )
    if snapshot.get("agentId") != binding.agent_id:
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_BINDING,
        )
    if "sessionId" in snapshot and not _bounded_string(
        snapshot.get("sessionId"),
        1,
        200,
        stripped=True,
    ):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        )
    snapshot_session = snapshot.get("sessionId")
    if snapshot_session != binding.session_id:
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_BINDING,
        )

    novel = snapshot.get("novel")
    if not isinstance(novel, Mapping) or not _only_keys(
        novel,
        required=frozenset({"id", "title"}),
    ) or (
        novel.get("id") != binding.novel_id
        or not _bounded_string(novel.get("id"), 1, 200, stripped=True)
        or not _bounded_string(novel.get("title"), 1, 500)
    ):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_BINDING,
        )

    page = snapshot.get("page")
    if not isinstance(page, Mapping) or not _only_keys(
        page,
        required=frozenset({"section", "view"}),
        optional=frozenset({"modal"}),
    ) or (
        page.get("section") not in _PAGE_SECTIONS
        or page.get("view") not in _PAGE_VIEWS
        or (
            "modal" in page
            and page.get("modal") not in _PAGE_VIEWS
        )
    ):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        )

    document = snapshot.get("document")
    snapshot_document_id = (
        document.get("id") if isinstance(document, Mapping) else None
    )
    if (
        snapshot_document_id != binding.document_id
        or (
            "document" in snapshot
            and not _validate_document(document)
        )
        or (
            "entity" in snapshot
            and not _validate_entity(snapshot.get("entity"))
        )
        or (
            "editing" in snapshot
            and not _validate_editing(snapshot.get("editing"))
        )
    ):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_BINDING
            if snapshot_document_id != binding.document_id
            else ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        )

    if "selection" in snapshot:
        selection_error = _validate_selection(
            snapshot.get("selection"),
            revision=revision,
            now=now,
            snapshot_expires_at=expires_at,
        )
        if selection_error is not None:
            raise ContextRefCreateError(selection_error)
    if not _validate_budget(snapshot.get("budget")):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_BUDGET,
        )

    try:
        serialized = json.dumps(
            dict(snapshot),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        ) from None
    payload_characters = _utf16_length(serialized)
    if payload_characters > MAX_CONTEXT_CHARACTERS:
        raise ContextRefCreateError(
            ContextRefCreateErrorCode.CONTEXT_TOO_LARGE,
        )
    return _ValidatedSnapshot(
        serialized=serialized,
        expires_at=expires_at,
        context_revision=revision,
        payload_characters=payload_characters,
    )


def _canonical_request_size(
    binding: ContextRefBinding,
    serialized_snapshot: str,
) -> int:
    envelope: dict[str, object] = {
        "ownerToken": binding.owner_token,
        "tabInstance": binding.tab_instance,
        "agentId": binding.agent_id,
        "novelId": binding.novel_id,
        "snapshot": json.loads(serialized_snapshot),
    }
    if binding.document_id is not None:
        envelope["documentId"] = binding.document_id
    if binding.session_id is not None:
        envelope["sessionId"] = binding.session_id
    return len(
        json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8"),
    )


def _valid_context_ref(value: object) -> bool:
    if not isinstance(value, str) or not _CONTEXT_REF_PATTERN.fullmatch(value):
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=")
    except (ValueError, TypeError):
        return False
    return len(decoded) == CONTEXT_REF_RANDOM_BYTES


class AssistantContextRefRegistry:
    """Thread-safe FIFO registry implementing ADR-0003's context-ref lease."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(CONTEXT_REF_RANDOM_BYTES)
        )
        self._lock = RLock()
        self._entries: OrderedDict[str, _ContextRefEntry] = OrderedDict()
        self._owner_rates: dict[str, deque[datetime]] = defaultdict(deque)
        self._created_total = 0
        self._first_lease_total = 0
        self._lease_success_total = 0
        self._invalid_lease_total = 0
        self._evicted_total = 0
        self._expired_total = 0

    def create(
        self,
        *,
        binding: ContextRefBinding,
        snapshot: Mapping[str, object],
        request_body_size: int | None = None,
    ) -> ContextRefCreated:
        """Validate and store one immutable snapshot.

        The HTTP owner should pass the exact raw request byte length through
        ``request_body_size``.  The registry always also measures its compact
        canonical envelope, so a caller cannot claim a size below the data it
        supplies.
        """

        now = self._now()
        if not _valid_binding(binding, lease=False):
            raise ContextRefCreateError(
                ContextRefCreateErrorCode.INVALID_BINDING,
            )
        if request_body_size is not None and (
            isinstance(request_body_size, bool)
            or not isinstance(request_body_size, int)
            or request_body_size < 0
        ):
            raise ContextRefCreateError(
                ContextRefCreateErrorCode.REQUEST_TOO_LARGE,
            )
        if (
            request_body_size is not None
            and request_body_size > CONTEXT_REF_MAX_REQUEST_BYTES
        ):
            raise ContextRefCreateError(
                ContextRefCreateErrorCode.REQUEST_TOO_LARGE,
            )

        validated = _validate_snapshot(snapshot, binding, now)
        canonical_size = _canonical_request_size(
            binding,
            validated.serialized,
        )
        effective_size = max(request_body_size or 0, canonical_size)
        if effective_size > CONTEXT_REF_MAX_REQUEST_BYTES:
            raise ContextRefCreateError(
                ContextRefCreateErrorCode.REQUEST_TOO_LARGE,
            )

        with self._lock:
            self._purge_locked(now)
            self._reserve_owner_rate_locked(binding.owner_token, now)
            self._evict_tab_fifo_locked(
                binding.owner_token,
                binding.tab_instance,
            )
            while len(self._entries) >= CONTEXT_REF_MAX_PROCESS:
                self._entries.popitem(last=False)
                self._evicted_total += 1

            context_ref = self._new_context_ref_locked()
            expires_at = min(
                now + CONTEXT_REF_MAX_TTL,
                validated.expires_at,
            )
            self._entries[context_ref] = _ContextRefEntry(
                binding=binding,
                serialized_snapshot=validated.serialized,
                created_at=now,
                expires_at=expires_at,
                context_revision=validated.context_revision,
                payload_characters=validated.payload_characters,
            )
            self._created_total += 1
            return ContextRefCreated(
                context_ref=context_ref,
                expires_at=expires_at,
                context_revision=validated.context_revision,
                payload_characters=validated.payload_characters,
            )

    def lease(
        self,
        context_ref: str,
        *,
        binding: ContextRefBinding,
    ) -> ContextRefLeaseResult:
        """Consume or idempotently re-lease a ref with non-enumerable failure."""

        now = self._now()
        with self._lock:
            self._purge_locked(now)
            return self._lease_locked(context_ref, binding, now)

    def lease_for_runtime(
        self,
        context_ref: str,
        *,
        agent_id: str,
        session_id: str | None,
    ) -> ContextRefLeaseResult:
        """Lease from a public runtime context that transports only the ref.

        The Middleware owner must reject a mismatched root Agent before this
        call.  Static owner, tab, novel, and document scope is recovered only
        inside the lock from the entry authorised at creation time; it is
        never accepted from request context, model input, or URL parameters.
        """

        now = self._now()
        with self._lock:
            self._purge_locked(now)
            if not _valid_context_ref(context_ref):
                return self._invalid_lease_locked()
            entry = self._entries.get(context_ref)
            if entry is None:
                return self._invalid_lease_locked()
            stored = entry.binding
            runtime_binding = ContextRefBinding(
                owner_token=stored.owner_token,
                tab_instance=stored.tab_instance,
                agent_id=agent_id,
                novel_id=stored.novel_id,
                document_id=stored.document_id,
                session_id=session_id,
            )
            return self._lease_locked(context_ref, runtime_binding, now)

    def _lease_locked(
        self,
        context_ref: str,
        binding: ContextRefBinding,
        now: datetime,
    ) -> ContextRefLeaseResult:
        if not _valid_context_ref(context_ref) or not _valid_binding(
            binding,
            lease=True,
        ):
            return self._invalid_lease_locked()
        entry = self._entries.get(context_ref)
        if entry is None or not self._binding_matches(entry, binding):
            return self._invalid_lease_locked()

        serialized = entry.serialized_snapshot
        if entry.binding.session_id is None:
            value = json.loads(serialized)
            value["sessionId"] = binding.session_id
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        payload_characters = _utf16_length(serialized)
        if payload_characters > MAX_CONTEXT_CHARACTERS:
            del self._entries[context_ref]
            return self._invalid_lease_locked()

        first_lease = entry.lease_expires_at is None
        if first_lease:
            if (
                entry.binding.session_id is not None
                and entry.binding.session_id != binding.session_id
            ):
                return self._invalid_lease_locked()
            entry.lease_session_id = binding.session_id
            entry.lease_agent_id = binding.agent_id
            entry.lease_expires_at = min(
                now + CONTEXT_REF_IDEMPOTENT_LEASE,
                entry.expires_at,
            )
            self._first_lease_total += 1
        elif (
            entry.lease_session_id != binding.session_id
            or entry.lease_agent_id != binding.agent_id
            or entry.lease_expires_at is None
            or entry.lease_expires_at <= now
        ):
            return self._invalid_lease_locked()

        self._lease_success_total += 1
        return ContextRefLeaseResult(
            status=ContextRefLeaseStatus.LEASED,
            payload_characters=payload_characters,
            context_revision=entry.context_revision,
            expires_at=entry.expires_at,
            lease_expires_at=entry.lease_expires_at,
            _serialized_snapshot=serialized,
        )

    def diagnostics(self) -> ContextRefRegistryDiagnostic:
        now = self._now()
        with self._lock:
            self._purge_locked(now)
            leased_entries = sum(
                entry.lease_expires_at is not None
                for entry in self._entries.values()
            )
            return ContextRefRegistryDiagnostic(
                active_entries=len(self._entries),
                leased_entries=leased_entries,
                rate_owner_count=len(self._owner_rates),
                created_total=self._created_total,
                first_lease_total=self._first_lease_total,
                lease_success_total=self._lease_success_total,
                invalid_lease_total=self._invalid_lease_total,
                evicted_total=self._evicted_total,
                expired_total=self._expired_total,
            )

    def clear(self) -> None:
        """Drop all ephemeral page content, for plugin teardown or tests."""

        with self._lock:
            self._entries.clear()
            self._owner_rates.clear()

    def _now(self) -> datetime:
        return _utc_now(self._clock())

    def _new_context_ref_locked(self) -> str:
        for _attempt in range(16):
            candidate = self._token_factory()
            if not _valid_context_ref(candidate):
                raise RuntimeError(
                    "context ref generator did not return 256-bit web-safe data",
                )
            if candidate not in self._entries:
                return candidate
        raise RuntimeError("could not allocate a unique context ref")

    def _reserve_owner_rate_locked(
        self,
        owner_token: str,
        now: datetime,
    ) -> None:
        self._prune_owner_rates_locked(now)
        timestamps = self._owner_rates[owner_token]
        if len(timestamps) >= CONTEXT_REF_OWNER_RATE_LIMIT:
            raise ContextRefCreateError(
                ContextRefCreateErrorCode.RATE_LIMITED,
            )
        timestamps.append(now)

    def _prune_owner_rates_locked(self, now: datetime) -> None:
        cutoff = now - CONTEXT_REF_OWNER_RATE_WINDOW
        for owner_token in tuple(self._owner_rates):
            timestamps = self._owner_rates[owner_token]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                del self._owner_rates[owner_token]

    def _purge_locked(self, now: datetime) -> None:
        expired = [
            context_ref
            for context_ref, entry in self._entries.items()
            if entry.expires_at <= now
            or (
                entry.lease_expires_at is not None
                and entry.lease_expires_at <= now
            )
        ]
        for context_ref in expired:
            del self._entries[context_ref]
            self._expired_total += 1
        self._prune_owner_rates_locked(now)

    def _evict_tab_fifo_locked(
        self,
        owner_token: str,
        tab_instance: str,
    ) -> None:
        matching = [
            context_ref
            for context_ref, entry in self._entries.items()
            if entry.binding.owner_token == owner_token
            and entry.binding.tab_instance == tab_instance
        ]
        overflow = len(matching) - CONTEXT_REF_MAX_PER_TAB + 1
        for context_ref in matching[: max(0, overflow)]:
            del self._entries[context_ref]
            self._evicted_total += 1

    def _binding_matches(
        self,
        entry: _ContextRefEntry,
        binding: ContextRefBinding,
    ) -> bool:
        stored = entry.binding
        return (
            stored.owner_token == binding.owner_token
            and stored.tab_instance == binding.tab_instance
            and stored.agent_id == binding.agent_id
            and stored.novel_id == binding.novel_id
            and stored.document_id == binding.document_id
        )

    def _invalid_lease_locked(self) -> ContextRefLeaseResult:
        self._invalid_lease_total += 1
        return ContextRefLeaseResult(status=ContextRefLeaseStatus.INVALID)


__all__ = [
    "AssistantContextRefRegistry",
    "CONTEXT_REF_IDEMPOTENT_LEASE",
    "CONTEXT_REF_MAX_PER_TAB",
    "CONTEXT_REF_MAX_PROCESS",
    "CONTEXT_REF_MAX_REQUEST_BYTES",
    "CONTEXT_REF_MAX_TTL",
    "CONTEXT_REF_OWNER_RATE_LIMIT",
    "CONTEXT_REF_OWNER_RATE_WINDOW",
    "CONTEXT_REF_RANDOM_BYTES",
    "ContextRefBinding",
    "ContextRefCreateError",
    "ContextRefCreateErrorCode",
    "ContextRefCreated",
    "ContextRefLeaseDiagnostic",
    "ContextRefLeaseResult",
    "ContextRefLeaseStatus",
    "ContextRefRegistryDiagnostic",
]
