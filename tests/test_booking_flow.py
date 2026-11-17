from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import autonova.api.main as api_main
from autonova.api.main import create_app
from autonova.config import get_settings
from autonova.llm import MockLLMClient
from autonova.orchestrator import AIOrchestrator
from autonova.skills import customer_faq
from autonova.storage import PlatformStore


def _client(monkeypatch, tmp_path) -> tuple[TestClient, PlatformStore]:
    store = PlatformStore(tmp_path / "booking.db")
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


def _finish_test_drive(client: TestClient) -> dict:
    first = client.post(
        "/api/chat",
        json={"message": "Хочу записаться на тест-драйв Nova Drive"},
    )
    assert first.status_code == 200
    opened = first.json()
    assert opened["agent"] == "SALES_AGENT"
    assert opened["skill"] == "test_drive_booking"
    assert opened["intake_state"] == "collecting"
    assert opened["request_id"] is None
    assert "Предпродажная подготовка" not in opened["reply"]

    named = client.post(
        "/api/chat",
        json={"message": "Меня зовут Анна Смирнова", "session_id": opened["session_id"]},
    )
    assert named.status_code == 200
    assert named.json()["intake_state"] == "collecting"
    assert named.json()["collected_fields"]["customer_name"] == "Анна Смирнова"
    assert named.json()["collected_fields"]["vehicle"] == "Nova Drive"
    assert named.json()["request_id"] is None

    completed = client.post(
        "/api/chat",
        json={
            "message": "Телефон +79991234567, завтра в 15:00",
            "session_id": opened["session_id"],
        },
    )
    assert completed.status_code == 200
    body = completed.json()
    assert body["skill"] == "test_drive_booking"
    assert body["intake_state"] == "saved"
    assert body["request_id"]
    assert body["action_status"] == "waiting_approval"
    assert "не подтверждена" in body["reply"].lower()
    assert "вы записаны" not in body["reply"].lower()
    return body


