from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Callable, TypeVar
from uuid import UUID, uuid4

import pytest

from backend.models import (
    MediaAsset,
    Novel,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration import schemas as wire
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from backend.narration.services import (
    IdempotencyConflict,
    NarrationCasConflict,
    NarrationScopeMismatch,
    VoiceRightsUnavailable,
)
from backend.narration.settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)
from backend.narration.voices import (
    VOICE_SETTINGS_OPERATIONS,
    VoiceProfileCreationReceipt,
    VoiceSettingsHandler,
    VoiceUploadValidationError,
    archive_voice_profile,
    create_voice_profile,
    list_voice_profiles,
    parse_uploaded_voice_multipart,
    update_voice_profile,
    voice_profile_resource,
)


T = TypeVar("T")
NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SHA_A = "a" * 64


class MemoryStore:
    """Transaction-shaped fake with no filesystem, model, or database I/O."""

    def __init__(self) -> None:
        self.rows: dict[type[object], list[object]] = defaultdict(list)
        self.flush_count = 0
        self.profile_creation_receipts = MemoryProfileCreationReceiptPort()

    def add(self, row: object) -> None:
        self.rows[type(row)].append(row)

    def flush(self) -> None:
        self.flush_count += 1

    def get(self, model: type[T], row_id: object, *, for_update: bool = False) -> T | None:
        del for_update
        return next(
            (row for row in self.rows[model] if getattr(row, "id") == row_id),
            None,
        )  # type: ignore[return-value]

    def find_one(
        self,
        model: type[T],
        *,
        for_update: bool = False,
        **filters: object,
    ) -> T | None:
        del for_update
        return next(
            (
                row
                for row in self.rows[model]
                if all(getattr(row, key) == value for key, value in filters.items())
            ),
            None,
        )  # type: ignore[return-value]

    def find_all(
        self,
        model: type[T],
        *,
        order_by: tuple[str, ...] = (),
        for_update: bool = False,
        **filters: object,
    ) -> list[T]:
        del for_update
        rows = [
            row
            for row in self.rows[model]
            if all(getattr(row, key) == value for key, value in filters.items())
        ]
        if order_by:
            rows.sort(key=lambda row: tuple(getattr(row, key) for key in order_by))
        return rows  # type: ignore[return-value]

    def consume_render_publication_context(self, **_: object) -> None:
        raise AssertionError("T2-D never consumes render publication context")


class MemoryProfileCreationReceiptPort:
    """Unit-test fake only; product integration must provide durable storage."""

    def __init__(self) -> None:
        self.receipts: dict[str, tuple[str, UUID]] = {}

    def reserve(
        self,
        *,
        idempotency_key: str,
        payload_sha256: str,
        profile_id: UUID,
    ) -> VoiceProfileCreationReceipt:
        existing = self.receipts.get(idempotency_key)
        if existing is not None:
            if existing != (payload_sha256, profile_id):
                raise IdempotencyConflict("profile key names another payload")
            return VoiceProfileCreationReceipt(
                profile_id=profile_id,
                payload_sha256=payload_sha256,
                replay=True,
            )
        self.receipts[idempotency_key] = (payload_sha256, profile_id)
        return VoiceProfileCreationReceipt(
            profile_id=profile_id,
            payload_sha256=payload_sha256,
            replay=False,
        )


def novel(novel_id: UUID | None = None) -> Novel:
    return Novel(
        id=novel_id or uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        title="测试作品",
        author_name="作者",
        description="",
        writing_type="novel",
        audience="general",
        genre="fiction",
        subgenre="",
        idea="",
        template_name="",
        template_data={},
        cover_mode="none",
        cover_image_data="",
        outline_target_chapters=0,
        highlight="",
        background="",
        main_plot="",
        story_ledger_version=1,
        version=1,
    )


