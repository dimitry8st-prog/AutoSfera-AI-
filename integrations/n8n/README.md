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

## Action Gateway

`action-gateway.workflow.json` is an importable, inactive demo adapter for the
`propose -> approve -> execute -> callback` path. It never receives a job before
an authorized AutoSfera employee approves it. The API signs every request and
n8n signs every callback with `ACTION_WEBHOOK_SECRET`.

Required n8n environment variables:

- `ACTION_WEBHOOK_SECRET` — the same strong secret as in the API;
- `AUTOSFERA_API_URL` — server-side API URL, never a browser localhost URL;
- `NODE_FUNCTION_ALLOW_BUILTIN=crypto` — permits the Code nodes to calculate HMAC.

Import the workflow, set the variables, replace the demo result node with a
real CRM/DMS adapter, test with non-production data, and only then activate the
production webhook. n8n must not connect directly to AutoSfera's database.
The workflow enables n8n's **Raw Body** webhook option so the HMAC is calculated
over the same bytes sent by the API. See the official
[Webhook node documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).

### Reproducible local sandbox

Run `scripts/setup_n8n_sandbox.sh` from Linux, macOS, WSL or Git Bash with
Docker Compose installed. The script creates `.env.n8n.local` with random
local secrets, imports and activates the sandbox workflow, starts PostgreSQL,
n8n and AutoSfera, and runs a real HTTP smoke test.

The smoke test verifies the complete boundary: chat proposal, human approval,
signed API-to-n8n request, signed n8n-to-API callback and the four-event audit
trail. n8n is published on loopback only. The committed workflow remains
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
