from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Callable
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from autonova.agents import AGENT_META
from autonova.auth import Actor, create_token, decode_token, verify_demo_credentials, verify_webhook
from autonova.channels import build_channels
from autonova.config import ROOT_DIR, get_settings
from autonova.logging import get_logger, setup_logging
from autonova.orchestrator import AIOrchestrator
from autonova.skills import build_skill_registry
from autonova.storage import PlatformStore
from autonova.research import dispatch_research_job

logger = get_logger("autonova.api")
bearer = HTTPBearer(auto_error=False)


def optional_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Actor:
    settings = get_settings()
    if credentials is None:
        return Actor("anonymous", "guest", settings.dealer_id)
    try:
        return decode_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_roles(*roles: str) -> Callable[..., Actor]:
    def dependency(actor: Actor = Depends(optional_actor)) -> Actor:
        if actor.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return actor

    return dependency


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
    collected_fields: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
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


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class RequestUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(new|qualified|scheduled|assigned|done|cancelled)$")
    assigned_to: str | None = Field(default=None, max_length=120)


class ResearchJobRequest(BaseModel):
    query: str = Field(..., min_length=5, max_length=2000)
    idempotency_key: str = Field(..., min_length=8, max_length=160)


class ResearchReviewRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|edit|reject)$")
    note: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=30000)


