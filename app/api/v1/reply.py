from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.domain import errors as err_codes
from app.domain.reply_service import create_reply_draft, send_reply
from app.observability.audit import log_tool_event
from app.security.approvals import verify_approval_token
from app.security.auth import require_tool_api_key
from app.security.idempotency import IdempotencyStore
from app.tools.schemas import (
    ReplyDraftRequest,
    ReplyDraftResponse,
    ReplySendRequest,
    ReplySendResponse,
    ToolErrorItem,
)

from ._common import bind_correlation, resolve_correlation_id

router = APIRouter(prefix="/email/reply", tags=["v1-reply"])


@router.post("/draft", response_model=ReplyDraftResponse)
async def v1_reply_draft(
    request: Request,
    body: ReplyDraftRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> ReplyDraftResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    session_id = body.client_session_id.strip()
    log_tool_event("v1_reply_draft", request_id=rid, request=request, extra={"session_id": session_id})
    try:
        draft = await create_reply_draft(
            request,
            settings,
            session_id=session_id,
            from_addr=body.from_addr,
            subject=body.subject,
            body_plain=body.body_plain,
            email_id=body.email_id,
            thread_id=body.thread_id,
            correlation_id=cid,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "AI service temporarily unavailable.",
                "request_id": rid,
                "errors": [
                    ToolErrorItem(
                        code=err_codes.AI_UNAVAILABLE,
                        message="AI service temporarily unavailable.",
                        retryable=True,
                    ).model_dump()
                ],
            },
        ) from None
    composer = {
        "action_id": draft.reply_handle,
        "to": draft.to,
        "subject": draft.subject,
        "body": draft.body,
    }
    return ReplyDraftResponse(
        request_id=rid,
        correlation_id=cid,
        reply_handle=draft.reply_handle,
        composer=composer,
        errors=[],
    )


@router.post("/send", response_model=ReplySendResponse)
async def v1_reply_send(
    request: Request,
    body: ReplySendRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> ReplySendResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    session_id = body.client_session_id.strip()
    log_tool_event("v1_reply_send", request_id=rid, request=request, extra={"session_id": session_id})

    idem: IdempotencyStore = request.app.state.idempotency
    idem_key = f"send:{body.idempotency_key}"
    cached = await idem.get(idem_key)
    if cached is not None:
        return ReplySendResponse.model_validate(cached)

    payload = {
        "reply_handle": body.reply_handle,
        "to": body.to.strip(),
        "subject": body.subject.strip(),
        "body": body.body.strip(),
    }
    if not verify_approval_token(
        settings,
        token=body.approval_token,
        action="email_send",
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

    ok, message, errs = await send_reply(
        request,
        settings,
        session_id=session_id,
        reply_handle=body.reply_handle,
        to=body.to,
        subject=body.subject,
        body=body.body,
        correlation_id=cid,
    )
    resp = ReplySendResponse(
        request_id=rid,
        correlation_id=cid,
        success=ok,
        ok=ok,
        message=message,
        errors=[ToolErrorItem.from_domain(e) for e in errs],
    )
    if ok:
        await idem.set(idem_key, resp.model_dump())
    return resp
