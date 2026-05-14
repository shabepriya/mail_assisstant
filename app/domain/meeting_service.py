from __future__ import annotations

import logging
import os
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import Request

from app.config import Settings
from app.domain.mappers import calendar_payload_from_proposal, meeting_proposal_from_candidate
from app.domain.models import MeetingProposal, ToolError
from app.google_calendar import GoogleCalendarClient
from app.meeting_parser import (
    DATE_HINT_PATTERN,
    TIME_PATTERN,
    extract_meeting_proposals_from_emails,
)
from app.models import CalendarProposalPayload
from app.pending_calendar import PendingProposal
from app.preprocess import clean_body, truncate_body_raw

logger = logging.getLogger(__name__)


def build_fallback_from_ai(
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
    return calendar_payload_from_proposal(
        meeting_proposal_from_candidate(candidate, settings.user_timezone)
    )


async def extract_and_register_proposals(
    request: Request,
    settings: Settings,
    *,
    emails: list[dict],
    session_id: str,
    correlation_id: str | None = None,
    debug_request_id: str | None = None,
) -> list[MeetingProposal]:
    pending_store = request.app.state.pending_calendar
    candidates = extract_meeting_proposals_from_emails(emails, settings)
    if not candidates and os.getenv("DEBUG_MEETING_PARSE", "").strip() in {"1", "true", "yes"}:
        for email in emails:
            subject = str(email.get("subject") or "")
            body = clean_body(
                truncate_body_raw(str(email.get("body") or ""), settings.max_body_chars),
                settings.max_body_chars,
            )
            logger.debug(
                "meeting_parse_clean_text request_id=%s session_id=%s correlation_id=%s subject=%r",
                debug_request_id,
                session_id,
                correlation_id,
                subject,
            )
    out: list[MeetingProposal] = []
    for c in candidates:
        mp = meeting_proposal_from_candidate(c, c.timezone)
        out.append(mp)
        await pending_store.put(
            PendingProposal(
                proposal_id=c.proposal_id,
                session_id=session_id,
                title=c.title,
                start_iso=mp.start_iso,
                end_iso=mp.end_iso,
                timezone=c.timezone,
                confidence=c.confidence,
                summary_for_user=c.summary_for_user,
            )
        )
        await pending_store.mark_confirmation_requested(session_id, c.proposal_id)
    return out


async def schedule_proposal(
    request: Request,
    settings: Settings,
    *,
    session_id: str,
    proposal_id: str,
    correlation_id: str | None = None,
) -> tuple[bool, str, list[ToolError]]:
    _ = correlation_id
    pending_store = request.app.state.pending_calendar
    client = request.app.state.http_client
    proposal = await pending_store.get(session_id, proposal_id)
    if not proposal:
        return False, "Proposal not found or expired.", [
            ToolError(code="NOT_FOUND", message="Unknown proposal_id for session", retryable=False)
        ]
    calendar_client = GoogleCalendarClient(client, settings)
    result = await calendar_client.create_event(
        proposal_id=proposal.proposal_id,
        title=proposal.title,
        start_iso=proposal.start_iso,
        end_iso=proposal.end_iso,
        timezone=proposal.timezone,
    )
    await pending_store.delete(session_id, proposal.proposal_id)
    if result.duplicate:
        return True, "Duplicate event skipped.", []
    if result.created:
        return True, f"Scheduled: {proposal.title}", []
    return False, "Calendar write failed.", [
        ToolError(code="SCHEDULE_FAILED", message="Calendar write failed", retryable=False)
    ]


async def dismiss_proposal(
    request: Request,
    *,
    session_id: str,
    proposal_id: str,
    correlation_id: str | None = None,
) -> str:
    _ = correlation_id
    pending_store = request.app.state.pending_calendar
    await pending_store.delete(session_id, proposal_id)
    return "Okay, I will ignore that calendar suggestion."
