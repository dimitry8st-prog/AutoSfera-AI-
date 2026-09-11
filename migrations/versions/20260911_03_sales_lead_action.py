"""Allow qualified sales leads in Action Gateway.

Revision ID: 20260911_03
Revises: 20260910_02
"""

from alembic import op


revision = "20260911_03"
down_revision = "20260910_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE action_jobs DROP CONSTRAINT ck_action_jobs_kind")
    op.execute(
        "ALTER TABLE action_jobs ADD CONSTRAINT ck_action_jobs_kind "
        "CHECK (kind IN ('lead', 'test_drive', 'service'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM action_events WHERE action_id IN (SELECT id FROM action_jobs WHERE kind = 'lead')")
    op.execute("DELETE FROM action_jobs WHERE kind = 'lead'")
    op.execute("ALTER TABLE action_jobs DROP CONSTRAINT ck_action_jobs_kind")
    op.execute(
        "ALTER TABLE action_jobs ADD CONSTRAINT ck_action_jobs_kind "
        "CHECK (kind IN ('test_drive', 'service'))"
    )
