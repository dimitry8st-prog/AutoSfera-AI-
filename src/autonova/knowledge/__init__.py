from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        parts = [self.title, self.content, " ".join(self.tags), self.section]
        if self.agent:
            parts.append(self.agent)
        return " ".join(parts)


SECTION_ACCESS: dict[str, tuple[str, ...]] = {
    "SALES_AGENT": (
        "conversation",
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
        "conversation",
        "company",
        "customer_support",
        "faq",
        "scripts",
        "policies",
        "glossary",
        "legal",
    ),
    "SERVICE_AGENT": (
        "conversation",
        "company",
        "service",
        "faq",
        "scripts",
        "policies",
        "glossary",
        "legal",
    ),
    "EMPLOYEE_AGENT": (
        "conversation",
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
        "conversation",
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
                        metadata=_approved_metadata(section, item.get("metadata") or {}),
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
        return [
            d
            for d in self._documents
            if d.section in allowed and (d.agent is None or d.agent == agent_key)
        ]

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
                "metadata": _approved_metadata(
                    "internal",
                    {
                        "version": str(version),
                        "owner": "Исследования",
                        "status": "approved",
                        "source_type": "research",
                        "source_ref": job_id,
                    },
                ),
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
_SECTION_OWNERS = {
    "company": "Маркетинг",
    "sales": "Отдел продаж",
    "finance": "Финансы",
    "service": "Сервис",
    "customer_support": "Поддержка",
    "internal": "Операции",
    "faq": "База знаний",
    "scripts": "Отдел продаж",
    "policies": "Комплаенс",
    "legal": "Комплаенс",
    "glossary": "База знаний",
    "conversation": "База знаний",
}
_STOPWORDS = frozenset({
    "и", "в", "во", "на", "с", "со", "к", "ко", "по", "от", "до", "из", "за",
    "о", "об", "про", "для", "при", "над", "через", "а", "но", "да", "или",
    "же", "бы", "ли", "то", "это", "этот", "эта", "эти", "этой", "этого",
    "как", "какой", "какая", "какие", "какое", "сейчас", "сегодня", "завтра",
    "очень", "просто", "также", "там", "тут", "здесь", "уже", "еще", "ещё",
    "только", "чтобы", "когда", "если", "чем", "его", "ее", "её", "их",
    "мы", "вы", "он", "она", "они", "мне", "меня", "тебе", "тебя", "вам",
    "вас", "наш", "ваш", "все", "всего", "этом", "тем", "том", "быть",
    "есть", "был", "была", "было", "мои", "моя", "мое", "моё", "мой",
    "свою", "свой", "своя", "мне", "нам", "них", "этим", "этих",
})
_SUFFIXES = (
    "анная", "енная", "онная", "иями", "ями", "ами", "ого", "ему", "ому",
    "ыми", "ими", "иях", "иям", "ией", "ться", "тся", "ие", "ые", "ое",
    "ее", "ая", "яя", "ую", "юю", "ый", "ий", "ов", "ев", "ом", "ем",
    "ах", "ях", "ям", "ам", "ой", "ей", "ии", "ию", "ия", "ью", "ть",
    "у", "ю", "ы", "и", "а", "я", "е", "о", "ь",
)
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "трейд-ин": ("trade-in", "трейд", "обмен", "обменять", "доплат"),
    "трейд": ("trade-in", "трейд-ин", "обмен"),
    "trade-in": ("трейд-ин", "трейд", "обмен", "обменять"),
    "обмен": ("trade-in", "трейд-ин", "обменять", "доплат"),
    "обменя": ("обмен", "trade-in", "трейд-ин"),
    "обменять": ("обмен", "trade-in", "трейд-ин", "доплат"),
    "доплат": ("обмен", "trade-in", "трейд-ин"),
    "доплата": ("обмен", "trade-in", "трейд-ин"),
    "сдать": ("обмен", "trade-in", "трейд-ин"),
    "вернуть": ("возврат", "отмена"),
    "верн": ("возврат", "отмена"),
    "возврат": ("вернуть", "отмена"),
    "заказанн": ("заказ",),
    "заказанная": ("заказ",),
    "заказа": ("заказ",),
    "связаться": ("контакт", "телефон", "автосалон"),
    "связ": ("контакт", "телефон"),
    "автосалон": ("контакт", "салон"),
    "салон": ("автосалон", "контакт"),
    "кредит": ("автокредит", "банк"),
    "автокредит": ("кредит",),
    "кроссовер": ("drive",),
    "корпоративн": ("b2b", "юрлиц", "скрипт"),
    "корпоративным": ("b2b", "скрипт"),
    "юрлиц": ("b2b", "лизинг"),
    "скрипт": ("разговор",),
    "разговора": ("скрипт",),
    "общать": ("скрипт", "корпоративн"),
    "общаться": ("скрипт", "корпоративн"),
    "аргумент": ("скрипт", "подбор"),
    "подбор": ("скрипт", "модель"),
    "руководител": ("эскалац", "руководитель"),
    "руководителю": ("эскалац", "руководитель"),
    "передать": ("эскалац",),
    "персональн": ("пдн", "152", "политик"),
    "персональные": ("пдн", "152-фз"),
    "игнорир": ("политик", "безопасн", "персональн"),
    "придумай": ("выдумк", "скидк", "ограничен"),
    "секретн": ("скидк", "ограничен", "выдумк"),
    "скидк": ("скидка", "ограничен"),
    "скидка": ("ограничен", "выдумк"),
    "подтверди": ("гарант",),
    "записаться": ("запись", "тест-драйв"),
    "запис": ("запись",),
    "обслуживан": ("то", "регламент"),
    "обслуживание": ("то", "регламент"),
    "лизинг": ("юрлиц", "b2b"),
    "осмотра": ("гарант", "инженер"),
    "коррозия": ("кузов", "гарант"),
    "кузова": ("кузов", "гарант"),
}


def _approved_metadata(section: str, metadata: dict[str, Any]) -> dict[str, Any]:
    filled = dict(metadata)
    filled.setdefault("version", "2026-09-12")
    filled.setdefault("owner", _SECTION_OWNERS.get(section, "База знаний"))
    filled.setdefault("status", "approved")
    return filled


def stem_token(token: str) -> str:
    token = token.lower().replace("ё", "е")
    if len(token) <= 4:
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str, *, expand: bool = False) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        token = raw.lower().replace("ё", "е")
        if token in _STOPWORDS or token.isdigit():
            continue
        stemmed = stem_token(token)
        tokens.append(stemmed)
        if token != stemmed:
            tokens.append(token)
        if expand:
            tokens.extend(_SYNONYMS.get(token, ()))
            if stemmed != token:
                tokens.extend(_SYNONYMS.get(stemmed, ()))
    return tokens
