"""Persist booking intake, session secrets and an immutable request version.

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
        ALTER TABLE requests ADD COLUMN IF NOT EXISTS details_version INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE requests DROP CONSTRAINT IF EXISTS ck_requests_status;
        ALTER TABLE requests ADD CONSTRAINT ck_requests_status CHECK (
            status IN (
                'new', 'qualified', 'scheduled', 'assigned', 'done',
                'cancelled', 'saved', 'confirmed'
            )
        );
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS access_token_hash TEXT;
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_subject TEXT;
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_role TEXT;
        ALTER TABLE sessions ADD COLUMN IF NOT EXISTS visibility TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE sessions DROP COLUMN IF EXISTS visibility;
        ALTER TABLE sessions DROP COLUMN IF EXISTS owner_role;
        ALTER TABLE sessions DROP COLUMN IF EXISTS owner_subject;
        ALTER TABLE sessions DROP COLUMN IF EXISTS access_token_hash;
        ALTER TABLE sessions DROP COLUMN IF EXISTS metadata_json;
        ALTER TABLE requests DROP CONSTRAINT IF EXISTS ck_requests_status;
        ALTER TABLE requests ADD CONSTRAINT ck_requests_status CHECK (
            status IN ('new', 'qualified', 'scheduled', 'assigned', 'done', 'cancelled')
        );
        ALTER TABLE requests DROP COLUMN IF EXISTS details_version;
        ALTER TABLE requests DROP COLUMN IF EXISTS session_id;
        """
    )
