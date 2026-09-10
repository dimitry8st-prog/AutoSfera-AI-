"""Add durable Action Gateway outbox and audit log."""

from alembic import op


revision = "20260910_02"
down_revision = "20260907_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE action_jobs (
            id TEXT PRIMARY KEY,
            dealer_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            session_id TEXT,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            result_json JSONB,
            idempotency_key TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            error TEXT,
            review_note TEXT,
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ux_action_jobs_idempotency UNIQUE (dealer_id, idempotency_key),
            CONSTRAINT ck_action_jobs_kind CHECK (kind IN ('test_drive', 'service')),
            CONSTRAINT ck_action_jobs_status CHECK (
                status IN ('waiting_approval', 'approved', 'running', 'completed', 'rejected', 'failed', 'delivery_unknown')
            )
        );
        CREATE INDEX ix_action_jobs_dealer_status ON action_jobs(dealer_id, status);

        CREATE TABLE action_events (
            id TEXT PRIMARY KEY,
            dealer_id TEXT NOT NULL,
            action_id TEXT NOT NULL REFERENCES action_jobs(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX ix_action_events_action_created ON action_events(action_id, created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS action_events; DROP TABLE IF EXISTS action_jobs;")
