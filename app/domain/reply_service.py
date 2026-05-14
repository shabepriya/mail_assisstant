from __future__ import annotations

import logging
import re

from fastapi import Request

from app.config import Settings
from app.domain import ai_service
from app.domain.mappers import composer_from_reply_draft, reply_draft_from_composer
from app.domain.models import NormalizedEmail, ReplyDraft, ToolError
from app.gmail_api import fetch_thread_id, send_reply_via_service
from app.models import EmailOpenView, EmailReplyActionPayload, ReplyComposerPayload
from app.pending_reply import PendingReplySnapshot, PendingReplyStore
from app.preprocess import clean_body, truncate_body_raw

logger = logging.getLogger(__name__)

_ADDR_IN_BRACKETS = re.compile(r"<([^<>]+)>")

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


def reply_subject_line(original: str) -> str:
    s = (original or "").strip() or "(no subject)"
    if s.lower().startswith("re:"):
        return s[:500]
    return f"Re: {s}"[:500]


def extract_email(addr: str) -> str:
    if not addr:
        return ""
    m = _ADDR_IN_BRACKETS.search(addr)
    return (m.group(1) if m else addr).strip().lower()


def is_system_sender(addr: str) -> bool:
    email = extract_email(addr)
    if any(tok in email for tok in _SYSTEM_SENDER_TOKENS):
        return True
    return any(domain in email for domain in _SYSTEM_SENDER_DOMAINS)


def select_reply_targets(emails: list[dict], limit: int) -> list[dict]:
    return list(emails[:limit])


async def draft_reply_for_action(
    request: Request,
    settings: Settings,
    *,
    session_id: str,
    action_id: str,
    correlation_id: str | None = None,
) -> tuple[ReplyComposerPayload | None, str]:
    reply_store: PendingReplyStore = request.app.state.pending_reply
    snap = await reply_store.get(session_id, action_id)
    if not snap:
        return None, "That reply action is no longer available. Please ask again."
    try:
        draft_body = await ai_service.draft_reply(
            settings,
            from_addr=snap.from_addr,
            subject=snap.subject,
            body_plain=snap.body_plain,
            correlation_id=correlation_id,
        )
    except Exception:
        logger.exception("reply_draft_failed correlation_id=%s", correlation_id)
        raise
    composer = ReplyComposerPayload(
        action_id=snap.action_id,
        to=snap.from_addr,
        subject=reply_subject_line(snap.subject),
        body=draft_body,
    )
    return composer, "Here is an editable draft based on that email."


async def open_reply_view(
    request: Request,
    *,
    session_id: str,
    action_id: str,
    correlation_id: str | None = None,
) -> tuple[EmailOpenView | None, str]:
    _ = correlation_id
    reply_store: PendingReplyStore = request.app.state.pending_reply
    snap = await reply_store.get(session_id, action_id)
    if not snap:
        return None, "That email is no longer available. Please ask again."
    return (
        EmailOpenView(
            email_id=snap.email_id,
            from_addr=snap.from_addr,
            subject=snap.subject,
            body=snap.body_plain,
        ),
        "Opened email.",
    )


async def register_reply_actions(
    request: Request,
    settings: Settings,
    *,
    session_id: str,
    emails: list[NormalizedEmail],
    limit: int,
    correlation_id: str | None = None,
) -> list[EmailReplyActionPayload]:
    _ = correlation_id
    reply_store: PendingReplyStore = request.app.state.pending_reply
    targets = select_reply_targets([e.to_dict() for e in emails], limit)
    payloads: list[EmailReplyActionPayload] = []
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
        thread_id = str(e.get("thread_id", "")).strip()
        await reply_store.put(
            PendingReplySnapshot(
                action_id=aid,
                session_id=session_id,
                email_id=em_id,
                thread_id=thread_id,
                from_addr=from_addr,
                subject=subj,
                body_plain=plain[:8000],
            )
        )
        payloads.append(
            EmailReplyActionPayload(
                action_id=aid,
                email_id=em_id,
                sender=from_addr,
                sender_email=from_addr if "@" in from_addr else None,
                subject=subj,
                preview=preview or "(no preview)",
                can_reply=not is_system_sender(from_addr),
            )
        )
    return payloads


async def create_reply_draft(
    request: Request,
    settings: Settings,
    *,
    session_id: str,
    from_addr: str,
    subject: str,
    body_plain: str,
    email_id: str = "",
    thread_id: str = "",
    correlation_id: str | None = None,
) -> ReplyDraft:
    reply_store: PendingReplyStore = request.app.state.pending_reply
    aid = PendingReplyStore.new_action_id()
    await reply_store.put(
        PendingReplySnapshot(
            action_id=aid,
            session_id=session_id,
            email_id=email_id,
            thread_id=thread_id,
            from_addr=from_addr.strip(),
            subject=subject.strip() or "(no subject)",
            body_plain=body_plain.strip()[:8000],
        )
    )
    draft_body = await ai_service.draft_reply(
        settings,
        from_addr=from_addr,
        subject=subject,
        body_plain=body_plain,
        correlation_id=correlation_id,
    )
    return reply_draft_from_composer(
        reply_handle=aid,
        to=from_addr,
        subject=reply_subject_line(subject),
        body=draft_body,
        email_id=email_id,
        thread_id=thread_id,
    )


async def send_reply(
    request: Request,
    settings: Settings,
    *,
    session_id: str,
    reply_handle: str,
    to: str,
    subject: str,
    body: str,
    correlation_id: str | None = None,
) -> tuple[bool, str, list[ToolError]]:
    _ = correlation_id
    reply_store: PendingReplyStore = request.app.state.pending_reply
    client = request.app.state.http_client
    snap = await reply_store.get(session_id, reply_handle)
    if not snap:
        return False, "Reply handle not found or expired.", [
            ToolError(code="NOT_FOUND", message="Unknown reply_handle", retryable=False)
        ]
    thread_id = (snap.thread_id or "").strip()
    if not thread_id and snap.email_id:
        fetched = await fetch_thread_id(client, settings, message_id=snap.email_id)
        thread_id = (fetched or "").strip()
    ok, err_msg = await send_reply_via_service(
        client,
        settings,
        to=to.strip(),
        subject=subject.strip(),
        content=body.strip(),
        thread_id=thread_id,
    )
    if not ok:
        return False, err_msg, [
            ToolError(code="SEND_FAILED", message=err_msg, retryable=False)
        ]
    await reply_store.delete(session_id, reply_handle)
    return True, f"Email sent successfully to {to.strip()}", []
