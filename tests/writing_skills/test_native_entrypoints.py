import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.assistant_context import Msg, TextBlock
from backend.writing_skills.contracts import (
    MethodBlock,
    SkillInjectionPacketV1,
    SkillInvocationPlanV1,
)
from backend.writing_skills.load_policy import ManagedMethodPolicy, MethodPolicyViolation
from backend.writing_skills.middleware import (
    NativePreparedAction,
    NativeWritingMethodMiddleware,
    current_native_user_text,
    create_native_writing_middleware,
    create_released_native_writing_middleware,
    native_task_route,
)
from backend.assistant_context_registry import AssistantContextRefRegistry, ContextRefBinding
from backend.models import Novel
from backend.writing_skills import button
from backend.writing_skills.catalog import published_skill_ids
from backend.writing_skills.models import WritingSkillDispatch
from backend.writing_skills.api import native_writing_action_result
from backend.writing_skills.native import (
    NativeActionReplay,
    NativeModelConfig,
    prepare_native_action,
)
from backend.writing_skills.persistence import ActionConflict, StaleFence
from .test_button_entrypoints import chapter
from .test_persistence import engine


ACTION_ID = UUID("00000000-0000-4000-8000-000000000058")


def method_policy() -> ManagedMethodPolicy:
    text = "冻结的通用写作方法"
    block = MethodBlock(
        skill_id="prose-writing",
        path="SKILL.md",
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    plan = SkillInvocationPlanV1(
        task="chapter_body",
        primary_skill="prose-writing",
        source_hash="a" * 64,
        catalog_version="b" * 64,
        genre_state="unresolved",
        mechanism_state="unresolved",
    )
    return ManagedMethodPolicy(
        SkillInjectionPacketV1(plan=plan, blocks=(block,), estimated_tokens=20)
    )


def prepared(events: list[object]) -> NativePreparedAction:
    async def verify_current():
        events.append("verified")

    async def mark_started():
        events.append("dispatch_started")

    async def mark_dispatched():
        events.append("dispatched")

    async def mark_failed(uncertain: bool):
        events.append(("failed", uncertain))

    return NativePreparedAction(
        action_id=ACTION_ID,
        policy=method_policy(),
        verify_current=verify_current,
        mark_dispatch_started=mark_started,
        mark_dispatched=mark_dispatched,
        mark_failed=mark_failed,
        route_data_text='【本轮路由资料；数据角色=user】{"genre":"悬疑","subgenre":"刑侦"}',
    )


def test_reads_only_final_current_user_input():
    assert current_native_user_text([
        Msg(name="user", role="user", content=[TextBlock(text="旧输入")]),
        Msg(name="assistant", role="assistant", content=[TextBlock(text="旧回答")]),
        Msg(name="user", role="user", content=[TextBlock(text="请续写《雾宅来信》的下一章")]),
    ]) == "请续写《雾宅来信》的下一章"
    assert current_native_user_text(None) is None


def test_released_factory_has_no_client_release_switch():
    # Registration is the release authority; the request cannot pass a
    # released flag or a Skill id into this exact public factory signature.
    assert tuple(create_released_native_writing_middleware.__annotations__) == (
        "ctx",
        "agent_config",
        "return",
    )


@pytest.mark.parametrize("text", [
    "《雾宅来信》",
    "《雾宅来信》现在一共有多少章？",
    "解释一下这里的‘系统’是不是公司软件。",
    "林澈看到死者来信，这一幕是什么意思？",
])
def test_title_plot_or_mechanism_words_do_not_claim_a_writing_task(text):
    snapshot = {"page": {"view": "chapter-editor"}}
    assert native_task_route(snapshot, text) is None


def test_explicit_real_writing_request_maps_by_current_view_not_title():
    snapshot = {"page": {"view": "chapter-editor"}}
    route = native_task_route(
        snapshot,
        "请续写《雾宅来信》的下一章，保持暴雨封路与死者来信事实。",
    )
    assert route is not None
    assert (route.task, route.intent, route.primary_skill, route.operation) == (
        "chapter_body",
        "write",
        "prose-writing",
        "",
    )


def test_selection_operation_and_review_are_explicit_and_fail_closed():
    selected = {"page": {"view": "chapter-editor"}, "selection": {"id": "sel-1"}}
    route = native_task_route(selected, "请润色这段，让动作更清楚。")
    assert route is not None and route.task == "selection_edit" and route.operation == "polish"
    review = native_task_route(
        {"page": {"view": "chapter-editor"}},
        "请审查这一章的人物知识边界。",
    )
    assert review is not None and review.task == "review" and review.primary_skill == "style-review"
    assert native_task_route(selected, "帮我看看这一段。") is None


def test_current_modal_owns_the_native_task_over_the_page_beneath_it():
    route = native_task_route(
        {
            "page": {
                "view": "chapter-editor",
                "modal": "chapter-outline-editor",
            }
        },
        "请设计《雾宅来信》下一章的行动与线索顺序。",
    )
    assert route is not None
    assert (route.task, route.primary_skill) == ("chapter_outline", "chapter-outline")


def test_rejects_oversized_current_input_before_preparation():
    with pytest.raises(MethodPolicyViolation, match="too_large"):
        current_native_user_text("写" * 20_001)


@pytest.mark.asyncio
async def test_real_writing_send_injects_once_and_finishes_after_model():
    events: list[object] = []
    prepared_texts: list[str] = []

    async def prepare(user_text: str):
        prepared_texts.append(user_text)
        return prepared(events)

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)
    reply_kwargs = {
        "inputs": Msg(
            name="user",
            role="user",
            content=[TextBlock(text="请续写《雾宅来信》的下一章，保持暴雨封路与死者来信事实。")],
        )
    }

    async def reply():
        model_kwargs = {
            "messages": [Msg(name="user", role="user", content=[TextBlock(text="当前写作请求")])],
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
        }

        async def model():
            assert model_kwargs["messages"][-1].name == "anw-frozen-methods"
            assert model_kwargs["messages"][-1].role == "system"
            assert model_kwargs["messages"][-2].name == "anw-writing-route-data"
            assert model_kwargs["messages"][-2].role == "user"
            assert model_kwargs["tools"] == []
            events.append("model")
            return "正文"

        assert await middleware.on_model_call(None, model_kwargs, model) == "正文"
        assert [message.name for message in model_kwargs["messages"]] == ["user"]
        yield "正文事件"

    assert [event async for event in middleware.on_reply(None, reply_kwargs, reply)] == ["正文事件"]
    assert prepared_texts == ["请续写《雾宅来信》的下一章，保持暴雨封路与死者来信事实。"]
    assert events == ["dispatch_started", "verified", "model", "dispatched"]


