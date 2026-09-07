"""Full public PawApp transport; no monkeypatch, runtime core or real novels."""
from dataclasses import replace
import os
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from qwenpaw.pawapp import PawApp, get_ctx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .backend.database import get_session
from .backend.models import Document, Novel
from .backend.schemas import GenerateChapterRequest
from .backend.model_runtime import effective_model_audit, reply_final_text
from .backend.generation_dependencies import verify_novel_model_reply
from .backend.writing_skills.button import generate_managed_chapter
from .backend.writing_skills.load_policy import PublicLoadCapabilities, create_managed_method_middleware
from .backend.writing_skills.semantic_runtime import public_semantic_call

pawapp = PawApp(name="S58 isolated chapter transport", app_id="s58-chapter-transport")
router = APIRouter()


@router.post("/chapters/{document_id}")
async def run(document_id: UUID, payload: GenerateChapterRequest, request: Request,
              ctx=Depends(get_ctx), session: Session = Depends(get_session)):
    title = session.scalar(select(Novel.title).join(Document, Document.novel_id == Novel.id)
                           .where(Document.id == document_id))
    if title != "s58-method-atomic-test" or payload.writing_action is None:
        raise HTTPException(403, "only the synthetic S58 chapter fixture is allowed")
    session.rollback()
    async def probe():
        result = await effective_model_audit(request.app, agent_id="ai-novel-writer")
        if (result.provider_id, result.model_id) != ("s58-fake", "s58-fake-model"):
            raise HTTPException(403, "only the configured loopback fake model is allowed")
        return result
    managed_ctx = replace(ctx, agent_id="ai-novel-writer")
    capabilities = PublicLoadCapabilities(True, True, True)

    def semantic_factory(session_id, verify_current, configured):
        started = time.monotonic()

        async def verify_reply(reply):
            await verify_novel_model_reply(
                reply,
                configured=configured,
                probe=probe,
                started_monotonic=started,
            )
            return reply_final_text(reply)

        return public_semantic_call(
            ctx=managed_ctx,
            session_id=session_id,
            capabilities=capabilities,
            verify_current=verify_current,
            verify_reply=verify_reply,
        )

    return await generate_managed_chapter(document_id=document_id, request=payload,
        ctx=managed_ctx, model_probe=probe, session=session,
        asgi_app=request.app, capabilities=capabilities,
        semantic_call_factory=(semantic_factory
                               if payload.writing_action.preferences.semantic_mode == "auto"
                               else None))


pawapp.include_router(router)


class FixturePlugin:
    def register(self, api):
        if not os.environ.get("AI_NOVEL_DATABASE_URL", "").endswith("@postgres:5432/ai_novel_s58_test"):
            raise RuntimeError("S58 fixture requires the disposable test database")
        pawapp.register(api)
        api.register_middleware(create_managed_method_middleware, priority=65)


plugin = FixturePlugin()
