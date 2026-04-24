from datetime import UTC, datetime

from bs4 import BeautifulSoup

from app.datetime_utils import parse_received_at


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
