#!/usr/bin/env python3
"""Compile approved canonical Markdown documents into AutoSfera KB JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ALLOWED_SECTIONS = {
    "company", "sales", "customer_support", "service", "finance", "internal",
    "legal", "faq", "scripts", "policies", "glossary",
}
ALLOWED_AGENTS = {"SALES_AGENT", "SERVICE_AGENT", "SUPPORT_AGENT", "EMPLOYEE_AGENT"}
REQUIRED = {"id", "title", "section", "tags", "source_type", "source_ref", "version", "owner", "status"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith(("[", '"')):
        return json.loads(raw)
    return raw


def parse_document(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing frontmatter delimiters")
    header, content = text[4:].split("\n---\n", 1)
    metadata: dict[str, Any] = {}
    for line_number, line in enumerate(header.splitlines(), start=2):
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter at line {line_number}")
        key, raw = line.split(":", 1)
        metadata[key.strip()] = parse_scalar(raw)
    return metadata, content.strip()


def validate(path: Path, metadata: dict[str, Any], content: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED - metadata.keys())
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if metadata.get("section") not in ALLOWED_SECTIONS:
        errors.append("unsupported section")
    if metadata.get("agent") and metadata["agent"] not in ALLOWED_AGENTS:
        errors.append("unsupported agent")
    if not ID_RE.fullmatch(str(metadata.get("id", ""))):
        errors.append("id must be lowercase ASCII words separated by hyphens")
    tags = metadata.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        errors.append("tags must be a JSON string array")
    if metadata.get("status") not in {"approved", "draft", "needs_review", "rejected"}:
        errors.append("unsupported status")
    if not content:
        errors.append("empty content")
    return [f"{path}: {error}" for error in errors]


def compile_documents(source_dir: Path, output_dir: Path) -> tuple[int, int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[str] = set()
    errors: list[str] = []
    skipped = 0

    for path in sorted(source_dir.rglob("*.md")):
        try:
            metadata, content = parse_document(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        errors.extend(validate(path, metadata, content))
        doc_id = str(metadata.get("id", ""))
        if doc_id in seen_ids:
            errors.append(f"{path}: duplicate id {doc_id}")
        seen_ids.add(doc_id)
        if metadata.get("status") != "approved":
            skipped += 1
            continue
        document = {
            "id": doc_id,
            "title": metadata.get("title"),
            "content": content,
            "tags": metadata.get("tags", []),
        }
        if metadata.get("agent"):
            document["agent"] = metadata["agent"]
        grouped[str(metadata.get("section"))].append(document)

    if errors:
        raise ValueError("\n".join(errors))
    if not seen_ids:
        raise ValueError(f"{source_dir}: no Markdown documents found")

    output_dir.mkdir(parents=True, exist_ok=True)
    for section, documents in grouped.items():
        target = output_dir / f"{section}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"section": section, "documents": documents}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    return sum(map(len, grouped.values())), skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        compiled, skipped = compile_documents(args.source_dir, args.output_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Compiled {compiled} approved document(s); skipped {skipped} unapproved document(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
