# Архитектура AutoNova

Стек: Python 3.11+, FastAPI, JSON Knowledge Base, TF-IDF RAG, Skills, mock/OpenAI LLM.

## Поток запроса

1. Канал (`web` или stub) принимает сообщение.  
2. Orchestrator при первом ходе выбирает агента (JSON от LLM).  
3. Agent вызывает SkillRouter → Skill.  
4. RAG достаёт фрагменты KB с учётом Least Privilege (`SECTION_ACCESS`).  
5. Skill формирует ответ; эскалации пишутся в dialogue log.

## Skills (12)

| Agent | Skills |
|---|---|
| Sales | vehicle_selection, trade_in, credit_leasing, test_drive_booking |
| Support | order_status, documentation_support, customer_faq, support_escalation |
| Service | warranty_consultation, service_booking, maintenance_consultation, service_escalation |

## Логи

- `logs/autonova.log` — приложение  
- `logs/dialogues.log` — диалоги  
- `data/dialogues/<session_id>.jsonl` — события сессии  

## API

- `POST /api/chat` — чат  
- `POST /api/reset` — новый диалог  
- `GET /api/knowledge` — KB  
- `GET /api/skills` — список skills  
- `POST /api/channels/{name}` — stub-каналы  

Интеграционные примеры: `docs/integration_examples.json`.
