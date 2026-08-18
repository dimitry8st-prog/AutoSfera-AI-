from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from autonova.logging import get_logger
from autonova.rag import RAGRetriever, RetrievedChunk

logger = get_logger("autonova.skills")


@dataclass
class SkillResult:
    skill_id: str
    reply: str
    escalated: bool = False
    escalation_target: str | None = None
    escalation_reason: str | None = None
    collected_fields: dict[str, Any] = field(default_factory=dict)
    rag_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


SkillHandler = Callable[[str, list[RetrievedChunk], dict[str, Any]], SkillResult]


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    agent: str
    description: str
    keywords: tuple[str, ...]
    handler: SkillHandler

    def match_score(self, text: str) -> float:
        lowered = text.lower()
        hits = 0
        for kw in self.keywords:
            key = kw.lower()
            if len(key) <= 2:
                if re.search(rf"(?<![а-яa-z0-9]){re.escape(key)}(?![а-яa-z0-9])", lowered):
                    hits += 1
            elif key in lowered:
                hits += 1
        if not self.keywords:
            return 0.0
        return hits / len(self.keywords)


# Sections useful for user-facing answers (scripts/policies stay in RAG index
# for retrieval scoring but are not dumped into replies by default).
_ANSWER_SECTIONS = frozenset(
    {
        "sales",
        "customer_support",
        "service",
        "finance",
        "company",
        "faq",
        "legal",
        "internal",
    }
)

_SKILL_SECTIONS: dict[str, tuple[str, ...]] = {
    "vehicle_selection": ("sales", "faq"),
    "trade_in": ("sales",),
    "credit_leasing": ("finance", "faq"),
    "test_drive_booking": ("sales",),
    "documentation_support": ("customer_support", "faq"),
    "customer_faq": ("faq", "customer_support", "company"),
    "warranty_consultation": ("service", "faq"),
    "service_booking": ("service",),
    "maintenance_consultation": ("service", "faq"),
    "competitor_research": ("internal", "sales", "company"),
}


def _pick_chunks(
    chunks: list[RetrievedChunk],
    skill_id: str,
    limit: int = 2,
    prefer_ids: tuple[str, ...] = (),
) -> list[RetrievedChunk]:
    preferred = _SKILL_SECTIONS.get(skill_id, ())

    def rank(chunk: RetrievedChunk) -> tuple[int, int, float]:
        doc_id = chunk.document.id
        section = chunk.document.section
        id_rank = prefer_ids.index(doc_id) if prefer_ids and doc_id in prefer_ids else 100
        if preferred and section in preferred:
            section_rank = preferred.index(section)
        elif section in _ANSWER_SECTIONS:
            section_rank = len(preferred) + 1
        else:
            section_rank = len(preferred) + 50
        return (id_rank, section_rank, -chunk.score)

    ranked = sorted(chunks, key=rank)
    filtered = [
        c
        for c in ranked
        if (prefer_ids and c.document.id in prefer_ids)
        or c.document.section in _ANSWER_SECTIONS
        or (preferred and c.document.section in preferred)
    ]
    chosen = filtered[:limit] if filtered else ranked[:limit]
    seen: set[str] = set()
    unique: list[RetrievedChunk] = []
    for chunk in chosen:
        key = chunk.document.content.strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
    return unique


def _context_or_missing(
    chunks: list[RetrievedChunk],
    skill_id: str = "",
    limit: int = 2,
    prefer_ids: tuple[str, ...] = (),
) -> tuple[str, list[str], bool]:
    picked = (
        _pick_chunks(chunks, skill_id, limit=limit, prefer_ids=prefer_ids)
        if chunks
        else []
    )
    if not picked:
        return (
            "В базе знаний нет данных по этому вопросу. "
            "Я передам обращение сотруднику AutoSfera AI.",
            [],
            True,
        )
    parts = [c.document.content.strip() for c in picked]
    ids = [c.document.id for c in picked]
    return "\n\n".join(parts), ids, False


def _extract_phone(text: str) -> str | None:
    match = re.search(r"(\+?\d[\d\-\s()]{9,}\d)", text)
    return match.group(1).strip() if match else None


