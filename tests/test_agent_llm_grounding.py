from __future__ import annotations

import json
from typing import Any

import httpx

from autosfera.agents import SalesAgent
from autosfera.knowledge import KnowledgeBase
from autosfera.llm import LLMClient, OpenAILLMClient
from autosfera.orchestrator import AIOrchestrator
from autosfera.rag import RAGRetriever
from autosfera.skills import SkillRouter, build_skill_registry


class GroundedRecordingLLM(LLMClient):
    def __init__(self, *, invalid_source: bool = False, answer: str = "Подтверждённый ответ модели.") -> None:
        self.invalid_source = invalid_source
        self.answer = answer
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        self.calls.append((system, messages))
        if "Контракт ответа" not in system:
            return json.dumps(
                {"agent": "SALES_AGENT", "reason": "test_route"},
                ensure_ascii=False,
            )
        payload = json.loads(messages[-1]["content"])
        source_id = (
            "invented-source"
            if self.invalid_source
            else payload["approved_context"][0]["id"]
        )
        control = payload["required_control"]
        return json.dumps(
            {
                "answer": self.answer,
                "source_ids": [source_id],
                "escalate": control["escalate"],
                "escalation_target": control["escalation_target"],
                "next_step": "Уточните предпочтения по комплектации.",
            },
            ensure_ascii=False,
        )


def _sales_agent() -> SalesAgent:
    return SalesAgent(
        RAGRetriever(KnowledgeBase()),
        SkillRouter(build_skill_registry()),
    )


def test_agent_prompt_is_used_only_with_grounded_context() -> None:
    llm = GroundedRecordingLLM()
    reply = _sales_agent().handle("Нужен кроссовер до 4 млн", llm=llm)

    assert reply.text.startswith("Подтверждённый ответ модели.")
    assert reply.rag_ids
    assert len(llm.calls) == 1
    system, messages = llm.calls[0]
    assert "Sales Agent" in system
    payload = json.loads(messages[-1]["content"])
    assert payload["approved_context"]
    assert set(reply.rag_ids).issubset(
        {item["id"] for item in payload["approved_context"]}
    )


def test_unknown_llm_source_is_rejected_in_favour_of_safe_draft() -> None:
    baseline = _sales_agent().handle("Нужен кроссовер до 4 млн")
    llm = GroundedRecordingLLM(invalid_source=True)
    checked = _sales_agent().handle("Нужен кроссовер до 4 млн", llm=llm)

    assert checked.text == baseline.text
    assert "Подтверждённый ответ модели" not in checked.text


def test_agent_does_not_call_llm_without_rag_context() -> None:
    llm = GroundedRecordingLLM()
    reply = _sales_agent().handle("квантовые водоросли на спутнике", llm=llm)

    assert llm.calls == []
    assert reply.escalated is True
    assert reply.rag_ids == []
    assert "нет данных" in reply.text.lower()


def test_complex_request_uses_complex_llm_for_route_and_answer() -> None:
    simple = GroundedRecordingLLM(answer="Ответ простой модели.")
    complex_llm = GroundedRecordingLLM(answer="Ответ сложной модели.")
    orchestrator = AIOrchestrator(llm=simple)
    orchestrator.simple_llm = simple
    orchestrator.complex_llm = complex_llm

    result = orchestrator.handle_message(
        "Нужен автомобиль, документы для сделки и консультация по гарантии"
    )

    assert result.model_tier == "complex"
    assert "Ответ сложной модели" in result.reply
    assert simple.calls == []
    assert len(complex_llm.calls) == 2


def test_first_business_answer_has_one_platform_greeting() -> None:
    llm = GroundedRecordingLLM()
    orchestrator = AIOrchestrator(llm=llm)
    result = orchestrator.handle_message("Нужен кроссовер до 4 млн")

    assert result.reply.count("Подключаю Sales Agent") == 1
    assert "Здравствуйте! Я Sales Agent" not in result.reply


def test_openai_client_sends_system_prompt_and_selected_model(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = OpenAILLMClient(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model="complex-model",
    )
    result = client.complete("SYSTEM PROMPT", [{"role": "user", "content": "test"}])

    assert result == '{"ok":true}'
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["json"]["model"] == "complex-model"
    assert captured["json"]["messages"][0] == {
        "role": "system",
        "content": "SYSTEM PROMPT",
    }
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
