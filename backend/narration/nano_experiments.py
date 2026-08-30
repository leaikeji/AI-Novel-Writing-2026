"""Database-independent orchestration for validated Nano voice experiments.

The public HTTP DTOs and SQLAlchemy mappings intentionally live elsewhere.
This module freezes the domain invariants needed by both adapters:

* all advanced sampling inputs are exact integers and always use ``full/375``;
* request, parameter and reusable-version identities are deterministic;
* synthesis and validation happen outside database transactions;
* a successful Binder owns one short atomic transaction covering the validated
  Voice Version, command terminal state and target CAS binding;
* failures never invoke the Binder and therefore cannot change an existing
  narrator or character binding.

The repository, synthesizer, validator and Binder are Protocols so the
SQLAlchemy/background-job integration can be added without moving these rules
into HTTP handlers or duplicating them in a worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import io
import json
import re
from types import MappingProxyType
from typing import Final, Literal, Mapping, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5
import wave

from .audio_pipeline import (
    AudioPipelineError,
    audio_processing_fingerprint,
    validate_synthesis_duration_for_text,
)
from .contracts import NanoDecodeParametersV2, PRODUCTION_NANO_MAX_SEED
from .jobs import JobLease
from .official_presets import (
    OFFICIAL_PRESET_MANIFEST_PATH,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESET_RIGHTS_POLICY_VERSION,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    require_official_preset,
    validate_official_preset_provenance,
)
from .runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT, PROTOCOL_VERSION


NANO_DECODE_PARAMETERS_V3: Final = "nano-decode-parameters/3"
NANO_EXPERIMENT_REQUEST_SCHEMA_VERSION: Final = (
    "nano-voice-experiment-request/1"
)
NANO_EXPERIMENT_COMMAND_SCHEMA_VERSION: Final = "nano-voice-experiment/1"
NANO_EXPERIMENT_PARAMETERS_DIGEST_VERSION: Final = (
    "nano-experiment-parameters-digest/1"
)
NANO_EXPERIMENT_FINGERPRINT_VERSION: Final = "nano-experiment-fingerprint/1"
NANO_EXPERIMENT_PROFILE_IDENTITY_VERSION: Final = "nano-experiment-profile/1"
NANO_EXPERIMENT_COMMAND_IDENTITY_VERSION: Final = "nano-experiment-command/1"
NANO_EXPERIMENT_VALIDATION_INPUT_VERSION: Final = (
    "nano-experiment-validation-input/1"
)
NANO_EXPERIMENT_VALIDATION_TEXT: Final = "这是一次音色参数验证。"
NANO_EXPERIMENT_SAMPLE_MODE: Final = "full"
NANO_EXPERIMENT_MAX_NEW_FRAMES: Final = 375

NANO_EXPERIMENT_FAILURE_CODES: Final[frozenset[str]] = frozenset(
    {
        "NANO_EXPERIMENT_MODEL_UNAVAILABLE",
        "NANO_EXPERIMENT_SYNTHESIS_FAILED",
        "NANO_EXPERIMENT_AUDIO_INVALID",
        "NANO_EXPERIMENT_MODEL_IDENTITY_MISMATCH",
        "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
        "NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH",
        "NANO_EXPERIMENT_DATABASE_FAILED",
    }
)

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_DIGEST_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class NanoExperimentError(RuntimeError):
    """Stable, redacted domain failure suitable for a persisted command."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        if code not in NANO_EXPERIMENT_FAILURE_CODES:
            raise ValueError("unknown Nano experiment failure code")
        if type(retryable) is not bool:
            raise TypeError("retryable must be an exact boolean")
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class NanoExperimentContractError(ValueError):
    """A caller supplied a value outside the frozen experiment contract."""


class NanoExperimentIdempotencyConflict(NanoExperimentContractError):
    """One idempotency key names two different canonical requests."""


class NanoExperimentStateError(NanoExperimentContractError):
    """A command attempted a transition outside the monotonic state graph."""


class NanoExperimentTargetKind(str):
    NARRATOR: Final = "narrator"
    CHARACTER: Final = "character"


NanoExperimentState = Literal[
    "pending",
    "running",
    "ready_applied",
    "ready_unapplied",
    "failed",
]
NanoExperimentWorkerStatus = Literal[
    "succeeded",
    "failed",
    "retry_wait",
    "dead_letter",
    "stale",
]

