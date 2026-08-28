from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.models import MediaAsset
from backend.narration.media import (
    GcPolicy,
    MediaConflict,
    MediaNotEligible,
    MediaPolicyError,
    ReferenceRoots,
    apply_ready_evidence,
    begin_gc_deletion,
    evaluate_gc,
    execute_gc_delete,
    finalize_gc_deletion,
    load_reference_roots_in_session,
    mark_gc_candidate,
    parse_single_range,
    plan_media_read,
    select_quota_candidates,
    stream_read_decision,
    strong_etag,
)
from backend.narration.storage import (
    ModelRootReadOnly,
    NarrationStorage,
    PublicationDurabilityError,
    PublicationValidationError,
    StorageError,
    StorageRootChanged,
    TargetCollision,
    UnsafeStoragePath,
    validate_relative_path,
)


OWNER = UUID("29cf94d9-a5c9-54ec-912c-5dfff8738c4c")
WORKSPACE = UUID("f0e2e632-bc99-52d2-9916-bb906aa4da6e")
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def storage(tmp_path: Path) -> NarrationStorage:
    models = tmp_path / "moss-models"
    media = tmp_path / "novel-media"
    models.mkdir()
    media.mkdir()
    return NarrationStorage(models_root=models, media_root=media)


def _publish(
    storage: NarrationStorage,
    payload: bytes,
    *,
    extension: str = "wav",
    asset_id: UUID | None = None,
):
    digest = hashlib.sha256(payload).hexdigest()
    resolved_asset_id = asset_id or uuid4()
    return storage.publish_media(
        [payload[:3], payload[3:]],
        asset_id=resolved_asset_id,
        expected_sha256=digest,
        expected_size=len(payload),
        extension=extension,
        max_bytes=1024,
    )


def _asset(
    *,
    asset_id=None,
    state: str = "ready",
    asset_class: str = "segment_playback",
    retention: str = "derivable",
    created_at: datetime = NOW - timedelta(days=30),
) -> MediaAsset:
    resolved_asset_id = asset_id or uuid4()
    return MediaAsset(
        id=resolved_asset_id,
        owner_id=OWNER,
        workspace_id=WORKSPACE,
        novel_id=uuid4(),
        source_revision_id=None,
        kind="narration_audio",
        asset_class=asset_class,
        mime_type="audio/wav",
        byte_size=7,
        duration_ms=10,
        sample_rate=24000,
        channels=1,
        storage_backend="local",
        state=state,
        retention_policy=retention,
        checksum_algorithm="sha256",
        validation_json={},
        verified_at=NOW if state == "ready" else None,
        gc_generation=0,
        storage_path=(
            f"assets/{resolved_asset_id.hex[:2]}/{resolved_asset_id.hex}/"
            + "0" * 64
            + ".wav"
        ),
        content_hash="0" * 64,
        metadata_json={},
        created_at=created_at,
    )


def test_atomic_publish_short_writes_etag_and_bounded_stream(storage: NarrationStorage) -> None:
    payload = b"0123456789abcdef"
    digest = hashlib.sha256(payload).hexdigest()

    def short_write(fd: int, chunk: bytes) -> int:
        return os.write(fd, chunk[:2])

    published = storage.publish_media(
        [payload[:5], payload[5:]],
        asset_id=uuid4(),
        expected_sha256=digest,
        expected_size=len(payload),
        extension="wav",
        max_bytes=len(payload),
        write_fn=short_write,
    )
    assert published.actual_sha256 == digest
    assert published.strong_etag == strong_etag(digest)
    chunks = list(storage.stream_media(published.relative_path, chunk_size=3))
    assert b"".join(chunks) == payload
    assert max(map(len, chunks)) <= 3
    assert not list((storage.media.path / ".staging").glob("*.part"))


@pytest.mark.parametrize("failure", ["crash", "hash", "oversize"])
def test_failed_publication_never_exposes_target_or_part(
    storage: NarrationStorage, failure: str
) -> None:
    payload = b"abcdef"
    digest = hashlib.sha256(payload).hexdigest()

    def chunks():
        yield payload[:2]
        if failure == "crash":
            raise RuntimeError("simulated producer crash")
        yield payload[2:]

    with pytest.raises((RuntimeError, PublicationValidationError)):
        storage.publish_media(
            chunks(),
            asset_id=uuid4(),
            expected_sha256=("f" * 64 if failure == "hash" else digest),
            expected_size=(len(payload) - 1 if failure == "oversize" else len(payload)),
            extension="wav",
            max_bytes=len(payload),
        )
    assert not list(storage.media.path.rglob("*.wav"))
    assert not list(storage.media.path.rglob("*.part"))


