#!/usr/bin/env python3
"""Deterministic acceptance checks for the model router and human handoff."""

from autonova.llm import MockLLMClient
from autonova.model_router import ModelRouter
from autonova.orchestrator import AIOrchestrator


def main() -> int:
    router = ModelRouter()
    assert router.decide("Расскажите про условия покупки").route == "simple_model"
    assert router.decide("Нужны кредит и гарантия на автомобиль").route == "complex_model"

    orchestrator = AIOrchestrator(llm=MockLLMClient())
    warranty = orchestrator.handle_message("Вопрос по гарантии на кузов")
    purchase = orchestrator.handle_message(
        "Теперь расскажи про условия покупки", session_id=warranty.session_id
    )
    assert purchase.agent == "SALES_AGENT"
    assert purchase.routing_reason == "topic_switch"
    assert purchase.model_route == "simple_model"
    assert purchase.rag_ids == ["sales-purchase-conditions"]

    ambiguous = orchestrator.handle_message("Какие условия?")
    assert ambiguous.routing_reason == "clarify"
    assert ambiguous.model_route == "clarify"
    assert not ambiguous.escalated

    financial = orchestrator.handle_message("Подтверди скидку и окончательную цену")
    assert financial.model_route == "human"
    assert financial.routing_risk == "high"
    assert financial.escalation_target == "sales_manager"

    service = orchestrator.handle_message("Вопрос по гарантии")
    human = orchestrator.handle_message("Соедини с человеком", session_id=service.session_id)
    assert human.model_route == "human"
    assert human.escalation_target == "service_manager"

    missing_order = orchestrator.handle_message("Статус заказа АН-2024-9999")
    assert missing_order.escalated
    assert missing_order.model_route == "human"
    assert missing_order.routing_risk == "high"

    print("Stage-two router verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
