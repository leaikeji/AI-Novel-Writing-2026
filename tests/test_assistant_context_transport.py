from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from threading import Barrier, Lock

import pytest

from backend.assistant_context import (
    MAX_CONTEXT_CHARACTERS,
    TARGET_AGENT_ID,
)
from backend.assistant_context_registry import (
    AssistantContextRefRegistry,
    CONTEXT_REF_MAX_PER_TAB,
    CONTEXT_REF_MAX_PROCESS,
    CONTEXT_REF_MAX_REQUEST_BYTES,
    CONTEXT_REF_OWNER_RATE_LIMIT,
    ContextRefBinding,
    ContextRefCreateError,
    ContextRefCreateErrorCode,
    ContextRefLeaseResult,
    ContextRefLeaseStatus,
)


NOW = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
OWNER_TOKEN = "owner_token_0000000000000001"
TAB_INSTANCE = "tab_instance_000000000000001"


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self.current

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self.current += delta


def binding(
    *,
    owner_token: str = OWNER_TOKEN,
    tab_instance: str = TAB_INSTANCE,
    agent_id: str = TARGET_AGENT_ID,
    novel_id: str = "novel-1",
    document_id: str | None = "document-1",
    session_id: str | None = "session-1",
) -> ContextRefBinding:
    return ContextRefBinding(
        owner_token=owner_token,
        tab_instance=tab_instance,
        agent_id=agent_id,
        novel_id=novel_id,
        document_id=document_id,
        session_id=session_id,
    )


def valid_snapshot(
    scope: ContextRefBinding | None = None,
    *,
    now: datetime = NOW,
    expires_in: timedelta = timedelta(minutes=10),
    marker: str = "AUTHOR-CONTENT-MARKER",
) -> dict[str, object]:
    current_scope = scope or binding()
    snapshot: dict[str, object] = {
        "schemaVersion": 2,
        "contextRevision": 7,
        "capturedAt": now.isoformat(),
        "expiresAt": (now + expires_in).isoformat(),
        "agentId": current_scope.agent_id,
        "novel": {"id": current_scope.novel_id, "title": "潮声替我说晚安"},
        "page": {"section": "chapters", "view": "chapter-editor"},
        "editing": {
            "focusedFieldId": "chapter.body",
            "fields": [
                {
                    "id": "chapter.body",
                    "label": "正文",
                    "value": f"未保存草稿 {marker}",
                    "dirty": True,
                    "truncated": False,
                    "characterCount": 24,
                    "persistence": "autosave",
                },
            ],
        },
        "budget": {
            "maxCharacters": MAX_CONTEXT_CHARACTERS,
            "usedCharacters": 512,
            "truncated": False,
            "omittedFieldIds": [],
        },
    }
    if current_scope.session_id is not None:
        snapshot["sessionId"] = current_scope.session_id
    if current_scope.document_id is not None:
        snapshot["document"] = {
            "id": current_scope.document_id,
            "kind": "chapter",
            "title": "第一章 海风",
            "draftVersion": 3,
            "savedContentHash": "a" * 64,
            "dirty": True,
        }
    return snapshot


def selection(now: datetime = NOW, *, text: str = "需要润色的句子") -> dict[str, object]:
    return {
        "id": "selection-1",
        "fieldId": "chapter.body",
        "text": text,
        "startUtf16": 0,
        "endUtf16": max(1, len(text)),
        "direction": "forward",
        "before": "",
        "after": "",
        "sourceValueSha256": "b" * 64,
        "contextRevision": 7,
        "createdAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=5)).isoformat(),
    }


def assert_create_error(
    expected: ContextRefCreateErrorCode,
    operation: object,
) -> None:
    assert callable(operation)
    with pytest.raises(ContextRefCreateError) as captured:
        operation()
    assert captured.value.code is expected
    assert str(captured.value) == expected.value


