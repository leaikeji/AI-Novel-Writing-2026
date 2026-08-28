"""Strict, provider-neutral wire contract for cloud speaker analysis.

The module deliberately contains no network client.  A trusted adapter receives
one canonical JSON request and must return the actual model identity out of band
from the model-authored JSON.  This keeps provider I/O injectable and makes it
impossible for a model response to self-report its own identity.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol
from uuid import RFC_4122, UUID

from .contracts import ConfidenceLevel
from .fingerprints import canonical_json_bytes
from .script_contracts import SpeakerKind, SpeakerRef

SPEAKER_MODEL_REQUEST_VERSION: Final = "narration-cloud-speaker-request/1"
SPEAKER_MODEL_RESPONSE_VERSION: Final = "narration-cloud-speaker-response/1"
SPEAKER_MODEL_TEMPLATE_VERSION: Final = "narration-cloud-speaker-prompt/1"
SPEAKER_MODEL_TASK: Final = "select_speaker"

MAX_TARGET_CHARACTERS: Final = 2_000
MAX_CONTEXT_CHARACTERS: Final = 600
MAX_SCENE_HINT_CHARACTERS: Final = 120
MAX_CANDIDATES: Final = 16
MAX_ALIASES_PER_CANDIDATE: Final = 8
MAX_RESPONSE_BYTES: Final = 32_768

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_GROUP_KEY = re.compile(r"^grp1_[a-f0-9]{64}$")


class SpeakerModelContractError(ValueError):
    """Raised when a request or model-authored response violates the wire schema."""


class SpeakerModelUnavailableError(RuntimeError):
    """Raised by an adapter that cannot perform a model call."""


class SpeakerEvidenceCode(str, Enum):
    ALIAS_MATCH = "alias_match"
    EXPLICIT_SPEECH_TAG = "explicit_speech_tag"
    TURN_CONTINUITY = "turn_continuity"
    NARRATIVE_CONTEXT = "narrative_context"
    SCENE_ROLE = "scene_role"
    GROUP_MARKER = "group_marker"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"


def _require_text(
    value: object,
    *,
    field_name: str,
    minimum: int = 1,
    maximum: int,
) -> str:
    if type(value) is not str:
        raise SpeakerModelContractError(f"{field_name} must be a string")
    if not minimum <= len(value) <= maximum:
        raise SpeakerModelContractError(
            f"{field_name} length must be between {minimum} and {maximum}"
        )
    if unicodedata.normalize("NFC", value) != value:
        raise SpeakerModelContractError(f"{field_name} must use NFC normalization")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise SpeakerModelContractError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


def _require_optional_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name=field_name, maximum=maximum)


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise SpeakerModelContractError(f"{field_name} must be lowercase SHA-256")
    return value


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not UUID or value.variant != RFC_4122 or value.version not in {
        1,
        2,
        3,
        4,
        5,
    }:
        raise SpeakerModelContractError(f"{field_name} must be an RFC-4122 UUID")
    return value


def _parse_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not str:
        raise SpeakerModelContractError(f"{field_name} must be a canonical UUID string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise SpeakerModelContractError(
            f"{field_name} must be a canonical UUID string"
        ) from error
    if str(parsed) != value:
        raise SpeakerModelContractError(f"{field_name} must be a canonical UUID string")
    return _require_uuid(parsed, field_name=field_name)


def _parse_optional_uuid(value: object, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _parse_uuid(value, field_name=field_name)


def _expect_object(value: object, *, field_name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise SpeakerModelContractError(f"{field_name} must be a JSON object")
    return value


def _expect_array(value: object, *, field_name: str) -> list[object]:
    if type(value) is not list:
        raise SpeakerModelContractError(f"{field_name} must be a JSON array")
    return value


def _expect_keys(
    value: dict[str, object], *, required: tuple[str, ...], field_name: str
) -> None:
    if set(value) != set(required):
        raise SpeakerModelContractError(f"{field_name} has unknown or missing fields")


def _parse_enum(value: object, enum_type: type[Enum], *, field_name: str) -> Enum:
    if type(value) is not str:
        raise SpeakerModelContractError(f"{field_name} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise SpeakerModelContractError(f"{field_name} has an unknown value") from error


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Server/adapter-owned model identity; never parsed from model JSON."""

    provider_id: str
    model_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        _require_text(self.provider_id, field_name="provider_id", maximum=160)
        _require_text(self.model_id, field_name="model_id", maximum=160)
        _require_sha256(self.fingerprint, field_name="model fingerprint")


