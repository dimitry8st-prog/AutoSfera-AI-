# CLAUDE.md

Guidance for working in this repository.

## Repository purpose

**AutoSfera AI** is a commercial MVP multi-agent platform for a single car dealership (Python package name remains `autonova` for compatibility). Stack: Python 3.11+, FastAPI, JSON Knowledge Base, TF-IDF RAG, SQLite storage, mock/OpenAI LLM, web chat.

Public product name: AutoSfera AI. Technical package: `autonova`.

## What the system does

1. Accepts a user message via web chat or HTTP API.
2. **AI Orchestrator** routes the first turn to one of four agents.
3. The selected agent picks a **Skill**, retrieves KB fragments via **RAG** (Least Privilege by agent), and returns a reply.
4. Persist conversations and business requests (leads, test drives, service) in SQLite scoped by `dealer_id`.
5. Escalate to a human when facts are missing or the decision is critical.

Agents and skills (16 total):

| Agent | Focus | Skills |
|---|---|---|
| Sales | Purchase / finance | vehicle_selection, trade_in, credit_leasing, test_drive_booking |
| Support | Orders / docs | order_status, documentation_support, customer_faq, support_escalation |
| Service | Warranty / TO | warranty_consultation, service_booking, maintenance_consultation, service_escalation |
| Employee | Internal ops | internal_knowledge, sales_coaching, process_lookup, manager_escalation |

## Key behavioral rules

- **No fabrication.** Answers must come from the Knowledge Base / skills; otherwise escalate or say data is missing.
- **Least Privilege.** Each agent only sees allowed KB sections (`SECTION_ACCESS` in `src/autonova/knowledge/`).
- **Dealer isolation.** Every stored conversation and request includes `dealer_id` (pilot default: `main-salon`).
- **Safe defaults.** `LLM_MODE=mock` works offline without an API key.
- **No side effects beyond the app.** Do not invent live CRM, real payments, or confirmed warranty cases.

## Working in this repo

```bash
python -m pip install -e ".[dev]"
pytest -q
uvicorn autonova.api.main:app --reload --app-dir src
```

- Entrypoint: `src/autonova/api/main.py`
- Prompts: `prompts/`
- KB: `knowledge_base/`
- Spec: `docs/COMMERCIAL_PILOT.md`, architecture: `docs/ARCHITECTURE.md`
- Keep `app_version` / `pyproject.toml` / package `__version__` aligned (current: **2.0.0**).
- Do not commit `.env`, `*.db`, or dialogue logs.
