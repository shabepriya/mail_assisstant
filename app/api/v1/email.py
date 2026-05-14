from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.domain import ai_service, errors as err_codes
from app.domain.email_pipeline import fetch_important_emails, fetch_normalized_emails
from app.domain.mappers import email_row_from_normalized
from app.domain.models import ToolError
from app.observability.audit import log_tool_event
from app.preprocess import emails_to_context
from app.security.auth import require_tool_api_key
from app.tokens import count_tokens
from app.tools.schemas import (
    EmailImportantRequest,
    EmailListRequest,
    EmailListResponse,
    EmailRow,
    EmailSummarizeRequest,
    EmailSummarizeResponse,
    ToolErrorItem,
)

from ._common import bind_correlation, resolve_correlation_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["v1-email"])


def _rows(emails) -> list[EmailRow]:
    return [EmailRow(**email_row_from_normalized(e)) for e in emails]


@router.post("/list", response_model=EmailListResponse)
async def v1_email_list(
    request: Request,
    body: EmailListRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> EmailListResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_email_list", request_id=rid, request=request, extra={"account_id": body.account_id})
    result = await fetch_normalized_emails(
        request,
        settings,
        account_id=body.account_id,
        category=body.category,
        force_refresh=body.force_refresh,
        for_today=body.for_today,
        apply_query_filters=False,
        limit=body.limit,
        correlation_id=cid,
    )
    if not result.ok:
        return EmailListResponse(
            request_id=rid,
            correlation_id=cid,
            success=False,
            emails=[],
            cache={"age_seconds": 0.0, "stale": False},
            errors=[ToolErrorItem.from_domain(e) for e in result.errors],
        )
    return EmailListResponse(
        request_id=rid,
        correlation_id=cid,
        emails=_rows(result.emails),
        cache={"age_seconds": result.cache_age_s, "stale": result.stale},
        errors=[],
    )


@router.post("/important", response_model=EmailListResponse)
async def v1_email_important(
    request: Request,
    body: EmailImportantRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> EmailListResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_email_important", request_id=rid, request=request, extra={"account_id": body.account_id})
    result = await fetch_important_emails(
        request,
        settings,
        account_id=body.account_id,
        category=body.category,
        force_refresh=body.force_refresh,
        for_today=body.for_today,
        limit=body.limit,
        correlation_id=cid,
    )
    if not result.ok:
        return EmailListResponse(
            request_id=rid,
            correlation_id=cid,
            success=False,
            emails=[],
            cache={"age_seconds": 0.0, "stale": False},
            errors=[ToolErrorItem.from_domain(e) for e in result.errors],
        )
    return EmailListResponse(
        request_id=rid,
        correlation_id=cid,
        emails=_rows(result.emails),
        cache={"age_seconds": result.cache_age_s, "stale": result.stale},
        errors=[],
    )


@router.post("/summarize", response_model=EmailSummarizeResponse)
async def v1_email_summarize(
    request: Request,
    body: EmailSummarizeRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_tool_api_key),
) -> EmailSummarizeResponse:
    rid = str(uuid.uuid4())
    cid = resolve_correlation_id(request, body.correlation_id)
    bind_correlation(request, cid)
    log_tool_event("v1_email_summarize", request_id=rid, request=request, extra={"account_id": body.account_id})
    overhead = ai_service.estimate_query_overhead(settings, body.query)
    budget = max(
        500,
        settings.max_context_tokens - settings.context_reserve_tokens - overhead,
    )
    result = await fetch_normalized_emails(
        request,
        settings,
        account_id=body.account_id,
        force_refresh=body.force_refresh,
        for_today=body.for_today,
        apply_query_filters=False,
        trim_budget=budget,
        correlation_id=cid,
    )
    if not result.ok:
        return EmailSummarizeResponse(
            request_id=rid,
            correlation_id=cid,
            success=False,
            summary="",
            email_count=0,
            tokens_used=0,
            errors=[ToolErrorItem.from_domain(e) for e in result.errors],
        )
    emails = result.emails
    if body.email_ids:
        wanted = set(body.email_ids)
        emails = [e for e in emails if e.id in wanted]
    if not emails:
        return EmailSummarizeResponse(
            request_id=rid,
            correlation_id=cid,
            summary="No emails to summarize.",
            email_count=0,
            tokens_used=0,
            errors=[],
        )
    from app.domain.email_pipeline import emails_to_dicts

    prompt_dicts = emails_to_dicts(emails)
    context = emails_to_context(prompt_dicts, settings.max_body_chars)
    priority_count = sum(1 for e in emails if e.priority)
    non_priority_count = len(emails) - priority_count
    overhead2 = ai_service.estimate_query_overhead(
        settings,
        body.query,
        priority_count=priority_count,
        non_priority_count=non_priority_count,
    )
    tokens_used = count_tokens(context, settings.gemini_model) + overhead2
    try:
        summary = await ai_service.summarize_emails(
            settings,
            context=context,
            query=body.query,
            email_count=len(emails),
            priority_count=priority_count,
            non_priority_count=non_priority_count,
            correlation_id=cid,
        )
    except Exception:
        logger.exception("v1_summarize_ai_failed request_id=%s", rid)
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
    return EmailSummarizeResponse(
        request_id=rid,
        correlation_id=cid,
        summary=summary,
        email_count=len(emails),
        tokens_used=tokens_used,
        errors=[],
    )