def test_create_uses_256_bit_web_safe_ref_and_returns_defensive_snapshots() -> None:
    clock = MutableClock()
    registry = AssistantContextRefRegistry(clock=clock)
    create_scope = binding(session_id=None)
    payload = valid_snapshot(create_scope)
    created = registry.create(binding=create_scope, snapshot=payload)

    decoded = base64.urlsafe_b64decode(created.context_ref + "=")
    assert len(decoded) == 32
    assert len(created.context_ref) == 43
    assert created.expires_at == NOW + timedelta(minutes=5)
    assert created.context_ref not in repr(created)

    payload["page"] = {"section": "settings", "view": "novel-settings"}
    lease_scope = replace(create_scope, session_id="session-1")
    leased = registry.lease(created.context_ref, binding=lease_scope)

    assert leased.accepted
    assert leased.status is ContextRefLeaseStatus.LEASED
    assert leased.snapshot is not None
    assert leased.snapshot["page"] == {
        "section": "chapters",
        "view": "chapter-editor",
    }
    assert leased.snapshot["sessionId"] == "session-1"
    first_copy = leased.snapshot
    assert first_copy is not None
    first_copy["page"] = {"section": "settings", "view": "novel-settings"}
    assert registry.lease(
        created.context_ref,
        binding=lease_scope,
    ).snapshot["page"] == {
        "section": "chapters",
        "view": "chapter-editor",
    }


def test_first_lease_is_idempotent_for_30_seconds_then_deleted() -> None:
    clock = MutableClock()
    registry = AssistantContextRefRegistry(clock=clock)
    create_scope = binding(session_id=None)
    created = registry.create(
        binding=create_scope,
        snapshot=valid_snapshot(create_scope),
    )
    first = registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id="session-1",
    )
    clock.advance(timedelta(seconds=29))
    retry = registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id="session-1",
    )
    wrong_session = registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id="session-2",
    )
    clock.advance(timedelta(seconds=1))
    expired_retry = registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id="session-1",
    )

    assert first.accepted
    assert retry.accepted
    assert wrong_session == ContextRefLeaseResult(
        status=ContextRefLeaseStatus.INVALID,
    )
    assert expired_retry == wrong_session
    assert registry.diagnostics().active_entries == 0


def test_runtime_lease_uses_only_ref_and_current_agent_session() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding(session_id="session-1")
    created = registry.create(binding=scope, snapshot=valid_snapshot(scope))
    invalid = ContextRefLeaseResult(status=ContextRefLeaseStatus.INVALID)

    assert registry.lease_for_runtime(
        created.context_ref,
        agent_id="default",
        session_id="session-1",
    ) == invalid
    assert registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id="session-2",
    ) == invalid
    assert registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id=None,
    ) == invalid
    assert registry.lease_for_runtime(
        "A" * 43,
        agent_id=TARGET_AGENT_ID,
        session_id="session-1",
    ) == invalid

    leased = registry.lease_for_runtime(
        created.context_ref,
        agent_id=TARGET_AGENT_ID,
        session_id="session-1",
    )
    assert leased.accepted
    assert leased.snapshot is not None
    assert leased.snapshot["novel"]["id"] == scope.novel_id
    assert not hasattr(leased, "binding")
    assert not hasattr(leased, "context_ref")


def test_ref_ttl_is_capped_by_the_earlier_snapshot_expiration() -> None:
    clock = MutableClock()
    registry = AssistantContextRefRegistry(clock=clock)
    scope = binding()
    created = registry.create(
        binding=scope,
        snapshot=valid_snapshot(scope, expires_in=timedelta(minutes=2)),
    )

    assert created.expires_at == NOW + timedelta(minutes=2)
    clock.advance(timedelta(minutes=2))
    assert not registry.lease(created.context_ref, binding=scope).accepted


def test_fresh_process_registry_cannot_lease_an_old_ref() -> None:
    clock = MutableClock()
    original = AssistantContextRefRegistry(clock=clock)
    restarted = AssistantContextRefRegistry(clock=clock)
    scope = binding()
    created = original.create(
        binding=scope,
        snapshot=valid_snapshot(scope),
    )

    assert not restarted.lease(created.context_ref, binding=scope).accepted
    assert original.lease(created.context_ref, binding=scope).accepted


@pytest.mark.parametrize(
    "invalid_scope",
    [
        binding(owner_token="short"),
        binding(tab_instance="contains spaces and is invalid"),
        binding(agent_id="default"),
        binding(novel_id=""),
        binding(document_id=" document-1 "),
        binding(session_id=" session-1 "),
    ],
)
def test_create_rejects_invalid_route_binding_format(
    invalid_scope: ContextRefBinding,
) -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())

    assert_create_error(
        ContextRefCreateErrorCode.INVALID_BINDING,
        lambda: registry.create(
            binding=invalid_scope,
            snapshot=valid_snapshot(invalid_scope),
        ),
    )


