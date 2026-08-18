from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def publish_approved(
        self,
        *,
        job_id: str,
        title: str,
        content: str,
        sources: list[dict[str, Any]],
    ) -> tuple[Document, int]:
        """Publish a reviewed research result as a versioned internal KB document."""
        approved_dir = self.root / "approved"
        approved_dir.mkdir(parents=True, exist_ok=True)
        safe_job_id = re.sub(r"[^a-zA-Z0-9-]", "", job_id)
        existing = sorted(approved_dir.glob(f"{safe_job_id}.v*.json"))
        version = len(existing) + 1
        doc_id = f"research-{safe_job_id}-v{version}"
        citations = "\n".join(
            f"- {source.get('title') or source.get('url')}: {source.get('url')}"
            for source in sources
            if source.get("url")
        )
        full_content = content.strip()
        if citations:
            full_content += f"\n\nИсточники:\n{citations}"
        payload = {
            "section": "internal",
            "documents": [{
                "id": doc_id,
                "title": title.strip() or "Исследование конкурента",
                "content": full_content,
                "tags": ["competitor_research", "approved", f"version:{version}"],
                "agent": "EMPLOYEE_AGENT",
            }],
        }
        target = approved_dir / f"{safe_job_id}.v{version}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        self.reload()
        document = self.get(doc_id)
        if document is None:
            raise RuntimeError("approved document was not loaded")
        return document, version


_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9\-]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]