@pytest.mark.asyncio
async def test_unmanaged_question_keeps_native_chat_untouched():
    prepared_texts: list[str] = []

    async def prepare(user_text: str):
        prepared_texts.append(user_text)
        return None

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        yield "普通回答"

    kwargs = {"inputs": "《雾宅来信》现在一共有多少章？"}
    assert [event async for event in middleware.on_reply(None, kwargs, reply)] == ["普通回答"]
    assert prepared_texts == ["《雾宅来信》现在一共有多少章？"]


@pytest.mark.asyncio
async def test_model_failure_records_uncertain_and_never_marks_dispatched():
    events: list[object] = []

    async def prepare(_user_text: str):
        return prepared(events)

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        async def model():
            raise RuntimeError("synthetic transport failure")

        await middleware.on_model_call(None, {"messages": [], "tools": []}, model)
        yield None

    with pytest.raises(RuntimeError, match="synthetic transport"):
        async for _ in middleware.on_reply(None, {"inputs": "续写《雾宅来信》"}, reply):
            pass
    assert events == ["dispatch_started", "verified", ("failed", True)]


@pytest.mark.asyncio
async def test_evidence_write_failure_does_not_mask_native_model_failure():
    events: list[object] = []
    base = prepared(events)

    async def broken_mark_failed(_uncertain: bool):
        raise RuntimeError("synthetic evidence failure")

    async def prepare(_user_text: str):
        return NativePreparedAction(
            action_id=base.action_id,
            policy=base.policy,
            verify_current=base.verify_current,
            mark_dispatch_started=base.mark_dispatch_started,
            mark_dispatched=base.mark_dispatched,
            mark_failed=broken_mark_failed,
            route_data_text=base.route_data_text,
        )

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        async def model():
            raise RuntimeError("synthetic model failure")

        await middleware.on_model_call(None, {"messages": [], "tools": []}, model)
        yield None

    with pytest.raises(RuntimeError, match="synthetic model failure"):
        async for _ in middleware.on_reply(
            None,
            {"inputs": "请续写《雾宅来信》"},
            reply,
        ):
            pass