def active_rights(
    *,
    novel_id: UUID | None,
    source_kind: str = "preset_catalog",
    source_identifier: str = "private://must-not-leak",
) -> VoiceRightsRecord:
    return VoiceRightsRecord(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=novel_id,
        source_kind=source_kind,
        source_identifier=source_identifier,
        notice_version="voice-rights/1",
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=True,
        subject_consent_reference="consent-record-1",
        confirmed_actor="local-owner",
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=365),
        risk_flags_json=[],
    )


def seeded_profile(
    store: MemoryStore,
    book: Novel,
    *,
    source_type: str = "preset",
    version_state: str = "draft",
    profile_status: str = "draft",
) -> tuple[VoiceProfile, VoiceProfileVersion, VoiceRightsRecord]:
    rights = active_rights(
        novel_id=book.id,
        source_kind={
            "preset": "preset_catalog",
            "uploaded": "user_upload",
            "generated": "voice_generator",
        }[source_type],
    )
    profile = VoiceProfile(
        id=uuid4(),
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=book.id,
        name="林岚",
        current_version_id=None,
        status=profile_status,
        version=1,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    locked = version_state == "locked"
    version = VoiceProfileVersion(
        id=uuid4(),
        profile_id=profile.id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        version_number=1,
        source_type=source_type,
        state=version_state,
        provider_id="moss",
        model_id="moss-tts-nano",
        model_revision="test-only-metadata",
        preset_key="unapproved-test-preset" if source_type == "preset" else None,
        reference_asset_id=uuid4() if source_type == "uploaded" else None,
        preview_asset_id=None,
        rights_record_id=rights.id,
        description_digest_key_id="private-key" if source_type == "generated" else None,
        description_digest=SHA_A if source_type == "generated" else None,
        language="zh-CN",
        seed=None,
        parameters_json={},
        fingerprint=SHA_A,
        quality_state="accepted" if locked else "pending",
        activation_basis="preview_confirmed",
        validation_basis="human_accepted" if locked else "pending",
        locked_actor="local-owner" if locked else None,
        locked_at=NOW if locked else None,
        created_at=NOW,
    )
    if locked:
        profile.current_version_id = version.id
        profile.status = "active"
    store.add(rights)
    store.add(profile)
    store.add(version)
    return profile, version, rights


def rights_request() -> wire.VoiceRightsDeclarationRequest:
    return wire.VoiceRightsDeclarationRequest(
        notice_version="voice-rights/1",
        source_identifier="my-authorized-recording",
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=True,
        subject_consent_reference="consent-1",
        confirmed=True,
    )


def wav_bytes() -> bytes:
    return b"RIFF" + (8).to_bytes(4, "little") + b"WAVE" + b"fmt "


def upload_metadata(audio: bytes, *, filename: str = "voice.wav") -> wire.UploadedVoiceVersionMetadata:
    return wire.UploadedVoiceVersionMetadata(
        expected_profile_version=1,
        language="zh-CN",
        original_filename=filename,
        reference_sha256=hashlib.sha256(audio).hexdigest(),
        rights=rights_request(),
    )


def multipart_body(
    metadata: wire.UploadedVoiceVersionMetadata,
    audio: bytes,
    *,
    boundary: str = "T2DBoundary123",
    mime_type: str = "audio/wav",
    filename: str | None = None,
    extra_part: bool = False,
) -> tuple[str, bytes]:
    actual_filename = filename or metadata.original_filename
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="metadata"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False).encode(),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        (
            "Content-Disposition: form-data; name=\"reference_audio\"; "
            f"filename=\"{actual_filename}\"\r\n"
        ).encode(),
        f"Content-Type: {mime_type}\r\n\r\n".encode(),
        audio,
        b"\r\n",
    ]
    if extra_part:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="unexpected"\r\n\r\n',
                b"nope\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def create_profile(store: MemoryStore, book: Novel | None, *, key: str, name: str) -> wire.VoiceProfileResource:
    return create_voice_profile(
        store,
        wire.CreateVoiceProfileRequest(novel_id=book.id if book else None, name=name),
        idempotency_key=key,
        receipt_port=store.profile_creation_receipts,
    )


