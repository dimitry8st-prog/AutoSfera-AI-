#!/usr/bin/env python3
"""Run evidence-based demo checks against a locally running AutoSfera API."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "demo" / "demo_scenarios.json"
RESULTS = ROOT / "demo" / "results"
BASE_URL = os.getenv("AUTOSFERA_DEMO_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def request_json(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        health = request_json("/health")
        ready = request_json("/ready")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"API недоступен или вернул некорректный ответ: {exc}", file=sys.stderr)
        return 2

    infrastructure_ok = (
        health.get("status") == "ok"
        and health.get("skills") == 18
        and len(health.get("agents", [])) == 4
        and bool(ready)
    )
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    results: list[dict] = []

    for scenario in scenarios:
        started = time.perf_counter()
        error = None
        response: dict = {}
        try:
            response = request_json(
                "/api/chat",
                {
                    "message": scenario["message"],
                    "session_id": f"demo-{scenario['id']}-{uuid.uuid4().hex[:10]}",
                    "channel": "web",
                },
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            error = str(exc)
        elapsed = round(time.perf_counter() - started, 3)
        passed = (
            error is None
            and response.get("agent") == scenario["expected_agent"]
            and response.get("skill") == scenario["expected_skill"]
            and bool(response.get("reply"))
            and elapsed < 30
        )
        results.append(
            {
                "id": scenario["id"],
                "message": scenario["message"],
                "expected_agent": scenario["expected_agent"],
                "expected_skill": scenario["expected_skill"],
                "agent": response.get("agent"),
                "skill": response.get("skill"),
                "model_route": response.get("model_route"),
                "rag_ids": response.get("rag_ids", []),
                "escalated": response.get("escalated"),
                "routing_reason": response.get("routing_reason"),
                "elapsed_seconds": elapsed,
                "passed": passed,
                "error": error,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "health": {
            "status": health.get("status"),
            "version": health.get("runtime", {}).get("app_version"),
            "agents": len(health.get("agents", [])),
            "skills": health.get("skills"),
            "llm": health.get("runtime", {}).get("llm"),
            "rag": health.get("runtime", {}).get("rag_backend"),
        },
        "infrastructure_passed": infrastructure_ok,
        "scenarios": results,
        "passed": infrastructure_ok and all(item["passed"] for item in results),
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Фактический прогон демонстрационных сценариев",
        "",
        f"- Дата: `{report['generated_at']}`",
        f"- Агенты: `{report['health']['agents']}`",
        f"- Skills: `{report['health']['skills']}`",
        f"- Итог: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "| Сценарий | Агент | Skill | Время, с | Результат |",
        "|---|---|---|---:|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['id']} | {item['agent'] or '—'} | {item['skill'] or '—'} | "
            f"{item['elapsed_seconds']} | {'PASS' if item['passed'] else 'FAIL'} |"
        )
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[5])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
