import logging
import os
import re
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai import ask_ai, estimate_overhead_tokens, generate_reply_draft, validate_ai_output
from app.config import Settings, get_settings
from app.email_client import EmailAPIError, fetch_emails
from app.filters import (
    extract_sender_query,
    filter_by_sender,
    filter_today,
    is_today_intent,
    resolve_query_limit,
    wants_meeting_calendar_help,
)
from app.google_calendar import GoogleCalendarClient
from app.meeting_parser import (
    DATE_HINT_PATTERN,
    TIME_PATTERN,
    extract_meeting_proposals_from_emails,
)
from app.gmail_api import fetch_thread_id, send_reply_via_service
from app.models import (
    CalendarProposalPayload,
    ChatRequest,
    ChatResponse,
    EmailOpenView,
    EmailReplyActionPayload,
    ReplyComposerPayload,
)
from app.pending_calendar import PendingProposal
from app.pending_reply import PendingReplySnapshot, PendingReplyStore
from app.preprocess import (
    clean_body,
    emails_to_context,
    sanitize_emails,
    sort_by_received_at_desc,
    truncate_body_raw,
)
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


def _resolve_session_id(request: Request, body: ChatRequest) -> str:
    if body.client_session_id and body.client_session_id.strip():
        return body.client_session_id.strip()
    if request.client and request.client.host:
        return request.client.host
    return "anonymous"


def _is_affirmative_only(query: str) -> bool:
    normalized = query.lower().strip().strip(".!?")
    return normalized in {"yes", "y", "ok", "okay", "approve", "schedule it", "add it"}


def _to_payload(candidate, timezone: str) -> CalendarProposalPayload:
    return CalendarProposalPayload(
        proposal_id=candidate.proposal_id,
        title=candidate.title,
        start_iso=candidate.start_local.isoformat(),
        end_iso=candidate.end_local.isoformat(),
        start_local_display=candidate.start_local.strftime("%Y-%m-%d %I:%M %p"),
        timezone=timezone,
        confidence=candidate.confidence,
    )


def _build_fallback_from_ai(
    answer: str, emails: list[dict], settings: Settings
) -> CalendarProposalPayload | None:
    lowered = answer.lower()
    if "meeting" not in lowered:
        return None
    if TIME_PATTERN.search(answer) is None:
        return None
    if DATE_HINT_PATTERN.search(answer) is None:
        return None
    fallback_email = {"subject": "Meeting reminder", "body": answer}
    parsed = extract_meeting_proposals_from_emails([fallback_email], settings)
    if not parsed:
        return None
    candidate = parsed[0]
    user_tz = ZoneInfo(settings.user_timezone)
    candidate.start_local = candidate.start_local.astimezone(user_tz)
    candidate.end_local = candidate.start_local + timedelta(
        minutes=settings.calendar_default_duration_minutes
    )
    candidate.confidence = 0.35
    candidate.summary_for_user = (
        f"Fallback meeting from assistant answer: "
        f"{candidate.start_local.strftime('%Y-%m-%d %I:%M %p')} ({settings.user_timezone})"
    )
    for email in emails:
        subject = str(email.get("subject") or "").strip()
        body = clean_body(
            truncate_body_raw(str(email.get("body") or ""), settings.max_body_chars),
            settings.max_body_chars,
        )
        text = f"{subject}\n{body}".lower()
        if any(token in text for token in ("meeting", "google meet", "zoom", "teams", "call")):
            candidate.title = subject[:120] if subject else "Meeting"
            break
    return _to_payload(candidate, settings.user_timezone)


def _reply_subject_line(original: str) -> str:
    s = (original or "").strip() or "(no subject)"
    if s.lower().startswith("re:"):
        return s[:500]
    return f"Re: {s}"[:500]


_ADDR_IN_BRACKETS = re.compile(r"<([^<>]+)>")


def _extract_email(addr: str) -> str:
    """Pull the bare address out of 'Name <addr@x>'; otherwise return normalized input."""
    if not addr:
        return ""
    m = _ADDR_IN_BRACKETS.search(addr)
    return (m.group(1) if m else addr).strip().lower()


_SYSTEM_SENDER_TOKENS = (
    "mailer-daemon",
    "postmaster",
    "no-reply",
    "noreply",
    "do-not-reply",
    "donotreply",
    "bounce@",
    "bounces@",
    "automated@",
    "daemon@",
    "system@",
    "notification",
    "notifications",
    "updates@",
    "mailgun",
    "facebookmail",
    "linkedin",
)

_SYSTEM_SENDER_DOMAINS = (
    "mailgun.com",
    "facebookmail.com",
    "linkedin.com",
)


def _is_system_sender(addr: str) -> bool:
    email = _extract_email(addr)
    if any(tok in email for tok in _SYSTEM_SENDER_TOKENS):
        return True
    if any(domain in email for domain in _SYSTEM_SENDER_DOMAINS):
        return True
    return False


