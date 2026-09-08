# Архитектура AutoSfera AI

Стек: Python 3.11+, FastAPI, LangGraph 1.2, JSON Knowledge Base, TF-IDF RAG, Skills, PostgreSQL/SQLite (`dealer_id`), mock/OpenAI LLM.

Версия платформы: **2.1.0**.

## Контуры доверия 2.1

- публичный пользователь видит только клиентские разделы KB и не может вызвать Employee Agent;
- сотрудники получают подписанный токен с `role` и `dealer_id`;
- n8n получает подписанный Job API payload и единолично вызывает Langflow;
- Langflow возвращает только черновик со ссылками на источники;
- публикация в версионируемую внутреннюю KB выполняется только после `approve` или `edit` сотрудником;
- CRM/DMS остаются источниками истины и не заменяются AutoSfera AI.

## Поток запроса

1. Канал (`web` или stub) принимает сообщение.
2. LangGraph распознаёт типовую фразу или определяет домен запроса.
3. Явная смена темы переключает агента; неоднозначное короткое уточнение остаётся у текущего агента.
4. `access_guard` проверяет, разрешён ли выбранный агент роли пользователя.
5. Agent вызывает SkillRouter → Skill, а RAG достаёт только разрешённые фрагменты KB.
6. `persist_turn` сохраняет активного агента и историю в PostgreSQL/SQLite; JSONL сохраняет аудит.
7. Бизнес-заявки (`lead` / `test_drive` / `service`) сохраняются через `/api/requests`.

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
  LangGraph Orchestrator
        │
   ┌────┼──────────────┬────────────┐
   ▼    ▼              ▼            ▼
 Sales Support      Service     Employee
 Agent  Agent        Agent       Agent
   │      │             │            │
   └──────┴── Skills (17) ──────────┘
              │
              ▼
             RAG  →  Knowledge Base
              │
              ▼
 PostgreSQL/SQLite (sessions, conversations, requests) + logs/
```

## Граф оркестрации

| Узел | Ответственность |
|---|---|
| `classify_conversation` | Приветствия, благодарности и другие типовые фразы из RAG |
| `route_agent` | Первый выбор агента, смена темы или продолжение текущего контекста |
| `access_guard` | Проверка роли и запрет доступа к Employee Agent для гостя |
| `execute_agent` | Запуск специализированного агента, Skill и RAG |
| `persist_turn` | Формирование результата и сохранение сессии |

Если граф аварийно завершается, система не выдумывает ответ: возвращает безопасное сообщение и эскалирует обращение человеку. Режим `ORCHESTRATOR_MODE=legacy` оставлен как операционный rollback.

## Skills (17)

| Agent | Skills |
|---|---|
| Sales | vehicle_selection, trade_in, credit_leasing, test_drive_booking |
| Support | order_status, documentation_support, customer_faq, support_escalation |
| Service | warranty_consultation, service_booking, maintenance_consultation, service_escalation |
| Employee | internal_knowledge, sales_coaching, process_lookup, manager_escalation, competitor_research |

## Хранение

- PostgreSQL в контейнерном/боевом контуре; SQLite — локальный резервный режим
- активный агент и история LangGraph-сессии сохраняются с изоляцией по `dealer_id`
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
