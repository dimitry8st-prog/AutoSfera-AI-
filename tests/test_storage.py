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
