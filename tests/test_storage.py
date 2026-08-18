from autonova.storage import PlatformStore


def test_store_isolates_dealers_and_builds_analytics(tmp_path):
    store = PlatformStore(tmp_path / "autosfera.db")
    store.record_conversation(
        dealer_id="salon-1", session_id="s1", channel="web", agent="SALES_AGENT",
        skill="vehicle_selection", user_message="Нужен автомобиль",
        assistant_reply="Уточните параметры", escalated=False,
    )
    store.create_request("salon-1", "lead", phone="+79990000000")
    store.create_request("salon-2", "service", phone="+79991111111")

    assert len(store.list_requests("salon-1")) == 1
    assert len(store.list_requests("salon-2")) == 1
    summary = store.analytics("salon-1")
    assert summary["conversations"] == 1
    assert summary["requests"] == 1
    assert summary["requests_by_kind"] == {"lead": 1}


def test_session_survives_new_store_instance(tmp_path):
    path = tmp_path / "sessions.db"
    PlatformStore(path).save_session(
        "salon-1", "s1", "web", "SALES_AGENT", [{"role": "user", "content": "Кроссовер"}]
    )
    restored = PlatformStore(path).load_session("salon-1", "s1")
    assert restored["active_agent"] == "SALES_AGENT"
    assert restored["history"][0]["content"] == "Кроссовер"


def test_request_status_and_assignee_update(tmp_path):
    store = PlatformStore(tmp_path / "requests.db")
    created = store.create_request("salon-1", "lead", customer_name="Иван")
    updated = store.update_request(
        "salon-1", created["id"], status="assigned", assigned_to="Мария"
    )
    assert updated["status"] == "assigned"
    assert updated["assigned_to"] == "Мария"


def test_research_idempotency(tmp_path):
    store = PlatformStore(tmp_path / "research.db")
    first, created = store.create_research_job("salon-1", "employee", "Конкурент A", "same-key-123", "trace-1")
    second, duplicate_created = store.create_research_job("salon-1", "employee", "Другая формулировка", "same-key-123", "trace-2")
    assert created is True
    assert duplicate_created is False
    assert second["id"] == first["id"]
