"""Fail-closed voice profile, source, preview, and locking services.

T2-D deliberately separates durable profile metadata from private reference
bytes.  Profile CRUD is transaction-local and persistent.  Source creation is
blocked until its product capability and rights evidence are approved; the
multipart parser is nevertheless complete so a future out-of-transaction media
orchestrator can reuse it without weakening the frozen wire contract.

The caller owns the database transaction.  This module never commits, writes a
file, calls a model, or logs reference audio / preview text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
import hashlib
import json
import re
from typing import Final, Protocol, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ValidationError

from ..models import (
    MediaAsset,
    VoicePreview,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsEvent,
    VoiceRightsRecord,
)

from . import schemas as wire
from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from .official_presets import (
    OFFICIAL_PRESETS,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    official_preset_validation_tier,
    require_official_preset,
    validate_official_version_evidence,
)
from .nano_experiments import validate_nano_experiment_version_evidence
from .services import (
    InvalidNarrationState,
    NarrationCasConflict,
    NarrationNotFound,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    VoiceRightsUnavailable,
    canonical_sha256,
    require_local_novel,
    utc_now,
)
from .settings_api import (
    NarrationApiFault,
    NarrationSettingsApiCommand,
    NarrationSettingsOperation,
)


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SAFE_RISK_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_MIME_PARAMETER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_METADATA_MAX_BYTES: Final = 64 * 1024
_MULTIPART_ENVELOPE_ALLOWANCE: Final = 64 * 1024
_PayloadModel = TypeVar("_PayloadModel", bound=BaseModel)

VOICE_SETTINGS_OPERATIONS: Final[frozenset[NarrationSettingsOperation]] = frozenset(
    {
        NarrationSettingsOperation.LIST_VOICE_PROFILES,
        NarrationSettingsOperation.LIST_OFFICIAL_PRESETS,
        NarrationSettingsOperation.CREATE_OFFICIAL_VOICE_PREVIEW,
        NarrationSettingsOperation.SELECT_OFFICIAL_VOICE,
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
)


class VoiceProfileNotFound(NarrationNotFound):
    """A profile is absent inside the fixed local scope."""


class VoiceVersionNotFound(NarrationNotFound):
    """A profile version is absent inside the fixed local scope."""


class VoiceUploadValidationError(NarrationServiceError):
    """Safe, typed multipart validation failure; reference bytes are never kept."""

    def __init__(
        self,
        code: wire.NarrationErrorCode,
        message: str,
        *,
        field_name: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.field_name = field_name


@dataclass(frozen=True, slots=True)
class ParsedUploadedVoice:
    """Validated in-memory envelope for a future approved media orchestrator."""

    metadata: wire.UploadedVoiceVersionMetadata
    mime_type: str
    filename: str
    byte_size: int
    checksum_sha256: str
    reference_audio: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class VoiceProfileCreationReceipt:
    profile_id: UUID
    payload_sha256: str
    replay: bool


class VoiceProfileCreationReceiptPort(Protocol):
    """Persist one immutable key/payload/resource receipt in the caller tx.

    Implementations must serialize first writers, return the existing receipt
    for the same canonical payload, and raise ``IdempotencyConflict`` if the key
    already names another payload.  An in-memory implementation is not a valid
    product backend.
    """

    def reserve(
        self,
        *,
        idempotency_key: str,
        payload_sha256: str,
        profile_id: UUID,
    ) -> VoiceProfileCreationReceipt: ...

    def complete(self, *, profile_id: UUID) -> None: ...


class VoiceProductPort(Protocol):
    """Narrow production seam for source/preview sagas.

    Upload normalization, filesystem publication, and Nano execution must be
    owned by this port outside the request-scoped settings transaction.  Its DB
    phases use independent short transactions; callers must therefore exclude
    uploaded-version creation from the generic settings transaction wrapper
    before installing a production implementation.
    """

    def create_uploaded_version(
        self,
        *,
        profile_id: UUID,
        parsed: ParsedUploadedVoice,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource: ...

    def create_preset_version(
        self,
        *,
        profile_id: UUID,
        request: wire.CreatePresetVoiceVersionRequest,
        idempotency_key: str,
    ) -> wire.VoiceProfileVersionResource: ...

    def create_preview(
        self,
        *,
        profile_id: UUID,
        request: wire.CreateVoicePreviewRequest,
        idempotency_key: str,
    ) -> wire.VoicePreviewResource: ...

    def create_official_preset_preview(
        self,
        *,
        novel_id: UUID,
        request: wire.OfficialVoicePreviewRequest,
        idempotency_key: str,
    ) -> wire.VoicePreviewResource: ...

    def get_preview(self, *, preview_id: UUID) -> wire.VoicePreviewResource: ...

    def lock_profile(
        self,
        *,
        profile_id: UUID,
        request: wire.LockVoiceProfileRequest,
    ) -> wire.VoiceProfileResource: ...


class OfficialVoiceSelectionPort(Protocol):
    """Independent-transaction port for one-click official voice selection."""

    def select_official_voice(
        self,
        *,
        novel_id: UUID,
        request: wire.OfficialVoiceSelectionRequest,
        idempotency_key: str,
    ) -> wire.OfficialVoiceSelectionResponse: ...


def _required_idempotency_key(value: str | None) -> str:
    if value is None or not _IDEMPOTENCY_KEY.fullmatch(value):
        raise NarrationServiceError("idempotency key is outside the frozen format")
    return value


def _idempotent_uuid(operation: str, idempotency_key: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            "ai-novel-world-2026/narration/"
            f"{LOCAL_OWNER_ID}/{LOCAL_WORKSPACE_ID}/{operation}/{idempotency_key}"
        ),
    )


def _required_profile(
    store: NarrationStore,
    profile_id: UUID,
    *,
    for_update: bool = False,
) -> VoiceProfile:
    profile = store.get(VoiceProfile, profile_id, for_update=for_update)
    if profile is None:
        raise VoiceProfileNotFound("voice profile not found")
    if (
        profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationScopeMismatch("voice profile is outside fixed local scope")
    return profile


def _required_version(
    store: NarrationStore,
    profile: VoiceProfile,
    version_id: UUID,
    *,
    for_update: bool = False,
) -> VoiceProfileVersion:
    version = store.get(VoiceProfileVersion, version_id, for_update=for_update)
    if version is None:
        raise VoiceVersionNotFound("voice version not found")
    if (
        version.owner_id != LOCAL_OWNER_ID
        or version.workspace_id != LOCAL_WORKSPACE_ID
        or version.profile_id != profile.id
    ):
        raise NarrationScopeMismatch("voice version belongs to another profile or scope")
    return version


def _rights_state(
    store: NarrationStore,
    rights: VoiceRightsRecord,
    *,
    at: datetime,
) -> wire.VoiceRightsState:
    events = store.find_all(
        VoiceRightsEvent,
        rights_record_id=rights.id,
        order_by=("occurred_at",),
    )
    event_types = {event.event_type for event in events}
    if "review_blocked" in event_types:
        return wire.VoiceRightsState.REVIEW_BLOCKED
    if "revoked" in event_types:
        return wire.VoiceRightsState.REVOKED
    if "expired" in event_types or (
        rights.expires_at is not None and rights.expires_at <= at
    ):
        return wire.VoiceRightsState.EXPIRED
    return wire.VoiceRightsState.ACTIVE


def _risk_flags(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        flags = list(value)
    elif value == {}:
        # The T1 ORM default was historically an empty mapping.  Accept only
        # that empty legacy shape; non-empty mappings are not public evidence.
        flags = []
    else:
        raise InvalidNarrationState("voice rights risk flags are malformed")
    if (
        any(type(item) is not str or not _SAFE_RISK_CODE.fullmatch(item) for item in flags)
        or len(flags) != len(set(flags))
    ):
        raise InvalidNarrationState("voice rights risk flags are malformed")
    return flags


def _required_rights(
    store: NarrationStore,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
) -> VoiceRightsRecord:
    rights = store.get(VoiceRightsRecord, version.rights_record_id, for_update=False)
    if rights is None:
        raise VoiceRightsUnavailable("voice rights record is absent")
    if (
        rights.owner_id != profile.owner_id
        or rights.workspace_id != profile.workspace_id
        or rights.novel_id not in {None, profile.novel_id}
    ):
        raise NarrationScopeMismatch("voice rights are outside the profile scope")
    expected_kinds = {
        "preset": {"official_preset", "preset_catalog"},
        "uploaded": "user_upload",
        "generated": (
            {"official_preset"}
            if version.activation_basis == "experimental_machine_validated"
            else {"voice_generator"}
        ),
    }.get(version.source_type)
    if expected_kinds is None or rights.source_kind not in (
        expected_kinds if isinstance(expected_kinds, set) else {expected_kinds}
    ):
        raise InvalidNarrationState("voice source and rights provenance disagree")
    if rights.source_kind == "official_preset":
        try:
            validator = (
                validate_nano_experiment_version_evidence
                if version.source_type == "generated"
                else validate_official_version_evidence
            )
            validator(
                version,
                rights,
                expected_model_fingerprint=(
                    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256
                ),
            )
        except ValueError as error:
            raise InvalidNarrationState(
                "official preset evidence disagrees with pinned policy"
            ) from error
    return rights


def _rights_resource(
    store: NarrationStore,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    *,
    now: datetime,
) -> wire.VoiceRightsSummary:
    rights = _required_rights(store, profile, version)
    return wire.VoiceRightsSummary(
        rights_record_id=rights.id,
        state=_rights_state(store, rights, at=now),
        notice_version=rights.notice_version,
        source_kind=rights.source_kind,
        source_identifier_sha256=hashlib.sha256(
            rights.source_identifier.encode("utf-8")
        ).hexdigest(),
        purpose=rights.purpose,
        commercial_use=rights.commercial_use,
        redistribution=rights.redistribution,
        voice_cloning=rights.voice_cloning,
        subject_consent_recorded=bool(rights.subject_consent_reference),
        confirmed_at=rights.confirmed_at,
        expires_at=rights.expires_at,
        risk_flags=_risk_flags(rights.risk_flags_json),
    )


def _require_rights_available(
    store: NarrationStore,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    *,
    now: datetime,
) -> VoiceRightsRecord:
    if profile.status in {"archived", "unavailable"}:
        raise VoiceRightsUnavailable("voice profile is not active for new work")
    if version.state in {"unavailable", "deleted"}:
        raise VoiceRightsUnavailable("voice version is unavailable")
    rights = _required_rights(store, profile, version)
    if _rights_state(store, rights, at=now) is not wire.VoiceRightsState.ACTIVE:
        raise VoiceRightsUnavailable("voice rights have negative or expired evidence")
    if version.source_type == "uploaded" and not rights.voice_cloning:
        raise VoiceRightsUnavailable("uploaded voice lacks cloning permission")
    return rights


def _media_link(
    store: NarrationStore,
    profile: VoiceProfile,
    asset_id: UUID | None,
) -> wire.MediaAssetLink | None:
    if asset_id is None:
        return None
    asset = store.get(MediaAsset, asset_id)
    if asset is None:
        raise InvalidNarrationState("voice preview asset metadata is absent")
    if (
        asset.owner_id != profile.owner_id
        or asset.workspace_id != profile.workspace_id
        or asset.novel_id != profile.novel_id
        or asset.asset_class != "preview"
        or asset.state != "ready"
        or asset.mime_type is None
        or asset.byte_size is None
        or asset.byte_size <= 0
        or asset.duration_ms is None
        or asset.duration_ms <= 0
        or asset.checksum_algorithm != "sha256"
        or not re.fullmatch(r"[a-f0-9]{64}", asset.content_hash)
        or asset.verified_at is None
    ):
        raise InvalidNarrationState("voice preview asset is not safe to publish")
    return wire.MediaAssetLink(
        asset_id=asset.id,
        content_path=f"/media-assets/{asset.id}/content",
        mime_type=asset.mime_type,
        byte_size=asset.byte_size,
        duration_ms=asset.duration_ms,
        checksum_sha256=asset.content_hash,
    )


def _latest_preview_asset_id(
    store: NarrationStore,
    profile: VoiceProfile,
    version: VoiceProfileVersion,
    *,
    at: datetime,
) -> UUID | None:
    """Return only a durable, unexpired preview publication.

    ``VoiceProfileVersion.preview_asset_id`` predates asynchronous Nano
    previews and cannot safely represent a particular expiring execution.
    Product projections therefore derive the link from immutable
    ``VoicePreview`` rows and leave the legacy version field untouched.
    """

    candidates = store.find_all(
        VoicePreview,
        profile_id=profile.id,
        version_id=version.id,
        order_by=("created_at", "id"),
    )
    selected: VoicePreview | None = None
    selected_key: tuple[datetime, UUID] | None = None
    for preview in candidates:
        if (
            preview.owner_id != profile.owner_id
            or preview.workspace_id != profile.workspace_id
            or preview.novel_id != profile.novel_id
        ):
            raise NarrationScopeMismatch("voice preview/profile scope mismatch")
        if (
            preview.status == "ready"
            and preview.result_asset_id is not None
            and preview.completed_at is not None
            and preview.expires_at is not None
            and preview.expires_at > at
        ):
            asset = store.get(MediaAsset, preview.result_asset_id)
            if asset is None:
                raise InvalidNarrationState(
                    "voice preview asset metadata is absent"
                )
            if (
                asset.owner_id != profile.owner_id
                or asset.workspace_id != profile.workspace_id
                or asset.novel_id != profile.novel_id
            ):
                raise NarrationScopeMismatch(
                    "voice preview asset/profile scope mismatch"
                )
            # Completed private-voice deletion retains immutable Preview rows
            # whose media asset is a tombstone.  A later experiment can safely
            # reactivate the unique Profile, so historical non-ready assets
            # must be ignored rather than poisoning the whole profile list.
            if asset.state != "ready":
                continue
            candidate_key = (preview.completed_at, preview.id)
            if selected_key is None or candidate_key > selected_key:
                selected = preview
                selected_key = candidate_key
    return selected.result_asset_id if selected is not None else None


def voice_profile_resource(
    store: NarrationStore,
    profile: VoiceProfile,
    *,
    at: datetime | None = None,
) -> wire.VoiceProfileResource:
    """Project one profile without exposing source locators or storage paths."""

    now = at or utc_now()
    if profile.created_at is None or profile.updated_at is None:
        raise InvalidNarrationState("voice profile timestamps are absent")
    versions: list[wire.VoiceProfileVersionResource] = []
    for version in store.find_all(
        VoiceProfileVersion,
        profile_id=profile.id,
        order_by=("version_number",),
    ):
        if (
            version.owner_id != profile.owner_id
            or version.workspace_id != profile.workspace_id
        ):
            raise NarrationScopeMismatch("voice version/profile scope mismatch")
        if version.created_at is None:
            raise InvalidNarrationState("voice version timestamp is absent")
        versions.append(
            # New official preset versions publish exact pinned provenance.
            # Legacy preset_catalog rows remain readable without pretending
            # they carry the new manifest evidence.
            wire.VoiceProfileVersionResource(
                version_id=version.id,
                profile_id=profile.id,
                version_number=version.version_number,
                source_type=version.source_type,
                state=version.state,
                provider_id=version.provider_id,
                model_id=version.model_id,
                model_revision=version.model_revision,
                preset_key=version.preset_key,
                language=version.language,
                fingerprint=version.fingerprint,
                quality_state=version.quality_state,
                activation_basis=version.activation_basis,
                validation_basis=version.validation_basis,
                rights=_rights_resource(store, profile, version, now=now),
                official_preset=(
                    version.parameters_json.get("official_preset")
                    if type(version.parameters_json) is dict
                    and _required_rights(store, profile, version).source_kind
                    == "official_preset"
                    else None
                ),
                reference_asset_id=version.reference_asset_id,
                preview_asset=_media_link(
                    store,
                    profile,
                    _latest_preview_asset_id(store, profile, version, at=now),
                ),
                description_available=(
                    version.description_digest_key_id is not None
                    and version.description_digest is not None
                ),
                locked_at=version.locked_at,
                created_at=version.created_at,
            )
        )
    return wire.VoiceProfileResource(
        profile_id=profile.id,
        novel_id=profile.novel_id,
        name=profile.name,
        status=profile.status,
        version=profile.version,
        current_version_id=profile.current_version_id,
        versions=versions,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        archived_at=profile.archived_at,
    )


def list_voice_profiles(
    store: NarrationStore,
    *,
    novel_id: UUID | None,
    include_library: bool,
) -> wire.VoiceProfileListResponse:
    if type(include_library) is not bool:
        raise NarrationServiceError("include_library must be an exact boolean")
    if novel_id is not None:
        require_local_novel(store, novel_id)
    scoped = store.find_all(
        VoiceProfile,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
    )
    # A completed private-voice deletion keeps an unavailable tombstone for
    # audit and historical Edition evidence.  Its media rows are deliberately
    # no longer publishable, so it must not poison the active selection list.
    scoped = [row for row in scoped if row.status != "unavailable"]
    if novel_id is None:
        selected = [row for row in scoped if include_library and row.novel_id is None]
    else:
        allowed_novel_ids = {novel_id, None} if include_library else {novel_id}
        selected = [row for row in scoped if row.novel_id in allowed_novel_ids]
    selected.sort(key=lambda row: (row.novel_id is None, row.name.casefold(), str(row.id)))
    return wire.VoiceProfileListResponse(
        items=[voice_profile_resource(store, row) for row in selected]
    )


def list_official_presets() -> wire.OfficialPresetCatalogResponse:
    """Return all 18 pinned presets without prompt codes or audio locators."""

    return wire.OfficialPresetCatalogResponse(
        items=[
            wire.OfficialPresetCatalogItem(
                preset_id=preset.preset_id,
                display_name=preset.display_name,
                group=preset.group,
                language=preset.language,
                local_use_status="available",
                commercial_distribution_status="not_evaluated",
                validation_tier=official_preset_validation_tier(preset.preset_id),
                language_scope=preset.language,
                selectable_now=True,
                previewable_now=True,
                renderable_existing=True,
                provenance=preset.provenance(),
            )
            for preset in OFFICIAL_PRESETS
        ]
    )


def create_voice_profile(
    store: NarrationStore,
    request: wire.CreateVoiceProfileRequest,
    *,
    idempotency_key: str,
    receipt_port: VoiceProfileCreationReceiptPort,
) -> wire.VoiceProfileResource:
    key = _required_idempotency_key(idempotency_key)
    name = request.name.strip()
    if not name or len(name) > 240:
        raise NarrationServiceError("voice profile name is outside the frozen bounds")
    if request.novel_id is not None:
        require_local_novel(store, request.novel_id, for_update=True)
    profile_id = _idempotent_uuid("create-voice-profile", key)
    payload_sha256 = canonical_sha256(
        {
            "operation": "create_voice_profile",
            "novel_id": str(request.novel_id) if request.novel_id is not None else None,
            "name": name,
            "voice_schema_version": wire.NARRATION_VOICE_SCHEMA_VERSION,
        }
    )
    receipt = receipt_port.reserve(
        idempotency_key=key,
        payload_sha256=payload_sha256,
        profile_id=profile_id,
    )
    if (
        receipt.profile_id != profile_id
        or receipt.payload_sha256 != payload_sha256
    ):
        raise InvalidNarrationState("voice profile idempotency receipt is inconsistent")
    existing = store.get(VoiceProfile, profile_id, for_update=True)
    if existing is not None:
        if (
            existing.owner_id != LOCAL_OWNER_ID
            or existing.workspace_id != LOCAL_WORKSPACE_ID
        ):
            raise NarrationScopeMismatch("idempotent voice profile is outside scope")
        if not receipt.replay:
            raise InvalidNarrationState("new receipt names an existing voice profile")
        return voice_profile_resource(store, existing)
    if receipt.replay:
        raise InvalidNarrationState("voice profile receipt names a missing resource")
    now = utc_now()
    profile = VoiceProfile(
        id=profile_id,
        owner_id=LOCAL_OWNER_ID,
        workspace_id=LOCAL_WORKSPACE_ID,
        novel_id=request.novel_id,
        name=name,
        current_version_id=None,
        status="draft",
        version=1,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    store.add(profile)
    store.flush()
    complete = getattr(receipt_port, "complete", None)
    if callable(complete):
        complete(profile_id=profile.id)
        store.flush()
    return voice_profile_resource(store, profile, at=now)


def get_voice_profile(
    store: NarrationStore,
    profile_id: UUID,
) -> wire.VoiceProfileResource:
    return voice_profile_resource(store, _required_profile(store, profile_id))


def update_voice_profile(
    store: NarrationStore,
    profile_id: UUID,
    request: wire.UpdateVoiceProfileRequest,
) -> wire.VoiceProfileResource:
    profile = _required_profile(store, profile_id, for_update=True)
    if profile.version != request.expected_version:
        raise NarrationCasConflict("voice profile version changed")
    if profile.status in {"archived", "unavailable"}:
        raise InvalidNarrationState("voice profile cannot be renamed in this state")
    name = request.name.strip()
    if not name or len(name) > 240:
        raise NarrationServiceError("voice profile name is outside the frozen bounds")
    profile.name = name
    profile.version += 1
    profile.updated_at = utc_now()
    store.flush()
    return voice_profile_resource(store, profile)


def archive_voice_profile(
    store: NarrationStore,
    profile_id: UUID,
    *,
    expected_version: int,
) -> wire.VoiceProfileResource:
    profile = _required_profile(store, profile_id, for_update=True)
    if profile.version != expected_version:
        raise NarrationCasConflict("voice profile version changed")
    if profile.status == "unavailable":
        raise InvalidNarrationState("unavailable voice profile cannot be archived")
    if profile.status == "archived":
        return voice_profile_resource(store, profile)
    now = utc_now()
    profile.status = "archived"
    profile.archived_at = now
    profile.updated_at = now
    profile.version += 1
    store.flush()
    return voice_profile_resource(store, profile, at=now)


def _upload_error(
    code: wire.NarrationErrorCode,
    message: str,
    *,
    field_name: str = "reference_audio",
) -> VoiceUploadValidationError:
    return VoiceUploadValidationError(code, message, field_name=field_name)


def _part_bytes(part: Message, *, field_name: str) -> bytes:
    try:
        payload = part.get_payload(decode=True)
    except (TypeError, ValueError) as error:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "multipart part could not be decoded",
            field_name=field_name,
        ) from error
    if not isinstance(payload, bytes):
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "multipart part has no binary payload",
            field_name=field_name,
        )
    return payload


def _content_disposition_parameter_names(raw_value: str) -> tuple[str, ...]:
    """Return raw parameter names without headerregistry's duplicate collapse."""

    segments: list[str] = []
    segment_start = 0
    quoted = False
    escaped = False
    for index, character in enumerate(raw_value):
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if character == ";" and not quoted:
            segments.append(raw_value[segment_start:index])
            segment_start = index + 1
    if quoted or escaped:
        raise ValueError("unterminated quoted parameter")
    segments.append(raw_value[segment_start:])
    if not segments or not segments[0].strip():
        raise ValueError("missing disposition")

    parameter_names: list[str] = []
    for segment in segments[1:]:
        if "=" not in segment:
            raise ValueError("malformed disposition parameter")
        name, _value = segment.split("=", 1)
        normalized_name = name.strip().lower()
        if not normalized_name or _MIME_PARAMETER_NAME.fullmatch(normalized_name) is None:
            raise ValueError("malformed disposition parameter name")
        parameter_names.append(normalized_name)
    return tuple(parameter_names)


