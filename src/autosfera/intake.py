from __future__ import annotations

from typing import Any
from uuid import uuid4

from autosfera.logging import get_logger
from autosfera.skills import _missing_booking_labels


logger = get_logger("autosfera.intake")

BOOKING_KINDS = {
    "test_drive_booking": "test_drive",
    "service_booking": "service",
}
_OPEN_ACTION = frozenset({"approved", "running", "delivery_unknown"})


def missing_booking_labels(kind: str, fields: dict[str, Any]) -> list[str]:
    return _missing_booking_labels(kind, fields)


def apply_booking_intake(
    store: Any,
    dealer_id: str,
    actor: str,
    session_id: str,
    kind: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Persist one intake per session and kind. Confirmation is a later state."""
    source_ref = f"intake:{session_id}:{kind}"
    comment = fields.get("issue") or "Сохранено из диалога, ожидает подтверждения"
    details = {
        "customer_name": fields.get("customer_name"),
        "phone": fields.get("phone"),
        "vehicle": fields.get("vehicle"),
        "preferred_at": fields.get("preferred_at"),
        "comment": comment,
        "session_id": session_id,
    }
    existing = store.find_request_by_source_ref(dealer_id, source_ref)
    if existing and existing.get("status") == "confirmed":
        return {"request": existing, "action": None, "intake_state": "confirmed"}
    if existing and existing.get("status") == "cancelled":
        return {"request": existing, "action": None, "intake_state": "cancelled"}
    if existing and existing.get("status") == "saved":
        request = store.update_request_details(dealer_id, existing["id"], **details) or existing
    elif existing:
        request = existing
    else:
        request = store.create_request(
            dealer_id,
            kind,
            source="chat",
            source_ref=source_ref,
            status="saved",
            **details,
        )
    if request.get("status") != "saved":
        state = "confirmed" if request.get("status") == "confirmed" else request.get("status")
        return {"request": request, "action": None, "intake_state": state}

    version = int(request.get("details_version") or 1)
    payload = {
        "customer_name": request.get("customer_name"),
        "phone": request.get("phone"),
        "vehicle": request.get("vehicle"),
        "preferred_at": request.get("preferred_at"),
        "issue": fields.get("issue"),
        "request_id": request["id"],
        "request_version": version,
        "comment": "Подтверждение сохранённой заявки",
    }
    base_key = f"chat:{session_id}:{kind}"
    action, created = store.create_action_job(
        dealer_id, actor, session_id, kind, payload, base_key, str(uuid4()),
    )
    if not created and action.get("status") == "waiting_approval":
        action = store.update_action_payload(dealer_id, action["id"], payload) or action
    elif not created and int((action.get("payload") or {}).get("request_version") or 0) != version:
        if action.get("status") in _OPEN_ACTION or action.get("status") == "completed":
            action, created = store.create_action_job(
                dealer_id, actor, session_id, kind, payload,
                f"{base_key}:v{version}", str(uuid4()),
            )
    logger.info(
        "intake_saved dealer_id=%s request_id=%s kind=%s action_id=%s version=%s created=%s",
        dealer_id, request["id"], kind, action.get("id"), version, created,
    )
    return {"request": request, "action": action, "intake_state": "saved"}
