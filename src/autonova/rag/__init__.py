from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from autonova.config import get_settings
from autonova.knowledge import Document, KnowledgeBase, tokenize
from autonova.logging import get_logger

logger = get_logger("autonova.rag")


@dataclass(frozen=True)
class RetrievedChunk:
    document: Document
    score: float


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
            blocks.append(
                f"[{d.id} | {d.section} | score={chunk.score:.3f}] {d.title}\n{d.content}"
            )
        return "\n\n".join(blocks)