def test_existing_target_collision_is_fail_closed(storage: NarrationStorage) -> None:
    payload = b"same immutable bytes"
    asset_id = uuid4()
    published = _publish(storage, payload, asset_id=asset_id)
    with pytest.raises(TargetCollision):
        _publish(storage, payload, asset_id=asset_id)
    recovered = storage.verify_existing_media(
        published.relative_path,
        expected_sha256=published.actual_sha256,
        expected_size=published.byte_size,
        max_bytes=1024,
        chunk_size=2,
    )
    assert recovered == published
    with pytest.raises(PublicationValidationError):
        storage.verify_existing_media(
            published.relative_path,
            expected_sha256="f" * 64,
            expected_size=published.byte_size,
            max_bytes=1024,
        )
    assert not list(storage.media.path.rglob("*.part"))


def test_identical_bytes_have_asset_scoped_paths_and_independent_gc(
    storage: NarrationStorage,
) -> None:
    payload = b"identical bytes owned by two logical assets"
    first = _publish(storage, payload, asset_id=uuid4())
    second = _publish(storage, payload, asset_id=uuid4())

    assert first.asset_id != second.asset_id
    assert first.actual_sha256 == second.actual_sha256
    assert first.relative_path != second.relative_path
    assert first.inode != second.inode
    assert b"".join(storage.stream_media(first.relative_path)) == payload
    assert b"".join(storage.stream_media(second.relative_path)) == payload

    assert storage.delete_media_verified(
        first.relative_path,
        expected_sha256=first.actual_sha256,
        expected_size=first.byte_size,
        expected_device=first.device,
        expected_inode=first.inode,
        expected_present=True,
    )
    assert not storage.media_path_exists(first.relative_path)
    assert b"".join(storage.stream_media(second.relative_path)) == payload


def test_corrupt_target_collision_preserves_the_only_valid_durable_copy(
    storage: NarrationStorage,
) -> None:
    payload = b"valid-durable-staging"
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = uuid4()
    target = (
        storage.media.path / "assets" / asset_id.hex[:2] / asset_id.hex / f"{digest}.wav"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * len(payload))
    os.chmod(target, 0o440)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
        )

    recovery = storage.media.path / captured.value.staging_relative_path
    assert recovery.read_bytes() == payload
    assert target.read_bytes() != payload
    os.utime(recovery, (1, 1))
    assert storage.cleanup_staging(older_than_epoch=2) == []
    assert recovery.exists(), "a corrupt collision cannot consume valid recovery bytes"


def test_verified_collision_fsync_failure_preserves_durable_staging(
    storage: NarrationStorage,
) -> None:
    payload = b"same-target-needs-a-directory-fsync"
    asset_id = uuid4()
    published = _publish(storage, payload, asset_id=asset_id)
    target = storage.media.path / published.relative_path

    def fail_collision_target_fsync(fd: int) -> None:
        info = os.fstat(fd)
        parent = target.parent.stat()
        if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
            raise OSError("fault injection: colliding target fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=published.actual_sha256,
            expected_size=published.byte_size,
            extension="wav",
            max_bytes=published.byte_size,
            fsync_fn=fail_collision_target_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    assert target.read_bytes() == payload
    assert recovery.read_bytes() == payload
    assert target.stat().st_ino != recovery.stat().st_ino


def test_publication_extension_allowlist_is_fail_closed(storage: NarrationStorage) -> None:
    payload = b"not-an-audio-extension"
    with pytest.raises(PublicationValidationError):
        storage.publish_media(
            [payload],
            asset_id=uuid4(),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_size=len(payload),
            extension="bin",
            max_bytes=len(payload),
        )


@pytest.mark.parametrize(
    "value",
    ["", "/absolute", "../escape", "a/../b", "a//b", "a\\b", "a\x00b", "./a"],
)
def test_path_validation_rejects_escaping_or_ambiguous_values(value: str) -> None:
    with pytest.raises(UnsafeStoragePath):
        validate_relative_path(value)


def test_path_validation_rejects_storage_identifiers_over_1024_bytes() -> None:
    with pytest.raises(UnsafeStoragePath):
        validate_relative_path("/".join(["a"] * 513))


def test_fd_open_rejects_symlink_and_model_root_is_read_only(
    storage: NarrationStorage, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"secret")
    (storage.media.path / "assets").mkdir()
    (storage.media.path / "assets" / "link.wav").symlink_to(outside)
    with pytest.raises(UnsafeStoragePath):
        list(storage.stream_media("assets/link.wav"))
    with pytest.raises(ModelRootReadOnly):
        storage.reject_model_write("anything")


def test_constructor_rejects_symlinked_or_nested_roots(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(UnsafeStoragePath):
        NarrationStorage(models_root=link, media_root=other)
    nested = real / "nested"
    nested.mkdir()
    with pytest.raises(UnsafeStoragePath):
        NarrationStorage(models_root=real, media_root=nested)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-3", (0, 3)),
        ("bytes=4-", (4, 9)),
        ("bytes=-3", (7, 9)),
        ("bytes=8-99", (8, 9)),
    ],
)
def test_single_range_forms(header: str, expected: tuple[int, int]) -> None:
    result = parse_single_range(header, 10)
    assert (result.start, result.end_inclusive) == expected