_ALLOWED_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "pending": frozenset({"running"}),
        "running": frozenset(
            {"ready_applied", "ready_unapplied", "failed"}
        ),
        "ready_unapplied": frozenset({"ready_applied"}),
        "ready_applied": frozenset(),
        "failed": frozenset(),
    }
)


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise NanoExperimentContractError(
            "Nano experiment identity is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _required_sha256(value: str, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise NanoExperimentContractError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _required_digest_key_id(value: str, *, field_name: str) -> str:
    if type(value) is not str or _DIGEST_KEY_ID.fullmatch(value) is None:
        raise NanoExperimentContractError(
            f"{field_name} must use the persisted digest-key format"
        )
    return value


def _required_text(value: str, *, field_name: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise NanoExperimentContractError(f"{field_name} is invalid")
    return value


def _required_uuid(value: UUID, *, field_name: str) -> UUID:
    if type(value) is not UUID:
        raise NanoExperimentContractError(f"{field_name} must be a UUID")
    return value


def _required_nonnegative_version(value: int, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise NanoExperimentContractError(
            f"{field_name} must be an exact non-negative integer"
        )
    return value


def _canonical_preview_path(asset_id: UUID, digest: str) -> str:
    _required_uuid(asset_id, field_name="result_asset_id")
    _required_sha256(digest, field_name="output_sha256")
    return f"assets/{asset_id.hex[:2]}/{asset_id.hex}/{digest}.wav"


def require_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise NanoExperimentContractError(
            "Nano experiment idempotency key is outside the frozen format"
        )
    return value


def ensure_idempotent_request(
    *, stored_request_digest: str, incoming_request_digest: str
) -> None:
    """Reject a same-key replay whose complete canonical request changed."""

    stored = _required_sha256(
        stored_request_digest, field_name="stored_request_digest"
    )
    incoming = _required_sha256(
        incoming_request_digest, field_name="incoming_request_digest"
    )
    if stored != incoming:
        raise NanoExperimentIdempotencyConflict(
            "Nano experiment idempotency key names another request"
        )


def ensure_state_transition(current: str, target: str) -> None:
    try:
        allowed = _ALLOWED_TRANSITIONS[current]
    except KeyError as error:
        raise NanoExperimentStateError(
            "Nano experiment current state is invalid"
        ) from error
    if target not in allowed:
        raise NanoExperimentStateError(
            f"Nano experiment cannot transition from {current} to {target}"
        )


@dataclass(frozen=True, slots=True)
class NanoDecodeParametersV3:
    """Canonical author-visible advanced parameters.

    The Sidecar currently consumes the seven fractional/top-k fields through
    its v2 decode object; ``seed``, ``full`` and ``375`` remain top-level
    synthesis inputs.  This v3 object is the complete persisted/public identity
    and prevents either layer from silently changing those fixed values.
    """

    seed: int = 1_234
    text_temperature_milli: int = 1_000
    text_top_p_milli: int = 1_000
    text_top_k: int = 50
    audio_temperature_milli: int = 800
    audio_top_p_milli: int = 950
    audio_top_k: int = 25
    audio_repetition_penalty_milli: int = 1_200
    sample_mode: str = NANO_EXPERIMENT_SAMPLE_MODE
    max_new_frames: int = NANO_EXPERIMENT_MAX_NEW_FRAMES
    schema_version: str = NANO_DECODE_PARAMETERS_V3

    def __post_init__(self) -> None:
        if self.schema_version != NANO_DECODE_PARAMETERS_V3:
            raise NanoExperimentContractError(
                "unknown Nano experiment parameter contract"
            )
        if type(self.seed) is not int or not 0 <= self.seed <= PRODUCTION_NANO_MAX_SEED:
            raise NanoExperimentContractError(
                "seed is outside the Nano experiment bound"
            )
        integer_bounds = {
            "text_temperature_milli": (100, 2_000),
            "text_top_p_milli": (1, 1_000),
            "text_top_k": (1, 100),
            "audio_temperature_milli": (100, 2_000),
            "audio_top_p_milli": (1, 1_000),
            "audio_top_k": (1, 100),
            "audio_repetition_penalty_milli": (1_000, 2_000),
        }
        for field_name, (minimum, maximum) in integer_bounds.items():
            value = getattr(self, field_name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise NanoExperimentContractError(
                    f"{field_name} is outside the Nano experiment bound"
                )
        if self.sample_mode != NANO_EXPERIMENT_SAMPLE_MODE:
            raise NanoExperimentContractError(
                "Nano experiments require sample_mode=full"
            )
        if (
            type(self.max_new_frames) is not int
            or self.max_new_frames != NANO_EXPERIMENT_MAX_NEW_FRAMES
        ):
            raise NanoExperimentContractError(
                "Nano experiments require max_new_frames=375"
            )

    def canonical_payload(self) -> Mapping[str, str | int]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "seed": self.seed,
                "text_temperature_milli": self.text_temperature_milli,
                "text_top_p_milli": self.text_top_p_milli,
                "text_top_k": self.text_top_k,
                "audio_temperature_milli": self.audio_temperature_milli,
                "audio_top_p_milli": self.audio_top_p_milli,
                "audio_top_k": self.audio_top_k,
                "audio_repetition_penalty_milli": (
                    self.audio_repetition_penalty_milli
                ),
                "sample_mode": self.sample_mode,
                "max_new_frames": self.max_new_frames,
            }
        )

    def sidecar_decode_parameters(self) -> NanoDecodeParametersV2:
        return NanoDecodeParametersV2(
            text_temperature_milli=self.text_temperature_milli,
            text_top_p_milli=self.text_top_p_milli,
            text_top_k=self.text_top_k,
            audio_temperature_milli=self.audio_temperature_milli,
            audio_top_p_milli=self.audio_top_p_milli,
            audio_top_k=self.audio_top_k,
            audio_repetition_penalty_milli=(
                self.audio_repetition_penalty_milli
            ),
        )

    @classmethod
    def from_payload(cls, value: object) -> "NanoDecodeParametersV3":
        expected = {
            "schema_version",
            "seed",
            "text_temperature_milli",
            "text_top_p_milli",
            "text_top_k",
            "audio_temperature_milli",
            "audio_top_p_milli",
            "audio_top_k",
            "audio_repetition_penalty_milli",
            "sample_mode",
            "max_new_frames",
        }
        if type(value) is not dict or set(value) != expected:
            raise NanoExperimentContractError(
                "Nano experiment parameter shape is invalid"
            )
        return cls(**value)  # type: ignore[arg-type]


def nano_parameters_digest(parameters: NanoDecodeParametersV3) -> str:
    if type(parameters) is not NanoDecodeParametersV3:
        raise NanoExperimentContractError(
            "parameters must use nano-decode-parameters/3"
        )
    return _canonical_sha256(
        {
            "schema_version": NANO_EXPERIMENT_PARAMETERS_DIGEST_VERSION,
            "parameters": dict(parameters.canonical_payload()),
        }
    )


@dataclass(frozen=True, slots=True)
class NanoExperimentModelIdentity:
    requested_provider_id: str | None
    requested_model_id: str
    requested_revision: str
    actual_provider_id: str | None
    actual_model_id: str
    actual_revision: str
    model_fingerprint_sha256: str
    sidecar_protocol_version: str
    postprocess_fingerprint: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.requested_model_id, "requested_model_id"),
            (self.requested_revision, "requested_revision"),
            (self.actual_model_id, "actual_model_id"),
            (self.actual_revision, "actual_revision"),
            (self.sidecar_protocol_version, "sidecar_protocol_version"),
        ):
            _required_text(value, field_name=field_name, maximum=240)
        for value, field_name in (
            (self.requested_provider_id, "requested_provider_id"),
            (self.actual_provider_id, "actual_provider_id"),
        ):
            if value is not None:
                _required_text(value, field_name=field_name, maximum=160)
        _required_sha256(
            self.model_fingerprint_sha256,
            field_name="model_fingerprint_sha256",
        )
        _required_sha256(
            self.postprocess_fingerprint,
            field_name="postprocess_fingerprint",
        )

    def canonical_payload(self) -> Mapping[str, str | None]:
        return MappingProxyType(
            {
                "requested_provider_id": self.requested_provider_id,
                "requested_model_id": self.requested_model_id,
                "requested_revision": self.requested_revision,
                "actual_provider_id": self.actual_provider_id,
                "actual_model_id": self.actual_model_id,
                "actual_revision": self.actual_revision,
                "model_fingerprint_sha256": self.model_fingerprint_sha256,
                "sidecar_protocol_version": self.sidecar_protocol_version,
                "postprocess_fingerprint": self.postprocess_fingerprint,
            }
        )


def production_nano_experiment_identity() -> NanoExperimentModelIdentity:
    """Return the pinned identity already enforced by the production Sidecar."""

    return NanoExperimentModelIdentity(
        requested_provider_id="local-sidecar",
        requested_model_id=EXPECTED_PRODUCTION_MODEL_FINGERPRINT.model_name,
        requested_revision=EXPECTED_PRODUCTION_MODEL_FINGERPRINT.model_revision,
        actual_provider_id="local-sidecar",
        actual_model_id=EXPECTED_PRODUCTION_MODEL_FINGERPRINT.model_name,
        actual_revision=EXPECTED_PRODUCTION_MODEL_FINGERPRINT.model_revision,
        model_fingerprint_sha256=OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
        sidecar_protocol_version=PROTOCOL_VERSION,
        postprocess_fingerprint=audio_processing_fingerprint(),
    )


