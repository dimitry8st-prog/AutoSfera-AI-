from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from autonova.agents import AGENT_META, AgentReply, BaseAgent, build_agents, load_prompt
from autonova.knowledge import KnowledgeBase
from autonova.llm import LLMClient, extract_json_object, get_llm_client
from autonova.logging import DialogueLogger, get_logger, setup_logging
from autonova.model_router import ModelRouter, RouterDecision
from autonova.rag import RAGRetriever, build_retriever
from autonova.skills import SkillRouter, build_skill_registry
from autonova.config import get_settings

logger = get_logger("autonova.orchestrator")

GRAPH_NODES = (
    "classify_conversation",
    "route_agent",
    "access_guard",
    "execute_agent",
    "persist_turn",
)


class OrchestratorGraphState(TypedDict, total=False):
    message: str
    channel: str
    allowed_agents: set[str] | None
    session: "SessionState"
    dialogue: DialogueLogger
    result: "TurnResult"
    greeting: str | None
    routing_reason: str | None
    model_decision: RouterDecision
    selected_agent: str
    agent_reply: AgentReply


_CONVERSATIONAL_PHRASES: dict[str, frozenset[str]] = {
    "greeting": frozenset({
        "привет", "здравствуйте", "здравствуй", "здраствуйте", "приветствую",
        "добрый день", "доброго дня", "доброе утро", "добрый вечер", "салют",
        "хай", "hello", "hi", "привет как дела", "здравствуйте как дела",
        "здравствуйте подскажите", "привет подскажите",
    }),
    "thanks": frozenset({
        "спасибо", "спасибо большое", "большое спасибо", "благодарю",
        "благодарю вас", "понятно спасибо", "хорошо спасибо",
    }),
    "farewell": frozenset({
        "до свидания", "до встречи", "пока", "всего доброго", "всего хорошего",
        "хорошего дня", "хорошего вечера", "до скорого", "bye",
    }),
    "wellbeing": frozenset({
        "как дела", "как ты", "как настроение", "как поживаешь",
    }),
    "identity": frozenset({
        "кто ты", "ты кто", "что ты такое", "ты бот", "это бот", "это человек",
    }),
    "capabilities": frozenset({
        "что ты умеешь", "чем ты можешь помочь", "чем можешь помочь",
        "что можешь", "помоги", "помощь", "help",
        "что вы умеете", "чем вы можете помочь", "что вы можете",
    }),
    "menu": frozenset({
        "что у вас есть", "что есть у вас", "какие услуги",
        "какие услуги у вас", "чем занимаетесь", "чем вы занимаетесь",
        "что предлагаете", "что вы предлагаете", "с чем поможешь",
        "с чем можете помочь", "какие темы", "меню",
    }),
    "hours": frozenset({
        "режим работы", "часы работы", "график работы", "когда открыты",
        "когда вы открыты", "до скольки работаете", "во сколько открыты",
        "рабочее время",
    }),
    "contacts": frozenset({
        "как связаться", "ваши контакты", "ваш телефон", "ваш адрес",
        "где вы находитесь", "где находитесь", "контакт автосалона",
        "телефон салона", "адрес салона",
    }),
    "human": frozenset({
        "позови оператора", "позовите оператора", "живой человек",
        "соедини с человеком", "соедините с человеком", "хочу человека",
        "это не бот", "позовите сотрудника",
        "подготовь обращение к сотруднику", "подготовьте обращение к сотруднику",
        "подготовь обращение", "подготовьте обращение",
        "обращение к сотруднику",
    }),
    "how_it_works": frozenset({
        "как ты работаешь", "как вы работаете", "как это работает",
        "как устроен ассистент", "что за сервис",
    }),
    "privacy": frozenset({
        "мои данные", "персональные данные", "это конфиденциально",
        "вы сохраняете данные", "конфиденциальность",
    }),
}

_CONVERSATIONAL_DOCUMENTS = {
    "greeting": "conversation-greeting",
    "thanks": "conversation-thanks",
    "farewell": "conversation-farewell",
    "wellbeing": "conversation-wellbeing",
    "identity": "conversation-identity",
    "capabilities": "conversation-capabilities",
    "menu": "conversation-menu",
    "hours": "conversation-hours",
    "contacts": "conversation-contacts",
    "human": "conversation-human",
    "how_it_works": "conversation-how-it-works",
    "privacy": "conversation-privacy",
}

