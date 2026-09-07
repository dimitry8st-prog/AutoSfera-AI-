from __future__ import annotations

import os
from uuid import uuid4

import pytest

from autonova.storage.postgres import PostgresPlatformStore


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


def test_postgres_store_contract_and_dealer_isolation() -> None:
    assert DATABASE_URL is not None
    store = PostgresPlatformStore(DATABASE_URL)
    dealer_id = f"integration-{uuid4()}"
    other_dealer_id = f"integration-{uuid4()}"

    try:
        assert store.healthcheck() == {"ok": True, "backend": "postgresql"}

        first = store.create_request(
            dealer_id,
            "test_drive",
            customer_name="Integration Test",
            vehicle="Nova Drive",
            source_ref="ci-lead-1",
        )
        duplicate = store.create_request(
            dealer_id,
            "test_drive",
            customer_name="Duplicate",
            source_ref="ci-lead-1",
        )
        assert duplicate["id"] == first["id"]
        assert len(store.list_requests(dealer_id)) == 1
        assert store.list_requests(other_dealer_id) == []

        history = [{"role": "user", "content": "Нужен тест-драйв"}]
        store.save_session(dealer_id, "ci-session", "web", "Sales Agent", history)
        session = store.load_session(dealer_id, "ci-session")
        assert session is not None
        assert session["active_agent"] == "Sales Agent"
        assert session["history"] == history
        assert store.load_session(other_dealer_id, "ci-session") is None

        analytics = store.analytics(dealer_id)
        assert analytics["requests"] == 1
        assert analytics["requests_by_kind"] == {"test_drive": 1}
    finally:
        with store.connect() as db, db.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE dealer_id IN (%s, %s)", (dealer_id, other_dealer_id))
            cur.execute("DELETE FROM requests WHERE dealer_id IN (%s, %s)", (dealer_id, other_dealer_id))