def validate_nano_experiment_version_evidence(
    version: object,
    rights: object,
    *,
    expected_model_fingerprint: str,
) -> object:
    """Validate the generated-but-official-base machine-validated voice shape.

    Cross-row command/Preview/ModelRun equality remains enforced by migration
    ``0034``.  This structural check is deliberately usable from the shared
    settings and projection layers without importing SQLAlchemy models.
    """

    if expected_model_fingerprint != OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256:
        raise ValueError("Nano experiment model fingerprint changed")
    parameters = getattr(version, "parameters_json", None)
    if type(parameters) is not dict or set(parameters) != {
        "schema_version",
        "official_preset",
        "sample_mode",
        "max_new_frames",
        "decode_parameters",
    }:
        raise ValueError("Nano experiment version parameters are malformed")
    if (
        parameters.get("schema_version")
        != "narration-nano-experiment-version/1"
        or parameters.get("sample_mode") != NANO_EXPERIMENT_SAMPLE_MODE
        or parameters.get("max_new_frames") != NANO_EXPERIMENT_MAX_NEW_FRAMES
    ):
        raise ValueError("Nano experiment fixed parameters changed")
    decode = NanoDecodeParametersV3.from_payload(parameters.get("decode_parameters"))
    preset = validate_official_preset_provenance(parameters.get("official_preset"))
    if (
        getattr(version, "source_type", None) != "generated"
        or getattr(version, "provider_id", None) != "local-sidecar"
        or getattr(version, "model_id", None) != OFFICIAL_PRESET_REPOSITORY
        or getattr(version, "model_revision", None) != OFFICIAL_PRESET_REVISION
        or getattr(version, "preset_key", None) != preset.preset_id
        or getattr(version, "reference_asset_id", None) is not None
        or getattr(version, "language", None) != preset.language
        or getattr(version, "seed", None) != decode.seed
        or getattr(version, "state", None) != "locked"
        or getattr(version, "quality_state", None) != "accepted"
        or getattr(version, "activation_basis", None)
        != "experimental_machine_validated"
        or getattr(version, "validation_basis", None) != "machine_validated"
        or getattr(version, "model_run_id", None) is None
        or getattr(version, "locked_actor", None) is not None
        or getattr(version, "locked_at", None) is not None
        or type(getattr(version, "fingerprint", None)) is not str
        or _SHA256.fullmatch(getattr(version, "fingerprint", "")) is None
    ):
        raise ValueError("Nano experiment version evidence changed")
    expected_source_identifier = (
        f"hf://{OFFICIAL_PRESET_REPOSITORY}@{OFFICIAL_PRESET_REVISION}/"
        f"{OFFICIAL_PRESET_MANIFEST_PATH}#{preset.preset_id}"
    )
    if (
        getattr(rights, "source_kind", None) != "official_preset"
        or getattr(rights, "source_identifier", None) != expected_source_identifier
        or getattr(rights, "notice_version", None)
        != OFFICIAL_PRESET_RIGHTS_POLICY_VERSION
        or getattr(rights, "purpose", None) != "private_novel_narration"
        or getattr(rights, "commercial_use", None) is not False
        or getattr(rights, "redistribution", None) is not False
        or getattr(rights, "voice_cloning", None) is not False
        or getattr(rights, "subject_consent_reference", None) is not None
        or getattr(rights, "expires_at", None) is not None
        or getattr(rights, "risk_flags_json", None)
        != ["COMMERCIAL_DISTRIBUTION_NOT_EVALUATED"]
        or type(getattr(rights, "confirmed_actor", None)) is not str
        or not getattr(rights, "confirmed_actor", "")
        or not isinstance(getattr(rights, "confirmed_at", None), datetime)
        or getattr(rights, "owner_id", None) != getattr(version, "owner_id", None)
        or getattr(rights, "workspace_id", None)
        != getattr(version, "workspace_id", None)
    ):
        raise ValueError("Nano experiment rights evidence changed")
    return preset


@dataclass(frozen=True, slots=True)
class NanoExperimentValidationInput:
    text: str = field(repr=False)
    input_digest_key_id: str
    input_digest: str
    schema_version: str = NANO_EXPERIMENT_VALIDATION_INPUT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != NANO_EXPERIMENT_VALIDATION_INPUT_VERSION:
            raise NanoExperimentContractError(
                "unknown Nano experiment validation input contract"
            )
        _required_text(self.text, field_name="validation text", maximum=500)
        _required_digest_key_id(
            self.input_digest_key_id, field_name="input_digest_key_id"
        )
        _required_sha256(self.input_digest, field_name="input_digest")


@dataclass(frozen=True, slots=True)
class NanoExperimentTarget:
    target_kind: Literal["narrator", "character"]
    character_id: UUID | None
    expected_settings_version: int
    expected_binding_version: int | None

    def __post_init__(self) -> None:
        if self.target_kind not in {
            NanoExperimentTargetKind.NARRATOR,
            NanoExperimentTargetKind.CHARACTER,
        }:
            raise NanoExperimentContractError(
                "Nano experiment target_kind is invalid"
            )
        _required_nonnegative_version(
            self.expected_settings_version,
            field_name="expected_settings_version",
        )
        if self.target_kind == NanoExperimentTargetKind.NARRATOR:
            if self.character_id is not None or self.expected_binding_version is not None:
                raise NanoExperimentContractError(
                    "narrator target cannot include character fields"
                )
            return
        if type(self.character_id) is not UUID:
            raise NanoExperimentContractError(
                "character target requires character_id"
            )
        if self.expected_binding_version is None:
            raise NanoExperimentContractError(
                "character target requires expected_binding_version"
            )
        _required_nonnegative_version(
            self.expected_binding_version,
            field_name="expected_binding_version",
        )

    def canonical_payload(self) -> Mapping[str, str | int | None]:
        return MappingProxyType(
            {
                "target_kind": self.target_kind,
                "character_id": (
                    str(self.character_id) if self.character_id is not None else None
                ),
                "expected_settings_version": self.expected_settings_version,
                "expected_binding_version": self.expected_binding_version,
            }
        )


@dataclass(frozen=True, slots=True)
class NanoExperimentIntent:
    command_id: UUID
    novel_id: UUID
    profile_id: UUID
    base_preset_id: str
    target: NanoExperimentTarget
    parameters: NanoDecodeParametersV3
    parameters_digest: str
    fingerprint: str
    request_digest: str
    validation_input: NanoExperimentValidationInput = field(repr=False)
    model_identity: NanoExperimentModelIdentity

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.command_id, "command_id"),
            (self.novel_id, "novel_id"),
            (self.profile_id, "profile_id"),
        ):
            _required_uuid(value, field_name=field_name)
        try:
            preset = require_official_preset(self.base_preset_id)
        except ValueError as error:
            raise NanoExperimentContractError(
                "Nano experiment base preset is not in the fixed catalog"
            ) from error
        if preset.preset_id != self.base_preset_id:
            raise NanoExperimentContractError(
                "Nano experiment base preset identity changed"
            )
        if type(self.target) is not NanoExperimentTarget:
            raise NanoExperimentContractError("Nano experiment target is invalid")
        if type(self.parameters) is not NanoDecodeParametersV3:
            raise NanoExperimentContractError("Nano experiment parameters are invalid")
        if type(self.validation_input) is not NanoExperimentValidationInput:
            raise NanoExperimentContractError(
                "Nano experiment validation input is invalid"
            )
        if type(self.model_identity) is not NanoExperimentModelIdentity:
            raise NanoExperimentContractError(
                "Nano experiment model identity is invalid"
            )
        _required_sha256(self.parameters_digest, field_name="parameters_digest")
        _required_sha256(self.fingerprint, field_name="fingerprint")
        _required_sha256(self.request_digest, field_name="request_digest")
        if self.parameters_digest != nano_parameters_digest(self.parameters):
            raise NanoExperimentContractError(
                "Nano experiment parameters digest changed"
            )
        expected_fingerprint = nano_experiment_fingerprint(
            novel_id=self.novel_id,
            base_preset_id=self.base_preset_id,
            parameters=self.parameters,
            validation_input=self.validation_input,
            model_identity=self.model_identity,
        )
        if self.fingerprint != expected_fingerprint:
            raise NanoExperimentContractError(
                "Nano experiment complete fingerprint changed"
            )
        expected_request_digest = _canonical_sha256(
            {
                "schema_version": NANO_EXPERIMENT_REQUEST_SCHEMA_VERSION,
                "novel_id": str(self.novel_id),
                "base_preset_id": self.base_preset_id,
                "target": dict(self.target.canonical_payload()),
                "parameters": dict(self.parameters.canonical_payload()),
                "parameters_digest": self.parameters_digest,
                "fingerprint": self.fingerprint,
            }
        )
        if self.request_digest != expected_request_digest:
            raise NanoExperimentContractError(
                "Nano experiment canonical request digest changed"
            )
        if self.profile_id != nano_experiment_profile_id(
            novel_id=self.novel_id, base_preset_id=self.base_preset_id
        ):
            raise NanoExperimentContractError(
                "Nano experiment profile identity changed"
            )


