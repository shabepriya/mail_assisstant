import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai import ask_ai, estimate_overhead_tokens
from app.config import Settings, get_settings
from app.email_client import EmailAPIError, fetch_emails
from app.filters import extract_sender_query, filter_by_sender, filter_today, is_today_intent
from app.models import ChatRequest, ChatResponse
from app.preprocess import deduplicate_by_id, emails_to_context, sort_by_received_at_desc
from app.tokens import count_tokens, trim_to_fit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


def _fetch_strategy(settings: Settings, for_today: bool) -> str:
    if for_today and settings.email_api_supports_since:
        return "today_since"
    if for_today:
        return "today_bulk"
    return "normal"


def _settings_dep() -> Settings:
    return get_settings()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    settings: Settings = Depends(_settings_dep),
) -> ChatResponse:
    request_id = str(uuid.uuid4())
    client = request.app.state.http_client
    cache = request.app.state.cache

    for_today = is_today_intent(body.query)
    strategy = _fetch_strategy(settings, for_today)

    async def _do_fetch():
        return await fetch_emails(client, settings, for_today=for_today)

    try:
        raw_emails, cache_age_s, stale = await cache.get(
            body.force_refresh,
            strategy,
            _do_fetch,
        )
    except EmailAPIError as e:
        logger.warning("email_fetch_failed request_id=%s error=%s", request_id, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Email service unavailable. Please try again later.",
                "request_id": request_id,
            },
        ) from e
    except Exception as e:
        logger.exception("email_fetch_unexpected request_id=%s", request_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Email service unavailable. Please try again later.",
                "request_id": request_id,
            },
        ) from e

    emails = [dict(e) for e in raw_emails]
    emails = deduplicate_by_id(emails)
    sort_by_received_at_desc(emails)

    filtered_count = len(emails)

    if for_today and settings.email_api_supports_since:
        emails = emails[: settings.max_emails]
        today_only = filter_today(emails, settings.user_timezone)
        if not today_only:
            return ChatResponse(
                response="No emails found for today in the current batch.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=cache_age_s,
                tokens_used=0,
                stale=stale,
            )
        emails = today_only
        filtered_count = len(emails)
    elif for_today:
        today_only = filter_today(emails, settings.user_timezone)
        if not today_only:
            return ChatResponse(
                response="No emails found for today in the current batch.",
                request_id=request_id,
                email_count=len(emails),
                filtered_count=0,
                cache_age_s=cache_age_s,
                tokens_used=0,
                stale=stale,
            )
        emails = today_only[: settings.max_emails]
        filtered_count = len(emails)
    else:
        emails = emails[: settings.max_emails]
        filtered_count = len(emails)

    sender_q = extract_sender_query(body.query)
    if sender_q:
        emails = filter_by_sender(emails, sender_q)
        filtered_count = len(emails)
        if not emails:
            return ChatResponse(
                response=f"No emails from {sender_q} in the current batch.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=cache_age_s,
                tokens_used=0,
                stale=stale,
            )

    overhead = estimate_overhead_tokens(settings, body.query)
    budget = max(
        500,
        settings.max_context_tokens - settings.context_reserve_tokens - overhead,
    )
    emails = trim_to_fit(
        emails,
        budget,
        settings.openai_model,
        settings.max_body_chars,
        settings.trim_chunk,
    )
    context = emails_to_context(emails, settings.max_body_chars)
    tokens_used = count_tokens(context, settings.openai_model) + overhead

    final_count = len(emails)

    try:
        answer = await ask_ai(
            settings,
            context=context,
            query=body.query,
            email_count=final_count,
        )
    except Exception:
        logger.exception("openai_failed request_id=%s", request_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "AI service temporarily unavailable.",
                "request_id": request_id,
            },
        ) from None

    return ChatResponse(
        response=answer,
        request_id=request_id,
        email_count=final_count,
        filtered_count=filtered_count,
        cache_age_s=cache_age_s,
        tokens_used=tokens_used,
        stale=stale,
    )
