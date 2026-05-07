import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.datetime_utils import parse_received_at, to_local


def is_today_intent(query: str) -> bool:
    q = query.lower()
    keywords = (
        "today",
        "this morning",
        "tonight",
        "since this morning",
        "new today",
        "incoming today",
        "emails today",
        "mail today",
        "latest",
        "recent",
        "new",
    )
    return any(k in q for k in keywords)


def wants_important_mail_help(query: str) -> bool:
    q = query.lower()
    hints = (
        "important",
        "priority",
        "urgent",
        "critical",
        "must read",
        "must-read",
        "action items",
        "need to respond",
        "need reply",
    )
    return any(h in q for h in hints)


def filter_important_emails(emails: list[dict]) -> list[dict]:
    return [e for e in emails if bool(e.get("priority"))]


def wants_sales_mail_help(query: str) -> bool:
    q = query.lower()
    hints = (
        "sales",
        "sale",
        "promotion",
        "promotional",
        "promo",
        "offer",
        "discount",
        "deal",
        "marketing",
        "newsletter",
        "product",
    )
    return any(h in q for h in hints)


def filter_sales_emails(emails: list[dict]) -> list[dict]:
    sales_hints = (
        "sale",
        "sales",
        "promo",
        "promotion",
        "offer",
        "discount",
        "deal",
        "coupon",
        "premium",
        "free",
        "trial",
        "livestream",
        "launch",
        "customer engagement",
        "unsubscribe",
    )
    out: list[dict] = []
    for e in emails:
        text = f"{e.get('subject', '')}\n{e.get('body', '')}".lower()
        if any(h in text for h in sales_hints):
            out.append(e)
    return out


def wants_spam_mail_help(query: str) -> bool:
    q = query.lower()
    hints = ("spam", "junk", "phishing", "scam", "unsolicited")
    return any(h in q for h in hints)


def filter_spam_emails(emails: list[dict]) -> list[dict]:
    spam_hints = (
        "unsubscribe",
        "limited time",
        "act now",
        "winner",
        "claim now",
        "free gift",
        "exclusive offer",
        "click here",
        "buy now",
        "congratulations",
        "promo",
        "promotion",
        "discount",
    )
    sender_hints = ("noreply", "no-reply", "donotreply", "mailer-daemon")
    out: list[dict] = []
    for e in emails:
        sender = str(e.get("from") or e.get("sender") or "").lower()
        text = f"{e.get('subject', '')}\n{e.get('body', '')}".lower()
        if any(s in sender for s in sender_hints) or any(h in text for h in spam_hints):
            out.append(e)
    return out


def wants_meeting_calendar_help(query: str) -> bool:
    q = query.lower()
    hard_hints = (
        "meeting",
        "calendar",
        "add to calendar",
        "appointment",
        "invite",
        "invitation",
        "google meet",
        "zoom",
        "teams",
    )
    soft_hints = ("schedule", "book this", "call at", "call")
    if any(h in q for h in hard_hints):
        return True
    if "schedule" in q and "call" in q:
        return True
    if any(h in q for h in soft_hints) and any(t in q for t in ("today", "tomorrow", "am", "pm")):
        return True
    return False


_QUERY_LIMIT_NUM = re.compile(
    r"\b(?:last|latest|first|top|recent|previous|past|summarize|summarise|show|list|give\s+me|read)\s+(\d+)\b"
)
_QUERY_LIMIT_NUM_TRAILING = re.compile(r"\b(\d+)\s+(?:mails?|emails?|messages?)\b")
_QUERY_SINGULAR_CUES = (
    "last mail",
    "last email",
    "last message",
    "latest mail",
    "latest email",
    "latest message",
    "most recent mail",
    "most recent email",
    "most recent message",
    "recent mail",
    "recent email",
    "recent message",
    "first mail",
    "first email",
    "first message",
    "top mail",
    "top email",
    "top message",
    "previous mail",
    "previous email",
    "previous message",
    "the latest",
    "my last",
    "my latest",
)


def resolve_query_limit(query: str, default: int) -> int:
    """How many emails to include in context and reply actions for this query."""
    q = (query or "").lower().strip()
    if not q:
        return default
    for rx in (_QUERY_LIMIT_NUM, _QUERY_LIMIT_NUM_TRAILING):
        m = rx.search(q)
        if m:
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            if n >= 1:
                return min(n, default)
    if any(cue in q for cue in _QUERY_SINGULAR_CUES):
        return 1
    return default


def extract_sender_query(query: str) -> str | None:
    """Return the token after 'from ' if present (e.g. sundar, sundar@gmail.com)."""
    match = re.search(r"from\s+(\S+)", query.lower())
    if not match:
        return None
    return match.group(1).rstrip(".,?!;:")


def filter_by_sender(emails: list[dict], sender_query: str) -> list[dict]:
    """Exact match on full email; substring match on name fragment."""
    q = sender_query.lower().strip()
    if not q:
        return list(emails)
    result: list[dict] = []
    for e in emails:
        sender = (e.get("from") or e.get("sender") or "").lower().strip()
        if not sender:
            continue
        if "@" in q:
            if sender == q:
                result.append(e)
        elif q in sender:
            result.append(e)
    return result


def filter_today(emails: list[dict], tz_name: str) -> list[dict]:
    """Keep emails whose local calendar date equals today in USER_TIMEZONE."""
    tz = ZoneInfo(tz_name)
    today_local = datetime.now(tz).date()
    out: list[dict] = []
    for e in emails:
        try:
            dt_utc = parse_received_at(str(e.get("received_at", "")))
            local_dt = to_local(dt_utc, tz_name)
            if local_dt.date() == today_local:
                out.append(e)
        except (ValueError, TypeError, KeyError):
            continue
    return out
