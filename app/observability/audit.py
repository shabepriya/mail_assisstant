"""Structured audit logging for /v1 tool calls."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

logger = logging.getLogger("app.audit")


def log_tool_event(
    event: str,
    *,
    request_id: str,
    request: Request | None = None,
    correlation_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    cid = correlation_id
    if request is not None:
        cid = cid or getattr(request.state, "correlation_id", None)
    payload: dict[str, Any] = {"event": event, "request_id": request_id}
    if cid:
        payload["correlation_id"] = cid
    if extra:
        payload.update(extra)
    logger.info("tool_event %s", payload)
