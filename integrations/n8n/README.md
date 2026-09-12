# n8n gateways

n8n is the only component allowed to call the Langflow research flow. AutoSfera never exposes Langflow directly.

Required workflow:

1. Receive the signed payload described by `contracts/research-job.schema.json`.
2. Reject an invalid `X-AutoSfera-Signature`.
3. Deduplicate by `dealer_id + idempotency_key`.
4. Call Langflow with bounded timeout and retry policy.
5. Validate the Langflow output against `contracts/research-callback.schema.json`.
6. POST the signed result to `/api/research/callback`.

Recommended limits: three attempts with exponential delay, one logical callback, no secrets in an exported workflow. The exact n8n export is environment-specific and must be committed only after credentials are removed.

## Action Gateway catalog (TZ 3.1 pilot)

The sandbox catalog lives in this directory:

| Code | Workflow | Role |
|---|---|---|
| WF-00 | `workflows/AUTOSFERA_WF-00_ACTION_GATEWAY.json` | signed webhook, HMAC, timestamp/nonce, allowlist, dispatch |
| WF-10 | `workflows/AUTOSFERA_WF-10_SALES_LEAD.json` | demo CRM `create_lead` |
| WF-11 | `workflows/AUTOSFERA_WF-11_TEST_DRIVE.json` | demo CRM `create_test_drive` |
| WF-20 | `workflows/AUTOSFERA_WF-20_SERVICE_BOOKING.json` | demo CRM `create_service` |

`manifest.json` is the source of stable IDs. Fixtures in `fixtures/` are ActionRequest v1 examples for local replay. The webhook path stays `autosfera-actions`.

WF-00 never receives a job before an authorized AutoSfera employee approves it. The API signs every request and n8n signs every callback with `ACTION_WEBHOOK_SECRET`. The sandbox adapters return `{provider: "n8n-sandbox", external_id}` — they do not call a live CRM or Telegram.

Sandbox WF-00 dispatches `action_type` with an in-gateway demo CRM adapter equivalent to WF-10/11/20. Child workflows are still imported so the catalog is visible in n8n; they can later replace the inlined adapter via Execute Workflow without changing the FastAPI contract.

Required n8n environment variables:

- `ACTION_WEBHOOK_SECRET` — the same strong secret as in the API;
- `AUTOSFERA_API_URL` — server-side API URL, never a browser localhost URL;
- `NODE_FUNCTION_ALLOW_BUILTIN=crypto` — permits the Code nodes to calculate HMAC.

Import the catalog, set the variables, replace the demo adapters with a real CRM/DMS mapping, test with non-production data, and only then activate the production webhook. n8n must not connect directly to AutoSfera's database. WF-00 enables n8n's **Raw Body** webhook option so the HMAC is calculated over the same bytes sent by the API. See the official [Webhook node documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).

### Reproducible local sandbox

Run `scripts/setup_n8n_sandbox.sh` from Linux, macOS, WSL or Git Bash with
Docker Compose installed. The script creates `.env.n8n.local` with random
local secrets, imports the catalog, publishes WF-00, starts PostgreSQL,
n8n and AutoSfera, and runs a real HTTP smoke test.

The smoke test verifies the complete boundary: chat proposal, human approval,
signed API-to-n8n ActionRequest v1, signed n8n-to-API callback and the four-event audit
trail. n8n is published on loopback only. The committed workflows remain
inactive by default; activation happens only inside the isolated sandbox.

Stop the sandbox without deleting its data:

```bash
docker compose --env-file .env.n8n.local \
  -f compose.yaml -f compose.n8n-sandbox.yaml down
```

Delete the sandbox volumes only when their data is no longer needed:

```bash
docker compose --env-file .env.n8n.local \
  -f compose.yaml -f compose.n8n-sandbox.yaml down --volumes
```
