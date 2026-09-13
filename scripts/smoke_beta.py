#!/usr/bin/env python3
"""In-process smoke test for the controlled beta contract."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="autosfera-beta-") as tmp:
        os.environ["DATABASE_PATH"] = str(Path(tmp) / "autosfera.db")
        os.environ["LOGS_DIR"] = str(Path(tmp) / "logs")
        os.environ["DIALOGUES_DIR"] = str(Path(tmp) / "dialogues")

        from fastapi.testclient import TestClient
        from autonova.api.main import create_app, get_orchestrator, get_store
        from autonova.config import get_settings

        get_settings.cache_clear()
        get_store.cache_clear()
        get_orchestrator.cache_clear()

        with TestClient(create_app()) as client:
            health = client.get("/health")
            health.raise_for_status()
            assert health.json()["version"] == "3.1.0-beta.1"
            runtime = health.json()["runtime"]
            assert runtime["build_sha"]
            assert runtime["prompts"]["fingerprint"] not in {"missing", "empty"}
            assert runtime["knowledge_base"]["fingerprint"] not in {"missing", "empty"}

            chat = client.post("/api/chat", json={"message": "Хочу подобрать кроссовер"})
            chat.raise_for_status()
            session_id = chat.json()["session_id"]

            feedback = client.post(
                "/api/feedback", json={"session_id": session_id, "rating": 5}
            )
            feedback.raise_for_status()
            assert feedback.json()["created"] is True

            login = client.post(
                "/api/auth/token",
                json={"username": "admin", "password": "admin-demo"},
            )
            login.raise_for_status()
            auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

            summary = client.get("/api/feedback/summary", headers=auth)
            summary.raise_for_status()
            assert summary.json()["csat"] == 5.0

            readiness = client.get("/api/beta/readiness", headers=auth)
            readiness.raise_for_status()
            assert readiness.json()["status"] == "ready_for_controlled_beta"

    print("Controlled beta smoke: PASS")


if __name__ == "__main__":
    main()
