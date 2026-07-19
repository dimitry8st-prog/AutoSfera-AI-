from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from autonova.agents import AGENT_META, AgentReply, BaseAgent, build_agents, load_prompt
from autonova.knowledge import KnowledgeBase
from autonova.llm import LLMClient, extract_json_object, get_llm_client
from autonova.logging import DialogueLogger, get_logger, setup_logging
from autonova.rag import RAGRetriever
from autonova.skills import SkillRouter, build_skill_registry

logger = get_logger("autonova.orchestrator")


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
    routing_reason: str | None = None


class AIOrchestrator:
    """Entry point: intent routing + specialized agent execution."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        rag: RAGRetriever | None = None,
        skills: SkillRouter | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        setup_logging()
        self.kb = knowledge_base or KnowledgeBase()
        self.rag = rag or RAGRetriever(self.kb)
        self.skills = skills or SkillRouter(build_skill_registry())
        self.llm = llm or get_llm_client()
        self.agents: dict[str, BaseAgent] = build_agents(self.rag, self.skills)
        self.system_prompt = load_prompt("orchestrator.txt")
        self.sessions: dict[str, SessionState] = {}
        logger.info("AIOrchestrator ready with agents=%s", list(self.agents))

    def get_or_create_session(
        self,
        session_id: str | None = None,
        channel: str = "web",
    ) -> SessionState:
        sid = session_id or str(uuid4())
        if sid not in self.sessions:
            self.sessions[sid] = SessionState(session_id=sid, channel=channel)
            logger.info("Created session %s channel=%s", sid, channel)
        return self.sessions[sid]

    def reset_session(self, session_id: str) -> SessionState:
        channel = self.sessions.get(session_id, SessionState(session_id)).channel
        self.sessions[session_id] = SessionState(session_id=session_id, channel=channel)
        logger.info("Reset session %s", session_id)
        return self.sessions[session_id]

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

    def handle_message(
        self,
        message: str,
        session_id: str | None = None,
        channel: str = "web",
    ) -> TurnResult:
        session = self.get_or_create_session(session_id, channel=channel)
        dialogue = DialogueLogger(session.session_id)
        dialogue.log_user_message(message, channel=channel)

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
            routing_reason=routing_reason,
        )
