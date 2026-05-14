from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.observability.audit import log_tool_event
from app.security.approvals import mint_approval_token
from app.security.auth import require_tool_api_key
from app.tools.schemas import ApprovalIntentRequest, ApprovalIntentResponse

from ._common import bind_correlation, resolve_correlation_id

router = APIRouter(prefix="/approvals", tags=["v1-approvals"])


@router.post("/intent", response_model=ApprovalIntentResponse)
async def v1_approval_intent(
    request: Request,
    body: ApprovalIntentRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> ApprovalIntentResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_approval_intent", request_id=rid, request=request, extra={"action": body.action})
    token = mint_approval_token(settings, action=body.action, payload=body.payload)
    return ApprovalIntentResponse(
        request_id=rid,
        correlation_id=cid,
        approval_token=token,
        expires_in_seconds=900,
    )
