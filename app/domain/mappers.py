from __future__ import annotations

from app.domain.models import MeetingProposal, NormalizedEmail, ReplyDraft
from app.meeting_parser import MeetingProposalCandidate
from app.models import CalendarProposalPayload, EmailReplyActionPayload, ReplyComposerPayload


def normalized_email_from_dict(d: dict, *, account_id: str = "") -> NormalizedEmail:
    body = str(d.get("body") or "")
    preview = body.replace("\n", " ").strip()
    if len(preview) > 200:
        preview = preview[:197] + "..."
    return NormalizedEmail(
        id=str(d.get("id", "")),
        account_id=str(d.get("account_id") or account_id or "unknown"),
        sender=str(d.get("from") or "unknown"),
        subject=str(d.get("subject") or ""),
        body=body,
        preview=preview or "(no preview)",
        received_at=str(d.get("received_at") or ""),
        thread_id=str(d.get("thread_id") or ""),
        priority=bool(d.get("priority")),
    )


def normalized_emails_from_dicts(rows: list[dict], *, account_id: str = "") -> list[NormalizedEmail]:
    return [normalized_email_from_dict(r, account_id=account_id) for r in rows]


def email_row_from_normalized(e: NormalizedEmail) -> dict[str, str | bool]:
    return {
        "id": e.id,
        "sender": e.sender,
        "subject": e.subject,
        "preview": e.preview,
        "received_at": e.received_at,
        "priority": e.priority,
        "thread_id": e.thread_id,
    }


def meeting_proposal_from_candidate(c: MeetingProposalCandidate, timezone: str) -> MeetingProposal:
    return MeetingProposal(
        proposal_id=c.proposal_id,
        title=c.title,
        start_iso=c.start_local.isoformat(),
        end_iso=c.end_local.isoformat(),
        start_local_display=c.start_local.strftime("%Y-%m-%d %I:%M %p"),
        timezone=timezone,
        confidence=c.confidence,
        summary_for_user=c.summary_for_user,
    )


def calendar_payload_from_proposal(p: MeetingProposal) -> CalendarProposalPayload:
    return CalendarProposalPayload(
        proposal_id=p.proposal_id,
        title=p.title,
        start_iso=p.start_iso,
        end_iso=p.end_iso,
        start_local_display=p.start_local_display,
        timezone=p.timezone,
        confidence=p.confidence,
    )


def meeting_proposal_from_calendar_payload(p: CalendarProposalPayload) -> MeetingProposal:
    return MeetingProposal(
        proposal_id=p.proposal_id,
        title=p.title,
        start_iso=p.start_iso,
        end_iso=p.end_iso,
        start_local_display=p.start_local_display,
        timezone=p.timezone,
        confidence=p.confidence,
    )


def reply_draft_from_composer(
    *,
    reply_handle: str,
    to: str,
    subject: str,
    body: str,
    email_id: str = "",
    thread_id: str = "",
) -> ReplyDraft:
    return ReplyDraft(
        reply_handle=reply_handle,
        to=to,
        subject=subject,
        body=body,
        email_id=email_id,
        thread_id=thread_id,
    )


def composer_from_reply_draft(d: ReplyDraft) -> ReplyComposerPayload:
    return ReplyComposerPayload(
        action_id=d.reply_handle,
        to=d.to,
        subject=d.subject,
        body=d.body,
    )
