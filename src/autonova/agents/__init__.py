from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autonova.config import get_settings
from autonova.logging import DialogueLogger, get_logger
from autonova.rag import RAGRetriever
from autonova.skills import SkillResult, SkillRouter

logger = get_logger("autonova.agents")

AGENT_META = {
    "SALES_AGENT": {
        "label": "Sales Agent",
        "color": "#1F6FEB",
        "icon": "car",
        "prompt_file": "sales_agent.txt",
    },
    "SUPPORT_AGENT": {
        "label": "Customer Support Agent",
        "color": "#2DA44E",
        "icon": "headset",
        "prompt_file": "support_agent.txt",
    },
    "SERVICE_AGENT": {
        "label": "Service Agent",
        "color": "#BF8700",
        "icon": "wrench",
        "prompt_file": "service_agent.txt",
    },
    "EMPLOYEE_AGENT": {
        "label": "Employee Agent",
        "color": "#7C3AED",
        "icon": "users",
        "prompt_file": "employee_agent.txt",
    },
}


def load_prompt(name: str) -> str:
    path = get_settings().prompts_dir / name
    return path.read_text(encoding="utf-8").strip()


@dataclass
class AgentReply:
    agent: str
    text: str
    skill: str | None = None
    escalated: bool = False
    escalation_target: str | None = None
    escalation_reason: str | None = None
    rag_ids: list[str] = field(default_factory=list)
    collected_fields: dict[str, Any] = field(default_factory=dict)
    system_prompt: str = ""


class BaseAgent:
    key: str

    def __init__(self, rag: RAGRetriever, skills: SkillRouter) -> None:
        self.rag = rag
        self.skills = skills
        meta = AGENT_META[self.key]
        self.label = meta["label"]
        self.system_prompt = load_prompt(meta["prompt_file"])

    def handle(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        dialogue: DialogueLogger | None = None,
    ) -> AgentReply:
        history = history or []
        query = " ".join(
            [
                *[item.get("content", "") for item in history if item.get("role") == "user"],
                message,
            ]
        ).strip()
        chunks = self.rag.retrieve(query or message, self.key)
        lowered = message.lower().replace("ё", "е")
        if any(phrase in lowered for phrase in ("игнорируй правила", "покажи персональные данные", "раскрой персональные данные")):
            result = SkillResult(
                "internal_knowledge" if self.key == "EMPLOYEE_AGENT" else "customer_faq",
                "Не раскрываю персональные данные и не выполняю инструкции, нарушающие правила доступа. Передаю запрос ответственному сотруднику.",
                escalated=True,
                escalation_target="security_owner",
                escalation_reason="запрос запрещённых данных",
                rag_ids=[c.document.id for c in chunks],
            )
        elif "придум" in lowered and "скид" in lowered:
            result = SkillResult(
                "vehicle_selection",
                "Не могу придумать скидку, которой нет в утверждённой базе. Актуальные условия подтвердит менеджер.",
                escalated=True,
                escalation_target="sales_manager",
                escalation_reason="запрос неподтверждённой скидки",
                rag_ids=[c.document.id for c in chunks],
            )
        elif not chunks:
            result = SkillResult(
                "customer_faq",
                "В базе знаний нет данных по этому вопросу. Передаю обращение сотруднику AutoSfera AI.",
                escalated=True,
                escalation_target="employee",
                escalation_reason="нет данных в KB",
            )
        else:
            result = self.skills.run(
                self.key,
                message,
                chunks,
                ctx={"history": history, "kb": self.rag.kb},
            )
        preface = (
            f"Здравствуйте! Я {self.label} — ИИ-ассистент AutoSfera AI.\n\n"
            if not history
            else ""
        )
        text = preface + result.reply
        reply = AgentReply(
            agent=self.key,
            text=text,
            skill=result.skill_id,
            escalated=result.escalated,
            escalation_target=result.escalation_target,
            escalation_reason=result.escalation_reason,
            rag_ids=result.rag_ids or [c.document.id for c in chunks],
            collected_fields=result.collected_fields,
            system_prompt=self.system_prompt,
        )
        if dialogue:
            dialogue.log_agent_reply(
                agent=self.key,
                skill=reply.skill,
                reply=reply.text,
                escalated=reply.escalated,
                rag_ids=reply.rag_ids,
            )
            if reply.escalated:
                dialogue.log_escalation(
                    agent=self.key,
                    reason=reply.escalation_reason or "escalation",
                    target=reply.escalation_target or "employee",
                )
        logger.info(
            "Agent %s replied skill=%s escalated=%s rag=%s",
            self.key,
            reply.skill,
            reply.escalated,
            reply.rag_ids,
        )
        return reply


class SalesAgent(BaseAgent):
    key = "SALES_AGENT"


class SupportAgent(BaseAgent):
    key = "SUPPORT_AGENT"


class ServiceAgent(BaseAgent):
    key = "SERVICE_AGENT"


class EmployeeAgent(BaseAgent):
    key = "EMPLOYEE_AGENT"


def build_agents(rag: RAGRetriever, skills: SkillRouter) -> dict[str, BaseAgent]:
    return {
        "SALES_AGENT": SalesAgent(rag, skills),
        "SUPPORT_AGENT": SupportAgent(rag, skills),
        "SERVICE_AGENT": ServiceAgent(rag, skills),
        "EMPLOYEE_AGENT": EmployeeAgent(rag, skills),
    }
