from __future__ import annotations

import uuid

from fastapi import Request


def resolve_correlation_id(request: Request, body_cid: str | None) -> str:
    header = (request.headers.get("X-Correlation-Id") or "").strip()
    if header:
        return header
    if body_cid and body_cid.strip():
        return body_cid.strip()
    return str(uuid.uuid4())


def bind_correlation(request: Request, correlation_id: str) -> None:
    request.state.correlation_id = correlation_id
