"""Deterministic narration-script review and freeze policy.

This module is deliberately free of ORM, HTTP, model, worker, and media I/O.
It consumes the frozen T3-A script contract and returns an immutable decision
that the T3 integration owner can persist through the existing request/script
services.  In particular, client or model supplied severities are never an
authority and an ``analyze_only`` request can never freeze a script.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Final, Iterable
from uuid import UUID

from .contracts import (
    NARRATION_REVIEW_TAXONOMY_VERSION,
    ReviewIssueSeverity,
    UnknownTaxonomyCodeError,
    issue_severity,
)
from .script_contracts import (
    ApprovalActorType,
    AttributionOrigin,
    NarrationScriptContract,
    ScriptApproval,
    ScriptApprovalKind,
    ScriptContractError,
    ScriptIssueContract,
    ScriptReviewPolicy,
    ScriptVersionState,
    ensure_script_transition,
)


NARRATION_SCRIPT_REVIEW_VERSION: Final = "narration-script-review/1"


class ScriptReviewError(ValueError):
    """Base class for deterministic review-policy failures."""


class ReviewTaxonomyError(ScriptReviewError):
    """Raised when an analyzer/client attempts to change the frozen taxonomy."""


class ReviewStateError(ScriptReviewError):
    """Raised when a freeze action is not legal for the current script/request."""


class ReviewIntent(str, Enum):
    ANALYZE_ONLY = "analyze_only"
    CREATE = "create"
    UPDATE = "update"
    BATCH = "batch"


class ReviewDisposition(str, Enum):
    ANALYSIS_ONLY = "analysis_only"
    AUTO_FREEZE = "auto_freeze"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class ReviewIssueCandidate:
    """Untrusted analyzer output before server-owned classification."""

    code: str
    segment_id: UUID | None = None
    evidence_summary: str | None = None
    evidence_digest: str | None = None
    claimed_severity: str | ReviewIssueSeverity | None = None
    taxonomy_version: str = NARRATION_REVIEW_TAXONOMY_VERSION


@dataclass(frozen=True, slots=True)
class ReviewRequestContext:
    """Server-loaded request guard used by both automatic and manual paths."""

    request_id: UUID
    intent: ReviewIntent
    allows_edition: bool
    effective_policy: ScriptReviewPolicy
    force_review: bool = False
    verified_manual_review_parent: bool = False
    verified_non_review_parent: bool = False

    def __post_init__(self) -> None:
        if type(self.request_id) is not UUID:
            raise ReviewStateError("request_id must be a UUID")
        if type(self.intent) is not ReviewIntent:
            raise ReviewStateError("intent must be a ReviewIntent")
        if type(self.allows_edition) is not bool:
            raise ReviewStateError("allows_edition must be an exact boolean")
        if type(self.effective_policy) is not ScriptReviewPolicy:
            raise ReviewStateError("effective_policy must be a ScriptReviewPolicy")
        if type(self.force_review) is not bool:
            raise ReviewStateError("force_review must be an exact boolean")
        if type(self.verified_manual_review_parent) is not bool:
            raise ReviewStateError(
                "verified_manual_review_parent must be an exact boolean"
            )
        if type(self.verified_non_review_parent) is not bool:
            raise ReviewStateError(
                "verified_non_review_parent must be an exact boolean"
            )
        if self.verified_manual_review_parent and self.verified_non_review_parent:
            raise ReviewStateError("parent review classifications must be disjoint")
        if self.intent is ReviewIntent.ANALYZE_ONLY:
            if self.allows_edition:
                raise ReviewStateError("analyze_only cannot allow an edition")
        elif not self.allows_edition:
            raise ReviewStateError("generation intent must allow an edition")
        if self.force_review and self.effective_policy is not ScriptReviewPolicy.ALWAYS_REVIEW:
            raise ReviewStateError("force_review may only tighten to always_review")


@dataclass(frozen=True, slots=True)
class ScriptReviewDecision:
    disposition: ReviewDisposition
    state: ScriptVersionState
    warning_count: int
    blocker_count: int
    approval: ScriptApproval | None
    reason_code: str
    contract_version: str = NARRATION_SCRIPT_REVIEW_VERSION

    def __post_init__(self) -> None:
        if type(self.disposition) is not ReviewDisposition:
            raise ReviewStateError("disposition must be a ReviewDisposition")
        if type(self.state) is not ScriptVersionState:
            raise ReviewStateError("state must be a ScriptVersionState")
        if type(self.warning_count) is not int or self.warning_count < 0:
            raise ReviewStateError("warning_count must be a non-negative integer")
        if type(self.blocker_count) is not int or self.blocker_count < 0:
            raise ReviewStateError("blocker_count must be a non-negative integer")
        if self.contract_version != NARRATION_SCRIPT_REVIEW_VERSION:
            raise ReviewStateError("unknown script review contract version")
        if not self.reason_code or len(self.reason_code) > 96:
            raise ReviewStateError("reason_code must be a non-empty stable code")
        if self.disposition is ReviewDisposition.AUTO_FREEZE:
            if self.state is not ScriptVersionState.APPROVED:
                raise ReviewStateError("auto freeze decision must target approved state")
        elif self.approval is not None:
            raise ReviewStateError("non-freeze decisions cannot contain approval")


def classify_review_issue(candidate: ReviewIssueCandidate) -> ScriptIssueContract:
    """Turn one untrusted candidate into a frozen, server-classified issue."""

    if type(candidate) is not ReviewIssueCandidate:
        raise ReviewTaxonomyError("candidate must be a ReviewIssueCandidate")
    if candidate.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION:
        raise ReviewTaxonomyError("unknown narration review taxonomy version")
    try:
        severity = issue_severity(candidate.code)
    except UnknownTaxonomyCodeError as error:
        raise ReviewTaxonomyError(str(error)) from error
    claimed = candidate.claimed_severity
    if claimed is not None:
        claimed_value = claimed.value if type(claimed) is ReviewIssueSeverity else claimed
        if type(claimed_value) is not str or claimed_value != severity.value:
            raise ReviewTaxonomyError(
                f"severity for {candidate.code} is server-owned and must be {severity.value}"
            )
    try:
        return ScriptIssueContract(
            code=candidate.code,
            severity=severity,
            segment_id=candidate.segment_id,
            evidence_summary=candidate.evidence_summary,
            evidence_digest=candidate.evidence_digest,
        )
    except ScriptContractError as error:
        raise ReviewTaxonomyError(str(error)) from error


def classify_review_issues(
    candidates: Iterable[ReviewIssueCandidate],
) -> tuple[ScriptIssueContract, ...]:
    """Classify and canonically sort issues, rejecting duplicate evidence rows."""

    if isinstance(candidates, (str, bytes)):
        raise ReviewTaxonomyError("candidates must be an iterable of issue candidates")
    classified = [classify_review_issue(candidate) for candidate in candidates]
    classified.sort(
        key=lambda issue: (
            issue.code,
            str(issue.segment_id) if issue.segment_id else "",
            issue.evidence_digest or "",
        )
    )
    keys = [
        (issue.code, issue.segment_id, issue.evidence_digest) for issue in classified
    ]
    if len(keys) != len(set(keys)):
        raise ReviewTaxonomyError("duplicate review issue evidence row")
    return tuple(classified)


def recompute_issue_counts(
    issues: Iterable[ScriptIssueContract],
) -> tuple[int, int]:
    """Return ``(warning_count, blocker_count)`` from server-owned severity."""

    warnings = 0
    blockers = 0
    for issue in issues:
        if type(issue) is not ScriptIssueContract:
            raise ReviewTaxonomyError("issues must contain ScriptIssueContract values")
        try:
            expected = issue_severity(issue.code)
        except UnknownTaxonomyCodeError as error:
            raise ReviewTaxonomyError(str(error)) from error
        if issue.severity is not expected:
            raise ReviewTaxonomyError(
                f"severity for {issue.code} differs from the frozen taxonomy"
            )
        if expected is ReviewIssueSeverity.WARNING:
            warnings += 1
        else:
            blockers += 1
    return warnings, blockers


def _validate_script_and_request(
    script: NarrationScriptContract,
    context: ReviewRequestContext,
) -> tuple[int, int]:
    if type(script) is not NarrationScriptContract:
        raise ReviewStateError("script must be a NarrationScriptContract")
    if type(context) is not ReviewRequestContext:
        raise ReviewStateError("context must be a ReviewRequestContext")
    if script.effective_policy is not context.effective_policy:
        raise ReviewStateError("request and script review policies differ")
    has_parent = script.parent_version_id is not None
    classified_parent = (
        context.verified_manual_review_parent
        or context.verified_non_review_parent
    )
    if has_parent != classified_parent:
        raise ReviewStateError(
            "script parent must have one exhaustive server verification"
        )
    warning_count, blocker_count = recompute_issue_counts(script.issues)
    if (warning_count, blocker_count) != (
        script.warning_count,
        script.blocker_count,
    ):
        raise ReviewStateError("script issue counts differ from frozen issue rows")
    return warning_count, blocker_count


def decide_script_review(
    script: NarrationScriptContract,
    context: ReviewRequestContext,
) -> ScriptReviewDecision:
    """Choose the only legal post-analysis path without performing persistence."""

    warning_count, blocker_count = _validate_script_and_request(script, context)
    if script.state is ScriptVersionState.APPROVED:
        raise ReviewStateError("approved script version is terminal")
    if script.state not in {
        ScriptVersionState.ANALYZED,
        ScriptVersionState.REVIEW_REQUIRED,
    }:
        raise ReviewStateError("script is not materialized for review")
    if context.intent is ReviewIntent.ANALYZE_ONLY:
        return ScriptReviewDecision(
            disposition=ReviewDisposition.ANALYSIS_ONLY,
            state=script.state,
            warning_count=warning_count,
            blocker_count=blocker_count,
            approval=None,
            reason_code="ANALYZE_ONLY_NEVER_FREEZES",
        )
    if blocker_count > 0:
        return ScriptReviewDecision(
            disposition=ReviewDisposition.REVIEW_REQUIRED,
            state=ScriptVersionState.REVIEW_REQUIRED,
            warning_count=warning_count,
            blocker_count=blocker_count,
            approval=None,
            reason_code="SCRIPT_BLOCKERS_PRESENT",
        )
    manual_derived_override = any(
        segment.manual_override
        and segment.attribution.origin in {
            AttributionOrigin.MANUAL_OVERRIDE,
            AttributionOrigin.INHERITED_OVERRIDE,
        }
        for segment in script.segments
    )
    if (
        context.force_review
        or script.effective_policy is ScriptReviewPolicy.ALWAYS_REVIEW
        or context.verified_manual_review_parent
        or manual_derived_override
    ):
        return ScriptReviewDecision(
            disposition=ReviewDisposition.REVIEW_REQUIRED,
            state=ScriptVersionState.REVIEW_REQUIRED,
            warning_count=warning_count,
            blocker_count=0,
            approval=None,
            reason_code=(
                "MANUAL_OVERRIDE_REQUIRES_OWNER_REVIEW"
                if manual_derived_override
                else "CORRECTED_VERSION_REQUIRES_OWNER_REVIEW"
                if context.verified_manual_review_parent
                else "ALWAYS_REVIEW_POLICY"
            ),
        )
    return ScriptReviewDecision(
        disposition=ReviewDisposition.AUTO_FREEZE,
        state=ScriptVersionState.APPROVED,
        warning_count=warning_count,
        blocker_count=0,
        approval=None,
        reason_code="ZERO_BLOCKERS_AUTO_FREEZE_READY",
    )


def auto_freeze_script(
    script: NarrationScriptContract,
    context: ReviewRequestContext,
    *,
    actor_type: ApprovalActorType,
    actor_id: str,
    approved_at: datetime,
) -> NarrationScriptContract:
    """Apply the audited default freeze path to one immutable script version."""

    decision = decide_script_review(script, context)
    if decision.disposition is not ReviewDisposition.AUTO_FREEZE:
        raise ReviewStateError(
            f"script is not eligible for automatic freeze: {decision.reason_code}"
        )
    if actor_type not in {ApprovalActorType.SYSTEM, ApprovalActorType.SERVICE}:
        raise ReviewStateError("automatic freeze requires a system or service actor")
    ensure_script_transition(script.state, ScriptVersionState.APPROVED)
    try:
        approval = ScriptApproval(
            kind=ScriptApprovalKind.AUTO_NO_BLOCKERS,
            request_id=context.request_id,
            actor_type=actor_type,
            actor_id=actor_id,
            approved_at=approved_at,
        )
        return replace(
            script,
            state=ScriptVersionState.APPROVED,
            approval=approval,
        )
    except ScriptContractError as error:
        raise ReviewStateError(str(error)) from error


def manual_freeze_script(
    script: NarrationScriptContract,
    context: ReviewRequestContext,
    *,
    owner_actor_id: str,
    approved_at: datetime,
) -> NarrationScriptContract:
    """Apply an explicit owner approval after review and after blockers are zero."""

    warning_count, blocker_count = _validate_script_and_request(script, context)
    del warning_count
    if context.intent is ReviewIntent.ANALYZE_ONLY or not context.allows_edition:
        raise ReviewStateError("analyze_only cannot be manually frozen")
    if script.state is ScriptVersionState.APPROVED:
        raise ReviewStateError("approved script version is terminal")
    if blocker_count:
        raise ReviewStateError("script blockers must be resolved in a new version")
    if not (
        script.effective_policy is ScriptReviewPolicy.ALWAYS_REVIEW
        or context.verified_manual_review_parent
        or any(
            segment.manual_override
            and segment.attribution.origin in {
                AttributionOrigin.MANUAL_OVERRIDE,
                AttributionOrigin.INHERITED_OVERRIDE,
            }
            for segment in script.segments
        )
    ):
        raise ReviewStateError(
            "manual freeze requires an explicit review policy or manual-derived override"
        )
    if script.state is not ScriptVersionState.REVIEW_REQUIRED:
        raise ReviewStateError("manual freeze requires review_required state")
    ensure_script_transition(script.state, ScriptVersionState.APPROVED)
    try:
        approval = ScriptApproval(
            kind=ScriptApprovalKind.MANUAL_AFTER_REVIEW,
            request_id=context.request_id,
            actor_type=ApprovalActorType.OWNER,
            actor_id=owner_actor_id,
            approved_at=approved_at,
        )
        return replace(
            script,
            state=ScriptVersionState.APPROVED,
            approval=approval,
        )
    except ScriptContractError as error:
        raise ReviewStateError(str(error)) from error


__all__ = [
    "NARRATION_SCRIPT_REVIEW_VERSION",
    "ReviewDisposition",
    "ReviewIntent",
    "ReviewIssueCandidate",
    "ReviewRequestContext",
    "ReviewStateError",
    "ReviewTaxonomyError",
    "ScriptReviewDecision",
    "ScriptReviewError",
    "auto_freeze_script",
    "classify_review_issue",
    "classify_review_issues",
    "decide_script_review",
    "manual_freeze_script",
    "recompute_issue_counts",
]
