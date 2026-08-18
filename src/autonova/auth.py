from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from autonova.config import get_settings


ROLES = frozenset({"guest", "sales", "service", "employee", "admin"})


@dataclass(frozen=True)
class Actor:
    subject: str
    role: str = "guest"
    dealer_id: str = "main-salon"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(subject: str, role: str, dealer_id: str) -> str:
    if role not in ROLES - {"guest"}:
        raise ValueError("unsupported role")
    settings = get_settings()
    now = datetime.now(UTC)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": subject,
        "role": role,
        "dealer_id": dealer_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.auth_token_ttl_minutes)).timestamp()),
    }
    segments = [
        _b64(json.dumps(header, separators=(",", ":")).encode()),
        _b64(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(settings.auth_secret.encode(), signing_input, hashlib.sha256).digest()
    return ".".join([*segments, _b64(signature)])


def decode_token(token: str) -> Actor:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}".encode()
        expected = hmac.new(
            get_settings().auth_secret.encode(), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _unb64(signature_part)):
            raise ValueError("invalid signature")
        header: dict[str, Any] = json.loads(_unb64(header_part))
        payload: dict[str, Any] = json.loads(_unb64(payload_part))
        if header.get("alg") != "HS256" or int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("expired or unsupported token")
        role = str(payload["role"])
        if role not in ROLES - {"guest"}:
            raise ValueError("invalid role")
        return Actor(str(payload["sub"]), role, str(payload["dealer_id"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid access token") from exc


def verify_demo_credentials(username: str, password: str) -> Actor | None:
    settings = get_settings()
    candidates = {
        "admin": (settings.demo_admin_password, "admin"),
        "employee": (settings.demo_employee_password, "employee"),
        "sales": (settings.demo_sales_password, "sales"),
        "service": (settings.demo_service_password, "service"),
    }
    expected = candidates.get(username)
    if expected and hmac.compare_digest(password, expected[0]):
        return Actor(username, expected[1], settings.dealer_id)
    return None


def sign_webhook(payload: bytes) -> str:
    return hmac.new(
        get_settings().research_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()


def verify_webhook(payload: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_webhook(payload), signature)
