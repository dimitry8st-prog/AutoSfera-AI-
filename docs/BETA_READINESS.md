# AutoSfera AI 3.1 — готовность контролируемой беты

## Допустимый контур

Версия `3.1.0-beta.1` предназначена для одного тестового автосалона, ограниченной группы сотрудников и вымышленных либо обезличенных данных. Это не разрешение на публичный production-запуск.

## Соответствие ТЗ

| Требование | Реализация | Проверка |
|---|---|---|
| Центральная оркестрация | LangGraph с быстрым откатом на legacy | `/api/beta/readiness` |
| 4 специализированных агента | Sales, Support, Service, Employee | `/health` и unit-тесты |
| 17 навыков и RAG | TF-IDF локально, pgvector/HNSW в пилотном Compose | RAG evaluation и PostgreSQL CI |
| Заявки и статусы | PostgreSQL/Alembic, SQLite fallback | API и storage tests |
| Контроль внешних действий | propose → approve → execute → audit | n8n sandbox E2E |
| Исследования конкурентов | подписанный n8n/Langflow job, human review | API tests; внешний Langflow настраивается отдельно |
| UX и обратная связь | доступная оценка 1–5, CSAT в кабинете | feedback API и smoke test |
| Изоляция салона | `dealer_id` во всех бизнес-записях | storage tests |
| Диагностика беты | обязательные блокеры и предупреждения конфигурации | `/api/beta/readiness` |

## Критерии допуска

- обязательные проверки `/api/beta/readiness` не содержат блокеров;
- миграции применены, `/ready` возвращает `status=ready`;
- unit/API тесты и PostgreSQL integration job успешны;
- n8n sandbox E2E успешен;
- тестовые секреты заменены до любого внешнего доступа;
- для пилота назначены владелец инцидента и сотрудник, подтверждающий действия;
- CSAT отслеживается, целевое значение — не ниже `4.0/5` после накопления первых 10 оценок.

## Известные ограничения

- CRM/DMS, Telegram/WhatsApp и Langflow требуют реквизитов конкретного поставщика и не активируются автоматически;
- live LLM и pgvector считаются конфигурационными предупреждениями в локальном mock-контуре;
- финансовые, договорные, скидочные и гарантийные решения всегда остаются за сотрудником;
- персональные данные нельзя загружать до утверждения политики хранения и доступа.

## Откат

1. Отключить внешние webhook в n8n.
2. Установить `ACTION_GATEWAY_MODE=mock` и `LLM_MODE=mock`.
3. При проблеме LangGraph временно установить `ORCHESTRATOR_MODE=legacy`.
4. Сохранить audit trail и восстановить PostgreSQL из проверенной резервной копии при повреждении данных.

## Локальная проверка

```bash
python -m pip install -e ".[dev]"
pytest -q
python scripts/evaluate_rag.py --enforce --output-dir /tmp/autosfera-rag-eval
python scripts/smoke_beta.py
```