@lru_cache
def get_orchestrator() -> AIOrchestrator:
    setup_logging()
    return AIOrchestrator(store=get_store())


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
        allow_origins=settings.allowed_origins,
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

    @app.post("/api/auth/token")
    def login(body: LoginRequest) -> dict[str, Any]:
        actor = verify_demo_credentials(body.username, body.password)
        if actor is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        return {
            "access_token": create_token(actor.subject, actor.role, actor.dealer_id),
            "token_type": "bearer",
            "role": actor.role,
            "dealer_id": actor.dealer_id,
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
    def knowledge(actor: Actor = Depends(optional_actor)) -> dict[str, Any]:
        orch = get_orchestrator()
        public_sections = {"company", "sales", "service", "finance", "faq", "glossary"}
        allowed_sections = None if actor.role in {"employee", "admin"} else public_sections
        sections: dict[str, list[dict[str, Any]]] = {}
        for doc in orch.kb.documents:
            if allowed_sections is not None and doc.section not in allowed_sections:
                continue
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
    def chat(body: ChatRequest, actor: Actor = Depends(optional_actor)) -> ChatResponse:
        orch = get_orchestrator()
        channels = build_channels(orch)
        channel = channels.get(body.channel)
        if channel is None:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {body.channel}")
        try:
            allowed_agents = set(AGENT_META)
            if actor.role not in {"employee", "admin"}:
                allowed_agents.discard("EMPLOYEE_AGENT")
            result = orch.handle_message(
                body.message,
                session_id=body.session_id,
                channel=body.channel,
                allowed_agents=allowed_agents,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        store = get_store()
        store.record_conversation(
            dealer_id=actor.dealer_id,
            session_id=result.session_id,
            channel=result.channel,
            agent=result.agent,
            skill=result.skill,
            user_message=body.message,
            assistant_reply=result.reply,
            escalated=result.escalated,
        )
        request_id = None
        request_kind = {
            "test_drive_booking": "test_drive",
            "service_booking": "service",
        }.get(result.skill or "")
        if request_kind and result.collected_fields.get("phone"):
            source_ref = f"chat:{result.session_id}:{result.skill}"
            existing = store.find_request_by_source_ref(actor.dealer_id, source_ref)
            request_row = existing or store.create_request(
                actor.dealer_id,
                request_kind,
                phone=result.collected_fields.get("phone"),
                vehicle=result.collected_fields.get("vehicle"),
                comment="Автоматически создано из подтверждённого сценария чата",
                source="web-chat",
                source_ref=source_ref,
            )
            request_id = request_row["id"]
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
            collected_fields=result.collected_fields,
            request_id=request_id,
            routing_reason=result.routing_reason,
        )

    @app.post("/api/reset")
    def reset(body: ResetRequest) -> dict[str, Any]:
        orch = get_orchestrator()
        session = orch.reset_session(body.session_id)
        return {"session_id": session.session_id, "active_agent": session.active_agent}

    @app.post("/api/requests", status_code=201)
    def create_business_request(
        body: BusinessRequest,
        actor: Actor = Depends(optional_actor),
    ) -> dict[str, Any]:
        return get_store().create_request(
            actor.dealer_id,
            body.kind,
            customer_name=body.customer_name,
            phone=body.phone,
            vehicle=body.vehicle,
            preferred_at=body.preferred_at,
            comment=body.comment,
            source=body.source,
        )

    @app.get("/api/requests")
    def list_business_requests(
        limit: int = 100,
        actor: Actor = Depends(require_roles("admin", "sales", "service", "employee")),
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 500))
        return {"items": get_store().list_requests(actor.dealer_id, safe_limit)}

    @app.patch("/api/requests/{request_id}")
    def update_business_request(
        request_id: str,
        body: RequestUpdate,
        actor: Actor = Depends(require_roles("admin", "sales", "service", "employee")),
    ) -> dict[str, Any]:
        item = get_store().update_request(
            actor.dealer_id,
            request_id,
            status=body.status,
            assigned_to=body.assigned_to,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="request not found")
        return item

    @app.get("/api/analytics/summary")
    def analytics_summary(
        actor: Actor = Depends(require_roles("admin", "sales", "service", "employee")),
    ) -> dict[str, Any]:
        return get_store().analytics(actor.dealer_id)

    @app.get("/api/inventory")
    def inventory() -> dict[str, Any]:
        docs = get_orchestrator().kb.by_section("sales")
        return {
            "items": [
                {"id": doc.id, "title": doc.title, "description": doc.content, "available": True}
                for doc in docs
            ]
        }

    @app.post("/api/research/jobs", status_code=202)
    def create_research_job(
        body: ResearchJobRequest,
        background: BackgroundTasks,
        actor: Actor = Depends(require_roles("admin", "employee")),
    ) -> dict[str, Any]:
        job, created = get_store().create_research_job(
            actor.dealer_id,
            actor.subject,
            body.query,
            body.idempotency_key,
            str(uuid4()),
        )
        if created:
            background.add_task(dispatch_research_job, get_store(), job)
        return {"created": created, "job": job}

    @app.get("/api/research/jobs")
    def list_research_jobs(
        actor: Actor = Depends(require_roles("admin", "employee")),
    ) -> dict[str, Any]:
        return {"items": get_store().list_research_jobs(actor.dealer_id)}

    @app.get("/api/research/jobs/{job_id}")
    def get_research_job(
        job_id: str,
        actor: Actor = Depends(require_roles("admin", "employee")),
    ) -> dict[str, Any]:
        job = get_store().get_research_job(actor.dealer_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="research job not found")
        return job

    @app.post("/api/research/callback")
    async def research_callback(
        request: Request,
        x_autosfera_signature: str = Header(default=""),
    ) -> dict[str, Any]:
        raw = await request.body()
        if not verify_webhook(raw, x_autosfera_signature):
            raise HTTPException(status_code=401, detail="invalid webhook signature")
        try:
            payload = await request.json()
            job_id = str(payload["job_id"])
            dealer_id = str(payload["dealer_id"])
            trace_id = str(payload["trace_id"])
            result = payload["result"]
            sources = payload["sources"]
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="invalid callback contract") from exc
        if not isinstance(result, dict) or not isinstance(sources, list):
            raise HTTPException(status_code=422, detail="result and sources must be structured")
        if not sources or any(not isinstance(s, dict) or not s.get("url") for s in sources):
            raise HTTPException(status_code=422, detail="at least one source URL is required")
        job = get_store().get_research_job(dealer_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="research job not found")
        if trace_id != job["trace_id"]:
            raise HTTPException(status_code=409, detail="trace_id does not match job")
        if job["status"] in {"review", "approved", "rejected"}:
            return {"accepted": False, "status": job["status"]}
        updated = get_store().update_research_job(
            dealer_id,
            job_id,
            status="review",
            result=result,
            sources=sources,
            error=None,
        )
        return {"accepted": True, "job": updated}

    @app.post("/api/research/jobs/{job_id}/review")
    def review_research_job(
        job_id: str,
        body: ResearchReviewRequest,
        actor: Actor = Depends(require_roles("admin", "employee")),
    ) -> dict[str, Any]:
        job = get_store().get_research_job(actor.dealer_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="research job not found")
        if body.action == "reject":
            updated = get_store().update_research_job(
                actor.dealer_id, job_id, status="rejected", review_note=body.note
            )
            return {"job": updated}
        if job["status"] != "review" or not job["result"]:
            raise HTTPException(status_code=409, detail="job is not ready for review")
        result = dict(job["result"])
        content = (body.content if body.action == "edit" else None) or result.get("content") or result.get("summary")
        title = body.title or result.get("title") or f"Исследование: {job['query']}"
        if not content:
            raise HTTPException(status_code=422, detail="approved content is required")
        document, version = get_orchestrator().kb.publish_approved(
            job_id=job_id,
            title=str(title),
            content=str(content),
            sources=job["sources"],
        )
        updated = get_store().update_research_job(
            actor.dealer_id,
            job_id,
            status="approved",
            review_note=body.note,
            published_version=version,
        )
        return {"job": updated, "document_id": document.id, "version": version}

    @app.post("/api/channels/{channel_name}")
    def channel_webhook(
        channel_name: str,
        payload: dict[str, Any],
        _actor: Actor = Depends(require_roles("admin", "employee")),
    ) -> ChatResponse:
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
            collected_fields=result.collected_fields,
            routing_reason=result.routing_reason,
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("autonova.api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
