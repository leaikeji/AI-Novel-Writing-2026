from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from backend.narration.script_contracts import (
    ApprovalActorType,
    ScriptIssueContract,
    ScriptReviewPolicy,
    ScriptVersionState,
)
from backend.narration.script_review import (
    ReviewDisposition,
    ReviewIntent,
    ReviewIssueCandidate,
    ReviewRequestContext,
    ReviewStateError,
    ReviewTaxonomyError,
    auto_freeze_script,
    classify_review_issue,
    classify_review_issues,
    decide_script_review,
    manual_freeze_script,
    recompute_issue_counts,
)
from tests.narration.test_script_contracts import _make_contract


REQUEST_ID = UUID("a1000000-0000-4000-8000-000000000001")
PARENT_ID = UUID("a1000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _context(
    *,
    intent: ReviewIntent = ReviewIntent.CREATE,
    policy: ScriptReviewPolicy = ScriptReviewPolicy.BLOCKERS_ONLY,
    force_review: bool = False,
    manual_parent: bool = False,
    non_review_parent: bool = False,
) -> ReviewRequestContext:
    return ReviewRequestContext(
        request_id=REQUEST_ID,
        intent=intent,
        allows_edition=intent is not ReviewIntent.ANALYZE_ONLY,
        effective_policy=policy,
        force_review=force_review,
        verified_manual_review_parent=manual_parent,
        verified_non_review_parent=non_review_parent,
    )


def _issue(code: str) -> ScriptIssueContract:
    return classify_review_issue(ReviewIssueCandidate(code=code))


def test_classifier_owns_every_severity_and_canonical_order() -> None:
    issues = classify_review_issues(
        (
            ReviewIssueCandidate(code="W_NEW_ANONYMOUS_SPEAKER"),
            ReviewIssueCandidate(code="B_VOICE_MISSING"),
            ReviewIssueCandidate(code="W_SPEAKER_MEDIUM_CONFIDENCE"),
        )
    )

    assert [item.code for item in issues] == [
        "B_VOICE_MISSING",
        "W_NEW_ANONYMOUS_SPEAKER",
        "W_SPEAKER_MEDIUM_CONFIDENCE",
    ]
    assert recompute_issue_counts(issues) == (2, 1)


@pytest.mark.parametrize(
    ("candidate", "match"),
    [
        (ReviewIssueCandidate(code="B_NOT_IN_V1"), "unknown review taxonomy"),
        (
            ReviewIssueCandidate(
                code="B_VOICE_MISSING",
                claimed_severity="warning",
            ),
            "server-owned",
        ),
        (
            ReviewIssueCandidate(
                code="W_NEW_ANONYMOUS_SPEAKER",
                taxonomy_version="narration-review-taxonomy/2",
            ),
            "unknown narration review taxonomy",
        ),
    ],
)
def test_classifier_rejects_unknown_spoofed_or_future_taxonomy(
    candidate: ReviewIssueCandidate,
    match: str,
) -> None:
    with pytest.raises(ReviewTaxonomyError, match=match):
        classify_review_issue(candidate)


def test_classifier_rejects_duplicate_issue_evidence_rows() -> None:
    candidate = ReviewIssueCandidate(code="B_VOICE_MISSING")
    with pytest.raises(ReviewTaxonomyError, match="duplicate"):
        classify_review_issues((candidate, candidate))


def test_default_zero_blocker_generation_is_eligible_for_automatic_freeze() -> None:
    script = _make_contract()

    decision = decide_script_review(script, _context())

    assert decision.disposition is ReviewDisposition.AUTO_FREEZE
    assert decision.state is ScriptVersionState.APPROVED
    assert decision.blocker_count == 0


def test_automatic_freeze_records_server_actor_without_changing_immutable_hash() -> None:
    script = _make_contract()

    approved = auto_freeze_script(
        script,
        _context(),
        actor_type=ApprovalActorType.SERVICE,
        actor_id="narration-request-orchestrator",
        approved_at=NOW,
    )

    assert approved.state is ScriptVersionState.APPROVED
    assert approved.approval is not None
    assert approved.approval.kind.value == "auto_no_blockers"
    assert approved.approval.request_id == REQUEST_ID
    assert approved.immutable_hash == script.immutable_hash


def test_client_or_owner_cannot_impersonate_automatic_freeze_actor() -> None:
    script = _make_contract()
    with pytest.raises(ReviewStateError, match="system or service"):
        auto_freeze_script(
            script,
            _context(),
            actor_type=ApprovalActorType.OWNER,
            actor_id="local-owner",
            approved_at=NOW,
        )


