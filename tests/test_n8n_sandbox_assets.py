from __future__ import annotations

import json
import os
from pathlib import Path

from autonova.config import Settings


ROOT = Path(__file__).resolve().parents[1]
N8N_DIR = ROOT / "integrations" / "n8n"
WORKFLOWS = {
    "WF-00": N8N_DIR / "workflows" / "AUTOSFERA_WF-00_ACTION_GATEWAY.json",
    "WF-10": N8N_DIR / "workflows" / "AUTOSFERA_WF-10_SALES_LEAD.json",
    "WF-11": N8N_DIR / "workflows" / "AUTOSFERA_WF-11_TEST_DRIVE.json",
    "WF-20": N8N_DIR / "workflows" / "AUTOSFERA_WF-20_SERVICE_BOOKING.json",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_sandbox_catalog_is_safe_and_importable() -> None:
    manifest = _load(N8N_DIR / "manifest.json")
    assert manifest["webhook_path"] == "autosfera-actions"
    assert [item["code"] for item in manifest["workflows"]] == ["WF-00", "WF-10", "WF-11", "WF-20"]

    gateway = _load(WORKFLOWS["WF-00"])
    assert gateway["id"] == "autosfera-wf-00-action-gateway"
    assert gateway["active"] is False
    assert [node["name"] for node in gateway["nodes"]] == [
        "Signed Action Webhook",
        "Verify and Validate",
        "Dispatch Demo CRM",
        "Prepare Signed Callback",
        "Return Result",
    ]
    webhook = gateway["nodes"][0]
    assert webhook["parameters"]["path"] == "autosfera-actions"
    assert webhook["parameters"]["options"]["rawBody"] is True
    serialized = json.dumps(gateway)
    assert "$env.ACTION_WEBHOOK_SECRET" in serialized
    assert "replace-action-webhook-secret" not in serialized
    assert "n8n-sandbox" in serialized
    assert "create_lead" in serialized and "create_test_drive" in serialized
    assert "create_service" in serialized

    children = {
        "WF-10": ("autosfera-wf-10-sales-lead", "create_lead"),
        "WF-11": ("autosfera-wf-11-test-drive", "create_test_drive"),
        "WF-20": ("autosfera-wf-20-service-booking", "create_service"),
    }
    for code, (workflow_id, action_type) in children.items():
        workflow = _load(WORKFLOWS[code])
        assert workflow["id"] == workflow_id
        assert workflow["active"] is False
        assert workflow["nodes"][0]["type"] == "n8n-nodes-base.executeWorkflowTrigger"
        assert action_type in json.dumps(workflow)
        assert "n8n-sandbox" in json.dumps(workflow)


def test_action_request_fixtures_match_catalog() -> None:
    expected = {
        "create_lead": "lead",
        "create_test_drive": "test_drive",
        "create_service": "service",
    }
    for action_type, kind in expected.items():
        fixture = _load(N8N_DIR / "fixtures" / f"{action_type}.json")
        assert fixture["action_type"] == action_type
        assert fixture["kind"] == kind
        assert fixture["dealer_id"] == "main-salon"
        assert len(fixture["nonce"]) >= 8
        assert fixture["callback_url"].endswith("/api/actions/callback")
        assert fixture["payload"]["phone"]


def test_sandbox_compose_keeps_n8n_local_and_secrets_external() -> None:
    compose = (ROOT / "compose.n8n-sandbox.yaml").read_text(encoding="utf-8")
    assert "n8nio/n8n:2.37.10" in compose
    assert '127.0.0.1:${N8N_PORT:-5678}:5678' in compose
    assert "N8N_LISTEN_ADDRESS: 0.0.0.0" in compose
    assert "ACTION_WEBHOOK_SECRET:?" in compose
    assert "N8N_ENCRYPTION_KEY:?" in compose
    assert "http://n8n:5678/webhook/autosfera-actions" in compose
    assert "ACTION_CALLBACK_URL: http://api:8000/api/actions/callback" in compose
    assert "NODE_FUNCTION_ALLOW_BUILTIN: crypto" in compose
    assert (
        'command: ["import:workflow", "--separate", "--input=/workflows/workflows"]'
        in compose
    )
    assert (
        'command: ["publish:workflow", "--id=autosfera-wf-00-action-gateway"]'
        in compose
    )


def test_sandbox_scripts_do_not_embed_customer_or_gateway_secrets() -> None:
    setup = (ROOT / "scripts/setup_n8n_sandbox.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts/smoke_action_gateway_n8n.py").read_text(encoding="utf-8")
    assert "secrets.token_hex" in setup
    assert ".env.n8n.local" in setup
    assert "compose run --rm n8n-publish" in setup
    assert "Waiting for n8n webhook execution" in setup
    assert "ACTION_WEBHOOK_SECRET=" not in smoke
    assert "+79990000000" in smoke
    assert 'response.get("job", response)' in smoke


def test_container_runtime_paths_are_configurable_and_writable(tmp_path: Path) -> None:
    paths = {
        "DATABASE_PATH": tmp_path / "data" / "autosfera.db",
        "KNOWLEDGE_BASE_DIR": tmp_path / "knowledge_base",
        "PROMPTS_DIR": tmp_path / "prompts",
        "FRONTEND_DIR": tmp_path / "frontend",
        "LOGS_DIR": tmp_path / "logs",
        "DIALOGUES_DIR": tmp_path / "data" / "dialogues",
    }
    previous = {name: os.environ.get(name) for name in paths}
    try:
        os.environ.update({name: str(path) for name, path in paths.items()})
        settings = Settings(_env_file=None)
        assert settings.database_path == paths["DATABASE_PATH"]
        assert settings.knowledge_base_dir == paths["KNOWLEDGE_BASE_DIR"]
        assert settings.prompts_dir == paths["PROMPTS_DIR"]
        assert settings.frontend_dir == paths["FRONTEND_DIR"]
        assert settings.logs_dir == paths["LOGS_DIR"]
        assert settings.dialogues_dir == paths["DIALOGUES_DIR"]
        settings.logs_dir.mkdir(parents=True)
        settings.dialogues_dir.mkdir(parents=True)
        assert settings.logs_dir.is_dir()
        assert settings.dialogues_dir.is_dir()
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_docker_image_uses_application_owned_runtime_paths() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for declaration in (
        "DATABASE_PATH=/app/data/autosfera.db",
        "KNOWLEDGE_BASE_DIR=/app/knowledge_base",
        "PROMPTS_DIR=/app/prompts",
        "FRONTEND_DIR=/app/frontend",
        "LOGS_DIR=/app/logs",
        "DIALOGUES_DIR=/app/data/dialogues",
    ):
        assert declaration in dockerfile
