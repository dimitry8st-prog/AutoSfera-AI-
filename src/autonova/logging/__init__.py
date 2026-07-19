from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import uuid4

from autonova.config import get_settings


_configured = False


def setup_logging(level: str | None = None) -> logging.Logger:
    """Configure application and dialogue loggers once."""
    global _configured
    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.dialogues_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("autonova")
    if _configured:
        return root

    log_level = getattr(logging, (level or settings.log_level).upper(), logging.INFO)
    root.setLevel(log_level)
    root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(log_level)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.logs_dir / "autonova.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    root.addHandler(file_handler)

    dialogue_handler = RotatingFileHandler(
        settings.logs_dir / "dialogues.log",
        maxBytes=2_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    dialogue_handler.setFormatter(formatter)
    dialogue_handler.setLevel(logging.INFO)

    dialogue_logger = logging.getLogger("autonova.dialogues")
    dialogue_logger.setLevel(logging.INFO)
    dialogue_logger.handlers.clear()
    dialogue_logger.addHandler(dialogue_handler)
    dialogue_logger.addHandler(console)
    dialogue_logger.propagate = False

    _configured = True
    root.info("Logging configured (level=%s)", logging.getLevelName(log_level))
    return root


def get_logger(name: str = "autonova") -> logging.Logger:
    if not _configured:
        setup_logging()
    return logging.getLogger(name)


class DialogueLogger:
    """Persists dialogue turns as JSONL and structured log lines."""

    def __init__(self, session_id: str | None = None) -> None:
        settings = get_settings()
        settings.dialogues_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or str(uuid4())
        self.path = settings.dialogues_dir / f"{self.session_id}.jsonl"
        self._logger = get_logger("autonova.dialogues")

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event_type,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._logger.info(
            "session=%s event=%s payload=%s",
            self.session_id,
            event_type,
            json.dumps(payload, ensure_ascii=False),
        )

    def log_user_message(self, text: str, channel: str) -> None:
        self.log_event("user_message", {"channel": channel, "text": text})

    def log_routing(self, agent: str, reason: str, greeting: str) -> None:
        self.log_event(
            "routing",
            {"agent": agent, "reason": reason, "greeting": greeting},
        )

    def log_agent_reply(
        self,
        agent: str,
        skill: str | None,
        reply: str,
        escalated: bool,
        rag_ids: list[str],
    ) -> None:
        self.log_event(
            "agent_reply",
            {
                "agent": agent,
                "skill": skill,
                "reply": reply,
                "escalated": escalated,
                "rag_document_ids": rag_ids,
            },
        )

    def log_escalation(self, agent: str, reason: str, target: str) -> None:
        self.log_event(
            "escalation",
            {"agent": agent, "reason": reason, "target": target},
        )
