from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from autonova.logging import get_logger
from autonova.orchestrator import AIOrchestrator, TurnResult

logger = get_logger("autonova.channels")


class ChannelAdapter(ABC):
    name: str

    def __init__(self, orchestrator: AIOrchestrator) -> None:
        self.orchestrator = orchestrator

    @abstractmethod
    def receive(self, payload: dict[str, Any]) -> TurnResult:
        raise NotImplementedError


class WebChannel(ChannelAdapter):
    name = "web"

    def receive(self, payload: dict[str, Any]) -> TurnResult:
        message = str(payload.get("message", "")).strip()
        session_id = payload.get("session_id")
        if not message:
            raise ValueError("message is required")
        logger.info("WebChannel message session=%s", session_id)
        return self.orchestrator.handle_message(
            message=message,
            session_id=session_id,
            channel=self.name,
        )


class TelegramChannel(ChannelAdapter):
    """Stub adapter — architecture ready for Bot API webhook."""

    name = "telegram"

    def receive(self, payload: dict[str, Any]) -> TurnResult:
        message = str(payload.get("text") or payload.get("message", "")).strip()
        session_id = str(payload.get("chat_id") or payload.get("session_id"))
        logger.info("TelegramChannel stub chat_id=%s", session_id)
        return self.orchestrator.handle_message(
            message=message,
            session_id=session_id,
            channel=self.name,
        )


class WhatsAppChannel(ChannelAdapter):
    name = "whatsapp"

    def receive(self, payload: dict[str, Any]) -> TurnResult:
        message = str(payload.get("text") or payload.get("message", "")).strip()
        session_id = str(payload.get("from") or payload.get("session_id"))
        return self.orchestrator.handle_message(
            message=message,
            session_id=session_id,
            channel=self.name,
        )


class EmailChannel(ChannelAdapter):
    name = "email"

    def receive(self, payload: dict[str, Any]) -> TurnResult:
        message = str(payload.get("body") or payload.get("message", "")).strip()
        session_id = str(payload.get("message_id") or payload.get("session_id"))
        return self.orchestrator.handle_message(
            message=message,
            session_id=session_id,
            channel=self.name,
        )


class CRMChannel(ChannelAdapter):
    name = "crm"

    def receive(self, payload: dict[str, Any]) -> TurnResult:
        message = str(payload.get("note") or payload.get("message", "")).strip()
        session_id = str(payload.get("ticket_id") or payload.get("session_id"))
        return self.orchestrator.handle_message(
            message=message,
            session_id=session_id,
            channel=self.name,
        )


def build_channels(orchestrator: AIOrchestrator) -> dict[str, ChannelAdapter]:
    channels: list[ChannelAdapter] = [
        WebChannel(orchestrator),
        TelegramChannel(orchestrator),
        WhatsAppChannel(orchestrator),
        EmailChannel(orchestrator),
        CRMChannel(orchestrator),
    ]
    return {c.name: c for c in channels}
