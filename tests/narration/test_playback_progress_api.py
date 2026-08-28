from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.narration import playback_api
from backend.narration.progress import PlaybackResumeProjection
from backend.narration.services import NarrationCasConflict, NarrationScopeMismatch
from backend.models import NarrationEditionSegment, NarrationPlaybackProgress
from tests.narration.test_domain_services import MemoryNarrationStore, _edition_with_ready_renders
from tests.narration.test_playback_recovery import _publish_all_ready


EDITION_ID = UUID("a7100000-0000-4000-8000-000000000001")
EDITION_SEGMENT_ID = UUID("a7100000-0000-4000-8000-000000000002")
SEGMENT_ID = UUID("a7100000-0000-4000-8000-000000000003")
OTHER_EDITION_ID = UUID("a7100000-0000-4000-8000-000000000004")
PROFILE_ID = "desktop.default"
ETAG = f'"{"a" * 64}"'
UPDATED_AT = datetime(2026, 8, 27, 9, 30, tzinfo=UTC)


def _projection(**changes: object) -> PlaybackResumeProjection:
    values: dict[str, object] = {
        "profile_id": PROFILE_ID,
        "edition_id": EDITION_ID,
        "manifest_revision": 4,
        "manifest_etag": ETAG,
        "edition_segment_id": EDITION_SEGMENT_ID,
        "segment_id": SEGMENT_ID,
        "ordinal": 2,
        "offset_ms": 450,
        "last_legal_start_ordinal": 1,
        "playback_rate_millis": 1_250,
        "manifest_advanced": False,
        "progress_updated_at": UPDATED_AT,
    }
    values.update(changes)
    return PlaybackResumeProjection(**values)  # type: ignore[arg-type]


def _put_body(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "profile_id": PROFILE_ID,
        "manifest_revision": 4,
        "manifest_etag": ETAG,
        "edition_segment_id": str(EDITION_SEGMENT_ID),
        "segment_id": str(SEGMENT_ID),
        "offset_ms": 450,
        "last_legal_start_ordinal": 1,
        "playback_rate_millis": 1_250,
        "expected_updated_at": UPDATED_AT.isoformat(),
    }
    values.update(changes)
    return values


@dataclass
class Backend:
    restored: PlaybackResumeProjection | None = None
    saved: PlaybackResumeProjection = field(default_factory=_projection)
    failure: Exception | None = None
    restore_calls: list[tuple[UUID, str]] = field(default_factory=list)
    save_calls: list[tuple[UUID, playback_api.SavePlaybackProgressRequest]] = field(
        default_factory=list
    )

    def restore_progress(
        self,
        edition_id: UUID,
        profile_id: str,
    ) -> PlaybackResumeProjection | None:
        self.restore_calls.append((edition_id, profile_id))
        if self.failure is not None:
            raise self.failure
        return self.restored

    def save_progress(
        self,
        edition_id: UUID,
        payload: playback_api.SavePlaybackProgressRequest,
    ) -> PlaybackResumeProjection:
        self.save_calls.append((edition_id, payload))
        if self.failure is not None:
            raise self.failure
        return self.saved


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    def test_session():  # type: ignore[no-untyped-def]
        with Session() as session:
            yield session

    monkeypatch.setattr(playback_api, "get_session", test_session)
    playback_api.uninstall_playback_api_backend_factory()
    yield
    playback_api.uninstall_playback_api_backend_factory()


def _client(backend: Backend | None = None, *, allow_t4: bool = True) -> TestClient:
    if backend is not None:
        playback_api.install_playback_api_backend_factory(lambda _session: backend)
    app = FastAPI()
    if allow_t4:
        app.dependency_overrides[
            playback_api.require_narration_t4_http_access
        ] = lambda: None
    app.include_router(playback_api.router)
    return TestClient(app, raise_server_exceptions=False)


