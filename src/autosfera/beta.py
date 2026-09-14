from __future__ import annotations

from typing import Any

from autosfera.agents import AGENT_META
from autosfera.config import Settings
from autosfera.skills import build_skill_registry


_PLACEHOLDER_MARKERS = ("demo", "replace", "change-me")


def _placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def beta_readiness(settings: Settings, store: Any, orchestrator: Any) -> dict[str, Any]:
    """Return evidence-based readiness for a reversible, single-dealer beta."""
    database = store.healthcheck()
    documents = orchestrator.kb.documents
    governed_documents = [
        document for document in documents
        if document.metadata.get("version")
        and document.metadata.get("owner")
        and document.metadata.get("status") == "approved"
    ]
    checks = [
        {
            "id": "database",
            "required": True,
            "ok": bool(database.get("ok")),
            "detail": database.get("backend", "unknown"),
        },
        {
            "id": "langgraph",
            "required": True,
            "ok": orchestrator.orchestrator_mode == "langgraph",
            "detail": orchestrator.orchestrator_mode,
        },
        {
            "id": "agents",
            "required": True,
            "ok": len(AGENT_META) == 4,
            "detail": f"{len(AGENT_META)} agents",
        },
        {
            "id": "skills",
            "required": True,
            "ok": len(build_skill_registry()) == 17,
            "detail": f"{len(build_skill_registry())} skills",
        },
        {
            "id": "knowledge_base",
            "required": True,
            "ok": len(documents) >= 15,
            "detail": f"{len(documents)} documents",
        },
        {
            "id": "knowledge_governance",
            "required": True,
            "ok": len(governed_documents) == len(documents),
            "detail": f"{len(governed_documents)}/{len(documents)} approved and versioned",
        },
        {
            "id": "strong_secrets",
            "required": False,
            "ok": not any(
                _placeholder(secret)
                for secret in (
                    settings.auth_secret,
                    settings.action_webhook_secret,
                    settings.research_webhook_secret,
                )
            ),
            "detail": "replace demo secrets before external access",
        },
        {
            "id": "live_llm",
            "required": False,
            "ok": settings.llm_mode == "openai" and bool(settings.openai_api_key),
            "detail": settings.llm_mode,
        },
        {
            "id": "vector_rag",
            "required": False,
            "ok": settings.rag_backend == "pgvector",
            "detail": settings.rag_backend,
        },
        {
            "id": "n8n_action_gateway",
            "required": False,
            "ok": settings.action_gateway_mode == "n8n" and bool(settings.action_webhook_url),
            "detail": settings.action_gateway_mode,
        },
    ]
    blockers = [item["id"] for item in checks if item["required"] and not item["ok"]]
    warnings = [item["id"] for item in checks if not item["required"] and not item["ok"]]
    return {
        "status": "ready_for_controlled_beta" if not blockers else "not_ready",
        "scope": "single_dealer_controlled_beta",
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
    }
