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
    }),
}

_CONVERSATIONAL_DOCUMENTS = {
    "greeting": "conversation-greeting",
    "thanks": "conversation-thanks",
    "farewell": "conversation-farewell",
    "wellbeing": "conversation-wellbeing",
    "identity": "conversation-identity",
    "capabilities": "conversation-capabilities",
}


def _normalize_conversational_phrase(message: str) -> str:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", message.lower())
    return " ".join(words)


def _conversational_intent(message: str) -> str | None:
    normalized = _normalize_conversational_phrase(message)
    for intent, phrases in _CONVERSATIONAL_PHRASES.items():
        if normalized in phrases:
            return intent
    return None


_AGENT_INTENT_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EMPLOYEE_AGENT", (
        "сотрудник", "внутренн", "регламент", "скрипт продаж", "эскалац",
        "руководител", "отчёт", "отчет", "kpi", "конкурент", "исследуй",
        "анализ рынка",
    )),
    ("SALES_AGENT", (
        "купить", "кроссовер", "седан", "кредит", "лизинг", "trade",
        "тест-драйв", "nova", "b2b", "юридическ",
    )),
    ("SUPPORT_AGENT", ("заказ", "ан-2024", "документ", "статус", "возврат", "инн")),
    ("SERVICE_AGENT", (
        "гарант", "сервис", "ремонт", "масло", "диагност", "техобслуж",
        "обслуживан", "лкп",
    )),
)


def _explicit_agent_intent(message: str) -> str | None:
    """Return an agent only when a message contains a clear domain signal."""
    lowered = message.lower()
    for agent, keys in _AGENT_INTENT_KEYS:
        if any(key in lowered for key in keys):
            return agent
    if re.search(r"(?<![а-яa-z])то(?![а-яa-z])", lowered):
        return "SERVICE_AGENT"
    return None


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
        self.llm = llm or get_llm_client()
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

    def route(self, message: str) -> dict[str, str]:
        raw = self.llm.complete(
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
        logger.info("Routed to %s reason=%s", result["agent"], result["reason"])
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
        builder.add_edge("access_guard", "execute_agent")
        builder.add_edge("execute_agent", "persist_turn")
        builder.add_edge("persist_turn", END)
        return builder.compile()

    def _graph_classify_conversation(
        self, state: OrchestratorGraphState
    ) -> OrchestratorGraphState:
        result = self._handle_conversational_phrase(
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
        explicit_agent = _explicit_agent_intent(state["message"])
        should_route = session.active_agent is None or (
            explicit_agent is not None and explicit_agent != session.active_agent
        )
        if not should_route:
            return {
                "selected_agent": session.active_agent,
                "greeting": None,
                "routing_reason": "session_continuity",
            }

        routed = self.route(state["message"])
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
        }

    def _graph_access_guard(self, state: OrchestratorGraphState) -> OrchestratorGraphState:
        selected = state["selected_agent"]
        allowed_agents = state.get("allowed_agents")
        if allowed_agents is not None and selected not in allowed_agents:
            state["session"].active_agent = None
            self._persist(state["session"])
            raise PermissionError(f"agent {selected} requires an employee role")
        return {}

    def _graph_execute_agent(self, state: OrchestratorGraphState) -> OrchestratorGraphState:
        message = state["message"]
        # Give Skills/RAG the missing subject of a short follow-up without exposing
        # internal graph state in the user-visible reply.
        if (
            state.get("routing_reason") == "session_continuity"
            and _explicit_agent_intent(message) is None
            and len(_normalize_conversational_phrase(message).split()) <= 8
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
        )

    def _handle_conversational_phrase(
        self,
        message: str,
        session: SessionState,
        dialogue: DialogueLogger,
    ) -> TurnResult | None:
        intent = _conversational_intent(message)
        if intent is None:
            return None

        expected_id = _CONVERSATIONAL_DOCUMENTS[intent]
        chunks = self.rag.retrieve(message, "ORCHESTRATOR", top_k=6, min_score=0.01)
        matched = next((chunk for chunk in chunks if chunk.document.id == expected_id), None)
        if matched is None:
            logger.warning("Conversation KB document %s was not retrieved", expected_id)
            return None

        reply_text = matched.document.content.strip()
        rag_ids = [matched.document.id]
        dialogue.log_routing(
            agent="AI_ORCHESTRATOR",
            reason=f"conversational_{intent}",
            greeting="",
        )
        dialogue.log_agent_reply(
            agent="AI_ORCHESTRATOR",
            skill="common_phrases",
            reply=reply_text,
            escalated=False,
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
            skill="common_phrases",
            escalated=False,
            escalation_target=None,
            rag_ids=rag_ids,
            routing_reason=f"conversational_{intent}",
        )

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

        conversational = self._handle_conversational_phrase(message, session, dialogue)
        if conversational is not None:
            return conversational

        greeting: str | None = None
        routing_reason: str | None = None

        if session.active_agent is None:
            routed = self.route(message)
            session.active_agent = routed["agent"]
            greeting = routed["greeting"]
            routing_reason = routed["reason"]
            dialogue.log_routing(
                agent=session.active_agent,
                reason=routing_reason,
                greeting=greeting,
            )

        if allowed_agents is not None and session.active_agent not in allowed_agents:
            denied_agent = session.active_agent
            session.active_agent = None
            self._persist(session)
            raise PermissionError(f"agent {denied_agent} requires an employee role")

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
        )