def _select_reply_targets(emails: list[dict], limit: int) -> list[dict]:
    """First ``limit`` emails in the same order as the AI context (no filtering)."""
    return list(emails[:limit])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    settings: Settings = Depends(_settings_dep),
) -> ChatResponse:
    request_id = str(uuid.uuid4())
    client = request.app.state.http_client
    cache = request.app.state.cache
    pending_store = request.app.state.pending_calendar
    reply_store: PendingReplyStore = request.app.state.pending_reply
    session_id = _resolve_session_id(request, body)
    calendar_client = GoogleCalendarClient(client, settings)

    if body.email_reply_action == "draft":
        if not body.email_reply_action_id:
            return ChatResponse(
                response="Missing reply action id.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        snap = await reply_store.get(session_id, body.email_reply_action_id)
        if not snap:
            return ChatResponse(
                response="That reply action is no longer available. Please ask again.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        try:
            draft_body = await generate_reply_draft(
                settings,
                from_addr=snap.from_addr,
                subject=snap.subject,
                body_plain=snap.body_plain,
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
        composer = ReplyComposerPayload(
            action_id=snap.action_id,
            to=snap.from_addr,
            subject=_reply_subject_line(snap.subject),
            body=draft_body,
        )
        return ChatResponse(
            response="Here is an editable draft based on that email.",
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
        snap = await reply_store.get(session_id, body.email_reply_action_id)
        if not snap:
            return ChatResponse(
                response="That email is no longer available. Please ask again.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        try:
            draft_body = await generate_reply_draft(
                settings,
                from_addr=snap.from_addr,
                subject=snap.subject,
                body_plain=snap.body_plain,
            )
        except Exception:
            logger.exception("open_view_draft_failed request_id=%s", request_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "AI service temporarily unavailable.",
                    "request_id": request_id,
                },
            ) from None
        composer = ReplyComposerPayload(
            action_id=snap.action_id,
            to=snap.from_addr,
            subject=_reply_subject_line(snap.subject),
            body=draft_body,
        )
        return ChatResponse(
            response="Opened email with editable reply.",
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
            email_open_view=EmailOpenView(
                email_id=snap.email_id,
                from_addr=snap.from_addr,
                subject=snap.subject,
                body=snap.body_plain,
            ),
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
        snap = await reply_store.get(session_id, body.email_reply_action_id)
        if not snap:
            return ChatResponse(
                response="That reply action is no longer available. Please ask again.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        to_addr = (body.reply_to or "").strip()
        subj = (body.reply_subject or "").strip()
        body_txt = (body.reply_body or "").strip()
        if not to_addr or not subj or not body_txt:
            return ChatResponse(
                response="Please fill To, Subject, and Body before sending.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        thread_id = (snap.thread_id or "").strip()
        if not thread_id and snap.email_id:
            fetched = await fetch_thread_id(client, settings, message_id=snap.email_id)
            thread_id = (fetched or "").strip()
            if thread_id:
                logger.info(
                    "thread_id_resolved_lazily email_id=%s thread_id=%s",
                    snap.email_id,
                    thread_id,
                )
            else:
                logger.warning(
                    "thread_id_unresolved email_id=%s — reply may start a new thread",
                    snap.email_id,
                )

        ok, err_msg = await send_reply_via_service(
            client,
            settings,
            to=to_addr,
            subject=subj,
            content=body_txt,
            thread_id=thread_id,
        )
        if not ok:
            return ChatResponse(
                response=err_msg,
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=0.0,
                tokens_used=0,
            )
        await reply_store.delete(session_id, body.email_reply_action_id)
        return ChatResponse(
            response=f"Email sent successfully to {to_addr} ✅",
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=0.0,
            tokens_used=0,
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
            await pending_store.delete(session_id, proposal.proposal_id)
            return ChatResponse(
                response="Okay, I will ignore that calendar suggestion.",
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

    if body.calendar_action is None and _is_affirmative_only(body.query):
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

    # Dedupe is owned by sanitize_emails to keep preprocessing single-responsibility.
    emails = sanitize_emails([dict(e) for e in raw_emails])
    if not emails:
        return ChatResponse(
            response="No emails found in the current batch.",
            request_id=request_id,
            email_count=0,
            filtered_count=0,
            cache_age_s=cache_age_s,
            tokens_used=0,
            stale=stale,
        )
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
                response="Not available in current emails.",
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
        settings.gemini_model,
        settings.max_body_chars,
        settings.trim_chunk,
    )
    if not emails:
        return ChatResponse(
            response="Not available in current emails.",
            request_id=request_id,
            email_count=0,
            filtered_count=filtered_count,
            cache_age_s=cache_age_s,
            tokens_used=0,
            stale=stale,
        )

    query_limit = resolve_query_limit(body.query, settings.reply_action_max)
    emails = emails[:query_limit]

    priority_count = sum(1 for e in emails if bool(e.get("priority")))
    non_priority_count = len(emails) - priority_count

    if wants_meeting_calendar_help(body.query):
        candidates = extract_meeting_proposals_from_emails(emails, settings)
        if not candidates and os.getenv("DEBUG_MEETING_PARSE", "").strip() in {"1", "true", "yes"}:
            for email in emails:
                subject = str(email.get("subject") or "")
                body = clean_body(
                    truncate_body_raw(str(email.get("body") or ""), settings.max_body_chars),
                    settings.max_body_chars,
                )
                logger.debug(
                    "meeting_parse_clean_text request_id=%s session_id=%s subject=%r clean_text=%r",
                    request_id,
                    session_id,
                    subject,
                    f"{subject}\n{body}"[:2000],
                )
        if not candidates:
            return ChatResponse(
                response="No meeting-related emails found.",
                request_id=request_id,
                email_count=0,
                filtered_count=0,
                cache_age_s=cache_age_s,
                tokens_used=0,
                stale=stale,
            )
        if candidates:
            payloads: list[CalendarProposalPayload] = []
            for c in candidates:
                payload = _to_payload(c, c.timezone)
                payloads.append(payload)
                await pending_store.put(
                    PendingProposal(
                        proposal_id=c.proposal_id,
                        session_id=session_id,
                        title=c.title,
                        start_iso=payload.start_iso,
                        end_iso=payload.end_iso,
                        timezone=c.timezone,
                        confidence=c.confidence,
                        summary_for_user=c.summary_for_user,
                    )
                )
                await pending_store.mark_confirmation_requested(session_id, c.proposal_id)

            if len(payloads) == 1:
                confidence_hint = (
                    " (low confidence, please verify)"
                    if payloads[0].confidence < 0.8
                    else ""
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
                email_count=len(emails),
                filtered_count=filtered_count,
                cache_age_s=cache_age_s,
                tokens_used=0,
                priority_email_count=priority_count,
                other_email_count=non_priority_count,
                calendar_proposals=payloads,
                stale=stale,
            )

    context = emails_to_context(emails, settings.max_body_chars)
    overhead = estimate_overhead_tokens(
        settings,
        body.query,
        priority_count=priority_count,
        non_priority_count=non_priority_count,
        include_calendar_confirmation_guidance=False,
    )
    tokens_used = count_tokens(context, settings.gemini_model) + overhead

    final_count = len(emails)

    try:
        answer = await ask_ai(
            settings,
            context=context,
            query=body.query,
            email_count=final_count,
            priority_count=priority_count,
            non_priority_count=non_priority_count,
            include_calendar_confirmation_guidance=False,
        )
        answer = validate_ai_output(answer)
    except Exception:
        logger.exception("openai_failed request_id=%s", request_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "AI service temporarily unavailable.",
                "request_id": request_id,
            },
        ) from None

    email_actions_list: list[EmailReplyActionPayload] | None = None
    if emails:
        targets = _select_reply_targets(emails, query_limit)
        logger.info(
            "reply_actions_attached request_id=%s session_id=%s count=%d total_in_batch=%d",
            request_id,
            session_id,
            len(targets),
            len(emails),
        )
        payloads_actions: list[EmailReplyActionPayload] = []
        for e in targets:
            aid = PendingReplyStore.new_action_id()
            plain = clean_body(
                truncate_body_raw(str(e.get("body") or ""), settings.max_body_chars),
                settings.max_body_chars,
            )
            preview = plain.replace("\n", " ").strip()
            if len(preview) > 200:
                preview = preview[:197] + "..."
            subj = str(e.get("subject") or "(no subject)")[:200]
            from_addr = str(e.get("from") or "unknown")[:320]
            em_id = str(e.get("id", "")).strip()
            await reply_store.put(
                PendingReplySnapshot(
                    action_id=aid,
                    session_id=session_id,
                    email_id=em_id,
                    thread_id=str(e.get("thread_id", "")).strip(),
                    from_addr=from_addr,
                    subject=subj,
                    body_plain=plain[:8000],
                )
            )
            payloads_actions.append(
                EmailReplyActionPayload(
                    action_id=aid,
                    email_id=em_id,
                    sender=from_addr,
                    sender_email=from_addr if "@" in from_addr else None,
                    subject=subj,
                    preview=preview or "(no preview)",
                    can_reply=not _is_system_sender(str(e.get("from", ""))),
                )
            )
        email_actions_list = payloads_actions

    calendar_payloads: list[CalendarProposalPayload] | None = None
    if (
        wants_meeting_calendar_help(body.query)
        and settings.calendar_scheduling_enabled
    ):
        fallback = _build_fallback_from_ai(answer, emails, settings)
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
            await pending_store.mark_confirmation_requested(
                session_id, fallback.proposal_id
            )
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