def test_get_progress_returns_exact_edition_envelope_or_explicit_null() -> None:
    backend = Backend()
    client = _client(backend)

    missing = client.get(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": PROFILE_ID},
    )
    assert missing.status_code == 200
    assert missing.headers["cache-control"] == "no-store"
    assert missing.json() == {
        "contract_version": "narration-production-api/1",
        "edition_id": str(EDITION_ID),
        "profile_id": PROFILE_ID,
        "progress": None,
    }

    backend.restored = _projection(manifest_advanced=True, manifest_revision=5)
    restored = client.get(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": PROFILE_ID},
    )
    assert restored.status_code == 200
    assert restored.json()["progress"] == {
        "manifest_revision": 5,
        "manifest_etag": ETAG,
        "edition_segment_id": str(EDITION_SEGMENT_ID),
        "segment_id": str(SEGMENT_ID),
        "ordinal": 2,
        "offset_ms": 450,
        "last_legal_start_ordinal": 1,
        "playback_rate_millis": 1250,
        "manifest_advanced": True,
        "progress_updated_at": "2026-08-27T09:30:00Z",
    }
    assert backend.restore_calls == [
        (EDITION_ID, PROFILE_ID),
        (EDITION_ID, PROFILE_ID),
    ]


def test_put_progress_forwards_all_fences_and_returns_non_null_projection() -> None:
    backend = Backend()
    response = _client(backend).put(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": PROFILE_ID},
        json=_put_body(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["progress"]["segment_id"] == str(SEGMENT_ID)
    assert len(backend.save_calls) == 1
    edition_id, payload = backend.save_calls[0]
    assert edition_id == EDITION_ID
    assert payload.profile_id == PROFILE_ID
    assert payload.manifest_revision == 4
    assert payload.manifest_etag == ETAG
    assert payload.edition_segment_id == EDITION_SEGMENT_ID
    assert payload.segment_id == SEGMENT_ID
    assert payload.expected_updated_at == UPDATED_AT


def test_put_progress_allows_server_resolved_edition_segment_identity() -> None:
    backend = Backend()
    body = _put_body()
    body.pop("edition_segment_id")

    response = _client(backend).put(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": PROFILE_ID},
        json=body,
    )

    assert response.status_code == 200
    assert len(backend.save_calls) == 1
    assert backend.save_calls[0][1].edition_segment_id is None
    assert backend.save_calls[0][1].segment_id == SEGMENT_ID


@pytest.mark.parametrize(
    ("query_profile", "changes"),
    [
        ("other.profile", {}),
        (PROFILE_ID, {"profile_id": "bad profile"}),
        (PROFILE_ID, {"manifest_etag": 'W/"' + "a" * 64 + '"'}),
        (PROFILE_ID, {"segment_id": str(OTHER_EDITION_ID), "extra": True}),
        (PROFILE_ID, {"offset_ms": -1}),
        (PROFILE_ID, {"last_legal_start_ordinal": True}),
        (PROFILE_ID, {"playback_rate_millis": 4_001}),
        (PROFILE_ID, {"expected_updated_at": "2026-08-27T09:30:00"}),
    ],
)
def test_put_progress_rejects_ambiguous_or_unfenced_inputs_before_dispatch(
    query_profile: str,
    changes: dict[str, object],
) -> None:
    backend = Backend()
    response = _client(backend).put(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": query_profile},
        json=_put_body(**changes),
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.save_calls == []


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (NarrationCasConflict("late writer"), 409, "VERSION_CONFLICT"),
        (NarrationScopeMismatch("secret foreign scope"), 404, "SCOPE_VIOLATION"),
    ],
)
def test_progress_faults_preserve_cas_and_hide_cross_scope_details(
    failure: Exception,
    status_code: int,
    code: str,
) -> None:
    backend = Backend(failure=failure)
    response = _client(backend).put(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": PROFILE_ID},
        json=_put_body(),
    )

    assert response.status_code == status_code
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == code
    assert "secret foreign scope" not in response.text
    assert "late writer" not in response.text


def test_progress_routes_remain_hidden_behind_the_existing_t4_http_gate() -> None:
    response = _client(Backend(), allow_t4=False).get(
        f"/narration-editions/{EDITION_ID}/playback-progress",
        params={"profile_id": PROFILE_ID},
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"


class _TransactionSession:
    def __init__(self) -> None:
        self.begin_count = 0
        self.exit_count = 0

    def begin(self) -> "_TransactionSession":
        self.begin_count += 1
        return self

    def __enter__(self) -> "_TransactionSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self.exit_count += 1


def test_sqlalchemy_backend_checks_manifest_and_both_segment_identities_in_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    manifest = _publish_all_ready(store, edition, renders, rows, revision=0)
    current_manifest = _publish_all_ready(store, edition, renders, rows, revision=1)
    session = _TransactionSession()
    monkeypatch.setattr(playback_api, "SqlAlchemyNarrationStore", lambda _session: store)
    backend = playback_api.SqlAlchemyPlaybackApiBackend(  # type: ignore[arg-type]
        session,
        object(),
    )

    payload = playback_api.SavePlaybackProgressRequest(
        profile_id=PROFILE_ID,
        manifest_revision=manifest.manifest_revision,
        manifest_etag=f'"{manifest.etag_sha256}"',
        edition_segment_id=None,
        segment_id=rows[0].segment_id,
        offset_ms=300,
        last_legal_start_ordinal=0,
        playback_rate_millis=1_000,
        expected_updated_at=None,
    )
    saved = backend.save_progress(edition.id, payload)

    assert saved.edition_id == edition.id
    assert saved.edition_segment_id == rows[0].id
    assert saved.segment_id == rows[0].segment_id
    assert saved.manifest_revision == current_manifest.manifest_revision
    assert saved.manifest_etag == f'"{current_manifest.etag_sha256}"'
    assert saved.manifest_advanced is True
    assert session.begin_count == session.exit_count == 1
    assert len(store.rows[NarrationPlaybackProgress]) == 1

    with pytest.raises(NarrationCasConflict, match="ETag"):
        backend.save_progress(
            edition.id,
            payload.model_copy(update={"manifest_etag": f'"{"f" * 64}"'}),
        )
    with pytest.raises(NarrationScopeMismatch, match="another Edition"):
        backend.save_progress(
            edition.id,
            payload.model_copy(
                update={
                    "edition_segment_id": rows[0].id,
                    "segment_id": rows[1].segment_id,
                }
            ),
        )
    assert len(store.rows[NarrationPlaybackProgress]) == 1
    assert session.begin_count == session.exit_count == 3


def test_sqlalchemy_backend_fences_late_progress_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment,
        edition_id=edition.id,
        order_by=("ordinal",),
    )
    manifest = _publish_all_ready(store, edition, renders, rows, revision=0)
    session = _TransactionSession()
    monkeypatch.setattr(playback_api, "SqlAlchemyNarrationStore", lambda _session: store)
    backend = playback_api.SqlAlchemyPlaybackApiBackend(  # type: ignore[arg-type]
        session,
        object(),
    )
    base = playback_api.SavePlaybackProgressRequest(
        profile_id=PROFILE_ID,
        manifest_revision=manifest.manifest_revision,
        manifest_etag=f'"{manifest.etag_sha256}"',
        edition_segment_id=rows[0].id,
        segment_id=rows[0].segment_id,
        offset_ms=100,
        last_legal_start_ordinal=0,
        playback_rate_millis=1_000,
        expected_updated_at=None,
    )
    first = backend.save_progress(edition.id, base)
    latest = backend.save_progress(
        edition.id,
        base.model_copy(
            update={
                "edition_segment_id": rows[1].id,
                "segment_id": rows[1].segment_id,
                "offset_ms": 250,
                "last_legal_start_ordinal": 1,
                "expected_updated_at": first.progress_updated_at,
            }
        ),
    )

    with pytest.raises(NarrationCasConflict, match="changed"):
        backend.save_progress(
            edition.id,
            base.model_copy(update={"expected_updated_at": first.progress_updated_at}),
        )
    restored = backend.restore_progress(edition.id, PROFILE_ID)
    assert restored is not None
    assert restored.edition_segment_id == rows[1].id
    assert restored.offset_ms == 250
    assert restored.progress_updated_at == latest.progress_updated_at
