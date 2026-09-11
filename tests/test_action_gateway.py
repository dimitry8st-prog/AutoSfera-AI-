from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

import autonova.api.main as api_main
from autonova.action_gateway import execute_action
from autonova.api.main import create_app
from autonova.auth import sign_action_webhook
from autonova.config import get_settings
from autonova.llm import MockLLMClient
from autonova.orchestrator import AIOrchestrator
from autonova.storage import PlatformStore


def _action(store: PlatformStore, *, kind: str = "test_drive") -> dict:
    action, created = store.create_action_job(
        "main-salon", "anonymous", "session-1", kind,
        {"phone": "+79991234567", "vehicle": "Nova Drive"},
        f"idem-{uuid4()}", str(uuid4()),
    )
    assert created
    return action


def _client(monkeypatch, tmp_path) -> tuple[TestClient, PlatformStore]:
    store = PlatformStore(tmp_path / "actions.db")
    orch = AIOrchestrator(store=store, llm=MockLLMClient())
    monkeypatch.setattr(api_main, "get_store", lambda: store)
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: orch)
    return TestClient(create_app()), store


def _headers(client: TestClient, role: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/token", json={"username": role, "password": f"{role}-demo"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_action_store_is_durable_idempotent_and_audited(tmp_path) -> None:
    path = tmp_path / "durable.db"
    store = PlatformStore(path)
    key = "chat:session:test-drive"
    first, created = store.create_action_job(
        "main-salon", "guest", "session", "test_drive", {"phone": "+79990000000"}, key, "trace"
    )
    duplicate, duplicate_created = store.create_action_job(
        "main-salon", "guest", "session", "test_drive", {"phone": "+70000000000"}, key, "other"
    )
    assert created is True and duplicate_created is False
    assert duplicate["id"] == first["id"]
    assert PlatformStore(path).get_action_job("main-salon", first["id"])["status"] == "waiting_approval"
    assert [event["event_type"] for event in store.list_action_events("main-salon", first["id"])] == ["proposed"]


def test_approved_demo_action_creates_exactly_one_request(tmp_path) -> None:
    store = PlatformStore(tmp_path / "demo.db")
    action = _action(store)
    reviewed, changed = store.review_action_job("main-salon", action["id"], "approve", "sales")
    assert changed and reviewed["status"] == "approved"
    completed = execute_action(store, "main-salon", action["id"])
    assert completed["status"] == "completed"
    assert completed["result"]["request_id"]
    assert len(store.list_requests("main-salon")) == 1
    assert execute_action(store, "main-salon", action["id"])["status"] == "completed"
    assert len(store.list_requests("main-salon")) == 1


def test_rejected_action_never_creates_request(tmp_path) -> None:
    store = PlatformStore(tmp_path / "reject.db")
    action = _action(store)
    rejected, changed = store.review_action_job("main-salon", action["id"], "reject", "sales")
    assert changed and rejected["status"] == "rejected"
    assert execute_action(store, "main-salon", action["id"])["status"] == "rejected"
    assert store.list_requests("main-salon") == []


def test_chat_proposes_action_without_creating_request(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/chat",
        json={"message": "Запишите на тест-драйв Nova Drive, телефон +79991234567"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["skill"] == "test_drive_booking"
    assert body["action_status"] == "waiting_approval"
    assert body["request_id"] is None
    assert store.list_requests("main-salon") == []


def test_sales_lead_is_collected_across_turns_and_requires_approval(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    first = client.post(
        "/api/chat",
        json={"message": "Ищу кроссовер до 3 млн и хочу передать заявку менеджеру"},
    )
    assert first.status_code == 200
    assert first.json()["action_id"] is None
    assert "имя" in first.json()["reply"] and "телефон" in first.json()["reply"]

    second = client.post(
        "/api/chat",
        json={
            "message": "Меня зовут Дмитрий, телефон +79991234567",
            "session_id": first.json()["session_id"],
        },
    )
    body = second.json()
    assert second.status_code == 200
    assert body["skill"] == "vehicle_selection"
    assert body["action_status"] == "waiting_approval"
    assert body["collected_fields"]["customer_name"] == "Дмитрий"
    assert body["collected_fields"]["phone"] == "+79991234567"
    assert store.list_requests("main-salon") == []

    approved = client.post(
        f"/api/actions/{body['action_id']}/review",
        json={"decision": "approve"},
        headers=_headers(client, "sales"),
    )
    assert approved.status_code == 200
    requests = store.list_requests("main-salon")
    assert len(requests) == 1
    assert requests[0]["kind"] == "lead"
    assert requests[0]["customer_name"] == "Дмитрий"
    assert requests[0]["phone"] == "+79991234567"


def test_sales_lead_duplicate_message_reuses_one_action(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    payload = {
        "message": (
            "Передайте заявку менеджеру: меня зовут Дмитрий, "
            "телефон +79991234567, нужен Nova Drive"
        )
    }
    first = client.post("/api/chat", json=payload).json()
    payload["session_id"] = first["session_id"]
    second = client.post("/api/chat", json=payload).json()
    assert first["action_id"] == second["action_id"]
    assert len(store.list_action_jobs("main-salon")) == 1


def test_service_cannot_approve_sales_lead(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action, _ = store.create_action_job(
        "main-salon", "guest", "session", "lead",
        {"customer_name": "Дмитрий", "phone": "+79991234567", "vehicle": "Nova Drive"},
        "lead-role-check", str(uuid4()),
    )
    denied = client.post(
        f"/api/actions/{action['id']}/review",
        json={"decision": "approve"},
        headers=_headers(client, "service"),
    )
    assert denied.status_code == 403
    assert store.list_requests("main-salon") == []


def test_sales_can_approve_test_drive_but_service_cannot(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    denied = client.post(
        f"/api/actions/{action['id']}/review",
        json={"decision": "approve"}, headers=_headers(client, "service"),
    )
    assert denied.status_code == 403
    approved = client.post(
        f"/api/actions/{action['id']}/review",
        json={"decision": "approve"}, headers=_headers(client, "sales"),
    )
    assert approved.status_code == 200
    assert store.get_action_job("main-salon", action["id"])["status"] == "completed"
    assert len(store.list_requests("main-salon")) == 1


def test_duplicate_review_is_rejected(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    headers = _headers(client, "sales")
    assert client.post(f"/api/actions/{action['id']}/review", json={"decision": "reject"}, headers=headers).status_code == 200
    assert client.post(f"/api/actions/{action['id']}/review", json={"decision": "approve"}, headers=headers).status_code == 409


def test_callback_requires_signature_and_is_idempotent(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    running = store.claim_action_job("main-salon", action["id"])
    payload = {
        "action_id": action["id"], "dealer_id": "main-salon", "trace_id": running["trace_id"],
        "status": "completed", "result": {"external_id": "n8n-1"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    assert client.post("/api/actions/callback", content=raw).status_code == 401
    headers = {"Content-Type": "application/json", "X-AutoSfera-Signature": sign_action_webhook(raw)}
    first = client.post("/api/actions/callback", content=raw, headers=headers)
    assert first.status_code == 200 and first.json()["accepted"] is True
    second = client.post("/api/actions/callback", content=raw, headers=headers)
    assert second.status_code == 200 and second.json()["accepted"] is False


def test_callback_rejects_wrong_trace(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    store.claim_action_job("main-salon", action["id"])
    payload = {"action_id": action["id"], "dealer_id": "main-salon", "trace_id": "wrong", "status": "completed"}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    response = client.post(
        "/api/actions/callback", content=raw,
        headers={"Content-Type": "application/json", "X-AutoSfera-Signature": sign_action_webhook(raw)},
    )
    assert response.status_code == 409


def test_n8n_failure_is_bounded_and_retryable(monkeypatch, tmp_path) -> None:
    store = PlatformStore(tmp_path / "n8n-failure.db")
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    monkeypatch.setenv("ACTION_GATEWAY_MODE", "n8n")
    monkeypatch.setenv("ACTION_WEBHOOK_URL", "https://n8n.invalid/action")
    monkeypatch.setenv("ACTION_MAX_ATTEMPTS", "1")
    get_settings.cache_clear()

    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr("autonova.action_gateway.httpx.post", unavailable)
    failed = execute_action(store, "main-salon", action["id"])
    assert failed["status"] == "failed"
    assert failed["error"] == "dispatch_failed: ConnectionError"
    assert store.list_requests("main-salon") == []
    retried, changed = store.retry_action_job("main-salon", action["id"], "sales")
    assert changed and retried["status"] == "approved"
    get_settings.cache_clear()


def test_startup_recovers_approved_action(monkeypatch, tmp_path) -> None:
    store = PlatformStore(tmp_path / "recovery.db")
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    orch = AIOrchestrator(store=store, llm=MockLLMClient())
    monkeypatch.setattr(api_main, "get_store", lambda: store)
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: orch)
    with TestClient(create_app()):
        pass
    assert store.get_action_job("main-salon", action["id"])["status"] == "completed"
    assert len(store.list_requests("main-salon")) == 1


def test_timeout_is_unknown_and_late_callback_can_complete(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    monkeypatch.setenv("ACTION_GATEWAY_MODE", "n8n")
    monkeypatch.setenv("ACTION_WEBHOOK_URL", "https://n8n.invalid/action")
    get_settings.cache_clear()

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("outcome unknown")

    monkeypatch.setattr("autonova.action_gateway.httpx.post", timeout)
    unknown = execute_action(store, "main-salon", action["id"])
    assert unknown["status"] == "delivery_unknown"
    assert store.retry_action_job("main-salon", action["id"], "sales")[1] is False

    payload = {
        "action_id": action["id"], "dealer_id": "main-salon", "trace_id": action["trace_id"],
        "status": "completed", "result": {"external_id": "late-1"},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    response = client.post(
        "/api/actions/callback", content=raw,
        headers={"Content-Type": "application/json", "X-AutoSfera-Signature": sign_action_webhook(raw)},
    )
    assert response.status_code == 200 and response.json()["accepted"] is True
    assert store.get_action_job("main-salon", action["id"])["status"] == "completed"
    get_settings.cache_clear()


def test_action_logs_lifecycle_without_personal_payload(caplog, tmp_path) -> None:
    store = PlatformStore(tmp_path / "logging.db")
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    with caplog.at_level(logging.INFO, logger="autonova.action_gateway"):
        execute_action(store, "main-salon", action["id"])
    text = caplog.text
    assert "action_dispatch_started" in text
    assert "action_completed" in text
    assert action["id"] in text and action["trace_id"] in text
    assert "+79991234567" not in text


def test_employee_can_view_but_cannot_approve(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    headers = _headers(client, "employee")
    listing = client.get("/api/actions", headers=headers)
    assert listing.status_code == 200 and listing.json()["items"][0]["id"] == action["id"]
    denied = client.post(
        f"/api/actions/{action['id']}/review",
        json={"decision": "approve"}, headers=headers,
    )
    assert denied.status_code == 403
    assert store.get_action_job("main-salon", action["id"])["status"] == "waiting_approval"


def test_service_role_approves_only_service_action(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store, kind="service")
    response = client.post(
        f"/api/actions/{action['id']}/review",
        json={"decision": "approve"}, headers=_headers(client, "service"),
    )
    assert response.status_code == 200
    completed = store.get_action_job("main-salon", action["id"])
    assert completed["status"] == "completed"
    assert store.list_requests("main-salon")[0]["kind"] == "service"


def test_actions_are_isolated_by_dealer(tmp_path) -> None:
    store = PlatformStore(tmp_path / "dealer-isolation.db")
    action, _ = store.create_action_job(
        "salon-1", "guest", "session", "test_drive", {"phone": "+79990000000"},
        "isolation-key", str(uuid4()),
    )
    assert store.get_action_job("salon-2", action["id"]) is None
    assert store.list_action_jobs("salon-2") == []
    assert store.list_action_events("salon-2", action["id"]) == []


def test_unsupported_action_kind_is_rejected(tmp_path) -> None:
    store = PlatformStore(tmp_path / "invalid-kind.db")
    try:
        store.create_action_job(
            "main-salon", "guest", "session", "delete_customer", {},
            "invalid-kind", str(uuid4()),
        )
    except ValueError as exc:
        assert str(exc) == "unsupported action kind"
    else:
        raise AssertionError("unsupported action kind must be rejected")


def test_retry_endpoint_executes_failed_action(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    action = _action(store)
    store.review_action_job("main-salon", action["id"], "approve", "sales")
    store.claim_action_job("main-salon", action["id"])
    store.finish_action_job(
        "main-salon", action["id"], "failed", "test", error="temporary_failure"
    )
    response = client.post(
        f"/api/actions/{action['id']}/retry", headers=_headers(client, "sales")
    )
    assert response.status_code == 200
    assert store.get_action_job("main-salon", action["id"])["status"] == "completed"
    events = [item["event_type"] for item in store.list_action_events("main-salon", action["id"])]
    assert events == [
        "proposed", "approved", "dispatch_started", "failed",
        "retry_requested", "dispatch_started", "completed",
    ]