@pytest.mark.parametrize(
    ("field_name", "wrong_value"),
    [
        ("owner_token", "other_owner_0000000000000001"),
        ("tab_instance", "other_tab_000000000000000001"),
        ("agent_id", "default"),
        ("novel_id", "novel-2"),
        ("document_id", "document-2"),
        ("session_id", "session-2"),
    ],
)
def test_every_binding_dimension_fails_with_the_same_invalid_result(
    field_name: str,
    wrong_value: str,
) -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    created = registry.create(binding=scope, snapshot=valid_snapshot(scope))
    wrong_scope = replace(scope, **{field_name: wrong_value})

    mismatched = registry.lease(created.context_ref, binding=wrong_scope)
    missing = registry.lease("A" * 43, binding=scope)

    assert mismatched == missing == ContextRefLeaseResult(
        status=ContextRefLeaseStatus.INVALID,
    )
    assert repr(mismatched) == repr(missing)
    assert registry.lease(created.context_ref, binding=scope).accepted


def test_per_tab_capacity_evicts_the_oldest_ref_fifo() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    created = [
        registry.create(binding=scope, snapshot=valid_snapshot(scope))
        for _ in range(CONTEXT_REF_MAX_PER_TAB + 1)
    ]

    assert not registry.lease(created[0].context_ref, binding=scope).accepted
    assert all(
        registry.lease(item.context_ref, binding=scope).accepted
        for item in created[1:]
    )
    diagnostic = registry.diagnostics()
    assert diagnostic.active_entries == CONTEXT_REF_MAX_PER_TAB
    assert diagnostic.evicted_total == 1


def test_process_capacity_evicts_the_oldest_ref_fifo() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    created: list[tuple[object, ContextRefBinding]] = []
    for index in range(CONTEXT_REF_MAX_PROCESS + 1):
        scope = binding(
            owner_token=f"owner_{index:04d}_0000000000000000",
            tab_instance=f"tab_{index:04d}_000000000000000000",
            document_id=None,
        )
        created.append(
            (
                registry.create(
                    binding=scope,
                    snapshot=valid_snapshot(scope),
                ),
                scope,
            ),
        )

    first, first_scope = created[0]
    last, last_scope = created[-1]
    assert not registry.lease(first.context_ref, binding=first_scope).accepted
    assert registry.lease(last.context_ref, binding=last_scope).accepted
    diagnostic = registry.diagnostics()
    assert diagnostic.active_entries == CONTEXT_REF_MAX_PROCESS
    assert diagnostic.evicted_total == 1


def test_owner_rate_limit_is_rolling_and_recovers_after_one_minute() -> None:
    clock = MutableClock()
    registry = AssistantContextRefRegistry(clock=clock)
    scope = binding()
    for _ in range(CONTEXT_REF_OWNER_RATE_LIMIT):
        registry.create(binding=scope, snapshot=valid_snapshot(scope))

    assert_create_error(
        ContextRefCreateErrorCode.RATE_LIMITED,
        lambda: registry.create(binding=scope, snapshot=valid_snapshot(scope)),
    )
    clock.advance(timedelta(minutes=1))
    assert registry.create(
        binding=scope,
        snapshot=valid_snapshot(scope, now=clock.current),
    ).context_ref


def test_request_body_enforces_96_kib_even_for_a_small_snapshot() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    assert registry.create(
        binding=scope,
        snapshot=valid_snapshot(scope),
        request_body_size=CONTEXT_REF_MAX_REQUEST_BYTES,
    ).context_ref

    assert_create_error(
        ContextRefCreateErrorCode.REQUEST_TOO_LARGE,
        lambda: registry.create(
            binding=scope,
            snapshot=valid_snapshot(scope),
            request_body_size=CONTEXT_REF_MAX_REQUEST_BYTES + 1,
        ),
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda value: value.update(schemaVersion=3),
            ContextRefCreateErrorCode.UNSUPPORTED_SCHEMA,
        ),
        (
            lambda value: value["budget"].update(maxCharacters=23_999),
            ContextRefCreateErrorCode.INVALID_BUDGET,
        ),
        (
            lambda value: value["budget"].update(usedCharacters=24_001),
            ContextRefCreateErrorCode.INVALID_BUDGET,
        ),
        (
            lambda value: value.update(unapprovedExtra="author text"),
            ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        ),
    ],
)
def test_schema_and_budget_are_not_coerced(
    mutation: object,
    expected: ContextRefCreateErrorCode,
) -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    payload = valid_snapshot(scope)
    assert callable(mutation)
    mutation(payload)

    assert_create_error(
        expected,
        lambda: registry.create(binding=scope, snapshot=payload),
    )


