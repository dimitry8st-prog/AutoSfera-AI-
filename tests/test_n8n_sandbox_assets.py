from __future__ import annotations

import json
import os
from pathlib import Path

from autonova.config import Settings


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
    assert 'command: ["import:workflow", "--input=/workflows/action-gateway.workflow.json"]' in compose
    assert (
        'command: ["publish:workflow", "--id=autosfera-action-gateway-sandbox"]'
        in compose
    )


def test_sandbox_scripts_do_not_embed_customer_or_gateway_secrets() -> None:
    setup = (ROOT / "scripts/setup_n8n_sandbox.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts/smoke_action_gateway_n8n.py").read_text(encoding="utf-8")
    assert "secrets.token_hex" in setup
    assert ".env.n8n.local" in setup
    assert "compose run --rm n8n-publish" in setup
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
