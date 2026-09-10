#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SALES_PASSWORD = os.getenv("DEMO_SALES_PASSWORD", "sales-demo")


def request_json(method: str, path: str, body: dict[str, Any] | None = None,
                 token: str | None = None) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(BASE_URL + path, data=data, headers=headers, method=method), timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload
    except URLError as exc:
        raise RuntimeError(f"API is unavailable at {BASE_URL}: {exc.reason}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    status, ready = request_json("GET", "/ready")
    require(status == 200 and ready.get("status") == "ready", "API is not ready")

    status, chat = request_json(
        "POST", "/api/chat",
        {"message": "Запишите на тест-драйв Nova Drive, телефон +79990000000", "channel": "web"},
    )
    require(status == 200, f"chat failed: {status}")
    action_id = chat.get("action_id")
    require(bool(action_id), "chat did not create an action proposal")
    require(chat.get("action_status") == "waiting_approval", "action bypassed human approval")

    status, auth = request_json(
        "POST", "/api/auth/token", {"username": "sales", "password": SALES_PASSWORD}
    )
    require(status == 200 and auth.get("access_token"), "sales authentication failed")
    token = auth["access_token"]

    status, _ = request_json(
        "POST", f"/api/actions/{action_id}/review", {"decision": "approve"}, token
    )
    require(status == 200, f"approval failed: {status}")

    job: dict[str, Any] = {}
    for _ in range(30):
        status, response = request_json("GET", f"/api/actions/{action_id}", token=token)
        require(status == 200, f"action lookup failed: {status}")
        job = response["job"]
        if job["status"] in {"completed", "failed", "delivery_unknown"}:
            break
        time.sleep(1)

    require(job.get("status") == "completed", f"action ended as {job.get('status')}: {job.get('error')}")
    result = job.get("result") or {}
    require(result.get("provider") == "n8n-sandbox", "callback did not come from the n8n sandbox")
    require(bool(result.get("external_id")), "n8n execution id is missing")

    status, audit = request_json("GET", f"/api/actions/{action_id}/events", token=token)
    require(status == 200, f"audit lookup failed: {status}")
    event_types = [event["event_type"] for event in audit["items"]]
    require(
        event_types == ["proposed", "approved", "dispatch_started", "completed"],
        f"unexpected audit trail: {event_types}",
    )

    print(json.dumps({
        "status": "passed",
        "action_id": action_id,
        "external_id": result["external_id"],
        "events": event_types,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"n8n sandbox smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
