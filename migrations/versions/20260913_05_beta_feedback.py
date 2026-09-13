"""Add dealer-scoped CSAT feedback for the controlled beta.

Revision ID: 20260913_05
Revises: 20260911_04
"""

from alembic import op


revision = "20260913_05"
down_revision = "20260911_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feedback (
            id TEXT PRIMARY KEY,
            dealer_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ux_feedback_session UNIQUE (dealer_id, session_id)
        );
        CREATE INDEX ix_feedback_dealer_created
            ON feedback(dealer_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback")