_SAFETY_DOCUMENTS = {
    "illegal": "conversation-safety-illegal",
    "abuse": "conversation-safety-abuse",
}

_ILLEGAL_TOPIC_KEYS = (
    "оружие", "пистолет", "винтовк", "калашников", "ак-47", "ak-47",
    "бомб", "взрывчат", "гранат", "самострел", "наркотик", "наркота",
    "кокаин", "героин", "амфетамин", "мефедрон", "марихуан", "гашиш",
    "экстази", "закладк", "спайс", "метадон", "как убить",
)

_PROFANITY_RE = re.compile(
    r"(?<![а-яa-z0-9])("
    r"бля(?:ть|дь)?|сука|суки|сучар\w*|хуй\w*|хуя\w*|хуе\w*|"
    r"пизд\w*|ебан\w*|ёбан\w*|ебат\w*|ебл\w*|мудак\w*|мудил\w*|"
    r"гондон\w*|пидор\w*|пидар\w*|чмо|залуп\w*|нахуй|похуй|охуе\w*|"
    r"заеб\w*|fuck(?:ing)?|shit|asshole|bitch|cunt|dickhead"
    r")(?![а-яa-z0-9])",
    re.IGNORECASE,
)

_UNEXPECTED_TOPIC_KEYS = (
    "погода", "курс акци", "крипто", "рецепт", "футбол", "кино",
)

_NON_DEALER_PRODUCT_KEYS = (
    "танк", "самолет", "самолёт", "вертолет", "вертолёт",
    "ракет", "корабл", "яхт", "лодк", "велосипед", "мотоцикл",
)

_ANAPHORIC_FOLLOW_UP_RE = re.compile(
    r"^(а |и |ну )?(какой|какая|какие|какое|каков|сколько|когда|где|"
    r"куда|зачем|почему|ещё|еще|подробнее|уточни)(\s|$)",
    re.IGNORECASE,
)

_OFF_CATALOG_KEYS = (
    "запчаст", "колес", "шины", "покрышк",
    "аккумулятор", "колодк",
)

_VEHICLE_TOPIC_KEYS = (
    "машин", "модель", "модел", "каталог", "кроссовер", "седан", "фургон",
    "nova", "комплектац",
)

_BUDGET_TOPIC_KEYS = (
    "доллар", "руб", "бюджет", "млн", "бакс", "евро", "цена", "стоим",
)

_CUSTOMER_HANDOFF_MARKERS = (
    "обращение к сотруднику",
    "обращение сотруднику",
    "подготовь обращение",
    "подготовьте обращение",
    "передай сотруднику",
    "передайте сотруднику",
    "свяжите с сотрудником",
    "свяжи с сотрудником",
    "позвать сотрудника",
    "позовите сотрудника",
    "нужен сотрудник",
    "хочу сотрудника",
)

_ORCHESTRATOR_COMPANY_FAQ_IDS = frozenset({
    "company-contacts",
    "company-overview",
    "company-ai-disclosure",
})


def _normalize_conversational_phrase(message: str) -> str:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", message.lower())
    return " ".join(words)


def _conversational_intent(message: str) -> str | None:
    normalized = _normalize_conversational_phrase(message)
    for intent, phrases in _CONVERSATIONAL_PHRASES.items():
        if normalized in phrases:
            return intent
    return None


def _safety_intent(message: str) -> str | None:
    """Refuse illegal and abusive turns before any agent routing."""
    lowered = message.lower().replace("ё", "е")
    if _PROFANITY_RE.search(lowered):
        return "abuse"
    if any(key in lowered for key in _ILLEGAL_TOPIC_KEYS):
        return "illegal"
    return None


