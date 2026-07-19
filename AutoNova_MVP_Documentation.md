# AutoNova — MVP Documentation
## Версия 1.1 | Учебный проект

Документ описывает **текущую** реализацию в репозитории (Python/FastAPI), а не устаревший прототип на React + Anthropic.

---

## 1. ОБЗОР MVP

Рабочий чат мультиагентной системы AutoNova: оркестратор маршрутизирует обращение, агент отвечает через Skills и RAG по JSON Knowledge Base.

| Компонент | Статус |
|---|---|
| AI Orchestrator | Реализован |
| Sales / Support / Service Agents | Реализованы |
| 12 Skills | Реализованы |
| Knowledge Base (JSON, 10 разделов) | Реализована |
| RAG (TF-IDF, без vector DB) | Реализован |
| Веб-чат + просмотр KB + quick replies | Реализованы |
| История диалога в сессии (сервер) | Реализована |
| Логирование диалогов (log + JSONL) | Реализовано |
| Адаптеры Telegram/WhatsApp/Email/CRM | Каркас API (без внешних Bot API) |

Не входит: полноценные Bot API, CRM live, аутентификация, векторная БД.

---

## 2. АРХИТЕКТУРА

```
Браузер (frontend/)
   │  POST /api/chat
   ▼
FastAPI (src/autonova/api)
   ▼
Channel → AI Orchestrator → Agent → Skill → RAG → Knowledge Base
   │
   └─→ logs/ + data/dialogues/*.jsonl
```

- Первое сообщение сессии → маршрутизация Orchestrator (`prompts/orchestrator.txt`).
- Дальше отвечает выбранный агент до «Новый чат» / `POST /api/reset`.
- LLM по умолчанию: `LLM_MODE=mock` (офлайн). Опционально OpenAI-compatible API.

Подробности: `docs/ARCHITECTURE.md`.

---

## 3. SYSTEM PROMPTS

Актуальные тексты — в `prompts/`:
- `orchestrator.txt`
- `sales_agent.txt`
- `support_agent.txt`
- `service_agent.txt`

В промптах: роль, цели, Skills, RAG-правила, ограничения, эскалация. Фактические факты берутся из KB через RAG, а не зашиваются только в промпт.

---

## 4. СЦЕНАРИИ

1. «Хочу купить кроссовер» → SALES / vehicle_selection → Nova Drive  
2. «Статус заказа АН-2024-0512» → SUPPORT / order_status  
3. «Вопрос по гарантии на кузов» → SERVICE / warranty_consultation (без подтверждения случая)  
4. «Лизинг для юридических лиц на 5 авто» → SALES / credit_leasing  

См. также `docs/TEST_DIALOGS.md`.

---

## 5. ТЕСТОВЫЕ ДАННЫЕ

| Модель | Тип | Цена от | Комплектации |
|---|---|---|---|
| Nova Comfort | Седан | 1 800 000 руб. | Base, Standard, Premium |
| Nova Drive | Кроссовер | 2 400 000 руб. | Standard, Premium, Sport |
| Nova Cargo | Фургон | 2 100 000 руб. | Base, Standard |
| Nova Classic | Седан б/у | 950 000 руб. | — |

| Номер | Модель | Статус | Выдача |
|---|---|---|---|
| АН-2024-0512 | Nova Drive Premium | Предпродажная подготовка | 3 дня |
| АН-2024-0388 | Nova Comfort Standard | В пути со склада | 5 дней |

Источник: `knowledge_base/`.

---

## 6. СТРУКТУРА КОДА

```
src/autonova/
  orchestrator/  — маршрутизация и сессии
  agents/        — Sales, Support, Service
  skills/        — 12 skills
  rag/           — retrieval
  knowledge/     — загрузка KB
  channels/      — web + stubs
  logging/       — app + dialogue logs
  api/main.py    — FastAPI
frontend/        — чат
prompts/         — system prompts
tests/           — pytest
```

---

## 7. ОГРАНИЧЕНИЯ

1. RAG — учебный TF-IDF, не vector DB.  
2. История сессии в памяти процесса (плюс JSONL логов).  
3. Внешние мессенджеры — только HTTP-заготовки.  
4. Нет аутентификации.  
5. Все цены/заказы вымышлены.

---

## 8. ЗАПУСК

```bash
python -m pip install -e ".[dev]"
pytest -q
uvicorn autonova.api.main:app --reload --app-dir src
```

http://127.0.0.1:8000

---

*AutoNova MVP v1.1 — учебный проект. Данные вымышлены.*