@dataclass(frozen=True, slots=True)
class SpeakerTextFragment:
    segment_id: UUID
    text: str
    truncated: bool

    def __post_init__(self) -> None:
        _require_uuid(self.segment_id, field_name="fragment segment_id")
        _require_text(
            self.text,
            field_name="fragment text",
            maximum=MAX_TARGET_CHARACTERS,
        )
        if type(self.truncated) is not bool:
            raise SpeakerModelContractError("fragment truncated must be a boolean")


@dataclass(frozen=True, slots=True)
class SpeakerModelCandidate:
    """The only speaker identity fields the model may select."""

    speaker: SpeakerRef
    display_name: str
    aliases: tuple[str, ...] = ()
    role_hint: str | None = None

    def __post_init__(self) -> None:
        if type(self.speaker) is not SpeakerRef:
            raise SpeakerModelContractError("candidate speaker must be SpeakerRef")
        if self.speaker.kind is SpeakerKind.UNKNOWN:
            raise SpeakerModelContractError("unknown is implicit and cannot be a candidate")
        _require_text(
            self.display_name,
            field_name="candidate display_name",
            maximum=160,
        )
        if type(self.aliases) is not tuple:
            raise SpeakerModelContractError("candidate aliases must be a tuple")
        if len(self.aliases) > MAX_ALIASES_PER_CANDIDATE:
            raise SpeakerModelContractError("candidate aliases exceed the privacy limit")
        normalized_aliases = tuple(
            _require_text(alias, field_name="candidate alias", maximum=80)
            for alias in self.aliases
        )
        if len(set(normalized_aliases)) != len(normalized_aliases):
            raise SpeakerModelContractError("candidate aliases must be unique")
        if normalized_aliases != tuple(sorted(normalized_aliases)):
            raise SpeakerModelContractError("candidate aliases must use canonical order")
        _require_optional_text(
            self.role_hint,
            field_name="candidate role_hint",
            maximum=80,
        )


@dataclass(frozen=True, slots=True)
class SpeakerModelRequest:
    target: SpeakerTextFragment
    context_before: tuple[SpeakerTextFragment, ...]
    context_after: tuple[SpeakerTextFragment, ...]
    scene_hint: str | None
    previous_speaker: SpeakerRef | None
    candidates: tuple[SpeakerModelCandidate, ...]
    schema_version: str = SPEAKER_MODEL_REQUEST_VERSION
    template_version: str = SPEAKER_MODEL_TEMPLATE_VERSION
    task: str = SPEAKER_MODEL_TASK

    def __post_init__(self) -> None:
        if self.schema_version != SPEAKER_MODEL_REQUEST_VERSION:
            raise SpeakerModelContractError("unknown speaker request schema version")
        if self.template_version != SPEAKER_MODEL_TEMPLATE_VERSION:
            raise SpeakerModelContractError("unknown speaker prompt template version")
        if self.task != SPEAKER_MODEL_TASK:
            raise SpeakerModelContractError("unknown speaker model task")
        if type(self.target) is not SpeakerTextFragment or self.target.truncated:
            raise SpeakerModelContractError("target must be one complete text fragment")
        for field_name, fragments in (
            ("context_before", self.context_before),
            ("context_after", self.context_after),
        ):
            if type(fragments) is not tuple or not all(
                type(item) is SpeakerTextFragment for item in fragments
            ):
                raise SpeakerModelContractError(f"{field_name} must be a fragment tuple")
            if len(fragments) > 1:
                raise SpeakerModelContractError(
                    f"{field_name} exceeds the one-segment minimal window"
                )
            if any(len(item.text) > MAX_CONTEXT_CHARACTERS for item in fragments):
                raise SpeakerModelContractError(f"{field_name} text exceeds its limit")
        fragment_ids = [
            item.segment_id
            for item in (*self.context_before, self.target, *self.context_after)
        ]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise SpeakerModelContractError("request fragment ids must be unique")
        _require_optional_text(
            self.scene_hint,
            field_name="scene_hint",
            maximum=MAX_SCENE_HINT_CHARACTERS,
        )
        if self.previous_speaker is not None and type(
            self.previous_speaker
        ) is not SpeakerRef:
            raise SpeakerModelContractError(
                "previous_speaker must be SpeakerRef or None"
            )
        if type(self.candidates) is not tuple or not all(
            type(item) is SpeakerModelCandidate for item in self.candidates
        ):
            raise SpeakerModelContractError("candidates must be a candidate tuple")
        if not self.candidates or len(self.candidates) > MAX_CANDIDATES:
            raise SpeakerModelContractError(
                "candidates must contain between 1 and 16 server options"
            )
        speakers = [item.speaker for item in self.candidates]
        if len(speakers) != len(set(speakers)):
            raise SpeakerModelContractError("candidate speakers must be unique")
        if self.previous_speaker is not None and (
            self.previous_speaker.kind
            not in {SpeakerKind.NARRATOR, SpeakerKind.UNKNOWN}
            and self.previous_speaker not in speakers
        ):
            raise SpeakerModelContractError(
                "previous speaker must be narrator/unknown or an allowed candidate"
            )