def nano_experiment_profile_id(
    *, novel_id: UUID, base_preset_id: str
) -> UUID:
    _required_uuid(novel_id, field_name="novel_id")
    try:
        preset = require_official_preset(base_preset_id)
    except ValueError as error:
        raise NanoExperimentContractError(
            "Nano experiment base preset is not in the fixed catalog"
        ) from error
    return uuid5(
        NAMESPACE_URL,
        f"{NANO_EXPERIMENT_PROFILE_IDENTITY_VERSION}:{novel_id}:{preset.preset_id}",
    )


def nano_experiment_command_id(*, novel_id: UUID, idempotency_key: str) -> UUID:
    _required_uuid(novel_id, field_name="novel_id")
    key = require_idempotency_key(idempotency_key)
    return uuid5(
        NAMESPACE_URL,
        f"{NANO_EXPERIMENT_COMMAND_IDENTITY_VERSION}:{novel_id}:{key}",
    )


def nano_experiment_fingerprint(
    *,
    novel_id: UUID,
    base_preset_id: str,
    parameters: NanoDecodeParametersV3,
    validation_input: NanoExperimentValidationInput,
    model_identity: NanoExperimentModelIdentity,
) -> str:
    _required_uuid(novel_id, field_name="novel_id")
    try:
        preset = require_official_preset(base_preset_id)
    except ValueError as error:
        raise NanoExperimentContractError(
            "Nano experiment base preset is not in the fixed catalog"
        ) from error
    if type(parameters) is not NanoDecodeParametersV3:
        raise NanoExperimentContractError(
            "parameters must use nano-decode-parameters/3"
        )
    if type(validation_input) is not NanoExperimentValidationInput:
        raise NanoExperimentContractError(
            "validation input is outside the frozen contract"
        )
    if type(model_identity) is not NanoExperimentModelIdentity:
        raise NanoExperimentContractError(
            "model identity is outside the frozen contract"
        )
    parameters_digest = nano_parameters_digest(parameters)
    return _canonical_sha256(
        {
            "schema_version": NANO_EXPERIMENT_FINGERPRINT_VERSION,
            # VoiceProfileVersion fingerprints are unique inside the fixed
            # owner/workspace.  Experiments are deliberately novel-scoped, so
            # this identity prevents identical tuning in two novels from
            # colliding while retaining reuse inside the one experiment
            # profile for this novel and preset.
            "novel_id": str(novel_id),
            "base_preset_id": preset.preset_id,
            "model_identity": dict(model_identity.canonical_payload()),
            "parameters": dict(parameters.canonical_payload()),
            "parameters_digest": parameters_digest,
            "validation_input": {
                "schema_version": validation_input.schema_version,
                "input_digest_key_id": validation_input.input_digest_key_id,
                "input_digest": validation_input.input_digest,
            },
        }
    )


def build_nano_experiment_intent(
    *,
    novel_id: UUID,
    base_preset_id: str,
    target: NanoExperimentTarget,
    parameters: NanoDecodeParametersV3,
    validation_input: NanoExperimentValidationInput,
    model_identity: NanoExperimentModelIdentity,
    idempotency_key: str,
) -> NanoExperimentIntent:
    key = require_idempotency_key(idempotency_key)
    profile_id = nano_experiment_profile_id(
        novel_id=novel_id, base_preset_id=base_preset_id
    )
    parameters_digest = nano_parameters_digest(parameters)
    fingerprint = nano_experiment_fingerprint(
        novel_id=novel_id,
        base_preset_id=base_preset_id,
        parameters=parameters,
        validation_input=validation_input,
        model_identity=model_identity,
    )
    request_digest = _canonical_sha256(
        {
            "schema_version": NANO_EXPERIMENT_REQUEST_SCHEMA_VERSION,
            "novel_id": str(novel_id),
            "base_preset_id": base_preset_id,
            "target": dict(target.canonical_payload()),
            "parameters": dict(parameters.canonical_payload()),
            "parameters_digest": parameters_digest,
            "fingerprint": fingerprint,
        }
    )
    return NanoExperimentIntent(
        command_id=nano_experiment_command_id(
            novel_id=novel_id, idempotency_key=key
        ),
        novel_id=novel_id,
        profile_id=profile_id,
        base_preset_id=base_preset_id,
        target=target,
        parameters=parameters,
        parameters_digest=parameters_digest,
        fingerprint=fingerprint,
        request_digest=request_digest,
        validation_input=validation_input,
        model_identity=model_identity,
    )


@dataclass(frozen=True, slots=True)
class NanoExperimentCommand:
    command_id: UUID
    novel_id: UUID
    profile_id: UUID
    version_id: UUID
    preview_id: UUID
    background_job_id: UUID
    base_preset_id: str
    target: NanoExperimentTarget
    parameters: NanoDecodeParametersV3
    parameters_digest: str
    fingerprint: str
    request_digest: str
    state: NanoExperimentState
    reused_version: bool
    failure_code: str | None
    retryable: bool
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.command_id, "command_id"),
            (self.novel_id, "novel_id"),
            (self.profile_id, "profile_id"),
            (self.version_id, "version_id"),
            (self.preview_id, "preview_id"),
            (self.background_job_id, "background_job_id"),
        ):
            _required_uuid(value, field_name=field_name)
        try:
            preset = require_official_preset(self.base_preset_id)
        except ValueError as error:
            raise NanoExperimentContractError(
                "Nano experiment command preset is not in the fixed catalog"
            ) from error
        if preset.preset_id != self.base_preset_id:
            raise NanoExperimentContractError(
                "Nano experiment command preset identity changed"
            )
        if type(self.target) is not NanoExperimentTarget:
            raise NanoExperimentContractError(
                "Nano experiment command target is invalid"
            )
        if type(self.parameters) is not NanoDecodeParametersV3:
            raise NanoExperimentContractError(
                "Nano experiment command parameters are invalid"
            )
        if self.profile_id != nano_experiment_profile_id(
            novel_id=self.novel_id,
            base_preset_id=self.base_preset_id,
        ):
            raise NanoExperimentContractError(
                "Nano experiment command profile identity changed"
            )
        if self.state not in _ALLOWED_TRANSITIONS:
            raise NanoExperimentStateError("Nano experiment state is invalid")
        if type(self.reused_version) is not bool or type(self.retryable) is not bool:
            raise NanoExperimentContractError(
                "Nano experiment flags must be exact booleans"
            )
        for value, field_name in (
            (self.parameters_digest, "parameters_digest"),
            (self.fingerprint, "fingerprint"),
            (self.request_digest, "request_digest"),
        ):
            _required_sha256(value, field_name=field_name)
        if self.parameters_digest != nano_parameters_digest(self.parameters):
            raise NanoExperimentContractError(
                "Nano experiment command parameters digest changed"
            )
        if type(self.created_at) is not datetime or self.created_at.tzinfo is None:
            raise NanoExperimentContractError("created_at must be timezone-aware")
        if self.started_at is not None and (
            type(self.started_at) is not datetime or self.started_at.tzinfo is None
        ):
            raise NanoExperimentContractError("started_at must be timezone-aware")
        if self.completed_at is not None and (
            type(self.completed_at) is not datetime or self.completed_at.tzinfo is None
        ):
            raise NanoExperimentContractError("completed_at must be timezone-aware")
        if self.started_at is not None and self.started_at < self.created_at:
            raise NanoExperimentStateError(
                "Nano experiment started_at precedes created_at"
            )
        if self.completed_at is not None and (
            self.started_at is None or self.completed_at < self.started_at
        ):
            raise NanoExperimentStateError(
                "Nano experiment completed_at precedes started_at"
            )
        if self.state == "pending":
            if (
                self.started_at is not None
                or self.completed_at is not None
                or self.failure_code is not None
                or self.retryable
                or self.reused_version
            ):
                raise NanoExperimentStateError("pending command evidence is invalid")
        elif self.state == "running":
            if (
                self.started_at is None
                or self.completed_at is not None
                or self.failure_code is not None
                or self.retryable
                or self.reused_version
            ):
                raise NanoExperimentStateError("running command evidence is invalid")
        elif self.state in {"ready_applied", "ready_unapplied"}:
            if (
                self.started_at is None
                or self.completed_at is None
                or self.failure_code is not None
                or self.retryable
            ):
                raise NanoExperimentStateError("ready command evidence is invalid")
        else:
            if (
                self.started_at is None
                or self.completed_at is None
                or self.failure_code not in NANO_EXPERIMENT_FAILURE_CODES
            ):
                raise NanoExperimentStateError("failed command evidence is invalid")
        if self.state != "failed" and self.failure_code is not None:
            raise NanoExperimentStateError(
                "only a failed command may carry failure_code"
            )


