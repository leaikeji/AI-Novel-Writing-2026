"""Isolated test PawApp. Source copies are assembled by the test runner only."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends
from qwenpaw.pawapp import PawApp, get_ctx

from .backend.writing_skills.contracts import MethodBlock, SkillInjectionPacketV1, SkillInvocationPlanV1
from .backend.writing_skills.load_policy import ManagedMethodPolicy, PublicLoadCapabilities, create_managed_method_middleware, managed_method_request

pawapp = PawApp(name="S58 isolated probe", app_id="s58-method-probe")
router = APIRouter()


@router.post("/run")
async def run_probe(host_skill: bool = True, novel_tool: bool = False, ctx=Depends(get_ctx)):
    # Assembled from the project's source, never copied from host private state.
    method = "S58_PAWAPP_METHOD_BYTES\n" + (Path(__file__).parent / "probe-assets" / "prose-writing.md").read_text()
    block = MethodBlock(skill_id="prose-writing", path="SKILL.md", text=method, sha256=hashlib.sha256(method.encode()).hexdigest())
    plan = SkillInvocationPlanV1(task="chapter_body", primary_skill="prose-writing", source_hash="a"*64, catalog_version="b"*64, genre_state="excluded", mechanism_state="excluded")
    policy = ManagedMethodPolicy(
        SkillInjectionPacketV1(plan=plan, blocks=(block,), estimated_tokens=(len(method) + 2) // 3),
        frozenset({"novel_get_context"}) if novel_tool else frozenset(),
    )
    checks = []
    async def check():
        checks.append(True)
    # Synthetic transport gate is only for this zero-model fixture. Production
    # gates cannot be enabled by this test endpoint or a client-supplied marker.
    with managed_method_request(policy, session_id=f"s58-probe:{uuid4()}",
                                capabilities=PublicLoadCapabilities(True, True, True), entry="button", verify_current=check) as binding:
        reply = await replace(ctx, agent_id="ai-novel-writer").chat(
            "Return S58_PROBE_OK only. This is a test.", skill="prose-writing" if host_skill else None, session_id=binding.session_id)
    return {"factory_claimed": binding.factory_claimed, "observed_model_calls": binding.observed_model_calls,
            "authorization_checks": len(checks), "binding_expired": not binding.active,
            "reply_type": type(reply).__name__}


pawapp.include_router(router)


class ProbePlugin:
    def register(self, api):
        if not os.environ.get("AI_NOVEL_DATABASE_URL", "").endswith("@postgres:5432/ai_novel_s58_test"):
            raise RuntimeError("S58 probe may run only in its disposable test environment")
        pawapp.register(api)
        api.register_middleware(create_managed_method_middleware, priority=65)


plugin = ProbePlugin()
