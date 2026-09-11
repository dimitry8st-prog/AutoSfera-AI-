from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from autonova.config import get_settings


class PlatformStore:
    """SQLite pilot store. Every business row is scoped by dealer_id."""

    backend_name = "sqlite"

    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    assigned_to TEXT,
                    source_ref TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_requests_dealer_status
                    ON requests(dealer_id, status);

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT NOT NULL,
                    dealer_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    active_agent TEXT,
                    history_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, dealer_id)
                );

                CREATE TABLE IF NOT EXISTS research_jobs (
                    id TEXT PRIMARY KEY,
                    dealer_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    query TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    sources_json TEXT,
                    error TEXT,
                    review_note TEXT,
                    published_version INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (dealer_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS ix_research_jobs_dealer_status
                    ON research_jobs(dealer_id, status);

                CREATE TABLE IF NOT EXISTS action_jobs (
                    id TEXT PRIMARY KEY,
                    dealer_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    session_id TEXT,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    idempotency_key TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    error TEXT,
                    review_note TEXT,
                    approved_by TEXT,
                    approved_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (dealer_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS ix_action_jobs_dealer_status
                    ON action_jobs(dealer_id, status);

                CREATE TABLE IF NOT EXISTS action_events (
                    id TEXT PRIMARY KEY,
                    dealer_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(action_id) REFERENCES action_jobs(id)
                );
                CREATE INDEX IF NOT EXISTS ix_action_events_action_created
                    ON action_events(action_id, created_at);
                """
            )
            self._ensure_column(db, "requests", "updated_at", "TEXT")
            self._ensure_column(db, "requests", "assigned_to", "TEXT")
            self._ensure_column(db, "requests", "source_ref", "TEXT")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_requests_source_ref "
                "ON requests(dealer_id, source_ref) WHERE source_ref IS NOT NULL"
            )

    def healthcheck(self) -> dict[str, Any]:
        try:
            with self.connect() as db:
                db.execute("SELECT 1").fetchone()
            return {"ok": True, "backend": self.backend_name}
        except sqlite3.Error as exc:
            return {"ok": False, "backend": self.backend_name, "error": type(exc).__name__}

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
        source_ref = data.get("source_ref")
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO requests
                (id, dealer_id, kind, customer_name, phone, vehicle, preferred_at,
                comment, status, source, created_at, updated_at, assigned_to, source_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)
                ON CONFLICT (dealer_id, source_ref) WHERE source_ref IS NOT NULL DO NOTHING""",
                (
                    request_id, dealer_id, kind, data.get("customer_name"),
                    data.get("phone"), data.get("vehicle"), data.get("preferred_at"),
                    data.get("comment"), data.get("source", "web"), created_at,
                    created_at, data.get("assigned_to"), source_ref,
                ),
            )
            if cursor.rowcount == 0 and source_ref:
                row = db.execute(
                    "SELECT * FROM requests WHERE dealer_id = ? AND source_ref = ?",
                    (dealer_id, source_ref),
                ).fetchone()
                if row:
                    return dict(row)
        return {"id": request_id, "dealer_id": dealer_id, "kind": kind, "status": "new", "created_at": created_at}

    def find_request_by_source_ref(self, dealer_id: str, source_ref: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM requests WHERE dealer_id = ? AND source_ref = ?",
                (dealer_id, source_ref),
            ).fetchone()
        return dict(row) if row else None

    def list_requests(self, dealer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM requests WHERE dealer_id = ? ORDER BY created_at DESC LIMIT ?",
                (dealer_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_request(
        self,
        dealer_id: str,
        request_id: str,
        *,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any] | None:
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [self._now()]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if assigned_to is not None:
            updates.append("assigned_to = ?")
            values.append(assigned_to)
        values.extend([request_id, dealer_id])
        with self.connect() as db:
            db.execute(
                f"UPDATE requests SET {', '.join(updates)} WHERE id = ? AND dealer_id = ?",
                values,
            )
            row = db.execute(
                "SELECT * FROM requests WHERE id = ? AND dealer_id = ?",
                (request_id, dealer_id),
            ).fetchone()
        return dict(row) if row else None

    def save_session(
        self,
        dealer_id: str,
        session_id: str,
        channel: str,
        active_agent: str | None,
        history: list[dict[str, str]],
    ) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO sessions
                (session_id, dealer_id, channel, active_agent, history_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, dealer_id) DO UPDATE SET
                    channel = excluded.channel,
                    active_agent = excluded.active_agent,
                    history_json = excluded.history_json,
                    updated_at = excluded.updated_at""",
                (session_id, dealer_id, channel, active_agent, json.dumps(history), self._now()),
            )

    def load_session(self, dealer_id: str, session_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE session_id = ? AND dealer_id = ?",
                (session_id, dealer_id),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["history"] = json.loads(data.pop("history_json"))
        return data

    def create_research_job(
        self,
        dealer_id: str,
        actor: str,
        query: str,
        idempotency_key: str,
        trace_id: str,
    ) -> tuple[dict[str, Any], bool]:
        now = self._now()
        job_id = str(uuid4())
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM research_jobs WHERE dealer_id = ? AND idempotency_key = ?",
                (dealer_id, idempotency_key),
            ).fetchone()
            if existing:
                return self._decode_research_row(existing), False
            db.execute(
                """INSERT INTO research_jobs
                (id, dealer_id, actor, query, idempotency_key, trace_id, status,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (job_id, dealer_id, actor, query, idempotency_key, trace_id, now, now),
            )
            row = db.execute("SELECT * FROM research_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._decode_research_row(row), True

    @staticmethod
    def _decode_research_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        result_json = data.pop("result_json", None)
        sources_json = data.pop("sources_json", None)
        data["result"] = json.loads(result_json) if result_json else None
        data["sources"] = json.loads(sources_json) if sources_json else []
        return data

    def get_research_job(self, dealer_id: str, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM research_jobs WHERE id = ? AND dealer_id = ?",
                (job_id, dealer_id),
            ).fetchone()
        return self._decode_research_row(row) if row else None

    def list_research_jobs(self, dealer_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM research_jobs WHERE dealer_id = ? ORDER BY created_at DESC LIMIT ?",
                (dealer_id, limit),
            ).fetchall()
        return [self._decode_research_row(row) for row in rows]

    def update_research_job(self, dealer_id: str, job_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {
            "status": "status",
            "result": "result_json",
            "sources": "sources_json",
            "error": "error",
            "review_note": "review_note",
            "published_version": "published_version",
        }
        updates = ["updated_at = ?"]
        values: list[Any] = [self._now()]
        for key, value in changes.items():
            column = allowed.get(key)
            if not column:
                continue
            if key in {"result", "sources"}:
                value = json.dumps(value, ensure_ascii=False)
            updates.append(f"{column} = ?")
            values.append(value)
        values.extend([job_id, dealer_id])
        with self.connect() as db:
            db.execute(
                f"UPDATE research_jobs SET {', '.join(updates)} WHERE id = ? AND dealer_id = ?",
                values,
            )
        return self.get_research_job(dealer_id, job_id)

    @staticmethod
    def _decode_action_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        result_json = data.pop("result_json", None)
        data["result"] = json.loads(result_json) if result_json else None
        return data

    def _add_action_event(
        self, db: sqlite3.Connection, dealer_id: str, action_id: str,
        event_type: str, actor: str, details: dict[str, Any] | None = None,
    ) -> None:
        db.execute(
            """INSERT INTO action_events
            (id, dealer_id, action_id, event_type, actor, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), dealer_id, action_id, event_type, actor,
             json.dumps(details or {}, ensure_ascii=False), self._now()),
        )

    def create_action_job(
        self, dealer_id: str, actor: str, session_id: str | None, kind: str,
        payload: dict[str, Any], idempotency_key: str, trace_id: str,
    ) -> tuple[dict[str, Any], bool]:
        if kind not in {"lead", "test_drive", "service"}:
            raise ValueError("unsupported action kind")
        now = self._now()
        action_id = str(uuid4())
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO action_jobs
                (id, dealer_id, actor, session_id, kind, status, payload_json,
                 idempotency_key, trace_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'waiting_approval', ?, ?, ?, ?, ?)
                ON CONFLICT (dealer_id, idempotency_key) DO NOTHING""",
                (action_id, dealer_id, actor, session_id, kind,
                 json.dumps(payload, ensure_ascii=False), idempotency_key, trace_id, now, now),
            )
            created = cursor.rowcount == 1
            if created:
                self._add_action_event(db, dealer_id, action_id, "proposed", actor, {"kind": kind})
                row = db.execute("SELECT * FROM action_jobs WHERE id = ?", (action_id,)).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM action_jobs WHERE dealer_id = ? AND idempotency_key = ?",
                    (dealer_id, idempotency_key),
                ).fetchone()
        return self._decode_action_row(row) or {}, created

    def get_action_job(self, dealer_id: str, action_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM action_jobs WHERE id = ? AND dealer_id = ?", (action_id, dealer_id)
            ).fetchone()
        return self._decode_action_row(row)

    def list_action_jobs(self, dealer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM action_jobs WHERE dealer_id = ? ORDER BY created_at DESC LIMIT ?",
                (dealer_id, limit),
            ).fetchall()
        return [self._decode_action_row(row) or {} for row in rows]

    def review_action_job(
        self, dealer_id: str, action_id: str, decision: str, actor: str,
        note: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        target = "approved" if decision == "approve" else "rejected"
        now = self._now()
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE action_jobs SET status = ?, review_note = ?, approved_by = ?,
                approved_at = ?, updated_at = ?
                WHERE id = ? AND dealer_id = ? AND status = 'waiting_approval'""",
                (target, note, actor if target == "approved" else None,
                 now if target == "approved" else None, now, action_id, dealer_id),
            )
            changed = cursor.rowcount == 1
            if changed:
                self._add_action_event(db, dealer_id, action_id, target, actor, {"note": note})
            row = db.execute(
                "SELECT * FROM action_jobs WHERE id = ? AND dealer_id = ?", (action_id, dealer_id)
            ).fetchone()
        return self._decode_action_row(row), changed

    def claim_action_job(self, dealer_id: str, action_id: str, actor: str = "gateway") -> dict[str, Any] | None:
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE action_jobs SET status = 'running', attempt_count = attempt_count + 1,
                error = NULL, updated_at = ?
                WHERE id = ? AND dealer_id = ? AND status = 'approved'""",
                (self._now(), action_id, dealer_id),
            )
            if cursor.rowcount != 1:
                return None
            self._add_action_event(db, dealer_id, action_id, "dispatch_started", actor)
            row = db.execute("SELECT * FROM action_jobs WHERE id = ?", (action_id,)).fetchone()
        return self._decode_action_row(row)

    def finish_action_job(
        self, dealer_id: str, action_id: str, status: str, actor: str,
        *, result: dict[str, Any] | None = None, error: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        if status not in {"completed", "failed", "delivery_unknown"}:
            raise ValueError("unsupported terminal action status")
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE action_jobs SET status = ?, result_json = ?, error = ?, updated_at = ?
                WHERE id = ? AND dealer_id = ?
                AND (status = 'running' OR (? IN ('completed', 'failed') AND status = 'delivery_unknown'))""",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, self._now(), action_id, dealer_id, status),
            )
            changed = cursor.rowcount == 1
            if changed:
                self._add_action_event(db, dealer_id, action_id, status, actor,
                                       {"result": result, "error": error})
            row = db.execute(
                "SELECT * FROM action_jobs WHERE id = ? AND dealer_id = ?", (action_id, dealer_id)
            ).fetchone()
        return self._decode_action_row(row), changed

    def retry_action_job(self, dealer_id: str, action_id: str, actor: str) -> tuple[dict[str, Any] | None, bool]:
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE action_jobs SET status = 'approved', error = NULL, updated_at = ?
                WHERE id = ? AND dealer_id = ? AND status = 'failed'""",
                (self._now(), action_id, dealer_id),
            )
            changed = cursor.rowcount == 1
            if changed:
                self._add_action_event(db, dealer_id, action_id, "retry_requested", actor)
            row = db.execute(
                "SELECT * FROM action_jobs WHERE id = ? AND dealer_id = ?", (action_id, dealer_id)
            ).fetchone()
        return self._decode_action_row(row), changed

    def list_action_events(self, dealer_id: str, action_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT * FROM action_events WHERE dealer_id = ? AND action_id = ?
                ORDER BY created_at, id""", (dealer_id, action_id),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            items.append(item)
        return items

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
            by_status = db.execute(
                "SELECT status, COUNT(*) AS total FROM requests WHERE dealer_id = ? GROUP BY status",
                (dealer_id,),
            ).fetchall()
        return {
            "dealer_id": dealer_id,
            "conversations": conversations,
            "escalations": escalations,
            "requests": requests,
            "requests_by_kind": {row["kind"]: row["total"] for row in by_kind},
            "requests_by_status": {row["status"]: row["total"] for row in by_status},
        }


def build_store() -> Any:
    """Build the configured store without importing PostgreSQL dependencies in SQLite mode."""
    settings = get_settings()
    if settings.storage_backend == "postgresql":
        from autonova.storage.postgres import PostgresPlatformStore

        return PostgresPlatformStore(
            settings.database_url,
            connect_timeout_seconds=settings.database_connect_timeout_seconds,
        )
    return PlatformStore(settings.database_path)