@dataclass(frozen=True, slots=True)
class NanoReusableVersion:
    version_id: UUID
    profile_id: UUID
    model_run_id: UUID
    preview_id: UUID
    result_asset_id: UUID
    fingerprint: str
    parameters_digest: str
    model_fingerprint_sha256: str
    output_sha256: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.version_id, "version_id"),
            (self.profile_id, "profile_id"),
            (self.model_run_id, "model_run_id"),
            (self.preview_id, "preview_id"),
            (self.result_asset_id, "result_asset_id"),
        ):
            _required_uuid(value, field_name=field_name)
        for value, field_name in (
            (self.fingerprint, "fingerprint"),
            (self.parameters_digest, "parameters_digest"),
            (self.model_fingerprint_sha256, "model_fingerprint_sha256"),
            (self.output_sha256, "output_sha256"),
        ):
            _required_sha256(value, field_name=field_name)


def validate_reusable_version(
    intent: NanoExperimentIntent, reusable: NanoReusableVersion
) -> None:
    if type(intent) is not NanoExperimentIntent or type(reusable) is not NanoReusableVersion:
        raise NanoExperimentContractError("reusable version input is invalid")
    if (
        reusable.profile_id != intent.profile_id
        or reusable.fingerprint != intent.fingerprint
        or reusable.parameters_digest != intent.parameters_digest
        or reusable.model_fingerprint_sha256
        != intent.model_identity.model_fingerprint_sha256
    ):
        raise NanoExperimentError(
            "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
            "reusable Nano version does not match the complete fingerprint",
        )


@dataclass(frozen=True, slots=True)
class NanoExperimentReservation:
    command: NanoExperimentCommand
    replayed: bool
    reusable_version: NanoReusableVersion | None = None

    def __post_init__(self) -> None:
        if type(self.command) is not NanoExperimentCommand:
            raise NanoExperimentContractError("reservation command is invalid")
        if type(self.replayed) is not bool:
            raise NanoExperimentContractError("replayed must be an exact boolean")
        if self.reusable_version is not None:
            if self.command.state != "pending" or self.replayed:
                raise NanoExperimentStateError(
                    "only a new pending command can reserve version reuse"
                )
            if (
                self.command.profile_id != self.reusable_version.profile_id
                or self.command.version_id != self.reusable_version.version_id
                or self.command.preview_id != self.reusable_version.preview_id
                or self.command.fingerprint != self.reusable_version.fingerprint
                or self.command.parameters_digest
                != self.reusable_version.parameters_digest
            ):
                raise NanoExperimentContractError(
                    "reserved reusable Nano version differs from the command"
                )


@dataclass(frozen=True, slots=True)
class NanoExperimentWorkItem:
    lease: JobLease
    command: NanoExperimentCommand
    validation_input: NanoExperimentValidationInput = field(repr=False)
    model_identity: NanoExperimentModelIdentity
    model_input_digest_key_id: str
    model_input_digest: str
    reusable_version: NanoReusableVersion | None = None

    def __post_init__(self) -> None:
        if type(self.lease) is not JobLease:
            raise NanoExperimentContractError("Nano experiment lease is invalid")
        if self.command.state != "running":
            raise NanoExperimentStateError(
                "Nano experiment work item requires a running command"
            )
        if self.lease.fence.job_id != self.command.background_job_id:
            raise NanoExperimentContractError(
                "Nano experiment lease belongs to another background job"
            )
        _required_digest_key_id(
            self.model_input_digest_key_id,
            field_name="model_input_digest_key_id",
        )
        _required_sha256(
            self.model_input_digest,
            field_name="model_input_digest",
        )
        intent = _intent_from_work(self)
        if self.reusable_version is not None:
            if (
                self.command.version_id != self.reusable_version.version_id
                or self.command.preview_id != self.reusable_version.preview_id
            ):
                raise NanoExperimentContractError(
                    "reused Nano version/preview differs from the reserved command"
                )
            validate_reusable_version(
                intent, self.reusable_version
            )


def _intent_from_work(work: NanoExperimentWorkItem) -> NanoExperimentIntent:
    command = work.command
    return NanoExperimentIntent(
        command_id=command.command_id,
        novel_id=command.novel_id,
        profile_id=command.profile_id,
        base_preset_id=command.base_preset_id,
        target=command.target,
        parameters=command.parameters,
        parameters_digest=command.parameters_digest,
        fingerprint=command.fingerprint,
        request_digest=command.request_digest,
        validation_input=work.validation_input,
        model_identity=work.model_identity,
    )


@dataclass(frozen=True, slots=True)
class NanoModelRunEvidence:
    model_run_id: UUID
    attempt_id: UUID
    requested_provider_id: str | None
    requested_model_id: str
    requested_revision: str
    actual_provider_id: str | None
    actual_model_id: str
    actual_revision: str
    model_fingerprint_sha256: str
    parameters_digest: str
    input_digest_key_id: str
    input_digest: str
    output_digest: str
    result_classification: str

    def __post_init__(self) -> None:
        _required_uuid(self.model_run_id, field_name="model_run_id")
        _required_uuid(self.attempt_id, field_name="attempt_id")
        for value, field_name in (
            (self.requested_model_id, "requested_model_id"),
            (self.requested_revision, "requested_revision"),
            (self.actual_model_id, "actual_model_id"),
            (self.actual_revision, "actual_revision"),
            (self.result_classification, "result_classification"),
        ):
            _required_text(value, field_name=field_name, maximum=240)
        _required_digest_key_id(
            self.input_digest_key_id, field_name="input_digest_key_id"
        )
        for value, field_name in (
            (self.requested_provider_id, "requested_provider_id"),
            (self.actual_provider_id, "actual_provider_id"),
        ):
            if value is not None:
                _required_text(value, field_name=field_name, maximum=160)
        for value, field_name in (
            (self.model_fingerprint_sha256, "model_fingerprint_sha256"),
            (self.parameters_digest, "parameters_digest"),
            (self.input_digest, "input_digest"),
            (self.output_digest, "output_digest"),
        ):
            _required_sha256(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class NanoExperimentSynthesisRequest:
    command_id: UUID
    attempt_id: UUID
    preview_id: UUID
    base_preset_id: str
    text: str = field(repr=False)
    parameters: NanoDecodeParametersV3
    parameters_digest: str
    input_digest_key_id: str
    input_digest: str
    model_identity: NanoExperimentModelIdentity

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.command_id, "command_id"),
            (self.attempt_id, "attempt_id"),
            (self.preview_id, "preview_id"),
        ):
            _required_uuid(value, field_name=field_name)
        try:
            require_official_preset(self.base_preset_id)
        except ValueError as error:
            raise NanoExperimentContractError(
                "Nano experiment synthesis preset is invalid"
            ) from error
        _required_text(self.text, field_name="validation text", maximum=500)
        if type(self.parameters) is not NanoDecodeParametersV3:
            raise NanoExperimentContractError(
                "Nano experiment synthesis parameters are invalid"
            )
        _required_sha256(self.parameters_digest, field_name="parameters_digest")
        if self.parameters_digest != nano_parameters_digest(self.parameters):
            raise NanoExperimentContractError(
                "Nano experiment synthesis parameters digest changed"
            )
        _required_digest_key_id(
            self.input_digest_key_id, field_name="input_digest_key_id"
        )
        _required_sha256(self.input_digest, field_name="input_digest")
        if type(self.model_identity) is not NanoExperimentModelIdentity:
            raise NanoExperimentContractError(
                "Nano experiment synthesis model identity is invalid"
            )


