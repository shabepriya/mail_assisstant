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


def wants_meeting_calendar_help(query: str) -> bool:
    q = query.lower()
    hints = (
        "meeting",
        "calendar",
        "schedule",
        "add to calendar",
        "book this",
        "tomorrow",
        "today",
        "appointment",
        "call at",
    )
    return any(h in q for h in hints)


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
