from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from autonova.agents import AGENT_META
from autonova.channels import build_channels
from autonova.config import ROOT_DIR, get_settings
from autonova.logging import get_logger, setup_logging
from autonova.orchestrator import AIOrchestrator
from autonova.skills import build_skill_registry
from autonova.storage import PlatformStore

logger = get_logger("autonova.api")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
    channel: str = "web"


class ChatResponse(BaseModel):
    session_id: str
    channel: str
    agent: str
    agent_label: str
    greeting: str | None
    reply: str
    skill: str | None
    escalated: bool
    escalation_target: str | None
    rag_ids: list[str]
    routing_reason: str | None = None


class ResetRequest(BaseModel):
    session_id: str


class BusinessRequest(BaseModel):
    kind: str = Field(..., pattern="^(lead|test_drive|service)$")
    customer_name: str | None = None
    phone: str | None = None
    vehicle: str | None = None
    preferred_at: str | None = None
    comment: str | None = None
    source: str = "web"


@lru_cache
def get_orchestrator() -> AIOrchestrator:
    setup_logging()
    return AIOrchestrator()


@lru_cache
def get_store() -> PlatformStore:
    return PlatformStore()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()
    frontend_dir = ROOT_DIR / "frontend"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        orch = get_orchestrator()
        logger.info("API started; sessions=%s", len(orch.sessions))
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AutoSfera AI — мультиагентная платформа для автодилера",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        index_path = frontend_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="frontend not found")
        return FileResponse(index_path)

    @app.get("/health")
    def health() -> dict[str, Any]:
        orch = get_orchestrator()
        return {
            "status": "ok",
            "version": settings.app_version,
            "agents": list(orch.agents),
            "skills": len(build_skill_registry()),
            "kb_documents": len(orch.kb.documents),
            "dealer_id": settings.dealer_id,
            "dealer_name": settings.dealer_name,
        }

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        return {"agents": AGENT_META}

    @app.get("/api/skills")
    def skills() -> dict[str, Any]:
        registry = build_skill_registry()
        return {
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "agent": s.agent,
                    "description": s.description,
                }
                for s in registry.values()
            ]
        }

    @app.get("/api/knowledge")
    def knowledge() -> dict[str, Any]:
        orch = get_orchestrator()
        sections: dict[str, list[dict[str, Any]]] = {}
        for doc in orch.kb.documents:
            sections.setdefault(doc.section, []).append(
                {
                    "id": doc.id,
                    "title": doc.title,
                    "tags": list(doc.tags),
                    "content": doc.content,
                }
            )
        return {"sections": sections}

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(body: ChatRequest) -> ChatResponse:
        orch = get_orchestrator()
        channels = build_channels(orch)
        channel = channels.get(body.channel)
        if channel is None:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {body.channel}")
        try:
            result = channel.receive(
                {"message": body.message, "session_id": body.session_id}
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        get_store().record_conversation(
            dealer_id=settings.dealer_id,
            session_id=result.session_id,
            channel=result.channel,
            agent=result.agent,
            skill=result.skill,
            user_message=body.message,
            assistant_reply=result.reply,
            escalated=result.escalated,
        )
        return ChatResponse(
            session_id=result.session_id,
            channel=result.channel,
            agent=result.agent,
            agent_label=result.agent_label,
            greeting=result.greeting,
            reply=result.reply,
            skill=result.skill,
            escalated=result.escalated,
            escalation_target=result.escalation_target,
            rag_ids=result.rag_ids,
            routing_reason=result.routing_reason,
        )

    @app.post("/api/reset")
    def reset(body: ResetRequest) -> dict[str, Any]:
        orch = get_orchestrator()
        session = orch.reset_session(body.session_id)
        return {"session_id": session.session_id, "active_agent": session.active_agent}

    @app.post("/api/requests", status_code=201)
    def create_business_request(body: BusinessRequest) -> dict[str, Any]:
        return get_store().create_request(
            settings.dealer_id,
            body.kind,
            customer_name=body.customer_name,
            phone=body.phone,
            vehicle=body.vehicle,
            preferred_at=body.preferred_at,
            comment=body.comment,
            source=body.source,
        )

    @app.get("/api/requests")
    def list_business_requests(limit: int = 100) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 500))
        return {"items": get_store().list_requests(settings.dealer_id, safe_limit)}

    @app.get("/api/analytics/summary")
    def analytics_summary() -> dict[str, Any]:
        return get_store().analytics(settings.dealer_id)

    @app.post("/api/channels/{channel_name}")
    def channel_webhook(channel_name: str, payload: dict[str, Any]) -> ChatResponse:
        orch = get_orchestrator()
        channels = build_channels(orch)
        channel = channels.get(channel_name)
        if channel is None:
            raise HTTPException(status_code=404, detail="channel not found")
        result = channel.receive(payload)
        return ChatResponse(
            session_id=result.session_id,
            channel=result.channel,
            agent=result.agent,
            agent_label=result.agent_label,
            greeting=result.greeting,
            reply=result.reply,
            skill=result.skill,
            escalated=result.escalated,
            escalation_target=result.escalation_target,
            rag_ids=result.rag_ids,
            routing_reason=result.routing_reason,
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("autonova.api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