@pytest.mark.parametrize(
    "header", ["bytes=", "bytes=2-1", "bytes=10-", "bytes=-0", "items=0-1", "bytes=0-1,4-5"]
)
def test_invalid_or_multiple_ranges_are_rejected(header: str) -> None:
    with pytest.raises(MediaPolicyError):
        parse_single_range(header, 10)


def test_http_decisions_cover_range_conditionals_and_head(storage: NarrationStorage) -> None:
    payload = b"abcdefghij"
    published = _publish(storage, payload)
    etag = published.strong_etag
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    ranged = plan_media_read(
        storage,
        asset,
        method="GET",
        range_header="bytes=2-5",
        if_range=etag,
    )
    assert ranged.status == 206
    assert ranged.headers["Content-Range"] == "bytes 2-5/10"
    assert b"".join(stream_read_decision(storage, ranged, chunk_size=2)) == b"cdef"
    mismatch = plan_media_read(
        storage, asset, method="GET", range_header="bytes=2-5", if_range='"different"'
    )
    assert mismatch.status == 200 and mismatch.byte_range is None
    weak = plan_media_read(
        storage, asset, method="GET", range_header="bytes=2-5", if_range=f"W/{etag}"
    )
    assert weak.status == 200
    cached = plan_media_read(
        storage, asset, method="GET", if_none_match=f"W/{etag}"
    )
    assert cached.status == 304 and not cached.send_body
    head = plan_media_read(
        storage, asset, method="HEAD"
    )
    assert head.status == 200 and not head.send_body and list(stream_read_decision(storage, head)) == []
    unsatisfied = plan_media_read(
        storage, asset, method="GET", range_header="bytes=0-1,4-5"
    )
    assert unsatisfied.status == 416 and unsatisfied.headers["Content-Range"] == "bytes */10"
    assert ranged.headers["X-Content-Type-Options"] == "nosniff"
    assert ranged.headers["Cache-Control"].startswith("private,")
    assert ranged.headers["Content-Disposition"].startswith("inline;")


def test_ready_transition_uses_actual_publication_evidence(storage: NarrationStorage) -> None:
    payload = b"payload"
    published = _publish(storage, payload)
    asset = _asset(asset_id=published.asset_id, state="staging")
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = None
    with pytest.raises(MediaConflict):
        apply_ready_evidence(asset, published, mime_type="audio/wav", now=NOW)
    apply_ready_evidence(
        asset,
        published,
        mime_type="audio/wav",
        now=NOW,
        validation={"ok": True},
        structured_parent_state="ready",
    )
    assert (asset.state, asset.byte_size, asset.verified_at) == ("ready", len(payload), NOW)
    assert asset.validation_json["ok"] is True
    assert asset.validation_json["immutable_mode"] == "0440"
    asset.state = "staging"
    asset.content_hash = "0" * 64
    with pytest.raises(MediaConflict):
        apply_ready_evidence(
            asset,
            published,
            mime_type="audio/wav",
            now=NOW,
            structured_parent_state="ready",
        )


def test_ready_transition_rejects_cross_scope_asset(storage: NarrationStorage) -> None:
    published = _publish(storage, b"scope")
    asset = _asset(asset_id=published.asset_id, state="staging")
    asset.owner_id = uuid4()
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    with pytest.raises(MediaConflict):
        apply_ready_evidence(
            asset,
            published,
            mime_type="audio/wav",
            now=NOW,
            structured_parent_state="ready",
        )


