#!/usr/bin/env python3
"""Run the stage-one API routing and resilience baseline."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, list[str]]:
    errors = []
    for key, value in expected.items():
        if actual.get(key) != value:
            errors.append(f"{key}: expected {value!r}, got {actual.get(key)!r}")
    return not errors, errors


def _write_report(
    path: Path,
    runtime: dict[str, Any],
    results: list[dict[str, Any]],
    title: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for item in results if item["passed"])
    payload = {"runtime": runtime, "passed": passed, "total": len(results), "results": results}
    path.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# {title}",
        "",
        f"Результат: {passed}/{len(results)} сценариев соответствуют целевому поведению.",
        "",
        f"- Версия: `{runtime['app_version']}`",
        f"- Commit: `{runtime['build_sha']}`",
        f"- Промпты: `{runtime['prompts']['version']}` / `{runtime['prompts']['fingerprint']}`",
        f"- База знаний: `{runtime['knowledge_base']['version']}` / `{runtime['knowledge_base']['fingerprint']}`",
        f"- LLM: `{runtime['llm']['mode']}`",
        f"- RAG: `{runtime['rag_backend']}`",
        "",
        "| Сценарий | Статус | Диагностика |",
        "|---|---|---|",
    ]
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        detail = "; ".join(item["errors"]) if item["errors"] else "Ожидаемый результат получен"
        lines.append(f"| {item['id']} | {status} | {detail} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Return code 1 when a target case fails")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports" / "stage-1" / "report.md"
    )
    parser.add_argument("--title", default="Этап 1 Базовая проверка AutoSfera AI")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="autosfera-stage1-") as tmp:
        os.environ.update({
            "DATABASE_PATH": str(Path(tmp) / "autosfera.db"),
            "LOGS_DIR": str(Path(tmp) / "logs"),
            "DIALOGUES_DIR": str(Path(tmp) / "dialogues"),
            "LLM_MODE": "mock",
            "BUILD_SHA": os.environ.get("BUILD_SHA", "local-baseline"),
        })

        from fastapi.testclient import TestClient
        import autonova.api.main as api_main
        from autonova.config import get_settings

        get_settings.cache_clear()
        api_main.get_store.cache_clear()
        api_main.get_orchestrator.cache_clear()
        cases = json.loads((ROOT / "evals" / "stage1_cases.json").read_text(encoding="utf-8"))
        results: list[dict[str, Any]] = []

        with TestClient(api_main.create_app()) as client:
            runtime = client.get("/health").json()["runtime"]
            employee_token = client.post(
                "/api/auth/token",
                json={"username": "employee", "password": "employee-demo"},
            ).json()["access_token"]

            for case in cases:
                errors: list[str] = []
                observations: list[dict[str, Any]] = []
                if case["type"] == "chat":
                    session_id = None
                    headers = (
                        {"Authorization": f"Bearer {employee_token}"}
                        if case.get("role") == "employee" else {}
                    )
                    for turn in case["turns"]:
                        body = {"message": turn["message"]}
                        if session_id:
                            body["session_id"] = session_id
                        response = client.post("/api/chat", json=body, headers=headers)
                        if response.status_code != 200:
                            errors.append(f"HTTP {response.status_code}")
                            break
                        actual = response.json()
                        session_id = actual["session_id"]
                        observations.append({
                            key: actual.get(key)
                            for key in (
                                "agent", "skill", "routing_reason", "model_route",
                                "model_tier", "routing_risk", "escalated", "rag_ids",
                            )
                        })
                        _, mismatch = _matches(actual, turn["expected"])
                        errors.extend(mismatch)
                elif case["type"] == "graph_failure":
                    class BrokenGraph:
                        def invoke(self, _state: dict[str, Any]) -> dict[str, Any]:
                            raise RuntimeError("stage-one simulated graph failure")

                    orchestrator = api_main.get_orchestrator()
                    original_graph = orchestrator.graph
                    orchestrator.graph = BrokenGraph()
                    actual = client.post("/api/chat", json={"message": "Хочу купить автомобиль"}).json()
                    orchestrator.graph = original_graph
                    observations.append({key: actual.get(key) for key in ("agent", "skill", "escalated")})
                    _, errors = _matches(
                        actual,
                        {"agent": "AI_ORCHESTRATOR", "skill": "safe_fallback", "escalated": True},
                    )
                else:
                    first = client.post("/api/chat", json={"message": "Хочу купить кроссовер"}).json()
                    api_main.get_orchestrator.cache_clear()
                    second = client.post(
                        "/api/chat",
                        json={"message": "А какие цвета?", "session_id": first["session_id"]},
                    ).json()
                    observations.append({key: second.get(key) for key in ("agent", "routing_reason")})
                    _, errors = _matches(
                        second, {"agent": "SALES_AGENT", "routing_reason": "session_continuity"}
                    )
                results.append({
                    "id": case["id"], "passed": not errors,
                    "errors": errors, "observations": observations,
                })

        _write_report(args.output, runtime, results, args.title)
        print(f"Stage-one baseline: {sum(r['passed'] for r in results)}/{len(results)} passed")
        print(args.output)
        return 1 if args.strict and any(not item["passed"] for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
