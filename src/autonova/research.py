from __future__ import annotations

import json
from typing import Any

import httpx

from autonova.auth import sign_webhook
from autonova.config import get_settings
from autonova.logging import get_logger
from autonova.storage import PlatformStore


logger = get_logger("autonova.research")


def dispatch_research_job(store: PlatformStore, job: dict[str, Any]) -> None:
    """Send a bounded research job to n8n; never calls Langflow directly."""
    settings = get_settings()
    if not settings.research_webhook_url:
        logger.info("Research job %s queued; webhook is not configured", job["id"])
        return
    payload = {
        "job_id": job["id"],
        "dealer_id": job["dealer_id"],
        "actor": job["actor"],
        "query": job["query"],
        "trace_id": job["trace_id"],
        "idempotency_key": job["idempotency_key"],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    try:
        response = httpx.post(
            settings.research_webhook_url,
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-AutoSfera-Signature": sign_webhook(raw),
            },
            timeout=settings.research_timeout_seconds,
        )
        response.raise_for_status()
        store.update_research_job(job["dealer_id"], job["id"], status="running")
    except Exception as exc:  # dependency/network errors must not break the chat
        logger.exception("Research dispatch failed job=%s", job["id"])
        store.update_research_job(
            job["dealer_id"],
            job["id"],
            status="failed",
            error=f"dispatch_failed: {type(exc).__name__}",
        )
