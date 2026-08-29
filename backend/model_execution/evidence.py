"""Pure model-execution evidence derived from public reply metadata.

This module deliberately has no dependency on QwenPaw implementation modules,
HTTP clients, persistence, or application services.  Callers provide the
preflight/postflight identities obtained through their public boundary plus the
raw public reply chunks.  Missing public usage stays explicitly unverified;
malformed or contradictory usage fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


MODEL_EXECUTION_EVIDENCE_SCHEMA_VERSION = "model-execution-evidence/2"


class ModelExecutionContractError(ValueError):
    """Raised when a caller constructs an invalid domain value."""


class ModelExecutionEvidenceStatus(str, Enum):
    VERIFIED_FROM_PROVIDER_USAGE = "verified_from_provider_usage"
    NOT_EXPOSED = "not_exposed"
    REJECTED = "rejected"


class PublicUsageState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    MALFORMED = "malformed"


class ModelExecutionRejectionReason(str, Enum):
    PUBLIC_USAGE_MALFORMED = "public_usage_malformed"
    PREFLIGHT_POSTFLIGHT_IDENTITY_MISMATCH = (
        "preflight_postflight_identity_mismatch"
    )
    PROVIDER_USAGE_IDENTITY_MISMATCH = "provider_usage_identity_mismatch"
    POSTFLIGHT_UNAVAILABLE = "postflight_unavailable"
    EXECUTION_FAILED = "execution_failed"


def _required_text(value: object, *, field: str, maximum: int = 240) -> str:
    if type(value) is not str:
        raise ModelExecutionContractError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ModelExecutionContractError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise ModelExecutionContractError(f"{field} exceeds {maximum} characters")
    if "\x00" in normalized:
        raise ModelExecutionContractError(f"{field} contains a null byte")
    return normalized


def _optional_token_count(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ModelExecutionContractError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_id",
            _required_text(self.provider_id, field="provider_id", maximum=160),
        )
        object.__setattr__(
            self,
            "model_id",
            _required_text(self.model_id, field="model_id", maximum=200),
        )

    def as_dict(self) -> dict[str, str]:
        return {"provider_id": self.provider_id, "model_id": self.model_id}


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            object.__setattr__(
                self,
                field,
                _optional_token_count(getattr(self, field), field=field),
            )
        if (
            self.prompt_tokens is None
            and self.completion_tokens is None
            and self.total_tokens is None
        ):
            raise ModelExecutionContractError(
                "provider usage must expose at least one token count"
            )
        if self.provider_request_id is not None:
            object.__setattr__(
                self,
                "provider_request_id",
                _required_text(
                    self.provider_request_id,
                    field="provider_request_id",
                    maximum=240,
                ),
            )

    def as_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "provider_request_id": self.provider_request_id,
        }


@dataclass(frozen=True, slots=True)
class PublicUsageObservation:
    state: PublicUsageState
    actual_identity: ModelIdentity | None = None
    usage: ProviderUsage | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not PublicUsageState:
            raise ModelExecutionContractError("public usage state is invalid")
        if self.state is PublicUsageState.PRESENT:
            if (
                type(self.actual_identity) is not ModelIdentity
                or type(self.usage) is not ProviderUsage
            ):
                raise ModelExecutionContractError(
                    "present public usage requires identity and token usage"
                )
        elif self.actual_identity is not None or self.usage is not None:
            raise ModelExecutionContractError(
                "absent or malformed public usage cannot expose actual values"
            )


@dataclass(frozen=True, slots=True)
class ModelExecutionEvidenceV2:
    status: ModelExecutionEvidenceStatus
    preflight_identity: ModelIdentity
    postflight_identity: ModelIdentity | None
    actual_identity: ModelIdentity | None
    usage: ProviderUsage | None
    agent_id: str
    duration_ms: int
    rejection_reason: ModelExecutionRejectionReason | None = None
    preflight_source: str = "effective-model-api"
    postflight_source: str | None = "effective-model-api"
    effective_max_input_length: int | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not ModelExecutionEvidenceStatus:
            raise ModelExecutionContractError("model evidence status is invalid")
        if type(self.preflight_identity) is not ModelIdentity:
            raise ModelExecutionContractError("preflight_identity is invalid")
        if self.postflight_identity is not None and type(self.postflight_identity) is not ModelIdentity:
            raise ModelExecutionContractError("postflight_identity is invalid")
        if self.actual_identity is not None and type(self.actual_identity) is not ModelIdentity:
            raise ModelExecutionContractError("actual_identity is invalid")
        if self.usage is not None and type(self.usage) is not ProviderUsage:
            raise ModelExecutionContractError("usage is invalid")
        if (self.actual_identity is None) != (self.usage is None):
            raise ModelExecutionContractError(
                "actual_identity and usage must be present or absent together"
            )
        if (
            self.rejection_reason is not None
            and type(self.rejection_reason) is not ModelExecutionRejectionReason
        ):
            raise ModelExecutionContractError("rejection_reason is invalid")
        object.__setattr__(
            self,
            "agent_id",
            _required_text(self.agent_id, field="agent_id", maximum=160),
        )
        if type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ModelExecutionContractError(
                "duration_ms must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "preflight_source",
            _required_text(
                self.preflight_source,
                field="preflight_source",
                maximum=160,
            ),
        )
        if self.postflight_source is not None:
            object.__setattr__(
                self,
                "postflight_source",
                _required_text(
                    self.postflight_source,
                    field="postflight_source",
                    maximum=160,
                ),
            )
        if (
            self.effective_max_input_length is not None
            and (
                type(self.effective_max_input_length) is not int
                or self.effective_max_input_length <= 0
            )
        ):
            raise ModelExecutionContractError(
                "effective_max_input_length must be a positive integer"
            )

        identities_match = (
            self.postflight_identity is not None
            and self.preflight_identity == self.postflight_identity
        )
        if self.status is ModelExecutionEvidenceStatus.VERIFIED_FROM_PROVIDER_USAGE:
            if (
                type(self.actual_identity) is not ModelIdentity
                or type(self.usage) is not ProviderUsage
                or self.actual_identity != self.preflight_identity
                or not identities_match
                or self.rejection_reason is not None
            ):
                raise ModelExecutionContractError(
                    "verified evidence requires matching preflight, postflight, and usage identities"
                )
        elif self.status is ModelExecutionEvidenceStatus.NOT_EXPOSED:
            if (
                self.actual_identity is not None
                or self.usage is not None
                or not identities_match
                or self.rejection_reason is not None
            ):
                raise ModelExecutionContractError(
                    "not_exposed evidence requires matching effective identities and null actual usage"
                )
        else:
            if self.rejection_reason is None:
                raise ModelExecutionContractError(
                    "rejected evidence requires a rejection reason"
                )
            if (
                self.rejection_reason
                is ModelExecutionRejectionReason.PUBLIC_USAGE_MALFORMED
                and (self.actual_identity is not None or self.usage is not None)
            ):
                raise ModelExecutionContractError(
                    "malformed public usage cannot expose actual values"
                )
            if (
                self.rejection_reason
                is ModelExecutionRejectionReason.PREFLIGHT_POSTFLIGHT_IDENTITY_MISMATCH
                and identities_match
            ):
                raise ModelExecutionContractError(
                    "preflight/postflight rejection requires an identity switch"
                )
            if (
                self.rejection_reason
                is ModelExecutionRejectionReason.PROVIDER_USAGE_IDENTITY_MISMATCH
                and (
                    not identities_match
                    or self.actual_identity is None
                    or self.actual_identity == self.preflight_identity
                )
            ):
                raise ModelExecutionContractError(
                    "provider usage rejection requires a conflicting public identity"
                )
            if self.rejection_reason in {
                ModelExecutionRejectionReason.POSTFLIGHT_UNAVAILABLE,
                ModelExecutionRejectionReason.EXECUTION_FAILED,
            } and (self.actual_identity is not None or self.usage is not None):
                raise ModelExecutionContractError(
                    "execution-boundary rejections cannot expose actual values"
                )
            if (
                self.rejection_reason
                is ModelExecutionRejectionReason.POSTFLIGHT_UNAVAILABLE
                and self.postflight_identity is not None
            ):
                raise ModelExecutionContractError(
                    "postflight-unavailable rejection cannot include postflight identity"
                )

    @property
    def schema_version(self) -> str:
        return MODEL_EXECUTION_EVIDENCE_SCHEMA_VERSION

    @property
    def effective_model_pre_post_match(self) -> bool:
        return (
            self.postflight_identity is not None
            and self.preflight_identity == self.postflight_identity
        )

    @property
    def private_usage_buffer_used(self) -> bool:
        """This V2 contract never reads or accepts a private usage buffer."""

        return False

    def as_dict(self) -> dict[str, object]:
        if self.usage is not None:
            usage_payload: dict[str, object] = {
                "status": "exposed",
                **self.usage.as_dict(),
            }
        else:
            usage_payload = {
                "status": (
                    "malformed"
                    if self.rejection_reason
                    is ModelExecutionRejectionReason.PUBLIC_USAGE_MALFORMED
                    else "not_exposed"
                ),
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "provider_request_id": None,
            }
        verification_reason = (
            self.rejection_reason.value
            if self.rejection_reason is not None
            else (
                "provider_usage_matches_effective_model"
                if self.status
                is ModelExecutionEvidenceStatus.VERIFIED_FROM_PROVIDER_USAGE
                else "public_usage_not_exposed_pre_post_match"
            )
        )
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "execution_agent_id": self.agent_id,
            "preflight_effective": {
                **self.preflight_identity.as_dict(),
                "source": self.preflight_source,
                "effective_max_input_length": self.effective_max_input_length,
            },
            "postflight_effective": (
                {
                    **self.postflight_identity.as_dict(),
                    "source": self.postflight_source,
                }
                if self.postflight_identity is not None
                else None
            ),
            "reported_actual": (
                self.actual_identity.as_dict()
                if self.actual_identity is not None
                else None
            ),
            "usage": usage_payload,
            "verification_reason": verification_reason,
            "duration_ms": self.duration_ms,
            "private_usage_buffer_used": False,
        }


def _field(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _malformed_observation() -> PublicUsageObservation:
    return PublicUsageObservation(state=PublicUsageState.MALFORMED)


def inspect_public_reply_metadata(
    reply_chunks: object,
) -> PublicUsageObservation:
    """Inspect only a closing assistant message's public usage envelope.

    An entirely absent ``qwenpaw_turn_usage`` envelope is a supported absence,
    not a parsing failure.  Once the public envelope is present, every identity
    and token field is validated strictly; malformed data cannot degrade to
    ``not_exposed`` and cannot grant an actual model identity.
    """

    if not _is_sequence(reply_chunks):
        return _malformed_observation()

    for chunk in reversed(reply_chunks):
        output = _field(chunk, "output")
        if not _is_sequence(output) or not output:
            continue
        closing_message = output[-1]
        role = _field(closing_message, "role")
        if role is not None and (
            type(role) is not str
            or role.strip().casefold() not in {"assistant", "model"}
        ):
            continue
        metadata = _field(closing_message, "metadata")
        if not isinstance(metadata, Mapping):
            return PublicUsageObservation(state=PublicUsageState.ABSENT)
        if "qwenpaw_turn_usage" not in metadata:
            return PublicUsageObservation(state=PublicUsageState.ABSENT)
        envelope = metadata["qwenpaw_turn_usage"]
        if not isinstance(envelope, Mapping):
            return _malformed_observation()
        usage_payload = envelope.get("usage")
        if not isinstance(usage_payload, Mapping):
            return _malformed_observation()

        raw_provider = usage_payload.get("provider_id")
        raw_model_name = usage_payload.get("model_name")
        raw_model = (
            raw_model_name
            if raw_model_name is not None
            else usage_payload.get("model_id")
        )
        try:
            actual_identity = ModelIdentity(
                provider_id=raw_provider,
                model_id=raw_model,
            )
            usage = ProviderUsage(
                prompt_tokens=usage_payload.get("prompt_tokens"),
                completion_tokens=usage_payload.get("completion_tokens"),
                total_tokens=usage_payload.get("total_tokens"),
                provider_request_id=(
                    usage_payload.get("provider_request_id")
                    or usage_payload.get("request_id")
                    or envelope.get("provider_request_id")
                    or envelope.get("request_id")
                ),
            )
        except ModelExecutionContractError:
            return _malformed_observation()
        return PublicUsageObservation(
            state=PublicUsageState.PRESENT,
            actual_identity=actual_identity,
            usage=usage,
        )

    return PublicUsageObservation(state=PublicUsageState.ABSENT)


def determine_model_execution_evidence(
    *,
    preflight_identity: ModelIdentity,
    postflight_identity: ModelIdentity,
    reply_chunks: object,
    agent_id: str,
    duration_ms: int,
    preflight_source: str = "effective-model-api",
    postflight_source: str = "effective-model-api",
    effective_max_input_length: int | None = None,
) -> ModelExecutionEvidenceV2:
    """Build one immutable ModelExecutionEvidenceV2 from public evidence only."""

    if type(preflight_identity) is not ModelIdentity:
        raise ModelExecutionContractError("preflight_identity is invalid")
    if type(postflight_identity) is not ModelIdentity:
        raise ModelExecutionContractError("postflight_identity is invalid")
    normalized_agent_id = _required_text(agent_id, field="agent_id", maximum=160)
    if type(duration_ms) is not int or duration_ms < 0:
        raise ModelExecutionContractError(
            "duration_ms must be a non-negative integer"
        )

    observation = inspect_public_reply_metadata(reply_chunks)
    if observation.state is PublicUsageState.MALFORMED:
        return ModelExecutionEvidenceV2(
            status=ModelExecutionEvidenceStatus.REJECTED,
            preflight_identity=preflight_identity,
            postflight_identity=postflight_identity,
            actual_identity=None,
            usage=None,
            agent_id=normalized_agent_id,
            duration_ms=duration_ms,
            rejection_reason=(
                ModelExecutionRejectionReason.PUBLIC_USAGE_MALFORMED
            ),
            preflight_source=preflight_source,
            postflight_source=postflight_source,
            effective_max_input_length=effective_max_input_length,
        )

    actual_identity = observation.actual_identity
    usage = observation.usage
    if preflight_identity != postflight_identity:
        return ModelExecutionEvidenceV2(
            status=ModelExecutionEvidenceStatus.REJECTED,
            preflight_identity=preflight_identity,
            postflight_identity=postflight_identity,
            actual_identity=actual_identity,
            usage=usage,
            agent_id=normalized_agent_id,
            duration_ms=duration_ms,
            rejection_reason=(
                ModelExecutionRejectionReason.PREFLIGHT_POSTFLIGHT_IDENTITY_MISMATCH
            ),
            preflight_source=preflight_source,
            postflight_source=postflight_source,
            effective_max_input_length=effective_max_input_length,
        )

    if observation.state is PublicUsageState.ABSENT:
        return ModelExecutionEvidenceV2(
            status=ModelExecutionEvidenceStatus.NOT_EXPOSED,
            preflight_identity=preflight_identity,
            postflight_identity=postflight_identity,
            actual_identity=None,
            usage=None,
            agent_id=normalized_agent_id,
            duration_ms=duration_ms,
            preflight_source=preflight_source,
            postflight_source=postflight_source,
            effective_max_input_length=effective_max_input_length,
        )

    assert actual_identity is not None
    assert usage is not None
    if actual_identity != preflight_identity:
        return ModelExecutionEvidenceV2(
            status=ModelExecutionEvidenceStatus.REJECTED,
            preflight_identity=preflight_identity,
            postflight_identity=postflight_identity,
            actual_identity=actual_identity,
            usage=usage,
            agent_id=normalized_agent_id,
            duration_ms=duration_ms,
            rejection_reason=(
                ModelExecutionRejectionReason.PROVIDER_USAGE_IDENTITY_MISMATCH
            ),
            preflight_source=preflight_source,
            postflight_source=postflight_source,
            effective_max_input_length=effective_max_input_length,
        )

    return ModelExecutionEvidenceV2(
        status=ModelExecutionEvidenceStatus.VERIFIED_FROM_PROVIDER_USAGE,
        preflight_identity=preflight_identity,
        postflight_identity=postflight_identity,
        actual_identity=actual_identity,
        usage=usage,
        agent_id=normalized_agent_id,
        duration_ms=duration_ms,
        preflight_source=preflight_source,
        postflight_source=postflight_source,
        effective_max_input_length=effective_max_input_length,
    )


def rejected_model_execution_evidence(
    *,
    preflight_identity: ModelIdentity,
    postflight_identity: ModelIdentity | None,
    agent_id: str,
    duration_ms: int,
    reason: ModelExecutionRejectionReason,
    preflight_source: str = "effective-model-api",
    postflight_source: str | None = None,
    effective_max_input_length: int | None = None,
) -> ModelExecutionEvidenceV2:
    """Record a failed public execution boundary without inventing actual usage."""

    if reason not in {
        ModelExecutionRejectionReason.POSTFLIGHT_UNAVAILABLE,
        ModelExecutionRejectionReason.EXECUTION_FAILED,
    }:
        raise ModelExecutionContractError("unsupported boundary rejection reason")
    return ModelExecutionEvidenceV2(
        status=ModelExecutionEvidenceStatus.REJECTED,
        preflight_identity=preflight_identity,
        postflight_identity=postflight_identity,
        actual_identity=None,
        usage=None,
        agent_id=agent_id,
        duration_ms=duration_ms,
        rejection_reason=reason,
        preflight_source=preflight_source,
        postflight_source=postflight_source,
        effective_max_input_length=effective_max_input_length,
    )