def test_test_drive_with_booking_word_is_not_service(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _finish_test_drive(client)
    rows = store.list_requests("main-salon")
    assert len(rows) == 1
    assert rows[0]["id"] == saved["request_id"]
    assert rows[0]["kind"] == "test_drive"
    assert rows[0]["status"] == "saved"
    assert rows[0]["phone"] == "+79991234567"
    assert rows[0]["session_id"] == saved["session_id"]


def test_service_request_is_saved_separately_from_test_drive(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    first = client.post("/api/chat", json={"message": "Хочу записаться на сервис"})
    assert first.status_code == 200
    opened = first.json()
    assert opened["agent"] == "SERVICE_AGENT"
    assert opened["skill"] == "service_booking"
    assert opened["intake_state"] == "collecting"
    assert store.list_requests("main-salon") == []

    completed = client.post(
        "/api/chat",
        json={
            "message": "Меня зовут Иван Петров, телефон +79990001122, завтра в 11:00, проблема шум тормозов, Nova Drive",
            "session_id": opened["session_id"],
        },
    )
    body = completed.json()
    assert completed.status_code == 200
    assert body["agent"] == "SERVICE_AGENT"
    assert body["skill"] == "service_booking"
    assert body["intake_state"] == "saved"
    assert "не подтверждена" in body["reply"].lower()
    rows = store.list_requests("main-salon")
    assert len(rows) == 1
    assert rows[0]["kind"] == "service"
    assert rows[0]["status"] == "saved"
    assert rows[0]["customer_name"] == "Иван Петров"
    assert rows[0]["vehicle"] == "Nova Drive"


def test_missing_required_field_does_not_save_request(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/chat",
        json={"message": "Хочу записаться на тест-драйв Nova Drive. Меня зовут Анна Смирнова"},
    )
    body = response.json()
    assert body["intake_state"] == "collecting"
    assert body["request_id"] is None
    assert "телефон" in body["reply"].lower()
    assert store.list_requests("main-salon") == []
    assert store.list_action_jobs("main-salon") == []


def test_repeat_submission_reuses_request_and_action(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    first = _finish_test_drive(client)
    second = client.post(
        "/api/chat",
        json={
            "message": "Телефон +79991234567, завтра в 15:00",
            "session_id": first["session_id"],
        },
    ).json()
    assert second["request_id"] == first["request_id"]
    assert second["action_id"] == first["action_id"]
    assert len(store.list_requests("main-salon")) == 1
    assert len(store.list_action_jobs("main-salon")) == 1


def test_saved_request_survives_orchestrator_restart(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _finish_test_drive(client)
    restarted = AIOrchestrator(store=store, llm=MockLLMClient())
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: restarted)
    follow = client.post(
        "/api/chat",
        json={"message": "Повторите заявку", "session_id": saved["session_id"]},
    ).json()
    assert follow["collected_fields"]["phone"] == "+79991234567"
    assert follow["collected_fields"]["customer_name"] == "Анна Смирнова"
    assert follow["request_id"] == saved["request_id"]
    assert follow["intake_state"] == "saved"
    loaded = store.load_session("main-salon", saved["session_id"])
    assert loaded["metadata"]["collected_fields"]["vehicle"] == "Nova Drive"
    assert len(store.list_requests("main-salon")) == 1


def test_unknown_order_does_not_reuse_known_status(monkeypatch, tmp_path) -> None:
    client, _store = _client(monkeypatch, tmp_path)
    body = client.post(
        "/api/chat", json={"message": "Статус заказа АН-2024-7777"}
    ).json()
    assert "не найден" in body["reply"].lower()
    assert "АН-2024-0512" not in body["reply"]
    assert "Предпродажная подготовка" not in body["reply"]
    known = client.post(
        "/api/chat", json={"message": "Статус заказа АН-2024-0512"}
    ).json()
    assert "АН-2024-0512" in known["reply"]
    assert "Предпродажная подготовка" in known["reply"]


def test_client_cannot_read_another_sessions_request(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _finish_test_drive(client)
    request_id = saved["request_id"]
    foreign = client.get(f"/api/requests/{request_id}", params={"session_id": str(uuid4())})
    assert foreign.status_code == 403
    owner = client.get(
        f"/api/requests/{request_id}", params={"session_id": saved["session_id"]}
    )
    assert owner.status_code == 200
    assert owner.json()["status"] == "saved"
    assert "phone" not in owner.json()
    missing = client.get(f"/api/requests/{uuid4()}", params={"session_id": saved["session_id"]})
    assert missing.status_code == 404
    assert "не найдена" in missing.json()["detail"].lower()
    denied = client.get(f"/api/requests/{request_id}", headers=_headers(client, "service"))
    assert denied.status_code == 403
    allowed = client.get(f"/api/requests/{request_id}", headers=_headers(client, "sales"))
    assert allowed.status_code == 200
    assert allowed.json()["phone"] == "+79991234567"
    store.create_request("other-salon", "test_drive", customer_name="Чужой", status="saved")
    hidden = store.get_request("main-salon", store.list_requests("other-salon")[0]["id"])
    assert hidden is None


def test_manager_confirmation_changes_status_and_failure_does_not(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    saved = _finish_test_drive(client)
    approved = client.post(
        f"/api/actions/{saved['action_id']}/review",
        json={"decision": "approve"},
        headers=_headers(client, "sales"),
    )
    assert approved.status_code == 200
    request = store.get_request("main-salon", saved["request_id"])
    assert request["status"] == "confirmed"
    assert len(store.list_requests("main-salon")) == 1
    status = client.get(
        f"/api/requests/{saved['request_id']}",
        params={"session_id": saved["session_id"]},
    ).json()
    assert status["status"] == "confirmed"

    failed_client, failed_store = _client(monkeypatch, tmp_path)
    failed = _finish_test_drive(failed_client)
    monkeypatch.setenv("ACTION_GATEWAY_MODE", "n8n")
    monkeypatch.setenv("ACTION_WEBHOOK_URL", "https://n8n.invalid/action")
    monkeypatch.setenv("ACTION_MAX_ATTEMPTS", "1")
    get_settings.cache_clear()

    def unavailable(*_args, **_kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr("autonova.action_gateway.httpx.post", unavailable)
    response = failed_client.post(
        f"/api/actions/{failed['action_id']}/review",
        json={"decision": "approve"},
        headers=_headers(failed_client, "sales"),
    )
    assert response.status_code == 200
    assert failed_store.get_action_job("main-salon", failed["action_id"])["status"] == "failed"
    assert failed_store.get_request("main-salon", failed["request_id"])["status"] == "saved"
    get_settings.cache_clear()


def test_missing_knowledge_does_not_invent_an_answer() -> None:
    result = customer_faq("Какой тариф доставки в Антарктиду?", [], {"kb": None, "history": []})
    assert result.escalated is True
    assert "базе знаний" in result.reply.lower()
    assert result.rag_ids == []
    assert "500" not in result.reply


def test_research_without_webhook_is_not_presented_as_done(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_WEBHOOK_URL", "")
    get_settings.cache_clear()
    created = client.post(
        "/api/research/jobs",
        json={"query": "Сравни Tesla и Audi", "idempotency_key": "research-not-connected"},
        headers=_headers(client, "employee"),
    )
    assert created.status_code == 202
    job_id = created.json()["job"]["id"]
    stored = store.get_research_job("main-salon", job_id)
    assert stored["status"] == "not_connected"
    assert not stored["result"]
    assert "Tesla" not in (stored.get("error") or "")
    get_settings.cache_clear()
