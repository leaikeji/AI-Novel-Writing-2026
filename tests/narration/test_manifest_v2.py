from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    NarrationEditionState,
    NarrationEditionSegment,
    NarrationRenderAsset,
)
from backend.narration import playback_api
from backend.narration.manifest import (
    INITIAL_BUFFER_POLICY,
    ManifestFailure,
    ManifestRead,
    ManifestSegmentInput,
    PrepareRangeCommand,
    PublishManifest,
    append_manifest_revision,
    load_public_manifest,
    parse_manifest_v2,
    prepare_manifest_range,
    publish_manifest,
    resolve_playback_media_asset,
)
from backend.narration.media import ByteRange, MediaReadDecision
from backend.narration.playback_api import PlaybackMediaRead
from backend.narration.services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
)
from tests.narration.test_domain_services import (
    MemoryNarrationStore,
    _edition_with_ready_renders,
)


FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "narration" / "manifest-v2.json"
)
EDITION_ID = UUID("10000000-0000-4000-8000-000000000001")
SEGMENT_ID = UUID("10000000-0000-4000-8000-000000000010")
ASSET_ID = UUID("20000000-0000-4000-8000-000000000020")
VOICE_PREVIEW_ID = UUID("30000000-0000-4000-8000-000000000030")
GENERIC_VOICE_SLOT_ID = UUID("50000000-0000-4000-8000-000000000050")
MANIFEST_ID = UUID("40000000-0000-4000-8000-000000000001")


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _publish_ready(store: MemoryNarrationStore):
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    edition_segments = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    manifest = publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=tuple(
                ManifestSegmentInput(
                    edition_segment_id=row.id,
                    render_status="ready",
                    render_id=renders[index].id,
                )
                for index, row in enumerate(edition_segments)
            ),
            updated_actor="test-worker",
        ),
    )
    return foundation, edition_segments, manifest


def test_checked_in_manifest_v2_fixture_is_canonical_and_strict() -> None:
    payload = _fixture()
    parsed = parse_manifest_v2(payload)

    assert parsed["schema_version"] == "narration-manifest/2.0"
    assert parsed["ready_prefix_count"] == 3
    assert parsed["ready_ranges"] == [
        {
            "start_ordinal": 0,
            "end_ordinal_exclusive": 3,
            "segment_count": 3,
            "duration_ms": 9500,
            "last_playable_start_ordinal": 0,
        }
    ]
    assert "text_sha256" not in json.dumps(parsed)
    assert "text_hmac" not in json.dumps(parsed)

    for mutation in ("extra", "range", "url", "etag"):
        candidate = deepcopy(payload)
        if mutation == "extra":
            candidate["text_hmac"] = "private-derived-data"
        elif mutation == "range":
            candidate["ready_ranges"][0]["duration_ms"] = 9499  # type: ignore[index]
        elif mutation == "url":
            candidate["segments"][0]["audio"]["url"] += "?token=secret"  # type: ignore[index,operator]
        else:
            candidate["etag"] = f'"{"b" * 64}"'
        with pytest.raises(InvalidNarrationState):
            parse_manifest_v2(candidate)


def test_manifest_read_resolves_current_and_exact_revision() -> None:
    store = MemoryNarrationStore()
    foundation, _edition_segments, manifest = _publish_ready(store)
    edition = foundation[4]

    current = load_public_manifest(store, edition_id=edition.id)
    exact = load_public_manifest(
        store, edition_id=edition.id, manifest_revision=manifest.manifest_revision
    )

    assert current == exact
    assert current.etag == f'"{manifest.etag_sha256}"'
    assert current.payload["edition_id"] == str(edition.id)
    with pytest.raises(NarrationNotFound):
        load_public_manifest(store, edition_id=edition.id, manifest_revision=99)


