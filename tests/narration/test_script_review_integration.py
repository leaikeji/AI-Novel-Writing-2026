from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from backend.narration.aliases import (
    AliasSource,
    CharacterAliasRecord,
    build_character_alias_index,
)
from backend.narration.script_contracts import (
    ApprovalActorType,
    ScriptReviewPolicy,
    ScriptVersionState,
    SegmentKind,
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
)
from backend.narration.speaker_rules import (
    SpeakerRuleContext,
    attribute_speaker_local,
)
from tests.narration.test_script_contracts import _make_contract


def _uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://example.invalid/t3-i-review/{label}")


REQUEST_ID = _uuid("request")
PARENT_VERSION_ID = _uuid("parent-version")
CHARACTER_ID = _uuid("character-lin-wan")
APPROVED_AT = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)


def _aliases():
    return build_character_alias_index(
        (
            CharacterAliasRecord(
                character_id=CHARACTER_ID,
                alias="林晚",
                source=AliasSource.CANONICAL_NAME,
            ),
        ),
        allowed_character_ids=frozenset({CHARACTER_ID}),
    )


def _context(
    *,
    intent: ReviewIntent = ReviewIntent.CREATE,
    policy: ScriptReviewPolicy = ScriptReviewPolicy.BLOCKERS_ONLY,
    manual_parent: bool = False,
    non_review_parent: bool = False,
) -> ReviewRequestContext:
    return ReviewRequestContext(
        request_id=REQUEST_ID,
        intent=intent,
        allows_edition=intent is not ReviewIntent.ANALYZE_ONLY,
        effective_policy=policy,
        verified_manual_review_parent=manual_parent,
        verified_non_review_parent=non_review_parent,
    )


def test_named_attribution_with_warning_uses_default_auto_freeze_path() -> None:
    attribution = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="林晚说道：“可以出发了。”",
        ),
        aliases=_aliases(),
    )
    warning = classify_review_issue(
        ReviewIssueCandidate(code="W_PRONUNCIATION_SOFT_FALLBACK")
    )
    script = _make_contract(
        speaker=attribution.speaker,
        confidence=attribution.confidence,
        attribution=attribution.attribution,
        issues=(warning,),
    )
    context = _context()

    first_decision = decide_script_review(script, context)
    second_decision = decide_script_review(script, context)
    first_approved = auto_freeze_script(
        script,
        context,
        actor_type=ApprovalActorType.SERVICE,
        actor_id="narration-request-orchestrator",
        approved_at=APPROVED_AT,
    )
    second_approved = auto_freeze_script(
        script,
        context,
        actor_type=ApprovalActorType.SERVICE,
        actor_id="narration-request-orchestrator",
        approved_at=APPROVED_AT,
    )

    assert first_decision == second_decision
    assert first_decision.disposition is ReviewDisposition.AUTO_FREEZE
    assert first_decision.warning_count == 1
    assert first_decision.blocker_count == 0
    assert first_approved == second_approved
    assert first_approved.state is ScriptVersionState.APPROVED
    assert first_approved.approval is not None
    assert first_approved.approval.kind.value == "auto_no_blockers"
    assert first_approved.approval.actor_type is ApprovalActorType.SERVICE
    assert first_approved.immutable_hash == script.immutable_hash


def test_unknown_attribution_blockers_prevent_auto_and_manual_freeze() -> None:
    attribution = attribute_speaker_local(
        SpeakerRuleContext(
            segment_kind=SegmentKind.DIALOGUE,
            source_text="“这里没有说话人提示。”",
        ),
        aliases=_aliases(),
    )
    issues = classify_review_issues(
        ReviewIssueCandidate(code=code) for code in attribution.issue_codes
    )
    script = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        issues=issues,
    )
    context = _context()

    decision = decide_script_review(script, context)

    assert decision.disposition is ReviewDisposition.REVIEW_REQUIRED
    assert decision.reason_code == "SCRIPT_BLOCKERS_PRESENT"
    assert decision.blocker_count == 2
    assert {issue.code for issue in script.issues} == {
        "B_SPEAKER_LOW_CONFIDENCE",
        "B_SPEAKER_UNKNOWN",
    }
    with pytest.raises(ReviewStateError, match="not eligible"):
        auto_freeze_script(
            script,
            context,
            actor_type=ApprovalActorType.SYSTEM,
            actor_id="narration-request-orchestrator",
            approved_at=APPROVED_AT,
        )
    with pytest.raises(ReviewStateError, match="resolved in a new version"):
        manual_freeze_script(
            script,
            context,
            owner_actor_id="local-owner",
            approved_at=APPROVED_AT,
        )
    assert script.state is ScriptVersionState.REVIEW_REQUIRED
    assert script.approval is None


