# AutoSfera AI — единый интеллект автодилера

> **Проект подготовлен для участия в OpenAI Build Week 2026 — глобальном хакатоне по созданию решений с Codex и GPT-5.6.**

Коммерческий демо-пилот для одного автосалона с архитектурой, готовой к масштабированию на дилерскую сеть. Версия **2.1.0** добавляет роли, постоянные сессии, кабинет менеджера и защищённый контур исследований с обязательным подтверждением человеком.

Актуальная спецификация пилота: [`docs/COMMERCIAL_PILOT.md`](docs/COMMERCIAL_PILOT.md).

> Пакет Python пока сохраняет техническое имя `autonova`, чтобы не ломать существующие интеграции. Публичный продукт и API называются AutoSfera AI.

## Возможности версии 2.0

- 4 агента и 17 skills: продажи, поддержка, сервис, внутренний помощник и исследование конкурентов;
- сохранение диалогов, лидов, тест-драйвов и сервисных заявок;
- API `/api/requests` и `/api/analytics/summary`;
- конфигурация одного салона через `DEALER_ID` и `DEALER_NAME`;
- изоляция всех бизнес-данных по `dealer_id` для будущих филиалов;
- Web-чат и каркас внешних каналов;
- полностью офлайн mock-режим для демонстрации без API-ключа.

---

## Архивная документация MVP 1.1

Учебный проект: автоматизация клиентских обращений вымышленной автомобильной компании **AutoNova** с помощью AI Orchestrator, трёх специализированных агентов, Skills, Knowledge Base и RAG.

Версия MVP: **1.1** · Стек: **Python 3.11+**, **FastAPI**, JSON KB, TF-IDF RAG, веб-чат  
Все цены, заказы и контакты — **тестовые (вымышленные)**.

---

## Содержание

