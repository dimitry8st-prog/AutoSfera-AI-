from __future__ import annotations

from pathlib import Path

import pytest

from autonova.config import get_settings
from autonova.embeddings import DeterministicEmbeddingClient
from autonova.knowledge import Document, KnowledgeBase
from autonova.rag import PgVectorRAGRetriever, _vector_literal, chunk_document


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return self._cursor


def test_chunk_document_produces_stable_traceable_ids() -> None:
    document = Document("policy", "Политика", "internal", "Абзац. " * 120, (), "EMPLOYEE_AGENT")
    chunks = chunk_document(document, size=240, overlap=40)
    assert len(chunks) > 1
    assert chunks[0][0] == "policy#000"
    assert chunks[-1][0] == f"policy#{len(chunks) - 1:03d}"
    assert all(content for _, content in chunks)


def test_vector_literal_rejects_wrong_shape_and_non_finite_values() -> None:
    assert _vector_literal([0.1, -0.2], 2) == "[0.1,-0.2]"
    with pytest.raises(ValueError):
        _vector_literal([0.1], 2)
    with pytest.raises(ValueError):
        _vector_literal([float("nan"), 0.0], 2)


def test_pgvector_retrieval_applies_dealer_role_and_section_filters(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    monkeypatch.setenv("RAG_VECTOR_MIN_SCORE", "0.42")
    get_settings.cache_clear()
    root = tmp_path / "kb"
    root.mkdir()
    (root / "empty.json").write_text('{"section":"company","documents":[]}', encoding="utf-8")
    cursor = FakeCursor([{
        "chunk_id": "sales-models#000", "document_id": "sales-models",
        "title": "Модели", "section": "sales", "agent": "SALES_AGENT",
        "content": "Nova Drive", "tags_json": ["catalog"],
        "metadata_json": {"version": "2026-09"}, "score": 0.91,
    }])
    retriever = PgVectorRAGRetriever(
        KnowledgeBase(root), "dealer-42", DeterministicEmbeddingClient(1536),
        connection_factory=lambda *_args, **_kwargs: FakeConnection(cursor),
    )

    hits = retriever.retrieve("кроссовер", "SALES_AGENT")

    assert hits[0].chunk_id == "sales-models#000"
    assert hits[0].document.metadata["version"] == "2026-09"
    query, params = cursor.calls[0]
    assert "dealer_id = %s" in query and "section = ANY(%s)" in query
    assert params[1] == "dealer-42"
    assert "internal" not in params[2]
    assert params[3] == "SALES_AGENT"
    assert params[5] == 0.42
    get_settings.cache_clear()


def test_pgvector_sync_replaces_only_current_dealer_index(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    get_settings.cache_clear()
    root = tmp_path / "kb"
    root.mkdir()
    (root / "sales.json").write_text(
        '''{"section":"sales","documents":[{"id":"catalog","title":"Каталог",'''
        '''"content":"Nova Drive — кроссовер.","tags":["catalog"],'''
        '''"agent":"SALES_AGENT","metadata":{"version":"2026-09","status":"approved"}}]}''',
        encoding="utf-8",
    )
    cursor = FakeCursor()
    retriever = PgVectorRAGRetriever(
        KnowledgeBase(root), "dealer-42", DeterministicEmbeddingClient(1536),
        connection_factory=lambda *_args, **_kwargs: FakeConnection(cursor),
    )

    assert retriever.sync() == 1

    assert cursor.calls[0][0].startswith("DELETE FROM knowledge_chunks")
    assert cursor.calls[0][1] == ("dealer-42",)
    insert_query, insert_params = cursor.calls[1]
    assert "INSERT INTO knowledge_chunks" in insert_query
    assert insert_params[0] == "dealer-42"
    assert '"version": "2026-09"' in insert_params[8]
    get_settings.cache_clear()


def test_pgvector_migration_defines_hnsw_cosine_index() -> None:
    migration = Path("migrations/versions/20260911_04_pgvector_rag.py").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "USING hnsw (embedding vector_cosine_ops)" in migration
    assert "PRIMARY KEY (dealer_id, chunk_id)" in migration


def test_pgvector_healthcheck_reports_schema_readiness(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    get_settings.cache_clear()
    root = tmp_path / "kb"
    root.mkdir()
    (root / "empty.json").write_text('{"section":"company","documents":[]}', encoding="utf-8")
    cursor = FakeCursor([{"ready": True}])
    retriever = PgVectorRAGRetriever(
        KnowledgeBase(root), "dealer-42", DeterministicEmbeddingClient(1536),
        connection_factory=lambda *_args, **_kwargs: FakeConnection(cursor),
    )
    assert retriever.healthcheck() == {"ok": True, "backend": "pgvector"}
    get_settings.cache_clear()