def test_always_review_zero_blockers_still_requires_owner_confirmation() -> None:
    script = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        policy=ScriptReviewPolicy.ALWAYS_REVIEW,
    )
    context = _context(policy=ScriptReviewPolicy.ALWAYS_REVIEW)

    decision = decide_script_review(script, context)
    assert decision.disposition is ReviewDisposition.REVIEW_REQUIRED
    assert decision.reason_code == "ALWAYS_REVIEW_POLICY"
    assert decision.blocker_count == 0
    with pytest.raises(ReviewStateError, match="not eligible"):
        auto_freeze_script(
            script,
            context,
            actor_type=ApprovalActorType.SERVICE,
            actor_id="narration-request-orchestrator",
            approved_at=APPROVED_AT,
        )

    approved = manual_freeze_script(
        script,
        context,
        owner_actor_id="local-owner",
        approved_at=APPROVED_AT,
    )
    assert approved.state is ScriptVersionState.APPROVED
    assert approved.approval is not None
    assert approved.approval.kind.value == "manual_after_review"
    assert approved.approval.actor_type is ApprovalActorType.OWNER
    assert approved.immutable_hash == script.immutable_hash


def test_corrected_child_cannot_return_to_automatic_freeze() -> None:
    corrected = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        parent_version_id=PARENT_VERSION_ID,
    )
    context = _context(manual_parent=True)

    decision = decide_script_review(corrected, context)
    assert decision.disposition is ReviewDisposition.REVIEW_REQUIRED
    assert decision.reason_code == "CORRECTED_VERSION_REQUIRES_OWNER_REVIEW"
    with pytest.raises(ReviewStateError, match="not eligible"):
        auto_freeze_script(
            corrected,
            context,
            actor_type=ApprovalActorType.SERVICE,
            actor_id="narration-request-orchestrator",
            approved_at=APPROVED_AT,
        )

    approved = manual_freeze_script(
        corrected,
        context,
        owner_actor_id="local-owner",
        approved_at=APPROVED_AT,
    )
    assert approved.approval is not None
    assert approved.approval.kind.value == "manual_after_review"


def test_verified_non_review_parent_may_replay_default_zero_blocker_policy() -> None:
    child = _make_contract(parent_version_id=PARENT_VERSION_ID)
    context = _context(non_review_parent=True)

    first = decide_script_review(child, context)
    second = decide_script_review(child, context)

    assert first == second
    assert first.disposition is ReviewDisposition.AUTO_FREEZE
    assert first.reason_code == "ZERO_BLOCKERS_AUTO_FREEZE_READY"


def test_analysis_only_never_creates_approval_even_when_clean() -> None:
    script = _make_contract()
    context = _context(intent=ReviewIntent.ANALYZE_ONLY)

    decision = decide_script_review(script, context)

    assert decision.disposition is ReviewDisposition.ANALYSIS_ONLY
    assert decision.approval is None
    assert decision.reason_code == "ANALYZE_ONLY_NEVER_FREEZES"
    with pytest.raises(ReviewStateError, match="not eligible"):
        auto_freeze_script(
            script,
            context,
            actor_type=ApprovalActorType.SYSTEM,
            actor_id="scanner",
            approved_at=APPROVED_AT,
        )


@pytest.mark.parametrize(
    "candidate",
    (
        ReviewIssueCandidate(code="B_FUTURE_UNKNOWN"),
        ReviewIssueCandidate(
            code="B_VOICE_MISSING",
            claimed_severity="warning",
        ),
        ReviewIssueCandidate(
            code="W_NEW_ANONYMOUS_SPEAKER",
            taxonomy_version="narration-review-taxonomy/999",
        ),
    ),
)
def test_illegal_or_spoofed_issue_cannot_be_downgraded_to_warning(
    candidate: ReviewIssueCandidate,
) -> None:
    with pytest.raises(ReviewTaxonomyError):
        classify_review_issue(candidate)


def test_parent_authority_must_be_exhaustive_and_disjoint_before_review() -> None:
    child = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        parent_version_id=PARENT_VERSION_ID,
    )
    with pytest.raises(ReviewStateError, match="exhaustive server verification"):
        decide_script_review(child, _context())
    with pytest.raises(ReviewStateError, match="disjoint"):
        _context(manual_parent=True, non_review_parent=True)
