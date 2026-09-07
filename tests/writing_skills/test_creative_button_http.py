import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.creative_services import (
    build_character_profile_completion_snapshot,
    create_novel_character,
    get_or_create_chapter_creation_draft,
    get_or_create_novel_creation_draft,
    get_or_create_outline_draft,
)
from backend.model_runtime import ModelAudit
from backend.models import ChapterCreationDraft, Novel, Volume
from backend.services import create_document, create_novel, create_volume, save_draft
from backend.writing_skills import button
from backend.writing_skills.catalog import published_skill_ids
from backend.writing_skills.contracts import canonical_hash
from backend.writing_skills.load_policy import (
    PublicLoadCapabilities,
    create_managed_method_middleware,
)
from backend.writing_skills.semantic_runtime import SemanticAdapterObservationV1
from writing_e2e._host_stub import import_creative_api, reply
from .test_persistence import engine


@pytest.fixture
def harness(engine, monkeypatch):
    creative_api = import_creative_api(monkeypatch)
    from backend.writing_skills import creative
    from backend.writing_skills.api import router as writing_skills_router

    with Session(engine) as session:
        draft = get_or_create_novel_creation_draft(
            session, f"s58-managed-creation-{uuid4()}"
        )
        created = create_novel(session, f"s58-managed-outline-{uuid4()}")
        novel_id = UUID(created["id"])
        novel = session.get(Novel, novel_id)
        novel.genre = "悬疑"
        novel.subgenre = "刑侦"
        novel.idea = "停职刑警回到封闭小镇调查旧案。"
        session.commit()
        outline = get_or_create_outline_draft(session, novel_id)
        volume = session.scalar(
            select(Volume)
            .where(Volume.novel_id == novel_id)
            .order_by(Volume.position, Volume.id)
        )
        if volume is None:
            volume_id = UUID(create_volume(session, novel_id, "第一卷")["id"])
        else:
            volume_id = volume.id
        chapter_draft = get_or_create_chapter_creation_draft(
            session,
            novel_id=novel_id,
            volume_id=volume_id,
            draft_key=f"s58-managed-chapter-{uuid4()}",
        )
        review_document = create_document(
            session,
            novel_id,
            "死者来信",
            volume_id=volume_id,
        )
        review_document = save_draft(
            session,
            UUID(review_document["id"]),
            expected_draft_version=review_document["draft_version"],
            content_markdown="林澈在档案室核对死者来信与借阅记录。" * 40,
        )
        profile_character = create_novel_character(
            session,
            novel_id,
            role_type="main",
            name="林澈",
            description="林澈面对证据冲突时会反复核对记录。",
            details={"core_flaw": "过度相信程序正义"},
        )
        profile_snapshot = build_character_profile_completion_snapshot(
            session, novel_id
        )
        novel_snapshot = {
            "title": novel.title,
            "genre": novel.genre,
            "subgenre": novel.subgenre,
            "highlight": novel.highlight,
            "background": novel.background,
            "main_plot": novel.main_plot,
        }
    app = FastAPI()
    app.include_router(creative_api.router, prefix="/api/ai-novel-world-2026")
    app.include_router(writing_skills_router, prefix="/api/ai-novel-world-2026")
    counts = {"model_reads": 0, "catalog_reads": 0, "chat": 0, "injected": 0}
    counts["profile_character_id"] = profile_character["id"]
    counts["profile_character_version"] = profile_character["version"]

    def database():
        with Session(engine) as session:
            yield session

    async def model():
        counts["model_reads"] += 1
        return ModelAudit(
            provider_id="s58-fake",
            model_id="s58-fake-model",
            source="effective-model-api",
            agent_id="ai-novel-writer",
            effective_max_input_length=131072,
        )

    async def chat(prompt, *, skill, session_id):
        counts["chat"] += 1
        assert skill is None
        if counts.get("raise"):
            raise TimeoutError("fake uncertain creative transport")
        context = SimpleNamespace(
            agent_id="ai-novel-writer",
            root_agent_id="ai-novel-writer",
            session_id=session_id,
            request=SimpleNamespace(
                agent_id="ai-novel-writer", session_id=session_id
            ),
        )
        middleware = create_managed_method_middleware(context, None)
        assert middleware is not None
        kwargs = {"messages": [], "tools": []}

        async def raw_model():
            counts["injected"] += 1
            assert kwargs["tools"] == [] and kwargs["tool_choice"] is None
            blocks = kwargs["messages"][-1].content
            assert len(blocks) >= 3
            texts = [getattr(block, "text", "") for block in blocks]
            counts["last_injected_texts"] = texts
            assert any(
                "小说方向与读者承诺" in text
                or "故事设定总表与总体架构" in text
                or "人物塑造与人物弧线" in text
                or "章节大纲与场景链" in text
                or "分层审稿与文风修订" in text
                or "小说正文写作" in text
                for text in texts
            )
            assert any("悬疑" in text for text in texts)

        await middleware.on_model_call(None, kwargs, raw_model)
        if "最应推进的1到3条故事线" in prompt:
            response_text = '{"storyline_ids":[],"reason":"当前主线应承接上一阶段后果。"}'
        elif "精简、可直接写作的章纲" in prompt:
            response_text = (
                '{"title":"死者来信","outline_text":"' +
                "林澈核对死者来信的邮戳与档案编号，发现两者指向不同时间；她要求周栩调取借阅记录，却被孟青山以停职身份拒绝。许遥带来失踪者就诊记录，迫使三人重新排列旧案时间线。一次现场核查排除最直接的伪造方式，也暴露警局内部仍有人接触原卷宗。林澈决定用假转移计划试探监视者，代价是公开自己掌握新证词。周栩表面服从，却暗中把借阅日志交给许遥；许遥发现签名笔迹属于已经调离的人，三人的合作因此出现新的信任裂缝。林澈先去地下库房核对受潮卷宗，再用假转移计划试探监视者，代价是公开自己掌握新证词。章末，地下库房的水位报警响起，而借阅记录显示死者当天刚刚签出卷宗。" +
                '"}'
            )
        elif "审阅正文的连续性" in prompt:
            response_text = (
                '{"passed":true,"summary":"正文事实与行动因果保持一致。",'
                '"issues":[]}'
            )
        elif "selection_text" in prompt and "replacement_text" in prompt:
            response_text = (
                '{"replacement_text":"林澈警官",'
                '"short_summary":"补充人物身份称谓。"}'
            )
        elif "为每个角色生成" in prompt and "insufficient_evidence" in prompt:
            response_text = (
                '{"characters":[{"character_id":"'
                + str(counts["profile_character_id"])
                + '","base_version":'
                + str(counts["profile_character_version"])
                + ',"status":"candidate","personality":"面对证据冲突会反复核对，并承担延误行动的风险",'
                '"basis":"designed","confidence":88,"evidence":[{"source_type":"character",'
                '"source_id":"'
                + str(counts["profile_character_id"])
                + '","quote":"林澈面对证据冲突时会反复核对记录。"}],"warnings":[]}]}'
            )
        elif "顶层只能有characters数组" in prompt:
            response_text = (
                '{"characters":['
                '{"name":"林澈","role_type":"main","gender":"女",'
                '"identity_summary":"停职刑警","personality_summary":"谨慎复核证据并独自承担风险",'
                '"core_goal":"查清旧案","bio":"十年前参与过失踪案调查。"},'
                '{"name":"周栩","role_type":"supporting","gender":"男",'
                '"identity_summary":"档案员","personality_summary":"回避冲突但坚持保存记录",'
                '"core_goal":"找回原始卷宗","bio":"熟悉镇史档案流转。"},'
                '{"name":"许遥","role_type":"supporting","gender":"女",'
                '"identity_summary":"失踪者家属","personality_summary":"帮助他人却隐瞒高风险怀疑",'
                '"core_goal":"确认姐姐下落","bio":"保存着失踪前的就诊记录。"}]}'
            )
        elif "控制在1200到1800个中文可见字符" in prompt:
            response_text = '{"plot_text":"' + ("调查行动改变证据、关系与行动权限。" * 80) + '"}'
        elif "提炼作品亮点" in prompt:
            response_text = '{"highlight_text":"死者新证词迫使停职刑警在暴雨封镇期间重查十年前失踪案。"}'
        elif "background_text" in prompt:
            response_text = (
                '{"background_text":"封闭小镇被连日暴雨切断交通，停职刑警在旧档案馆收到死者寄出的新证词，'
                '警局内部的沉默与失踪名单迫使她在期限前重查十年前旧案。"}'
            )
        else:
            response_text = (
                '{"titles":["雾宅来信","消失的门牌","回声名单","夜访旧楼",'
                '"无人签收","暗门之后","第七码头","倒置房间"]}'
            )
        return reply(
            text=response_text,
            provider_id="s58-fake",
            model_id="s58-fake-model",
        )

    app.dependency_overrides[creative_api.get_session] = database
    app.dependency_overrides[creative_api.get_novel_generation_ctx] = (
        lambda: SimpleNamespace(chat=chat)
    )
    app.dependency_overrides[creative_api.get_novel_effective_model_probe] = lambda: model

    @app.get("/api/skills")
    def skills():
        counts["catalog_reads"] += 1
        return [
            {
                "name": name,
                "source": "plugin:ai-novel-world-2026",
                "enabled": True,
            }
            for name in published_skill_ids(button.SKILLS_ROOT)
        ]

    monkeypatch.setattr(
        creative,
        "CREATION_HELPER_CAPABILITIES",
        PublicLoadCapabilities(True, True, True),
    )
    monkeypatch.setattr(
        creative,
        "NOVEL_CREATIVE_CAPABILITIES",
        PublicLoadCapabilities(True, True, True),
    )
    payload = {
        "scope_type": "novel_creation",
        "scope_id": draft["id"],
        "kind": "novel_naming",
        "expected_scope_version": draft["version"],
        "input_snapshot": {
            "audience": "女频",
            "genre": "悬疑",
            "subgenre": "刑侦",
            "idea": "调查一栋没有门牌的旧楼",
        },
        "writing_action": {
            "action_id": str(uuid4()),
            "tab_id": "creative-http-test",
        },
    }
    outline_payload = {
        "scope_type": "outline",
        "scope_id": outline["id"],
        "novel_id": str(novel_id),
        "kind": "outline_background",
        "expected_scope_version": outline["version"],
        "input_snapshot": {
            "schema_version": "outline-generation-request-v1",
            "intent": "fresh",
            "expected_outline_version": outline["version"],
        },
        "force_new": True,
        "writing_action": {
            "action_id": str(uuid4()),
            "tab_id": "outline-http-test",
        },
    }
    chapter_payloads = {
        "chapter_storyline_recommendation": {
            "scope_type": "chapter_creation",
            "scope_id": chapter_draft["id"],
            "novel_id": str(novel_id),
            "kind": "chapter_storyline_recommendation",
            "expected_scope_version": chapter_draft["version"],
            "force_new": True,
            "input_snapshot": {},
            "writing_action": {
                "action_id": str(uuid4()),
                "tab_id": "chapter-storyline-http-test",
            },
        },
        "chapter_outline": {
            "scope_type": "chapter_creation",
            "scope_id": chapter_draft["id"],
            "novel_id": str(novel_id),
            "kind": "chapter_outline",
            "expected_scope_version": chapter_draft["version"],
            "force_new": True,
            "input_snapshot": {"rewrite_attempt": 1},
            "writing_action": {
                "action_id": str(uuid4()),
                "tab_id": "chapter-outline-http-test",
            },
        },
        "review": {
            "scope_type": "document",
            "scope_id": review_document["id"],
            "novel_id": str(novel_id),
            "document_id": review_document["id"],
            "kind": "review",
            "expected_scope_version": review_document["draft_version"],
            "force_new": True,
            "input_snapshot": {
                "novel_title": novel_snapshot["title"],
                "genre": novel_snapshot["genre"],
                "subgenre": novel_snapshot["subgenre"],
                "chapter_title": "第1章 死者来信",
                "visible_character_count": review_document[
                    "visible_character_count"
                ],
                "outline_text": "",
                "expectation_text": "",
                "content_markdown": review_document["content_markdown"],
                "draft_version": review_document["draft_version"],
                "content_hash": review_document["content_hash"],
            },
            "writing_action": {
                "action_id": str(uuid4()),
                "tab_id": "review-http-test",
            },
        },
        "selection_edit": {
            "scope_type": "document",
            "scope_id": review_document["id"],
            "novel_id": str(novel_id),
            "document_id": review_document["id"],
            "kind": "selection_edit",
            "expected_scope_version": review_document["draft_version"],
            "force_new": False,
            "input_snapshot": {
                "schema_version": 1,
                "selection_id": str(uuid4()),
                "operation": "polish",
                "custom_instruction": None,
                "use_novel_context": False,
                "target": {
                    "novel_id": str(novel_id),
                    "document_id": review_document["id"],
                    "entity_type": "document",
                    "entity_id": review_document["id"],
                    "field_id": "chapter.body",
                    "field_label": "正文",
                    "persistence": "autosave",
                    "context_revision": 7,
                },
                "base": {
                    "field_value_sha256": review_document["content_hash"],
                    "persistence_version_kind": "draft",
                    "persistence_version": review_document["draft_version"],
                    "start_utf16": 0,
                    "end_utf16": 2,
                    "selection_text": "林澈",
                    "selection_text_sha256": (
                        "8b3041b1d6f454ba6bc9472da655a690"
                        "37a6c3aa8e3aeab2ce9a00d51ab2acaf"
                    ),
                    "before": "",
                    "after": review_document["content_markdown"][2:1502],
                },
            },
            "writing_action": {
                "action_id": str(uuid4()),
                "tab_id": "selection-http-test",
            },
        },
        "character_profile_completion": {
            "scope_type": "novel",
            "scope_id": str(novel_id),
            "novel_id": str(novel_id),
            "kind": "character_profile_completion",
            "force_new": True,
            "input_snapshot": {
                "expected_source_hash": canonical_hash(profile_snapshot),
            },
            "writing_action": {
                "action_id": str(uuid4()),
                "tab_id": "character-profile-http-test",
            },
        },
    }
    return app, counts, payload, outline_payload, chapter_payloads