@dataclass(frozen=True, slots=True)
class NanoExperimentSynthesisResult:
    command_id: UUID
    attempt_id: UUID
    audio_bytes: bytes = field(repr=False)
    output_sha256: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    duration_ms: int
    sidecar_protocol_version: str
    postprocess_fingerprint: str
    preview_id: UUID
    result_asset_id: UUID
    published_relative_path: str
    published_byte_size: int
    model_run: NanoModelRunEvidence

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.command_id, "command_id"),
            (self.attempt_id, "attempt_id"),
            (self.preview_id, "preview_id"),
            (self.result_asset_id, "result_asset_id"),
        ):
            _required_uuid(value, field_name=field_name)
        if type(self.audio_bytes) is not bytes:
            raise NanoExperimentContractError(
                "Nano experiment synthesis audio must be bytes"
            )
        _required_sha256(self.output_sha256, field_name="output_sha256")
        _required_text(
            self.published_relative_path,
            field_name="published_relative_path",
            maximum=1_000,
        )
        if self.published_relative_path != _canonical_preview_path(
            self.result_asset_id, self.output_sha256
        ):
            raise NanoExperimentContractError(
                "published_relative_path differs from the immutable asset identity"
            )
        if (
            type(self.published_byte_size) is not int
            or self.published_byte_size < 0
        ):
            raise NanoExperimentContractError(
                "published_byte_size must be a non-negative exact integer"
            )
        for value, field_name in (
            (self.sample_rate_hz, "sample_rate_hz"),
            (self.channels, "channels"),
            (self.sample_width_bytes, "sample_width_bytes"),
            (self.duration_ms, "duration_ms"),
        ):
            if type(value) is not int or value < 0:
                raise NanoExperimentContractError(
                    f"{field_name} must be a non-negative exact integer"
                )
        _required_text(
            self.sidecar_protocol_version,
            field_name="sidecar_protocol_version",
            maximum=120,
        )
        _required_sha256(
            self.postprocess_fingerprint,
            field_name="postprocess_fingerprint",
        )
        if type(self.model_run) is not NanoModelRunEvidence:
            raise NanoExperimentContractError("model_run evidence is invalid")


@dataclass(frozen=True, slots=True)
class NanoValidatedEvidence:
    attempt_id: UUID
    model_run_id: UUID
    preview_id: UUID
    result_asset_id: UUID
    published_relative_path: str
    published_byte_size: int
    output_sha256: str
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    parameters_digest: str
    input_digest_key_id: str
    input_digest: str
    model_fingerprint_sha256: str
    sidecar_protocol_version: str
    postprocess_fingerprint: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.attempt_id, "attempt_id"),
            (self.model_run_id, "model_run_id"),
            (self.preview_id, "preview_id"),
            (self.result_asset_id, "result_asset_id"),
        ):
            _required_uuid(value, field_name=field_name)
        for value, field_name in (
            (self.output_sha256, "output_sha256"),
            (self.parameters_digest, "parameters_digest"),
            (self.input_digest, "input_digest"),
            (self.model_fingerprint_sha256, "model_fingerprint_sha256"),
            (self.postprocess_fingerprint, "postprocess_fingerprint"),
        ):
            _required_sha256(value, field_name=field_name)
        _required_text(
            self.published_relative_path,
            field_name="published_relative_path",
            maximum=1_000,
        )
        if self.published_relative_path != _canonical_preview_path(
            self.result_asset_id, self.output_sha256
        ):
            raise NanoExperimentContractError(
                "validated publication path differs from the immutable asset identity"
            )
        if type(self.published_byte_size) is not int or self.published_byte_size <= 0:
            raise NanoExperimentContractError(
                "published_byte_size must be a positive exact integer"
            )
        _required_digest_key_id(
            self.input_digest_key_id, field_name="input_digest_key_id"
        )
        _required_text(
            self.sidecar_protocol_version,
            field_name="sidecar_protocol_version",
            maximum=120,
        )
        for value, field_name in (
            (self.duration_ms, "duration_ms"),
            (self.sample_rate_hz, "sample_rate_hz"),
            (self.channels, "channels"),
            (self.sample_width_bytes, "sample_width_bytes"),
        ):
            if type(value) is not int or value <= 0:
                raise NanoExperimentContractError(
                    f"{field_name} must be a positive exact integer"
                )


@dataclass(frozen=True, slots=True)
class NanoExperimentApplyRequest:
    expected_settings_version: int
    expected_binding_version: int | None

    def __post_init__(self) -> None:
        _required_nonnegative_version(
            self.expected_settings_version,
            field_name="expected_settings_version",
        )
        if self.expected_binding_version is not None:
            _required_nonnegative_version(
                self.expected_binding_version,
                field_name="expected_binding_version",
            )

    def validate_for(self, target: NanoExperimentTarget) -> None:
        if target.target_kind == NanoExperimentTargetKind.NARRATOR:
            if self.expected_binding_version is not None:
                raise NanoExperimentContractError(
                    "narrator apply cannot include expected_binding_version"
                )
        elif self.expected_binding_version is None:
            raise NanoExperimentContractError(
                "character apply requires expected_binding_version"
            )


@dataclass(frozen=True, slots=True)
class NanoExperimentFailure:
    code: str
    retryable: bool

    def __post_init__(self) -> None:
        if self.code not in NANO_EXPERIMENT_FAILURE_CODES:
            raise NanoExperimentContractError(
                "Nano experiment failure code is invalid"
            )
        if type(self.retryable) is not bool:
            raise NanoExperimentContractError(
                "Nano experiment retryable flag is invalid"
            )


@dataclass(frozen=True, slots=True)
class NanoExperimentWorkerOutcome:
    status: NanoExperimentWorkerStatus
    job_id: UUID
    command_id: UUID | None = None
    failure_code: str | None = None
    command: NanoExperimentCommand | None = None


class NanoExperimentRepository(Protocol):
    """Short-transaction persistence excluding successful target binding."""

    def reserve(
        self, intent: NanoExperimentIntent, *, idempotency_key: str
    ) -> NanoExperimentReservation:
        """Create/replay command, pending Version, preview and BackgroundJob."""

    def get(
        self, *, novel_id: UUID, command_id: UUID
    ) -> NanoExperimentCommand: ...

    def list_for_novel(
        self, *, novel_id: UUID
    ) -> tuple[NanoExperimentCommand, ...]: ...

    def load_and_mark_running(
        self, lease: JobLease
    ) -> NanoExperimentWorkItem: ...

    def fail(
        self, work: NanoExperimentWorkItem, failure: NanoExperimentFailure
    ) -> NanoExperimentWorkerOutcome:
        """Fence the attempt; terminalize command only with terminal job failure."""

    def fail_claim(
        self, lease: JobLease, failure: NanoExperimentFailure
    ) -> NanoExperimentWorkerOutcome: ...