def parse_uploaded_voice_multipart(
    content_type: str | None,
    body: bytes | None,
) -> ParsedUploadedVoice:
    """Validate exact ``metadata + reference_audio`` before any persistence.

    This function performs bounded in-memory parsing only.  It does not keep a
    locator, open a file, standardize audio, or create database rows.
    """

    if (
        type(content_type) is not str
        or not content_type.lower().startswith("multipart/form-data;")
        or "boundary=" not in content_type.lower()
        or "\r" in content_type
        or "\n" in content_type
    ):
        raise _upload_error(
            wire.NarrationErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "reference upload must be multipart/form-data with a boundary",
        )
    if type(body) is not bytes:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "reference upload body must be bytes",
        )
    maximum_envelope = (
        wire.REFERENCE_UPLOAD_MAX_BYTES + _MULTIPART_ENVELOPE_ALLOWANCE
    )
    if len(body) > maximum_envelope:
        raise _upload_error(
            wire.NarrationErrorCode.PAYLOAD_TOO_LARGE,
            "reference upload exceeds the frozen envelope limit",
        )
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            b"MIME-Version: 1.0\r\nContent-Type: "
            + content_type.encode("ascii", "strict")
            + b"\r\n\r\n"
            + body
        )
    except (UnicodeEncodeError, ValueError) as error:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "multipart content type is malformed",
        ) from error
    if (
        message.defects
        or not message.is_multipart()
        or message.get_content_type() != "multipart/form-data"
    ):
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "multipart envelope is malformed",
        )
    parts = list(message.iter_parts())
    if len(parts) != 2 or any(part.is_multipart() for part in parts):
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "multipart must contain exactly metadata and reference_audio",
        )
    named: dict[str, Message] = {}
    for part in parts:
        if part.defects:
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart part is malformed",
            )
        raw_content_dispositions = [
            value
            for header_name, value in part.raw_items()
            if header_name.lower() == "content-disposition"
        ]
        if len(raw_content_dispositions) != 1:
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart part must have one content disposition",
            )
        try:
            disposition_parameters = _content_disposition_parameter_names(
                raw_content_dispositions[0]
            )
        except ValueError as error:
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart content disposition parameters are malformed",
            ) from error
        name_parameters = [
            name
            for name in disposition_parameters
            if name == "name" or name.startswith("name*")
        ]
        filename_parameters = [
            name
            for name in disposition_parameters
            if name == "filename" or name.startswith("filename*")
        ]
        if name_parameters != ["name"] or filename_parameters not in (
            [],
            ["filename"],
        ):
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart content disposition name or filename is ambiguous",
            )
        if len(part.get_all("content-type", [])) > 1:
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart part has ambiguous content type",
            )
        transfer_encodings = part.get_all("content-transfer-encoding", [])
        if len(transfer_encodings) > 1:
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart part has ambiguous transfer encoding",
            )
        if transfer_encodings:
            transfer_encoding = str(transfer_encodings[0]).strip().lower()
            if transfer_encoding not in {"binary", "8bit"}:
                raise _upload_error(
                    wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                    "multipart transfer encoding is not accepted",
                )
        if part.get_content_disposition() != "form-data":
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart part must use form-data disposition",
            )
        name = part.get_param("name", header="content-disposition")
        if name not in {"metadata", "reference_audio"} or name in named:
            raise _upload_error(
                wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
                "multipart fields must be unique metadata and reference_audio",
            )
        named[name] = part
    if set(named) != {"metadata", "reference_audio"}:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "multipart fields must be exact",
        )

    metadata_part = named["metadata"]
    if metadata_part.get_filename() is not None:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "metadata must not be a file",
            field_name="metadata",
        )
    if metadata_part.get_content_type().lower() not in {
        "application/json",
        "text/plain",
    }:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "metadata part must contain JSON text",
            field_name="metadata",
        )
    metadata_bytes = _part_bytes(metadata_part, field_name="metadata")
    if not metadata_bytes or len(metadata_bytes) > _METADATA_MAX_BYTES:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "metadata is empty or too large",
            field_name="metadata",
        )
    try:
        metadata_value = json.loads(metadata_bytes.decode("utf-8", "strict"))
        metadata = wire.UploadedVoiceVersionMetadata.model_validate(metadata_value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "metadata does not match the frozen upload contract",
            field_name="metadata",
        ) from error

    audio_part = named["reference_audio"]
    filename = audio_part.get_filename()
    if (
        type(filename) is not str
        or filename != metadata.original_filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "reference filename is unsafe or disagrees with metadata",
        )
    mime_type = audio_part.get_content_type().lower()
    if mime_type not in wire.REFERENCE_UPLOAD_MIME_TYPES:
        raise _upload_error(
            wire.NarrationErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "reference audio must be WAV or FLAC",
        )
    expected_suffix = ".wav" if mime_type == "audio/wav" else ".flac"
    if not filename.lower().endswith(expected_suffix):
        raise _upload_error(
            wire.NarrationErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "reference filename extension disagrees with MIME",
        )
    audio = _part_bytes(audio_part, field_name="reference_audio")
    if not audio:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "reference audio is empty",
        )
    if len(audio) > wire.REFERENCE_UPLOAD_MAX_BYTES:
        raise _upload_error(
            wire.NarrationErrorCode.PAYLOAD_TOO_LARGE,
            "reference audio exceeds 16 MiB",
        )
    if mime_type == "audio/wav":
        valid_magic = len(audio) >= 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    else:
        valid_magic = audio.startswith(b"fLaC")
    if not valid_magic:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "reference audio signature disagrees with MIME",
        )
    checksum = hashlib.sha256(audio).hexdigest()
    if checksum != metadata.reference_sha256:
        raise _upload_error(
            wire.NarrationErrorCode.REFERENCE_AUDIO_INVALID,
            "reference audio SHA-256 disagrees with metadata",
        )
    return ParsedUploadedVoice(
        metadata=metadata,
        mime_type=mime_type,
        filename=filename,
        byte_size=len(audio),
        checksum_sha256=checksum,
        reference_audio=audio,
    )