@pytest.mark.asyncio
async def test_no_model_call_fails_closed_and_send_cannot_reenter():
    events: list[object] = []

    async def prepare(_user_text: str):
        return prepared(events)

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        yield "没有模型调用"

    with pytest.raises(MethodPolicyViolation, match="not_observed_once"):
        async for _ in middleware.on_reply(None, {"inputs": "续写《雾宅来信》"}, reply):
            pass
    assert events == ["dispatch_started", ("failed", False)]
    with pytest.raises(MethodPolicyViolation, match="reentered"):
        async for _ in middleware.on_reply(None, {"inputs": "继续"}, reply):
            pass


@pytest.mark.asyncio
async def test_hidden_tool_is_denied_before_io():
    events: list[object] = []

    async def prepare(_user_text: str):
        return prepared(events)

    middleware = NativeWritingMethodMiddleware(session_id="native-58", prepare=prepare)

    async def reply():
        async def never():
            pytest.fail("hidden tool reached I/O")
            yield None

        async for _ in middleware.on_acting(
            None,
            {"tool_call": SimpleNamespace(name="materialize_skill")},
            never,
        ):
            pass
        yield None

    with pytest.raises(MethodPolicyViolation, match="not_allowed"):
        async for _ in middleware.on_reply(None, {"inputs": "续写《雾宅来信》"}, reply):
            pass
    assert events == ["dispatch_started", "verified", ("failed", False)]


@pytest.fixture
def native_harness(engine, chapter):
    document_id, _, projection, _ = chapter
    with Session(engine) as session:
        novel = session.get(Novel, projection.scope.scope_id)
        novel.title = "《雾宅来信》"
        novel.genre = "悬疑"
        novel.subgenre = "刑侦"
        session.commit()
    snapshot = {
        "contextRevision": 12,
        "novel": {"id": str(projection.scope.scope_id), "title": "《雾宅来信》"},
        "page": {"section": "chapters", "view": "chapter-editor"},
        "document": {
            "id": str(document_id),
            "kind": "chapter",
            "title": "第一章",
            "draftVersion": 0,
            "savedContentHash": "a" * 64,
            "dirty": False,
        },
    }
    app = FastAPI()
    enabled = set(published_skill_ids(button.SKILLS_ROOT))
    counts = {"catalog": 0, "model": 0}

    @app.get("/api/skills")
    def skills():
        counts["catalog"] += 1
        return [
            {
                "name": name,
                "source": "plugin:ai-novel-world-2026",
                "enabled": name in enabled,
            }
            for name in sorted(published_skill_ids(button.SKILLS_ROOT))
        ]

    async def model_probe():
        counts["model"] += 1
        return NativeModelConfig(
            provider_id="s58-fake",
            model_id="s58-fake-model",
            effective_input_budget=131_072,
        )

    return {
        "engine": engine,
        "app": app,
        "enabled": enabled,
        "counts": counts,
        "model_probe": model_probe,
        "snapshot": snapshot,
        "document_id": document_id,
    }