def test_manifest_read_never_exposes_first_segment_pending_revision() -> None:
    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    rows[0].render_state = "pending"
    manifest = publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=(
                ManifestSegmentInput(rows[0].id, "pending"),
                ManifestSegmentInput(rows[1].id, "ready", renders[1].id),
            ),
            updated_actor="test-worker",
        ),
    )

    assert manifest.canonical_json["status"] == "partial_ready"
    with pytest.raises(InvalidNarrationState, match="first segment"):
        load_public_manifest(store, edition_id=edition.id)


def test_terminal_failure_appends_revision_without_rewriting_old_manifest_or_edition() -> None:
    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    rows[1].render_state = "rendering"
    edition.state = "rendering"
    first = publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=(
                ManifestSegmentInput(rows[0].id, "ready", renders[0].id),
                ManifestSegmentInput(rows[1].id, "rendering"),
            ),
            updated_actor="test-worker",
        ),
    )
    first_payload = deepcopy(first.canonical_json)
    rows[1].render_state = "failed"
    rows[1].failure_code = "LEASE_EXPIRED"
    pointer = store.get(NarrationEditionState, edition.id)
    assert pointer is not None

    second = append_manifest_revision(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=pointer.current_manifest_revision,
            expected_state_version=pointer.version,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=(
                ManifestSegmentInput(rows[0].id, "ready", renders[0].id),
                ManifestSegmentInput(
                    rows[1].id,
                    "failed",
                    failure=ManifestFailure(
                        code="LEASE_EXPIRED",
                        retryable=False,
                        message="该句段生成失败，可稍后重新生成。",
                    ),
                ),
            ),
            updated_actor="narration-worker-expired-attempt",
        ),
    )

    assert first.manifest_revision == 1
    assert second.manifest_revision == 2
    assert first.canonical_json == first_payload
    assert second.canonical_json["status"] == "partial_ready"
    assert second.canonical_json["segments"][1]["failure"]["code"] == "LEASE_EXPIRED"
    assert edition.state == "partial_ready"
    assert pointer.current_manifest_id == second.id
    assert pointer.current_manifest_revision == 2


def test_prepare_range_returns_ready_or_boosts_only_existing_exact_job() -> None:
    ready_store = MemoryNarrationStore()
    ready_foundation, ready_rows, _manifest = _publish_ready(ready_store)
    ready_edition = ready_foundation[4]
    called: list[UUID] = []
    immediate = prepare_manifest_range(
        ready_store,
        PrepareRangeCommand(
            edition_id=ready_edition.id,
            start_segment_id=ready_rows[1].segment_id,
            reason="user_seek",
            expected_manifest_revision=1,
            idempotency_key="prepare:ready:0001",
        ),
        promote_job=lambda job: called.append(job.id) is None,
    )
    assert immediate.state == "ready"
    assert immediate.ready_range is not None
    assert called == []

    store = MemoryNarrationStore()
    foundation = _edition_with_ready_renders(store)
    edition = foundation[4]
    renders = foundation[6]
    rows = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    pending_render = renders[1]
    pending_job = store.get(BackgroundJob, pending_render.source_job_id)
    assert pending_job is not None
    rows[1].render_state = "pending"
    pending_render.state = "pending"
    pending_render.duration_ms = None
    pending_render.ready_at = None
    pending_job.state = "queued"
    publish_manifest(
        store,
        PublishManifest(
            edition_id=edition.id,
            expected_current_revision=0,
            expected_state_version=0,
            buffer_policy=INITIAL_BUFFER_POLICY,
            segments=(
                ManifestSegmentInput(rows[0].id, "ready", renders[0].id),
                ManifestSegmentInput(rows[1].id, "pending"),
            ),
            updated_actor="test-worker",
        ),
    )
    promoted: list[UUID] = []
    preparing = prepare_manifest_range(
        store,
        PrepareRangeCommand(
            edition_id=edition.id,
            start_segment_id=rows[1].segment_id,
            reason="resume",
            expected_manifest_revision=1,
            idempotency_key="prepare:pending:0001",
        ),
        promote_job=lambda job: not promoted.append(job.id),
    )
    assert preparing.state == "preparing"
    assert preparing.promoted_job_ids == (pending_job.id,)
    assert promoted == [pending_job.id]
    with pytest.raises(NarrationCasConflict):
        prepare_manifest_range(
            store,
            PrepareRangeCommand(
                edition_id=edition.id,
                start_segment_id=rows[1].segment_id,
                reason="resume",
                expected_manifest_revision=2,
                idempotency_key="prepare:stale:0001",
            ),
            promote_job=lambda _job: True,
        )