def test_profile_create_is_durable_idempotent_and_conflict_safe() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    first = create_profile(store, book, key="profile-key-0001", name="旁白")
    replay = create_profile(store, book, key="profile-key-0001", name="旁白")
    assert replay == first
    assert store.flush_count == 1
    assert len(store.rows[VoiceProfile]) == 1
    assert first.status is wire.VoiceProfileStatus.DRAFT
    assert first.version == 1 and first.versions == []
    renamed = update_voice_profile(
        store,
        first.profile_id,
        wire.UpdateVoiceProfileRequest(expected_version=1, name="旁白（已改名）"),
    )
    replay_after_mutation = create_profile(
        store,
        book,
        key="profile-key-0001",
        name="旁白",
    )
    assert replay_after_mutation == renamed
    with pytest.raises(IdempotencyConflict):
        create_profile(store, book, key="profile-key-0001", name="另一音色")
    assert len(store.rows[VoiceProfile]) == 1


def test_profile_listing_never_leaks_another_novel() -> None:
    store = MemoryStore()
    book_a, book_b = novel(), novel()
    store.add(book_a)
    store.add(book_b)
    library = create_profile(store, None, key="profile-library", name="私人音色库")
    local = create_profile(store, book_a, key="profile-book-a", name="甲作品")
    create_profile(store, book_b, key="profile-book-b", name="乙作品")
    assert {item.profile_id for item in list_voice_profiles(
        store, novel_id=book_a.id, include_library=True
    ).items} == {library.profile_id, local.profile_id}
    assert [item.profile_id for item in list_voice_profiles(
        store, novel_id=book_a.id, include_library=False
    ).items] == [local.profile_id]
    assert [item.profile_id for item in list_voice_profiles(
        store, novel_id=None, include_library=True
    ).items] == [library.profile_id]


def test_profile_scope_update_archive_and_locked_version_immutability() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    profile, version, _ = seeded_profile(
        store,
        book,
        version_state="locked",
        profile_status="active",
    )
    immutable_before = (
        version.id,
        version.state,
        version.quality_state,
        version.locked_actor,
        version.locked_at,
        version.fingerprint,
    )
    renamed = update_voice_profile(
        store,
        profile.id,
        wire.UpdateVoiceProfileRequest(expected_version=1, name="林岚·新版名称"),
    )
    assert renamed.version == 2 and renamed.name == "林岚·新版名称"
    with pytest.raises(NarrationCasConflict):
        archive_voice_profile(store, profile.id, expected_version=1)
    archived = archive_voice_profile(store, profile.id, expected_version=2)
    assert archived.status is wire.VoiceProfileStatus.ARCHIVED
    assert archived.version == 3 and archived.archived_at is not None
    assert immutable_before == (
        version.id,
        version.state,
        version.quality_state,
        version.locked_actor,
        version.locked_at,
        version.fingerprint,
    )
    profile.owner_id = uuid4()
    with pytest.raises(NarrationScopeMismatch):
        voice_profile_resource(store, profile)


def test_rights_projection_hashes_private_locator_and_preserves_revocation_history() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    profile, version, rights = seeded_profile(store, book)
    store.add(VoiceRightsEvent(
        id=uuid4(),
        rights_record_id=rights.id,
        event_key="revoked-1",
        event_type="revoked",
        actor="local-owner",
        reason_code="AUTHOR_REVOKED",
        occurred_at=NOW + timedelta(hours=1),
    ))
    resource = voice_profile_resource(store, profile, at=NOW + timedelta(hours=2))
    public_rights = resource.versions[0].rights
    assert public_rights.state is wire.VoiceRightsState.REVOKED
    assert public_rights.source_identifier_sha256 == hashlib.sha256(
        rights.source_identifier.encode()
    ).hexdigest()
    assert rights.source_identifier not in resource.model_dump_json()
    with pytest.raises(VoiceRightsUnavailable):
        VoiceSettingsHandler(store).dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
            profile_id=profile.id,
            payload=wire.CreateVoicePreviewRequest(
                version_id=version.id,
                preview_text="这段私人试听文本不得回显",
            ),
            idempotency_key="preview-key-0001",
        ))


