#!/bin/sh
set -eu

BACKUP_FILE=${1:-}
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
  printf '%s\n' "Usage: CONFIRM_RESTORE=YES scripts/restore_postgres.sh backups/<file>.dump" >&2
  exit 2
fi
if [ "${CONFIRM_RESTORE:-NO}" != "YES" ]; then
  printf '%s\n' "Restore replaces objects in the demo database. Set CONFIRM_RESTORE=YES." >&2
  exit 3
fi

docker compose exec -T postgres pg_restore \
  --username autosfera \
  --dbname autosfera \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl < "$BACKUP_FILE"

docker compose exec -T postgres psql \
  --username autosfera \
  --dbname autosfera \
  --tuples-only \
  --command "SELECT 'restore_ok', COUNT(*) FROM requests;"
