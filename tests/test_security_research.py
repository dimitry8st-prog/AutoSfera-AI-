from __future__ import annotations

import json

import pytest

from autonova.auth import create_token, decode_token, sign_webhook, verify_webhook
from autonova.knowledge import KnowledgeBase
from autonova.storage import PlatformStore


def test_signed_token_round_trip():
    token = create_token("employee", "employee", "main-salon")
    actor = decode_token(token)
    assert actor.subject == "employee"
    assert actor.role == "employee"


def test_tampered_token_is_rejected():
    token = create_token("admin", "admin", "main-salon")
    with pytest.raises(ValueError):
        decode_token(token[:-2] + "xx")


def test_unknown_token_role_is_rejected():
    with pytest.raises(ValueError):
        create_token("root", "owner", "main-salon")


def test_webhook_signature_round_trip():
    payload = b'{"job_id":"1"}'
    signature = sign_webhook(payload)
    assert verify_webhook(payload, signature)


def test_webhook_signature_detects_changed_payload():
    assert not verify_webhook(b"changed", sign_webhook(b"original"))


def test_research_callback_state_is_review(tmp_path):
    store = PlatformStore(tmp_path / "jobs.db")
    job, _ = store.create_research_job("main-salon", "employee", "Конкурент A", "unique-key-1", "trace")
    updated = store.update_research_job(
        "main-salon",
        job["id"],
        status="review",
        result={"title": "A", "summary": "Проверенный черновик"},
        sources=[{"title": "Official", "url": "https://example.com"}],
    )
    assert updated["status"] == "review"
    assert updated["sources"][0]["url"] == "https://example.com"


def test_approved_research_is_versioned(tmp_path):
    kb_root = tmp_path / "kb"
    base = kb_root / "company"
    base.mkdir(parents=True)
    (base / "base.json").write_text(
        json.dumps({"section": "company", "documents": [{"id": "base", "title": "Base", "content": "Base", "tags": []}]}),
        encoding="utf-8",
    )
    kb = KnowledgeBase(kb_root)
    first, v1 = kb.publish_approved(job_id="job-1", title="A", content="Result", sources=[{"url": "https://example.com"}])
    second, v2 = kb.publish_approved(job_id="job-1", title="A2", content="Updated", sources=[{"url": "https://example.com/2"}])
    assert v1 == 1 and v2 == 2
    assert first.id != second.id


def test_research_jobs_are_isolated_by_dealer(tmp_path):
    store = PlatformStore(tmp_path / "isolated.db")
    store.create_research_job("salon-1", "employee", "A", "unique-111", "trace-1")
    store.create_research_job("salon-2", "employee", "B", "unique-222", "trace-2")
    assert len(store.list_research_jobs("salon-1")) == 1
    assert store.list_research_jobs("salon-1")[0]["query"] == "A"
