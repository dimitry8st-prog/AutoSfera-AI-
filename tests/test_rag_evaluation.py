from __future__ import annotations

from pathlib import Path

from autonova.evaluation import EvaluationCase, apply_gates, evaluate, load_cases, markdown_report
from autonova.knowledge import Document
from autonova.rag import RetrievedChunk


class FakeKnowledgeBase:
    documents = [
        Document(
            "sales-models", "Модели", "sales", "Nova Drive", (), "SALES_AGENT",
            {"version": "1", "owner": "Sales", "status": "approved"},
        )
    ]

    def get(self, document_id):
        return next((document for document in self.documents if document.id == document_id), None)


class FakeRetriever:
    kb = FakeKnowledgeBase()

    def retrieve(self, query, agent, top_k=None, min_score=None):
        if "погода" in query:
            return []
        return [RetrievedChunk(self.kb.documents[0], 0.9, "sales-models#000")]


def test_fixed_dataset_has_required_coverage() -> None:
    cases, gates = load_cases(Path("evals/rag_cases.json"))
    assert 24 <= len(cases) <= 30
    assert {"typical", "edge", "out_of_kb", "adversarial"} <= {case.category for case in cases}
    assert {"SALES_AGENT", "SERVICE_AGENT", "SUPPORT_AGENT", "EMPLOYEE_AGENT"} <= {
        case.agent for case in cases
    }
    assert gates["abstention_accuracy"] == 1.0
    assert gates["access_violation_count"] == 0


def test_evaluator_measures_retrieval_abstention_access_and_freshness() -> None:
    cases = [
        EvaluationCase(
            "known", "typical", "SALES_AGENT", "Какие модели?", ("sales-models",)
        ),
        EvaluationCase("unknown", "out_of_kb", "SALES_AGENT", "Какая погода?", should_abstain=True),
    ]
    report = evaluate(FakeRetriever(), cases)
    assert report["metrics"]["retrieval_hit_rate"] == 1.0
    assert report["metrics"]["abstention_accuracy"] == 1.0
    assert report["metrics"]["safe_refusal_accuracy"] == 1.0
    assert report["metrics"]["access_violation_count"] == 0
    assert report["metrics"]["freshness_metadata_coverage"] == 1.0

    gates = {
        "retrieval_hit_rate": 0.85, "abstention_accuracy": 1.0, "safe_refusal_accuracy": 1.0,
        "answer_term_coverage": 0.85, "access_violation_count": 0,
        "retrieval_latency_p95_ms": 2000, "freshness_metadata_coverage": 0.9,
    }
    decision = apply_gates(report, gates)
    assert decision["status"] == "GO"
    assert "Решение: **GO**" in markdown_report(report, gates)
