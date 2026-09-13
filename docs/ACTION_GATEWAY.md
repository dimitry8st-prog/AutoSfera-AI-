# AutoSfera Action Gateway

## Purpose

Action Gateway is the only application boundary allowed to create an external
business side effect from an AI conversation. The assistant may propose an
action, but it cannot approve or execute it.

## State machine

`waiting_approval -> approved -> running -> completed`

Alternative terminal paths are `waiting_approval -> rejected` and
`running -> failed`. A failed job can be explicitly returned to `approved` by
an authorized employee and dispatched again. Compare-and-update transitions
prevent two workers from executing the same action.

A transport timeout becomes `delivery_unknown`, not `failed`: n8n may have
accepted the request before the connection timed out. This state cannot be
blindly retried; an operator must reconcile it using the external system and
the `trace_id`. A later valid callback can still complete it.

## Authorization

| Kind | Can approve/retry | Can view |
|---|---|---|
| `lead` | `admin`, `sales` | all staff roles |
| `test_drive` | `admin`, `sales` | all staff roles |
| `service` | `admin`, `service` | all staff roles |

Guests can propose an action through a validated chat scenario. They cannot
list, review, retry, or execute actions.

## Data and audit

`action_jobs` is a durable outbox in SQLite or PostgreSQL. The unique
`dealer_id + idempotency_key` pair represents one logical action. Every state
change appends an `action_events` row with actor, timestamp, and details.
`trace_id` binds dispatch and callback.

On API startup, durable jobs left in `approved` are dispatched again. Atomic
claiming makes this safe when multiple API workers start simultaneously.

Two complementary records are kept:

- `action_events` is the immutable business audit trail used by the manager UI;
- `logs/autonova.log` contains operational lifecycle messages for diagnostics.

Operational logs include action, dealer and trace identifiers, status, role,
attempt count and error class. Customer name, phone number and request payload
are deliberately excluded from log messages.

## Execution modes

- `ACTION_GATEWAY_MODE=mock` executes against the local demo CRM. This is the
  default and is fully covered by automated tests.
- `ACTION_GATEWAY_MODE=n8n` sends a signed ActionRequest v1 payload to
  `ACTION_WEBHOOK_URL`. The main chat remains available when n8n is down; the
  action becomes `failed` and can be retried by an authorized role.

The envelope includes `action_type`, `issued_at`, `nonce`, `idempotency_key`,
`trace_id` and `callback_url`. HMAC-SHA256 covers the raw JSON body with
`ACTION_WEBHOOK_SECRET`. Optional headers `X-AutoSfera-Timestamp` and
`X-AutoSfera-Nonce` repeat the body values. `ACTION_CALLBACK_URL` defaults to
`http://api:8000/api/actions/callback` inside the Compose sandbox.

Production deployments must use a random secret and TLS. n8n never receives
database credentials and never writes directly to application tables.

WF-00 is the only published webhook. It verifies the signature, rejects a
timestamp skew greater than 300 seconds, requires a nonce, and dispatches
`create_lead` / `create_test_drive` / `create_service`. The sandbox adapters
are a demo CRM, not a live CRM or Telegram bot.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/actions` | list the dealer's action jobs |
| `GET` | `/api/actions/{id}` | inspect one job |
| `GET` | `/api/actions/{id}/events` | inspect its audit trail |
| `POST` | `/api/actions/{id}/review` | approve or reject |
| `POST` | `/api/actions/{id}/retry` | retry a failed job |
| `POST` | `/api/actions/callback` | signed n8n result |

JSON contracts are in `contracts/action-job.schema.json`,
`contracts/action-request.schema.json` and
`contracts/action-callback.schema.json`. The n8n catalog is in
`integrations/n8n/workflows/` (WF-00 gateway plus WF-10/11/20 demo adapters).

## Production checklist

1. Apply Alembic migrations before starting the updated API.
2. Rotate all demo secrets and restrict CORS.
3. Import the n8n catalog and set its environment variables.
4. Replace the demo adapters with the selected CRM/DMS API mapping.
5. Run a sandbox acceptance test, including duplicate delivery and timeout.
6. Activate the workflow only after signed callback verification succeeds.