def test_context_and_selection_character_budgets_use_utf16_units() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    oversized_context = valid_snapshot(scope)
    oversized_context["editing"]["fields"][0]["value"] = "文" * 24_000
    oversized_selection = valid_snapshot(scope)
    oversized_selection["selection"] = selection(text="😀" * 6_001)

    assert_create_error(
        ContextRefCreateErrorCode.CONTEXT_TOO_LARGE,
        lambda: registry.create(
            binding=scope,
            snapshot=oversized_context,
        ),
    )
    assert_create_error(
        ContextRefCreateErrorCode.SELECTION_TOO_LARGE,
        lambda: registry.create(
            binding=scope,
            snapshot=oversized_selection,
        ),
    )


def test_selection_at_exact_utf16_limit_is_accepted() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    payload = valid_snapshot(scope)
    boundary = selection(text="😀" * 6_000)
    boundary["endUtf16"] = 12_000
    payload["selection"] = boundary

    created = registry.create(binding=scope, snapshot=payload)

    assert registry.lease(created.context_ref, binding=scope).accepted


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["selection"].update(endUtf16=0),
        lambda value: value["selection"].update(direction="sideways"),
        lambda value: value["selection"].update(before="前" * 1_501),
        lambda value: value["selection"].update(sourceValueSha256="bad"),
        lambda value: value["selection"].update(contextRevision=8),
        lambda value: value["selection"].update(
            expiresAt=(NOW + timedelta(minutes=11)).isoformat(),
        ),
    ],
)
def test_selection_shape_anchor_and_lifetime_are_validated(
    mutation: object,
) -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    payload = valid_snapshot(scope)
    payload["selection"] = selection()
    assert callable(mutation)
    mutation(payload)

    assert_create_error(
        ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        lambda: registry.create(binding=scope, snapshot=payload),
    )


@pytest.mark.parametrize(
    "field_name",
    ["sessionId", "entity", "document", "editing", "selection"],
)
def test_optional_schema_fields_reject_explicit_null(field_name: str) -> None:
    scope = binding(
        session_id=None if field_name == "sessionId" else "session-1",
        document_id=None if field_name == "document" else "document-1",
    )
    payload = valid_snapshot(scope)
    payload[field_name] = None
    registry = AssistantContextRefRegistry(clock=MutableClock())

    assert_create_error(
        ContextRefCreateErrorCode.INVALID_SNAPSHOT,
        lambda: registry.create(binding=scope, snapshot=payload),
    )


def test_session_binding_cannot_expand_snapshot_past_context_budget() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    create_scope = binding(session_id=None)
    payload = valid_snapshot(create_scope)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    padding = MAX_CONTEXT_CHARACTERS - len(
        serialized.encode("utf-16-le"),
    ) // 2
    payload["editing"]["fields"][0]["value"] += "文" * padding

    created = registry.create(binding=create_scope, snapshot=payload)
    leased = registry.lease(
        created.context_ref,
        binding=replace(create_scope, session_id="session-1"),
    )

    assert created.payload_characters == MAX_CONTEXT_CHARACTERS
    assert leased == ContextRefLeaseResult(
        status=ContextRefLeaseStatus.INVALID,
    )
    assert registry.diagnostics().active_entries == 0


@pytest.mark.parametrize("time_case", ["expired", "future", "overlong"])
def test_invalid_snapshot_time_windows_are_rejected(time_case: str) -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    payload = valid_snapshot(scope)
    if time_case == "expired":
        payload["capturedAt"] = (NOW - timedelta(minutes=2)).isoformat()
        payload["expiresAt"] = (NOW - timedelta(minutes=1)).isoformat()
    elif time_case == "future":
        payload["capturedAt"] = (NOW + timedelta(minutes=2)).isoformat()
        payload["expiresAt"] = (NOW + timedelta(minutes=3)).isoformat()
    else:
        payload["expiresAt"] = (NOW + timedelta(minutes=21)).isoformat()

    assert_create_error(
        ContextRefCreateErrorCode.INVALID_TIME_WINDOW,
        lambda: registry.create(binding=scope, snapshot=payload),
    )