def test_profile_projection_uses_latest_unexpired_preview_record_not_legacy_version_link() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    profile, version, _ = seeded_profile(store, book)
    legacy_asset_id = uuid4()
    selected_asset_id = uuid4()
    version.preview_asset_id = legacy_asset_id

    def preview_asset(asset_id: UUID, digest: str) -> MediaAsset:
        return MediaAsset(
            id=asset_id,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=book.id,
            source_revision_id=None,
            kind="narration_voice_preview",
            asset_class="preview",
            mime_type="audio/wav",
            byte_size=4_096,
            duration_ms=1_000,
            sample_rate=48_000,
            channels=2,
            storage_backend="local",
            state="ready",
            retention_policy="temporary_preview",
            checksum_algorithm="sha256",
            validation_json={},
            verified_at=NOW,
            last_accessed_at=None,
            expires_at=NOW + timedelta(hours=1),
            deleted_at=None,
            gc_generation=0,
            gc_marked_at=None,
            storage_path=(
                f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.wav"
            ),
            content_hash=digest,
            metadata_json={},
            created_at=NOW,
        )

    store.add(preview_asset(legacy_asset_id, "b" * 64))
    store.add(preview_asset(selected_asset_id, "c" * 64))
    store.add(
        VoicePreview(
            id=uuid4(),
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            novel_id=book.id,
            profile_id=profile.id,
            version_id=version.id,
            rights_record_id=version.rights_record_id,
            job_id=uuid4(),
            reference_asset_id=uuid4(),
            result_asset_id=selected_asset_id,
            preview_text=None,
            preview_text_digest_key_id="key-1",
            preview_text_digest="d" * 64,
            model_fingerprint="e" * 64,
            reference_fingerprint="f" * 64,
            parameters_fingerprint="1" * 64,
            request_fingerprint="2" * 64,
            status="ready",
            started_at=NOW,
            completed_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            failure_code=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )

    current = voice_profile_resource(store, profile, at=NOW + timedelta(minutes=1))
    assert current.versions[0].preview_asset is not None
    assert current.versions[0].preview_asset.asset_id == selected_asset_id
    expired = voice_profile_resource(store, profile, at=NOW + timedelta(hours=2))
    assert expired.versions[0].preview_asset is None


def test_multipart_parser_accepts_only_exact_validated_wav_and_hides_bytes_from_repr() -> None:
    audio = wav_bytes()
    metadata = upload_metadata(audio)
    content_type, body = multipart_body(metadata, audio)
    parsed = parse_uploaded_voice_multipart(content_type, body)
    assert parsed.metadata == metadata
    assert parsed.mime_type == "audio/wav"
    assert parsed.filename == "voice.wav"
    assert parsed.byte_size == len(audio)
    assert parsed.checksum_sha256 == metadata.reference_sha256
    assert "RIFF" not in repr(parsed)


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda metadata, audio: multipart_body(metadata, audio, extra_part=True), wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID),
        (lambda metadata, audio: multipart_body(metadata, audio, mime_type="audio/mpeg"), wire.NarrationErrorCode.UNSUPPORTED_MEDIA_TYPE),
        (lambda metadata, audio: multipart_body(metadata, audio, filename="../voice.wav"), wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID),
        (lambda metadata, audio: multipart_body(metadata, b"not-a-wave"), wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID),
    ],
)
def test_multipart_parser_rejects_extra_mime_filename_magic_and_hash_drift(
    mutator: Callable[
        [wire.UploadedVoiceVersionMetadata, bytes],
        tuple[str, bytes],
    ],
    expected_code: wire.NarrationErrorCode,
) -> None:
    audio = wav_bytes()
    metadata = upload_metadata(audio)
    content_type, body = mutator(metadata, audio)
    with pytest.raises(VoiceUploadValidationError) as caught:
        parse_uploaded_voice_multipart(content_type, body)
    assert caught.value.code is expected_code


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        (
            b"Content-Type: audio/wav\r\n\r\n",
            b"Content-Transfer-Encoding: binary\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n"
            b"Content-Type: audio/wav\r\n\r\n",
        ),
        (
            b'name="reference_audio"; filename="voice.wav"',
            b'name="reference_audio"; name="metadata"; filename="voice.wav"',
        ),
        (
            b'name="reference_audio"; filename="voice.wav"',
            b'name="reference_audio"; filename="voice.wav"; filename="other.wav"',
        ),
        (
            b'name="reference_audio"; filename="voice.wav"',
            b'name="reference_audio"; name*=utf-8\'\'metadata; filename="voice.wav"',
        ),
        (
            b'name="reference_audio"; filename="voice.wav"',
            b'name="reference_audio"; filename="voice.wav"; filename*=utf-8\'\'other.wav',
        ),
    ],
)
def test_multipart_parser_explicitly_rejects_ambiguous_transfer_and_disposition(
    original: bytes,
    replacement: bytes,
) -> None:
    audio = wav_bytes()
    metadata = upload_metadata(audio)
    content_type, body = multipart_body(metadata, audio)
    ambiguous_body = body.replace(original, replacement, 1)
    assert ambiguous_body != body
    with pytest.raises(VoiceUploadValidationError) as caught:
        parse_uploaded_voice_multipart(content_type, ambiguous_body)
    assert caught.value.code is wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID


