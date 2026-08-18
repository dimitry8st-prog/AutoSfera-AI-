# n8n research gateway

n8n is the only component allowed to call the Langflow research flow. AutoSfera never exposes Langflow directly.

Required workflow:

1. Receive the signed payload described by `contracts/research-job.schema.json`.
2. Reject an invalid `X-AutoSfera-Signature`.
3. Deduplicate by `dealer_id + idempotency_key`.
4. Call Langflow with bounded timeout and retry policy.
5. Validate the Langflow output against `contracts/research-callback.schema.json`.
6. POST the signed result to `/api/research/callback`.

Recommended limits: three attempts with exponential delay, one logical callback, no secrets in an exported workflow. The exact n8n export is environment-specific and must be committed only after credentials are removed.
