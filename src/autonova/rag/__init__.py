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
from autonova.knowledge import SECTION_ACCESS, Document, KnowledgeBase, stem_token, tokenize
from autonova.logging import get_logger

logger = get_logger("autonova.rag")


def _section_boost(query: str, section: str) -> float:
    q = query.lower().replace("ё", "е")
    base = {
        "conversation": 1.2,
        "sales": 1.18,
        "service": 1.18,
        "customer_support": 1.18,
        "finance": 1.18,
        "internal": 1.16,
        "legal": 1.12,
        "company": 1.06,
        "faq": 0.72,
        "scripts": 0.8,
        "policies": 0.88,
        "glossary": 0.85,
    }
    if any(token in q for token in ("скрипт", "разговора", "общаться", "общат", "аргумент")):
        if section == "scripts":
            return 1.38
        if section in {"sales", "service", "customer_support"}:
            return 0.92
    if any(token in q for token in ("политик", "безопасн", "игнорир", "персональн", "152")):
        if section in {"policies", "legal"}:
            return 1.36
    if any(token in q for token in ("контакт", "связать", "телефон", "адрес", "email")):
        if section == "company":
            return 1.32
    if any(token in q for token in ("руководител", "эскалац")):
        if section == "internal":
            return 1.28
    if any(token in q for token in ("кредит", "лизинг", "взнос", "ставк")):
        if section == "finance":
            return 1.3
        if section == "faq":
            return 0.6
    if any(token in q for token in ("гарант", "коррози", "кузов")):
        if section == "service":
            return 1.3
        if section == "faq":
            return 0.62
    if any(token in q for token in ("тест-драйв", "тест драйв", "пробная поездка")):
        if section == "sales":
            return 1.34
    if any(token in q for token in ("лизинг",)):
        if section == "finance":
            return 1.34
        if section == "company":
            return 0.7
    if any(token in q for token in ("обслуживан", "техобслуж", "плановое")):
        if section == "service":
            return 1.32
    if "сервис" in q and any(token in q for token in ("запис", "недел")):
        if section == "service":
            return 1.32
    if any(token in q for token in ("модел", "продаж")) and "скрипт" not in q:
        if section == "sales":
            return 1.28
        if section == "company":
            return 0.78
    if any(token in q for token in ("юридическ", "юрлиц", "b2b", "корпоративн")):
        if section in {"sales", "finance"}:
            return 1.26
    return base.get(section, 1.0)


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

        base_query_tokens = tokenize(query, expand=False)
        query_tokens = tokenize(query, expand=True)
        query_vec = self._tfidf(query_tokens)
        query_terms = list(dict.fromkeys(
            stem_token(token) for token in base_query_tokens if len(stem_token(token)) > 2
        ))
        weak_terms = {"компан", "autosfera", "авто"}
        candidates = self.kb.for_agent(agent_key)
        scored: list[RetrievedChunk] = []
        for doc in candidates:
            doc_tokens = self._doc_tokens.get(doc.id, [])
            doc_set = set(doc_tokens)
            overlap = sum(1 for term in query_terms if term in doc_set and term not in weak_terms)
            if query_terms and overlap == 0:
                continue
            doc_vec = self._tfidf(doc_tokens)
            score = self._cosine(query_vec, doc_vec) * _section_boost(query, doc.section)
            title_terms = set(tokenize(f"{doc.title} {' '.join(doc.tags)}", expand=True))
            title_hits = len(title_terms.intersection(set(query_terms)))
            if title_hits:
                score += 0.12 * min(title_hits, 3)
            if score >= min_score:
                scored.append(RetrievedChunk(document=doc, score=score))

        scored.sort(key=lambda c: c.score, reverse=True)
        if scored and scored[0].score >= 0.2:
            floor = max(min_score, scored[0].score * 0.28)
            scored = [chunk for chunk in scored if chunk.score >= floor]
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
