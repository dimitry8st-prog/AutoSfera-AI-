#!/usr/bin/env python3
"""Run defense demo questions against a live API. Saves JSON only — no secrets."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent / "captures"
OUT.mkdir(exist_ok=True)

SCENARIOS = [
    ("s1", "Подбери семейный автомобиль стоимостью до 5 миллионов рублей", True),
    ("s2", "Какие документы нужны для оформления сделки?", False),
    ("s3", "Что входит в гарантию и куда обратиться при неисправности?", True),
    ("s4", "Хочу записаться на тест-драйв", True),
    ("s5", "Подтвердите окончательную скидку и измените условия договора", True),
    ("s6", "Расскажи, как приготовить торт", True),
]


def post_chat(message: str, session_id: str | None) -> dict:
    payload = {"message": message, "channel": "web"}
    if session_id:
        payload["session_id"] = session_id
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def slim(data: dict) -> dict:
    return {
        "agent": data.get("agent"),
        "agent_label": data.get("agent_label"),
        "skill": data.get("skill"),
        "escalated": data.get("escalated"),
        "needs_human": data.get("needs_human"),
        "action_id": data.get("action_id"),
        "action_status": data.get("action_status"),
        "rag_ids": data.get("rag_ids") or data.get("sources"),
        "model_route": data.get("model_route"),
        "reply": data.get("reply"),
        "session_id": data.get("session_id"),
    }


def main() -> None:
    session = None
    log = []
    for sid, message, new_chat in SCENARIOS:
        if new_chat:
            session = None
        data = post_chat(message, session)
        session = data.get("session_id")
        rec = {"id": sid, "message": message, "new_chat": new_chat, **slim(data)}
        log.append(rec)
        print(sid, rec.get("agent"), rec.get("skill"), rec.get("escalated"), rec.get("action_id"))
        print(" ", (rec.get("reply") or "")[:180].replace("\n", " "))
    (OUT / "live_replies.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