def test_ready_transition_rejects_another_asset_publication(
    storage: NarrationStorage,
) -> None:
    published = _publish(storage, b"same bytes cannot cross logical owners")
    asset = _asset(state="staging")
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    with pytest.raises(MediaConflict):
        apply_ready_evidence(
            asset,
            published,
            mime_type="audio/wav",
            now=NOW,
            structured_parent_state="ready",
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "novel_cover", "render_assets", "export_assets", "voice_references",
        "locked_voice_assets", "manifest_assets", "active_job_assets", "uploaded_originals",
    ],
)
def test_every_structured_reference_root_prevents_gc(field_name: str) -> None:
    asset = _asset()
    roots = ReferenceRoots(**{field_name: frozenset({asset.id})})
    decision = evaluate_gc(asset, roots, now=NOW)
    assert not decision.eligible and decision.action == "retain"
    assert field_name in decision.reason


@pytest.mark.parametrize("asset_ids", [(), ("not-a-uuid",)])
def test_db_root_snapshot_rejects_empty_or_untyped_ids(asset_ids: tuple[object, ...]) -> None:
    with pytest.raises(MediaPolicyError):
        load_reference_roots_in_session(None, asset_ids=asset_ids)  # type: ignore[arg-type]


def test_db_root_snapshot_stops_after_the_bounded_input_limit() -> None:
    generated = 0

    def too_many_ids():
        nonlocal generated
        for _ in range(1_002):
            generated += 1
            yield uuid4()

    with pytest.raises(MediaPolicyError):
        load_reference_roots_in_session(None, asset_ids=too_many_ids())  # type: ignore[arg-type]
    assert generated == 1_001


@pytest.mark.parametrize("asset_class", ["source", "voice_reference"])
def test_source_and_private_reference_classes_never_enter_ordinary_gc(asset_class: str) -> None:
    asset = _asset(asset_class=asset_class)
    assert evaluate_gc(asset, ReferenceRoots(), now=NOW).action == "retain"


@pytest.mark.parametrize("retention", ["cover", "uploaded_original", "locked_voice", "legal_hold"])
def test_protected_retention_never_enters_ordinary_gc(retention: str) -> None:
    asset = _asset(retention=retention)
    assert evaluate_gc(asset, ReferenceRoots(), now=NOW).action == "retain"


def test_two_phase_gc_rechecks_late_reference_and_emits_path_free_tombstone(
    storage: NarrationStorage,
) -> None:
    payload = b"payload"
    published = _publish(storage, payload)
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    assert evaluate_gc(asset, ReferenceRoots(), now=NOW).action == "mark"
    generation = mark_gc_candidate(asset, ReferenceRoots(), now=NOW)
    with pytest.raises(MediaNotEligible):
        begin_gc_deletion(
            asset,
            ReferenceRoots(render_assets=frozenset({asset.id})),
            expected_generation=generation,
            now=NOW + timedelta(days=8),
            storage=storage,
        )
    plan = begin_gc_deletion(
        asset,
        ReferenceRoots(),
        expected_generation=generation,
        now=NOW + timedelta(days=8),
        storage=storage,
    )
    result = execute_gc_delete(storage, plan)
    assert result.removed and result.verified_absent
    assert not (storage.media.path / published.relative_path).exists()
    tombstone = finalize_gc_deletion(
        asset,
        result,
        digest_key_id="test-key-v1",
        digest_key=b"test-only-secret-that-is-at-least-32-bytes",
        deleted_actor="test-suite",
        now=NOW + timedelta(days=8),
    )
    assert asset.state == "deleted"
    assert tombstone.original_asset_id == asset.id
    assert len(tombstone.digest) == 64
    assert published.relative_path not in tombstone.digest


def test_staging_gc_obeys_grace_and_generation(storage: NarrationStorage) -> None:
    fresh = _asset(state="staging", created_at=NOW - timedelta(hours=23))
    old = _asset(state="staging", created_at=NOW - timedelta(hours=25))
    assert evaluate_gc(fresh, ReferenceRoots(), now=NOW).action == "wait"
    assert evaluate_gc(old, ReferenceRoots(), now=NOW).eligible
    with pytest.raises(MediaConflict):
        begin_gc_deletion(
            old, ReferenceRoots(), expected_generation=1, now=NOW, storage=storage
        )
    plan = begin_gc_deletion(
        old, ReferenceRoots(), expected_generation=0, now=NOW, storage=storage
    )
    assert plan.reason_code == "staging_orphan"


