from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, Request, status

from app.config import Settings
from app.domain import ai_service
from app.domain.email_pipeline import emails_to_dicts, fetch_normalized_emails
from app.domain.mappers import calendar_payload_from_proposal
from app.domain.meeting_service import (
    build_fallback_from_ai,
    dismiss_proposal,
    extract_and_register_proposals,
    schedule_proposal,
)
from app.domain.reply_service import (
    draft_reply_for_action,
    extract_email as _extract_email,
    is_system_sender as _is_system_sender,
    open_reply_view,
    register_reply_actions,
    reply_subject_line,
    send_reply,
)
from app.filters import (
    extract_sender_query,
    is_today_intent,
    resolve_query_limit,
    wants_important_mail_help,
    wants_meeting_calendar_help,
    wants_order_mail_help,
    wants_sales_mail_help,
    wants_spam_mail_help,
)
from app.google_calendar import GoogleCalendarClient
from app.models import ChatRequest, ChatResponse
from app.pending_calendar import PendingProposal
from app.preprocess import emails_to_context
from app.tokens import count_tokens

logger = logging.getLogger(__name__)


def resolve_session_id(request: Request, body: ChatRequest) -> str:
    if body.client_session_id and body.client_session_id.strip():
        return body.client_session_id.strip()
    if request.client and request.client.host:
        return request.client.host
    return "anonymous"


def is_affirmative_only(query: str) -> bool:
    normalized = query.lower().strip().strip(".!?")
    return normalized in {"yes", "y", "ok", "okay", "approve", "schedule it", "add it"}


def is_no_match_answer(answer: str) -> bool:
    normalized = (answer or "").strip().lower()
    return normalized in {
        "not available in current emails.",
        "no, you don't have any emergency related emails.",
    }


