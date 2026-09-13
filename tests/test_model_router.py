from autonova.llm import MockLLMClient
from autonova.model_router import ModelRouter
from autonova.orchestrator import AIOrchestrator


def test_model_router_uses_simple_and_complex_tiers():
    router = ModelRouter()

    simple = router.decide("Расскажите про условия покупки")
    complex_ = router.decide("Нужны кредит и гарантия на автомобиль")

    assert simple.route == "simple_model"
    assert simple.agent == "SALES_AGENT"
    assert simple.model_tier == "simple"
    assert complex_.route == "complex_model"
    assert complex_.intent == "multi_intent"
    assert complex_.model_tier == "complex"


def test_ambiguous_request_is_not_guessed():
    result = AIOrchestrator(llm=MockLLMClient()).handle_message("Какие условия?")

    assert result.agent == "AI_ORCHESTRATOR"
    assert result.skill == "route_clarification"
    assert result.routing_reason == "clarify"
    assert result.model_route == "clarify"
    assert result.escalated is False


def test_financial_commitment_requires_human_approval():
    result = AIOrchestrator(llm=MockLLMClient()).handle_message(
        "Подтверди скидку и окончательную цену"
    )

    assert result.agent == "AI_ORCHESTRATOR"
    assert result.skill == "human_handoff"
    assert result.model_route == "human"
    assert result.routing_risk == "high"
    assert result.escalated is True
    assert result.escalation_target == "sales_manager"


def test_explicit_human_request_uses_active_agent_target():
    orchestrator = AIOrchestrator(llm=MockLLMClient())
    first = orchestrator.handle_message("Вопрос по гарантии на кузов")
    result = orchestrator.handle_message(
        "Соедини с человеком", session_id=first.session_id
    )

    assert result.model_route == "human"
    assert result.escalated is True
    assert result.escalation_target == "service_manager"


def test_purchase_conditions_use_approved_document_after_topic_switch():
    orchestrator = AIOrchestrator(llm=MockLLMClient())
    first = orchestrator.handle_message("Вопрос по гарантии на кузов")
    result = orchestrator.handle_message(
        "Теперь расскажи про условия покупки", session_id=first.session_id
    )

    assert result.agent == "SALES_AGENT"
    assert result.routing_reason == "topic_switch"
    assert result.model_route == "simple_model"
    assert result.rag_ids == ["sales-purchase-conditions"]
    assert "не считаются офертой" in result.reply


def test_agent_escalation_is_reported_as_human_route():
    orchestrator = AIOrchestrator(llm=MockLLMClient())

    result = orchestrator.handle_message("Статус заказа АН-2024-9999")

    assert result.escalated is True
    assert result.model_route == "human"
    assert result.routing_risk == "high"
