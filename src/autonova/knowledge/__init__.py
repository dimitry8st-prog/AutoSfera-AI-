from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from autonova.config import get_settings
from autonova.logging import get_logger

logger = get_logger("autonova.knowledge")


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    section: str
    content: str
    tags: tuple[str, ...]
    agent: str | None = None

    @property
    def searchable_text(self) -> str:
        parts = [self.title, self.content, " ".join(self.tags), self.section]
        if self.agent:
            parts.append(self.agent)
        return " ".join(parts)


SECTION_ACCESS: dict[str, tuple[str, ...]] = {
    "SALES_AGENT": (
        "company",
        "sales",
        "finance",
        "faq",
        "scripts",
        "policies",
        "glossary",
        "legal",
    ),
    "SUPPORT_AGENT": (
        "company",
        "customer_support",
        "faq",
        "scripts",
        "policies",
        "glossary",
        "legal",
    ),
    "SERVICE_AGENT": (
        "company",
        "service",
        "faq",
        "scripts",
        "policies",
        "glossary",
        "legal",
    ),
    "EMPLOYEE_AGENT": (
        "company",
        "sales",
        "customer_support",
        "service",
        "finance",
        "internal",
        "faq",
        "scripts",
        "policies",
        "glossary",
        "legal",
    ),
    "ORCHESTRATOR": (
        "company",
        "glossary",
        "policies",
        "scripts",
    ),
}


class KnowledgeBase:
    """Loads JSON knowledge sections from disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or get_settings().knowledge_base_dir)
        self._documents: list[Document] = []
        self.reload()

    def reload(self) -> None:
        docs: list[Document] = []
        if not self.root.exists():
            raise FileNotFoundError(f"Knowledge base not found: {self.root}")

        for path in sorted(self.root.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            section = payload.get("section") or path.parent.name
            for item in payload.get("documents", []):
                docs.append(
                    Document(
                        id=item["id"],
                        title=item["title"],
                        section=section,
                        content=item["content"],
                        tags=tuple(item.get("tags", [])),
                        agent=item.get("agent"),
                    )
                )
        self._documents = docs
        logger.info("Loaded %s KB documents from %s", len(docs), self.root)

    @property
    def documents(self) -> list[Document]:
        return list(self._documents)

    def by_section(self, section: str) -> list[Document]:
        return [d for d in self._documents if d.section == section]

    def for_agent(self, agent_key: str) -> list[Document]:
        allowed = SECTION_ACCESS.get(agent_key, ())
        return [d for d in self._documents if d.section in allowed]

    def get(self, doc_id: str) -> Document | None:
        for doc in self._documents:
            if doc.id == doc_id:
                return doc
        return None


_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9\-]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]
