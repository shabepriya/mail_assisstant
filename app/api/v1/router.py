from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.security.auth import require_tool_api_key
from app.tools import registry

from . import approvals, email, meetings, reply, tasks

router = APIRouter(prefix="/v1", tags=["v1"])

router.include_router(email.router)
router.include_router(meetings.router)
router.include_router(reply.router)
router.include_router(approvals.router)
router.include_router(tasks.router)


@router.get("/tools/manifest")
async def tools_manifest(
    request: Request,
    _: None = Depends(require_tool_api_key),
) -> dict[str, object]:
    base = str(request.base_url).rstrip("/")
    return {
        "version": registry.TOOLS_MANIFEST_VERSION,
        "openapi_url": f"{base}/openapi.json",
        "tools": registry.TOOLS,
        "error_codes": registry.ERROR_CODES,
    }