async def run_chat_turn(
    request: Request,
    body: ChatRequest,
    settings: Settings,
) -> ChatResponse:
    request_id = str(uuid.uuid4())
    pending_store = request.app.state.pending_calendar
    session_id = resolve_session_id(request, body)
    client = request.app.state.http_client
    calendar_client = GoogleCalendarClient(client, settings)

    if body.email_reply_action in {"reply", "draft"}:
        if not body.email_reply_action_id:
            return ChatResponse(
                response="Missing reply action id.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        try:
            composer, msg = await draft_reply_for_action(
                request,
                settings,
                session_id=session_id,
                action_id=body.email_reply_action_id,
            )
        except Exception:
            logger.exception("reply_draft_failed request_id=%s", request_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "AI service temporarily unavailable.",
                    "request_id": request_id,
                },
            ) from None
        if not composer:
            return ChatResponse(
                response=msg,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        return ChatResponse(
            response=msg,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
            reply_composer=composer,
        )

    if body.email_reply_action == "open":
        if not body.email_reply_action_id:
            return ChatResponse(
                response="Missing reply action id.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        view, view_msg = await open_reply_view(
            request,
            session_id=session_id,
            action_id=body.email_reply_action_id,
        )
        if not view:
            return ChatResponse(
                response=view_msg,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        try:
            composer, _ = await draft_reply_for_action(
                request,
                settings,
                session_id=session_id,
                action_id=body.email_reply_action_id,
            )
        except Exception:
            logger.exception("reply_draft_failed request_id=%s", request_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "AI service temporarily unavailable.",
                    "request_id": request_id,
                },
            ) from None
        if not composer:
            return ChatResponse(
                response=view_msg,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
                email_open_view=view,
            )
        return ChatResponse(
            response=view_msg,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
            email_open_view=view,
            reply_composer=composer,
        )

    if body.email_reply_action == "send":
        if not body.email_reply_action_id:
            return ChatResponse(
                response="Missing reply action id.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        to_addr = (body.reply_to or "").strip()
        subject = (body.reply_subject or "").strip()
        content = (body.reply_body or "").strip()
        if not to_addr or not subject or not content:
            return ChatResponse(
                response="Missing reply_to, reply_subject, or reply_body for send.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        ok, message, _errs = await send_reply(
            request,
            settings,
            session_id=session_id,
            reply_handle=body.email_reply_action_id,
            to=to_addr,
            subject=subject,
            body=content,
            correlation_id=request_id,
        )
        if ok:
            message = f"Email sent successfully to {to_addr} ✅"
        return ChatResponse(
            response=message,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
        )

    if body.email_reply_action == "view":
        if not body.email_reply_action_id:
            return ChatResponse(
                response="Missing reply action id.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        view, msg = await open_reply_view(
            request,
            session_id=session_id,
            action_id=body.email_reply_action_id,
        )
        if not view:
            return ChatResponse(
                response=msg,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        return ChatResponse(
            response=msg,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
            email_open_view=view,
        )

    if body.calendar_action in {"approve", "dismiss"}:
        if not body.calendar_proposal_id:
            return ChatResponse(
                response="Please choose a proposal before confirming this action.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        proposal = await pending_store.get(session_id, body.calendar_proposal_id)
        if not proposal:
            return ChatResponse(
                response="That calendar proposal is no longer available. Please ask again.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        if body.calendar_action == "dismiss":
            message = await dismiss_proposal(
                request, session_id=session_id, proposal_id=proposal.proposal_id
            )
            return ChatResponse(
                response=message,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        result = await calendar_client.create_event(
            proposal_id=proposal.proposal_id,
            title=proposal.title,
            start_iso=proposal.start_iso,
            end_iso=proposal.end_iso,
            timezone=proposal.timezone,
        )
        await pending_store.delete(session_id, proposal.proposal_id)
        if result.duplicate:
            message = "This meeting looks already scheduled, so I skipped creating a duplicate event."
        elif result.created:
            message = f"Done. I added '{proposal.title}' to your calendar."
        else:
            message = "I couldn't schedule this event right now. Please try again in a moment."
        return ChatResponse(
            response=message,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
        )

    if body.calendar_action is None and is_affirmative_only(body.query):
        pending = await pending_store.list_for_session(session_id)
        if len(pending) == 1 and pending[0].requested_confirmation:
            proposal = pending[0]
            result = await calendar_client.create_event(
                proposal_id=proposal.proposal_id,
                title=proposal.title,
                start_iso=proposal.start_iso,
                end_iso=proposal.end_iso,
                timezone=proposal.timezone,
            )
            await pending_store.delete(session_id, proposal.proposal_id)
            if result.duplicate:
                message = "This meeting was already on your calendar, so I skipped creating a duplicate."
            elif result.created:
                message = f"Done. I added '{proposal.title}' to your calendar."
            else:
                message = "I couldn't schedule this event right now. Please try again in a moment."
            return ChatResponse(
                response=message,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )

    for_today = is_today_intent(body.query)
    overhead = ai_service.estimate_query_overhead(settings, body.query)
    budget = max(
        500,
        settings.max_context_tokens - settings.context_reserve_tokens - overhead,
    )
    fetch_result = await fetch_normalized_emails(
        request,
        settings,
        force_refresh=body.force_refresh,
        for_today=for_today,
        query=body.query,
        apply_query_filters=True,
        trim_budget=budget,
        correlation_id=request_id,
    )
    if not fetch_result.ok:
        logger.warning(
            "email_fetch_failed request_id=%s errors=%s",
            request_id,
            fetch_result.errors,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Email service unavailable. Please try again later.",
                "request_id": request_id,
            },
        )
    cache_age_s = fetch_result.cache_age_s
    stale = fetch_result.stale
    filtered_count = fetch_result.filtered_count

    if not fetch_result.emails:
        empty_msg = "No emails found in the current batch."
        if for_today:
            empty_msg = "No emails found for today in the current batch."
        if extract_sender_query(body.query):
            empty_msg = "Not available in current emails."
        elif wants_spam_mail_help(body.query):
            empty_msg = "No spam emails found."
        elif wants_important_mail_help(body.query) or wants_order_mail_help(body.query):
            empty_msg = "Not available in current emails."
        elif wants_sales_mail_help(body.query):
            empty_msg = "No sales emails found."
        elif fetch_result.filtered_count > 0:
            empty_msg = "Not available in current emails."
        return ChatResponse(
            response=empty_msg,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=cache_age_s,
            tokens_used=0,
            stale=stale,
        )

    intent_filtered_query = any(
        (
            wants_spam_mail_help(body.query),
            wants_order_mail_help(body.query),
            wants_sales_mail_help(body.query),
            wants_important_mail_help(body.query),
        )
    )

    query_limit = resolve_query_limit(body.query, settings.reply_action_max)
    prompt_emails = fetch_result.emails[:query_limit]
    prompt_dicts = emails_to_dicts(prompt_emails)

    priority_count = sum(1 for e in prompt_emails if e.priority)
    non_priority_count = len(prompt_emails) - priority_count

    if wants_meeting_calendar_help(body.query):
        proposals = await extract_and_register_proposals(
            request,
            settings,
            emails=prompt_dicts,
            session_id=session_id,
            correlation_id=request_id,
            debug_request_id=request_id,
        )
        if not proposals:
            return ChatResponse(
                response="No meeting-related emails found.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=cache_age_s,
                tokens_used=0,
                stale=stale,
            )
        payloads = [calendar_payload_from_proposal(p) for p in proposals]
        if len(payloads) == 1:
            confidence_hint = (
                " (low confidence, please verify)" if payloads[0].confidence < 0.8 else ""
            )
            response_text = (
                f"I found a meeting suggestion: {payloads[0].title} at "
                f"{payloads[0].start_local_display}.{confidence_hint} "
                "Would you like me to add it to your calendar?"
            )
        else:
            options = [
                f"- {p.start_local_display}: {p.title} (proposal_id: {p.proposal_id})"
                for p in payloads
            ]
            response_text = (
                f"I found {len(payloads)} possible meetings. Choose one to add:\n"
                + "\n".join(options)
            )
        return ChatResponse(
            response=response_text,
            request_id=request_id,
            email_count=len(prompt_emails),
            filtered_count=filtered_count,
            cache_age_s=cache_age_s,
            tokens_used=0,
            priority_email_count=priority_count,
            other_email_count=non_priority_count,
            calendar_proposals=payloads,
            stale=stale,
        )

    context = emails_to_context(prompt_dicts, settings.max_body_chars)
    overhead = ai_service.estimate_query_overhead(
        settings,
        body.query,
        priority_count=priority_count,
        non_priority_count=non_priority_count,
        include_calendar_confirmation_guidance=False,
    )
    tokens_used = count_tokens(context, settings.gemini_model) + overhead
    final_count = len(prompt_emails)

    try:
        answer = await ai_service.summarize_emails(
            settings,
            context=context,
            query=body.query,
            email_count=final_count,
            priority_count=priority_count,
            non_priority_count=non_priority_count,
            include_calendar_confirmation_guidance=False,
            correlation_id=request_id,
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

    if intent_filtered_query and is_no_match_answer(answer):
        return ChatResponse(
            response=answer,
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=cache_age_s,
            tokens_used=tokens_used,
            priority_email_count=0,
            other_email_count=0,
            calendar_proposals=None,
            email_actions=None,
            stale=stale,
        )

    email_actions_list = None
    if prompt_emails:
        logger.info(
            "reply_actions_attached request_id=%s session_id=%s count_limit=%d total_in_batch=%d",
            request_id,
            session_id,
            query_limit,
            len(prompt_emails),
        )
        email_actions_list = await register_reply_actions(
            request,
            settings,
            session_id=session_id,
            emails=prompt_emails,
            limit=query_limit,
            correlation_id=request_id,
        )

    calendar_payloads = None
    if wants_meeting_calendar_help(body.query) and settings.calendar_scheduling_enabled:
        fallback = build_fallback_from_ai(answer, prompt_dicts, settings)
        if fallback is not None:
            calendar_payloads = [fallback]
            await pending_store.put(
                PendingProposal(
                    proposal_id=fallback.proposal_id,
                    session_id=session_id,
                    title=fallback.title,
                    start_iso=fallback.start_iso,
                    end_iso=fallback.end_iso,
                    timezone=fallback.timezone,
                    confidence=fallback.confidence,
                    summary_for_user=(
                        "Fallback proposal derived from assistant summary; "
                        "please verify date and time before approving."
                    ),
                )
            )
            await pending_store.mark_confirmation_requested(session_id, fallback.proposal_id)
            answer = (
                f"{answer}\n\nI detected a possible meeting time. "
                "Please verify the date/time and choose Add to Calendar or Ignore."
            )

    return ChatResponse(
        response=answer,
        request_id=request_id,
        email_count=final_count,
        filtered_count=filtered_count,
        cache_age_s=cache_age_s,
        tokens_used=tokens_used,
        priority_email_count=priority_count,
        other_email_count=non_priority_count,
        calendar_proposals=calendar_payloads,
        email_actions=email_actions_list,
        stale=stale,
    )
