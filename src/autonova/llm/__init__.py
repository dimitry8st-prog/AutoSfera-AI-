from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from autonova.config import get_settings
from autonova.logging import get_logger

logger = get_logger("autonova.llm")


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Deterministic offline LLM used for tests and local demo without API keys."""

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        user = messages[-1]["content"] if messages else ""
        lowered = user.lower()
        logger.debug("MockLLM complete system_len=%s user=%r", len(system), user[:120])

        if "orchestrator" in system.lower() or "определи намерение" in system.lower():
            service_keys = (
                "гарант",
                "сервис",
                "ремонт",
                "масло",
                "диагност",
                "техобслуж",
                "обслуживан",
                "лкп",
            )
            support_keys = ("заказ", "ан-2024", "документ", "статус", "возврат", "инн")
            employee_keys = (
                "сотрудник", "внутренн", "регламент", "скрипт продаж",
                "эскалац", "руководител", "отчёт", "отчет", "kpi",
            )
            sales_keys = (
                "купить",
                "кроссовер",
                "седан",
                "кредит",
                "лизинг",
                "trade",
                "тест-драйв",
                "nova",
                "b2b",
                "юридическ",
            )

            def _hit(keys: tuple[str, ...]) -> bool:
                return any(k in lowered for k in keys)

            # Prefer explicit sales finance intents over accidental service matches.
            if _hit(employee_keys):
                agent = "EMPLOYEE_AGENT"
                greeting = "Подключаю внутреннего ассистента AutoSfera AI."
            elif _hit(sales_keys):
                agent = "SALES_AGENT"
                greeting = "Передаю вас Sales Agent AutoSfera AI."
            elif _hit(support_keys):
                agent = "SUPPORT_AGENT"
                greeting = "Передаю вас Customer Support Agent AutoSfera AI."
            elif _hit(service_keys) or re.search(r"(?<![а-яa-z])то(?![а-яa-z])", lowered):
                agent = "SERVICE_AGENT"
                greeting = "Передаю вас Service Agent AutoSfera AI."
            else:
                agent = "SALES_AGENT"
                greeting = "Передаю вас Sales Agent AutoSfera AI."
            return json.dumps({"agent": agent, "greeting": greeting}, ensure_ascii=False)

        # Agent path: return grounded hint — actual reply is produced by skills.
        return "OK"


class OpenAILLMClient(LLMClient):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.model = model or settings.openai_model
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY / openai_api_key is required for openai mode")

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"
        logger.info("Calling LLM model=%s", self.model)
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()


def get_llm_client() -> LLMClient:
    settings = get_settings()
    mode = settings.llm_mode.lower().strip()
    if mode == "openai":
        logger.info("Using OpenAI LLM client")
        return OpenAILLMClient()
    logger.info("Using Mock LLM client")
    return MockLLMClient()


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))