def _extract_vehicle(text: str) -> str | None:
    match = re.search(r"\b(Nova\s+(?:Comfort|Drive|Cargo|Classic))\b", text, flags=re.IGNORECASE)
    return match.group(1).title() if match else None


def _extract_order_id(text: str) -> str | None:
    match = re.search(r"АН-\d{4}-\d{4}", text, flags=re.IGNORECASE)
    if not match:
        return None
    # Normalize Latin lookalikes of Cyrillic АН- prefix if pasted from KB/docs.
    raw = match.group(0)
    return "АН-" + raw.split("-", 1)[1]


# --- Sales skills ---

def vehicle_selection(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "vehicle_selection", limit=1)
    if missing:
        return SkillResult(
            "vehicle_selection",
            text,
            escalated=True,
            escalation_target="sales_manager",
            escalation_reason="нет данных в KB",
            rag_ids=ids,
        )
    reply = (
        "Помогу подобрать автомобиль. Вот данные из каталога автосалона:\n\n"
        f"{text}\n\n"
        "Уточните бюджет, тип кузова и предпочтения по комплектации."
    )
    return SkillResult("vehicle_selection", reply, rag_ids=ids)


def trade_in(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "trade_in")
    if missing:
        return SkillResult(
            "trade_in",
            text,
            escalated=True,
            escalation_target="sales_manager",
            escalation_reason="нет данных Trade-in",
            rag_ids=ids,
        )
    reply = (
        f"{text}\n\n"
        "Для предварительной оценки укажите марку, модель, год, пробег и состояние. "
        "Итоговую сумму зафиксирует менеджер после осмотра."
    )
    return SkillResult("trade_in", reply, rag_ids=ids)