def test_gc_plan_rejects_noncanonical_media_root_paths(storage: NarrationStorage) -> None:
    old = _asset(state="staging", created_at=NOW - timedelta(hours=25))
    old.storage_path = "internal/metadata.wav"
    with pytest.raises(MediaConflict, match="canonical narration media path"):
        begin_gc_deletion(
            old,
            ReferenceRoots(),
            expected_generation=0,
            now=NOW,
            storage=storage,
        )
    old.storage_path = (
        f"assets/{old.id.hex[:2]}/{old.id.hex}/" + "0" * 64 + ".wav"
    )
    old.mime_type = "audio/mpeg"
    with pytest.raises(MediaConflict, match="canonical narration MIME evidence"):
        begin_gc_deletion(
            old,
            ReferenceRoots(),
            expected_generation=0,
            now=NOW,
            storage=storage,
        )


def test_retention_expiry_and_quota_candidates_do_not_bypass_gc_policy() -> None:
    protected_until_later = _asset()
    protected_until_later.expires_at = NOW + timedelta(days=1)
    old_ready = _asset(created_at=NOW - timedelta(days=90))
    newer_ready = _asset(created_at=NOW - timedelta(days=30))
    candidates = select_quota_candidates(
        [newer_ready, protected_until_later, old_ready], ReferenceRoots(), now=NOW, limit=10
    )
    assert [candidate.asset_id for candidate in candidates] == [old_ready.id, newer_ready.id]
    assert all(candidate.action == "mark" for candidate in candidates)
    assert evaluate_gc(protected_until_later, ReferenceRoots(), now=NOW).reason == "retention_not_expired"


def test_cleanup_staging_deletes_only_stale_owned_part(storage: NarrationStorage) -> None:
    staging = storage.media.path / ".staging"
    staging.mkdir()
    old = staging / ("a" * 32 + ".part")
    keep = staging / ("b" * 32 + ".part")
    unrelated = staging / "do-not-delete.txt"
    old.write_bytes(b"old")
    keep.write_bytes(b"new")
    unrelated.write_bytes(b"keep")
    os.utime(old, (1, 1))
    removed = storage.cleanup_staging(older_than_epoch=2)
    assert removed == [old.name]
    assert keep.exists() and unrelated.exists()


