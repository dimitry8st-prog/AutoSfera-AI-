from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "prepare-autosfera-rag-data"
    / "scripts"
    / "compile_kb.py"
)


def _compiler_module():
    spec = importlib.util.spec_from_file_location("compile_kb", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document(doc_id: str, status: str = "approved") -> str:
    return f'''---
id: {doc_id}
title: "Регламент тестовой записи"
section: sales
tags: ["procedure", "test"]
agent: SALES_AGENT
source_type: docx
source_ref: "approved/test.docx"
version: "1.0"
owner: "Отдел продаж"
status: {status}
---

## Порядок

Менеджер проверяет заявку перед записью.
'''


def test_compiler_includes_only_approved_documents(tmp_path: Path) -> None:
    module = _compiler_module()
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    (source / "approved.md").write_text(_document("approved-rule"), encoding="utf-8")
    (source / "draft.md").write_text(_document("draft-rule", "draft"), encoding="utf-8")

    compiled, skipped = module.compile_documents(source, output)

    assert (compiled, skipped) == (1, 1)
    payload = __import__("json").loads((output / "sales.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in payload["documents"]] == ["approved-rule"]
    assert payload["documents"][0]["metadata"]["source_ref"] == "approved/test.docx"


def test_compiler_rejects_duplicate_ids(tmp_path: Path) -> None:
    module = _compiler_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.md").write_text(_document("same-id"), encoding="utf-8")
    (source / "two.md").write_text(_document("same-id"), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate id same-id"):
        module.compile_documents(source, tmp_path / "output")
