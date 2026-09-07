from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresPlatformStore:
    """PostgreSQL demo CRM/store with the same contract as the SQLite fallback."""

    backend_name = "postgresql"

    def __init__(self, database_url: str, *, connect_timeout_seconds: int = 5) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("PostgreSQL DATABASE_URL is required")
        self.database_url = database_url
        self.connect_timeout_seconds = connect_timeout_seconds

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        with psycopg.connect(
            self.database_url,
            connect_timeout=self.connect_timeout_seconds,
            row_factory=dict_row,
        ) as connection:
            yield connection

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in ("created_at", "updated_at", "preferred_at"):
            if isinstance(data.get(key), datetime):
                data[key] = data[key].isoformat()
        return data

    def healthcheck(self) -> dict[str, Any]:
        try:
            with self.connect() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return {"ok": True, "backend": self.backend_name}
        except psycopg.Error as exc:
            return {"ok": False, "backend": self.backend_name, "error": type(exc).__name__}

    def record_conversation(self, **data: Any) -> str:
        row_id = str(uuid4())
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                """INSERT INTO conversations
                (id, dealer_id, session_id, channel, agent, skill, user_message,
                 assistant_reply, escalated, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    row_id, data["dealer_id"], data["session_id"], data["channel"],
                    data["agent"], data.get("skill"), data["user_message"],
                    data["assistant_reply"], bool(data.get("escalated", False)), self._now(),
                ),
            )
        return row_id

    def create_request(self, dealer_id: str, kind: str, **data: Any) -> dict[str, Any]:
        request_id = str(uuid4())
        now = self._now()
        source_ref = data.get("source_ref")
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                """INSERT INTO requests
                (id, dealer_id, kind, customer_name, phone, vehicle, preferred_at,
                 comment, status, source, created_at, updated_at, assigned_to, source_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', %s, %s, %s, %s, %s)
                ON CONFLICT (dealer_id, source_ref) WHERE source_ref IS NOT NULL
                DO NOTHING
                RETURNING *""",
                (
                    request_id, dealer_id, kind, data.get("customer_name"), data.get("phone"),
                    data.get("vehicle"), data.get("preferred_at"), data.get("comment"),
                    data.get("source", "web"), now, now, data.get("assigned_to"), source_ref,
                ),
            )
            row = cur.fetchone()
            if row is None and source_ref:
                cur.execute(
                    "SELECT * FROM requests WHERE dealer_id = %s AND source_ref = %s",
                    (dealer_id, source_ref),
                )
                row = cur.fetchone()
        return self._row(row) or {
            "id": request_id, "dealer_id": dealer_id, "kind": kind,
            "status": "new", "created_at": now.isoformat(),
        }

    def find_request_by_source_ref(self, dealer_id: str, source_ref: str) -> dict[str, Any] | None:
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM requests WHERE dealer_id = %s AND source_ref = %s",
                (dealer_id, source_ref),
            )
            return self._row(cur.fetchone())

    def list_requests(self, dealer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM requests WHERE dealer_id = %s ORDER BY created_at DESC LIMIT %s",
                (dealer_id, limit),
            )
            return [self._row(row) or {} for row in cur.fetchall()]

    def update_request(
        self,
        dealer_id: str,
        request_id: str,
        *,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> dict[str, Any] | None:
        updates = ["updated_at = %s"]
        values: list[Any] = [self._now()]
        if status is not None:
            updates.append("status = %s")
            values.append(status)
        if assigned_to is not None:
            updates.append("assigned_to = %s")
            values.append(assigned_to)
        values.extend([request_id, dealer_id])
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                f"UPDATE requests SET {', '.join(updates)} WHERE id = %s AND dealer_id = %s RETURNING *",
                values,
            )
            return self._row(cur.fetchone())

    def save_session(
        self,
        dealer_id: str,
        session_id: str,
        channel: str,
        active_agent: str | None,
        history: list[dict[str, str]],
    ) -> None:
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                """INSERT INTO sessions
                (session_id, dealer_id, channel, active_agent, history_json, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(session_id, dealer_id) DO UPDATE SET
                    channel = excluded.channel,
                    active_agent = excluded.active_agent,
                    history_json = excluded.history_json,
                    updated_at = excluded.updated_at""",
                (session_id, dealer_id, channel, active_agent, Jsonb(history), self._now()),
            )

    def load_session(self, dealer_id: str, session_id: str) -> dict[str, Any] | None:
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM sessions WHERE session_id = %s AND dealer_id = %s",
                (session_id, dealer_id),
            )
            data = self._row(cur.fetchone())
        if data is not None:
            data["history"] = data.pop("history_json", [])
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
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                """INSERT INTO research_jobs
                (id, dealer_id, actor, query, idempotency_key, trace_id, status,
                 created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, %s)
                ON CONFLICT (dealer_id, idempotency_key) DO NOTHING
                RETURNING *""",
                (job_id, dealer_id, actor, query, idempotency_key, trace_id, now, now),
            )
            row = cur.fetchone()
            created = row is not None
            if row is None:
                cur.execute(
                    "SELECT * FROM research_jobs WHERE dealer_id = %s AND idempotency_key = %s",
                    (dealer_id, idempotency_key),
                )
                row = cur.fetchone()
        return self._decode_research_row(row), created

    def _decode_research_row(self, row: dict[str, Any] | None) -> dict[str, Any]:
        data = self._row(row) or {}
        data["result"] = data.pop("result_json", None)
        data["sources"] = data.pop("sources_json", None) or []
        return data

    def get_research_job(self, dealer_id: str, job_id: str) -> dict[str, Any] | None:
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM research_jobs WHERE id = %s AND dealer_id = %s",
                (job_id, dealer_id),
            )
            row = cur.fetchone()
        return self._decode_research_row(row) if row else None

    def list_research_jobs(self, dealer_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM research_jobs WHERE dealer_id = %s ORDER BY created_at DESC LIMIT %s",
                (dealer_id, limit),
            )
            return [self._decode_research_row(row) for row in cur.fetchall()]

    def update_research_job(self, dealer_id: str, job_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {
            "status": "status", "result": "result_json", "sources": "sources_json",
            "error": "error", "review_note": "review_note", "published_version": "published_version",
        }
        updates = ["updated_at = %s"]
        values: list[Any] = [self._now()]
        for key, value in changes.items():
            column = allowed.get(key)
            if column is None:
                continue
            if key in {"result", "sources"}:
                value = Jsonb(value)
            updates.append(f"{column} = %s")
            values.append(value)
        values.extend([job_id, dealer_id])
        with self.connect() as db, db.cursor() as cur:
            cur.execute(
                f"UPDATE research_jobs SET {', '.join(updates)} WHERE id = %s AND dealer_id = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
        return self._decode_research_row(row) if row else None

    def analytics(self, dealer_id: str) -> dict[str, Any]:
        with self.connect() as db, db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM conversations WHERE dealer_id = %s", (dealer_id,))
            conversations = cur.fetchone()["total"]
            cur.execute(
                "SELECT COUNT(*) AS total FROM conversations WHERE dealer_id = %s AND escalated = TRUE",
                (dealer_id,),
            )
            escalations = cur.fetchone()["total"]
            cur.execute("SELECT COUNT(*) AS total FROM requests WHERE dealer_id = %s", (dealer_id,))
            requests = cur.fetchone()["total"]
            cur.execute("SELECT kind, COUNT(*) AS total FROM requests WHERE dealer_id = %s GROUP BY kind", (dealer_id,))
            by_kind = cur.fetchall()
            cur.execute("SELECT status, COUNT(*) AS total FROM requests WHERE dealer_id = %s GROUP BY status", (dealer_id,))
            by_status = cur.fetchall()
        return {
            "dealer_id": dealer_id,
            "conversations": conversations,
            "escalations": escalations,
            "requests": requests,
            "requests_by_kind": {row["kind"]: row["total"] for row in by_kind},
            "requests_by_status": {row["status"]: row["total"] for row in by_status},
        }