def test_published_file_is_read_only_and_short_writes_are_linear(
    storage: NarrationStorage,
) -> None:
    payload = b"x" * (256 * 1024)
    digest = hashlib.sha256(payload).hexdigest()
    buffer_types: set[type[object]] = set()
    calls = 0

    def one_byte_write(fd: int, chunk: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        buffer_types.add(type(chunk))
        return os.write(fd, chunk[:1])

    published = storage.publish_media(
        [payload],
        asset_id=uuid4(),
        expected_sha256=digest,
        expected_size=len(payload),
        extension="wav",
        max_bytes=len(payload),
        write_fn=one_byte_write,
    )
    info = storage.media_stat(published.relative_path)
    assert stat.S_IMODE(info.st_mode) == 0o440
    assert calls == len(payload)
    assert buffer_types == {memoryview}


def test_staging_directory_fsync_failure_retains_validated_recovery(
    storage: NarrationStorage,
) -> None:
    payload = b"staging-directory-durability"
    digest = hashlib.sha256(payload).hexdigest()
    staging = storage.media.path / ".staging"

    def fail_staging_directory_fsync(fd: int) -> None:
        info = os.fstat(fd)
        if staging.exists():
            staging_info = staging.stat()
            if (info.st_dev, info.st_ino) == (
                staging_info.st_dev,
                staging_info.st_ino,
            ):
                raise OSError("fault injection: staging directory fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=uuid4(),
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=fail_staging_directory_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    target = storage.media.path / captured.value.target_relative_path
    assert recovery.read_bytes() == payload
    assert not recovery.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    assert not target.exists()


def test_destination_fsync_failure_retains_verified_staging(
    storage: NarrationStorage,
) -> None:
    payload = b"durable-staging"
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = uuid4()
    target = (
        storage.media.path / "assets" / asset_id.hex[:2] / asset_id.hex / f"{digest}.wav"
    )

    def fail_destination_fsync(fd: int) -> None:
        info = os.fstat(fd)
        if target.exists() and target.parent.exists():
            parent = target.parent.stat()
            if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
                raise OSError("fault injection: destination fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=fail_destination_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    assert recovery.is_file()
    assert recovery.read_bytes() == payload
    assert not recovery.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    os.utime(recovery, (1, 1))
    assert storage.cleanup_staging(older_than_epoch=2) == [recovery.name]
    assert target.exists() and not recovery.exists()


def test_recovery_cleanup_fsyncs_target_directory_before_removing_staging(
    storage: NarrationStorage,
) -> None:
    payload = b"cleanup-must-redurabilize-target"
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = uuid4()
    target = (
        storage.media.path / "assets" / asset_id.hex[:2] / asset_id.hex / f"{digest}.wav"
    )

    def fail_publication_target_fsync(fd: int) -> None:
        info = os.fstat(fd)
        if target.exists() and target.parent.exists():
            parent = target.parent.stat()
            if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
                raise OSError("fault injection: publication target fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=fail_publication_target_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    os.utime(recovery, (1, 1))

    target_parent = target.parent.stat()

    def fail_cleanup_target_fsync(fd: int) -> None:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (
            target_parent.st_dev,
            target_parent.st_ino,
        ):
            raise OSError("fault injection: cleanup target fsync")
        os.fsync(fd)

    with pytest.raises(OSError, match="cleanup target fsync"):
        storage.cleanup_staging(
            older_than_epoch=2,
            fsync_fn=fail_cleanup_target_fsync,
        )
    assert recovery.exists(), "failed target fsync must preserve durable recovery"
    assert target.stat().st_nlink == 2

    assert storage.cleanup_staging(older_than_epoch=2) == [recovery.name]
    assert not recovery.exists()
    assert target.stat().st_nlink == 1


def test_publication_detects_target_swap_and_keeps_verified_staging(
    storage: NarrationStorage,
) -> None:
    payload = b"target-swap-during-publication"
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = uuid4()
    target = (
        storage.media.path / "assets" / asset_id.hex[:2] / asset_id.hex / f"{digest}.wav"
    )
    swapped = False

    def swap_target_during_fsync(fd: int) -> None:
        nonlocal swapped
        info = os.fstat(fd)
        if target.exists() and target.parent.exists():
            parent = target.parent.stat()
            if not swapped and (info.st_dev, info.st_ino) == (
                parent.st_dev,
                parent.st_ino,
            ):
                target.unlink()
                target.write_bytes(b"x" * len(payload))
                os.chmod(target, 0o440)
                swapped = True
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=swap_target_during_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    assert swapped
    assert recovery.read_bytes() == payload
    assert target.read_bytes() != payload


def test_cleanup_preserves_verified_staging_when_target_inode_was_replaced(
    storage: NarrationStorage,
) -> None:
    payload = b"replacement-must-not-consume-recovery"
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = uuid4()
    target = (
        storage.media.path / "assets" / asset_id.hex[:2] / asset_id.hex / f"{digest}.wav"
    )

    def fail_destination_fsync(fd: int) -> None:
        info = os.fstat(fd)
        if target.exists() and target.parent.exists():
            parent = target.parent.stat()
            if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
                raise OSError("fault injection: destination fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=fail_destination_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    target.unlink()
    target.write_bytes(payload)
    os.chmod(target, 0o440)
    os.utime(recovery, (1, 1))
    assert storage.cleanup_staging(older_than_epoch=2) == []
    assert recovery.exists(), "a same-name replacement is not durable publication evidence"


def test_cleanup_rechecks_target_after_directory_fsync_before_unlinking_recovery(
    storage: NarrationStorage,
) -> None:
    payload = b"cleanup-target-swap-must-preserve-recovery"
    digest = hashlib.sha256(payload).hexdigest()
    asset_id = uuid4()
    target = (
        storage.media.path / "assets" / asset_id.hex[:2] / asset_id.hex / f"{digest}.wav"
    )

    def fail_publication_target_fsync(fd: int) -> None:
        info = os.fstat(fd)
        if target.exists() and target.parent.exists():
            parent = target.parent.stat()
            if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
                raise OSError("fault injection: publication target fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=asset_id,
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=fail_publication_target_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    backup = target.with_suffix(".original")
    os.utime(recovery, (1, 1))
    swapped = False

    def swap_target_during_cleanup_fsync(fd: int) -> None:
        nonlocal swapped
        info = os.fstat(fd)
        parent = target.parent.stat()
        if not swapped and (info.st_dev, info.st_ino) == (
            parent.st_dev,
            parent.st_ino,
        ):
            target.rename(backup)
            target.write_bytes(b"x" * len(payload))
            os.chmod(target, 0o440)
            swapped = True
        os.fsync(fd)

    assert storage.cleanup_staging(
        older_than_epoch=2,
        fsync_fn=swap_target_during_cleanup_fsync,
    ) == []
    assert swapped
    assert recovery.exists()
    assert recovery.stat().st_ino == backup.stat().st_ino
    assert target.read_bytes() != payload


def test_destination_directory_creation_fsync_failure_keeps_only_durable_copy(
    storage: NarrationStorage,
) -> None:
    payload = b"directory-fsync-recovery"
    digest = hashlib.sha256(payload).hexdigest()
    assets = storage.media.path / "assets"

    def fail_new_assets_parent_fsync(fd: int) -> None:
        root = storage.media.path.stat()
        info = os.fstat(fd)
        if assets.exists() and (info.st_dev, info.st_ino) == (root.st_dev, root.st_ino):
            raise OSError("fault injection: new directory parent fsync")
        os.fsync(fd)

    with pytest.raises(PublicationDurabilityError) as captured:
        storage.publish_media(
            [payload],
            asset_id=uuid4(),
            expected_sha256=digest,
            expected_size=len(payload),
            extension="wav",
            max_bytes=len(payload),
            fsync_fn=fail_new_assets_parent_fsync,
        )
    recovery = storage.media.path / captured.value.staging_relative_path
    assert recovery.is_file()
    assert not (assets / digest[:2] / f"{digest}.wav").exists()
    os.utime(recovery, (1, 1))
    assert storage.cleanup_staging(older_than_epoch=2) == []
    assert recovery.exists(), "verified unique staging bytes must remain recoverable"


def test_fifo_and_hardlink_aliases_fail_without_following_or_blocking(
    storage: NarrationStorage,
) -> None:
    assets = storage.media.path / "assets"
    assets.mkdir()
    fifo = assets / "blocked.wav"
    os.mkfifo(fifo)
    with pytest.raises(UnsafeStoragePath):
        list(storage.stream_media("assets/blocked.wav"))

    published = _publish(storage, b"hard-link-protected")
    alias = storage.media.path / "alias.wav"
    os.link(storage.media.path / published.relative_path, alias)
    with pytest.raises(UnsafeStoragePath):
        storage.media_stat(published.relative_path)


def test_constructor_rejects_root_inode_alias(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    with pytest.raises(UnsafeStoragePath):
        NarrationStorage(models_root=shared, media_root=shared)


def test_runtime_rejects_group_or_world_writable_storage_root(
    storage: NarrationStorage,
) -> None:
    os.chmod(storage.media.path, 0o777)
    with pytest.raises(StorageRootChanged):
        storage.media_path_exists("assets/missing.wav")


def test_head_and_304_fail_closed_when_ready_file_is_missing(
    storage: NarrationStorage,
) -> None:
    published = _publish(storage, b"conditional")
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    os.unlink(storage.media.path / published.relative_path)
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="HEAD")
    with pytest.raises(MediaNotEligible):
        plan_media_read(
            storage, asset, method="GET", if_none_match=published.strong_etag
        )


def test_http_plan_rejects_state_mime_and_extension_mismatch(
    storage: NarrationStorage,
) -> None:
    published = _publish(storage, b"mime")
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    asset.mime_type = "audio/mpeg"
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="GET")
    asset.mime_type = "audio/wav"
    asset.state = "deleting"
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="GET")
    asset.state = "ready"
    asset.checksum_algorithm = "md5"
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="GET")
    asset.checksum_algorithm = "sha256"
    asset.verified_at = None
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="GET")
    asset.verified_at = NOW
    asset.asset_class = None
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="GET")


def test_stream_rejects_inode_swap_after_http_plan(storage: NarrationStorage) -> None:
    payload = b"same-size-original"
    published = _publish(storage, payload)
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    decision = plan_media_read(storage, asset, method="GET")
    target = storage.media.path / published.relative_path
    target.unlink()
    target.write_bytes(b"same-size-replaced")
    os.chmod(target, 0o440)
    with pytest.raises(StorageError):
        list(stream_read_decision(storage, decision))


def test_http_plan_rehashes_actual_bytes_before_emitting_etag(
    storage: NarrationStorage,
) -> None:
    payload = b"etag-original"
    published = _publish(storage, payload)
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    target = storage.media.path / published.relative_path
    target.unlink()
    target.write_bytes(b"etag-tampered")
    os.chmod(target, 0o440)
    with pytest.raises(MediaNotEligible):
        plan_media_read(storage, asset, method="HEAD")


def _ready_gc_plan(
    storage: NarrationStorage, payload: bytes = b"gc-identity"
) -> tuple[MediaAsset, object]:
    published = _publish(storage, payload)
    asset = _asset(asset_id=published.asset_id)
    asset.storage_path = published.relative_path
    asset.content_hash = published.actual_sha256
    asset.byte_size = published.byte_size
    generation = mark_gc_candidate(asset, ReferenceRoots(), now=NOW)
    plan = begin_gc_deletion(
        asset,
        ReferenceRoots(),
        expected_generation=generation,
        now=NOW + timedelta(days=8),
        storage=storage,
    )
    return asset, plan


def test_gc_unlink_rejects_replacement_hash_and_inode(storage: NarrationStorage) -> None:
    _asset_row, plan = _ready_gc_plan(storage)
    target = storage.media.path / plan.relative_path
    target.unlink()
    replacement = b"x" * plan.byte_size
    target.write_bytes(replacement)
    os.chmod(target, 0o440)
    with pytest.raises(UnsafeStoragePath):
        execute_gc_delete(storage, plan)
    assert target.exists()


def test_gc_rejects_file_appearing_after_absent_plan(storage: NarrationStorage) -> None:
    asset = _asset(state="staging", created_at=NOW - timedelta(days=2))
    plan = begin_gc_deletion(
        asset,
        ReferenceRoots(),
        expected_generation=0,
        now=NOW,
        storage=storage,
    )
    assert not plan.file_present
    target = storage.media.path / plan.relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"appeared")
    os.chmod(target, 0o440)
    with pytest.raises(UnsafeStoragePath):
        execute_gc_delete(storage, plan)


