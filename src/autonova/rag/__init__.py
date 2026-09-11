from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from autonova.config import get_settings
from autonova.embeddings import EmbeddingClient, get_embedding_client
from autonova.knowledge import SECTION_ACCESS, Document, KnowledgeBase, tokenize
from autonova.logging import get_logger

logger = get_logger("autonova.rag")


@dataclass(frozen=True)
class RetrievedChunk:
    document: Document
    score: float
    chunk_id: str | None = None


class RAGRetriever:
    """Simple TF-IDF style retriever over in-memory Knowledge Base.

    Emulates RAG for the educational MVP without an external vector DB.
    Answers must still be grounded only in retrieved documents.
    """

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self.kb = knowledge_base
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._doc_tokens: dict[str, list[str]] = {}
        self._df: Counter[str] = Counter()
        for doc in self.kb.documents:
            tokens = tokenize(doc.searchable_text)
            self._doc_tokens[doc.id] = tokens
            self._df.update(set(tokens))
        self._n_docs = max(len(self._doc_tokens), 1)
        logger.info("RAG index rebuilt: %s documents", self._n_docs)

    def reload(self) -> None:
        self.kb.reload()
        self._rebuild_index()

    def _tfidf(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        length = len(tokens) or 1
        weights: dict[str, float] = {}
        for term, count in tf.items():
            idf = math.log((1 + self._n_docs) / (1 + self._df.get(term, 0))) + 1.0
            weights[term] = (count / length) * idf
        return weights

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def retrieve(
        self,
        query: str,
        agent_key: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        settings = get_settings()
        top_k = top_k if top_k is not None else settings.rag_top_k
        min_score = min_score if min_score is not None else settings.rag_min_score

        query_vec = self._tfidf(tokenize(query))
        candidates = self.kb.for_agent(agent_key)
        # Prefer factual sections over scripts/policies when scores are close.
        section_boost = {
            "conversation": 1.2,
            "sales": 1.12,
            "service": 1.12,
            "customer_support": 1.12,
            "finance": 1.12,
            "faq": 1.08,
            "company": 1.05,
            "scripts": 0.85,
            "policies": 0.9,
            "glossary": 0.9,
        }
        scored: list[RetrievedChunk] = []
        for doc in candidates:
            doc_vec = self._tfidf(self._doc_tokens.get(doc.id, []))
            score = self._cosine(query_vec, doc_vec) * section_boost.get(doc.section, 1.0)
            if score >= min_score:
                scored.append(RetrievedChunk(document=doc, score=score))

        scored.sort(key=lambda c: c.score, reverse=True)
        results = scored[:top_k]
        logger.debug(
            "RAG retrieve agent=%s query=%r hits=%s",
            agent_key,
            query[:80],
            [c.document.id for c in results],
        )
        return results

    def format_context(self, chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return "Релевантные фрагменты базы знаний не найдены."
        blocks = []
        for chunk in chunks:
            d = chunk.document
            source_id = chunk.chunk_id or d.id
            blocks.append(
                f"<knowledge_chunk id=\"{source_id}\" document=\"{d.id}\" "
                f"section=\"{d.section}\" score=\"{chunk.score:.3f}\">\n"
                f"{d.title}\n{d.content}\n</knowledge_chunk>"
            )
        return "\n\n".join(blocks)


def chunk_document(document: Document, size: int, overlap: int) -> list[tuple[str, str]]:
    if size < 200 or overlap < 0 or overlap >= size:
        raise ValueError("invalid RAG chunk size or overlap")
    text = f"# {document.title}\n\n{document.content}".strip()
    if len(text) <= size:
        return [(f"{document.id}#000", text)]
    chunks: list[tuple[str, str]] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + size // 2:
                end = boundary + (2 if text[boundary:boundary + 2] == ". " else 0)
        content = text[start:end].strip()
        if content:
            chunks.append((f"{document.id}#{index:03d}", content))
            index += 1
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _vector_literal(vector: list[float], dimensions: int) -> str:
    if len(vector) != dimensions or any(not math.isfinite(value) for value in vector):
        raise ValueError("embedding has an invalid shape or non-finite value")
    return "[" + ",".join(f"{value:.10g}" for value in vector) + "]"


class PgVectorRAGRetriever:
    """Dealer-isolated cosine retrieval over PostgreSQL/pgvector with HNSW."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        dealer_id: str,
        embedder: EmbeddingClient | None = None,
        connection_factory: Callable[..., Any] = psycopg.connect,
    ) -> None:
        settings = get_settings()
        if not settings.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("pgvector RAG requires DATABASE_URL for PostgreSQL")
        self.kb = knowledge_base
        self.dealer_id = dealer_id
        self.embedder = embedder or get_embedding_client()
        self.dimensions = settings.embedding_dimensions
        if self.dimensions != 1536:
            raise ValueError("EMBEDDING_DIMENSIONS must be 1536 for the current migration")
        if self.embedder.dimensions != self.dimensions:
            raise ValueError("embedding dimensions do not match configuration")
        self.database_url = settings.database_url
        self.connect_timeout = settings.database_connect_timeout_seconds
        self.connection_factory = connection_factory

    def reload(self) -> None:
        self.kb.reload()

    def sync(self) -> int:
        settings = get_settings()
        rows: list[tuple[Document, str, str]] = []
        for document in self.kb.documents:
            for chunk_id, content in chunk_document(
                document, settings.rag_chunk_size, settings.rag_chunk_overlap
            ):
                rows.append((document, chunk_id, content))
        vectors: list[list[float]] = []
        texts = [content for _, _, content in rows]
        for start in range(0, len(texts), settings.embedding_batch_size):
            vectors.extend(self.embedder.embed(texts[start:start + settings.embedding_batch_size]))
        with self.connection_factory(
            self.database_url, connect_timeout=self.connect_timeout, row_factory=dict_row
        ) as db, db.cursor() as cur:
            cur.execute("DELETE FROM knowledge_chunks WHERE dealer_id = %s", (self.dealer_id,))
            for (document, chunk_id, content), vector in zip(rows, vectors, strict=True):
                cur.execute(
                    """INSERT INTO knowledge_chunks
                       (dealer_id, chunk_id, document_id, title, section, agent, content,
                        tags_json, metadata_json, embedding, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                               %s::vector, NOW())""",
                    (
                        self.dealer_id, chunk_id, document.id, document.title,
                        document.section, document.agent, content,
                        json.dumps(list(document.tags), ensure_ascii=False),
                        json.dumps(
                            {"source": "knowledge_base", **document.metadata}, ensure_ascii=False
                        ),
                        _vector_literal(vector, self.dimensions),
                    ),
                )
        logger.info("pgvector index synced dealer_id=%s chunks=%s", self.dealer_id, len(rows))
        return len(rows)

    def healthcheck(self) -> dict[str, Any]:
        try:
            with self.connection_factory(
                self.database_url, connect_timeout=self.connect_timeout, row_factory=dict_row
            ) as db, db.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') "
                    "AND to_regclass('public.knowledge_chunks') IS NOT NULL AS ready"
                )
                row = cur.fetchone()
            return {"ok": bool(row and row["ready"]), "backend": "pgvector"}
        except Exception as exc:
            logger.error("pgvector healthcheck failed error=%s", type(exc).__name__)
            return {"ok": False, "backend": "pgvector", "error": type(exc).__name__}

    def retrieve(
        self,
        query: str,
        agent_key: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        settings = get_settings()
        top_k = top_k if top_k is not None else settings.rag_top_k
        min_score = min_score if min_score is not None else settings.rag_vector_min_score
        sections = list(SECTION_ACCESS.get(agent_key, ()))
        if not sections:
            return []
        query_vector = _vector_literal(self.embedder.embed([query])[0], self.dimensions)
        with self.connection_factory(
            self.database_url, connect_timeout=self.connect_timeout, row_factory=dict_row
        ) as db, db.cursor() as cur:
            cur.execute(
                """SELECT chunk_id, document_id, title, section, agent, content, tags_json, metadata_json,
                          1 - (embedding <=> %s::vector) AS score
                   FROM knowledge_chunks
                   WHERE dealer_id = %s
                     AND section = ANY(%s)
                     AND (agent IS NULL OR agent = %s)
                     AND 1 - (embedding <=> %s::vector) >= %s
                   ORDER BY embedding <=> %s::vector
                   LIMIT %s""",
                (query_vector, self.dealer_id, sections, agent_key, query_vector,
                 min_score, query_vector, top_k),
            )
            rows = cur.fetchall()
        return [
            RetrievedChunk(
                document=Document(
                    id=row["document_id"], title=row["title"], section=row["section"],
                    content=row["content"], tags=tuple(row["tags_json"]), agent=row["agent"],
                    metadata=row["metadata_json"],
                ),
                score=float(row["score"]),
                chunk_id=row["chunk_id"],
            )
            for row in rows
        ]

    def format_context(self, chunks: list[RetrievedChunk]) -> str:
        return RAGRetriever.format_context(self, chunks)


def build_retriever(knowledge_base: KnowledgeBase, dealer_id: str):
    settings = get_settings()
    if settings.rag_backend == "tfidf":
        return RAGRetriever(knowledge_base)
    if settings.rag_backend == "pgvector":
        return PgVectorRAGRetriever(knowledge_base, dealer_id)
    raise ValueError("RAG_BACKEND must be 'tfidf' or 'pgvector'")