def test_sqlalchemy_prepare_range_serves_ready_but_refuses_pending_boost_when_production_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = Session()
    backend = playback_api.SqlAlchemyPlaybackApiBackend(
        session,
        object(),  # type: ignore[arg-type]
        can_promote_jobs=lambda: False,
    )
    payload = playback_api.PrepareRangeRequest(
        start_segment_id=SEGMENT_ID,
        reason="user_seek",
        expected_manifest_revision=4,
    )
    ready = playback_api.PrepareRangeResult(
        edition_id=EDITION_ID,
        start_segment_id=SEGMENT_ID,
        start_ordinal=0,
        state="ready",
        manifest_revision=4,
        manifest_etag=f'"{"1" * 64}"',
        ready_range={
            "start_ordinal": 0,
            "end_ordinal_exclusive": 1,
            "segment_count": 1,
            "duration_ms": 1_000,
            "last_playable_start_ordinal": 0,
        },
        promoted_job_ids=(),
    )
    monkeypatch.setattr(playback_api, "prepare_manifest_range", lambda *_args, **_kwargs: ready)
    assert backend.prepare_range(EDITION_ID, payload, "prepare:ready:guard") == ready

    job = SimpleNamespace(base_priority=0)

    def pending(_store, _command, *, promote_job):  # type: ignore[no-untyped-def]
        promote_job(job)
        raise AssertionError("production guard should abort pending preparation")

    monkeypatch.setattr(playback_api, "prepare_manifest_range", pending)
    monkeypatch.setattr(
        playback_api,
        "enqueue_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("job priority must not change while production is down")
        ),
    )
    with pytest.raises(playback_api.PlaybackApiFault) as failure:
        backend.prepare_range(EDITION_ID, payload, "prepare:pending:guard")
    assert failure.value.code is playback_api.PlaybackApiErrorCode.BACKEND_NOT_INSTALLED
    session.close()


def test_media_resolution_requires_exact_manifest_playback_reachability() -> None:
    store = MemoryNarrationStore()
    foundation, _rows, manifest = _publish_ready(store)
    edition = foundation[4]
    render = foundation[6][0]
    link = store.find_one(NarrationRenderAsset, render_id=render.id, role="playback")
    assert link is not None

    asset = resolve_playback_media_asset(
        store,
        edition_id=edition.id,
        manifest_revision=manifest.manifest_revision,
        asset_id=link.asset_id,
    )
    assert asset.asset_class == "segment_playback"
    render.request_id = uuid4()
    cached_asset = resolve_playback_media_asset(
        store,
        edition_id=edition.id,
        manifest_revision=manifest.manifest_revision,
        asset_id=link.asset_id,
    )
    assert cached_asset.id == asset.id
    original_novel_id = render.novel_id
    render.novel_id = uuid4()
    with pytest.raises(NarrationScopeMismatch):
        resolve_playback_media_asset(
            store,
            edition_id=edition.id,
            manifest_revision=manifest.manifest_revision,
            asset_id=link.asset_id,
        )
    render.novel_id = original_novel_id
    with pytest.raises(NarrationNotFound):
        resolve_playback_media_asset(
            store,
            edition_id=edition.id,
            manifest_revision=99,
            asset_id=link.asset_id,
        )
    link.role = "master"
    with pytest.raises(NarrationScopeMismatch):
        resolve_playback_media_asset(
            store,
            edition_id=edition.id,
            manifest_revision=manifest.manifest_revision,
            asset_id=link.asset_id,
        )


