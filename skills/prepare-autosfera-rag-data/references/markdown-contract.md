# AutoSfera canonical Markdown contract

Each knowledge document is one UTF-8 `.md` file with frontmatter followed by structured Markdown.

## Required fields

```markdown
---
id: sales-nova-drive-2026
title: "Nova Drive: комплектации и цены"
section: sales
tags: ["catalog", "vehicle"]
agent: SALES_AGENT
source_type: pdf
source_ref: "approved/catalog-2026-09.pdf"
version: "2026-09"
effective_date: "2026-09-01"
owner: "Отдел продаж"
status: approved
---

## Назначение

...
```

Use lowercase ASCII IDs with hyphens. `tags` must be a JSON-compatible string array. Quote values containing punctuation.

Statuses are `approved`, `draft`, `needs_review`, and `rejected`. Only `approved` is eligible for compilation.

Allowed sections: `company`, `sales`, `customer_support`, `service`, `finance`, `internal`, `legal`, `faq`, `scripts`, `policies`, `glossary`.

Allowed agents: `SALES_AGENT`, `SERVICE_AGENT`, `SUPPORT_AGENT`, `EMPLOYEE_AGENT`. Omit `agent` only when the document is intentionally shared through section access rules.

## Content rules

- Preserve conditions, exceptions, dates, currencies, units, and responsible roles.
- Prefer short topical sections and explicit lists over long unbroken paragraphs.
- Convert tables only when headers and row relationships are retained.
- Add `[НЕРАЗБОРЧИВО]` for uncertain OCR; never guess missing text.
- Put unresolved contradictions in the validation report, not in an authoritative answer.
- Keep citations or source anchors near claims when the source supplies them.

## Generated JSON shape

```json
{
  "section": "sales",
  "documents": [{
    "id": "sales-nova-drive-2026",
    "title": "Nova Drive: комплектации и цены",
    "content": "## Назначение\n\n...",
    "tags": ["catalog", "vehicle"],
    "agent": "SALES_AGENT"
  }]
}
```
