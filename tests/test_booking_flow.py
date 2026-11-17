from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import autosfera.api.main as api_main
from autosfera.action_gateway import execute_action
from autosfera.api.main import create_app
from autosfera.auth import create_token, sign_action_webhook
from autosfera.llm import MockLLMClient
from autosfera.orchestrator import AIOrchestrator
from autosfera.skills import resolve_preferred_at
from autosfera.storage import PlatformStore


def _client(monkeypatch, tmp_path) -> tuple[TestClient, PlatformStore]:
    store = PlatformStore(tmp_path / "booking.db")
    orch = AIOrchestrator(store=store, llm=MockLLMClient())
    monkeypatch.setattr(api_main, "get_store", lambda: store)
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: orch)
    return TestClient(create_app()), store


def _say(client: TestClient, text: str, previous: dict | None = None) -> dict:
    payload = {"message": text}
    headers = {}
    if previous:
        payload["session_id"] = previous["session_id"]
        headers["X-Session-Token"] = previous["session_token"]
    response = client.post("/api/chat", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    if previous and not body.get("session_token"):
        body["session_token"] = previous["session_token"]
    return body


def _book_test_drive(client: TestClient) -> dict:
    started = _say(client, "Хочу записаться на тест-драйв Nova Drive")
    named = _say(client, "Меня зовут Анна Смирнова, телефон +79991234567", started)
    return _say(client, "18.11.2026 в 15:00", named)


def test_relative_date_keeps_the_day_and_time() -> None:
    now = datetime(2026, 11, 17, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    value, clarification = resolve_preferred_at(
        "завтра в 15:00", now=now, timezone_name="Europe/Moscow"
    )
    assert clarification is None
    assert value == "2026-11-18T15:00+03:00"
    kept, again = resolve_preferred_at(
        "телефон тот же", value, now=now.replace(day=20), timezone_name="Europe/Moscow"
    )
    assert again is None
    assert kept == "2026-11-18T15:00+03:00"


def test_time_without_a_date_is_not_enough() -> None:
    now = datetime(2026, 11, 17, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    value, clarification = resolve_preferred_at("в 15:00", now=now, timezone_name="Europe/Moscow")
    assert value is None
    assert clarification
    vague, ask = resolve_preferred_at("завтра вечером", now=now, timezone_name="Europe/Moscow")
    assert vague is None
    assert ask


def test_test_drive_is_saved_once_and_confirmed_only_after_execution(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    started = _say(client, "Хочу записаться на тест-драйв Nova Drive")
    assert started["request_id"] is None
    assert store.list_requests("main-salon") == []
    saved = _book_test_drive(client)
    assert saved["intake_state"] == "saved"
    assert saved["skill"] == "test_drive_booking"
    assert "не подтверждена" in saved["reply"]
    assert saved["collected_fields"]["preferred_at"].startswith("2026-11-18T15:00")
    repeated = _say(client, "18.11.2026 в 15:00", saved)
    assert repeated["request_id"] == saved["request_id"]
    assert len(store.list_requests("main-salon")) == 1

    store.review_action_job("main-salon", saved["action_id"], "approve", "sales")
    completed = execute_action(store, "main-salon", saved["action_id"])
    assert completed["status"] == "completed"
    assert store.get_request("main-salon", saved["request_id"])["status"] == "confirmed"


def test_service_booking_is_separate_from_test_drive(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    started = _say(client, "Хочу записаться на сервис, стук в подвеске")
    named = _say(client, "Меня зовут Иван Петров, телефон +79990001122", started)
    saved = _say(client, "18.11.2026 в 11:00", named)
    assert saved["agent"] == "SERVICE_AGENT"
    assert saved["skill"] == "service_booking"
    assert saved["intake_state"] == "saved"
    request = store.get_request("main-salon", saved["request_id"])
    assert request["kind"] == "service"
    assert request["status"] == "saved"


def test_changed_time_after_approval_is_not_confirmed_by_the_old_action(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _book_test_drive(client)
    approved, changed = store.review_action_job("main-salon", saved["action_id"], "approve", "sales")
    assert changed and approved["status"] == "approved"
    updated = _say(client, "19.11.2026 в 16:00", saved)
    request = store.get_request("main-salon", saved["request_id"])
    assert request["status"] == "saved"
    assert request["details_version"] == 2
    assert request["preferred_at"].startswith("2026-11-19T16:00")
    execute_action(store, "main-salon", saved["action_id"])
    request = store.get_request("main-salon", saved["request_id"])
    assert request["status"] == "saved"
    assert request["preferred_at"].startswith("2026-11-19T16:00")
    waiting = [
        job for job in store.list_action_jobs("main-salon")
        if job["status"] == "waiting_approval" and job["payload"].get("request_version") == 2
    ]
    assert len(waiting) == 1
    assert updated["request_id"] == saved["request_id"]


def test_late_callback_does_not_confirm_a_changed_running_request(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _book_test_drive(client)
    store.review_action_job("main-salon", saved["action_id"], "approve", "sales")
    running = store.claim_action_job("main-salon", saved["action_id"])
    assert running["status"] == "running"
    _say(client, "19.11.2026 в 16:00", saved)
    job = store.get_action_job("main-salon", saved["action_id"])
    raw = json.dumps({
        "action_id": job["id"],
        "dealer_id": "main-salon",
        "trace_id": job["trace_id"],
        "status": "completed",
        "result": {"provider": "n8n"},
    }).encode()
    response = client.post(
        "/api/actions/callback",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-AutoSfera-Signature": sign_action_webhook(raw),
        },
    )
    assert response.status_code == 200
    request = store.get_request("main-salon", saved["request_id"])
    assert request["status"] == "saved"
    assert request["preferred_at"].startswith("2026-11-19T16:00")


def test_saved_fields_survive_orchestrator_restart(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _book_test_drive(client)
    restarted = AIOrchestrator(store=store, llm=MockLLMClient())
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: restarted)
    follow = _say(client, "телефон тот же +79991234567", saved)
    assert follow["collected_fields"]["customer_name"] == "Анна Смирнова"
    assert follow["collected_fields"]["preferred_at"].startswith("2026-11-18T15:00")
    assert follow["request_id"] == saved["request_id"]


def test_client_session_requires_its_secret_and_internal_session_requires_staff(monkeypatch, tmp_path) -> None:
    client, _store = _client(monkeypatch, tmp_path)
    guest = _say(client, "Хочу записаться на тест-драйв Nova Drive")
    hidden = client.get(f"/api/session/{guest['session_id']}")
    assert hidden.status_code == 401
    wrong = client.get(
        f"/api/session/{guest['session_id']}",
        headers={"X-Session-Token": "not-the-secret"},
    )
    assert wrong.status_code == 401
    owned = client.get(
        f"/api/session/{guest['session_id']}",
        headers={"X-Session-Token": guest["session_token"]},
    )
    assert owned.status_code == 200
    assert owned.json()["history"]
    assert owned.json()["visibility"] == "client"

    employee = client.post(
        "/api/auth/token",
        json={"username": "employee", "password": "employee-demo"},
    ).json()["access_token"]
    internal = client.post(
        "/api/chat",
        json={"message": "Найди внутренний регламент обработки лида"},
        headers={"Authorization": f"Bearer {employee}"},
    ).json()
    leaked = client.get(f"/api/session/{internal['session_id']}")
    assert leaked.status_code == 401
    staff_view = client.get(
        f"/api/session/{internal['session_id']}",
        headers={"Authorization": f"Bearer {employee}"},
    )
    assert staff_view.status_code == 200
    sales = client.post(
        "/api/auth/token", json={"username": "sales", "password": "sales-demo"}
    ).json()["access_token"]
    denied = client.get(
        f"/api/session/{internal['session_id']}",
        headers={"Authorization": f"Bearer {sales}"},
    )
    assert denied.status_code == 403
    outsider = create_token("employee", "employee", f"other-{uuid4()}")
    missing = client.get(
        f"/api/session/{internal['session_id']}",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert missing.status_code == 404


def test_employee_continuation_cannot_put_internal_answers_in_a_client_session(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    guest = _say(client, "Хочу купить автомобиль")
    original = store.load_session("main-salon", guest["session_id"])["history"]
    employee = create_token("employee", "employee", "main-salon")
    internal = client.post(
        "/api/chat",
        json={"message": "Найди внутренний регламент обработки лида", "session_id": guest["session_id"]},
        headers={"Authorization": f"Bearer {employee}", "X-Session-Token": guest["session_token"]},
    )
    assert internal.status_code == 200
    body = internal.json()
    assert body["agent"] == "EMPLOYEE_AGENT"
    assert body["session_id"] != guest["session_id"]
    assert body["session_token"] is None
    restored = client.get(
        f"/api/session/{guest['session_id']}",
        headers={"X-Session-Token": guest["session_token"]},
    )
    assert restored.status_code == 200
    assert restored.json()["history"] == original
    assert restored.json()["visibility"] == "client"
    denied = client.get(
        f"/api/session/{body['session_id']}",
        headers={"X-Session-Token": guest["session_token"]},
    )
    assert denied.status_code == 401
    assert client.get(
        f"/api/session/{body['session_id']}", headers={"Authorization": f"Bearer {employee}"},
    ).status_code == 200


def test_channel_adapter_cannot_append_to_a_client_session(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    guest = _say(client, "Хочу купить автомобиль")
    original = store.load_session("main-salon", guest["session_id"])["history"]
    employee = create_token("employee", "employee", "main-salon")
    response = client.post(
        "/api/channels/telegram",
        json={"text": "Найди внутренний регламент", "chat_id": guest["session_id"]},
        headers={"Authorization": f"Bearer {employee}", "X-Session-Token": guest["session_token"]},
    )
    assert response.status_code == 401
    assert store.load_session("main-salon", guest["session_id"])["history"] == original


def test_unknown_chat_session_id_is_not_adopted(monkeypatch, tmp_path) -> None:
    client, _store = _client(monkeypatch, tmp_path)
    chosen_id = str(uuid4())
    response = client.post("/api/chat", json={"message": "Здравствуйте", "session_id": chosen_id})
    assert response.status_code == 200
    assert response.json()["session_id"] != chosen_id


def test_saving_manager_assignment_preserves_booking_status(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    employee = create_token("sales", "sales", "main-salon")
    for status in ("saved", "confirmed"):
        request = store.create_request("main-salon", "test_drive", status=status)
        response = client.patch(
            f"/api/requests/{request['id']}",
            json={"assigned_to": "Менеджер", "status": status},
            headers={"Authorization": f"Bearer {employee}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == status
        assert response.json()["assigned_to"] == "Менеджер"