@pytest.mark.asyncio
async def test_creation_helper_claims_then_injects_one_frozen_method_packet(harness):
    app, counts, payload, _, _ = harness
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert first.status_code == 201, first.text
        result = first.json()
        assert result["state"] == "ready"
        assert result["writing_method"]["state"] == "dispatched"
        # Published category methods explicitly exclude pre-book naming. The
        # task still uses its primary direction Skill and does not force a
        # suspense method merely because the author supplied a genre label.
        assert result["writing_method"]["selected_ids"] == []
        methods = result["writing_method"]["details"]["methods"]
        assert [(item["skill_id"], item["version"]) for item in methods] == [
            ("novel-direction", "0.4.0"),
        ]
        assert methods[0]["reference_count"] == 1
        assert counts["chat"] == counts["injected"] == 1
        before = dict(counts)
        replay = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == result["id"]
        assert counts == before
        query = {"tab_id": payload["writing_action"]["tab_id"]}
        recovered = await client.get(
            "/api/ai-novel-world-2026/creation-drafts/"
            f"{payload['scope_id']}/writing-method-actions/"
            f"{payload['writing_action']['action_id']}",
            params=query,
        )
        assert recovered.status_code == 200
        assert recovered.json() == replay.json()
        assert counts == before


@pytest.mark.asyncio
async def test_outline_button_uses_shared_internal_semantic_route_once(
    harness, monkeypatch
):
    from backend.writing_skills import creative

    app, counts, _, outline_payload, _ = harness
    original = creative.generate_managed_creation_helper

    async def semantic_call(_prompt, request):
        counts["semantic"] = counts.get("semantic", 0) + 1
        return SemanticAdapterObservationV1(
            status="ok",
            text=json.dumps({
                "schema_version": "semantic-route-response/1",
                "decisions": [{
                    "skill_id": item.skill_id,
                    "decision": "reject",
                    "evidence_refs": [request.sources[0].key],
                } for item in request.candidates],
            }),
            model_rounds=1,
            tool_calls=0,
            transport_attempts=1,
        )

    async def enabled(**kwargs):
        return await original(
            **kwargs,
            semantic_call_factory=lambda _session, _verify, _model: semantic_call,
        )

    monkeypatch.setattr(creative, "generate_managed_creation_helper", enabled)
    outline_payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto"
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/ai-novel-world-2026/creative-generations",
            json=outline_payload,
        )
        assert first.status_code == 201, first.text
        method = first.json()["writing_method"]
        assert method["state"] == "dispatched"
        assert method["semantic_enabled"] is True
        assert method["auxiliary_calls"] == 1
        assert counts["semantic"] == counts["chat"] == 1
        before = dict(counts)
        replay = await client.post(
            "/api/ai-novel-world-2026/creative-generations",
            json=outline_payload,
        )
        assert replay.status_code == 201
        assert replay.json()["writing_method"]["method_input_hash"] == method[
            "method_input_hash"
        ]
        assert counts == before