def test_multipart_parser_enforces_frozen_envelope_and_explicit_rights() -> None:
    with pytest.raises(VoiceUploadValidationError) as oversized:
        parse_uploaded_voice_multipart(
            "multipart/form-data; boundary=x",
            b"x" * (wire.REFERENCE_UPLOAD_MAX_BYTES + 64 * 1024 + 1),
        )
    assert oversized.value.code is wire.NarrationErrorCode.PAYLOAD_TOO_LARGE
    audio = wav_bytes()
    metadata_value = upload_metadata(audio).model_dump(mode="json")
    metadata_value["rights"]["confirmed"] = False
    boundary = "T2DRights"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n"
        "Content-Type: application/json\r\n\r\n"
        f"{json.dumps(metadata_value)}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"reference_audio\"; "
        "filename=\"voice.wav\"\r\nContent-Type: audio/wav\r\n\r\n"
    ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    with pytest.raises(VoiceUploadValidationError) as rights_error:
        parse_uploaded_voice_multipart(
            f"multipart/form-data; boundary={boundary}",
            body,
        )
    assert rights_error.value.code is wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID


def test_preset_and_authorized_upload_remain_fail_closed_without_persisting_rows() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    profile = create_profile(store, book, key="profile-source-1", name="候选音色")
    handler = VoiceSettingsHandler(store)
    with pytest.raises(NarrationApiFault) as preset:
        handler.dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
            profile_id=profile.profile_id,
                payload=wire.CreatePresetVoiceVersionRequest(
                    expected_profile_version=1,
                    preset_id="onnx.Lingyu",
            ),
            idempotency_key="preset-key-0001",
        ))
    assert preset.value.code is wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE
    assert preset.value.capability is wire.CapabilityKey.PRESET_VOICE_SOURCE

    audio = wav_bytes()
    content_type, body = multipart_body(upload_metadata(audio), audio)
    with pytest.raises(NarrationApiFault) as uploaded:
        handler.dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
            profile_id=profile.profile_id,
            idempotency_key="uploaded-key-01",
            multipart_content_type=content_type,
            multipart_body=body,
        ))
    assert uploaded.value.code is wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE
    assert uploaded.value.capability is wire.CapabilityKey.REFERENCE_CLONE
    assert store.rows[VoiceProfileVersion] == []
    assert store.rows[VoiceRightsRecord] == []

    bad_metadata = upload_metadata(audio).model_copy(
        update={"reference_sha256": "b" * 64}
    )
    bad_content_type, bad_body = multipart_body(bad_metadata, audio)
    with pytest.raises(NarrationApiFault) as invalid:
        handler.dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
            profile_id=profile.profile_id,
            idempotency_key="uploaded-key-02",
            multipart_content_type=bad_content_type,
            multipart_body=bad_body,
        ))
    assert invalid.value.code is wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID
    assert store.rows[VoiceProfileVersion] == []
    assert store.rows[VoiceRightsRecord] == []


