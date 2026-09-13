from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from autonova.config import Settings


def _tree_fingerprint(root: Path, suffixes: tuple[str, ...]) -> str:
    """Return a short stable digest of the files copied into the running build."""
    if not root.exists():
        return "missing"
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12] if files else "empty"


def _declared_kb_version(settings: Settings) -> str:
    if settings.knowledge_base_version != "auto":
        return settings.knowledge_base_version
    governance = settings.knowledge_base_dir / "_governance.json"
    try:
        payload = json.loads(governance.read_text(encoding="utf-8"))
        return str(payload["metadata_defaults"]["version"])
    except (OSError, KeyError, TypeError, ValueError):
        return "unversioned"


def runtime_identity(settings: Settings) -> dict[str, Any]:
    return {
        "app_version": settings.app_version,
        "build_sha": settings.build_sha,
        "prompts": {
            "version": settings.prompt_version,
            "fingerprint": _tree_fingerprint(settings.prompts_dir, (".txt", ".md")),
        },
        "knowledge_base": {
            "version": _declared_kb_version(settings),
            "fingerprint": _tree_fingerprint(
                settings.knowledge_base_dir, (".json", ".md", ".txt", ".pdf")
            ),
        },
        "llm": {
            "mode": settings.llm_mode,
            "model": settings.openai_model if settings.llm_mode == "openai" else None,
            "simple_model": (
                settings.openai_simple_model or settings.openai_model
                if settings.llm_mode == "openai" else None
            ),
            "complex_model": (
                settings.openai_complex_model or settings.openai_model
                if settings.llm_mode == "openai" else None
            ),
        },
        "rag_backend": settings.rag_backend,
    }