def _source_unavailable(source_type: wire.VoiceSourceType) -> NarrationApiFault:
    capability, message = {
        wire.VoiceSourceType.PRESET: (
            wire.CapabilityKey.PRESET_VOICE_SOURCE,
            "官方预设目录与当前 Nano 模型还未完成一致性接线。",
        ),
        wire.VoiceSourceType.UPLOADED: (
            wire.CapabilityKey.REFERENCE_CLONE,
            "参考录音克隆仍处于产品门禁 HOLD。",
        ),
        wire.VoiceSourceType.GENERATED: (
            wire.CapabilityKey.VOICE_GENERATOR,
            "文字描述生成音色当前不可用。",
        ),
    }[source_type]
    return NarrationApiFault(
        wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE,
        message,
        retryable=False,
        capability=capability,
    )


def create_unavailable_voice_preview(
    store: NarrationStore,
    profile_id: UUID,
    request: wire.CreateVoicePreviewRequest,
    *,
    idempotency_key: str,
) -> wire.VoicePreviewResource:
    """Return a truthful terminal projection; never fabricate a job or asset."""

    key = _required_idempotency_key(idempotency_key)
    profile = _required_profile(store, profile_id)
    version = _required_version(store, profile, request.version_id)
    _require_rights_available(store, profile, version, now=utc_now())
    return wire.VoicePreviewResource(
        preview_id=_idempotent_uuid("unavailable-voice-preview", key),
        profile_id=profile.id,
        version_id=version.id,
        status=wire.VoicePreviewStatus.UNAVAILABLE,
        job_id=None,
        asset=None,
        temporary=True,
        expires_at=None,
        failure_code=wire.NarrationErrorCode.PREVIEW_UNAVAILABLE,
    )