@dataclass
class FakeBackend:
    manifest_payload: dict[str, object] = field(default_factory=_fixture)
    media_calls: list[dict[str, object]] = field(default_factory=list)
    prepare_calls: list[tuple[UUID, playback_api.PrepareRangeRequest, str]] = field(
        default_factory=list
    )

    def get_manifest(
        self, edition_id: UUID, manifest_revision: int | None
    ) -> ManifestRead:
        assert edition_id == EDITION_ID
        assert manifest_revision in {None, 4}
        return ManifestRead(
            manifest_id=MANIFEST_ID,
            edition_id=EDITION_ID,
            manifest_revision=4,
            etag=str(self.manifest_payload["etag"]),
            payload=self.manifest_payload,
        )

    def prepare_range(
        self,
        edition_id: UUID,
        payload: playback_api.PrepareRangeRequest,
        idempotency_key: str,
    ):
        self.prepare_calls.append((edition_id, payload, idempotency_key))
        return playback_api.PrepareRangeResult(
            edition_id=edition_id,
            start_segment_id=payload.start_segment_id,
            start_ordinal=0,
            state="preparing",
            manifest_revision=4,
            manifest_etag=str(self.manifest_payload["etag"]),
            ready_range=None,
            promoted_job_ids=(uuid4(),),
        )

    def read_media(self, **kwargs: object) -> PlaybackMediaRead:
        self.media_calls.append(kwargs)
        method = str(kwargs["method"])
        range_header = kwargs.get("range_header")
        if range_header == "bytes=999-":
            decision = MediaReadDecision(
                status=416,
                headers={
                    "Content-Range": "bytes */3",
                    "Content-Length": "0",
                    "ETag": f'"{"1" * 64}"',
                },
                byte_range=None,
                send_body=False,
                relative_path="unused",
                device=1,
                inode=2,
                byte_size=3,
            )
            return PlaybackMediaRead(decision, ())
        decision = MediaReadDecision(
            status=206 if range_header else 200,
            headers={
                "Content-Type": "audio/ogg",
                "Content-Length": "3",
                "Accept-Ranges": "bytes",
                "ETag": f'"{"1" * 64}"',
                **(
                    {"Content-Range": "bytes 0-2/3"}
                    if range_header
                    else {}
                ),
            },
            byte_range=ByteRange(0, 2) if range_header else None,
            send_body=method == "GET",
            relative_path="unused",
            device=1,
            inode=2,
            byte_size=3,
        )
        return PlaybackMediaRead(decision, (b"abc",) if method == "GET" else ())


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    def test_session():  # type: ignore[no-untyped-def]
        with Session() as session:
            yield session

    monkeypatch.setattr(playback_api, "get_session", test_session)
    playback_api.uninstall_playback_api_backend_factory()
    yield
    playback_api.uninstall_playback_api_backend_factory()


def _client(backend: FakeBackend | None = None) -> TestClient:
    if backend is not None:
        playback_api.install_playback_api_backend_factory(lambda _session: backend)
    app = FastAPI()
    app.dependency_overrides[
        playback_api.require_narration_t4_http_access
    ] = lambda: None
    app.include_router(playback_api.router)
    return TestClient(app, raise_server_exceptions=False)


