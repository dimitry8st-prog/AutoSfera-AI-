from __future__ import annotations

from fastapi.testclient import TestClient

from autonova.api.main import create_app
from autonova.llm import MockLLMClient
from autonova.orchestrator import AIOrchestrator
from autonova.storage import PlatformStore


def test_health_and_chat_flow(monkeypatch, tmp_path):
    app = create_app()
    # Ensure deterministic orchestrator
    import autonova.api.main as api_main

    api_main.get_orchestrator.cache_clear()
    orch = AIOrchestrator(llm=MockLLMClient())
    monkeypatch.setattr(api_main, "get_orchestrator", lambda: orch)
    store = PlatformStore(tmp_path / "pilot.db")
    monkeypatch.setattr(api_main, "get_store", lambda: store)

    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["skills"] == 16
    assert body["agents"] == ["SALES_AGENT", "SUPPORT_AGENT", "SERVICE_AGENT", "EMPLOYEE_AGENT"]
    assert body["dealer_id"] == "main-salon"

    skills = client.get("/api/skills").json()
    assert len(skills["skills"]) == 16

    chat = client.post("/api/chat", json={"message": "Хочу купить кроссовер"})
    assert chat.status_code == 200
    data = chat.json()
    assert data["agent"] == "SALES_AGENT"
    assert data["session_id"]
    assert data["reply"]

    reset = client.post("/api/reset", json={"session_id": data["session_id"]})
    assert reset.status_code == 200
    assert reset.json()["active_agent"] is None

    tg = client.post(
        "/api/channels/telegram",
        json={"text": "Статус заказа АН-2024-0388", "chat_id": "tg-1"},
    )
    assert tg.status_code == 200
    assert tg.json()["agent"] == "SUPPORT_AGENT"
    assert tg.json()["channel"] == "telegram"

    employee = client.post("/api/chat", json={"message": "Найди внутренний регламент обработки лида"})
    assert employee.status_code == 200
    assert employee.json()["agent"] == "EMPLOYEE_AGENT"

    created = client.post(
        "/api/requests",
        json={"kind": "test_drive", "customer_name": "Иван", "phone": "+79990000000", "vehicle": "Nova Drive"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "new"
    assert len(client.get("/api/requests").json()["items"]) == 1

    analytics = client.get("/api/analytics/summary").json()
    assert analytics["conversations"] == 2
    assert analytics["requests"] == 1
