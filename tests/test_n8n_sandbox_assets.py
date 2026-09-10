from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sandbox_workflow_is_safe_and_importable() -> None:
    workflow = json.loads(
        (ROOT / "integrations/n8n/action-gateway.workflow.json").read_text(encoding="utf-8")
    )
    assert workflow["id"] == "autosfera-action-gateway-sandbox"
    assert workflow["active"] is False
    assert [node["name"] for node in workflow["nodes"]] == [
        "Signed Action Webhook",
        "Verify and Validate",
        "Prepare Signed Callback",
        "Return Result",
    ]
    serialized = json.dumps(workflow)
    assert "$env.ACTION_WEBHOOK_SECRET" in serialized
    assert "replace-action-webhook-secret" not in serialized
    assert "n8n-sandbox" in serialized


def test_sandbox_compose_keeps_n8n_local_and_secrets_external() -> None:
    compose = (ROOT / "compose.n8n-sandbox.yaml").read_text(encoding="utf-8")
    assert "n8nio/n8n:2.37.10" in compose
    assert '127.0.0.1:${N8N_PORT:-5678}:5678' in compose
    assert "N8N_LISTEN_ADDRESS: 0.0.0.0" in compose
    assert "ACTION_WEBHOOK_SECRET:?" in compose
    assert "N8N_ENCRYPTION_KEY:?" in compose
    assert "http://n8n:5678/webhook/autosfera-actions" in compose
    assert "NODE_FUNCTION_ALLOW_BUILTIN: crypto" in compose


def test_sandbox_scripts_do_not_embed_customer_or_gateway_secrets() -> None:
    setup = (ROOT / "scripts/setup_n8n_sandbox.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts/smoke_action_gateway_n8n.py").read_text(encoding="utf-8")
    assert "secrets.token_hex" in setup
    assert ".env.n8n.local" in setup
    assert "ACTION_WEBHOOK_SECRET=" not in smoke
    assert "+79990000000" in smoke
