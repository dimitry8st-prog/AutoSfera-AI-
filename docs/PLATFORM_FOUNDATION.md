# Platform Foundation: PostgreSQL demo CRM

Этот этап переводит бизнес-данные AutoSfera AI из локального SQLite в PostgreSQL, не меняя контракт API, агентов и пользовательскую воронку.

## Что изменилось

- `PostgresPlatformStore` реализует тот же прикладной контракт, что и SQLite-хранилище.
- `DATABASE_URL=postgresql://...` включает PostgreSQL; пустое значение сохраняет SQLite fallback.
- Alembic создаёт таблицы `conversations`, `requests`, `sessions`, `research_jobs` и индексы идемпотентности.
- `compose.yaml` поднимает API и непубличный PostgreSQL с healthchecks.
- `/health` проверяет жизнеспособность API; `/ready` отдельно проверяет зависимость от базы.
- Backup и restore выполняются явными скриптами, восстановление защищено подтверждением `CONFIRM_RESTORE=YES`.

## Граница этапа

Это демо-CRM пилота, а не замена будущей CRM/DMS автосалона. Таблица `requests` хранит лиды, тест-драйвы и сервисные заявки. Когда заказчик выберет реальную CRM, новый адаптер должен сохранить методы создания, чтения, обновления, идемпотентность и изоляцию по `dealer_id`.

## Запуск

1. Скопировать `.env.example` в `.env`.
2. Заменить три placeholder-секрета на длинные случайные значения.
3. Выполнить `docker compose up --build -d`.
4. Дождаться состояния `healthy` у `postgres` и `api`.
5. Выполнить `scripts/smoke_postgres.sh`.

## Backup и restore gate

```bash
scripts/backup_postgres.sh
CONFIRM_RESTORE=YES scripts/restore_postgres.sh backups/<имя>.dump
```

Gate считается пройденным, если:

- GitHub Actions применил Alembic-миграцию к реальному PostgreSQL 17 и выполнил интеграционный тест;
- backup-файл существует и имеет ненулевой размер;
- восстановление завершается без ошибки;
- `/ready` снова возвращает `200`;
- созданная до backup тестовая заявка присутствует после restore;
- повторный запрос с одинаковым `source_ref` не создаёт дубль.

## Следующий этап

После прохождения smoke + restore подключается единый n8n Action Gateway. До этого n8n не должен получать прямой доступ к таблицам приложения.
