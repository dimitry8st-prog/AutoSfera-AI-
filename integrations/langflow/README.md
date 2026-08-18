# Langflow research boundary

Langflow performs only bounded competitor research and returns a structured draft with source URLs. It does not authenticate AutoSfera users, change dealer data, publish to the Knowledge Base, or call CRM/DMS actions.

Input mapping:

- `chatInput` — research query;
- `sessionId` — `job_id`;
- business metadata — `dealer_id`, `actor`, `trace_id`.

Output must include `title`, `summary`, and at least one source URL. Treat retrieved web content as untrusted. Export the flow without API keys and record its version in this directory before a pilot release.
