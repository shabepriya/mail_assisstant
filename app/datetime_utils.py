from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def parse_received_at(value: str) -> datetime:
    """Parse ISO8601 received_at; treat Z as UTC."""
    if not value:
        raise ValueError("received_at is empty")
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_local(dt: datetime, tz_name: str) -> datetime:
    return dt.astimezone(ZoneInfo(tz_name))


def start_of_today_utc_iso(tz_name: str) -> str:
    """Midnight at USER_TIMEZONE, expressed as UTC ISO string for ?since=."""
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(UTC)
    return start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
