"""Store booking intake owner and session fields.

Revision ID: 20261117_06
Revises: 20260913_05
"""

from alembic import op


revision = "20261117_06"
down_revision = "20260913_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE requests ADD COLUMN IF NOT EXISTS session_id TEXT;
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE requests DROP CONSTRAINT IF EXISTS ck_requests_status;
        ALTER TABLE requests ADD CONSTRAINT ck_requests_status CHECK (
            status IN (
                'new', 'qualified', 'scheduled', 'assigned', 'done',
                'cancelled', 'saved', 'confirmed'
            )
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE requests DROP CONSTRAINT IF EXISTS ck_requests_status;
        ALTER TABLE requests ADD CONSTRAINT ck_requests_status CHECK (
            status IN ('new', 'qualified', 'scheduled', 'assigned', 'done', 'cancelled')
        );
        ALTER TABLE sessions DROP COLUMN IF EXISTS metadata_json;
        ALTER TABLE requests DROP COLUMN IF EXISTS session_id;
        """
    )