def test_http_manifest_etag_prepare_and_fail_closed_backend() -> None:
    unavailable = _client().get(f"/narration-editions/{EDITION_ID}/manifest")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "NARRATION_PRODUCTION_BACKEND_NOT_INSTALLED"

    backend = FakeBackend()
    client = _client(backend)
    response = client.get(
        f"/narration-editions/{EDITION_ID}/manifest?manifest_revision=4"
    )
    assert response.status_code == 200
    assert response.headers["etag"] == backend.manifest_payload["etag"]
    assert response.json()["schema_version"] == "narration-manifest/2.0"
    cached = client.get(
        f"/narration-editions/{EDITION_ID}/manifest",
        headers={"If-None-Match": str(backend.manifest_payload["etag"])},
    )
    assert cached.status_code == 304 and cached.content == b""

    prepared = client.post(
        f"/narration-editions/{EDITION_ID}/prepare-range",
        headers={"Idempotency-Key": "prepare:http:0001"},
        json={
            "start_segment_id": str(SEGMENT_ID),
            "reason": "user_seek",
            "expected_manifest_revision": 4,
        },
    )
    assert prepared.status_code == 200
    assert prepared.json()["state"] == "preparing"
    assert backend.prepare_calls[0][2] == "prepare:http:0001"


def test_http_media_requires_scope_headers_and_forwards_range_conditions() -> None:
    backend = FakeBackend()
    client = _client(backend)
    path = f"/media-assets/{ASSET_ID}/content"
    rejected = client.get(path)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    rejected_query = client.get(
        f"{path}?token=secret",
        headers={
            "X-Narration-Edition-Id": str(EDITION_ID),
            "X-Narration-Manifest-Revision": "4",
        },
    )
    assert rejected_query.status_code == 422
    assert rejected_query.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert backend.media_calls == []

    headers = {
        "X-Narration-Edition-Id": str(EDITION_ID),
        "X-Narration-Manifest-Revision": "4",
        "Range": "bytes=0-2",
        "If-Range": f'"{"1" * 64}"',
        "If-None-Match": f'"{"2" * 64}"',
    }
    ranged = client.get(path, headers=headers)
    assert ranged.status_code == 206 and ranged.content == b"abc"
    assert ranged.headers["content-range"] == "bytes 0-2/3"
    assert backend.media_calls[-1] == {
        "asset_id": ASSET_ID,
        "edition_id": EDITION_ID,
        "manifest_revision": 4,
        "voice_preview_id": None,
        "generic_voice_slot_id": None,
        "method": "GET",
        "range_header": "bytes=0-2",
        "if_range": f'"{"1" * 64}"',
        "if_none_match": f'"{"2" * 64}"',
    }

    preview = client.get(
        path,
        headers={"X-Narration-Voice-Preview-Id": str(VOICE_PREVIEW_ID)},
    )
    assert preview.status_code == 200 and preview.content == b"abc"
    assert backend.media_calls[-1]["voice_preview_id"] == VOICE_PREVIEW_ID
    assert backend.media_calls[-1]["edition_id"] is None
    assert backend.media_calls[-1]["manifest_revision"] is None
    assert backend.media_calls[-1]["generic_voice_slot_id"] is None

    generic = client.get(
        path,
        headers={"X-Narration-Generic-Voice-Slot-Id": str(GENERIC_VOICE_SLOT_ID)},
    )
    assert generic.status_code == 200 and generic.content == b"abc"
    assert backend.media_calls[-1]["generic_voice_slot_id"] == GENERIC_VOICE_SLOT_ID
    assert backend.media_calls[-1]["voice_preview_id"] is None
    assert backend.media_calls[-1]["edition_id"] is None

    conflicting = client.get(
        path,
        headers={
            "X-Narration-Voice-Preview-Id": str(VOICE_PREVIEW_ID),
            "X-Narration-Edition-Id": str(EDITION_ID),
            "X-Narration-Manifest-Revision": "4",
            "X-Narration-Generic-Voice-Slot-Id": str(GENERIC_VOICE_SLOT_ID),
        },
    )
    assert conflicting.status_code == 422
    assert conflicting.json()["detail"]["code"] == "REQUEST_VALIDATION_FAILED"

    head = client.head(path, headers={**headers, "Range": "bytes=999-"})
    assert head.status_code == 416 and head.content == b""
    assert head.headers["content-range"] == "bytes */3"
    assert backend.media_calls[-1]["method"] == "HEAD"