@pytest.mark.parametrize("mismatch", ["agent", "novel", "document", "session"])
def test_snapshot_scope_must_equal_the_creation_binding(mismatch: str) -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    payload = valid_snapshot(scope)
    if mismatch == "agent":
        payload["agentId"] = "default"
    elif mismatch == "novel":
        payload["novel"]["id"] = "novel-2"
    elif mismatch == "document":
        payload["document"]["id"] = "document-2"
    else:
        payload["sessionId"] = "session-2"

    assert_create_error(
        ContextRefCreateErrorCode.INVALID_BINDING,
        lambda: registry.create(binding=scope, snapshot=payload),
    )


def test_diagnostics_and_repr_do_not_leak_author_content_or_ref() -> None:
    marker = "SECRET-NOVEL-PAGE-CONTENT"
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    created = registry.create(
        binding=scope,
        snapshot=valid_snapshot(scope, marker=marker),
    )
    leased = registry.lease(created.context_ref, binding=scope)
    diagnostic = leased.diagnostic()
    aggregate = registry.diagnostics()

    assert marker not in repr(created)
    assert marker not in repr(leased)
    assert marker not in repr(diagnostic)
    assert marker not in repr(aggregate)
    assert created.context_ref not in repr(leased)
    assert created.context_ref not in repr(diagnostic)
    assert created.context_ref not in repr(aggregate)
    assert "snapshot" not in asdict(diagnostic)
    assert set(asdict(aggregate)) == {
        "active_entries",
        "leased_entries",
        "rate_owner_count",
        "created_total",
        "first_lease_total",
        "lease_success_total",
        "invalid_lease_total",
        "evicted_total",
        "expired_total",
    }


def test_concurrent_first_lease_atomically_binds_exactly_one_session() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    create_scope = binding(session_id=None)
    created = registry.create(
        binding=create_scope,
        snapshot=valid_snapshot(create_scope),
    )
    workers = 32
    barrier = Barrier(workers)

    def lease_for(session_id: str) -> tuple[str, bool]:
        barrier.wait()
        result = registry.lease_for_runtime(
            created.context_ref,
            agent_id=TARGET_AGENT_ID,
            session_id=session_id,
        )
        return session_id, result.accepted

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(
                lease_for,
                ["session-a", "session-b"] * (workers // 2),
            ),
        )

    accepted_sessions = {
        session_id for session_id, accepted in results if accepted
    }
    assert len(accepted_sessions) == 1
    assert any(accepted for _, accepted in results)
    diagnostic = registry.diagnostics()
    assert diagnostic.first_lease_total == 1
    assert diagnostic.lease_success_total == sum(
        accepted for _, accepted in results
    )


def test_concurrent_creation_keeps_unique_refs_and_global_fifo_capacity() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    workers = 80

    def create_for(index: int) -> str:
        scope = binding(
            owner_token=f"parallel_owner_{index:04d}_00000000",
            tab_instance=f"parallel_tab_{index:04d}_0000000000",
            document_id=None,
        )
        return registry.create(
            binding=scope,
            snapshot=valid_snapshot(scope),
        ).context_ref

    with ThreadPoolExecutor(max_workers=16) as pool:
        refs = list(pool.map(create_for, range(workers)))

    assert len(set(refs)) == workers
    diagnostic = registry.diagnostics()
    assert diagnostic.active_entries == CONTEXT_REF_MAX_PROCESS
    assert diagnostic.created_total == workers
    assert diagnostic.evicted_total == workers - CONTEXT_REF_MAX_PROCESS


def test_clear_drops_all_ephemeral_content_and_rate_state() -> None:
    registry = AssistantContextRefRegistry(clock=MutableClock())
    scope = binding()
    created = registry.create(binding=scope, snapshot=valid_snapshot(scope))

    registry.clear()

    assert not registry.lease(created.context_ref, binding=scope).accepted
    diagnostic = registry.diagnostics()
    assert diagnostic.active_entries == 0
    assert diagnostic.rate_owner_count == 0
