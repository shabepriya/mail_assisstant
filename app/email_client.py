import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings
from app.datetime_utils import start_of_today_utc_iso
from app.decrypt import decrypt_if_needed
from app.errors import EmailAPIError

logger = logging.getLogger(__name__)

MOCK_EMAILS: list[dict[str, Any]] = [
    {
        "id": "1",
        "account_id": "acc_east_01",
        "subject": "Order delay",
        "body": "<p>My order is <b>delayed</b> by 3 days. Please help.</p>",
        "from": "customer@gmail.com",
        "branch": "Chennai",
        "received_at": "2026-04-22T08:30:00Z",
    },
    {
        "id": "2",
        "account_id": "acc_west_02",
        "subject": "Complaint: rude staff",
        "body": "I visited the Mumbai branch and staff was rude.",
        "from": "user@example.com",
        "branch": "Mumbai",
        "received_at": "2026-04-21T18:00:00Z",
    },
    {
        "id": "3",
        "subject": "No account_id field",
        "body": "Plain text feedback.",
        "from": "anon@test.com",
        "branch": "Delhi",
        "received_at": "2026-04-22T11:00:00Z",
    },
]


async def fetch_emails(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    for_today: bool,
) -> list[dict]:
    if settings.mock_emails:
        return decrypt_if_needed([dict(e) for e in MOCK_EMAILS], settings)

    base = settings.email_api_base_url.rstrip("/")
    headers: dict[str, str] = {}
    if settings.email_api_key:
        headers["Authorization"] = f"Bearer {settings.email_api_key}"

    if for_today and settings.email_api_supports_since:
        since = start_of_today_utc_iso(settings.user_timezone)
        url = f"{base}/emails?since={since}&limit={settings.max_emails}"
    elif for_today:
        url = f"{base}/emails?limit={settings.today_fetch_limit}"
    else:
        url = f"{base}/emails?limit={settings.max_emails}"

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise EmailAPIError("Email API must return a JSON array")
            out: list[dict] = []
            for item in data:
                if isinstance(item, dict):
                    out.append(dict(item))
            return decrypt_if_needed(out, settings)
        except httpx.HTTPError as e:
            last_err = e
            logger.warning("email_fetch_attempt_failed attempt=%s error=%s", attempt + 1, e)
            await asyncio.sleep(0.5 * (2**attempt))
        except ValueError as e:
            raise EmailAPIError("Invalid JSON from email API") from e

    assert last_err is not None
    logger.warning("email_fetch_http_error error=%s", last_err)
    raise EmailAPIError(str(last_err)) from last_err
