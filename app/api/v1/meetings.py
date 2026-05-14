from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.domain import errors as err_codes
from app.domain.email_pipeline import emails_to_dicts, fetch_normalized_emails
from app.domain.meeting_service import extract_and_register_proposals, schedule_proposal
from app.observability.audit import log_tool_event
from app.security.approvals import verify_approval_token
from app.security.auth import require_tool_api_key
from app.security.idempotency import IdempotencyStore
from app.tools.schemas import (
    MeetingExtractRequest,
    MeetingExtractResponse,
    MeetingProposalRow,
    MeetingScheduleRequest,
    MeetingScheduleResponse,
    ToolErrorItem,
)

from ._common import bind_correlation, resolve_correlation_id

router = APIRouter(prefix="/meeting", tags=["v1-meeting"])


@router.post("/extract", response_model=MeetingExtractResponse)
async def v1_meeting_extract(
    request: Request,
    body: MeetingExtractRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> MeetingExtractResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_meeting_extract", request_id=rid, request=request, extra={"account_id": body.account_id})
    result = await fetch_normalized_emails(
        request,
        settings,
        account_id=body.account_id,
        force_refresh=body.force_refresh,
        for_today=body.for_today,
        apply_query_filters=False,
        correlation_id=cid,
    )
    if not result.ok:
        return MeetingExtractResponse(
            request_id=rid,
            correlation_id=cid,
            success=False,
            proposals=[],
            errors=[ToolErrorItem.from_domain(e) for e in result.errors],
        )
    if not result.emails:
        return MeetingExtractResponse(request_id=rid, correlation_id=cid, proposals=[], errors=[])
    proposals = await extract_and_register_proposals(
        request,
        settings,
        emails=emails_to_dicts(result.emails),
        session_id=body.client_session_id.strip(),
        correlation_id=cid,
        debug_request_id=rid,
    )
    rows = [
        MeetingProposalRow(
            proposal_id=p.proposal_id,
            title=p.title,
            start_iso=p.start_iso,
            end_iso=p.end_iso,
            start_local_display=p.start_local_display,
            timezone=p.timezone,
            confidence=p.confidence,
        )
        for p in proposals
    ]
    return MeetingExtractResponse(request_id=rid, correlation_id=cid, proposals=rows, errors=[])


@router.post("/schedule", response_model=MeetingScheduleResponse)
async def v1_meeting_schedule(
    request: Request,
    body: MeetingScheduleRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> MeetingScheduleResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_meeting_schedule", request_id=rid, request=request, extra={"proposal_id": body.proposal_id})

    idem: IdempotencyStore = request.app.state.idempotency
    idem_key = f"schedule:{body.idempotency_key}" if body.idempotency_key.strip() else None
    if idem_key:
        cached = await idem.get(idem_key)
        if cached is not None:
            return MeetingScheduleResponse.model_validate(cached)

    session_id = body.client_session_id.strip()
    payload = {"proposal_id": body.proposal_id, "client_session_id": session_id}
    if not verify_approval_token(
        settings,
        token=body.approval_token,
        action="meeting_schedule",
        payload=payload,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Invalid or expired approval_token",
                "request_id": rid,
                "errors": [
                    ToolErrorItem(
                        code=err_codes.APPROVAL_INVALID,
                        message="Invalid or expired approval_token",
                        retryable=False,
                    ).model_dump()
                ],
            },
        )

    ok, message, errs = await schedule_proposal(
        request,
        settings,
        session_id=session_id,
        proposal_id=body.proposal_id,
        correlation_id=cid,
    )
    resp = MeetingScheduleResponse(
        request_id=rid,
        correlation_id=cid,
        success=ok,
        ok=ok,
        message=message,
        errors=[ToolErrorItem.from_domain(e) for e in errs],
    )
    if idem_key and ok:
        await idem.set(idem_key, resp.model_dump())
    return resp