def _voice_profile_fault(error: NarrationServiceError) -> NarrationApiFault:
    if isinstance(error, VoiceProfileNotFound):
        return NarrationApiFault(
            wire.NarrationErrorCode.VOICE_PROFILE_NOT_FOUND,
            "找不到请求的音色档案。",
        )
    if isinstance(error, VoiceVersionNotFound):
        return NarrationApiFault(
            wire.NarrationErrorCode.VOICE_VERSION_NOT_FOUND,
            "找不到请求的音色版本。",
        )
    if isinstance(error, VoiceUploadValidationError):
        return NarrationApiFault(
            error.code,
            "参考录音未通过安全校验。",
            field=error.field_name,
            capability=wire.CapabilityKey.REFERENCE_CLONE,
        )
    raise error


class VoiceSettingsHandler:
    """Narrow T2-D operation handler for the final single dispatcher."""

    operations = VOICE_SETTINGS_OPERATIONS

    def __init__(
        self,
        store: NarrationStore,
        *,
        profile_creation_receipts: VoiceProfileCreationReceiptPort | None = None,
        voice_product: VoiceProductPort | None = None,
        official_voice_selection: OfficialVoiceSelectionPort | None = None,
    ) -> None:
        self.store = store
        self.profile_creation_receipts = profile_creation_receipts
        self.voice_product = voice_product
        self.official_voice_selection = official_voice_selection

    @classmethod
    def handles(cls, operation: NarrationSettingsOperation) -> bool:
        return operation in cls.operations

    def dispatch(self, command: NarrationSettingsApiCommand) -> object:
        if command.operation not in self.operations:
            raise KeyError(f"operation is not owned by T2-D: {command.operation.value}")
        try:
            return self._dispatch(command)
        except (VoiceProfileNotFound, VoiceVersionNotFound, VoiceUploadValidationError) as error:
            raise _voice_profile_fault(error) from error

    def _dispatch(self, command: NarrationSettingsApiCommand) -> object:
        operation = command.operation
        if operation is NarrationSettingsOperation.LIST_OFFICIAL_PRESETS:
            return list_official_presets()
        if operation is NarrationSettingsOperation.CREATE_OFFICIAL_VOICE_PREVIEW:
            if self.voice_product is None:
                raise NarrationApiFault(
                    wire.NarrationErrorCode.PREVIEW_UNAVAILABLE,
                    "官方音色试听服务尚未接线。",
                    retryable=False,
                    capability=wire.CapabilityKey.VOICE_PREVIEW,
                )
            return self.voice_product.create_official_preset_preview(
                novel_id=_required_uuid(command.novel_id, "novel_id"),
                request=_payload(command, wire.OfficialVoicePreviewRequest),
                idempotency_key=_required_idempotency_key(command.idempotency_key),
            )
        if operation is NarrationSettingsOperation.SELECT_OFFICIAL_VOICE:
            if self.official_voice_selection is None:
                raise NarrationApiFault(
                    wire.NarrationErrorCode.VOICE_SOURCE_UNAVAILABLE,
                    "官方音色直接选择服务尚未接线。",
                    retryable=False,
                    capability=wire.CapabilityKey.PRESET_VOICE_SOURCE,
                )
            return self.official_voice_selection.select_official_voice(
                novel_id=_required_uuid(command.novel_id, "novel_id"),
                request=_payload(command, wire.OfficialVoiceSelectionRequest),
                idempotency_key=_required_idempotency_key(command.idempotency_key),
            )
        if operation is NarrationSettingsOperation.LIST_VOICE_PROFILES:
            return list_voice_profiles(
                self.store,
                novel_id=command.novel_id,
                include_library=command.include_library is not False,
            )
        if operation is NarrationSettingsOperation.CREATE_VOICE_PROFILE:
            payload = _payload(command, wire.CreateVoiceProfileRequest)
            if payload.novel_id != command.novel_id:
                raise NarrationScopeMismatch("profile payload and command scope disagree")
            if self.profile_creation_receipts is None:
                raise NarrationApiFault(
                    wire.NarrationErrorCode.STORAGE_UNAVAILABLE,
                    "音色档案幂等回执存储尚未接线。",
                    retryable=False,
                )
            return create_voice_profile(
                self.store,
                payload,
                idempotency_key=_required_idempotency_key(command.idempotency_key),
                receipt_port=self.profile_creation_receipts,
            )
        if operation is NarrationSettingsOperation.GET_VOICE_PROFILE:
            return get_voice_profile(self.store, _required_uuid(command.profile_id, "profile_id"))
        if operation is NarrationSettingsOperation.PUT_VOICE_PROFILE:
            return update_voice_profile(
                self.store,
                _required_uuid(command.profile_id, "profile_id"),
                _payload(command, wire.UpdateVoiceProfileRequest),
            )
        if operation is NarrationSettingsOperation.ARCHIVE_VOICE_PROFILE:
            expected_version = command.expected_version
            if type(expected_version) is not int or expected_version < 1:
                raise NarrationServiceError("expected_version must be a positive integer")
            return archive_voice_profile(
                self.store,
                _required_uuid(command.profile_id, "profile_id"),
                expected_version=expected_version,
            )
        if operation is NarrationSettingsOperation.CREATE_PRESET_VOICE_VERSION:
            payload = _payload(command, wire.CreatePresetVoiceVersionRequest)
            profile_id = _required_uuid(command.profile_id, "profile_id")
            key = _required_idempotency_key(command.idempotency_key)
            require_official_preset(payload.preset_id)
            if self.voice_product is not None:
                return self.voice_product.create_preset_version(
                    profile_id=profile_id,
                    request=payload,
                    idempotency_key=key,
                )
            profile = _required_profile(self.store, profile_id)
            if profile.version != payload.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            raise _source_unavailable(wire.VoiceSourceType.PRESET)
        if operation is NarrationSettingsOperation.CREATE_UPLOADED_VOICE_VERSION:
            # Parse every byte and declaration before querying or writing any
            # persistent row.  The approved-source gate is checked afterwards;
            # it remains closed in T2-D.
            parsed = parse_uploaded_voice_multipart(
                command.multipart_content_type,
                command.multipart_body,
            )
            key = _required_idempotency_key(command.idempotency_key)
            if self.voice_product is not None:
                return self.voice_product.create_uploaded_version(
                    profile_id=_required_uuid(command.profile_id, "profile_id"),
                    parsed=parsed,
                    idempotency_key=key,
                )
            profile = _required_profile(
                self.store,
                _required_uuid(command.profile_id, "profile_id"),
            )
            if profile.version != parsed.metadata.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            raise _source_unavailable(wire.VoiceSourceType.UPLOADED)
        if operation is NarrationSettingsOperation.CREATE_VOICE_PREVIEW:
            payload = _payload(command, wire.CreateVoicePreviewRequest)
            key = _required_idempotency_key(command.idempotency_key)
            if self.voice_product is not None:
                return self.voice_product.create_preview(
                    profile_id=_required_uuid(command.profile_id, "profile_id"),
                    request=payload,
                    idempotency_key=key,
                )
            return create_unavailable_voice_preview(
                self.store,
                _required_uuid(command.profile_id, "profile_id"),
                payload,
                idempotency_key=key,
            )
        if operation is NarrationSettingsOperation.GET_VOICE_PREVIEW:
            preview_id = _required_uuid(command.preview_id, "preview_id")
            if self.voice_product is not None:
                return self.voice_product.get_preview(preview_id=preview_id)
            raise NarrationApiFault(
                wire.NarrationErrorCode.PREVIEW_UNAVAILABLE,
                "试听状态存储尚未通过后续产品门禁接线。",
                retryable=False,
                capability=wire.CapabilityKey.VOICE_PREVIEW,
            )
        if operation is NarrationSettingsOperation.LOCK_VOICE_PROFILE:
            payload = _payload(command, wire.LockVoiceProfileRequest)
            profile_id = _required_uuid(command.profile_id, "profile_id")
            if self.voice_product is not None:
                return self.voice_product.lock_profile(
                    profile_id=profile_id,
                    request=payload,
                )
            version_id = _required_uuid(payload.version_id, "version_id")

            # LOCK_VOICE_PROFILE shares one global authority order with script
            # review/production: version -> profile -> rights -> rights event.
            # Do not validate the cross-row relation until both leading rows
            # are locked; otherwise another route can enter the reverse
            # Profile -> Version order and deadlock with review approval.
            version = self.store.get(
                VoiceProfileVersion,
                version_id,
                for_update=True,
            )
            if version is None:
                raise VoiceVersionNotFound("voice version not found")
            profile = self.store.get(VoiceProfile, profile_id, for_update=True)
            if profile is None:
                raise VoiceProfileNotFound("voice profile not found")
            if (
                profile.owner_id != LOCAL_OWNER_ID
                or profile.workspace_id != LOCAL_WORKSPACE_ID
                or version.owner_id != LOCAL_OWNER_ID
                or version.workspace_id != LOCAL_WORKSPACE_ID
                or version.profile_id != profile.id
            ):
                raise NarrationScopeMismatch(
                    "voice version belongs to another profile or scope"
                )
            if profile.version != payload.expected_profile_version:
                raise NarrationCasConflict("voice profile version changed")
            _require_rights_available(self.store, profile, version, now=utc_now())
            # Every source remains unapproved at the T2-D gate.  No version or
            # profile field is mutated before this terminal check.
            raise _source_unavailable(wire.VoiceSourceType(version.source_type))
        raise AssertionError("unreachable T2-D operation")


def _payload(
    command: NarrationSettingsApiCommand,
    model: type[_PayloadModel],
) -> _PayloadModel:
    if not isinstance(command.payload, model):
        raise NarrationServiceError("command payload does not match its operation")
    return command.payload


def _required_uuid(value: UUID | None, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise NarrationServiceError(f"{field_name} must be a UUID")
    return value


__all__ = [
    "ParsedUploadedVoice",
    "VOICE_SETTINGS_OPERATIONS",
    "VoiceProfileCreationReceipt",
    "VoiceProfileCreationReceiptPort",
    "VoiceProductPort",
    "OfficialVoiceSelectionPort",
    "VoiceProfileNotFound",
    "VoiceSettingsHandler",
    "VoiceUploadValidationError",
    "VoiceVersionNotFound",
    "archive_voice_profile",
    "create_unavailable_voice_preview",
    "create_voice_profile",
    "get_voice_profile",
    "list_voice_profiles",
    "parse_uploaded_voice_multipart",
    "update_voice_profile",
    "voice_profile_resource",
]