async def prepare_harness(harness, *, action_id, text):
    return await prepare_native_action(
        session_factory=lambda: Session(harness["engine"]),
        asgi_app=harness["app"],
        action_id=action_id,
        tab_id="anw-tab-native-58",
        session_id="native-session-58",
        snapshot=harness["snapshot"],
        user_text=text,
        model_probe=harness["model_probe"],
    )


@pytest.mark.asyncio
async def test_native_domain_service_claims_before_catalog_and_dispatches_once(native_harness):
    action_id = uuid4()
    text = "请续写《雾宅来信》，保持暴雨封路、死者来信和档案篡改事实。"
    prepared_action = await prepare_harness(native_harness, action_id=action_id, text=text)
    assert prepared_action is not None
    assert native_harness["counts"] == {"catalog": 1, "model": 1}
    assert [item.skill_id for item in prepared_action.policy.packet.plan.selected] == [
        "suspense-writing"
    ]
    assert "golden-finger-writing" in prepared_action.policy.packet.plan.unresolved_ids

    middleware = NativeWritingMethodMiddleware(
        session_id="native-session-58",
        prepare=lambda _text: prepare_harness(
            native_harness,
            action_id=action_id,
            text=text,
        ),
    )

    async def reply():
        async def model():
            return "正文"

        assert await middleware.on_model_call(
            None,
            {"messages": [], "tools": []},
            model,
        ) == "正文"
        yield "正文事件"

    # The action was prepared above, so a duplicate native transport must not
    # silently execute it again.
    with pytest.raises(NativeActionReplay):
        async for _ in middleware.on_reply(None, {"inputs": text}, reply):
            pass
    assert native_harness["counts"] == {"catalog": 1, "model": 1}

    # Execute a fresh real send through middleware preparation.
    fresh_id = uuid4()
    fresh = NativeWritingMethodMiddleware(
        session_id="native-session-58",
        prepare=lambda current: prepare_harness(
            native_harness,
            action_id=fresh_id,
            text=current,
        ),
    )
    async def fresh_reply():
        async def model():
            return "正文"

        assert await fresh.on_model_call(
            None,
            {"messages": [], "tools": []},
            model,
        ) == "正文"
        yield "正文事件"

    assert [event async for event in fresh.on_reply(None, {"inputs": text}, fresh_reply)] == [
        "正文事件"
    ]
    assert native_harness["counts"] == {"catalog": 3, "model": 3}
    with Session(native_harness["engine"]) as session:
        row = session.scalar(select(WritingSkillDispatch).where(
            WritingSkillDispatch.action_id == fresh_id
        ))
        assert row is not None and row.entry == "native" and row.state == "dispatched"
        assert row.job_ref == f"native:{fresh_id}"
        assert row.method_packet["plan"]["selected"][0]["skill_id"] == "suspense-writing"
        status = native_writing_action_result(
            novel_id=row.novel_id,
            action_id=fresh_id,
            tab_id="anw-tab-native-58",
            document_id=native_harness["document_id"],
            session=session,
        )
        assert status.state == "dispatched"
        assert status.selected_ids == ("suspense-writing",)
        with pytest.raises(HTTPException) as missing:
            native_writing_action_result(
                novel_id=row.novel_id,
                action_id=fresh_id,
                tab_id="anw-tab-native-58",
                document_id=uuid4(),
                session=session,
            )
        assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_native_same_action_changed_text_conflicts_before_current_config(native_harness):
    action_id = uuid4()
    text = "请续写《雾宅来信》，让林澈核查死者来信。"
    assert await prepare_harness(native_harness, action_id=action_id, text=text)
    before = dict(native_harness["counts"])
    with pytest.raises(ActionConflict):
        await prepare_harness(
            native_harness,
            action_id=action_id,
            text=text + "并立刻揭晓真凶。",
        )
    assert native_harness["counts"] == before