def test_analyze_only_never_freezes_even_with_zero_blockers() -> None:
    script = _make_contract()

    decision = decide_script_review(
        script,
        _context(intent=ReviewIntent.ANALYZE_ONLY),
    )

    assert decision.disposition is ReviewDisposition.ANALYSIS_ONLY
    assert decision.approval is None
    with pytest.raises(ReviewStateError, match="not eligible"):
        auto_freeze_script(
            script,
            _context(intent=ReviewIntent.ANALYZE_ONLY),
            actor_type=ApprovalActorType.SYSTEM,
            actor_id="scanner",
            approved_at=NOW,
        )


def test_blocker_forces_review_and_cannot_be_manually_approved_in_place() -> None:
    script = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        issues=(_issue("B_VOICE_MISSING"),),
    )
    decision = decide_script_review(script, _context())

    assert decision.disposition is ReviewDisposition.REVIEW_REQUIRED
    assert decision.blocker_count == 1
    with pytest.raises(ReviewStateError, match="resolved in a new version"):
        manual_freeze_script(
            script,
            _context(),
            owner_actor_id="local-owner",
            approved_at=NOW,
        )


def test_always_review_zero_blocker_requires_owner_confirmation() -> None:
    script = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        policy=ScriptReviewPolicy.ALWAYS_REVIEW,
    )
    context = _context(policy=ScriptReviewPolicy.ALWAYS_REVIEW)

    decision = decide_script_review(script, context)
    approved = manual_freeze_script(
        script,
        context,
        owner_actor_id="local-owner",
        approved_at=NOW,
    )

    assert decision.disposition is ReviewDisposition.REVIEW_REQUIRED
    assert approved.state is ScriptVersionState.APPROVED
    assert approved.approval is not None
    assert approved.approval.kind.value == "manual_after_review"
    assert approved.approval.actor_type is ApprovalActorType.OWNER


def test_verified_blocker_correction_stays_on_manual_path() -> None:
    corrected = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        parent_version_id=PARENT_ID,
    )
    context = _context(manual_parent=True)

    decision = decide_script_review(corrected, context)
    approved = manual_freeze_script(
        corrected,
        context,
        owner_actor_id="local-owner",
        approved_at=NOW,
    )

    assert decision.reason_code == "CORRECTED_VERSION_REQUIRES_OWNER_REVIEW"
    assert approved.approval is not None
    assert approved.approval.kind.value == "manual_after_review"


def test_parent_classification_is_exhaustive_disjoint_and_server_owned() -> None:
    child = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        parent_version_id=PARENT_ID,
    )
    with pytest.raises(ReviewStateError, match="exhaustive server verification"):
        decide_script_review(child, _context())
    with pytest.raises(ReviewStateError, match="disjoint"):
        _context(manual_parent=True, non_review_parent=True)


def test_verified_non_review_parent_may_use_default_zero_blocker_path() -> None:
    child = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        parent_version_id=PARENT_ID,
    )
    decision = decide_script_review(child, _context(non_review_parent=True))
    assert decision.disposition is ReviewDisposition.AUTO_FREEZE


def test_request_policy_and_force_review_cannot_silently_relax() -> None:
    script = _make_contract()
    with pytest.raises(ReviewStateError, match="policies differ"):
        decide_script_review(
            script,
            _context(policy=ScriptReviewPolicy.ALWAYS_REVIEW),
        )
    with pytest.raises(ReviewStateError, match="force_review"):
        ReviewRequestContext(
            request_id=uuid4(),
            intent=ReviewIntent.CREATE,
            allows_edition=True,
            effective_policy=ScriptReviewPolicy.BLOCKERS_ONLY,
            force_review=True,
        )


def test_issue_count_tampering_fails_closed_before_any_freeze() -> None:
    script = _make_contract(issues=(_issue("W_NEW_ANONYMOUS_SPEAKER"),))
    object.__setattr__(script, "warning_count", 0)

    with pytest.raises(ReviewStateError, match="counts differ"):
        decide_script_review(script, _context())


def test_manual_freeze_is_not_a_general_override_for_blockers_only() -> None:
    script = _make_contract()
    with pytest.raises(ReviewStateError, match="always_review or a verified corrected parent"):
        manual_freeze_script(
            script,
            _context(),
            owner_actor_id="local-owner",
            approved_at=NOW,
        )
