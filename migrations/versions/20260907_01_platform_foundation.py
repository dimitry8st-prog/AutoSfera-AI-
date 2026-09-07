"""Create PostgreSQL platform and demo CRM tables."""

from alembic import op


revision = "20260907_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            dealer_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            agent TEXT NOT NULL,
            skill TEXT,
            user_message TEXT NOT NULL,
            assistant_reply TEXT NOT NULL,
            escalated BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX ix_conversations_dealer_created
            ON conversations(dealer_id, created_at DESC);

        CREATE TABLE requests (
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
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ,
            assigned_to TEXT,
            source_ref TEXT,
            CONSTRAINT ck_requests_status CHECK (
                status IN ('new', 'qualified', 'scheduled', 'assigned', 'done', 'cancelled')
            )
        );
        CREATE INDEX ix_requests_dealer_status ON requests(dealer_id, status);
        CREATE UNIQUE INDEX ux_requests_source_ref
            ON requests(dealer_id, source_ref) WHERE source_ref IS NOT NULL;

        CREATE TABLE sessions (
            session_id TEXT NOT NULL,
            dealer_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            active_agent TEXT,
            history_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (session_id, dealer_id)
        );

        CREATE TABLE research_jobs (
            id TEXT PRIMARY KEY,
            dealer_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            query TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json JSONB,
            sources_json JSONB,
            error TEXT,
            review_note TEXT,
            published_version INTEGER,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ux_research_jobs_idempotency UNIQUE (dealer_id, idempotency_key)
        );
        CREATE INDEX ix_research_jobs_dealer_status ON research_jobs(dealer_id, status);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS research_jobs;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS requests;
        DROP TABLE IF EXISTS conversations;
        """
    )
