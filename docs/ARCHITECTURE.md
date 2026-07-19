# Архитектура AutoSfera AI

Стек: Python 3.11+, FastAPI, JSON Knowledge Base, TF-IDF RAG, Skills, SQLite (`dealer_id`), mock/OpenAI LLM.

Версия платформы: **2.0.0**.

## Поток запроса

1. Канал (`web` или stub) принимает сообщение.
2. Orchestrator при первом ходе выбирает агента (JSON от LLM или эвристика в `mock`).
3. Agent вызывает SkillRouter → Skill.
4. RAG достаёт фрагменты KB с учётом Least Privilege (`SECTION_ACCESS`).
5. Skill формирует ответ; диалог и эскалации пишутся в SQLite + JSONL.
6. Бизнес-заявки (`lead` / `test_drive` / `service`) сохраняются через `/api/requests`.

```
Пользователь (браузер)
        │
        ▼
  frontend/  →  POST /api/chat
        │
        ▼
  FastAPI (src/autonova/api)
        │
        ▼
  AI Orchestrator
        │
   ┌────┼──────────────┬────────────┐
   ▼    ▼              ▼            ▼
 Sales Support      Service     Employee
 Agent  Agent        Agent       Agent
   │      │             │            │
   └──────┴── Skills (16) ──────────┘
              │
              ▼
             RAG  →  Knowledge Base
              │
              ▼
     SQLite (conversations, requests) + logs/
```

## Skills (16)

| Agent | Skills |
|---|---|
| Sales | vehicle_selection, trade_in, credit_leasing, test_drive_booking |
| Support | order_status, documentation_support, customer_faq, support_escalation |
| Service | warranty_consultation, service_booking, maintenance_consultation, service_escalation |
| Employee | internal_knowledge, sales_coaching, process_lookup, manager_escalation |

## Хранение

- `data/autosfera.db` — диалоги и заявки, каждая строка с `dealer_id`
- `logs/autonova.log` — приложение
- `logs/dialogues.log` — диалоги
- `data/dialogues/<session_id>.jsonl` — события сессии

## API

- `POST /api/chat` — чат
- `POST /api/reset` — новый диалог
- `POST /api/requests` / `GET /api/requests` — бизнес-заявки
- `GET /api/analytics/summary` — сводка по салону
- `GET /api/knowledge` — KB
- `GET /api/skills` — список skills
- `GET /health` — статус, агенты, skills, dealer
- `POST /api/channels/{name}` — stub-каналы

Пилот: [`COMMERCIAL_PILOT.md`](COMMERCIAL_PILOT.md).  
Интеграционные примеры: `docs/integration_examples.json`.