@pytest.mark.asyncio
async def test_public_semantic_preference_remains_closed_before_config_io(harness):
    app, counts, payload, _, _ = harness
    payload["writing_action"]["preferences"] = {
        "mode": "auto", "semantic_mode": "auto"
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "semantic routing is not released"
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_key",
    [
        "creation",
        "outline",
        "chapter_storyline_recommendation",
        "chapter_outline",
        "review",
        "selection_edit",
        "character_profile_completion",
    ],
)
async def test_released_server_gate_rejects_legacy_creative_requests_before_io(
    harness,
    payload_key,
):
    app, counts, creation, outline, chapter_payloads = harness
    candidates = {
        "creation": creation,
        "outline": outline,
        **chapter_payloads,
    }
    payload = {**candidates[payload_key]}
    payload.pop("writing_action")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["type"] == "managed_writing_action_required"
    assert counts["model_reads"] == 0
    assert counts["catalog_reads"] == 0
    assert counts["chat"] == 0


@pytest.mark.asyncio
async def test_released_profile_gate_rejects_dedicated_legacy_endpoint_before_io(
    harness,
):
    app, counts, _, _, chapter_payloads = harness
    novel_id = chapter_payloads["character_profile_completion"]["novel_id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/ai-novel-world-2026/novels/{novel_id}/character-profile-completion/generate",
            json={"force_new": False},
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["type"] == "managed_writing_action_required"
    assert counts["model_reads"] == 0
    assert counts["catalog_reads"] == 0
    assert counts["chat"] == 0
@pytest.mark.asyncio
async def test_creation_catalog_returns_exact_scope_and_server_gate(harness):
    app, counts, payload, _, _ = harness
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={
                "creation_draft_id": payload["scope_id"],
                "tab_id": payload["writing_action"]["tab_id"],
            },
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["creation_helper_available"] is True
    assert result["chapter_body_available"] is False
    assert result["scope"] == {
        "owner_id": "29cf94d9-a5c9-54ec-912c-5dfff8738c4c",
        "workspace_id": "f0e2e632-bc99-52d2-9916-bb906aa4da6e",
        "kind": "creation_draft",
        "scope_id": payload["scope_id"],
        "document_id": None,
        "tab_id": payload["writing_action"]["tab_id"],
    }


@pytest.mark.asyncio
async def test_creation_helper_unknown_transport_never_replays(harness):
    app, counts, payload, _, _ = harness
    payload["writing_action"]["action_id"] = str(uuid4())
    counts["raise"] = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert first.status_code == 502, first.text
        assert first.json()["detail"]["writing_method"]["state"] == "unknown"
        before = dict(counts)
        replay = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert replay.status_code == 201
        assert replay.json()["writing_method"]["state"] == "unknown"
        assert counts == before


@pytest.mark.asyncio
async def test_unreleased_creative_kind_cannot_enter_managed_path(harness):
    app, counts, payload, _, _ = harness
    payload.update(
        kind="novel_cover",
        input_snapshot={"idea": "media task"},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 503
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
async def test_outline_helper_uses_novel_scope_and_story_foundation(harness):
    app, counts, _, payload, _ = harness
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        catalog = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={
                "novel_id": payload["novel_id"],
                "creative_kind": payload["kind"],
                "tab_id": payload["writing_action"]["tab_id"],
            },
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["novel_creative_available"] is True
        assert catalog.json()["scope"]["kind"] == "novel"

        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["state"] == "ready"
        assert result["output_json"]["background_text"].startswith("封闭小镇")
        assert result["writing_method"]["selected_ids"] == ["suspense-writing"]
        methods = result["writing_method"]["details"]["methods"]
        assert [item["skill_id"] for item in methods] == [
            "story-foundation",
            "suspense-writing",
        ]
        assert counts["chat"] == counts["injected"] == 1
        assert any(
            "故事设定总表与总体架构" in text
            for text in counts["last_injected_texts"]
        )

        before = dict(counts)
        recovered = await client.get(
            f"/api/ai-novel-world-2026/novels/{payload['novel_id']}"
            f"/writing-method-actions/{payload['writing_action']['action_id']}",
            params={"tab_id": payload["writing_action"]["tab_id"]},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["id"] == result["id"]
        assert counts == before


@pytest.mark.parametrize(
    ("kind", "output_key", "primary_skill", "primary_heading"),
    [
        (
            "outline_characters",
            "characters",
            "character-craft",
            "人物塑造与人物弧线",
        ),
        (
            "outline_plot",
            "plot_text",
            "story-foundation",
            "故事设定总表与总体架构",
        ),
        (
            "outline_highlight",
            "highlight_text",
            "story-foundation",
            "故事设定总表与总体架构",
        ),
    ],
)
@pytest.mark.asyncio
async def test_remaining_outline_helpers_use_their_frozen_primary_method(
    harness,
    kind,
    output_key,
    primary_skill,
    primary_heading,
):
    app, counts, _, payload, _ = harness
    payload["kind"] = kind
    payload["writing_action"] = {
        "action_id": str(uuid4()),
        "tab_id": f"{kind}-http-test",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["state"] == "ready"
        assert result["output_json"][output_key]
        assert result["writing_method"]["selected_ids"] == ["suspense-writing"]
        assert [
            item["skill_id"]
            for item in result["writing_method"]["details"]["methods"]
        ] == [primary_skill, "suspense-writing"]
        assert counts["chat"] == counts["injected"] == 1
        assert any(
            primary_heading in text for text in counts["last_injected_texts"]
        )


@pytest.mark.parametrize(
    ("kind", "output_key"),
    [
        ("chapter_storyline_recommendation", "storyline_ids"),
        ("chapter_outline", "outline_text"),
    ],
)
@pytest.mark.asyncio
async def test_chapter_helpers_bind_exact_draft_and_use_chapter_method(
    harness,
    kind,
    output_key,
):
    app, counts, _, _, chapter_payloads = harness
    payload = chapter_payloads[kind]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        catalog = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={
                "novel_id": payload["novel_id"],
                "creative_kind": kind,
                "tab_id": payload["writing_action"]["tab_id"],
            },
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["novel_creative_available"] is True
        assert catalog.json()["scope"]["kind"] == "novel"

        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["state"] == "ready"
        assert output_key in result["output_json"]
        assert result["writing_method"]["selected_ids"] == ["suspense-writing"]
        assert [
            item["skill_id"]
            for item in result["writing_method"]["details"]["methods"]
        ] == ["chapter-outline", "suspense-writing"]
        assert counts["chat"] == counts["injected"] == 1
        assert any(
            "章节大纲与场景链" in text
            for text in counts["last_injected_texts"]
        )

        before = dict(counts)
        recovered = await client.get(
            f"/api/ai-novel-world-2026/novels/{payload['novel_id']}"
            f"/writing-method-actions/{payload['writing_action']['action_id']}",
            params={"tab_id": payload["writing_action"]["tab_id"]},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["id"] == result["id"]
        assert counts == before


@pytest.mark.asyncio
async def test_chapter_helper_rejects_stale_version_before_catalog_or_model(harness):
    app, counts, _, _, chapter_payloads = harness
    payload = chapter_payloads["chapter_outline"]
    payload["expected_scope_version"] += 1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["type"] == "managed_creation_scope_invalid"
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
async def test_chapter_helper_rejects_browser_story_material_before_model(harness):
    app, counts, _, _, chapter_payloads = harness
    payload = chapter_payloads["chapter_storyline_recommendation"]
    payload["input_snapshot"] = {
        "novel": {"genre": "玄幻"},
        "storylines": [{"id": str(uuid4()), "title": "跨书伪造线"}],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 422, response.text
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
async def test_chapter_helper_rejects_foreign_persisted_ids_before_catalog_or_model(
    harness,
    engine,
):
    app, counts, _, _, chapter_payloads = harness
    payload = chapter_payloads["chapter_outline"]
    with Session(engine) as session:
        draft = session.get(ChapterCreationDraft, UUID(payload["scope_id"]))
        draft.data_json = {"required_role_ids": [str(uuid4())]}
        session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["type"] == "managed_creation_helper_failed"
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
async def test_review_binds_exact_working_copy_and_uses_review_method(harness):
    app, counts, _, _, payloads = harness
    payload = payloads["review"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        catalog = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={
                "document_id": payload["document_id"],
                "creative_kind": "review",
                "tab_id": payload["writing_action"]["tab_id"],
            },
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["document_creative_available"] is True
        assert catalog.json()["chapter_body_available"] is False
        assert catalog.json()["scope"]["document_id"] == payload["document_id"]

        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["state"] == "ready"
        assert result["output_json"] == {
            "passed": True,
            "summary": "正文事实与行动因果保持一致。",
            "issues": [],
        }
        assert result["writing_method"]["selected_ids"] == ["suspense-writing"]
        assert [
            item["skill_id"]
            for item in result["writing_method"]["details"]["methods"]
        ] == ["style-review", "suspense-writing"]
        assert counts["chat"] == counts["injected"] == 1
        assert any(
            "分层审稿与文风修订" in text
            for text in counts["last_injected_texts"]
        )

        before = dict(counts)
        recovered = await client.get(
            f"/api/ai-novel-world-2026/documents/{payload['document_id']}"
            f"/writing-method-actions/{payload['writing_action']['action_id']}",
            params={"tab_id": payload["writing_action"]["tab_id"]},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["id"] == result["id"]
        assert counts == before


@pytest.mark.asyncio
async def test_review_rejects_forged_content_before_catalog_or_model(harness):
    app, counts, _, _, payloads = harness
    payload = payloads["review"]
    payload["input_snapshot"]["content_markdown"] += "伪造"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["type"] == "managed_creation_scope_invalid"
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
async def test_selection_binds_exact_body_and_returns_unapplied_v2_diff(harness):
    app, counts, _, _, payloads = harness
    payload = payloads["selection_edit"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        catalog = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={
                "document_id": payload["document_id"],
                "creative_kind": "selection_edit",
                "selection_operation": "polish",
                "tab_id": payload["writing_action"]["tab_id"],
            },
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["document_creative_available"] is True

        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["state"] == "ready"
        assert result["output_text"] == "林澈警官"
        assert result["output_json"]["schema_version"] == 2
        assert result["output_json"]["selection_id"] == payload["input_snapshot"]["selection_id"]
        assert result["output_json"]["replacement_text"] == "林澈警官"
        assert [
            item["skill_id"]
            for item in result["writing_method"]["details"]["methods"]
        ] == ["prose-writing", "suspense-writing"]
        assert counts["chat"] == counts["injected"] == 1

        before = dict(counts)
        recovered = await client.get(
            f"/api/ai-novel-world-2026/documents/{payload['document_id']}"
            f"/writing-method-actions/{payload['writing_action']['action_id']}",
            params={"tab_id": payload["writing_action"]["tab_id"]},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == result
        assert counts == before


@pytest.mark.asyncio
async def test_selection_rejects_forged_body_before_catalog_or_model(harness):
    app, counts, _, _, payloads = harness
    payload = payloads["selection_edit"]
    payload["input_snapshot"]["base"]["selection_text"] = "伪造"
    payload["input_snapshot"]["base"]["selection_text_sha256"] = "0" * 64
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code in {409, 422}, response.text
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0


@pytest.mark.asyncio
async def test_character_profile_uses_server_snapshot_and_character_method(harness):
    app, counts, _, _, payloads = harness
    payload = payloads["character_profile_completion"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        catalog = await client.get(
            "/api/ai-novel-world-2026/writing-skills",
            params={
                "novel_id": payload["novel_id"],
                "creative_kind": "character_profile_completion",
                "tab_id": payload["writing_action"]["tab_id"],
            },
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["novel_creative_available"] is True

        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["state"] == "ready"
        assert result["output_json"]["schema_version"] == "character-profile-completion-v1"
        assert result["output_json"]["characters"][0]["character_id"] == counts[
            "profile_character_id"
        ]
        assert [
            item["skill_id"]
            for item in result["writing_method"]["details"]["methods"]
        ] == ["character-craft", "suspense-writing"]
        assert counts["chat"] == counts["injected"] == 1
        assert any(
            "人物塑造与人物弧线" in text
            for text in counts["last_injected_texts"]
        )

        before = dict(counts)
        recovered = await client.get(
            f"/api/ai-novel-world-2026/novels/{payload['novel_id']}"
            f"/writing-method-actions/{payload['writing_action']['action_id']}",
            params={"tab_id": payload["writing_action"]["tab_id"]},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json() == result
        assert counts == before


@pytest.mark.asyncio
async def test_character_profile_rejects_changed_source_before_catalog_or_model(harness):
    app, counts, _, _, payloads = harness
    payload = payloads["character_profile_completion"]
    payload["input_snapshot"]["expected_source_hash"] = "0" * 64
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/ai-novel-world-2026/creative-generations", json=payload
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["message"] == "character profile sources changed"
    assert counts["model_reads"] == counts["catalog_reads"] == counts["chat"] == 0
