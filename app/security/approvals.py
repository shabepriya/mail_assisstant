"""HMAC-signed approval tokens for high-risk tool calls."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.config import Settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def mint_approval_token(
    settings: Settings,
    *,
    action: str,
    payload: dict[str, Any],
    ttl_seconds: int = 900,
) -> str:
    secret = (settings.approval_signing_secret or "").strip()
    if not secret:
        return "dev_unverified"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    exp = int(time.time()) + ttl_seconds
    msg = json.dumps({"action": action, "digest": digest, "exp": exp}, separators=(",", ":"))
    sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(msg.encode("utf-8")) + "." + _b64url(sig)


def verify_approval_token(
    settings: Settings,
    *,
    token: str,
    action: str,
    payload: dict[str, Any],
) -> bool:
    secret = (settings.approval_signing_secret or "").strip()
    if not secret:
        return token in {"", "dev_unverified"}
    if token == "dev_unverified":
        return False
    try:
        msg_b, sig_b = token.split(".", 1)
        msg = _b64url_decode(msg_b).decode("utf-8")
        sig = _b64url_decode(sig_b)
    except (ValueError, UnicodeDecodeError):
        return False
    expected_sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        return False
    data = json.loads(msg)
    if data.get("action") != action:
        return False
    if int(data.get("exp", 0)) < int(time.time()):
        return False
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return data.get("digest") == digest