def test_absent_staging_gc_plan_is_idempotently_verified_absent(
    storage: NarrationStorage,
) -> None:
    asset = _asset(state="staging", created_at=NOW - timedelta(days=2))
    plan = begin_gc_deletion(
        asset,
        ReferenceRoots(),
        expected_generation=0,
        now=NOW,
        storage=storage,
    )
    result = execute_gc_delete(storage, plan)
    assert not result.removed and result.verified_absent


def test_gc_finalize_compares_full_identity_and_validates_hmac_inputs(
    storage: NarrationStorage,
) -> None:
    asset, plan = _ready_gc_plan(storage)
    result = execute_gc_delete(storage, plan)
    with pytest.raises(MediaPolicyError):
        finalize_gc_deletion(
            asset,
            result,
            digest_key_id="key",
            digest_key=b"too-short",
            deleted_actor="actor",
            now=NOW + timedelta(days=8),
        )
    with pytest.raises(MediaPolicyError):
        finalize_gc_deletion(
            asset,
            result,
            digest_key_id=" ",
            digest_key=b"k" * 32,
            deleted_actor=" ",
            now=NOW + timedelta(days=8),
        )
    for key_id, actor in (("key\nforge", "actor"), ("key-v1", "actor\x7f")):
        with pytest.raises(MediaPolicyError):
            finalize_gc_deletion(
                asset,
                result,
                digest_key_id=key_id,
                digest_key=b"k" * 32,
                deleted_actor=actor,
                now=NOW + timedelta(days=8),
            )
    asset.storage_backend = "replaced"
    with pytest.raises(MediaConflict):
        finalize_gc_deletion(
            asset,
            result,
            digest_key_id="key-v1",
            digest_key=b"k" * 32,
            deleted_actor="actor",
            now=NOW + timedelta(days=8),
        )


def test_etag_is_derived_from_actual_bytes_not_declared_metadata() -> None:
    payload = b"actual playback bytes"
    digest = hashlib.sha256(payload).hexdigest()
    assert strong_etag(digest) == f'"{digest}"'
    with pytest.raises(MediaPolicyError):
        strong_etag("requested-model-fingerprint")
