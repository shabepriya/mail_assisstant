from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

from app.config import Settings
from app.domain import errors as err_codes
from app.domain.mappers import normalized_emails_from_dicts
from app.domain.models import FetchEmailsResult, NormalizedEmail, ToolError
from app.email_client import EmailAPIError, fetch_emails
from app.filters import (
    extract_sender_query,
    filter_by_sender,
    filter_important_emails,
    filter_order_emails,
    filter_promotional_emails,
    filter_sales_emails,
    filter_spam_emails,
    filter_today,
    wants_important_mail_help,
    wants_order_mail_help,
    wants_sales_mail_help,
    wants_spam_mail_help,
)
from app.preprocess import sanitize_emails, sort_by_received_at_desc
from app.tokens import trim_to_fit

logger = logging.getLogger(__name__)


def fetch_strategy(settings: Settings, for_today: bool) -> str:
    if for_today and settings.email_api_supports_since:
        return "today_since"
    if for_today:
        return "today_bulk"
    return "normal"


def effective_settings(settings: Settings, account_id: str, category: str) -> Settings:
    return settings.model_copy(
        update={"email_account_id": account_id, "email_category": category}
    )


def map_email_api_error(exc: Exception) -> ToolError:
    msg = str(exc)
    if "401" in msg or "session has expired" in msg.lower() or "unauthorized" in msg.lower():
        return ToolError(
            code=err_codes.GMAIL_SESSION_EXPIRED,
            message="Gmail session expired or unauthorized. Reconnect the account.",
            retryable=True,
        )
    return ToolError(
        code=err_codes.GMAIL_FETCH_FAILED,
        message=msg or "Email fetch failed",
        retryable=True,
    )


async def fetch_normalized_emails(
    request: Request,
    settings: Settings,
    *,
    account_id: str | None = None,
    category: str | None = None,
    force_refresh: bool = False,
    for_today: bool = False,
    query: str | None = None,
    apply_query_filters: bool = True,
    trim_budget: int | None = None,
    limit: int | None = None,
    correlation_id: str | None = None,
) -> FetchEmailsResult:
    eff = effective_settings(
        settings,
        account_id or settings.email_account_id,
        category or settings.email_category,
    )
    strategy = fetch_strategy(eff, for_today)
    client = request.app.state.http_client
    cache = request.app.state.cache

    async def _do_fetch() -> list[dict]:
        return await fetch_emails(client, eff, for_today=for_today)

    try:
        raw_emails, cache_age_s, stale = await cache.get(force_refresh, strategy, _do_fetch)
    except EmailAPIError as e:
        logger.warning(
            "email_fetch_failed correlation_id=%s error=%s",
            correlation_id,
            e,
        )
        te = map_email_api_error(e)
        return FetchEmailsResult(errors=[te])
    except Exception as e:
        logger.exception("email_fetch_unexpected correlation_id=%s", correlation_id)
        return FetchEmailsResult(errors=[map_email_api_error(e)])

    emails = sanitize_emails([dict(e) for e in raw_emails])
    if not emails:
        return FetchEmailsResult(cache_age_s=cache_age_s, stale=stale)

    sort_by_received_at_desc(emails)
    filtered_count = len(emails)

    if for_today and eff.email_api_supports_since:
        emails = emails[: eff.max_emails]
        today_only = filter_today(emails, eff.user_timezone)
        emails = today_only or []
        filtered_count = len(emails)
    elif for_today:
        today_only = filter_today(emails, eff.user_timezone)
        emails = (today_only or [])[: eff.max_emails]
        filtered_count = len(emails)
    else:
        emails = emails[: eff.max_emails]
        filtered_count = len(emails)

    if apply_query_filters and query:
        sender_q = extract_sender_query(query)
        if sender_q:
            emails = filter_by_sender(emails, sender_q)
            filtered_count = len(emails)
        elif wants_spam_mail_help(query) and wants_sales_mail_help(query):
            emails = filter_promotional_emails(emails)
            filtered_count = len(emails)
        elif wants_spam_mail_help(query):
            emails = filter_spam_emails(emails)
            filtered_count = len(emails)
        elif wants_order_mail_help(query):
            emails = filter_order_emails(emails)
            filtered_count = len(emails)
        elif wants_sales_mail_help(query):
            emails = filter_sales_emails(emails)
            filtered_count = len(emails)
        elif wants_important_mail_help(query):
            emails = filter_important_emails(emails)
            filtered_count = len(emails)

    if trim_budget is not None and emails:
        emails = trim_to_fit(
            emails,
            trim_budget,
            eff.gemini_model,
            eff.max_body_chars,
            eff.trim_chunk,
        )

    if limit is not None:
        emails = emails[:limit]

    normalized = normalized_emails_from_dicts(emails, account_id=eff.email_account_id)
    return FetchEmailsResult(
        emails=normalized,
        cache_age_s=cache_age_s,
        stale=stale,
        filtered_count=filtered_count,
    )


async def fetch_important_emails(
    request: Request,
    settings: Settings,
    *,
    account_id: str,
    category: str = "inbox",
    force_refresh: bool = False,
    for_today: bool = False,
    limit: int = 20,
    correlation_id: str | None = None,
) -> FetchEmailsResult:
    result = await fetch_normalized_emails(
        request,
        settings,
        account_id=account_id,
        category=category,
        force_refresh=force_refresh,
        for_today=for_today,
        apply_query_filters=False,
        limit=limit,
        correlation_id=correlation_id,
    )
    if not result.ok:
        return result
    important_dicts = filter_important_emails([e.to_dict() for e in result.emails])
    important = normalized_emails_from_dicts(important_dicts[:limit], account_id=account_id)
    return FetchEmailsResult(
        emails=important,
        cache_age_s=result.cache_age_s,
        stale=result.stale,
        filtered_count=len(important),
    )


def emails_to_dicts(emails: list[NormalizedEmail]) -> list[dict[str, Any]]:
    return [e.to_dict() for e in emails]