class NanoExperimentSynthesizer(Protocol):
    async def synthesize(
        self, request: NanoExperimentSynthesisRequest
    ) -> NanoExperimentSynthesisResult: ...


class NanoExperimentValidator(Protocol):
    def validate(
        self,
        work: NanoExperimentWorkItem,
        result: NanoExperimentSynthesisResult,
    ) -> NanoValidatedEvidence: ...


class NanoExperimentBinder(Protocol):
    """Atomic success path owned by the SQLAlchemy integration.

    Each method must use one short transaction. ``complete_validated`` locks
    the command/version/job/target, persists the successful ModelRun link and
    machine-validation evidence, then attempts the original CAS binding before
    committing ``ready_applied`` or ``ready_unapplied``. A raised exception
    must roll the whole transaction back, including the target binding.
    """

    def complete_validated(
        self,
        work: NanoExperimentWorkItem,
        evidence: NanoValidatedEvidence,
    ) -> NanoExperimentCommand: ...

    def complete_reused(
        self,
        work: NanoExperimentWorkItem,
        reusable_version: NanoReusableVersion,
    ) -> NanoExperimentCommand: ...

    def apply_ready_unapplied(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        request: NanoExperimentApplyRequest,
    ) -> NanoExperimentCommand: ...


class StrictNanoExperimentValidator:
    """Validate every frozen synthesis and ModelRun identity before binding."""

    @staticmethod
    def _validate_audio(
        result: NanoExperimentSynthesisResult, *, validation_text: str
    ) -> None:
        if not result.audio_bytes:
            raise NanoExperimentError(
                "NANO_EXPERIMENT_AUDIO_INVALID",
                "Nano experiment output audio is empty",
            )
        if len(result.audio_bytes) != result.published_byte_size:
            raise NanoExperimentError(
                "NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH",
                "Nano experiment published byte size differs from audio bytes",
            )
        if hashlib.sha256(result.audio_bytes).hexdigest() != result.output_sha256:
            raise NanoExperimentError(
                "NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH",
                "Nano experiment output hash differs from audio bytes",
            )
        try:
            with wave.open(io.BytesIO(result.audio_bytes), "rb") as reader:
                observed = (
                    reader.getframerate(),
                    reader.getnchannels(),
                    reader.getsampwidth(),
                    reader.getnframes(),
                )
                frames = reader.readframes(reader.getnframes() + 1)
        except (EOFError, ValueError, wave.Error) as error:
            raise NanoExperimentError(
                "NANO_EXPERIMENT_AUDIO_INVALID",
                "Nano experiment output is not a complete PCM WAV",
            ) from error
        expected_format = (
            result.sample_rate_hz,
            result.channels,
            result.sample_width_bytes,
        )
        if observed[:3] != expected_format or expected_format != (48_000, 2, 2):
            raise NanoExperimentError(
                "NANO_EXPERIMENT_AUDIO_INVALID",
                "Nano experiment audio format differs from the fixed format",
            )
        frame_width = result.channels * result.sample_width_bytes
        duration_ms = round(observed[3] * 1_000 / result.sample_rate_hz)
        if (
            not frames
            or len(frames) != observed[3] * frame_width
            or duration_ms != result.duration_ms
            or not 80 <= duration_ms <= 180_000
        ):
            raise NanoExperimentError(
                "NANO_EXPERIMENT_AUDIO_INVALID",
                "Nano experiment audio duration or frame evidence is invalid",
            )
        try:
            validate_synthesis_duration_for_text(
                validation_text,
                duration_ms,
            )
        except AudioPipelineError as error:
            raise NanoExperimentError(
                "NANO_EXPERIMENT_AUDIO_INVALID",
                "Nano experiment duration is invalid for the validation text",
            ) from error

    def validate(
        self,
        work: NanoExperimentWorkItem,
        result: NanoExperimentSynthesisResult,
    ) -> NanoValidatedEvidence:
        if (
            type(work) is not NanoExperimentWorkItem
            or type(result) is not NanoExperimentSynthesisResult
        ):
            raise NanoExperimentError(
                "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
                "Nano experiment validator received invalid evidence",
            )
        command = work.command
        identity = work.model_identity
        run = result.model_run
        if (
            result.command_id != command.command_id
            or result.attempt_id != work.lease.fence.attempt_id
            or run.attempt_id != work.lease.fence.attempt_id
            or result.preview_id != command.preview_id
        ):
            raise NanoExperimentError(
                "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
                "Nano experiment result belongs to another command or attempt",
            )
        if (
            run.parameters_digest != command.parameters_digest
            or run.input_digest_key_id != work.model_input_digest_key_id
            or run.input_digest != work.model_input_digest
        ):
            raise NanoExperimentError(
                "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
                "Nano experiment parameters or input HMAC changed",
            )
        if (
            run.requested_provider_id != identity.requested_provider_id
            or run.requested_model_id != identity.requested_model_id
            or run.requested_revision != identity.requested_revision
            or run.actual_provider_id != identity.actual_provider_id
            or run.actual_model_id != identity.actual_model_id
            or run.actual_revision != identity.actual_revision
            or run.model_fingerprint_sha256
            != identity.model_fingerprint_sha256
            or result.sidecar_protocol_version
            != identity.sidecar_protocol_version
            or result.postprocess_fingerprint
            != identity.postprocess_fingerprint
        ):
            raise NanoExperimentError(
                "NANO_EXPERIMENT_MODEL_IDENTITY_MISMATCH",
                "Nano experiment requested or actual model identity changed",
            )
        if run.result_classification != "success":
            raise NanoExperimentError(
                "NANO_EXPERIMENT_SYNTHESIS_FAILED",
                "Nano experiment ModelRun is not successful",
                retryable=True,
            )
        if run.output_digest != result.output_sha256:
            raise NanoExperimentError(
                "NANO_EXPERIMENT_OUTPUT_HASH_MISMATCH",
                "Nano experiment ModelRun output differs from synthesis output",
            )
        self._validate_audio(
            result,
            validation_text=work.validation_input.text,
        )
        return NanoValidatedEvidence(
            attempt_id=run.attempt_id,
            model_run_id=run.model_run_id,
            preview_id=result.preview_id,
            result_asset_id=result.result_asset_id,
            published_relative_path=result.published_relative_path,
            published_byte_size=result.published_byte_size,
            output_sha256=result.output_sha256,
            duration_ms=result.duration_ms,
            sample_rate_hz=result.sample_rate_hz,
            channels=result.channels,
            sample_width_bytes=result.sample_width_bytes,
            parameters_digest=run.parameters_digest,
            input_digest_key_id=run.input_digest_key_id,
            input_digest=run.input_digest,
            model_fingerprint_sha256=run.model_fingerprint_sha256,
            sidecar_protocol_version=result.sidecar_protocol_version,
            postprocess_fingerprint=result.postprocess_fingerprint,
        )