def test_non_product_preset_is_rejected_before_product_service_dispatch() -> None:
    class RecordingProduct:
        def __init__(self) -> None:
            self.preset_calls: list[str] = []

        def create_preset_version(
            self,
            *,
            profile_id: UUID,
            request: wire.CreatePresetVoiceVersionRequest,
            idempotency_key: str,
        ) -> object:
            del profile_id, idempotency_key
            self.preset_calls.append(request.preset_id)
            return object()

    store = MemoryStore()
    book = novel()
    store.add(book)
    profile = create_profile(store, book, key="profile-scope-1", name="产品音色")
    product = RecordingProduct()
    handler = VoiceSettingsHandler(
        store,
        voice_product=product,  # type: ignore[arg-type]
    )
    before_rows = {
        VoiceProfileVersion: tuple(store.rows[VoiceProfileVersion]),
        VoiceRightsRecord: tuple(store.rows[VoiceRightsRecord]),
    }

    with pytest.raises(NarrationApiFault) as rejected:
        handler.dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
            profile_id=profile.profile_id,
            payload=wire.CreatePresetVoiceVersionRequest(
                expected_profile_version=1,
                preset_id="onnx.Trump",
            ),
            idempotency_key="preset-scope-0001",
        ))

    assert rejected.value.code is wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE
    assert rejected.value.message == "PRODUCT_PRESET_OUT_OF_SCOPE"
    assert rejected.value.field == "preset_id"
    assert rejected.value.capability is wire.CapabilityKey.PRESET_VOICE_SOURCE
    assert product.preset_calls == []
    assert tuple(store.rows[VoiceProfileVersion]) == before_rows[VoiceProfileVersion]
    assert tuple(store.rows[VoiceRightsRecord]) == before_rows[VoiceRightsRecord]


def test_preview_is_terminal_unavailable_and_never_fabricates_asset_or_job() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    profile, version, _ = seeded_profile(store, book)
    handler = VoiceSettingsHandler(store)
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
        profile_id=profile.id,
        payload=wire.CreateVoicePreviewRequest(
            version_id=version.id,
            preview_text="固定试听句",
        ),
        idempotency_key="preview-key-0002",
    )
    first = handler.dispatch(command)
    replay = handler.dispatch(command)
    assert isinstance(first, wire.VoicePreviewResource)
    assert first == replay
    assert first.status is wire.VoicePreviewStatus.UNAVAILABLE
    assert first.failure_code is wire.NarrationErrorCode.PREVIEW_UNAVAILABLE
    assert first.job_id is None and first.asset is None and first.expires_at is None
    assert "固定试听句" not in first.model_dump_json()
    assert store.rows[MediaAsset] == []
    with pytest.raises(NarrationApiFault) as poll:
        handler.dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_VOICE_PREVIEW,
            preview_id=first.preview_id,
        ))
    assert poll.value.code is wire.NarrationErrorCode.PREVIEW_UNAVAILABLE


def test_lock_rechecks_rights_then_source_gate_without_mutating_version() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    profile, version, rights = seeded_profile(
        store,
        book,
        version_state="preview_ready",
    )
    handler = VoiceSettingsHandler(store)
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.LOCK_VOICE_PROFILE,
        profile_id=profile.id,
        payload=wire.LockVoiceProfileRequest(
            expected_profile_version=1,
            version_id=version.id,
            quality_confirmed=True,
        ),
    )
    before = (profile.status, profile.version, profile.current_version_id, version.state, version.locked_at)
    with pytest.raises(NarrationApiFault) as held:
        handler.dispatch(command)
    assert held.value.code is wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE
    assert before == (profile.status, profile.version, profile.current_version_id, version.state, version.locked_at)
    store.add(VoiceRightsEvent(
        id=uuid4(),
        rights_record_id=rights.id,
        event_key="rights-blocked",
        event_type="review_blocked",
        actor="local-owner",
        reason_code="RIGHTS_REVIEW_BLOCKED",
        occurred_at=NOW,
    ))
    with pytest.raises(VoiceRightsUnavailable):
        handler.dispatch(command)
    assert before == (profile.status, profile.version, profile.current_version_id, version.state, version.locked_at)


