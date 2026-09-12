from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx

from autonova.auth import sign_action_webhook
from autonova.config import get_settings
from autonova.logging import get_logger


logger = get_logger("autonova.action_gateway")
ACTION_KINDS = frozenset({"lead", "test_drive", "service"})
ACTION_TYPE_BY_KIND = {
    "lead": "create_lead",
    "test_drive": "create_test_drive",
    "service": "create_service",
}
KIND_BY_ACTION_TYPE = {value: key for key, value in ACTION_TYPE_BY_KIND.items()}
ACTION_REQUEST_MAX_SKEW_SECONDS = 300
APPROVER_ROLES = {
    "lead": frozenset({"admin", "sales"}),
    "test_drive": frozenset({"admin", "sales"}),
    "service": frozenset({"admin", "service"}),
}


def can_approve(kind: str, role: str) -> bool:
    return role in APPROVER_ROLES.get(kind, frozenset())


def build_action_request(job: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Build the signed ActionRequest v1 envelope sent to n8n WF-00."""
    settings = get_settings()
    kind = job["kind"]
    issued_at = int(now if now is not None else time.time())
    callback_url = settings.action_callback_url or "http://api:8000/api/actions/callback"
    return {
        "request_id": job["id"],
        "action_id": job["id"],
        "trace_id": job["trace_id"],
        "dealer_id": job["dealer_id"],
        "actor": {"subject": job.get("approved_by") or job.get("created_by") or "gateway"},
        "action_type": ACTION_TYPE_BY_KIND[kind],
        "kind": kind,
        "idempotency_key": job["idempotency_key"],
        "issued_at": issued_at,
        "nonce": uuid.uuid4().hex,
        "approval": {
            "required": True,
            "decision": "approve",
            "actor": job.get("approved_by") or "gateway",
        },
        "payload": job["payload"],
        "callback_url": callback_url,
    }


def validate_action_request(request: dict[str, Any], *, now: float | None = None) -> str | None:
    """Return an error code if the WF-00 envelope is not executable."""
    current = int(now if now is not None else time.time())
    action_type = request.get("action_type")
    if action_type not in KIND_BY_ACTION_TYPE:
        return "unsupported_action_type"
    if request.get("kind") not in ACTION_KINDS:
        return "unsupported_kind"
    if KIND_BY_ACTION_TYPE[action_type] != request.get("kind"):
        return "action_type_kind_mismatch"
    issued_at = request.get("issued_at")
    if not isinstance(issued_at, int) or abs(current - issued_at) > ACTION_REQUEST_MAX_SKEW_SECONDS:
        return "stale_or_invalid_timestamp"
    nonce = request.get("nonce")
    if not isinstance(nonce, str) or len(nonce) < 8:
        return "nonce_required"
    if not request.get("idempotency_key") or not request.get("trace_id") or not request.get("dealer_id"):
        return "missing_correlation"
    if not isinstance(request.get("payload"), dict):
        return "invalid_payload"
    return None


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
    payload = build_action_request(job)
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
                    "X-AutoSfera-Timestamp": str(payload["issued_at"]),
                    "X-AutoSfera-Nonce": payload["nonce"],
                },
                timeout=settings.action_timeout_seconds,
            )
            response.raise_for_status()
            logger.info(
                "action_dispatched dealer_id=%s action_id=%s trace_id=%s action_type=%s target=n8n http_status=%s",
                job["dealer_id"], job["id"], job["trace_id"], payload["action_type"],
                response.status_code,
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
