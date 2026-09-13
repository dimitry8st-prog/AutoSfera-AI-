# Этап 1 Базовая проверка AutoSfera AI

Результат: 9/13 сценариев соответствуют целевому поведению.

- Версия: `3.1.0-beta.1`
- Commit: `cbc6078`
- Промпты: `2026-09-13-beta.1` / `f94fca3b57fd`
- База знаний: `2026-09-13-beta.1` / `c8b0cb409f4a`
- LLM: `mock`
- RAG: `tfidf`

| Сценарий | Статус | Диагностика |
|---|---|---|
| catalog | PASS | Ожидаемый результат получен |
| order_status | PASS | Ожидаемый результат получен |
| warranty | PASS | Ожидаемый результат получен |
| service_booking | PASS | Ожидаемый результат получен |
| employee_process | PASS | Ожидаемый результат получен |
| switch_service_to_purchase | FAIL | agent: expected 'SALES_AGENT', got 'SERVICE_AGENT'; routing_reason: expected 'topic_switch', got 'session_continuity' |
| switch_sales_to_service | FAIL | agent: expected 'SERVICE_AGENT', got 'SUPPORT_AGENT' |
| ambiguous_conditions | FAIL | routing_reason: expected 'clarify', got 'conversational_faq' |
| ambiguous_paperwork | FAIL | agent: expected 'AI_ORCHESTRATOR', got 'SALES_AGENT'; routing_reason: expected 'clarify', got 'intent_match' |
| off_scope_weather | PASS | Ожидаемый результат получен |
| illegal_request | PASS | Ожидаемый результат получен |
| graph_failure | PASS | Ожидаемый результат получен |
| restart_session | PASS | Ожидаемый результат получен |
