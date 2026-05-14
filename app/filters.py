import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.datetime_utils import parse_received_at, to_local

# Transactional / security — never treat as sales or spam
TRUSTED_SYSTEM_SENDERS = (
    "accounts.google.com",
    "google.com",
    "github.com",
    "gitlab.com",
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "paypal.com",
    "stripe.com",
)

TRANSACTIONAL_SECURITY_KEYWORDS = (
    "security alert",
    "new sign-in",
    "new sign in",
    "sign-in attempt",
    "sign in attempt",
    "password reset",
    "reset your password",
    "verification code",
    "verify your",
    "suspicious sign-in",
    "suspicious login",
    "unusual sign-in",
    "login attempt",
    "authentication code",
    "two-factor",
    "2-step verification",
    "billing notice",
    "invoice #",
    "payment received",
    "pull request",
    "merged pull request",
    "workflow run",
    "issue #",
    "dependabot",
)

# Known marketing / job-board senders (noreply from these is still promotional)
PROMOTIONAL_SENDER_DOMAINS = (
    "linkedin.com",
    "indeed.com",
    "facebookmail.com",
    "mailchimp.com",
    "sendgrid.net",
    "chess.com",
    "substack.com",
)

NOREPLY_SENDER_HINTS = ("noreply", "no-reply", "donotreply", "do-not-reply")

SPAM_BODY_HINTS = (
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
    "promo code",
    "promotional",
)

SALES_BODY_HINTS = (
    "unsubscribe",
    "limited time",
    "exclusive offer",
    "buy now",
    "discount",
    "coupon",
    "% off",
    "free trial",
    "premium for free",
    "get premium",
    "promotional",
    "newsletter",
    "marketing",
    "livestream",
    "customer engagement",
    "better jobs are waiting",
    "jobs waiting for you",
    "job alert",
    "recommended for you",
    "special offer",
    "flash sale",
    "on sale",
)


def _sender_lower(email: dict) -> str:
    return str(email.get("from") or email.get("sender") or "").lower()


def _text_blob(email: dict) -> str:
    return f"{email.get('subject', '')}\n{email.get('body', '')}".lower()


def is_trusted_system_sender(email: dict) -> bool:
    sender = _sender_lower(email)
    return any(domain in sender for domain in TRUSTED_SYSTEM_SENDERS)


def is_protected_transactional_email(email: dict) -> bool:
    """Security alerts, billing, and trusted platform notifications — not sales/spam."""
    if is_trusted_system_sender(email):
        return True
    text = _text_blob(email)
    if any(kw in text for kw in TRANSACTIONAL_SECURITY_KEYWORDS):
        return True
    sender = _sender_lower(email)
    if "github.com" in sender and any(
        k in text for k in ("pull request", "merged", "issue #", "workflow", "review requested")
    ):
        return True
    return False


def is_promotional_sender(email: dict) -> bool:
    sender = _sender_lower(email)
    return any(domain in sender for domain in PROMOTIONAL_SENDER_DOMAINS)


def _has_spam_body_signals(text: str) -> bool:
    return any(h in text for h in SPAM_BODY_HINTS)


def _has_sales_body_signals(text: str) -> bool:
    return any(h in text for h in SALES_BODY_HINTS)


def _is_noreply_sender(sender: str) -> bool:
    return any(h in sender for h in NOREPLY_SENDER_HINTS)


def filter_promotional_emails(emails: list[dict]) -> list[dict]:
    """Union of sales + spam filters, deduped by id."""
    seen: set[str] = set()
    out: list[dict] = []
    for e in filter_sales_emails(emails) + filter_spam_emails(emails):
        eid = str(e.get("id", "")) or id(e)
        if eid in seen:
            continue
        seen.add(eid)
        out.append(e)
    return out


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
        "emergency",
        "emergent",
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
    out: list[dict] = []
    for e in emails:
        if is_protected_transactional_email(e):
            continue
        sender = _sender_lower(e)
        text = _text_blob(e)
        if _has_sales_body_signals(text):
            out.append(e)
        elif is_promotional_sender(e) and any(
            k in text
            for k in (
                "newsletter",
                "digest",
                "recommended",
                "waiting for you",
                "job",
                "offer",
                "unsubscribe",
                "promo",
            )
        ):
            out.append(e)
    return out


def wants_order_mail_help(query: str) -> bool:
    q = query.lower()
    hints = (
        "order",
        "orders",
        "product",
        "purchase",
        "invoice",
        "billing",
        "shipment",
        "tracking",
        "refund",
        "subscription",
    )
    return any(h in q for h in hints)


def filter_order_emails(emails: list[dict]) -> list[dict]:
    order_hints = (
        "order",
        "ordered",
        "order id",
        "invoice",
        "billing",
        "payment",
        "shipment",
        "tracking",
        "delivered",
        "dispatch",
        "purchase",
        "refund",
        "subscription",
        "renewal",
        "product",
    )
    out: list[dict] = []
    for e in emails:
        text = f"{e.get('subject', '')}\n{e.get('body', '')}".lower()
        if any(h in text for h in order_hints):
            out.append(e)
    return out


def wants_spam_mail_help(query: str) -> bool:
    q = query.lower()
    hints = ("spam", "junk", "phishing", "scam", "unsolicited")
    return any(h in q for h in hints)


def filter_spam_emails(emails: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in emails:
        if is_protected_transactional_email(e):
            continue
        sender = _sender_lower(e)
        text = _text_blob(e)
        noreply = _is_noreply_sender(sender)
        if is_promotional_sender(e) and (noreply or _has_spam_body_signals(text) or _has_sales_body_signals(text)):
            out.append(e)
        elif noreply and _has_spam_body_signals(text):
            out.append(e)
        elif _has_spam_body_signals(text):
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
