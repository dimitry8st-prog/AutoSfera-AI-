from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from autosfera.action_gateway import confirm_saved_request
from autosfera.storage import PlatformStore
from autosfera.storage.postgres import PostgresPlatformStore


@pytest.fixture(params=["sqlite", "postgresql"])
def booking_store(request, tmp_path):
    dealer = f"booking-safety-{uuid4()}"
    if request.param == "postgresql":
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("TEST_DATABASE_URL is not configured")
        store = PostgresPlatformStore(url)
    else:
        store = PlatformStore(tmp_path / "booking.db")
    try:
        yield store, dealer
    finally:
        if request.param == "postgresql":
            with store.connect() as db, db.cursor() as cur:
                cur.execute("DELETE FROM requests WHERE dealer_id = %s", (dealer,))


def _request(store, dealer):
    return store.create_request(
        dealer, "test_drive", status="saved", customer_name="Test Customer",
        phone="+70000000000", vehicle="Nova Drive", preferred_at="2026-11-18T15:00+03:00",
    )


def test_confirmation_requires_the_approved_version_and_dealer(booking_store):
    store, dealer = booking_store
    request = _request(store, dealer)
    edited = store.update_request_details(dealer, request["id"], phone="+70000000001")
    assert edited["details_version"] == 2
    assert store.confirm_request_version(dealer, request["id"], 1, request["preferred_at"]) is None
    assert store.confirm_request_version("another-dealer", request["id"], 2, request["preferred_at"]) is None
    assert store.confirm_request_version(dealer, request["id"], 2, "2026-11-19T16:00+03:00") is None
    assert store.get_request(dealer, request["id"])["status"] == "saved"
    assert store.confirm_request_version(dealer, request["id"], 2, request["preferred_at"])["status"] == "confirmed"


def test_edit_winning_the_race_blocks_the_late_confirmation(booking_store, monkeypatch):
    store, dealer = booking_store
    request = _request(store, dealer)
    job = {"id": "approved-action", "dealer_id": dealer, "payload": {
        "request_id": request["id"], "request_version": 1, "preferred_at": request["preferred_at"],
    }}
    entered, release = threading.Event(), threading.Event()
    original = store.confirm_request_version

    def paused_confirmation(*args):
        entered.set()
        assert release.wait(5), "confirmation was not released"
        return original(*args)

    monkeypatch.setattr(store, "confirm_request_version", paused_confirmation)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(confirm_saved_request, store, job)
        try:
            assert entered.wait(5), "confirmation did not reach the conditional write"
            store.update_request_details(dealer, request["id"], preferred_at="2026-11-19T16:00+03:00")
        finally:
            release.set()
        result = future.result(timeout=5)
    assert result["status"] == "saved"
    assert result["details_version"] == 2
    assert result["preferred_at"] == "2026-11-19T16:00+03:00"


def test_confirmation_winning_the_race_prevents_later_overwrite(booking_store):
    store, dealer = booking_store
    request = _request(store, dealer)
    assert store.confirm_request_version(dealer, request["id"], 1, request["preferred_at"])
    edited = store.update_request_details(dealer, request["id"], preferred_at="2026-11-19T16:00+03:00")
    assert edited["status"] == "confirmed"
    assert edited["details_version"] == 1
    assert edited["preferred_at"] == request["preferred_at"]


def test_parallel_partial_edits_do_not_lose_fields_or_reuse_a_version(booking_store, monkeypatch):
    store, dealer = booking_store
    request = _request(store, dealer)
    barrier = threading.Barrier(2)
    local = threading.local()
    original = store.get_request

    def synchronized_read(*args):
        value = original(*args)
        if not getattr(local, "read", False):
            local.read = True
            barrier.wait(timeout=5)
        return value

    monkeypatch.setattr(store, "get_request", synchronized_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.update_request_details, dealer, request["id"], phone="+70000000001")
        second = pool.submit(store.update_request_details, dealer, request["id"], vehicle="Nova Cargo")
        first.result(timeout=10)
        second.result(timeout=10)
    stored = original(dealer, request["id"])
    assert stored["details_version"] == 3
    assert stored["phone"] == "+70000000001"
    assert stored["vehicle"] == "Nova Cargo"
    # Replaying unchanged fields does not invalidate the current approval.
    monkeypatch.setattr(store, "get_request", original)
    repeated = store.update_request_details(dealer, request["id"], phone=stored["phone"])
    assert repeated["details_version"] == 3


def test_only_one_concurrent_confirmation_can_win(booking_store):
    store, dealer = booking_store
    request = _request(store, dealer)
    barrier = threading.Barrier(2)

    def confirm():
        barrier.wait(timeout=5)
        return store.confirm_request_version(dealer, request["id"], 1, request["preferred_at"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert sum(item is not None for item in results) == 1