class NanoExperimentService:
    """Create/list/get/apply use-cases over the persistence/Binder ports."""

    def __init__(
        self,
        *,
        repository: NanoExperimentRepository,
        binder: NanoExperimentBinder,
        validation_input: NanoExperimentValidationInput,
        model_identity: NanoExperimentModelIdentity,
    ) -> None:
        self._repository = repository
        self._binder = binder
        self._validation_input = validation_input
        self._model_identity = model_identity

    def create(
        self,
        *,
        novel_id: UUID,
        base_preset_id: str,
        target: NanoExperimentTarget,
        parameters: NanoDecodeParametersV3,
        idempotency_key: str,
    ) -> NanoExperimentReservation:
        intent = build_nano_experiment_intent(
            novel_id=novel_id,
            base_preset_id=base_preset_id,
            target=target,
            parameters=parameters,
            validation_input=self._validation_input,
            model_identity=self._model_identity,
            idempotency_key=idempotency_key,
        )
        return self._repository.reserve(intent, idempotency_key=idempotency_key)

    def get(
        self, *, novel_id: UUID, command_id: UUID
    ) -> NanoExperimentCommand:
        return self._repository.get(novel_id=novel_id, command_id=command_id)

    def list_for_novel(
        self, *, novel_id: UUID
    ) -> tuple[NanoExperimentCommand, ...]:
        return self._repository.list_for_novel(novel_id=novel_id)

    def apply(
        self,
        *,
        novel_id: UUID,
        command_id: UUID,
        request: NanoExperimentApplyRequest,
    ) -> NanoExperimentCommand:
        command = self._repository.get(novel_id=novel_id, command_id=command_id)
        request.validate_for(command.target)
        if command.state == "ready_applied":
            return command
        if command.state != "ready_unapplied":
            raise NanoExperimentStateError(
                "only ready_unapplied Nano experiments can be explicitly applied"
            )
        applied = self._binder.apply_ready_unapplied(
            novel_id=novel_id,
            command_id=command_id,
            request=request,
        )
        ensure_state_transition(command.state, applied.state)
        if applied.state != "ready_applied":
            raise NanoExperimentStateError(
                "explicit Nano experiment apply did not reach ready_applied"
            )
        return applied


class NanoExperimentProcessor:
    """Execute one already-claimed Nano experiment job outside long txns."""

    def __init__(
        self,
        *,
        repository: NanoExperimentRepository,
        synthesizer: NanoExperimentSynthesizer,
        validator: NanoExperimentValidator,
        binder: NanoExperimentBinder,
    ) -> None:
        self._repository = repository
        self._synthesizer = synthesizer
        self._validator = validator
        self._binder = binder

    @staticmethod
    def _failure(error: BaseException, *, boundary: str) -> NanoExperimentFailure:
        if isinstance(error, NanoExperimentError):
            return NanoExperimentFailure(error.code, error.retryable)
        if boundary == "synthesis":
            return NanoExperimentFailure(
                "NANO_EXPERIMENT_SYNTHESIS_FAILED", True
            )
        return NanoExperimentFailure("NANO_EXPERIMENT_DATABASE_FAILED", True)

    @staticmethod
    def _request(work: NanoExperimentWorkItem) -> NanoExperimentSynthesisRequest:
        command = work.command
        return NanoExperimentSynthesisRequest(
            command_id=command.command_id,
            attempt_id=work.lease.fence.attempt_id,
            preview_id=command.preview_id,
            base_preset_id=command.base_preset_id,
            text=work.validation_input.text,
            parameters=command.parameters,
            parameters_digest=command.parameters_digest,
            input_digest_key_id=work.model_input_digest_key_id,
            input_digest=work.model_input_digest,
            model_identity=work.model_identity,
        )

    async def process(self, lease: JobLease) -> NanoExperimentWorkerOutcome:
        try:
            work = self._repository.load_and_mark_running(lease)
        except Exception as error:
            failure = self._failure(error, boundary="database")
            try:
                return self._repository.fail_claim(lease, failure)
            except Exception as repository_error:
                raise NanoExperimentError(
                    "NANO_EXPERIMENT_DATABASE_FAILED",
                    "Nano experiment claim could not be persisted",
                    retryable=True,
                ) from repository_error

        if work.reusable_version is not None:
            try:
                validate_reusable_version(
                    _intent_from_work(work), work.reusable_version
                )
                command = self._binder.complete_reused(
                    work, work.reusable_version
                )
                if (
                    command.state not in {"ready_applied", "ready_unapplied"}
                    or not command.reused_version
                ):
                    raise NanoExperimentStateError(
                        "reused Nano experiment did not reach a ready state"
                    )
                return NanoExperimentWorkerOutcome(
                    "succeeded",
                    lease.fence.job_id,
                    command.command_id,
                    command=command,
                )
            except Exception as error:
                failure = self._failure(error, boundary="database")
                return self._repository.fail(work, failure)

        try:
            result = await self._synthesizer.synthesize(self._request(work))
        except Exception as error:
            failure = self._failure(error, boundary="synthesis")
            return self._repository.fail(work, failure)

        try:
            evidence = self._validator.validate(work, result)
            if type(evidence) is not NanoValidatedEvidence:
                raise NanoExperimentError(
                    "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
                    "Nano experiment validator returned invalid evidence",
                )
            if (
                evidence.attempt_id != work.lease.fence.attempt_id
                or evidence.preview_id != work.command.preview_id
                or evidence.parameters_digest != work.command.parameters_digest
                or evidence.input_digest_key_id
                != work.model_input_digest_key_id
                or evidence.input_digest != work.model_input_digest
                or evidence.model_fingerprint_sha256
                != work.model_identity.model_fingerprint_sha256
                or evidence.sidecar_protocol_version
                != work.model_identity.sidecar_protocol_version
                or evidence.postprocess_fingerprint
                != work.model_identity.postprocess_fingerprint
            ):
                raise NanoExperimentError(
                    "NANO_EXPERIMENT_PARAMETERS_MISMATCH",
                    "Nano experiment validated evidence changed",
                )
        except Exception as error:
            failure = self._failure(error, boundary="validation")
            return self._repository.fail(work, failure)

        try:
            command = self._binder.complete_validated(work, evidence)
            if command.state not in {"ready_applied", "ready_unapplied"}:
                raise NanoExperimentStateError(
                    "validated Nano experiment did not reach a ready state"
                )
        except Exception as error:
            # Binder contract requires an atomic rollback, so this failure path
            # cannot expose a partially changed narrator/character binding.
            failure = self._failure(error, boundary="database")
            return self._repository.fail(work, failure)
        return NanoExperimentWorkerOutcome(
            "succeeded",
            lease.fence.job_id,
            command.command_id,
            command=command,
        )


__all__ = [
    "NANO_DECODE_PARAMETERS_V3",
    "NANO_EXPERIMENT_FAILURE_CODES",
    "NANO_EXPERIMENT_MAX_NEW_FRAMES",
    "NANO_EXPERIMENT_SAMPLE_MODE",
    "NANO_EXPERIMENT_VALIDATION_TEXT",
    "NanoDecodeParametersV3",
    "NanoExperimentApplyRequest",
    "NanoExperimentBinder",
    "NanoExperimentCommand",
    "NanoExperimentContractError",
    "NanoExperimentError",
    "NanoExperimentFailure",
    "NanoExperimentIdempotencyConflict",
    "NanoExperimentIntent",
    "NanoExperimentModelIdentity",
    "NanoExperimentProcessor",
    "NanoExperimentRepository",
    "NanoExperimentReservation",
    "NanoExperimentService",
    "NanoExperimentStateError",
    "NanoExperimentSynthesisRequest",
    "NanoExperimentSynthesisResult",
    "NanoExperimentSynthesizer",
    "NanoExperimentTarget",
    "NanoExperimentTargetKind",
    "NanoExperimentValidationInput",
    "NanoExperimentValidator",
    "NanoExperimentWorkItem",
    "NanoExperimentWorkerOutcome",
    "NanoModelRunEvidence",
    "NanoReusableVersion",
    "NanoValidatedEvidence",
    "StrictNanoExperimentValidator",
    "build_nano_experiment_intent",
    "ensure_idempotent_request",
    "ensure_state_transition",
    "nano_experiment_command_id",
    "nano_experiment_fingerprint",
    "nano_experiment_profile_id",
    "nano_parameters_digest",
    "production_nano_experiment_identity",
    "require_idempotency_key",
    "validate_reusable_version",
    "validate_nano_experiment_version_evidence",
]