def credit_leasing(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    lowered = message.lower()
    prefer_ids: list[str] = []
    if "лизинг" in lowered:
        prefer_ids.extend(["finance-leasing"])
    if any(k in lowered for k in ("кредит", "рассроч", "ставк", "взнос")):
        prefer_ids.extend(["finance-credit", "faq-sales-credit"])
    if not prefer_ids:
        prefer_ids.extend(["finance-credit", "finance-leasing", "faq-sales-credit"])
    text, ids, missing = _context_or_missing(
        chunks,
        "credit_leasing",
        limit=1,
        prefer_ids=tuple(prefer_ids),
    )
    if missing:
        return SkillResult(
            "credit_leasing",
            text,
            escalated=True,
            escalation_target="finance_specialist",
            escalation_reason="нет финансовых данных",
            rag_ids=ids,
        )
    reply = (
        f"{text}\n\n"
        "Я не принимаю финансовых решений и не одобряю сделки — "
        "для договора подключу специалиста."
    )
    lowered = message.lower()
    escalate = any(w in lowered for w in ("договор", "одобри", "подпиши", "оформи кредит"))
    return SkillResult(
        "credit_leasing",
        reply if not escalate else reply + "\nПередаю обращение кредитному/лизинговому специалисту.",
        escalated=escalate,
        escalation_target="finance_specialist" if escalate else None,
        escalation_reason="запрос финансового решения" if escalate else None,
        rag_ids=ids,
    )


def test_drive_booking(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, _ = _context_or_missing(chunks, "test_drive_booking")
    phone = _extract_phone(message)
    vehicle = _extract_vehicle(message)
    fields = {key: value for key, value in {"phone": phone, "vehicle": vehicle}.items() if value}
    if phone and vehicle:
        reply = (
            f"{text}\n\n"
            f"Заявка на тест-драйв принята предварительно (телефон: {phone}). "
            "Подтверждение выполнит менеджер."
        )
        return SkillResult(
            "test_drive_booking",
            reply,
            escalated=True,
            escalation_target="sales_manager",
            escalation_reason="подтверждение тест-драйва",
            collected_fields=fields,
            rag_ids=ids,
        )
    reply = (
        f"{text}\n\n"
        "Для записи укажите ФИО, телефон, модель и желаемые дату/время."
    )
    return SkillResult("test_drive_booking", reply, collected_fields=fields, rag_ids=ids)


# --- Support skills ---

_KNOWN_ORDERS = {
    "АН-2024-0512": (
        "Заказ АН-2024-0512: Nova Drive Premium, серебристый, "
        "статус «Предпродажная подготовка», ориентировочная выдача через 3 дня."
    ),
    "АН-2024-0388": (
        "Заказ АН-2024-0388: Nova Comfort Standard, белый, "
        "статус «В пути со склада», ориентировочная выдача через 5 дней."
    ),
}


def order_status(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    order_id = _extract_order_id(message)
    ids = [c.document.id for c in chunks]
    if not order_id:
        return SkillResult(
            "order_status",
            "Укажите номер заказа в формате АН-2024-XXXX. "
            "Известные тестовые: АН-2024-0512, АН-2024-0388.",
            rag_ids=ids,
        )
    if order_id in _KNOWN_ORDERS:
        return SkillResult(
            "order_status",
            _KNOWN_ORDERS[order_id],
            collected_fields={"order_id": order_id},
            rag_ids=ids,
        )
    return SkillResult(
        "order_status",
        f"Заказ {order_id} не найден в тестовой базе. Передаю обращение специалисту поддержки.",
        escalated=True,
        escalation_target="support_specialist",
        escalation_reason="неизвестный заказ",
        collected_fields={"order_id": order_id},
        rag_ids=ids,
    )


def documentation_support(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "documentation_support")
    if missing:
        return SkillResult(
            "documentation_support",
            text,
            escalated=True,
            escalation_target="support_specialist",
            escalation_reason="нет данных о документах",
            rag_ids=ids,
        )
    return SkillResult("documentation_support", text, rag_ids=ids)


def customer_faq(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "customer_faq")
    if missing:
        return SkillResult(
            "customer_faq",
            "Не нашёл ответ в базе знаний. Передам вопрос специалисту.",
            escalated=True,
            escalation_target="support_specialist",
            escalation_reason="FAQ miss",
            rag_ids=ids,
        )
    return SkillResult("customer_faq", text, rag_ids=ids)


def support_escalation(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    return SkillResult(
        "support_escalation",
        "Подключаю профильного специалиста службы поддержки. Сохранил контекст обращения.",
        escalated=True,
        escalation_target="support_specialist",
        escalation_reason=message[:200],
        rag_ids=[c.document.id for c in chunks],
    )


# --- Service skills ---

def warranty_consultation(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "warranty_consultation", limit=1)
    if missing:
        return SkillResult(
            "warranty_consultation",
            text,
            escalated=True,
            escalation_target="service_engineer",
            escalation_reason="нет данных о гарантии",
            rag_ids=ids,
        )
    lowered = message.lower()
    confirm_request = any(
        w in lowered for w in ("подтверди гарантию", "это гарантийный", "признай гарантий")
    )
    reply = (
        f"{text}\n\n"
        "Важно: я не подтверждаю гарантийный случай — это делает только инженер сервиса."
    )
    return SkillResult(
        "warranty_consultation",
        reply,
        escalated=confirm_request,
        escalation_target="service_engineer" if confirm_request else None,
        escalation_reason="запрос подтверждения гарантии" if confirm_request else None,
        rag_ids=ids,
    )


def service_booking(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, _ = _context_or_missing(chunks, "service_booking", limit=1)
    phone = _extract_phone(message)
    fields = {"phone": phone} if phone else {}
    if phone:
        reply = (
            f"{text}\n\n"
            f"Предварительная заявка на сервис принята (телефон: {phone}). "
            "Слот подтвердит сотрудник сервиса."
        )
        return SkillResult(
            "service_booking",
            reply,
            escalated=True,
            escalation_target="service_advisor",
            escalation_reason="подтверждение записи в сервис",
            collected_fields=fields,
            rag_ids=ids,
        )
    reply = f"{text}\n\nУкажите модель, телефон, дату и описание проблемы."
    return SkillResult("service_booking", reply, collected_fields=fields, rag_ids=ids)


def maintenance_consultation(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "maintenance_consultation", limit=1)
    if missing:
        return SkillResult(
            "maintenance_consultation",
            text,
            escalated=True,
            escalation_target="service_advisor",
            escalation_reason="нет данных ТО",
            rag_ids=ids,
        )
    return SkillResult("maintenance_consultation", text, rag_ids=ids)


def service_escalation(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    return SkillResult(
        "service_escalation",
        "Передаю обращение инженеру сервиса. Гарантийные и ремонтные решения принимает только сотрудник.",
        escalated=True,
        escalation_target="service_engineer",
        escalation_reason=message[:200],
        rag_ids=[c.document.id for c in chunks],
    )


# --- Employee skills ---

def internal_knowledge(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "internal_knowledge", limit=2)
    if missing:
        return SkillResult(
            "internal_knowledge", text, escalated=True,
            escalation_target="department_manager",
            escalation_reason="нет внутреннего регламента", rag_ids=ids,
        )
    return SkillResult("internal_knowledge", text, rag_ids=ids)


def sales_coaching(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "sales_coaching", limit=2)
    reply = f"{text}\n\nСледующий шаг: уточните потребность клиента и зафиксируйте договорённость в заявке."
    return SkillResult("sales_coaching", reply, escalated=missing, escalation_target="sales_manager" if missing else None, rag_ids=ids)


def process_lookup(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    text, ids, missing = _context_or_missing(chunks, "process_lookup", limit=2)
    return SkillResult("process_lookup", text, escalated=missing, escalation_target="department_manager" if missing else None, rag_ids=ids)


def competitor_research(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    return SkillResult(
        "competitor_research",
        "Запрос на исследование конкурента подготовлен. Создайте задачу в разделе "
        "«Исследования»: внешний результат сохранится как черновик и попадёт в базу "
        "знаний только после approve сотрудником.",
        rag_ids=[c.document.id for c in chunks],
        metadata={"requires_research_job": True, "human_approval": True},
    )


def manager_escalation(message: str, chunks: list[RetrievedChunk], ctx: dict[str, Any]) -> SkillResult:
    return SkillResult(
        "manager_escalation",
        "Запрос подготовлен для передачи руководителю. Контекст обращения сохранён.",
        escalated=True,
        escalation_target="department_manager",
        escalation_reason=message[:200],
        rag_ids=[c.document.id for c in chunks],
    )


def build_skill_registry() -> dict[str, Skill]:
    skills = [
        Skill(
            "vehicle_selection",
            "Vehicle Selection",
            "SALES_AGENT",
            "Подбор автомобиля и комплектации",
            ("купить", "подобрать", "кроссовер", "седан", "фургон", "модель", "комплектац", "nova"),
            vehicle_selection,
        ),
        Skill(
            "trade_in",
            "Trade-In",
            "SALES_AGENT",
            "Оценка и обмен автомобиля",
            ("trade-in", "трейд", "обмен", "сдать авто", "оценка"),
            trade_in,
        ),
        Skill(
            "credit_leasing",
            "Credit & Leasing",
            "SALES_AGENT",
            "Консультации по кредиту и лизингу",
            ("кредит", "лизинг", "взнос", "рассрочк", "ставка", "b2b"),
            credit_leasing,
        ),
        Skill(
            "test_drive_booking",
            "Test Drive Booking",
            "SALES_AGENT",
            "Запись на тест-драйв",
            ("тест-драйв", "тест драйв", "пробная поездка", "записать на тест"),
            test_drive_booking,
        ),
        Skill(
            "order_status",
            "Order Status",
            "SUPPORT_AGENT",
            "Статус заказа",
            ("статус", "заказ", "ан-2024", "где мой", "выдача"),
            order_status,
        ),
        Skill(
            "documentation_support",
            "Documentation Support",
            "SUPPORT_AGENT",
            "Помощь с документами",
            ("документ", "паспорт", "инн", "справка"),
            documentation_support,
        ),
        Skill(
            "customer_faq",
            "Customer FAQ",
            "SUPPORT_AGENT",
            "Типовые вопросы клиентов",
            ("вопрос", "как", "что нужно", "faq", "возврат"),
            customer_faq,
        ),
        Skill(
            "support_escalation",
            "Support Escalation",
            "SUPPORT_AGENT",
            "Передача специалисту поддержки",
            ("оператор", "человек", "специалист", "менеджер поддержки"),
            support_escalation,
        ),
        Skill(
            "warranty_consultation",
            "Warranty Consultation",
            "SERVICE_AGENT",
            "Консультации по гарантии",
            ("гарантия", "кузов", "лкп", "гарантий"),
            warranty_consultation,
        ),
        Skill(
            "service_booking",
            "Service Booking",
            "SERVICE_AGENT",
            "Запись в сервис",
            ("запис", "сервис", "диагностик", "ремонт"),
            service_booking,
        ),
        Skill(
            "maintenance_consultation",
            "Maintenance Consultation",
            "SERVICE_AGENT",
            "Консультации по ТО и эксплуатации",
            ("техобслуж", "техобслуживание", "обслуживан", "масло", "фильтр", "эксплуатац", "регламент"),
            maintenance_consultation,
        ),
        Skill(
            "service_escalation",
            "Service Escalation",
            "SERVICE_AGENT",
            "Передача инженеру сервиса",
            ("инженер", "гарантийный случай", "подтверди гарантию"),
            service_escalation,
        ),
        Skill(
            "internal_knowledge", "Internal Knowledge", "EMPLOYEE_AGENT",
            "Поиск внутренних инструкций", ("внутренн", "инструкц", "правило", "политик"),
            internal_knowledge,
        ),
        Skill(
            "sales_coaching", "Sales Coaching", "EMPLOYEE_AGENT",
            "Подсказки сотруднику по работе с клиентом", ("скрипт", "продаж", "клиент", "возражен"),
            sales_coaching,
        ),
        Skill(
            "process_lookup", "Process Lookup", "EMPLOYEE_AGENT",
            "Поиск регламентов и процессов", ("регламент", "процесс", "лид", "заявк", "что делать"),
            process_lookup,
        ),
        Skill(
            "manager_escalation", "Manager Escalation", "EMPLOYEE_AGENT",
            "Передача вопроса руководителю", ("руководител", "эскалац", "согласован", "решение"),
            manager_escalation,
        ),
        Skill(
            "competitor_research", "Competitor Research", "EMPLOYEE_AGENT",
            "Исследование одного конкурента через защищённый n8n/Langflow-контур",
            ("конкурент", "сравни компанию", "исследуй продукт", "анализ рынка", "competitor"),
            competitor_research,
        ),
    ]
    registry = {s.id: s for s in skills}
    logger.info("Registered %s skills", len(registry))
    return registry


class SkillRouter:
    def __init__(self, registry: dict[str, Skill] | None = None) -> None:
        self.registry = registry or build_skill_registry()

    def skills_for_agent(self, agent_key: str) -> list[Skill]:
        return [s for s in self.registry.values() if s.agent == agent_key]

    def select(self, agent_key: str, message: str) -> Skill:
        candidates = self.skills_for_agent(agent_key)
        ranked = sorted(candidates, key=lambda s: s.match_score(message), reverse=True)
        best = ranked[0]
        if best.match_score(message) == 0:
            # defaults per agent
            defaults = {
                "SALES_AGENT": "vehicle_selection",
                "SUPPORT_AGENT": "customer_faq",
                "SERVICE_AGENT": "maintenance_consultation",
                "EMPLOYEE_AGENT": "internal_knowledge",
            }
            return self.registry[defaults[agent_key]]
        logger.debug("Selected skill %s for agent %s", best.id, agent_key)
        return best

    def run(
        self,
        agent_key: str,
        message: str,
        chunks: list[RetrievedChunk],
        ctx: dict[str, Any] | None = None,
    ) -> SkillResult:
        skill = self.select(agent_key, message)
        result = skill.handler(message, chunks, ctx or {})
        logger.info(
            "Skill executed id=%s agent=%s escalated=%s",
            result.skill_id,
            agent_key,
            result.escalated,
        )
        return result