@pytest.mark.asyncio
async def test_native_revalidates_public_skill_state_before_model(native_harness):
    action_id = uuid4()
    text = "请续写《雾宅来信》，保持林澈不知道档案篡改者身份。"
    middleware = NativeWritingMethodMiddleware(
        session_id="native-session-58",
        prepare=lambda current: prepare_harness(
            native_harness,
            action_id=action_id,
            text=current,
        ),
    )

    async def reply():
        native_harness["enabled"].remove("suspense-writing")

        async def never():
            pytest.fail("model ran after Skill was disabled")

        await middleware.on_model_call(None, {"messages": [], "tools": []}, never)
        yield None

    with pytest.raises(ActionConflict, match="catalog changed"):
        async for _ in middleware.on_reply(None, {"inputs": text}, reply):
            pass
    with Session(native_harness["engine"]) as session:
        row = session.scalar(select(WritingSkillDispatch).where(
            WritingSkillDispatch.action_id == action_id
        ))
        assert row is not None and row.state == "failed"


@pytest.mark.asyncio
async def test_native_nonwriting_question_creates_no_dispatch_or_config_read(native_harness):
    action_id = uuid4()
    before = dict(native_harness["counts"])
    result = await prepare_harness(
        native_harness,
        action_id=action_id,
        text="《雾宅来信》现在一共有多少章？",
    )
    assert result is None and native_harness["counts"] == before
    with Session(native_harness["engine"]) as session:
        assert session.scalar(select(WritingSkillDispatch).where(
            WritingSkillDispatch.action_id == action_id
        )) is None


@pytest.mark.asyncio
async def test_native_factory_uses_leased_server_action_and_is_closed_by_default(native_harness):
    now = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    snapshot = {
        **native_harness["snapshot"],
        "schemaVersion": 2,
        "capturedAt": now.isoformat(),
        "expiresAt": (now + timedelta(minutes=5)).isoformat(),
        "agentId": "ai-novel-writer",
        "sessionId": "native-session-58",
        "budget": {
            "maxCharacters": 24_000,
            "usedCharacters": 500,
            "truncated": False,
            "omittedFieldIds": [],
        },
    }
    registry = AssistantContextRefRegistry(clock=lambda: now)
    created = registry.create(
        binding=ContextRefBinding(
            owner_token="owner_token_native_58",
            tab_instance="anw-tab-native-58",
            agent_id="ai-novel-writer",
            novel_id=snapshot["novel"]["id"],
            document_id=snapshot["document"]["id"],
            session_id="native-session-58",
        ),
        snapshot=snapshot,
        runtime_app=native_harness["app"],
    )
    ctx = SimpleNamespace(
        agent_id="ai-novel-writer",
        root_agent_id="ai-novel-writer",
        session_id="native-session-58",
        request=SimpleNamespace(
            agent_id="ai-novel-writer",
            session_id="native-session-58",
            request_context={"context_ref": created.context_ref},
        ),
    )
    assert create_native_writing_middleware(ctx, None, registry=registry) is None
    middleware = create_native_writing_middleware(
        ctx,
        None,
        released=True,
        registry=registry,
        session_factory=lambda: Session(native_harness["engine"]),
        model_probe_override=native_harness["model_probe"],
    )
    assert middleware is not None
    text = "请续写《雾宅来信》，让林澈先核查门禁记录，不要提前揭晓。"

    async def reply():
        async def model():
            return "正文"

        assert await middleware.on_model_call(
            None, {"messages": [], "tools": []}, model
        ) == "正文"
        yield "正文事件"

    assert [event async for event in middleware.on_reply(
        None, {"inputs": text}, reply
    )] == ["正文事件"]
    with Session(native_harness["engine"]) as session:
        row = session.scalar(select(WritingSkillDispatch).where(
            WritingSkillDispatch.action_id == created.writing_action_id
        ))
        assert row is not None and row.state == "dispatched" and row.entry == "native"