def _off_catalog_product(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return any(key in lowered for key in _OFF_CATALOG_KEYS)


def _unexpected_salon_topic(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return any(key in lowered for key in _UNEXPECTED_TOPIC_KEYS)


def _unknown_catalog_request(message: str) -> bool:
    """True when the user asks to sell/find something the demo salon does not carry."""
    if _conversational_intent(message) is not None:
        return False
    lowered = message.lower().replace("ё", "е")
    if any(key in lowered for key in _NON_DEALER_PRODUCT_KEYS):
        return True
    if (
        _vehicle_topic(message)
        or _budget_topic(message)
        or any(
            key in lowered
            for key in (
                "заказ", "ан-2024", "гарант", "сервис", "кредит", "лизинг",
                "документ", "договор", "сделк", "тест-драйв", "trade", "трейд",
            )
        )
    ):
        return False
    asking_to_sell = bool(re.search(r"\b(продай|продать|продайте|продажа)\b", lowered))
    asking_if_in_stock = bool(
        re.search(r"есть ли у вас", lowered) or re.search(r"у вас есть", lowered)
    )
    return asking_to_sell or asking_if_in_stock


def _is_anaphoric_follow_up(message: str) -> bool:
    """Short attribute questions like «а какой срок?» keep the current specialist."""
    if _unknown_catalog_request(message) or _off_catalog_product(message):
        return False
    normalized = _normalize_conversational_phrase(message)
    words = normalized.split()
    if not words or len(words) > 8:
        return False
    if re.fullmatch(r"\d+([.,]\d+)?", "".join(words)):
        return True
    if normalized.startswith("что есть") or normalized.startswith("а что есть"):
        return True
    return bool(_ANAPHORIC_FOLLOW_UP_RE.match(normalized))


def _off_scope_document_id(message: str) -> str | None:
    if _off_catalog_product(message):
        return "conversation-parts"
    if _unexpected_salon_topic(message) or _unknown_catalog_request(message):
        return "conversation-off-scope"
    return None


def _spoken_kb_reply(content: str) -> str:
    """Show the answer side of a RAG Q/A card, not the canned question."""
    match = re.search(r"(?:^|\s)О:\s*(.*)\Z", content.strip(), flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


def _budget_topic(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return any(key in lowered for key in _BUDGET_TOPIC_KEYS)


def _vehicle_topic(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    if _off_catalog_product(lowered):
        return False
    return any(key in lowered for key in _VEHICLE_TOPIC_KEYS)


def _customer_staff_handoff(message: str) -> bool:
    lowered = message.lower().replace("ё", "е")
    return any(marker in lowered for marker in _CUSTOMER_HANDOFF_MARKERS)


_AGENT_INTENT_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EMPLOYEE_AGENT", (
        "внутренн", "регламент", "скрипт продаж", "эскалац",
        "руководител", "отчёт", "отчет", "kpi", "конкурент", "исследуй",
        "анализ рынка",
    )),
    ("SALES_AGENT", (
        "купить", "продай", "продать", "продайте", "машин", "предложи",
        "кроссовер", "седан",
        "кредит", "лизинг", "trade", "тест-драйв", "nova", "b2b",
        "юридическ", "модел", "каталог", "условия покуп", "вариант оплат",
        "приобретени",
    )),
    ("SUPPORT_AGENT", (
        "заказ", "ан-2024", "документ", "статус", "возврат", "инн",
        "сделк", "договор", "оформлен",
    )),
    ("SERVICE_AGENT", (
        "гарант", "сервис", "ремонт", "масло", "диагност", "техобслуж",
        "обслуживан", "лкп",
    )),
)


def _explicit_agent_intent(message: str, skills: SkillRouter | None = None) -> str | None:
    """Pick the strongest domain signal on this turn, including skill keywords."""
    if _off_catalog_product(message) or _unknown_catalog_request(message):
        return None
    if re.search(r"оформ\w*\s+заказ", message.lower().replace("ё", "е")) and "статус" not in message.lower() and not re.search(r"ан-\d{4}-\d{4}", message.lower()):
        return "SALES_AGENT"
    lowered = message.lower()
    hits: dict[str, float] = {agent: 0.0 for agent, _ in _AGENT_INTENT_KEYS}
    for agent, keys in _AGENT_INTENT_KEYS:
        hits[agent] = float(sum(1 for key in keys if key in lowered))
    if re.search(r"(?<![а-яa-z])то(?![а-яa-z])", lowered):
        hits["SERVICE_AGENT"] += 1.0
    direct_ranked = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    if direct_ranked[0][1] > 0:
        if direct_ranked[0][1] == direct_ranked[1][1]:
            return None
        return direct_ranked[0][0]
    if skills is not None:
        skill_best: dict[str, float] = {}
        for skill in skills.registry.values():
            score = float(skill.match_score(message))
            if score > skill_best.get(skill.agent, 0.0):
                skill_best[skill.agent] = score
        for agent, score in skill_best.items():
            # Internal skill keywords must not steal public client requests.
            if agent == "EMPLOYEE_AGENT" and hits["EMPLOYEE_AGENT"] <= 0:
                continue
            hits[agent] = score
    ranked = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    best_agent, best_score = ranked[0]
    if best_score <= 0:
        return None
    second = ranked[1][1] if len(ranked) > 1 else 0
    if best_score == second:
        return None
    return best_agent


@dataclass
class SessionState:
    session_id: str
    channel: str = "web"
    active_agent: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResult:
    session_id: str
    channel: str
    agent: str
    agent_label: str
    greeting: str | None
    reply: str
    skill: str | None
    escalated: bool
    escalation_target: str | None
    rag_ids: list[str]
    collected_fields: dict[str, Any] = field(default_factory=dict)
    routing_reason: str | None = None
    model_route: str | None = None
    model_tier: str | None = None
    routing_intent: str | None = None
    routing_risk: str | None = None


class AIOrchestrator:
    """Entry point: intent routing + specialized agent execution."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        rag: RAGRetriever | None = None,
        skills: SkillRouter | None = None,
        llm: LLMClient | None = None,
        store: Any | None = None,
        dealer_id: str | None = None,
        orchestrator_mode: Literal["langgraph", "legacy"] | None = None,
    ) -> None:
        setup_logging()
        self.kb = knowledge_base or KnowledgeBase()
        self.dealer_id = dealer_id or get_settings().dealer_id
        self.rag = rag or build_retriever(self.kb, self.dealer_id)
        self.skills = skills or SkillRouter(build_skill_registry())
        settings = get_settings()
        if llm is not None:
            self.simple_llm = llm
            self.complex_llm = llm
        else:
            self.simple_llm = get_llm_client(settings.openai_simple_model or settings.openai_model)
            self.complex_llm = get_llm_client(settings.openai_complex_model or settings.openai_model)
        # Compatibility alias for integrations that inject or inspect one client.
        self.llm = self.simple_llm
        self.model_router = ModelRouter()
        self.store = store
        self.agents: dict[str, BaseAgent] = build_agents(self.rag, self.skills)
        self.system_prompt = load_prompt("orchestrator.txt")
        self.sessions: dict[str, SessionState] = {}
        configured_mode = orchestrator_mode or get_settings().orchestrator_mode
        if configured_mode not in {"langgraph", "legacy"}:
            raise ValueError("ORCHESTRATOR_MODE must be 'langgraph' or 'legacy'")
        self.orchestrator_mode = configured_mode
        self.graph_nodes = GRAPH_NODES
        self.graph = self._build_graph() if configured_mode == "langgraph" else None
        logger.info(
            "AIOrchestrator ready mode=%s agents=%s",
            self.orchestrator_mode,
            list(self.agents),
        )

    def get_or_create_session(
        self,
        session_id: str | None = None,
        channel: str = "web",
    ) -> SessionState:
        sid = session_id or str(uuid4())
        if sid not in self.sessions:
            persisted = self.store.load_session(self.dealer_id, sid) if self.store else None
            self.sessions[sid] = SessionState(
                session_id=sid,
                channel=persisted["channel"] if persisted else channel,
                active_agent=persisted["active_agent"] if persisted else None,
                history=persisted["history"] if persisted else [],
            )
            logger.info("Created session %s channel=%s", sid, channel)
        return self.sessions[sid]

    def reset_session(self, session_id: str) -> SessionState:
        channel = self.sessions.get(session_id, SessionState(session_id)).channel
        self.sessions[session_id] = SessionState(session_id=session_id, channel=channel)
        self._persist(self.sessions[session_id])
        logger.info("Reset session %s", session_id)
        return self.sessions[session_id]

    def _persist(self, session: SessionState) -> None:
        if self.store:
            self.store.save_session(
                self.dealer_id,
                session.session_id,
                session.channel,
                session.active_agent,
                session.history,
            )

    def route(self, message: str, model_tier: str = "simple") -> dict[str, str]:
        llm = self.complex_llm if model_tier == "complex" else self.simple_llm
        raw = llm.complete(
            self.system_prompt,
            [{"role": "user", "content": message}],
        )
        data = extract_json_object(raw)
        agent = data.get("agent", "SALES_AGENT")
        if agent not in self.agents:
            agent = "SALES_AGENT"
        result = {
            "agent": agent,
            "greeting": data.get("greeting", f"Подключаю {AGENT_META[agent]['label']} AutoSfera AI."),
            "reason": data.get("reason", "intent_match"),
        }
        logger.info(
            "Routed to %s reason=%s model_tier=%s",
            result["agent"], result["reason"], model_tier,
        )
        return result

    def _build_graph(self) -> Any:
        builder = StateGraph(OrchestratorGraphState)
        builder.add_node("classify_conversation", self._graph_classify_conversation)
        builder.add_node("route_agent", self._graph_route_agent)
        builder.add_node("access_guard", self._graph_access_guard)
        builder.add_node("execute_agent", self._graph_execute_agent)
        builder.add_node("persist_turn", self._graph_persist_turn)
        builder.add_edge(START, "classify_conversation")
        builder.add_conditional_edges(
            "classify_conversation",
            self._graph_after_conversation,
            {"complete": END, "route": "route_agent"},
        )
        builder.add_edge("route_agent", "access_guard")
        builder.add_conditional_edges(
            "access_guard",
            self._graph_after_access,
            {"complete": END, "execute": "execute_agent"},
        )
        builder.add_edge("execute_agent", "persist_turn")
        builder.add_edge("persist_turn", END)
        return builder.compile()

    def _graph_classify_conversation(
        self, state: OrchestratorGraphState
    ) -> OrchestratorGraphState:
        result = self._handle_orchestrator_direct(
            state["message"], state["session"], state["dialogue"]
        )
        return {"result": result} if result is not None else {}

    @staticmethod
    def _graph_after_conversation(
        state: OrchestratorGraphState,
    ) -> Literal["complete", "route"]:
        return "complete" if state.get("result") is not None else "route"

    def _graph_route_agent(self, state: OrchestratorGraphState) -> OrchestratorGraphState:
        session = state["session"]
        decision = self.model_router.decide(state["message"], session.active_agent)
        explicit_agent = decision.agent or _explicit_agent_intent(state["message"], self.skills)
        should_route = session.active_agent is None or (
            explicit_agent is not None and explicit_agent != session.active_agent
        )
        if not should_route:
            return {
                "selected_agent": session.active_agent,
                "greeting": None,
                "routing_reason": "session_continuity",
                "model_decision": RouterDecision(
                    route="skill", intent="follow_up", reason="session_continuity",
                    agent=session.active_agent,
                ),
            }

        routed = self.route(state["message"], decision.model_tier or "simple")
        # Deterministic domain signals take precedence over a malformed LLM route.
        selected = explicit_agent or routed["agent"]
        previous_agent = session.active_agent
        session.active_agent = selected
        reason = "topic_switch" if previous_agent else routed["reason"]
        greeting = routed["greeting"]
        if routed["agent"] != selected:
            greeting = f"Подключаю {AGENT_META[selected]['label']} AutoSfera AI."
        state["dialogue"].log_routing(selected, reason, greeting)
        return {
            "selected_agent": selected,
            "greeting": greeting,
            "routing_reason": reason,
            "model_decision": decision,
        }

    @staticmethod
    def _graph_after_access(
        state: OrchestratorGraphState,
    ) -> Literal["complete", "execute"]:
        return "complete" if state.get("result") is not None else "execute"

    def _graph_access_guard(self, state: OrchestratorGraphState) -> OrchestratorGraphState:
        selected = state["selected_agent"]
        allowed_agents = state.get("allowed_agents")
        if allowed_agents is not None and selected not in allowed_agents:
            state["session"].active_agent = None
            denial = self._reply_from_orchestrator_document(
                state["message"],
                state["session"],
                state["dialogue"],
                "conversation-staff-only",
                reason="staff_only",
                skill="staff_only",
            )
            if denial is None:
                raise PermissionError(f"agent {selected} requires an employee role")
            return {"result": denial}
        return {}

    def _graph_execute_agent(self, state: OrchestratorGraphState) -> OrchestratorGraphState:
        message = state["message"]
        # Give Skills/RAG the missing subject of a short follow-up without exposing
        # internal graph state in the user-visible reply.
        if (
            state.get("routing_reason") == "session_continuity"
            and _is_anaphoric_follow_up(message)
            and _explicit_agent_intent(message, self.skills) is None
        ):
            previous_user_message = next(
                (
                    item["content"]
                    for item in reversed(state["session"].history)
                    if item.get("role") == "user"
                ),
                "",
            )
            if previous_user_message:
                message = f"{previous_user_message}\nУточнение пользователя: {message}"
        reply = self.agents[state["selected_agent"]].handle(
            message,
            history=state["session"].history,
            dialogue=state["dialogue"],
        )
        return {"agent_reply": reply}

    def _graph_persist_turn(self, state: OrchestratorGraphState) -> OrchestratorGraphState:
        session = state["session"]
        agent_reply = state["agent_reply"]
        decision = state.get("model_decision")
        final_model_route = "human" if agent_reply.escalated else (decision.route if decision else None)
        final_routing_risk = (
            "high" if agent_reply.escalated else (decision.risk if decision else None)
        )
        greeting = state.get("greeting")
        reply_text = agent_reply.text
        if greeting:
            reply_text = f"{greeting}\n\n{reply_text}"
        session.history.append({"role": "user", "content": state["message"]})
        session.history.append({"role": "assistant", "content": reply_text})
        session.metadata.update({
            "orchestrator": "langgraph",
            "last_node": "persist_turn",
            "routing_reason": state.get("routing_reason"),
            "approval_required": agent_reply.escalated,
            "model_route": final_model_route,
        })
        self._persist(session)
        return {"result": TurnResult(
            session_id=session.session_id,
            channel=session.channel,
            agent=agent_reply.agent,
            agent_label=AGENT_META[agent_reply.agent]["label"],
            greeting=greeting,
            reply=reply_text,
            skill=agent_reply.skill,
            escalated=agent_reply.escalated,
            escalation_target=agent_reply.escalation_target,
            rag_ids=agent_reply.rag_ids,
            collected_fields=agent_reply.collected_fields,
            routing_reason=state.get("routing_reason"),
            model_route=final_model_route,
            model_tier=decision.model_tier if decision else None,
            routing_intent=decision.intent if decision else None,
            routing_risk=final_routing_risk,
        )}

    def _safe_failure_result(
        self,
        message: str,
        session: SessionState,
        channel: str,
    ) -> TurnResult:
        reply = (
            "Сейчас не удалось завершить обработку запроса. "
            "Нужна помощь сотрудника AutoSfera AI; пожалуйста, повторите попытку позже."
        )
        session.history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ])
        session.metadata.update({"orchestrator": "langgraph", "last_node": "safe_fallback"})
        self._persist(session)
        return TurnResult(
            session_id=session.session_id,
            channel=channel,
            agent="AI_ORCHESTRATOR",
            agent_label="AI Orchestrator",
            greeting=None,
            reply=reply,
            skill="safe_fallback",
            escalated=True,
            escalation_target="human_operator",
            rag_ids=[],
            routing_reason="graph_failure",
            model_route="human",
            routing_intent="technical_failure",
            routing_risk="high",
        )

    def _orchestrator_faq_ids(self) -> set[str]:
        ids = {document.id for document in self.kb.by_section("conversation")}
        ids.update(_ORCHESTRATOR_COMPANY_FAQ_IDS)
        return ids

    def _reply_from_orchestrator_document(
        self,
        message: str,
        session: SessionState,
        dialogue: DialogueLogger,
        document_id: str,
        *,
        reason: str,
        skill: str,
        escalated: bool = False,
        escalation_target: str | None = None,
        model_decision: RouterDecision | None = None,
    ) -> TurnResult | None:
        document = self.kb.get(document_id)
        if document is None:
            logger.warning("Orchestrator KB document %s is missing", document_id)
            return None
        reply_text = _spoken_kb_reply(document.content)
        rag_ids = [document.id]
        dialogue.log_routing(agent="AI_ORCHESTRATOR", reason=reason, greeting="")
        dialogue.log_agent_reply(
            agent="AI_ORCHESTRATOR",
            skill=skill,
            reply=reply_text,
            escalated=escalated,
            rag_ids=rag_ids,
        )
        session.history.append({"role": "user", "content": message})
        session.history.append({"role": "assistant", "content": reply_text})
        self._persist(session)
        return TurnResult(
            session_id=session.session_id,
            channel=session.channel,
            agent="AI_ORCHESTRATOR",
            agent_label="AI Orchestrator",
            greeting=None,
            reply=reply_text,
            skill=skill,
            escalated=escalated,
            escalation_target=escalation_target,
            rag_ids=rag_ids,
            routing_reason=reason,
            model_route=model_decision.route if model_decision else "skill",
            model_tier=model_decision.model_tier if model_decision else None,
            routing_intent=model_decision.intent if model_decision else reason,
            routing_risk=model_decision.risk if model_decision else "low",
        )

    def _reply_from_router_decision(
        self,
        message: str,
        session: SessionState,
        dialogue: DialogueLogger,
        decision: RouterDecision,
    ) -> TurnResult:
        if decision.route == "clarify":
            reply_text = (
                "Уточните, пожалуйста, о каких условиях идёт речь: покупке автомобиля, "
                "оформлении заказа или сервисном обслуживании?"
            )
            skill = "route_clarification"
            escalated = False
        else:
            reply_text = (
                "Передаю обращение сотруднику AutoSfera AI. "
                "Автоматически подтверждать решение или выполнять действие не буду."
            )
            skill = "human_handoff"
            escalated = True
        dialogue.log_routing("AI_ORCHESTRATOR", decision.reason, "")
        dialogue.log_agent_reply(
            agent="AI_ORCHESTRATOR",
            skill=skill,
            reply=reply_text,
            escalated=escalated,
            rag_ids=[],
        )
        session.history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply_text},
        ])
        session.metadata.update({
            "routing_reason": "clarify" if decision.route == "clarify" else decision.reason,
            "model_route": decision.route,
            "routing_intent": decision.intent,
            "routing_risk": decision.risk,
            "approval_required": escalated,
        })
        self._persist(session)
        return TurnResult(
            session_id=session.session_id,
            channel=session.channel,
            agent="AI_ORCHESTRATOR",
            agent_label="AI Orchestrator",
            greeting=None,
            reply=reply_text,
            skill=skill,
            escalated=escalated,
            escalation_target=decision.human_target if escalated else None,
            rag_ids=[],
            routing_reason="clarify" if decision.route == "clarify" else decision.reason,
            model_route=decision.route,
            model_tier=decision.model_tier,
            routing_intent=decision.intent,
            routing_risk=decision.risk,
        )

    def _handle_orchestrator_direct(
        self,
        message: str,
        session: SessionState,
        dialogue: DialogueLogger,
    ) -> TurnResult | None:
        safety = _safety_intent(message)
        if safety is not None:
            return self._reply_from_orchestrator_document(
                message,
                session,
                dialogue,
                _SAFETY_DOCUMENTS[safety],
                reason=f"safety_{safety}",
                skill="safety_refusal",
            )

        model_decision = self.model_router.decide(message, session.active_agent)
        if model_decision.route in {"clarify", "human"}:
            return self._reply_from_router_decision(
                message, session, dialogue, model_decision
            )

        if _customer_staff_handoff(message):
            return self._reply_from_orchestrator_document(
                message,
                session,
                dialogue,
                "conversation-human",
                reason="conversational_human",
                skill="common_phrases",
            )

        off_scope_id = _off_scope_document_id(message)
        if off_scope_id is not None:
            session.active_agent = None
            return self._reply_from_orchestrator_document(
                message,
                session,
                dialogue,
                off_scope_id,
                reason="off_scope",
                skill="common_phrases",
            )

        intent = _conversational_intent(message)
        if intent is not None:
            if intent == "menu" and session.active_agent == "SALES_AGENT":
                return None
            return self._reply_from_orchestrator_document(
                message,
                session,
                dialogue,
                _CONVERSATIONAL_DOCUMENTS[intent],
                reason=f"conversational_{intent}",
                skill="common_phrases",
            )

        if (
            session.active_agent is not None
            or _explicit_agent_intent(message, self.skills) is not None
            or _vehicle_topic(message)
            or _budget_topic(message)
        ):
            return None

        chunks = self.rag.retrieve(message, "ORCHESTRATOR", top_k=6, min_score=0.08)
        allowed = self._orchestrator_faq_ids()
        matched = next((chunk for chunk in chunks if chunk.document.id in allowed), None)
        if matched is None:
            return None
        skill = (
            "safety_refusal"
            if matched.document.id.startswith("conversation-safety-")
            else "common_phrases"
        )
        reason = (
            "safety_illegal"
            if matched.document.id == "conversation-safety-illegal"
            else "safety_abuse"
            if matched.document.id == "conversation-safety-abuse"
            else "conversational_faq"
        )
        return self._reply_from_orchestrator_document(
            message,
            session,
            dialogue,
            matched.document.id,
            reason=reason,
            skill=skill,
        )

    def _handle_conversational_phrase(
        self,
        message: str,
        session: SessionState,
        dialogue: DialogueLogger,
    ) -> TurnResult | None:
        return self._handle_orchestrator_direct(message, session, dialogue)

    def handle_message(
        self,
        message: str,
        session_id: str | None = None,
        channel: str = "web",
        allowed_agents: set[str] | None = None,
    ) -> TurnResult:
        if self.orchestrator_mode == "legacy":
            return self._handle_message_legacy(message, session_id, channel, allowed_agents)

        session = self.get_or_create_session(session_id, channel=channel)
        dialogue = DialogueLogger(session.session_id)
        dialogue.log_user_message(message, channel=channel)
        try:
            output = self.graph.invoke({
                "message": message,
                "channel": channel,
                "allowed_agents": allowed_agents,
                "session": session,
                "dialogue": dialogue,
            })
            return output["result"]
        except PermissionError:
            raise
        except Exception:
            logger.exception("LangGraph turn failed session=%s", session.session_id)
            return self._safe_failure_result(message, session, channel)

    def _handle_message_legacy(
        self,
        message: str,
        session_id: str | None = None,
        channel: str = "web",
        allowed_agents: set[str] | None = None,
    ) -> TurnResult:
        session = self.get_or_create_session(session_id, channel=channel)
        dialogue = DialogueLogger(session.session_id)
        dialogue.log_user_message(message, channel=channel)

        conversational = self._handle_orchestrator_direct(message, session, dialogue)
        if conversational is not None:
            return conversational

        greeting: str | None = None
        routing_reason: str | None = None
        model_decision = self.model_router.decide(message, session.active_agent)

        if session.active_agent is None:
            routed = self.route(message, model_decision.model_tier or "simple")
            session.active_agent = model_decision.agent or routed["agent"]
            greeting = routed["greeting"]
            routing_reason = routed["reason"]
            dialogue.log_routing(
                agent=session.active_agent,
                reason=routing_reason,
                greeting=greeting,
            )

        if allowed_agents is not None and session.active_agent not in allowed_agents:
            session.active_agent = None
            denial = self._reply_from_orchestrator_document(
                message,
                session,
                dialogue,
                "conversation-staff-only",
                reason="staff_only",
                skill="staff_only",
            )
            if denial is not None:
                return denial
            raise PermissionError("agent requires an employee role")

        agent = self.agents[session.active_agent]
        agent_reply: AgentReply = agent.handle(
            message,
            history=session.history,
            dialogue=dialogue,
        )

        reply_text = agent_reply.text
        if greeting:
            reply_text = f"{greeting}\n\n{reply_text}"

        session.history.append({"role": "user", "content": message})
        session.history.append({"role": "assistant", "content": reply_text})
        self._persist(session)

        return TurnResult(
            session_id=session.session_id,
            channel=channel,
            agent=agent_reply.agent,
            agent_label=AGENT_META[agent_reply.agent]["label"],
            greeting=greeting,
            reply=reply_text,
            skill=agent_reply.skill,
            escalated=agent_reply.escalated,
            escalation_target=agent_reply.escalation_target,
            rag_ids=agent_reply.rag_ids,
            collected_fields=agent_reply.collected_fields,
            routing_reason=routing_reason,
            model_route="human" if agent_reply.escalated else model_decision.route,
            model_tier=model_decision.model_tier,
            routing_intent=model_decision.intent,
            routing_risk="high" if agent_reply.escalated else model_decision.risk,
        )