@dataclass(frozen=True, slots=True)
class SpeakerModelDecision:
    segment_id: UUID
    speaker: SpeakerRef
    confidence: ConfidenceLevel
    evidence_codes: tuple[SpeakerEvidenceCode, ...]
    schema_version: str = SPEAKER_MODEL_RESPONSE_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SPEAKER_MODEL_RESPONSE_VERSION:
            raise SpeakerModelContractError("unknown speaker response schema version")
        _require_uuid(self.segment_id, field_name="response segment_id")
        if type(self.speaker) is not SpeakerRef:
            raise SpeakerModelContractError("response speaker must be SpeakerRef")
        if type(self.confidence) is not ConfidenceLevel:
            raise SpeakerModelContractError("response confidence has an unknown value")
        if type(self.evidence_codes) is not tuple or not all(
            type(item) is SpeakerEvidenceCode for item in self.evidence_codes
        ):
            raise SpeakerModelContractError(
                "response evidence_codes must be a typed tuple"
            )
        if not self.evidence_codes or len(self.evidence_codes) > 8:
            raise SpeakerModelContractError(
                "response evidence_codes must contain between 1 and 8 values"
            )
        if len(set(self.evidence_codes)) != len(self.evidence_codes):
            raise SpeakerModelContractError("response evidence_codes must be unique")
        if self.evidence_codes != tuple(
            sorted(self.evidence_codes, key=lambda item: item.value)
        ):
            raise SpeakerModelContractError(
                "response evidence_codes must use canonical order"
            )
        if self.speaker.kind is SpeakerKind.UNKNOWN:
            allowed = {
                SpeakerEvidenceCode.INSUFFICIENT_EVIDENCE,
                SpeakerEvidenceCode.AMBIGUOUS_CANDIDATES,
            }
            if not set(self.evidence_codes).intersection(allowed):
                raise SpeakerModelContractError(
                    "unknown speaker requires insufficient/ambiguous evidence"
                )
            if self.confidence not in {ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN}:
                raise SpeakerModelContractError(
                    "unknown speaker cannot claim medium/high confidence"
                )


