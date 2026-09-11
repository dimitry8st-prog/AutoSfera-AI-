"""Add dealer-isolated pgvector knowledge index with HNSW.

Revision ID: 20260911_04
Revises: 20260911_03
"""

from alembic import op


revision = "20260911_04"
down_revision = "20260911_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE knowledge_chunks (
            dealer_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            title TEXT NOT NULL,
            section TEXT NOT NULL,
            agent TEXT,
            content TEXT NOT NULL,
            tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding vector(1536) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (dealer_id, chunk_id)
        );
        CREATE INDEX ix_knowledge_chunks_access
            ON knowledge_chunks(dealer_id, section, agent);
        CREATE INDEX ix_knowledge_chunks_embedding_hnsw
            ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_chunks")