def test_handler_owns_exact_frozen_voice_operations_only() -> None:
    expected = {
        NarrationSettingsOperation.LIST_OFFICIAL_PRESETS,
        NarrationSettingsOperation.SELECT_OFFICIAL_VOICE,
        NarrationSettingsOperation.LIST_VOICE_PROFILES,
        NarrationSettingsOperation.CREATE_VOICE_PROFILE,
        NarrationSettingsOperation.GET_VOICE_PROFILE,
        NarrationSettingsOperation.PUT_VOICE_PROFILE,
        NarrationSettingsOperation.ARCHIVE_VOICE_PROFILE,
        NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION,
        NarrationSettingsOperation.CREATE_VOICE_PREVIEW,
        NarrationSettingsOperation.GET_VOICE_PREVIEW,
        NarrationSettingsOperation.LOCK_VOICE_PROFILE,
    }
    assert VOICE_SETTINGS_OPERATIONS == expected
    assert all(VoiceSettingsHandler.handles(operation) for operation in expected)
    assert not VoiceSettingsHandler.handles(NarrationSettingsOperation.GET_SETTINGS)
    with pytest.raises(KeyError):
        VoiceSettingsHandler(MemoryStore()).dispatch(NarrationSettingsApiCommand(
            operation=NarrationSettingsOperation.GET_SETTINGS,
        ))


def test_handler_dispatches_official_selection_only_through_independent_port() -> None:
    class RecordingSelectionPort:
        def __init__(self) -> None:
            self.calls: list[tuple[UUID, object, str]] = []

        def select_official_voice(
            self,
            *,
            novel_id: UUID,
            request: wire.OfficialVoiceSelectionRequest,
            idempotency_key: str,
        ) -> object:
            self.calls.append((novel_id, request, idempotency_key))
            return "selected"

    store = MemoryStore()
    book = novel()
    store.add(book)
    payload = wire.OfficialVoiceSelectionRequest(
        preset_id="onnx.Trump",
        target_kind="narrator",
        expected_settings_version=0,
    )
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.SELECT_OFFICIAL_VOICE,
        novel_id=book.id,
        payload=payload,
        idempotency_key="official-select-0001",
    )
    with pytest.raises(NarrationApiFault) as unavailable:
        VoiceSettingsHandler(store).dispatch(command)
    assert unavailable.value.code is wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE

    port = RecordingSelectionPort()
    assert VoiceSettingsHandler(
        store,
        official_voice_selection=port,  # type: ignore[arg-type]
    ).dispatch(command) == "selected"
    assert port.calls == [(book.id, payload, "official-select-0001")]


def test_handler_fails_closed_without_durable_profile_creation_receipts() -> None:
    store = MemoryStore()
    book = novel()
    store.add(book)
    command = NarrationSettingsApiCommand(
        operation=NarrationSettingsOperation.CREATE_VOICE_PROFILE,
        novel_id=book.id,
        payload=wire.CreateVoiceProfileRequest(novel_id=book.id, name="旁白"),
        idempotency_key="profile-api-0001",
    )
    with pytest.raises(NarrationApiFault) as unavailable:
        VoiceSettingsHandler(store).dispatch(command)
    assert unavailable.value.code is wire.NarrationErrorCode.STORAGE_UNAVAILABLE
    assert store.rows[VoiceProfile] == []
    created = VoiceSettingsHandler(
        store,
        profile_creation_receipts=store.profile_creation_receipts,
    ).dispatch(command)
    assert isinstance(created, wire.VoiceProfileResource)
    assert len(store.rows[VoiceProfile]) == 1
