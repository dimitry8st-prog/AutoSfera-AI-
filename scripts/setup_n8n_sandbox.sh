#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${N8N_SANDBOX_ENV_FILE:-$ROOT_DIR/.env.n8n.local}

compose() {
  docker compose --env-file "$ENV_FILE" \
    -f "$ROOT_DIR/compose.yaml" \
    -f "$ROOT_DIR/compose.n8n-sandbox.yaml" "$@"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to run the n8n sandbox." >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  python - "$ENV_FILE" <<'PY'
from pathlib import Path
import secrets
import sys

target = Path(sys.argv[1])
target.write_text(
    "POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n"
    "AUTH_SECRET=" + secrets.token_hex(32) + "\n"
    "RESEARCH_WEBHOOK_SECRET=" + secrets.token_hex(32) + "\n"
    "ACTION_WEBHOOK_SECRET=" + secrets.token_hex(32) + "\n"
    "N8N_ENCRYPTION_KEY=" + secrets.token_hex(32) + "\n"
    "DEMO_SALES_PASSWORD=sales-demo\n",
    encoding="utf-8",
)
target.chmod(0o600)
PY
  echo "Created local sandbox secrets: $ENV_FILE"
fi

compose up -d postgres
compose stop n8n 2>/dev/null || true
compose run --rm n8n-import
compose run --rm n8n-publish
compose up -d n8n api

echo "Waiting for AutoSfera API readiness..."
attempt=0
until curl --fail --silent http://127.0.0.1:${APP_PORT:-8000}/ready >/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    compose ps
    echo "AutoSfera API did not become ready." >&2
    exit 1
  fi
  sleep 2
done

echo "Waiting for n8n webhook execution..."
attempt=0
until [ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 3 -X POST http://127.0.0.1:${N8N_PORT:-5678}/webhook/autosfera-actions || echo 000)" = "500" ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    compose ps
    echo "n8n webhook did not become executable." >&2
    exit 1
  fi
  sleep 2
done

BASE_URL=http://127.0.0.1:${APP_PORT:-8000} \
  python "$ROOT_DIR/scripts/smoke_action_gateway_n8n.py"

echo "n8n sandbox is ready: http://127.0.0.1:${N8N_PORT:-5678}"
