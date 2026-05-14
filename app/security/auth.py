"""Tool API authentication."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings


def require_tool_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.tool_require_auth:
        return
    keys = settings.tool_service_api_keys_list
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "TOOL_SERVICE_API_KEYS must be set when TOOL_REQUIRE_AUTH=true"},
        )
    provided = (request.headers.get("X-API-Key") or "").strip()
    if provided not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid or missing X-API-Key"},
        )
