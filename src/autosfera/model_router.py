from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal


RouteKind = Literal["skill", "simple_model", "complex_model", "clarify", "human"]
RiskLevel = Literal["low", "medium", "high"]


_DOMAIN_KEYS: dict[str, tuple[str, ...]] = {
    "SALES_AGENT": (
        "купить", "покупк", "приобрет", "условия покупки", "вариант оплат",
        "кроссовер", "седан", "кредит", "лизинг", "trade", "трейд",
        "тест-драйв", "nova", "b2b", "модел", "каталог", "машин",
        "автомобил",
    ),
    "SUPPORT_AGENT": (
        "заказ", "ан-2024", "документ", "статус", "возврат", "инн",
        "сделк", "договор", "оформ", "какие документы", "документы нужны",
    ),
    "SERVICE_AGENT": (
        "гарант", "сервис", "ремонт", "масло", "диагност", "техобслуж",
        "обслуживан", "лкп",
    ),
    "EMPLOYEE_AGENT": (
        "внутренн", "регламент", "скрипт продаж", "эскалац", "руководител",
        "отчёт", "отчет", "kpi", "конкурент", "исследуй", "анализ рынка",
        "база знаний", "ингест", "проверить документ", "проверь документ",
        "проверка документа", "проверка источника",
    ),
}

_AMBIGUOUS_REQUESTS = frozenset({
    "какие условия", "условия", "хочу оформить", "как оформить", "оформить",
    "какие документы", "что нужно", "что требуется",
})

_DIRECT_HUMAN_MARKERS = (
    "живой человек", "соедини с человеком", "соедините с человеком",
    "позови оператора", "позовите оператора", "хочу человека",
    "передай менеджеру", "передайте менеджеру", "нужен менеджер",
    "позови сотрудника", "позовите сотрудника", "хочу сотрудника",
)

_HIGH_RISK_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "financial_commitment",
        (
            "подтверди скид", "дай скид", "согласуй скид", "окончательная цена",
            "одобри кредит", "подтверди кредит", "подпиши договор",
            "заключи договор", "верни деньги", "возврат денег",
        ),
        "sales_manager",
    ),
    (
        "warranty_dispute",
        ("претензи", "компенсац", "спорный гарантийн", "жалоба на сервис"),
        "service_manager",
    ),
    (
        "external_change",
        (
            "измени мои данные", "измени персональные данные", "отмени заказ",
            "удали заказ", "перенеси запись", "измени запись",
        ),
        "support_operator",
    ),
)


def _normalize(message: str) -> str:
    return " ".join(re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9-]+", message.lower().replace("ё", "е")))


def _domain_scores(message: str) -> dict[str, int]:
    lowered = message.lower().replace("ё", "е")
    scores = {
        agent: sum(1 for key in keys if key in lowered)
        for agent, keys in _DOMAIN_KEYS.items()
    }
    if re.search(r"(?<![а-яa-z])то(?![а-яa-z])", lowered):
        scores["SERVICE_AGENT"] += 1
    return scores


@dataclass(frozen=True)
class RouterDecision:
    route: RouteKind
    intent: str
    reason: str
    risk: RiskLevel = "low"
    agent: str | None = None
    human_target: str | None = None
    model_tier: Literal["simple", "complex"] | None = None

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


class ModelRouter:
    """Deterministic policy gate before optional LLM classification.

    It chooses the required capability and control level. It never answers a
    business question and never treats a stronger model as a replacement for
    missing approved evidence.
    """

    def decide(self, message: str, active_agent: str | None = None) -> RouterDecision:
        normalized = _normalize(message)

        if any(marker in normalized for marker in _DIRECT_HUMAN_MARKERS):
            target = {
                "SALES_AGENT": "sales_manager",
                "SERVICE_AGENT": "service_manager",
                "SUPPORT_AGENT": "support_operator",
                "EMPLOYEE_AGENT": "department_manager",
            }.get(active_agent, "human_operator")
            return RouterDecision(
                route="human", intent="human_request", reason="explicit_human_request",
                risk="medium", human_target=target,
            )

        for intent, markers, target in _HIGH_RISK_RULES:
            if any(marker in normalized for marker in markers):
                return RouterDecision(
                    route="human", intent=intent, reason="human_approval_required",
                    risk="high", human_target=target,
                )

        if normalized in _AMBIGUOUS_REQUESTS:
            return RouterDecision(
                route="clarify", intent="unknown", reason="ambiguous_request",
                risk="low",
            )

        scores = _domain_scores(message)
        matched = [(agent, score) for agent, score in scores.items() if score > 0]
        matched.sort(key=lambda item: item[1], reverse=True)
        if len(matched) > 1:
            best_agent = matched[0][0] if matched[0][1] > matched[1][1] else None
            return RouterDecision(
                route="complex_model",
                intent="multi_intent",
                reason="multiple_domain_intents",
                risk="medium",
                agent=best_agent,
                model_tier="complex",
            )
        if matched:
            return RouterDecision(
                route="simple_model",
                intent=matched[0][0].lower(),
                reason="single_domain_intent",
                agent=matched[0][0],
                model_tier="simple",
            )
        if active_agent is not None:
            return RouterDecision(
                route="skill", intent="follow_up", reason="session_continuity",
                agent=active_agent,
            )
        return RouterDecision(
            route="complex_model", intent="unknown", reason="llm_classification_required",
            risk="medium", model_tier="complex",
        )
