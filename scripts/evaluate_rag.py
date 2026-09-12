#!/usr/bin/env python3
"""Run the fixed AutoSfera RAG evaluation dataset and write JSON/Markdown reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonova.config import get_settings
from autonova.evaluation import apply_gates, evaluate, load_cases, markdown_report
from autonova.knowledge import KnowledgeBase
from autonova.rag import build_retriever


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evals/rag_cases.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/rag-eval"))
    parser.add_argument("--enforce", action="store_true", help="return non-zero when a gate fails")
    args = parser.parse_args()
    settings = get_settings()
    cases, gates = load_cases(args.dataset)
    retriever = build_retriever(KnowledgeBase(), settings.dealer_id)
    report = evaluate(retriever, cases)
    report["configuration"] = {
        "backend": settings.rag_backend,
        "top_k": settings.rag_top_k,
        "tfidf_min_score": settings.rag_min_score,
        "vector_min_score": settings.rag_vector_min_score,
        "embedding_model": settings.embedding_model if settings.rag_backend == "pgvector" else None,
    }
    report["gates"] = gates
    report["decision"] = apply_gates(report, gates)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "report.md").write_text(markdown_report(report, gates), encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "decision": report["decision"]}, ensure_ascii=False))
    return 1 if args.enforce and report["decision"]["status"] != "GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
