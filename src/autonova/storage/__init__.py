from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from autonova.config import get_settings


class PlatformStore:
    """SQLite pilot store. Every business row is scoped by dealer_id."""

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    dealer_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    skill TEXT,
                    user_message TEXT NOT NULL,
                    assistant_reply TEXT NOT NULL,
                    escalated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_conversations_dealer_created
                    ON conversations(dealer_id, created_at);

                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    dealer_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    customer_name TEXT,
                    phone TEXT,
                    vehicle TEXT,
                    preferred_at TEXT,
                    comment TEXT,
                    status TEXT NOT NULL DEFAULT 'new',
                    source TEXT NOT NULL DEFAULT 'web',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_requests_dealer_status
                    ON requests(dealer_id, status);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def record_conversation(self, **data: Any) -> str:
        row_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                """INSERT INTO conversations
                (id, dealer_id, session_id, channel, agent, skill, user_message,
                 assistant_reply, escalated, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_id, data["dealer_id"], data["session_id"], data["channel"],
                    data["agent"], data.get("skill"), data["user_message"],
                    data["assistant_reply"], int(data.get("escalated", False)), self._now(),
                ),
            )
        return row_id

    def create_request(self, dealer_id: str, kind: str, **data: Any) -> dict[str, Any]:
        request_id = str(uuid4())
        created_at = self._now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO requests
                (id, dealer_id, kind, customer_name, phone, vehicle, preferred_at,
                 comment, status, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
                (
                    request_id, dealer_id, kind, data.get("customer_name"),
                    data.get("phone"), data.get("vehicle"), data.get("preferred_at"),
                    data.get("comment"), data.get("source", "web"), created_at,
                ),
            )
        return {"id": request_id, "dealer_id": dealer_id, "kind": kind, "status": "new", "created_at": created_at}

    def list_requests(self, dealer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM requests WHERE dealer_id = ? ORDER BY created_at DESC LIMIT ?",
                (dealer_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def analytics(self, dealer_id: str) -> dict[str, Any]:
        with self.connect() as db:
            conversations = db.execute(
                "SELECT COUNT(*) FROM conversations WHERE dealer_id = ?", (dealer_id,)
            ).fetchone()[0]
            escalations = db.execute(
                "SELECT COUNT(*) FROM conversations WHERE dealer_id = ? AND escalated = 1", (dealer_id,)
            ).fetchone()[0]
            requests = db.execute(
                "SELECT COUNT(*) FROM requests WHERE dealer_id = ?", (dealer_id,)
            ).fetchone()[0]
            by_kind = db.execute(
                "SELECT kind, COUNT(*) AS total FROM requests WHERE dealer_id = ? GROUP BY kind",
                (dealer_id,),
            ).fetchall()
        return {
            "dealer_id": dealer_id,
            "conversations": conversations,
            "escalations": escalations,
            "requests": requests,
            "requests_by_kind": {row["kind"]: row["total"] for row in by_kind},
        }
