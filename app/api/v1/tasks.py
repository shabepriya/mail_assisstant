from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.observability.audit import log_tool_event
from app.security.auth import require_tool_api_key
from app.tools.schemas import TasksFollowupRequest, TasksFollowupResponse

from ._common import bind_correlation, resolve_correlation_id

router = APIRouter(prefix="/tasks", tags=["v1-tasks"])


@router.post("/followup", response_model=TasksFollowupResponse)
async def v1_tasks_followup(
    request: Request,
    body: TasksFollowupRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> TasksFollowupResponse:
    _ = settings
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_tasks_followup", request_id=rid, request=request, extra={"account_id": body.account_id})
    title = body.title.strip() or "Follow-up"
    return TasksFollowupResponse(
        request_id=rid,
        correlation_id=cid,
        ok=True,
        message=f"Recorded follow-up: {title}",
        errors=[],
    )
