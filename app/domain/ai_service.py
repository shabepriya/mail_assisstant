"""Domain AI boundary — sole importer of app.ai for domain and /v1 routes."""

from __future__ import annotations

import logging

from app.ai import ask_ai, generate_reply_draft
from app.config import Settings

logger = logging.getLogger(__name__)


async def summarize_emails(
    settings: Settings,
    *,
    context: str,
    query: str,
    email_count: int,
    priority_count: int | None = None,
    non_priority_count: int | None = None,
    include_calendar_confirmation_guidance: bool = False,
    correlation_id: str | None = None,
) -> str:
    _ = correlation_id
    answer = await ask_ai(
        settings,
        context=context,
        query=query,
        email_count=email_count,
        priority_count=priority_count,
        non_priority_count=non_priority_count,
        include_calendar_confirmation_guidance=include_calendar_confirmation_guidance,
    )
    return answer


async def draft_reply(
    settings: Settings,
    *,
    from_addr: str,
    subject: str,
    body_plain: str,
    correlation_id: str | None = None,
) -> str:
    _ = correlation_id
    return await generate_reply_draft(
        settings,
        from_addr=from_addr,
        subject=subject,
        body_plain=body_plain,
    )


def estimate_query_overhead(
    settings: Settings,
    query: str,
    *,
    priority_count: int | None = None,
    non_priority_count: int | None = None,
    include_calendar_confirmation_guidance: bool = False,
) -> int:
    return 200
