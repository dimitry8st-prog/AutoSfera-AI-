"""Live API acceptance for the AutoSfera AI course demo. Does not change the app."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = REPO_ROOT / "demo" / "demo_scenarios.json"
DEFAULT_OUT_DIR = REPO_ROOT / "demo" / "results"
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+7|8)[\s\-]?(?:\(?\d{3}\)?[\s\-]?)?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]+|Bearer\s+\S+|OPENAI_API_KEY\s*=\s*\S+|AUTH_SECRET\s*=\s*\S+|"
    r"POSTGRES_PASSWORD\s*=\s*\S+)",
    re.IGNORECASE,
)
INTERNAL_RAG_PREFIXES = ("internal-",)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _git_identity() -> dict[str, str]:
    def _run(args: list[str]) -> str:
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    return {
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "sha": _run(["git", "rev-parse", "HEAD"]),
        "short_sha": _run(["git", "rev-parse", "--short", "HEAD"]),
    }


def _http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 45.0) -> tuple[dict[str, Any], float, int]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        data = raw
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            elapsed = time.perf_counter() - started
            return json.loads(body), elapsed, int(response.status)
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - started
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        elapsed = time.perf_counter() - started
        raise RuntimeError(f"API unavailable {url}: {exc.reason}") from exc


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = SECRET_RE.sub("[REDACTED]", value)
        return PHONE_RE.sub("[PHONE_REDACTED]", redacted)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items() if key.lower() not in {"password", "token", "api_key"}}
    return value


def _sanitize_health(health: dict[str, Any]) -> dict[str, Any]:
    runtime = health.get("runtime") or {}
    llm = runtime.get("llm") or {}
    return {
        "status": health.get("status"),
        "version": health.get("version"),
        "agents": health.get("agents"),
        "skills": health.get("skills"),
        "kb_documents": health.get("kb_documents"),
        "dealer_id": health.get("dealer_id"),
        "storage_backend": health.get("storage_backend"),
        "rag": health.get("rag"),
        "orchestration": health.get("orchestration"),
        "runtime": {
            "app_version": runtime.get("app_version"),
            "build_sha": runtime.get("build_sha"),
            "prompts": runtime.get("prompts"),
            "knowledge_base": runtime.get("knowledge_base"),
            "llm": {
                "mode": llm.get("mode"),
                "model": llm.get("model"),
                "simple_model": llm.get("simple_model"),
                "complex_model": llm.get("complex_model"),
            },
            "rag_backend": runtime.get("rag_backend"),
        },
    }


def _contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _write_blockers(path: Path, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Демо-запись заблокирована\n\n"
        f"- Время: `{_utc_now()}`\n"
        f"- Причина: {reason}\n"
        "- Ошибка не маскировалась: пакет записи нельзя считать готовым, пока проверка не проходит.\n",
        encoding="utf-8",
    )


def _precheck(base: str) -> dict[str, Any]:
    health, _, _ = _http_json(f"{base}/health", timeout=10.0)
    ready, _, _ = _http_json(f"{base}/ready", timeout=10.0)
    problems: list[str] = []
    if health.get("status") != "ok":
        problems.append(f"/health status={health.get('status')!r}, ожидался ok")
    if health.get("version") != "3.1.0-beta.1":
        problems.append(f"/health version={health.get('version')!r}, ожидалась 3.1.0-beta.1")
    agents = health.get("agents") or []
    if list(agents) != ["SALES_AGENT", "SUPPORT_AGENT", "SERVICE_AGENT", "EMPLOYEE_AGENT"]:
        problems.append(f"/health agents={agents!r}, ожидались 4 специализированных агента")
    if health.get("skills") != 17:
        problems.append(f"/health skills={health.get('skills')!r}, ожидалось 17")
    if ready.get("status") != "ready":
        problems.append(f"/ready status={ready.get('status')!r}, ожидался ready")
    if problems:
        raise RuntimeError("; ".join(problems))
    return {"health": _sanitize_health(health), "ready": _redact(ready)}


def _evaluate_turn(payload: dict[str, Any], elapsed: float, expect: dict[str, Any], max_seconds: float) -> list[str]:
    failures: list[str] = []
    reply = str(payload.get("reply") or "")
    if not reply.strip():
        failures.append("пустой reply")
    if elapsed > max_seconds:
        failures.append(f"время {elapsed:.3f}s > {max_seconds:.0f}s")
    agent = payload.get("agent")
    if "agent" in expect and agent != expect["agent"]:
        failures.append(f"agent {agent} != {expect['agent']}")
    if "agent_any" in expect and agent not in expect["agent_any"]:
        failures.append(f"agent {agent} not in {expect['agent_any']}")
    skill = payload.get("skill")
    if "skill" in expect and skill != expect["skill"]:
        failures.append(f"skill {skill} != {expect['skill']}")
    if "skill_any" in expect and skill not in expect["skill_any"]:
        failures.append(f"skill {skill} not in {expect['skill_any']}")
    rag_ids = payload.get("rag_ids") or []
    if expect.get("require_rag_ids") and not rag_ids:
        failures.append("нет rag_ids")
    if expect.get("forbid_internal_rag") and any(
        str(item).startswith(INTERNAL_RAG_PREFIXES) for item in rag_ids
    ):
        failures.append(f"утечка internal rag_ids={rag_ids}")
    if expect.get("action_must_be_unexecuted"):
        if payload.get("action_id"):
            failures.append("создано внешнее действие без подтверждения сотрудника")
        if payload.get("action_status") not in {None, "waiting_approval"}:
            failures.append(f"action_status={payload.get('action_status')!r}")
    for token in expect.get("reply_contains_any") or []:
        if token.lower() in reply.lower():
            break
    else:
        if expect.get("reply_contains_any"):
            failures.append(f"в reply нет ни одного из {expect['reply_contains_any']}")
    for token in expect.get("reply_not_contains_any") or []:
        if token.lower() in reply.lower():
            failures.append(f"запрещённый фрагмент в reply: {token}")
    if SECRET_RE.search(reply):
        failures.append("в reply обнаружен секретный шаблон")
    return failures


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "session_id": payload.get("session_id"),
        "agent": payload.get("agent"),
        "agent_label": payload.get("agent_label"),
        "skill": payload.get("skill"),
        "escalated": payload.get("escalated"),
        "escalation_target": payload.get("escalation_target"),
        "rag_ids": payload.get("rag_ids") or [],
        "model_route": payload.get("model_route"),
        "routing_reason": payload.get("routing_reason"),
        "routing_intent": payload.get("routing_intent"),
        "routing_risk": payload.get("routing_risk"),
        "action_id": payload.get("action_id"),
        "action_status": payload.get("action_status"),
        "reply": _redact(str(payload.get("reply") or "")),
    }
    return keep


def _markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Фактический прогон демо-сценариев",
        "",
        f"- Время: `{report['generated_at']}`",
        f"- Ветка: `{report['git']['branch']}`",
        f"- Commit: `{report['git']['short_sha']}`",
        f"- API: `{report['base_url']}`",
        f"- Версия: `{report['precheck']['health']['version']}`",
        f"- Агенты: `{len(report['precheck']['health']['agents'])}`",
        f"- Skills: `{report['precheck']['health']['skills']}`",
        f"- LLM: `{report['precheck']['health']['runtime']['llm']['mode']}` / `{report['precheck']['health']['runtime']['llm']['model']}`",
        f"- RAG: `{report['precheck']['health']['runtime']['rag_backend']}`",
        f"- Обязательные сценарии: `{report['required_passed']}/{report['required_total']}`",
        f"- Итог: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "| Запрос | Агент | Skill | model_route | rag_ids | Эскалация | Время, с | Результат |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["turns"]:
        rag = ", ".join(row["rag_ids"]) if row["rag_ids"] else "—"
        lines.append(
            "| {query} | {agent} | {skill} | {route} | {rag} | {esc} | {sec} | {status} |".format(
                query=row["message"].replace("|", "\\|"),
                agent=row["agent"] or "—",
                skill=row["skill"] or "—",
                route=row["model_route"] or "—",
                rag=rag.replace("|", "\\|"),
                esc="да" if row["escalated"] else "нет",
                sec=f"{row['seconds']:.3f}",
                status=row["status"],
            )
        )
    lines.append("")
    lines.append("Цифры только из этого прогона. Ответы модели не подменялись.")
    lines.append("")
    return "\n".join(lines)


def run(base: str, scenarios_path: Path, out_dir: Path) -> dict[str, Any]:
    spec = json.loads(scenarios_path.read_text(encoding="utf-8"))
    max_seconds = float(spec.get("max_seconds") or 30)
    precheck = _precheck(base)
    turns: list[dict[str, Any]] = []
    scenario_rows: list[dict[str, Any]] = []
    required_total = 0
    required_passed = 0

    for scenario in spec["scenarios"]:
        session_id: str | None = None
        scenario_fail: list[str] = []
        for turn in scenario["turns"]:
            payload, elapsed, _status = _http_json(
                f"{base}/api/chat",
                {"message": turn["message"], "session_id": session_id, "channel": "web"},
                timeout=60.0,
            )
            session_id = str(payload.get("session_id") or session_id)
            failures = _evaluate_turn(payload, elapsed, turn.get("expect") or {}, max_seconds)
            status = "FAIL" if failures else "PASS"
            public = _public_payload(payload)
            row = {
                "scenario_id": scenario["id"],
                "title": scenario["title"],
                "message": turn["message"],
                "seconds": round(elapsed, 3),
                "status": status,
                "failures": failures,
                **public,
            }
            turns.append(row)
            if failures:
                scenario_fail.extend(failures)
        required = bool(scenario.get("required", True))
        if required:
            required_total += 1
            if not scenario_fail:
                required_passed += 1
        scenario_rows.append({
            "id": scenario["id"],
            "title": scenario["title"],
            "required": required,
            "status": "FAIL" if scenario_fail else "PASS",
            "failures": scenario_fail,
        })

    passed = required_total == required_passed
    report = {
        "generated_at": _utc_now(),
        "git": _git_identity(),
        "base_url": base,
        "precheck": precheck,
        "passed": passed,
        "required_total": required_total,
        "required_passed": required_passed,
        "scenarios": scenario_rows,
        "turns": turns,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "latest.json"
    summary = out_dir / "summary.md"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary.write_text(_markdown_summary(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Прогон демо-сценариев AutoSfera AI против живого API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    blockers = REPO_ROOT / "demo" / "BLOCKERS.md"
    try:
        report = run(str(args.base_url).rstrip("/"), args.scenarios, args.out_dir)
    except Exception as exc:
        _write_blockers(blockers, str(exc))
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    if blockers.exists():
        blockers.unlink()
    print(
        f"{'PASS' if report['passed'] else 'FAIL'} "
        f"{report['required_passed']}/{report['required_total']} "
        f"-> {args.out_dir / 'latest.json'}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
