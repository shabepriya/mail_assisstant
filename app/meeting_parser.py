import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.preprocess import clean_body, truncate_body_raw

TIME_PATTERN = re.compile(
    r"\b((?:1[0-2]|0?[1-9])(?:[:.][0-5]\d)?\s*(?:am|pm)|(?:[01]?\d|2[0-3])[:.][0-5]\d)\b",
    re.I,
)
DATE_HINT_PATTERN = re.compile(r"\b(today|tomorrow)\b", re.I)
TZ_TOKEN_PATTERN = re.compile(r"\b(IST|UTC|PST|PDT|EST|EDT|CST|CDT|MST|MDT)\b")
MEETING_KEYWORDS = ("meeting", "google meet", "zoom", "teams", "call")

TZ_MAP = {
    "IST": "Asia/Kolkata",
    "UTC": "UTC",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
}


@dataclass
class MeetingProposalCandidate:
    proposal_id: str
    title: str
    start_local: datetime
    end_local: datetime
    timezone: str
    confidence: float
    summary_for_user: str


def _derive_title(email: dict) -> str:
    subject = str(email.get("subject") or "").strip()
    if subject:
        return subject[:120]
    body = str(email.get("body") or "").strip()
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if first:
        return first[:120]
    return "Meeting"


def _parse_time(text: str) -> tuple[int, int] | None:
    match = TIME_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1).lower().replace(" ", "")
    if raw.endswith(("am", "pm")):
        ampm = raw[-2:]
        clock = raw[:-2]
        if ":" in clock:
            hour_s, minute_s = clock.split(":", 1)
        elif "." in clock:
            hour_s, minute_s = clock.split(".", 1)
        else:
            hour_s, minute_s = clock, "0"
        hour = int(hour_s)
        minute = int(minute_s)
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        return hour, minute

    if ":" in raw:
        hour_s, minute_s = raw.split(":", 1)
    else:
        hour_s, minute_s = raw.split(".", 1)
    return int(hour_s), int(minute_s)


def _parse_date_base(text: str, tz: ZoneInfo) -> datetime | None:
    now = datetime.now(tz)
    date_hit = DATE_HINT_PATTERN.search(text)
    if not date_hit:
        return None
    key = date_hit.group(1).lower()
    if key == "today":
        return now
    if key == "tomorrow":
        return now + timedelta(days=1)
    return None


def _source_timezone(text: str, default_tz: str) -> ZoneInfo:
    match = TZ_TOKEN_PATTERN.search(text)
    if not match:
        return ZoneInfo(default_tz)
    mapped = TZ_MAP.get(match.group(1).upper(), default_tz)
    return ZoneInfo(mapped)


def extract_meeting_proposals_from_emails(
    emails: list[dict], settings: Settings
) -> list[MeetingProposalCandidate]:
    proposals: list[MeetingProposalCandidate] = []
    user_tz = ZoneInfo(settings.user_timezone)

    for email in emails:
        subject = str(email.get("subject") or "")
        body_raw = str(email.get("body") or "")
        clean_text = (
            subject
            + "\n"
            + clean_body(
                truncate_body_raw(body_raw, settings.max_body_chars),
                settings.max_body_chars,
            )
        )
        text_lower = clean_text.lower()
        if not any(keyword in text_lower for keyword in MEETING_KEYWORDS):
            continue

        source_tz = _source_timezone(clean_text, settings.user_timezone)
        date_base = _parse_date_base(clean_text, source_tz)
        time_hit = _parse_time(clean_text)
        if not date_base or not time_hit:
            continue

        hour, minute = time_hit
        start_source = date_base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        start_local = start_source.astimezone(user_tz)
        end_local = start_local + timedelta(minutes=settings.calendar_default_duration_minutes)

        confidence = 0.92
        if TZ_TOKEN_PATTERN.search(clean_text):
            confidence += 0.03
        if "?" in clean_text:
            confidence -= 0.1
        confidence = max(0.0, min(1.0, confidence))

        start_display = start_local.strftime("%Y-%m-%d %I:%M %p")
        proposals.append(
            MeetingProposalCandidate(
                proposal_id=f"prop_{uuid.uuid4().hex[:12]}",
                title=_derive_title(email),
                start_local=start_local,
                end_local=end_local,
                timezone=settings.user_timezone,
                confidence=confidence,
                summary_for_user=f"Meeting: {start_display} ({settings.user_timezone})",
            )
        )
    return proposals