1. [О проекте](#о-проекте)
2. [Что реализовано](#что-реализовано)
3. [Архитектура](#архитектура)
4. [Требования](#требования)
5. [Установка и запуск](#установка-и-запуск)
6. [Конфигурация](#конфигурация)
7. [Веб-интерфейс](#веб-интерфейс)
8. [HTTP API](#http-api)
9. [Агенты и Skills](#агенты-и-skills)
10. [Knowledge Base и RAG](#knowledge-base-и-rag)
11. [Логирование](#логирование)
12. [Тесты](#тесты)
13. [Демо-сценарии](#демо-сценарии)
14. [Структура репозитория](#структура-репозитория)
15. [Ограничения](#ограничения)
16. [Документация](#документация)

---

## О проекте

Система принимает сообщение пользователя, определяет намерение через **AI Orchestrator**, передаёт диалог одному из агентов и отвечает на основе фрагментов **Knowledge Base** (через RAG) и выбранного **Skill**.

Типовые задачи:

- подбор автомобиля, кредит / лизинг, Trade-in, тест-драйв;
- статус заказа, документы, FAQ поддержки;
- гарантия, ТО, запись в сервис;
- эскалация сотруднику, если данных нет или решение критическое.

Проект подготовлен по учебному ТЗ и готов к адаптации под GPTs / OpenAI-compatible API / no-code (через JSON API).

---

## Что реализовано

| Компонент | Статус |
|---|---|
| AI Orchestrator (маршрутизация) | ✅ |
| Sales / Support / Service / Employee Agents | ✅ |
| 17 Skills (4 клиентских набора + `competitor_research`) | ✅ |
| System Prompts (`prompts/`) | ✅ |
| Knowledge Base (JSON, в т.ч. internal) | ✅ |
| RAG (TF-IDF, без внешней vector DB) | ✅ |
| SQLite: диалоги и заявки по `dealer_id` | ✅ |
| API заявок и аналитики | ✅ |
| Веб-чат, quick replies, просмотр KB | ✅ |
| Логирование (файл + JSONL сессий) | ✅ |
| pytest-покрытие ядра, API и storage | ✅ |
| Каналы Telegram / WhatsApp / Email / CRM | 🟡 каркас API без внешних Bot API |
| Подписанные токены и роли `admin` / `employee` | ✅ |
| Постоянные сессии и кабинет заявок | ✅ |
| Защищённый Job API n8n/Langflow + human approval | ✅ |
| Live CRM/DMS и vector DB | ❌ вне демо-пилота |

Соответствие пилоту: оркестратор, 4 агента, 17 Skills, KB, RAG, заявки, аналитика, роли, изоляция `dealer_id`, эскалации и Least Privilege.

---

## Архитектура

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
  Channel Adapter (web / stubs)
        │
        ▼
  AI Orchestrator  ── первое сообщение: выбор агента
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
     SQLite + logs/ + data/dialogues/*.jsonl
     (при необходимости — эскалация сотруднику)
```

**Как работает сессия**

1. Первое сообщение → Orchestrator возвращает агента (`SALES_AGENT` | `SUPPORT_AGENT` | `SERVICE_AGENT` | `EMPLOYEE_AGENT`).
2. Дальнейшие сообщения в той же `session_id` обрабатывает выбранный агент.
3. Состояние сессии сохраняется в SQLite и восстанавливается после перезапуска.
4. «Новый чат» / `POST /api/reset` сбрасывает активного агента и историю.

LLM по умолчанию: **`LLM_MODE=mock`** (офлайн, без ключа). Опционально — OpenAI-compatible Chat Completions.

---

## Требования

- Python **3.11+** (проверено на 3.12)
- pip
- ОС: Windows / macOS / Linux

Зависимости описаны в `pyproject.toml` (`fastapi`, `uvicorn`, `pydantic`, `httpx`, `pytest` для dev).

---

## Установка и запуск

```bash
# из корня репозитория AutoNova
python -m pip install -e ".[dev]"

# тесты
pytest -q

# сервер
uvicorn autonova.api.main:app --reload --app-dir src
```

Откройте: **http://127.0.0.1:8000**

Проверка здоровья:

```bash
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ содержит `"status":"ok"`, четыре агента, `"skills":17`, `"version":"2.1.0"`, `dealer_id` и число документов KB.

---

## Конфигурация

Скопируйте пример окружения:

```bash
cp .env.example .env
```

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DEALER_ID` | `main-salon` | идентификатор салона (изоляция данных) |
| `DEALER_NAME` | `AutoSfera Demo Salon` | название салона |
| `DATABASE_PATH` | `data/autosfera.db` | путь к SQLite |
| `LLM_MODE` | `mock` | `mock` или `openai` |
| `OPENAI_API_KEY` | — | ключ для режима `openai` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | совместимый endpoint |
| `OPENAI_MODEL` | `gpt-4o-mini` | модель Chat Completions |
| `LOG_LEVEL` | `INFO` | уровень логов |
| `LOGS_DIR` | `logs/` | каталог логов |
| `DIALOGUES_DIR` | `data/dialogues/` | JSONL диалогов |
| `AUTH_SECRET` | demo-only | подпись JWT; обязательно заменить перед публикацией |
| `DEMO_ADMIN_PASSWORD` | `admin-demo` | локальный вход администратора без `.env` |
| `DEMO_EMPLOYEE_PASSWORD` | `employee-demo` | локальный вход сотрудника без `.env` |
| `DEMO_SALES_PASSWORD` | `sales-demo` | локальный вход менеджера продаж без `.env` |
| `DEMO_SERVICE_PASSWORD` | `service-demo` | локальный вход сервиса без `.env` |
| `CORS_ORIGINS` | localhost | разрешённые источники через запятую |
| `RESEARCH_WEBHOOK_URL` | — | защищённый webhook n8n |
| `RESEARCH_WEBHOOK_SECRET` | demo-only | HMAC-подпись запросов и callback |

Пример `.env` для реального LLM:

```env
DEALER_ID=main-salon
DEALER_NAME=AutoSfera Demo Salon
LLM_MODE=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
LOG_LEVEL=INFO
```

Настройки также читаются из `src/autonova/config.py` (пути к KB и prompts).

---

## Веб-интерфейс

Страница `frontend/` отдаётся с `/`:

- чат с индикатором агента;
- quick replies (кроссовер, статус заказа, гарантия, лизинг B2B);
- кнопка **Новый чат**;
- панель **База знаний** (`GET /api/knowledge`);
- дисклеймер: пользователь общается с ИИ.

`session_id` сохраняется в `localStorage` браузера до сброса.

---

## HTTP API

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | веб-чат |
| `GET` | `/health` | статус, агенты, skills, dealer, размер KB |
| `GET` | `/api/agents` | метаданные агентов |
| `GET` | `/api/skills` | список 17 skills |
| `GET` | `/api/knowledge` | публичные разделы KB; внутренние — только сотрудникам |
| `POST` | `/api/chat` | основное сообщение чата |
| `POST` | `/api/reset` | сброс сессии |
| `POST` | `/api/requests` | создать лид / тест-драйв / сервисную заявку |
| `POST` | `/api/auth/token` | локальный демонстрационный вход сотрудника |
| `GET/PATCH` | `/api/requests` | защищённая воронка заявок текущего салона |
| `GET` | `/api/analytics/summary` | защищённая сводка салона |
| `POST/GET` | `/api/research/jobs` | асинхронные исследования с идемпотентностью |
| `POST` | `/api/research/callback` | подписанный callback n8n |
| `POST` | `/api/research/jobs/{id}/review` | approve/edit/reject перед публикацией в KB |
| `POST` | `/api/channels/{name}` | защищённые stub-каналы интеграций |

### Пример: чат

**Запрос**

```http
POST /api/chat
Content-Type: application/json

{
  "message": "Хочу купить кроссовер",
  "session_id": null,
  "channel": "web"
}
```

**Ответ (поля)**

| Поле | Смысл |
|---|---|
| `session_id` | id сессии (передавать в следующих сообщениях) |
| `agent` / `agent_label` | выбранный агент |
| `greeting` | приветствие оркестратора (только на первом ходе) |
| `reply` | текст ответа |
| `skill` | сработавший skill |
| `escalated` / `escalation_target` | нужна ли передача сотруднику |
| `rag_ids` | id документов KB, использованных в ответе |
| `routing_reason` | причина маршрутизации (на первом ходе) |

Дополнительные JSON-примеры: [`docs/integration_examples.json`](docs/integration_examples.json).

Интерактивная схема FastAPI: http://127.0.0.1:8000/docs

---

## Агенты и Skills

### AI Orchestrator

Промпт: `prompts/orchestrator.txt`  
Роль: определить намерение и выбрать агента. В mock-режиме маршрутизация эвристическая; в `openai` — через LLM (строго JSON).

### Sales Agent — покупка и финансы

| Skill ID | Название | Примеры тем |
|---|---|---|
| `vehicle_selection` | Vehicle Selection | подбор модели / комплектации |
| `trade_in` | Trade-In | обмен авто |
| `credit_leasing` | Credit & Leasing | кредит, лизинг B2B |
| `test_drive_booking` | Test Drive Booking | запись на тест-драйв |

Промпт: `prompts/sales_agent.txt`

### Customer Support Agent — заказы и документы

| Skill ID | Название | Примеры тем |
|---|---|---|
| `order_status` | Order Status | АН-2024-0512 / 0388 |
| `documentation_support` | Documentation Support | паспорт, ИНН, справки |
| `customer_faq` | Customer FAQ | типовые вопросы |
| `support_escalation` | Support Escalation | запрос человека / специалиста |

Промпт: `prompts/support_agent.txt`

### Service Agent — сервис и гарантия

| Skill ID | Название | Примеры тем |
|---|---|---|
| `warranty_consultation` | Warranty Consultation | гарантия кузова / ЛКП |
| `service_booking` | Service Booking | запись в сервис |
| `maintenance_consultation` | Maintenance Consultation | ТО, эксплуатация |
| `service_escalation` | Service Escalation | инженер / гарантийный случай |

Промпт: `prompts/service_agent.txt`

### Employee Agent — внутренний помощник

| Skill ID | Название | Примеры тем |
|---|---|---|
| `internal_knowledge` | Internal Knowledge | регламенты, внутренние процессы |
| `sales_coaching` | Sales Coaching | скрипты продаж, подсказки менеджеру |
| `process_lookup` | Process Lookup | операционные процедуры |
| `manager_escalation` | Manager Escalation | передача руководителю |
| `competitor_research` | Competitor Research | защищённое исследование через n8n/Langflow |

Промпт: `prompts/employee_agent.txt`

**Ограничения агентов (заложены в промпты и skills):** не выдумывать факты вне KB; не подтверждать гарантийный случай; не принимать финансовые/юридические решения; не менять ПДн; при критике — эскалация.

---

## Knowledge Base и RAG

### Разделы KB (`knowledge_base/`)

| Раздел | Содержание |
|---|---|
| `company` | о компании, ИИ-дисклеймер, контакты |
| `sales` | модели, Trade-in, тест-драйв, B2B |
| `customer_support` | заказы, документы, возврат |
| `service` | гарантия, ТО, запись |
| `finance` | кредит, лизинг |
| `internal` | внутренние операции (Employee Agent) |
| `legal` | ограничения, 152-ФЗ (учебный контур) |
| `faq` | FAQ по агентам |
| `scripts` | скрипты общения |
| `policies` | эскалация, безопасность ответов |
| `glossary` | термины |

Доступ агентов к разделам ограничен (**Least Privilege**) в `src/autonova/knowledge/__init__.py` → `SECTION_ACCESS`.

### RAG

Реализация: `src/autonova/rag/` — TF-IDF + cosine similarity по токенам (учебная эмуляция retrieval без Pinecone/Weaviate/pgvector).

- `rag_top_k` по умолчанию: **6**
- в ответы skills попадают в основном фактовые разделы (не «шум» scripts/policies)
- при отсутствии данных пользователь уведомляется, возможна эскалация

---

## Логирование

| Куда | Что |
|---|---|
| `logs/autonova.log` | системные события приложения |
| `logs/dialogues.log` | ход диалогов (routing, reply, escalation) |
| `data/dialogues/<session_id>.jsonl` | события сессии построчно (JSONL) |

Типы событий JSONL: `user_message`, `routing`, `agent_reply`, `escalation`.

---

## Тесты

```bash
pytest -q
# или с покрытием:
pytest --cov=autonova -q
```

Основные проверки (`tests/`):

- загрузка KB и Least Privilege;
- регистрация ровно 17 skills;
- RAG retrieval;
- маршрутизация оркестратора (sales / support / service / employee / leasing);
- сохранение агента в сессии и reset;
- эскалации (неизвестный заказ, подтверждение гарантии);
- SQLite: заявки и аналитика по `dealer_id`;
- запись dialogue logger;
- FastAPI: `/health`, `/api/chat`, `/api/reset`, `/api/requests`, stub-канал telegram.

---

## Демо-сценарии

| Сообщение | Ожидание |
|---|---|
| «Хочу купить кроссовер» | `SALES_AGENT` → Nova Drive / каталог |
| «Статус заказа АН-2024-0512» | `SUPPORT_AGENT` → предпродажная подготовка, 3 дня |
| «Вопрос по гарантии на кузов» | `SERVICE_AGENT` → 6 лет, без подтверждения случая |
| «Лизинг для юридических лиц на 5 авто» | `SALES_AGENT` → лизинг от 8,5% |

Подробнее: [`docs/TEST_DIALOGS.md`](docs/TEST_DIALOGS.md).

### Тестовые данные (кратко)

**Модели:** Nova Comfort / Drive / Cargo / Classic (цены от 950 000 до 2 400 000 ₽).  
**Заказы:** `АН-2024-0512`, `АН-2024-0388`.  
Полные таблицы: [`AutoNova_MVP_Documentation.md`](AutoNova_MVP_Documentation.md).

---

## Структура репозитория

```
AutoSfera AI/
├── README.md
├── docs/COMMERCIAL_PILOT.md        # спецификация пилота 2.0
├── AutoNova_MVP_Documentation.md   # архив учебного MVP 1.1
├── pyproject.toml                  # пакет autonova 2.1.0
├── .env.example
├── contracts/                      # JSON Schema для n8n/Langflow
├── integrations/                   # границы и правила n8n/Langflow
├── prompts/                        # system prompts (4 агента + orchestrator)
├── knowledge_base/                 # JSON Knowledge Base
├── src/autonova/
│   ├── api/main.py                 # FastAPI
│   ├── orchestrator/               # маршрутизация и сессии
│   ├── agents/                     # Sales / Support / Service / Employee
│   ├── skills/                     # 17 skills
│   ├── storage/                    # SQLite (dealer_id)
│   ├── rag/                        # retrieval
│   ├── knowledge/                  # загрузка KB
│   ├── channels/                   # web + stubs
│   ├── llm/                        # mock / OpenAI client
│   ├── logging/                    # app + dialogue logs
│   └── config.py
├── frontend/                       # чат UI
├── tests/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TEST_DIALOGS.md
│   └── integration_examples.json
├── logs/
└── data/                           # SQLite + dialogues/
```

Исходное ТЗ: файл `ТЗ - окончательный вариант.docx` в корне проекта.

---

## Ограничения

1. RAG — учебный TF-IDF, не production vector DB.
2. Telegram / WhatsApp / Email / CRM — HTTP-заготовки без реальных Bot API и CRM-учётных данных.
3. Демонстрационный вход не заменяет корпоративный Identity Provider; пароли и секреты из `.env.example` необходимо заменить.
4. Все коммерческие и клиентские данные вымышлены.
5. В mock-режиме маршрутизация и ответы детерминированы skills/KB; `LLM_MODE=openai` меняет стиль, но не источник фактов.

---

## Документация

| Файл | Содержание |
|---|---|
| [docs/COMMERCIAL_PILOT.md](docs/COMMERCIAL_PILOT.md) | коммерческий пилот 2.0 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | поток запроса, skills, API, storage |
| [docs/TEST_DIALOGS.md](docs/TEST_DIALOGS.md) | тестовые диалоги |
| [docs/integration_examples.json](docs/integration_examples.json) | примеры JSON-интеграции |
| [AutoNova_MVP_Documentation.md](AutoNova_MVP_Documentation.md) | архив учебного MVP 1.1 |
| http://127.0.0.1:8000/docs | OpenAPI (Swagger UI) после запуска |

---

*AutoSfera AI 2.1.0 — защищённый коммерческий демо-пилот. Демо-данные вымышлены.*


---

## OpenAI Build Week 2026

**Category:** Work & Productivity

AutoSfera AI is adapted for OpenAI Build Week as a working multi-agent productivity platform for automotive dealerships. The demonstrable flow routes customer and employee requests to four specialized agents, grounds answers in the dealership knowledge base, captures structured leads and service requests, and exposes operational analytics.

### How Codex contributed

Codex was used to inspect the existing architecture, map the product to the hackathon requirements, identify submission gaps, prepare the Devpost presentation, and implement the Build Week configuration and documentation changes on the `agent/openai-build-week` branch. The final submission must include the `/feedback` Session ID for the primary build thread so judges can verify this work.

### GPT-5.6 evaluation mode

The OpenAI-compatible runtime is configured with `OPENAI_MODEL=gpt-5.6` for the Build Week demonstration. This mode requires a valid `OPENAI_API_KEY` and access to that model. The offline `mock` mode remains available so judges can run the complete routing, Skills, RAG, persistence, and analytics flow without credentials.

```env
LLM_MODE=openai
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5.6
```

### Judge walkthrough

1. Install and run the project using the commands in this README.
2. Open `http://127.0.0.1:8000`.
3. Try: `Хочу купить кроссовер`, `Статус заказа АН-2024-0512`, `Вопрос по гарантии на кузов`, and `Лизинг для юридических лиц на 5 авто`.
4. Review `/api/requests` and `/api/analytics/summary` to see conversations converted into dealership operations.
5. Switch to `LLM_MODE=openai` only when a valid key and GPT-5.6 access are available.

**Repository:** https://github.com/dimitry8st-prog/AutoSfera-AI-

All demo customer, vehicle, pricing, and order data are fictional.
