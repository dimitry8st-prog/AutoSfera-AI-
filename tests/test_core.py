from __future__ import annotations

import json
from pathlib import Path

import pytest

from autonova.knowledge import KnowledgeBase, SECTION_ACCESS
from autonova.llm import MockLLMClient, extract_json_object
from autonova.logging import DialogueLogger, setup_logging
from autonova.orchestrator import AIOrchestrator
from autonova.rag import RAGRetriever
from autonova.skills import SkillRouter, build_skill_registry


@pytest.fixture()
def orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AIOrchestrator:
    setup_logging("INFO")
    monkeypatch.setenv("AUTONOVA_LLM_MODE", "mock")
    logs = tmp_path / "logs"
    dialogues = tmp_path / "dialogues"
    logs.mkdir()
    dialogues.mkdir()
    monkeypatch.setenv("LOGS_DIR", str(logs))
    # Settings uses field names; override via object after init is simpler:
    orch = AIOrchestrator(llm=MockLLMClient())
    orch_sessions_dir = tmp_path / "dlg"
    orch_sessions_dir.mkdir(exist_ok=True)
    return orch


def test_knowledge_base_loads_all_sections():
    kb = KnowledgeBase()
    sections = {d.section for d in kb.documents}
    expected = {
        "company",
        "sales",
        "customer_support",
        "service",
        "finance",
        "legal",
        "faq",
        "scripts",
        "policies",
        "glossary",
    }
    assert expected.issubset(sections)
    assert len(kb.documents) >= 15


def test_agent_section_access_least_privilege():
    kb = KnowledgeBase()
    sales_docs = kb.for_agent("SALES_AGENT")
    assert all(d.section in SECTION_ACCESS["SALES_AGENT"] for d in sales_docs)
    assert not any(d.section == "service" for d in sales_docs)
    support_docs = kb.for_agent("SUPPORT_AGENT")
    assert not any(d.section == "sales" for d in support_docs)


def test_sixteen_skills_registered():
    registry = build_skill_registry()
    assert len(registry) == 16
    by_agent = {}
    for skill in registry.values():
        by_agent.setdefault(skill.agent, 0)
        by_agent[skill.agent] += 1
    assert by_agent == {
        "SALES_AGENT": 4,
        "SUPPORT_AGENT": 4,
        "SERVICE_AGENT": 4,
        "EMPLOYEE_AGENT": 4,
    }


def test_rag_retrieves_sales_model():
    rag = RAGRetriever(KnowledgeBase())
    hits = rag.retrieve("хочу купить кроссовер Nova Drive", "SALES_AGENT")
    assert hits
    assert any("drive" in h.document.id or "модель" in h.document.title.lower() or "Drive" in h.document.content for h in hits)


def test_rag_support_cannot_see_finance_prices_only_own_sections():
    rag = RAGRetriever(KnowledgeBase())
    hits = rag.retrieve("лизинг ставка", "SUPPORT_AGENT", min_score=0.01)
    assert all(h.document.section in SECTION_ACCESS["SUPPORT_AGENT"] for h in hits)


def test_orchestrator_routes_sales(orchestrator: AIOrchestrator):
    result = orchestrator.handle_message("Хочу купить кроссовер")
    assert result.agent == "SALES_AGENT"
    assert result.skill in {"vehicle_selection", "credit_leasing", "test_drive_booking", "trade_in"}
    assert "2 400 000" in result.reply or "Nova Drive" in result.reply
    assert result.greeting


def test_orchestrator_routes_support_order(orchestrator: AIOrchestrator):
    result = orchestrator.handle_message("Статус заказа АН-2024-0512")
    assert result.agent == "SUPPORT_AGENT"
    assert result.skill == "order_status"
    assert "АН-2024-0512" in result.reply
    assert "предпродажн" in result.reply.lower() or "Подготовк" in result.reply or "подготовк" in result.reply.lower()


def test_orchestrator_routes_service_warranty(orchestrator: AIOrchestrator):
    result = orchestrator.handle_message("Вопрос по гарантии на кузов")
    assert result.agent == "SERVICE_AGENT"
    assert result.skill == "warranty_consultation"
    assert "6 лет" in result.reply
    assert "не подтвержда" in result.reply.lower()


def test_session_keeps_agent(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message("Хочу купить седан")
    second = orchestrator.handle_message("Какие условия кредита?", session_id=first.session_id)
    assert first.agent == "SALES_AGENT"
    assert second.agent == "SALES_AGENT"
    assert second.greeting is None
    assert "20%" in second.reply or "9,9" in second.reply


def test_reset_session(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message("Хочу купить кроссовер")
    orchestrator.reset_session(first.session_id)
    again = orchestrator.handle_message(
        "Вопрос по гарантии на кузов",
        session_id=first.session_id,
    )
    assert again.agent == "SERVICE_AGENT"


def test_warranty_confirmation_escalates(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message("Вопрос по гарантии")
    second = orchestrator.handle_message(
        "Подтверди гарантию это гарантийный случай",
        session_id=first.session_id,
    )
    assert second.escalated is True
    assert second.escalation_target in {"service_engineer", "service_advisor"}


def test_unknown_order_escalates(orchestrator: AIOrchestrator):
    result = orchestrator.handle_message("Статус заказа АН-2024-9999")
    assert result.agent == "SUPPORT_AGENT"
    assert result.escalated is True


def test_dialogue_logger_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from autonova.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DIALOGUES_DIR", str(tmp_path))
    # DialogueLogger reads settings.dialogues_dir at init — patch via settings object
    settings = get_settings()
    settings.dialogues_dir = tmp_path
    dlg = DialogueLogger("test-session")
    dlg.log_user_message("hello", "web")
    dlg.log_routing("SALES_AGENT", "test", "hi")
    lines = dlg.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "user_message"
    get_settings.cache_clear()


def test_extract_json_object_from_noise():
    raw = 'Конечно:\n{"agent":"SERVICE_AGENT","greeting":"ok"}\n'
    data = extract_json_object(raw)
    assert data["agent"] == "SERVICE_AGENT"


def test_skill_router_selects_trade_in():
    router = SkillRouter()
    skill = router.select("SALES_AGENT", "Хочу сдать авто в trade-in")
    assert skill.id == "trade_in"


def test_leasing_b2b_scenario(orchestrator: AIOrchestrator):
    result = orchestrator.handle_message("Лизинг для юридических лиц на 5 авто")
    assert result.agent == "SALES_AGENT"
    assert "8,5" in result.reply or "лизинг" in result.reply.lower()


def test_prompts_exist():
    from autonova.config import get_settings

    prompts = get_settings().prompts_dir
    for name in ("orchestrator.txt", "sales_agent.txt", "support_agent.txt", "service_agent.txt"):
        assert (prompts / name).exists()
