#!/usr/bin/env python3
"""Explicitly rebuild the current dealer's pgvector knowledge index."""

from autonova.config import get_settings
from autonova.knowledge import KnowledgeBase
from autonova.rag import PgVectorRAGRetriever


def main() -> None:
    settings = get_settings()
    if settings.rag_backend != "pgvector":
        raise SystemExit("Set RAG_BACKEND=pgvector before indexing")
    retriever = PgVectorRAGRetriever(KnowledgeBase(), settings.dealer_id)
    count = retriever.sync()
    print(f"Indexed {count} chunk(s) for dealer {settings.dealer_id}.")


if __name__ == "__main__":
    main()