@dataclass(frozen=True, slots=True)
class TrustedSpeakerModelReply:
    """Adapter-owned actual identity plus untrusted model-authored JSON."""

    actual_identity: ModelIdentity
    response_json: str

    def __post_init__(self) -> None:
        if type(self.actual_identity) is not ModelIdentity:
            raise SpeakerModelContractError(
                "actual_identity must come from the trusted adapter"
            )
        response_json = _require_text(
            self.response_json,
            field_name="response_json",
            maximum=MAX_RESPONSE_BYTES,
        )
        if len(response_json.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise SpeakerModelContractError("response_json exceeds the byte limit")


class SpeakerModelAdapter(Protocol):
    async def analyze_speaker(
        self,
        *,
        request_json: str,
        requested_identity: ModelIdentity,
    ) -> TrustedSpeakerModelReply:
        """Return actual identity from adapter metadata, never model JSON."""


def _speaker_payload(speaker: SpeakerRef) -> dict[str, object]:
    return {
        "kind": speaker.kind.value,
        "character_id": str(speaker.character_id) if speaker.character_id else None,
        "anonymous_speaker_id": (
            str(speaker.anonymous_speaker_id)
            if speaker.anonymous_speaker_id
            else None
        ),
        "group_key": speaker.group_key,
    }


def _parse_speaker(value: object, *, field_name: str) -> SpeakerRef:
    payload = _expect_object(value, field_name=field_name)
    keys = ("kind", "character_id", "anonymous_speaker_id", "group_key")
    _expect_keys(payload, required=keys, field_name=field_name)
    kind = _parse_enum(payload["kind"], SpeakerKind, field_name=f"{field_name}.kind")
    group_key = payload["group_key"]
    if group_key is not None and (
        type(group_key) is not str or _GROUP_KEY.fullmatch(group_key) is None
    ):
        raise SpeakerModelContractError(f"{field_name}.group_key is invalid")
    try:
        return SpeakerRef(
            kind=kind,  # type: ignore[arg-type]
            character_id=_parse_optional_uuid(
                payload["character_id"], field_name=f"{field_name}.character_id"
            ),
            anonymous_speaker_id=_parse_optional_uuid(
                payload["anonymous_speaker_id"],
                field_name=f"{field_name}.anonymous_speaker_id",
            ),
            group_key=group_key,
        )
    except ValueError as error:
        raise SpeakerModelContractError(
            f"{field_name} identity fields do not match its kind"
        ) from error


def _fragment_payload(fragment: SpeakerTextFragment) -> dict[str, object]:
    return {
        "segment_id": str(fragment.segment_id),
        "text": fragment.text,
        "truncated": fragment.truncated,
    }


def _parse_fragment(value: object, *, field_name: str) -> SpeakerTextFragment:
    payload = _expect_object(value, field_name=field_name)
    keys = ("segment_id", "text", "truncated")
    _expect_keys(payload, required=keys, field_name=field_name)
    if type(payload["truncated"]) is not bool:
        raise SpeakerModelContractError(f"{field_name}.truncated must be a boolean")
    return SpeakerTextFragment(
        segment_id=_parse_uuid(
            payload["segment_id"], field_name=f"{field_name}.segment_id"
        ),
        text=_require_text(
            payload["text"],
            field_name=f"{field_name}.text",
            maximum=MAX_TARGET_CHARACTERS,
        ),
        truncated=payload["truncated"],
    )


def _candidate_payload(candidate: SpeakerModelCandidate) -> dict[str, object]:
    return {
        "speaker": _speaker_payload(candidate.speaker),
        "display_name": candidate.display_name,
        "aliases": list(candidate.aliases),
        "role_hint": candidate.role_hint,
    }


def _parse_candidate(value: object, *, field_name: str) -> SpeakerModelCandidate:
    payload = _expect_object(value, field_name=field_name)
    keys = ("speaker", "display_name", "aliases", "role_hint")
    _expect_keys(payload, required=keys, field_name=field_name)
    aliases = _expect_array(payload["aliases"], field_name=f"{field_name}.aliases")
    return SpeakerModelCandidate(
        speaker=_parse_speaker(payload["speaker"], field_name=f"{field_name}.speaker"),
        display_name=_require_text(
            payload["display_name"],
            field_name=f"{field_name}.display_name",
            maximum=160,
        ),
        aliases=tuple(
            _require_text(
                item,
                field_name=f"{field_name}.alias",
                maximum=80,
            )
            for item in aliases
        ),
        role_hint=_require_optional_text(
            payload["role_hint"],
            field_name=f"{field_name}.role_hint",
            maximum=80,
        ),
    )


def speaker_model_request_to_payload(
    request: SpeakerModelRequest,
) -> dict[str, object]:
    if type(request) is not SpeakerModelRequest:
        raise SpeakerModelContractError("request must be SpeakerModelRequest")
    candidates = sorted(
        (_candidate_payload(item) for item in request.candidates),
        key=canonical_json_bytes,
    )
    return {
        "schema_version": request.schema_version,
        "template_version": request.template_version,
        "task": request.task,
        "target": _fragment_payload(request.target),
        "context_before": [_fragment_payload(item) for item in request.context_before],
        "context_after": [_fragment_payload(item) for item in request.context_after],
        "scene_hint": request.scene_hint,
        "previous_speaker": (
            _speaker_payload(request.previous_speaker)
            if request.previous_speaker is not None
            else None
        ),
        "candidates": candidates,
    }


def speaker_model_request_to_json(request: SpeakerModelRequest) -> str:
    return canonical_json_bytes(speaker_model_request_to_payload(request)).decode("utf-8")


def speaker_model_request_from_payload(value: object) -> SpeakerModelRequest:
    payload = _expect_object(value, field_name="speaker model request")
    keys = (
        "schema_version",
        "template_version",
        "task",
        "target",
        "context_before",
        "context_after",
        "scene_hint",
        "previous_speaker",
        "candidates",
    )
    _expect_keys(payload, required=keys, field_name="speaker model request")
    before = _expect_array(payload["context_before"], field_name="context_before")
    after = _expect_array(payload["context_after"], field_name="context_after")
    candidates = _expect_array(payload["candidates"], field_name="candidates")
    previous = payload["previous_speaker"]
    request = SpeakerModelRequest(
        schema_version=_require_text(
            payload["schema_version"], field_name="schema_version", maximum=120
        ),
        template_version=_require_text(
            payload["template_version"], field_name="template_version", maximum=120
        ),
        task=_require_text(payload["task"], field_name="task", maximum=80),
        target=_parse_fragment(payload["target"], field_name="target"),
        context_before=tuple(
            _parse_fragment(item, field_name="context_before item") for item in before
        ),
        context_after=tuple(
            _parse_fragment(item, field_name="context_after item") for item in after
        ),
        scene_hint=_require_optional_text(
            payload["scene_hint"], field_name="scene_hint", maximum=120
        ),
        previous_speaker=(
            None
            if previous is None
            else _parse_speaker(previous, field_name="previous_speaker")
        ),
        candidates=tuple(
            _parse_candidate(item, field_name="candidate") for item in candidates
        ),
    )
    if speaker_model_request_to_payload(request) != payload:
        raise SpeakerModelContractError("speaker model request is not canonical")
    return request


def _reject_json_constant(value: str) -> object:
    raise SpeakerModelContractError(f"JSON constant {value} is forbidden")


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SpeakerModelContractError("duplicate JSON object key")
        result[key] = value
    return result


def strict_json_object(value: str) -> dict[str, object]:
    response_json = _require_text(
        value, field_name="JSON response", maximum=MAX_RESPONSE_BYTES
    )
    if len(response_json.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise SpeakerModelContractError("JSON response exceeds the byte limit")
    try:
        parsed = json.loads(
            response_json,
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_json_constant,
        )
    except SpeakerModelContractError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise SpeakerModelContractError("response is not strict JSON") from error
    return _expect_object(parsed, field_name="JSON response")


def speaker_model_decision_to_payload(
    decision: SpeakerModelDecision,
) -> dict[str, object]:
    if type(decision) is not SpeakerModelDecision:
        raise SpeakerModelContractError("decision must be SpeakerModelDecision")
    return {
        "schema_version": decision.schema_version,
        "segment_id": str(decision.segment_id),
        "speaker": _speaker_payload(decision.speaker),
        "confidence": decision.confidence.value,
        "evidence_codes": [item.value for item in decision.evidence_codes],
    }


def speaker_model_decision_to_json(decision: SpeakerModelDecision) -> str:
    return canonical_json_bytes(speaker_model_decision_to_payload(decision)).decode(
        "utf-8"
    )


def parse_speaker_model_response(response_json: str) -> SpeakerModelDecision:
    payload = strict_json_object(response_json)
    keys = (
        "schema_version",
        "segment_id",
        "speaker",
        "confidence",
        "evidence_codes",
    )
    _expect_keys(payload, required=keys, field_name="speaker model response")
    evidence = _expect_array(payload["evidence_codes"], field_name="evidence_codes")
    decision = SpeakerModelDecision(
        schema_version=_require_text(
            payload["schema_version"], field_name="schema_version", maximum=120
        ),
        segment_id=_parse_uuid(payload["segment_id"], field_name="segment_id"),
        speaker=_parse_speaker(payload["speaker"], field_name="speaker"),
        confidence=_parse_enum(
            payload["confidence"], ConfidenceLevel, field_name="confidence"
        ),  # type: ignore[arg-type]
        evidence_codes=tuple(
            _parse_enum(item, SpeakerEvidenceCode, field_name="evidence_code")
            for item in evidence
        ),  # type: ignore[arg-type]
    )
    return decision


__all__ = [
    "MAX_CANDIDATES",
    "MAX_CONTEXT_CHARACTERS",
    "MAX_TARGET_CHARACTERS",
    "ModelIdentity",
    "SPEAKER_MODEL_REQUEST_VERSION",
    "SPEAKER_MODEL_RESPONSE_VERSION",
    "SPEAKER_MODEL_TEMPLATE_VERSION",
    "SpeakerEvidenceCode",
    "SpeakerModelAdapter",
    "SpeakerModelCandidate",
    "SpeakerModelContractError",
    "SpeakerModelDecision",
    "SpeakerModelRequest",
    "SpeakerModelUnavailableError",
    "SpeakerTextFragment",
    "TrustedSpeakerModelReply",
    "parse_speaker_model_response",
    "speaker_model_decision_to_json",
    "speaker_model_decision_to_payload",
    "speaker_model_request_from_payload",
    "speaker_model_request_to_json",
    "speaker_model_request_to_payload",
    "strict_json_object",
]
