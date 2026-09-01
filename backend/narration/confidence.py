"""Fail-closed confidence and manual-override inheritance rules for T3.

Confidence levels in this module are explainable policy tiers, never numeric
probabilities.  Manual override inheritance is a separate authority decision:
local rule confidence can never manufacture or approve an override source.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Final, Sequence
from uuid import RFC_4122, UUID

from .contracts import ConfidenceLevel, issue_severity
from .script_contracts import (
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    NarrationScriptContract,
    OverrideKind,
    OverrideProvenance,
    ScriptIssueContract,
    ScriptVersionState,
    SegmentContract,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
)

SPEAKER_CONFIDENCE_POLICY_VERSION: Final = "speaker-confidence-policy/1"
OVERRIDE_INHERITANCE_POLICY_VERSION: Final = "override-inheritance-policy/1"

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ConfidenceRuleError(ValueError):
    """Raised for malformed or non-server-shaped confidence inputs."""


class ModelConsistency(str, Enum):
    """Optional already-authorized corroboration; this module calls no model."""

    NOT_EVALUATED = "not_evaluated"
    CONSISTENT = "consistent"
    CONFLICTING = "conflicting"


def _require_exact_int(
    value: object, *, field_name: str, minimum: int = 0, maximum: int
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfidenceRuleError(
            f"{field_name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _require_exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ConfidenceRuleError(f"{field_name} must be an exact boolean")
    return value


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not UUID:
        raise ConfidenceRuleError(f"{field_name} must be UUID")
    if value.variant != RFC_4122 or value.version not in {1, 2, 3, 4, 5}:
        raise ConfidenceRuleError(f"{field_name} must be an RFC-4122 UUID v1-v5")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ConfidenceRuleError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_sha256(value, field_name=field_name)


def _require_text(value: object, *, field_name: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ConfidenceRuleError(
            f"{field_name} must be a non-empty string of at most {maximum} characters"
        )
    if value != unicodedata.normalize("NFC", value):
        raise ConfidenceRuleError(f"{field_name} must be Unicode NFC")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ConfidenceRuleError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


@dataclass(frozen=True, slots=True)
class SpeakerConfidenceSignals:
    """Canonical discrete signals supplied by attribution/corroboration stages.

    ``identity_candidate_count`` counts distinct final identity candidates, not
    occurrences of an alias in text.  ``supporting_rule_count`` counts
    independent local rule families after de-duplication by the caller.
    """

    identity_candidate_count: int
    direct_identity_match: bool
    supporting_rule_count: int
    contextual_rule_count: int
    identity_conflict: bool = False
    model_consistency: ModelConsistency = ModelConsistency.NOT_EVALUATED
    policy_version: str = SPEAKER_CONFIDENCE_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_exact_int(
            self.identity_candidate_count,
            field_name="identity_candidate_count",
            maximum=32,
        )
        _require_exact_bool(
            self.direct_identity_match, field_name="direct_identity_match"
        )
        _require_exact_int(
            self.supporting_rule_count,
            field_name="supporting_rule_count",
            maximum=16,
        )
        _require_exact_int(
            self.contextual_rule_count,
            field_name="contextual_rule_count",
            maximum=16,
        )
        _require_exact_bool(self.identity_conflict, field_name="identity_conflict")
        if type(self.model_consistency) is not ModelConsistency:
            raise ConfidenceRuleError("model_consistency must be ModelConsistency")
        if self.policy_version != SPEAKER_CONFIDENCE_POLICY_VERSION:
            raise ConfidenceRuleError("unknown speaker confidence policy version")


@dataclass(frozen=True, slots=True)
class SpeakerConfidenceAssessment:
    """T3-A-compatible speaker confidence, issue codes, and rule evidence."""

    level: ConfidenceLevel
    issue_codes: tuple[str, ...]
    evidence_codes: tuple[str, ...]
    policy_version: str = SPEAKER_CONFIDENCE_POLICY_VERSION

    def __post_init__(self) -> None:
        if type(self.level) is not ConfidenceLevel:
            raise ConfidenceRuleError("level must be ConfidenceLevel")
        for field_name in ("issue_codes", "evidence_codes"):
            values = getattr(self, field_name)
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise ConfidenceRuleError(
                    f"{field_name} must be a unique canonically sorted tuple"
                )
        expected = {
            ConfidenceLevel.HIGH: (),
            ConfidenceLevel.MEDIUM: ("W_SPEAKER_MEDIUM_CONFIDENCE",),
            ConfidenceLevel.LOW: ("B_SPEAKER_LOW_CONFIDENCE",),
            ConfidenceLevel.UNKNOWN: (
                "B_SPEAKER_LOW_CONFIDENCE",
                "B_SPEAKER_UNKNOWN",
            ),
        }[self.level]
        if self.issue_codes != tuple(sorted(expected)):
            raise ConfidenceRuleError(
                "issue_codes differ from the frozen confidence taxonomy mapping"
            )
        if not self.evidence_codes:
            raise ConfidenceRuleError("confidence assessment requires rule evidence")
        if self.policy_version != SPEAKER_CONFIDENCE_POLICY_VERSION:
            raise ConfidenceRuleError("unknown speaker confidence policy version")

    def to_script_issues(self, *, segment_id: UUID) -> tuple[ScriptIssueContract, ...]:
        _require_uuid(segment_id, field_name="segment_id")
        return tuple(
            ScriptIssueContract(
                code=code,
                severity=issue_severity(code),
                segment_id=segment_id,
            )
            for code in self.issue_codes
        )


def _assessment(
    level: ConfidenceLevel, *evidence_codes: str
) -> SpeakerConfidenceAssessment:
    issue_codes = {
        ConfidenceLevel.HIGH: (),
        ConfidenceLevel.MEDIUM: ("W_SPEAKER_MEDIUM_CONFIDENCE",),
        ConfidenceLevel.LOW: ("B_SPEAKER_LOW_CONFIDENCE",),
        ConfidenceLevel.UNKNOWN: (
            "B_SPEAKER_LOW_CONFIDENCE",
            "B_SPEAKER_UNKNOWN",
        ),
    }[level]
    return SpeakerConfidenceAssessment(
        level=level,
        issue_codes=tuple(sorted(issue_codes)),
        evidence_codes=tuple(sorted(set(evidence_codes))),
    )


def assess_speaker_confidence(
    *, speaker: SpeakerRef, signals: SpeakerConfidenceSignals
) -> SpeakerConfidenceAssessment:
    """Apply the frozen v1 discrete threshold tree.

    Precedence is fail-closed: unknown identity, explicit conflicts, and
    corroboration conflicts are evaluated before any positive evidence.
    """

    if type(speaker) is not SpeakerRef:
        raise ConfidenceRuleError("speaker must be SpeakerRef")
    if type(signals) is not SpeakerConfidenceSignals:
        raise ConfidenceRuleError("signals must be SpeakerConfidenceSignals")

    if speaker.kind is SpeakerKind.UNKNOWN:
        codes = ["confidence.identity.unknown"]
        if signals.identity_conflict:
            codes.append("confidence.identity.conflict")
        return _assessment(ConfidenceLevel.UNKNOWN, *codes)

    if signals.identity_conflict:
        return _assessment(
            ConfidenceLevel.LOW,
            "confidence.identity.conflict",
            "confidence.identity.resolved_ref_rejected",
        )
    if signals.identity_candidate_count != 1:
        return _assessment(
            ConfidenceLevel.LOW,
            "confidence.identity.candidate_count_not_one",
        )
    if signals.model_consistency is ModelConsistency.CONFLICTING:
        return _assessment(
            ConfidenceLevel.LOW,
            "confidence.corroboration.conflicting",
        )

    if signals.direct_identity_match:
        return _assessment(
            ConfidenceLevel.HIGH,
            "confidence.identity.direct_unique",
        )
    if signals.supporting_rule_count >= 2:
        return _assessment(
            ConfidenceLevel.HIGH,
            "confidence.local_rules.corroborated",
        )
    if (
        signals.supporting_rule_count == 1
        and signals.model_consistency is ModelConsistency.CONSISTENT
    ):
        return _assessment(
            ConfidenceLevel.HIGH,
            "confidence.local_rule.single",
            "confidence.corroboration.consistent",
        )
    if signals.supporting_rule_count == 1:
        return _assessment(
            ConfidenceLevel.MEDIUM,
            "confidence.local_rule.single",
        )
    if signals.contextual_rule_count >= 1:
        return _assessment(
            ConfidenceLevel.MEDIUM,
            "confidence.context.unique",
        )
    if signals.model_consistency is ModelConsistency.CONSISTENT:
        return _assessment(
            ConfidenceLevel.MEDIUM,
            "confidence.corroboration.only",
        )
    return _assessment(
        ConfidenceLevel.LOW,
        "confidence.evidence.insufficient",
    )


class OverrideInheritanceReason(str, Enum):
    ELIGIBLE = "eligible"
    CROSS_NOVEL = "cross_novel"
    SOURCE_NOT_APPROVED = "source_not_approved"
    SOURCE_NOT_MANUAL = "source_not_manual"
    SOURCE_PROVENANCE_INVALID = "source_provenance_invalid"
    SOURCE_NOT_AUTHORIZED = "source_not_authorized"
    SAME_SCRIPT_VERSION = "same_script_version"
    AUDIT_ACTOR_UNAUTHORIZED = "audit_actor_unauthorized"
    AUDIT_ACTION_REUSED = "audit_action_reused"
    AUDIT_TIME_INVALID = "audit_time_invalid"
    LOCAL_HASH_MISMATCH = "local_hash_mismatch"
    ANCHOR_VALUE_MISMATCH = "anchor_value_mismatch"
    ANCHOR_NOT_UNIQUE = "anchor_not_unique"
    SPEAKER_TARGET_MISMATCH = "speaker_target_mismatch"


@dataclass(frozen=True, slots=True)
class ManualOverrideSource:
    """Immutable server-loaded source snapshot considered for inheritance."""

    novel_id: UUID
    script_version_id: UUID
    segment_id: UUID
    script_immutable_hash: str
    script_state: ScriptVersionState
    local_hash: str
    anchor_before_hash: str | None
    anchor_after_hash: str | None
    speaker: SpeakerRef
    casting: CastingDecision
    attribution_origin: AttributionOrigin
    manual_override: bool
    provenance: OverrideProvenance | None

    def __post_init__(self) -> None:
        for field_name in ("novel_id", "script_version_id", "segment_id"):
            _require_uuid(getattr(self, field_name), field_name=field_name)
        _require_sha256(
            self.script_immutable_hash, field_name="script_immutable_hash"
        )
        if type(self.script_state) is not ScriptVersionState:
            raise ConfidenceRuleError("script_state must be ScriptVersionState")
        _require_sha256(self.local_hash, field_name="local_hash")
        _require_optional_sha256(
            self.anchor_before_hash, field_name="anchor_before_hash"
        )
        _require_optional_sha256(
            self.anchor_after_hash, field_name="anchor_after_hash"
        )
        if type(self.speaker) is not SpeakerRef:
            raise ConfidenceRuleError("speaker must be SpeakerRef")
        if type(self.casting) is not CastingDecision:
            raise ConfidenceRuleError("casting must be CastingDecision")
        if type(self.attribution_origin) is not AttributionOrigin:
            raise ConfidenceRuleError(
                "attribution_origin must be AttributionOrigin"
            )
        _require_exact_bool(self.manual_override, field_name="manual_override")
        if self.provenance is not None and type(
            self.provenance
        ) is not OverrideProvenance:
            raise ConfidenceRuleError(
                "provenance must be OverrideProvenance or None"
            )


def manual_override_source(
    script: NarrationScriptContract,
    segment: SegmentContract,
) -> ManualOverrideSource:
    """Build the exact immutable source snapshot used by inheritance policy v1."""

    if type(script) is not NarrationScriptContract:
        raise ConfidenceRuleError("script must be NarrationScriptContract")
    if type(segment) is not SegmentContract or segment not in script.segments:
        raise ConfidenceRuleError("segment must belong to the supplied script")
    return ManualOverrideSource(
        novel_id=script.novel_id,
        script_version_id=script.script_version_id,
        segment_id=segment.segment_id,
        script_immutable_hash=script.immutable_hash,
        script_state=script.state,
        local_hash=segment.local_hash,
        anchor_before_hash=segment.inheritance_anchor_before_hash,
        anchor_after_hash=segment.inheritance_anchor_after_hash,
        speaker=segment.speaker,
        casting=segment.casting,
        attribution_origin=segment.attribution.origin,
        manual_override=segment.manual_override,
        provenance=segment.attribution.override_provenance,
    )


def segment_inheritance_anchors(
    segments: Sequence[object],
    index: int,
) -> tuple[str | None, str | None]:
    """Return stable immediate-neighbour hashes for one source-bound segment."""

    if not isinstance(segments, Sequence) or not segments:
        raise ConfidenceRuleError("segments must be a non-empty sequence")
    if type(index) is not int or not 0 <= index < len(segments):
        raise ConfidenceRuleError("segment index is outside the sequence")
    local_hashes = tuple(
        _require_sha256(
            getattr(segment, "local_hash", None),
            field_name="segment local_hash",
        )
        for segment in segments
    )
    return (
        local_hashes[index - 1] if index > 0 else None,
        local_hashes[index + 1] if index + 1 < len(local_hashes) else None,
    )


def _source_provenance_is_exact(source: ManualOverrideSource) -> bool:
    provenance = source.provenance
    if provenance is None:
        return False
    expected_kind = {
        AttributionOrigin.MANUAL_OVERRIDE: OverrideKind.MANUAL_CURRENT,
        AttributionOrigin.INHERITED_OVERRIDE: OverrideKind.INHERITED,
    }.get(source.attribution_origin)
    return (
        expected_kind is not None
        and provenance.kind is expected_kind
        and provenance.source_local_hash == source.local_hash
        and provenance.source_anchor_before_hash == source.anchor_before_hash
        and provenance.source_anchor_after_hash == source.anchor_after_hash
        and provenance.speaker_target_hash
        == speaker_target_hash(source.speaker, source.casting)
    )


@dataclass(frozen=True, slots=True)
class OverrideInheritanceAuthority:
    """Server authority bound to exact approved source snapshots and one owner."""

    novel_id: UUID
    owner_actor_id: str
    authorized_sources: frozenset[ManualOverrideSource]
    policy_version: str = OVERRIDE_INHERITANCE_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="authority novel_id")
        _require_text(
            self.owner_actor_id,
            field_name="authority owner_actor_id",
            maximum=120,
        )
        if type(self.authorized_sources) is not frozenset or not all(
            type(source) is ManualOverrideSource
            for source in self.authorized_sources
        ):
            raise ConfidenceRuleError(
                "authorized_sources must be a frozenset of ManualOverrideSource"
            )
        for source in self.authorized_sources:
            if source.novel_id != self.novel_id:
                raise ConfidenceRuleError(
                    "authorized source belongs to another novel"
                )
            if source.script_state is not ScriptVersionState.APPROVED:
                raise ConfidenceRuleError(
                    "authorized source must come from an approved script"
                )
            if not source.manual_override or not _source_provenance_is_exact(source):
                raise ConfidenceRuleError(
                    "authorized source must be an exact manual-derived override"
                )
            if (
                source.provenance is None
                or source.provenance.owner_actor_id != self.owner_actor_id
            ):
                raise ConfidenceRuleError(
                    "authorized source owner differs from authority owner"
                )
        if self.policy_version != OVERRIDE_INHERITANCE_POLICY_VERSION:
            raise ConfidenceRuleError("unknown override inheritance policy version")


@dataclass(frozen=True, slots=True)
class AnchorUniquenessEvidence:
    """Server-derived occurrence counts for the target immutable source."""

    local_hash_match_count: int
    before_anchor_match_count: int
    after_anchor_match_count: int
    combined_match_count: int
    target_at_document_start: bool
    target_at_document_end: bool

    def __post_init__(self) -> None:
        for field_name in (
            "local_hash_match_count",
            "before_anchor_match_count",
            "after_anchor_match_count",
            "combined_match_count",
        ):
            _require_exact_int(
                getattr(self, field_name), field_name=field_name, maximum=1_000_000
            )
        _require_exact_bool(
            self.target_at_document_start,
            field_name="target_at_document_start",
        )
        _require_exact_bool(
            self.target_at_document_end,
            field_name="target_at_document_end",
        )


def segment_anchor_uniqueness(
    segments: Sequence[object],
    index: int,
) -> AnchorUniquenessEvidence:
    """Prove v1 anchor uniqueness from the complete server-side segment list."""

    before_hash, after_hash = segment_inheritance_anchors(segments, index)
    local_hashes = tuple(
        _require_sha256(
            getattr(segment, "local_hash", None),
            field_name="segment local_hash",
        )
        for segment in segments
    )
    target_hash = local_hashes[index]
    combined_count = sum(
        1
        for candidate_index, candidate_hash in enumerate(local_hashes)
        if candidate_hash == target_hash
        and (local_hashes[candidate_index - 1] if candidate_index > 0 else None)
        == before_hash
        and (
            local_hashes[candidate_index + 1]
            if candidate_index + 1 < len(local_hashes)
            else None
        )
        == after_hash
    )
    return AnchorUniquenessEvidence(
        local_hash_match_count=local_hashes.count(target_hash),
        before_anchor_match_count=(
            0 if before_hash is None else local_hashes.count(before_hash)
        ),
        after_anchor_match_count=(
            0 if after_hash is None else local_hashes.count(after_hash)
        ),
        combined_match_count=combined_count,
        target_at_document_start=index == 0,
        target_at_document_end=index + 1 == len(local_hashes),
    )


@dataclass(frozen=True, slots=True)
class OverrideInheritanceTarget:
    novel_id: UUID
    script_version_id: UUID
    segment_id: UUID
    local_hash: str
    anchor_before_hash: str | None
    anchor_after_hash: str | None
    speaker: SpeakerRef
    casting: CastingDecision
    uniqueness: AnchorUniquenessEvidence

    def __post_init__(self) -> None:
        for field_name in ("novel_id", "script_version_id", "segment_id"):
            _require_uuid(getattr(self, field_name), field_name=field_name)
        _require_sha256(self.local_hash, field_name="target local_hash")
        _require_optional_sha256(
            self.anchor_before_hash, field_name="target anchor_before_hash"
        )
        _require_optional_sha256(
            self.anchor_after_hash, field_name="target anchor_after_hash"
        )
        if type(self.speaker) is not SpeakerRef:
            raise ConfidenceRuleError("target speaker must be SpeakerRef")
        if type(self.casting) is not CastingDecision:
            raise ConfidenceRuleError("target casting must be CastingDecision")
        if type(self.uniqueness) is not AnchorUniquenessEvidence:
            raise ConfidenceRuleError(
                "target uniqueness must be AnchorUniquenessEvidence"
            )


@dataclass(frozen=True, slots=True)
class InheritanceAuditStamp:
    """Server-issued identity and time for the new inherited action."""

    action_id: UUID
    owner_actor_id: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.action_id, field_name="audit action_id")
        _require_text(
            self.owner_actor_id,
            field_name="audit owner_actor_id",
            maximum=120,
        )
        if type(self.recorded_at) is not datetime:
            raise ConfidenceRuleError("audit recorded_at must be datetime")
        offset = self.recorded_at.utcoffset()
        if offset != timedelta(0):
            raise ConfidenceRuleError("audit recorded_at must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class OverrideInheritanceDecision:
    eligible: bool
    reason: OverrideInheritanceReason
    provenance: OverrideProvenance | None
    policy_version: str = OVERRIDE_INHERITANCE_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_exact_bool(self.eligible, field_name="eligible")
        if type(self.reason) is not OverrideInheritanceReason:
            raise ConfidenceRuleError("reason must be OverrideInheritanceReason")
        if self.provenance is not None and type(
            self.provenance
        ) is not OverrideProvenance:
            raise ConfidenceRuleError(
                "provenance must be OverrideProvenance or None"
            )
        if self.eligible != (self.reason is OverrideInheritanceReason.ELIGIBLE):
            raise ConfidenceRuleError("eligible and reason disagree")
        if self.eligible != (self.provenance is not None):
            raise ConfidenceRuleError("eligible and provenance shape disagree")
        if self.policy_version != OVERRIDE_INHERITANCE_POLICY_VERSION:
            raise ConfidenceRuleError("unknown override inheritance policy version")

    def to_attribution(self) -> AttributionEvidence | None:
        if self.provenance is None:
            return None
        return AttributionEvidence(
            origin=AttributionOrigin.INHERITED_OVERRIDE,
            override_provenance=self.provenance,
        )

    def to_script_issues(self, *, segment_id: UUID) -> tuple[ScriptIssueContract, ...]:
        _require_uuid(segment_id, field_name="segment_id")
        if not self.eligible:
            return ()
        code = "W_MANUAL_OVERRIDE_INHERITED"
        return (
            ScriptIssueContract(
                code=code,
                severity=issue_severity(code),
                segment_id=segment_id,
            ),
        )


def _rejected(reason: OverrideInheritanceReason) -> OverrideInheritanceDecision:
    return OverrideInheritanceDecision(
        eligible=False,
        reason=reason,
        provenance=None,
    )


def _anchors_are_unique(target: OverrideInheritanceTarget) -> bool:
    proof = target.uniqueness
    # Repeated local text remains review-required even if a pair of surrounding
    # anchors could appear to disambiguate it.  This is the conservative v1 rule.
    if proof.local_hash_match_count != 1 or proof.combined_match_count != 1:
        return False
    if target.anchor_before_hash is None:
        if not proof.target_at_document_start or proof.before_anchor_match_count != 0:
            return False
    elif proof.target_at_document_start or proof.before_anchor_match_count != 1:
        return False
    if target.anchor_after_hash is None:
        if not proof.target_at_document_end or proof.after_anchor_match_count != 0:
            return False
    elif proof.target_at_document_end or proof.after_anchor_match_count != 1:
        return False
    return True


def decide_override_inheritance(
    *,
    source: ManualOverrideSource,
    target: OverrideInheritanceTarget,
    authority: OverrideInheritanceAuthority,
    audit: InheritanceAuditStamp,
) -> OverrideInheritanceDecision:
    """Inherit only an exact, approved, authorized manual-derived override.

    All source/target fingerprints and anchor counts must be loaded or derived by
    the server.  A negative result never carries provenance, so callers cannot
    accidentally assemble it as an inherited decision.
    """

    if type(source) is not ManualOverrideSource:
        raise ConfidenceRuleError("source must be ManualOverrideSource")
    if type(target) is not OverrideInheritanceTarget:
        raise ConfidenceRuleError("target must be OverrideInheritanceTarget")
    if type(authority) is not OverrideInheritanceAuthority:
        raise ConfidenceRuleError("authority must be OverrideInheritanceAuthority")
    if type(audit) is not InheritanceAuditStamp:
        raise ConfidenceRuleError("audit must be InheritanceAuditStamp")

    if source.novel_id != target.novel_id or target.novel_id != authority.novel_id:
        return _rejected(OverrideInheritanceReason.CROSS_NOVEL)
    if source.script_state is not ScriptVersionState.APPROVED:
        return _rejected(OverrideInheritanceReason.SOURCE_NOT_APPROVED)
    if not source.manual_override or source.attribution_origin not in {
        AttributionOrigin.MANUAL_OVERRIDE,
        AttributionOrigin.INHERITED_OVERRIDE,
    }:
        return _rejected(OverrideInheritanceReason.SOURCE_NOT_MANUAL)
    if not _source_provenance_is_exact(source):
        return _rejected(OverrideInheritanceReason.SOURCE_PROVENANCE_INVALID)
    if source not in authority.authorized_sources:
        return _rejected(OverrideInheritanceReason.SOURCE_NOT_AUTHORIZED)
    if source.script_version_id == target.script_version_id:
        return _rejected(OverrideInheritanceReason.SAME_SCRIPT_VERSION)
    if audit.owner_actor_id != authority.owner_actor_id:
        return _rejected(OverrideInheritanceReason.AUDIT_ACTOR_UNAUTHORIZED)
    if source.provenance is None:
        # Kept explicit for type narrowing; the exact-provenance check above
        # already makes this branch unreachable for an eligible source.
        return _rejected(OverrideInheritanceReason.SOURCE_PROVENANCE_INVALID)
    if audit.action_id == source.provenance.action_id:
        return _rejected(OverrideInheritanceReason.AUDIT_ACTION_REUSED)
    if audit.recorded_at < source.provenance.recorded_at:
        return _rejected(OverrideInheritanceReason.AUDIT_TIME_INVALID)
    if source.local_hash != target.local_hash:
        return _rejected(OverrideInheritanceReason.LOCAL_HASH_MISMATCH)
    if (
        source.anchor_before_hash != target.anchor_before_hash
        or source.anchor_after_hash != target.anchor_after_hash
    ):
        return _rejected(OverrideInheritanceReason.ANCHOR_VALUE_MISMATCH)
    if not _anchors_are_unique(target):
        return _rejected(OverrideInheritanceReason.ANCHOR_NOT_UNIQUE)
    target_digest = speaker_target_hash(target.speaker, target.casting)
    if target_digest != speaker_target_hash(source.speaker, source.casting):
        return _rejected(OverrideInheritanceReason.SPEAKER_TARGET_MISMATCH)

    return OverrideInheritanceDecision(
        eligible=True,
        reason=OverrideInheritanceReason.ELIGIBLE,
        provenance=OverrideProvenance(
            kind=OverrideKind.INHERITED,
            action_id=audit.action_id,
            owner_actor_id=audit.owner_actor_id,
            recorded_at=audit.recorded_at,
            source_local_hash=target.local_hash,
            source_anchor_before_hash=target.anchor_before_hash,
            source_anchor_after_hash=target.anchor_after_hash,
            speaker_target_hash=target_digest,
            source_script_version_id=source.script_version_id,
            source_segment_id=source.segment_id,
            source_immutable_hash=source.script_immutable_hash,
        ),
    )


__all__ = [
    "AnchorUniquenessEvidence",
    "ConfidenceRuleError",
    "InheritanceAuditStamp",
    "ManualOverrideSource",
    "ModelConsistency",
    "OVERRIDE_INHERITANCE_POLICY_VERSION",
    "OverrideInheritanceAuthority",
    "OverrideInheritanceDecision",
    "OverrideInheritanceReason",
    "OverrideInheritanceTarget",
    "SPEAKER_CONFIDENCE_POLICY_VERSION",
    "SpeakerConfidenceAssessment",
    "SpeakerConfidenceSignals",
    "assess_speaker_confidence",
    "decide_override_inheritance",
    "manual_override_source",
    "segment_anchor_uniqueness",
    "segment_inheritance_anchors",
]
