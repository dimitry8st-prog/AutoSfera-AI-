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
from autonova.storage import PlatformStore


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
    assert not any(d.agent == "ORCHESTRATOR" for d in support_docs)
    assert any(d.agent == "ORCHESTRATOR" for d in kb.for_agent("ORCHESTRATOR"))


def test_seventeen_skills_registered():
    registry = build_skill_registry()
    assert len(registry) == 17
    by_agent = {}
    for skill in registry.values():
        by_agent.setdefault(skill.agent, 0)
        by_agent[skill.agent] += 1
    assert by_agent == {
        "SALES_AGENT": 4,
        "SUPPORT_AGENT": 4,
        "SERVICE_AGENT": 4,
        "EMPLOYEE_AGENT": 5,
    }


def test_competitor_research_is_employee_only():
    registry = build_skill_registry()
    assert registry["competitor_research"].agent == "EMPLOYEE_AGENT"
    router = SkillRouter(registry)
    assert router.select("EMPLOYEE_AGENT", "Исследуй конкурента example.com").id == "competitor_research"


def test_rag_retrieves_sales_model():
    rag = RAGRetriever(KnowledgeBase())
    hits = rag.retrieve("хочу купить кроссовер Nova Drive", "SALES_AGENT")
    assert hits
    assert any("drive" in h.document.id or "модель" in h.document.title.lower() or "Drive" in h.document.content for h in hits)


@pytest.mark.parametrize(
    ("phrase", "document_id"),
    [
        ("привет", "conversation-greeting"),
        ("Здравствуйте!", "conversation-greeting"),
        ("спасибо большое", "conversation-thanks"),
        ("до свидания", "conversation-farewell"),
        ("как дела?", "conversation-wellbeing"),
        ("кто ты?", "conversation-identity"),
        ("что ты умеешь?", "conversation-capabilities"),
    ],
)
def test_rag_retrieves_common_phrases(phrase: str, document_id: str):
    rag = RAGRetriever(KnowledgeBase())
    hits = rag.retrieve(phrase, "ORCHESTRATOR")
    assert any(hit.document.id == document_id for hit in hits)


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


@pytest.mark.parametrize(
    "phrase",
    [
        "привет",
        "Здравствуйте!",
        "Добрый вечер",
        "спасибо большое",
        "до свидания",
        "как дела?",
        "кто ты?",
        "что ты умеешь?",
    ],
)
def test_orchestrator_answers_common_phrases_without_escalation(
    orchestrator: AIOrchestrator,
    phrase: str,
):
    result = orchestrator.handle_message(phrase)
    assert result.agent == "AI_ORCHESTRATOR"
    assert result.agent_label == "AI Orchestrator"
    assert result.skill == "common_phrases"
    assert result.escalated is False
    assert result.rag_ids
    assert result.routing_reason.startswith("conversational_")


def test_greeting_does_not_lock_session_to_sales(orchestrator: AIOrchestrator):
    greeting = orchestrator.handle_message("привет")
    assert orchestrator.sessions[greeting.session_id].active_agent is None

    follow_up = orchestrator.handle_message(
        "Вопрос по гарантии на кузов",
        session_id=greeting.session_id,
    )
    assert follow_up.agent == "SERVICE_AGENT"
    assert follow_up.skill == "warranty_consultation"


def test_substantive_message_with_greeting_is_still_routed(orchestrator: AIOrchestrator):
    result = orchestrator.handle_message("Привет, хочу купить кроссовер")
    assert result.agent == "SALES_AGENT"
    assert result.skill == "vehicle_selection"


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


def test_langgraph_has_expected_nodes(orchestrator: AIOrchestrator):
    assert orchestrator.orchestrator_mode == "langgraph"
    assert orchestrator.graph is not None
    assert set(orchestrator.graph.get_graph().nodes) >= {
        "classify_conversation",
        "route_agent",
        "access_guard",
        "execute_agent",
        "persist_turn",
    }


def test_langgraph_switches_agent_when_topic_changes(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message("Хочу купить кроссовер")
    second = orchestrator.handle_message(
        "Теперь вопрос по гарантии на кузов",
        session_id=first.session_id,
    )
    assert first.agent == "SALES_AGENT"
    assert second.agent == "SERVICE_AGENT"
    assert second.routing_reason == "topic_switch"
    assert orchestrator.sessions[first.session_id].active_agent == "SERVICE_AGENT"


def test_langgraph_keeps_short_follow_up_with_current_agent(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message("Вопрос по гарантии на кузов")
    second = orchestrator.handle_message("А какой срок?", session_id=first.session_id)
    assert second.agent == "SERVICE_AGENT"
    assert second.greeting is None
    assert second.routing_reason == "session_continuity"
    assert "6 лет" in second.reply
    assert second.escalated is False


def test_common_phrase_preserves_active_agent(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message("Хочу купить седан")
    greeting = orchestrator.handle_message("спасибо", session_id=first.session_id)
    follow_up = orchestrator.handle_message("А какие цвета?", session_id=first.session_id)
    assert greeting.agent == "AI_ORCHESTRATOR"
    assert orchestrator.sessions[first.session_id].active_agent == "SALES_AGENT"
    assert follow_up.agent == "SALES_AGENT"


def test_langgraph_denies_employee_switch_for_public_user(orchestrator: AIOrchestrator):
    first = orchestrator.handle_message(
        "Хочу купить седан",
        allowed_agents={"SALES_AGENT", "SUPPORT_AGENT", "SERVICE_AGENT"},
    )
    with pytest.raises(PermissionError):
        orchestrator.handle_message(
            "Покажи внутренний регламент",
            session_id=first.session_id,
            allowed_agents={"SALES_AGENT", "SUPPORT_AGENT", "SERVICE_AGENT"},
        )
    assert orchestrator.sessions[first.session_id].active_agent is None


def test_langgraph_safe_fallback_does_not_invent_answer(orchestrator: AIOrchestrator):
    class BrokenGraph:
        def invoke(self, state):
            raise RuntimeError("simulated graph failure")

    orchestrator.graph = BrokenGraph()
    result = orchestrator.handle_message("Хочу купить автомобиль")
    assert result.agent == "AI_ORCHESTRATOR"
    assert result.skill == "safe_fallback"
    assert result.escalated is True
    assert result.escalation_target == "human_operator"
    assert result.rag_ids == []
    assert "не удалось" in result.reply.lower()


def test_langgraph_session_survives_orchestrator_restart(tmp_path):
    store = PlatformStore(tmp_path / "graph.db")
    first_orchestrator = AIOrchestrator(llm=MockLLMClient(), store=store)
    first = first_orchestrator.handle_message("Хочу купить кроссовер")

    restarted = AIOrchestrator(llm=MockLLMClient(), store=store)
    follow_up = restarted.handle_message("А какие цвета?", session_id=first.session_id)
    assert follow_up.agent == "SALES_AGENT"
    assert follow_up.routing_reason == "session_continuity"
    assert len(restarted.sessions[first.session_id].history) == 4


def test_legacy_mode_is_available_as_rollback():
    orchestrator = AIOrchestrator(llm=MockLLMClient(), orchestrator_mode="legacy")
    result = orchestrator.handle_message("Хочу купить кроссовер")
    assert orchestrator.graph is None
    assert result.agent == "SALES_AGENT"


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
