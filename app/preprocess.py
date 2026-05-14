import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from app.datetime_utils import parse_received_at
from app.filters import (
    is_trusted_system_sender,
)

SENSITIVE_CODE_PATTERN = re.compile(r"\b\d{4,8}\b")
PRIORITY_KEYWORDS = (
    "otp",
    "verification",
    "verification code",
    "login",
    "security",
    "security alert",
    "new sign-in",
    "new sign in",
    "sign-in attempt",
    "password",
    "password reset",
    "interview",
    "hr",
    "deadline",
    "action required",
    "urgent",
    "important",
    "schedule",
    "pull request",
    "billing notice",
)


def deduplicate_by_id(emails: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for e in emails:
        eid = str(e.get("id", ""))
        if not eid or eid in seen:
            continue
        seen.add(eid)
        unique.append(e)
    return unique


def sort_by_received_at_desc(emails: list[dict]) -> None:
    def key_fn(e: dict) -> datetime:
        try:
            return parse_received_at(str(e.get("received_at", "")))
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=UTC)

    emails.sort(key=key_fn, reverse=True)


def clean_body(raw: str, max_body_chars: int) -> str:
    truncated = (raw or "")[:max_body_chars]
    soup = BeautifulSoup(truncated, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def truncate_body_raw(raw: str, max_body_chars: int) -> str:
    return (raw or "")[:max_body_chars]


def normalize_sender_field(e: dict) -> str:
    """Lower/strip from or sender for display and matching consistency."""
    raw = e.get("from") or e.get("sender") or "unknown"
    return str(raw).lower().strip() or "unknown"


def _normalize_subject(subject: object) -> str:
    return str(subject or "").lower().strip()


def _stable_email_key(e: dict) -> str | tuple[str, str]:
    email_id = str(e.get("id") or "").strip()
    if email_id:
        return email_id
    sender = normalize_sender_field(e)
    subject = _normalize_subject(e.get("subject"))
    return (sender, subject)


def sanitize_emails(emails: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    seen: set[str | tuple[str, str]] = set()
    for email in emails:
        cloned = dict(email)
        key = _stable_email_key(cloned)
        if key in seen:
            continue
        seen.add(key)

        body = str(cloned.get("body", ""))
        redacted_body = SENSITIVE_CODE_PATTERN.sub("[REDACTED_CODE]", body)
        cloned["body"] = redacted_body

        subject = str(cloned.get("subject", ""))
        text_blob = f"{subject}\n{redacted_body}".lower()
        cloned["priority"] = is_trusted_system_sender(cloned) or any(
            keyword in text_blob for keyword in PRIORITY_KEYWORDS
        )
        sanitized.append(cloned)
    return sanitized


def emails_to_context(emails: list[dict], max_body_chars: int) -> str:
    blocks: list[str] = []
    for i, e in enumerate(emails, start=1):
        account_id = e.get("account_id", "unknown")
        branch = e.get("branch") or "unknown"
        sender = normalize_sender_field(e)
        subject = e.get("subject") or "(no subject)"
        body_raw = str(e.get("body", ""))
        body_t = truncate_body_raw(body_raw, max_body_chars)
        body_text = clean_body(body_t, max_body_chars)
        received = str(e.get("received_at", "") or "").strip() or "(unknown date)"
        blocks.append(
            f"Email #{i}\n"
            f"Account: {account_id}\n"
            f"Branch: {branch}\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Date: {received}\n"
            f"Body: {body_text}"
        )
    return "\n\n".join(blocks)
