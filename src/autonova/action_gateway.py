from __future__ import annotations

import json
import time
from typing import Any

import httpx

from autonova.auth import sign_action_webhook
from autonova.config import get_settings
from autonova.logging import get_logger


logger = get_logger("autonova.action_gateway")
ACTION_KINDS = frozenset({"lead", "test_drive", "service"})
APPROVER_ROLES = {
    "lead": frozenset({"admin", "sales"}),
    "test_drive": frozenset({"admin", "sales"}),
    "service": frozenset({"admin", "service"}),
}


def can_approve(kind: str, role: str) -> bool:
    return role in APPROVER_ROLES.get(kind, frozenset())


def execute_action(store: Any, dealer_id: str, action_id: str) -> dict[str, Any] | None:
    """Atomically claim and execute one approved action.

    SQLite/PostgreSQL is the durable source of truth. Only the process that wins
    the approved -> running transition may dispatch the side effect.
    """
    job = store.claim_action_job(dealer_id, action_id)
    if job is None:
        logger.info("action_claim_skipped dealer_id=%s action_id=%s", dealer_id, action_id)
        return store.get_action_job(dealer_id, action_id)
    logger.info(
        "action_dispatch_started dealer_id=%s action_id=%s trace_id=%s kind=%s attempt=%s mode=%s",
        dealer_id, action_id, job["trace_id"], job["kind"], job["attempt_count"],
        get_settings().action_gateway_mode,
    )
    settings = get_settings()
    if settings.action_gateway_mode == "mock":
        return _execute_demo_crm(store, job)
    if settings.action_gateway_mode != "n8n":
        return _fail(store, job, "configuration_error: unsupported ACTION_GATEWAY_MODE")
    if not settings.action_webhook_url:
        return _fail(store, job, "configuration_error: ACTION_WEBHOOK_URL is empty")
    return _dispatch_n8n(store, job)


def _execute_demo_crm(store: Any, job: dict[str, Any]) -> dict[str, Any] | None:
    payload = job["payload"]
    try:
        request = store.create_request(
            job["dealer_id"],
            job["kind"],
            customer_name=payload.get("customer_name"),
            phone=payload.get("phone"),
            vehicle=payload.get("vehicle"),
            preferred_at=payload.get("preferred_at"),
            comment=payload.get("comment") or "Создано Action Gateway после подтверждения",
            source="action-gateway-demo",
            source_ref=f"action:{job['id']}",
        )
        result = {"provider": "demo_crm", "request_id": request["id"]}
        completed = store.finish_action_job(
            job["dealer_id"], job["id"], "completed", "demo-crm", result=result
        )[0]
        logger.info(
            "action_completed dealer_id=%s action_id=%s trace_id=%s provider=demo_crm request_id=%s",
            job["dealer_id"], job["id"], job["trace_id"], request["id"],
        )
        return completed
    except Exception as exc:
        logger.exception("Demo CRM action failed action=%s", job["id"])
        return _fail(store, job, f"execution_failed: {type(exc).__name__}")


def _dispatch_n8n(store: Any, job: dict[str, Any]) -> dict[str, Any] | None:
    settings = get_settings()
    payload = {
        "action_id": job["id"],
        "dealer_id": job["dealer_id"],
        "kind": job["kind"],
        "payload": job["payload"],
        "trace_id": job["trace_id"],
        "idempotency_key": job["idempotency_key"],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    attempts = max(1, min(settings.action_max_attempts, 5))
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(
                settings.action_webhook_url,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-AutoSfera-Signature": sign_action_webhook(raw),
                },
                timeout=settings.action_timeout_seconds,
            )
            response.raise_for_status()
            logger.info(
                "action_dispatched dealer_id=%s action_id=%s trace_id=%s target=n8n http_status=%s",
                job["dealer_id"], job["id"], job["trace_id"], response.status_code,
            )
            return store.get_action_job(job["dealer_id"], job["id"])
        except httpx.TimeoutException as exc:
            logger.warning("n8n delivery outcome unknown action=%s error=%s", job["id"], type(exc).__name__)
            return store.finish_action_job(
                job["dealer_id"], job["id"], "delivery_unknown", "action-gateway",
                error=f"delivery_unknown: {type(exc).__name__}",
            )[0]
        except Exception as exc:
            logger.warning("n8n dispatch attempt=%s action=%s error=%s", attempt, job["id"], type(exc).__name__)
            if attempt < attempts:
                time.sleep(min(0.25 * 2 ** (attempt - 1), 1.0))
            else:
                return _fail(store, job, f"dispatch_failed: {type(exc).__name__}")
    return None


def _fail(store: Any, job: dict[str, Any], error: str) -> dict[str, Any] | None:
    failed = store.finish_action_job(
        job["dealer_id"], job["id"], "failed", "action-gateway", error=error
    )[0]
    logger.error(
        "action_failed dealer_id=%s action_id=%s trace_id=%s error=%s",
        job["dealer_id"], job["id"], job["trace_id"], error,
    )
    return failed
