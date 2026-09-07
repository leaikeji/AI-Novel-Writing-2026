import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from backend.creative_services import (
    build_creative_generation_prompt,
    get_or_create_novel_creation_draft,
    start_creative_generation,
)
from backend.services import ValidationError
from backend.writing_skills.contracts import (
    ActionIdentity,
    FIXED_LOCAL_OWNER_ID,
    FIXED_LOCAL_WORKSPACE_ID,
    FrozenRouteRequest,
    MethodBlock,
    MethodPreferences,
    Scope,
    SkillInjectionPacketV1,
    SkillInvocationPlanV1,
    canonical_hash,
)
from backend.writing_skills.persistence import advance, claim_action, lookup_action
from backend.writing_skills.projection import creative_projection
from .test_persistence import engine


def _draft(engine):
    with Session(engine) as session:
        draft = get_or_create_novel_creation_draft(session, f"s58-creative-{uuid4()}")
    return UUID(draft["id"])


def _assembled(engine, draft_id, *, text="frozen direction", primary="novel-direction"):
    scope = Scope(
        owner_id=FIXED_LOCAL_OWNER_ID,
        workspace_id=FIXED_LOCAL_WORKSPACE_ID,
        kind="creation_draft",
        scope_id=draft_id,
        tab_id="creative-tab",
    )
    snapshot = {"audience": "女频", "genre": "悬疑", "idea": "旧宅失踪"}
    prompt = build_creative_generation_prompt(
        {"kind": "novel_naming", "input_snapshot": snapshot}
    )
    projection = creative_projection(scope, "novel_naming", snapshot, prompt)
    projection = projection.model_copy(
        update={
            "source_version": canonical_hash(
                {"model_source": projection.source_version, "scope_version": 1}
            )
        }
    )
    request = FrozenRouteRequest(
        identity=ActionIdentity(
            owner_id=scope.owner_id,
            workspace_id=scope.workspace_id,
            entry="button",
            action_id=uuid4(),
        ),
        projection=projection,
        preferences=MethodPreferences(),
        catalog_version="a" * 64,
        provider_id="s58-fake",
        model_id="s58-fake-model",
    )
    block = MethodBlock(
        skill_id=primary,
        path="SKILL.md",
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    packet = SkillInjectionPacketV1(
        plan=SkillInvocationPlanV1(
            task="novel_naming",
            primary_skill=primary,
            source_hash=projection.source_hash,
            catalog_version=request.catalog_version,
            genre_state="unresolved",
            mechanism_state="unresolved",
        ),
        blocks=(block,),
        estimated_tokens=10,
    )
    with Session(engine) as session:
        claim = claim_action(
            session,
            request.identity,
            scope,
            "b" * 64,
            authorize=lambda *_: None,
            freeze=lambda: request,
        )
        claim = advance(session, claim, "route_ready")
        claim = advance(session, claim, "assembled", packet=packet)
    return claim, snapshot


def _read(engine, claim):
    with Session(engine) as session:
        return lookup_action(
            session,
            claim.identity,
            claim.scope,
            "b" * 64,
            authorize=lambda *_: None,
        )


def _start(session, draft_id, snapshot, **extra):
    if extra.get("method_dispatch") is not None:
        extra.setdefault("method_scope_version", 1)
    return start_creative_generation(
        session,
        scope_type="novel_creation",
        scope_id=draft_id,
        kind="novel_naming",
        input_snapshot=snapshot,
        execution_agent_id="ai-novel-writer",
        requested_provider_id="s58-fake",
        requested_model_id="s58-fake-model",
        generation_contract_version="s58-fixture/1",
        **extra,
    )


def test_creative_job_and_dispatch_link_atomically_without_leaking_method_text(engine):
    draft_id = _draft(engine)
    claim, snapshot = _assembled(engine, draft_id)
    with Session(engine) as session:
        job = _start(session, draft_id, snapshot, method_dispatch=claim)
    linked = _read(engine, claim)
    assert linked.state == "dispatch_started"
    assert linked.job_ref == f"creative:{job['id']}"
    assert "skill_invocation" not in job["input_snapshot"]
    prompt = build_creative_generation_prompt(job)
    assert claim.packet.blocks[0].text not in prompt
    assert claim.packet.method_input_hash not in prompt


def test_creative_method_hash_participates_in_business_dedup(engine):
    draft_id = _draft(engine)
    first, snapshot = _assembled(engine, draft_id, text="method-v1")
    second, _ = _assembled(engine, draft_id, text="method-v2")
    with Session(engine) as session:
        first_job = _start(session, draft_id, snapshot, method_dispatch=first)
    with Session(engine) as session:
        second_job = _start(session, draft_id, snapshot, method_dispatch=second)
    assert first_job["input_hash"] != second_job["input_hash"]
    assert first_job["id"] != second_job["id"]


def test_creative_rejects_wrong_primary_or_changed_source_before_job(engine):
    draft_id = _draft(engine)
    wrong, snapshot = _assembled(engine, draft_id, primary="story-foundation")
    with Session(engine) as session, pytest.raises(ValidationError, match="primary Skill"):
        _start(session, draft_id, snapshot, method_dispatch=wrong)
    assert _read(engine, wrong).job_ref is None

    claim, snapshot = _assembled(engine, draft_id)
    with Session(engine) as session, pytest.raises(ValidationError, match="source"):
        _start(
            session,
            draft_id,
            {**snapshot, "idea": "changed after routing"},
            method_dispatch=claim,
        )
    assert _read(engine, claim).job_ref is None


def test_legacy_creative_job_remains_unrecorded_and_unchanged(engine):
    draft_id = _draft(engine)
    snapshot = {"audience": "男频", "genre": "玄幻", "idea": "少年远行"}
    with Session(engine) as session:
        legacy = _start(session, draft_id, snapshot)
    assert legacy["state"] == "running"
    assert "skill_invocation" not in legacy["input_snapshot"]
