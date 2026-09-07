#!/bin/sh
set -eu

BACKUP_DIR=${BACKUP_DIR:-./backups}
mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="$BACKUP_DIR/autosfera_$STAMP.dump"

docker compose exec -T postgres pg_dump \
  --username autosfera \
  --dbname autosfera \
  --format=custom \
  --no-owner \
  --no-acl > "$BACKUP_FILE"

test -s "$BACKUP_FILE"
printf '%s\n' "$BACKUP_FILE"
