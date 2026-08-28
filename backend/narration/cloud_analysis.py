"""Privacy-minimal orchestration for optional cloud speaker analysis.

Only server-marked uncertain segments are sent.  Each call contains one target,
at most one adjacent fragment on either side, and a finite server-owned speaker
allowlist.  The injected adapter is the only possible I/O boundary; this module
does not import a provider SDK or perform network access itself.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol
from uuid import RFC_4122, UUID

from .contracts import ConfidenceLevel, WORKFLOW_FAILURE_CODES
from .digest_keyring import HmacDigestKey
from .fingerprints import canonical_json_bytes
from .script_contracts import (
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CloudAuthorityRecord,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
    text_sha256,
)
from .speaker_model import (
    MAX_CONTEXT_CHARACTERS,
    MAX_TARGET_CHARACTERS,
    ModelIdentity,
    SpeakerModelAdapter,
    SpeakerModelCandidate,
    SpeakerModelContractError,
    SpeakerModelDecision,
    SpeakerModelRequest,
    SpeakerModelUnavailableError,
    SpeakerTextFragment,
    TrustedSpeakerModelReply,
    parse_speaker_model_response,
    speaker_model_decision_to_payload,
    speaker_model_request_to_json,
)

CLOUD_CONSENT_PURPOSE: Final = "narration_speaker_analysis"
CLOUD_CONSENT_DATA_SCOPE: Final = "uncertain_segments_with_minimal_context"
CLOUD_CONSENT_NOTICE_VERSION: Final = "narration-cloud-consent/1"
CLOUD_DIGEST_ALGORITHM: Final = "HMAC-SHA256"
CLOUD_CONTEXT_RADIUS: Final = 1

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class CloudAnalysisFailureCode(str, Enum):
    ANALYZER_RUNTIME = "F_ANALYZER_RUNTIME"
    MODEL_IDENTITY_MISMATCH = "F_MODEL_IDENTITY_MISMATCH"
    MODEL_OUTPUT_SCHEMA_INVALID = "F_MODEL_OUTPUT_SCHEMA_INVALID"
    INPUT_FINGERPRINT_CHANGED = "F_INPUT_FINGERPRINT_CHANGED"
    SCOPE_VIOLATION = "F_SCOPE_VIOLATION"
    CONSENT_REVOKED_BEFORE_CALL = "F_CONSENT_REVOKED_BEFORE_CALL"
    ADAPTER_UNAVAILABLE = "F_ADAPTER_UNAVAILABLE"


if tuple(item.value for item in CloudAnalysisFailureCode) != WORKFLOW_FAILURE_CODES:
    raise RuntimeError("cloud analysis failure taxonomy drifted from T1-A")


_SAFE_FAILURE_MESSAGES: Final[dict[CloudAnalysisFailureCode, str]] = {
    CloudAnalysisFailureCode.ANALYZER_RUNTIME: (
        "cloud speaker analysis failed at the adapter boundary"
    ),
    CloudAnalysisFailureCode.MODEL_IDENTITY_MISMATCH: (
        "actual model identity did not match the requested identity"
    ),
    CloudAnalysisFailureCode.MODEL_OUTPUT_SCHEMA_INVALID: (
        "cloud speaker response failed strict schema validation"
    ),
    CloudAnalysisFailureCode.INPUT_FINGERPRINT_CHANGED: (
        "source fingerprint changed before cloud evidence could be accepted"
    ),
    CloudAnalysisFailureCode.SCOPE_VIOLATION: (
        "cloud speaker decision left the server-authorized scope"
    ),
    CloudAnalysisFailureCode.CONSENT_REVOKED_BEFORE_CALL: (
        "active cloud consent was absent at the call or acceptance boundary"
    ),
    CloudAnalysisFailureCode.ADAPTER_UNAVAILABLE: (
        "cloud speaker adapter is unavailable"
    ),
}


class CloudAnalysisFailure(RuntimeError):
    """Safe workflow failure that never embeds source/model response text."""

    def __init__(self, code: CloudAnalysisFailureCode) -> None:
        if type(code) is not CloudAnalysisFailureCode:
            raise TypeError("cloud failure code must be CloudAnalysisFailureCode")
        self.code = code
        super().__init__(_SAFE_FAILURE_MESSAGES[code])


def _fail(code: CloudAnalysisFailureCode) -> CloudAnalysisFailure:
    return CloudAnalysisFailure(code)


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not UUID or value.variant != RFC_4122 or value.version not in {
        1,
        2,
        3,
        4,
        5,
    }:
        raise ValueError(f"{field_name} must be an RFC-4122 UUID")
    return value


def _require_text(
    value: object,
    *,
    field_name: str,
    minimum: int = 1,
    maximum: int,
) -> str:
    if type(value) is not str or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field_name} has an invalid length")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{field_name} must use NFC normalization")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} contains an invalid surrogate") from error
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class CloudAnalysisScope:
    novel_id: UUID
    document_id: UUID
    revision_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="scope novel_id")
        _require_uuid(self.document_id, field_name="scope document_id")
        _require_uuid(self.revision_id, field_name="scope revision_id")


@dataclass(frozen=True, slots=True)
class CloudConsentSnapshot:
    """Server-owned projection of one persisted, work-scoped consent row."""

    consent_id: UUID
    novel_id: UUID
    version: int
    active: bool
    provider_id: str
    model_id: str
    purpose: str = CLOUD_CONSENT_PURPOSE
    data_scope: str = CLOUD_CONSENT_DATA_SCOPE
    notice_version: str = CLOUD_CONSENT_NOTICE_VERSION

    def __post_init__(self) -> None:
        _require_uuid(self.consent_id, field_name="consent_id")
        _require_uuid(self.novel_id, field_name="consent novel_id")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("consent version must be a positive integer")
        if type(self.active) is not bool:
            raise ValueError("consent active must be a boolean")
        _require_text(self.provider_id, field_name="consent provider_id", maximum=160)
        _require_text(self.model_id, field_name="consent model_id", maximum=160)
        _require_text(self.purpose, field_name="consent purpose", maximum=120)
        _require_text(self.data_scope, field_name="consent data_scope", maximum=120)
        _require_text(
            self.notice_version,
            field_name="consent notice_version",
            maximum=120,
        )


def _casting_matches_speaker(speaker: SpeakerRef, casting: CastingDecision) -> bool:
    if casting.origin in {
        CastingDecisionOrigin.UNRESOLVED,
        CastingDecisionOrigin.NOT_APPLICABLE,
        CastingDecisionOrigin.MANUAL_OVERRIDE,
    }:
        return False
    expected_kind = {
        CastingDecisionOrigin.NARRATOR_SETTING: SpeakerKind.NARRATOR,
        CastingDecisionOrigin.CHARACTER_BINDING: SpeakerKind.CHARACTER,
        CastingDecisionOrigin.ANONYMOUS_BINDING: SpeakerKind.ANONYMOUS,
    }.get(casting.origin)
    if expected_kind is not None and speaker.kind is not expected_kind:
        return False
    target = casting.final_target
    if target is None:
        return False
    if target.kind is CastingTargetKind.CHARACTER_BINDING:
        return (
            speaker.kind is SpeakerKind.CHARACTER
            and target.character_id == speaker.character_id
        )
    if target.kind is CastingTargetKind.ANONYMOUS_BINDING:
        return (
            speaker.kind is SpeakerKind.ANONYMOUS
            and target.anonymous_speaker_id == speaker.anonymous_speaker_id
        )
    return speaker.kind is not SpeakerKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class BoundSpeakerCandidate:
    """Public model candidate plus its exact server-owned casting decision."""

    model_candidate: SpeakerModelCandidate
    casting: CastingDecision

    def __post_init__(self) -> None:
        if type(self.model_candidate) is not SpeakerModelCandidate:
            raise ValueError("model_candidate must be SpeakerModelCandidate")
        if type(self.casting) is not CastingDecision:
            raise ValueError("candidate casting must be CastingDecision")
        if not _casting_matches_speaker(self.model_candidate.speaker, self.casting):
            raise ValueError("candidate casting is not bound to its speaker identity")


@dataclass(frozen=True, slots=True)
class CloudSourceSegment:
    segment_id: UUID
    ordinal: int
    source_text: str
    source_local_hash: str
    needs_cloud_analysis: bool
    candidates: tuple[BoundSpeakerCandidate, ...] = ()
    scene_hint: str | None = None
    previous_speaker: SpeakerRef | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.segment_id, field_name="segment_id")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("segment ordinal must be a non-negative integer")
        _require_text(
            self.source_text,
            field_name="segment source_text",
            maximum=100_000,
        )
        _require_sha256(self.source_local_hash, field_name="segment source_local_hash")
        if self.source_local_hash != text_sha256(self.source_text):
            raise ValueError("segment source_local_hash does not match source_text")
        if type(self.needs_cloud_analysis) is not bool:
            raise ValueError("needs_cloud_analysis must be a boolean")
        if type(self.candidates) is not tuple or not all(
            type(item) is BoundSpeakerCandidate for item in self.candidates
        ):
            raise ValueError("segment candidates must be a bound candidate tuple")
        if self.needs_cloud_analysis:
            if not self.candidates:
                raise ValueError("uncertain segment requires finite speaker candidates")
            if len(self.source_text) > MAX_TARGET_CHARACTERS:
                raise ValueError("uncertain target exceeds the cloud target limit")
        elif self.candidates:
            raise ValueError("context-only segment cannot carry cloud candidates")
        speakers = [item.model_candidate.speaker for item in self.candidates]
        if len(speakers) != len(set(speakers)):
            raise ValueError("segment candidate speakers must be unique")
        if self.scene_hint is not None:
            _require_text(self.scene_hint, field_name="scene_hint", maximum=120)
        if self.previous_speaker is not None and type(
            self.previous_speaker
        ) is not SpeakerRef:
            raise ValueError("previous_speaker must be SpeakerRef or None")


@dataclass(frozen=True, slots=True)
class MinimalCloudWindow:
    target: CloudSourceSegment
    context_before: tuple[CloudSourceSegment, ...]
    context_after: tuple[CloudSourceSegment, ...]

    def __post_init__(self) -> None:
        if type(self.target) is not CloudSourceSegment or not (
            self.target.needs_cloud_analysis
        ):
            raise ValueError("window target must be an uncertain source segment")
        for field_name, items in (
            ("context_before", self.context_before),
            ("context_after", self.context_after),
        ):
            if type(items) is not tuple or not all(
                type(item) is CloudSourceSegment for item in items
            ):
                raise ValueError(f"{field_name} must be a source segment tuple")
            if len(items) > CLOUD_CONTEXT_RADIUS:
                raise ValueError(f"{field_name} exceeds the minimal context radius")
        ids = [
            item.segment_id
            for item in (*self.context_before, self.target, *self.context_after)
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("window segment ids must be unique")


class CloudAnalysisGuard(Protocol):
    """Fresh server checks performed immediately before and after a call."""

    def consent_is_active(
        self,
        *,
        scope: CloudAnalysisScope,
        consent: CloudConsentSnapshot,
        requested_identity: ModelIdentity,
    ) -> bool: ...

    def source_is_current(
        self,
        *,
        scope: CloudAnalysisScope,
        segment_id: UUID,
        source_local_hash: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class CloudAnalysisResult:
    segment_id: UUID
    source_local_hash: str
    model_run_id: UUID
    requested_identity: ModelIdentity
    actual_identity: ModelIdentity
    decision: SpeakerModelDecision
    speaker: SpeakerRef
    casting: CastingDecision
    attribution: AttributionEvidence
    authority: CloudAuthorityRecord

    def __post_init__(self) -> None:
        _require_uuid(self.segment_id, field_name="result segment_id")
        _require_uuid(self.model_run_id, field_name="result model_run_id")
        _require_sha256(self.source_local_hash, field_name="result source_local_hash")
        if self.requested_identity != self.actual_identity:
            raise ValueError("result requested/actual model identities differ")
        if self.decision.segment_id != self.segment_id:
            raise ValueError("result decision belongs to another segment")
        if self.decision.speaker != self.speaker:
            raise ValueError("result speaker differs from the model decision")
        if self.authority.attribution != self.attribution:
            raise ValueError("result authority attribution drifted")
        if (
            self.authority.segment_id != self.segment_id
            or self.authority.source_local_hash != self.source_local_hash
            or self.authority.model_fingerprint != self.actual_identity.fingerprint
            or self.authority.speaker_target_hash
            != speaker_target_hash(self.speaker, self.casting)
        ):
            raise ValueError("result authority is not bound to the exact decision")


def build_minimal_cloud_windows(
    segments: Sequence[CloudSourceSegment],
) -> tuple[MinimalCloudWindow, ...]:
    """Build one radius-one window per uncertain target, never per context row."""

    if isinstance(segments, (str, bytes)):
        raise ValueError("segments must be a source segment sequence")
    ordered = tuple(segments)
    if not all(type(item) is CloudSourceSegment for item in ordered):
        raise ValueError("segments must contain CloudSourceSegment values")
    ids = [item.segment_id for item in ordered]
    ordinals = [item.ordinal for item in ordered]
    if len(ids) != len(set(ids)) or len(ordinals) != len(set(ordinals)):
        raise ValueError("source segment ids and ordinals must be unique")
    if ordinals != sorted(ordinals):
        raise ValueError("source segments must use increasing source order")
    windows: list[MinimalCloudWindow] = []
    for index, segment in enumerate(ordered):
        if not segment.needs_cloud_analysis:
            continue
        windows.append(
            MinimalCloudWindow(
                target=segment,
                context_before=(ordered[index - 1],) if index > 0 else (),
                context_after=(ordered[index + 1],) if index + 1 < len(ordered) else (),
            )
        )
    return tuple(windows)


def _context_fragment(
    segment: CloudSourceSegment, *, before_target: bool
) -> SpeakerTextFragment:
    text = segment.source_text
    truncated = len(text) > MAX_CONTEXT_CHARACTERS
    if truncated:
        text = (
            text[-MAX_CONTEXT_CHARACTERS:]
            if before_target
            else text[:MAX_CONTEXT_CHARACTERS]
        )
    return SpeakerTextFragment(
        segment_id=segment.segment_id,
        text=text,
        truncated=truncated,
    )


def _request_for_window(window: MinimalCloudWindow) -> SpeakerModelRequest:
    candidates = tuple(item.model_candidate for item in window.target.candidates)
    return SpeakerModelRequest(
        target=SpeakerTextFragment(
            segment_id=window.target.segment_id,
            text=window.target.source_text,
            truncated=False,
        ),
        context_before=tuple(
            _context_fragment(item, before_target=True)
            for item in window.context_before
        ),
        context_after=tuple(
            _context_fragment(item, before_target=False)
            for item in window.context_after
        ),
        scene_hint=window.target.scene_hint,
        previous_speaker=window.target.previous_speaker,
        candidates=candidates,
    )


def cloud_request_for_window(window: MinimalCloudWindow) -> SpeakerModelRequest:
    """Expose the exact outbound request for adapters/tests without performing I/O."""

    if type(window) is not MinimalCloudWindow:
        raise ValueError("window must be MinimalCloudWindow")
    return _request_for_window(window)


def _static_consent_check(
    *,
    scope: CloudAnalysisScope,
    consent: CloudConsentSnapshot,
    requested_identity: ModelIdentity,
) -> None:
    if not consent.active or (
        consent.purpose != CLOUD_CONSENT_PURPOSE
        or consent.data_scope != CLOUD_CONSENT_DATA_SCOPE
        or consent.notice_version != CLOUD_CONSENT_NOTICE_VERSION
    ):
        raise _fail(CloudAnalysisFailureCode.CONSENT_REVOKED_BEFORE_CALL)
    if consent.novel_id != scope.novel_id or (
        consent.provider_id != requested_identity.provider_id
        or consent.model_id != requested_identity.model_id
    ):
        raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION)


def _fresh_consent_check(
    guard: CloudAnalysisGuard,
    *,
    scope: CloudAnalysisScope,
    consent: CloudConsentSnapshot,
    requested_identity: ModelIdentity,
) -> None:
    try:
        active = guard.consent_is_active(
            scope=scope,
            consent=consent,
            requested_identity=requested_identity,
        )
    except Exception:
        raise _fail(CloudAnalysisFailureCode.ANALYZER_RUNTIME) from None
    if type(active) is not bool:
        raise _fail(CloudAnalysisFailureCode.ANALYZER_RUNTIME)
    if not active:
        raise _fail(CloudAnalysisFailureCode.CONSENT_REVOKED_BEFORE_CALL)


def _source_segments(window: MinimalCloudWindow) -> tuple[CloudSourceSegment, ...]:
    return (*window.context_before, window.target, *window.context_after)


def _fresh_source_check(
    guard: CloudAnalysisGuard,
    *,
    scope: CloudAnalysisScope,
    window: MinimalCloudWindow,
) -> None:
    for segment in _source_segments(window):
        try:
            current = guard.source_is_current(
                scope=scope,
                segment_id=segment.segment_id,
                source_local_hash=segment.source_local_hash,
            )
        except Exception:
            raise _fail(CloudAnalysisFailureCode.ANALYZER_RUNTIME) from None
        if type(current) is not bool:
            raise _fail(CloudAnalysisFailureCode.ANALYZER_RUNTIME)
        if not current:
            raise _fail(CloudAnalysisFailureCode.INPUT_FINGERPRINT_CHANGED)


def _resolve_server_decision(
    window: MinimalCloudWindow,
    decision: SpeakerModelDecision,
) -> tuple[SpeakerRef, CastingDecision]:
    if decision.segment_id != window.target.segment_id:
        raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION)
    if decision.speaker.kind is SpeakerKind.UNKNOWN:
        return (
            decision.speaker,
            CastingDecision(
                candidate_targets=(),
                final_target=None,
                origin=CastingDecisionOrigin.UNRESOLVED,
            ),
        )
    for candidate in window.target.candidates:
        if candidate.model_candidate.speaker == decision.speaker:
            return decision.speaker, candidate.casting
    raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION)


async def analyze_cloud_window(
    *,
    scope: CloudAnalysisScope,
    window: MinimalCloudWindow,
    consent: CloudConsentSnapshot,
    model_run_id: UUID,
    requested_identity: ModelIdentity,
    digest_key: HmacDigestKey,
    guard: CloudAnalysisGuard,
    adapter: SpeakerModelAdapter | None,
) -> CloudAnalysisResult:
    """Analyze one uncertain target and return immutable, exact T3-A evidence."""

    if type(scope) is not CloudAnalysisScope:
        raise TypeError("scope must be CloudAnalysisScope")
    if type(window) is not MinimalCloudWindow:
        raise TypeError("window must be MinimalCloudWindow")
    if type(consent) is not CloudConsentSnapshot:
        raise TypeError("consent must be CloudConsentSnapshot")
    try:
        _require_uuid(model_run_id, field_name="model_run_id")
    except ValueError:
        raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION) from None
    if type(requested_identity) is not ModelIdentity:
        raise TypeError("requested_identity must be ModelIdentity")
    if type(digest_key) is not HmacDigestKey:
        raise TypeError("digest_key must be HmacDigestKey")

    _static_consent_check(
        scope=scope,
        consent=consent,
        requested_identity=requested_identity,
    )
    _fresh_consent_check(
        guard,
        scope=scope,
        consent=consent,
        requested_identity=requested_identity,
    )
    _fresh_source_check(guard, scope=scope, window=window)
    if adapter is None:
        raise _fail(CloudAnalysisFailureCode.ADAPTER_UNAVAILABLE)

    request = _request_for_window(window)
    request_json = speaker_model_request_to_json(request)
    input_digest = digest_key.digest(request_json.encode("utf-8"))
    try:
        reply = await adapter.analyze_speaker(
            request_json=request_json,
            requested_identity=requested_identity,
        )
    except SpeakerModelUnavailableError:
        raise _fail(CloudAnalysisFailureCode.ADAPTER_UNAVAILABLE) from None
    except Exception:
        raise _fail(CloudAnalysisFailureCode.ANALYZER_RUNTIME) from None
    if type(reply) is not TrustedSpeakerModelReply:
        raise _fail(CloudAnalysisFailureCode.MODEL_OUTPUT_SCHEMA_INVALID)
    if reply.actual_identity != requested_identity:
        raise _fail(CloudAnalysisFailureCode.MODEL_IDENTITY_MISMATCH)
    try:
        decision = parse_speaker_model_response(reply.response_json)
    except SpeakerModelContractError:
        raise _fail(CloudAnalysisFailureCode.MODEL_OUTPUT_SCHEMA_INVALID) from None
    speaker, casting = _resolve_server_decision(window, decision)

    # A revoked consent or changed source invalidates a late reply.  The frozen
    # taxonomy has one consent failure code; it is used at both acceptance
    # boundaries while the result remains unpublished.
    _fresh_consent_check(
        guard,
        scope=scope,
        consent=consent,
        requested_identity=requested_identity,
    )
    _fresh_source_check(guard, scope=scope, window=window)

    output_digest = digest_key.digest(
        canonical_json_bytes(speaker_model_decision_to_payload(decision))
    )
    character_ids = tuple(
        sorted(
            {
                item.model_candidate.speaker.character_id
                for item in window.target.candidates
                if item.model_candidate.speaker.character_id is not None
            },
            key=str,
        )
    )
    attribution = AttributionEvidence(
        origin=AttributionOrigin.CLOUD_ASSISTED,
        rule_codes=tuple(item.value for item in decision.evidence_codes),
        candidate_character_ids=character_ids,
        consent_id=consent.consent_id,
        model_run_id=model_run_id,
        input_digest_key_id=digest_key.key_id,
        input_digest=input_digest,
        output_digest=output_digest,
    )
    authority = CloudAuthorityRecord(
        attribution=attribution,
        model_fingerprint=reply.actual_identity.fingerprint,
        segment_id=window.target.segment_id,
        source_local_hash=window.target.source_local_hash,
        speaker_target_hash=speaker_target_hash(speaker, casting),
    )
    return CloudAnalysisResult(
        segment_id=window.target.segment_id,
        source_local_hash=window.target.source_local_hash,
        model_run_id=model_run_id,
        requested_identity=requested_identity,
        actual_identity=reply.actual_identity,
        decision=decision,
        speaker=speaker,
        casting=casting,
        attribution=attribution,
        authority=authority,
    )


async def analyze_uncertain_segments(
    *,
    scope: CloudAnalysisScope,
    segments: Sequence[CloudSourceSegment],
    consent: CloudConsentSnapshot,
    model_run_ids: Mapping[UUID, UUID],
    requested_identity: ModelIdentity,
    digest_key: HmacDigestKey,
    guard: CloudAnalysisGuard,
    adapter: SpeakerModelAdapter | None,
) -> tuple[CloudAnalysisResult, ...]:
    """Analyze only uncertain targets; any failure returns no publishable batch."""

    windows = build_minimal_cloud_windows(segments)
    target_ids = {item.target.segment_id for item in windows}
    if set(model_run_ids) != target_ids:
        raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION)
    run_ids = tuple(model_run_ids.values())
    try:
        for run_id in run_ids:
            _require_uuid(run_id, field_name="model_run_id")
    except ValueError:
        raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION) from None
    if len(run_ids) != len(set(run_ids)):
        raise _fail(CloudAnalysisFailureCode.SCOPE_VIOLATION)
    if not windows:
        return ()

    results: list[CloudAnalysisResult] = []
    for window in windows:
        results.append(
            await analyze_cloud_window(
                scope=scope,
                window=window,
                consent=consent,
                model_run_id=model_run_ids[window.target.segment_id],
                requested_identity=requested_identity,
                digest_key=digest_key,
                guard=guard,
                adapter=adapter,
            )
        )
    return tuple(results)


__all__ = [
    "CLOUD_CONSENT_DATA_SCOPE",
    "CLOUD_CONSENT_NOTICE_VERSION",
    "CLOUD_CONSENT_PURPOSE",
    "CLOUD_CONTEXT_RADIUS",
    "CLOUD_DIGEST_ALGORITHM",
    "BoundSpeakerCandidate",
    "CloudAnalysisFailure",
    "CloudAnalysisFailureCode",
    "CloudAnalysisGuard",
    "CloudAnalysisResult",
    "CloudAnalysisScope",
    "CloudConsentSnapshot",
    "CloudSourceSegment",
    "HmacDigestKey",
    "MinimalCloudWindow",
    "analyze_cloud_window",
    "analyze_uncertain_segments",
    "build_minimal_cloud_windows",
    "cloud_request_for_window",
]
