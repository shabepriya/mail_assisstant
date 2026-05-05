import asyncio
import logging
from email.utils import parseaddr
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.config import Settings
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


def extract_header(headers: Any, name: str) -> str:
    if not isinstance(headers, list):
        return ""
    for header in headers:
        if not isinstance(header, dict):
            continue
        key = str(header.get("name", "")).strip().lower()
        if key == name.lower():
            return str(header.get("value", "")).strip()
    return ""


def _extract_received_at_iso(raw_email: dict[str, Any]) -> str:
    headers = raw_email.get("payload", {}).get("headers", [])
    date_raw = extract_header(headers, "Date")
    if not date_raw:
        return ""
    try:
        dt = parsedate_to_datetime(date_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return ""


def _normalize_sender(raw_sender: str) -> str:
    _, email_addr = parseaddr(raw_sender)
    normalized = (email_addr or raw_sender).lower().strip()
    return normalized or "unknown"


def _extract_body(raw_email: dict[str, Any]) -> str:
    body = raw_email.get("body") or raw_email.get("snippet") or ""
    return str(body)


def normalize_email(raw_email: dict[str, Any], account_id: str) -> dict[str, Any]:
    payload = raw_email.get("payload", {})
    headers = payload.get("headers", [])
    return {
        "id": str(raw_email.get("id", "")).strip(),
        "account_id": str(
            raw_email.get("account_id")
            or raw_email.get("accountId")
            or account_id
            or "unknown"
        ),
        "from": _normalize_sender(extract_header(headers, "From")),
        "subject": extract_header(headers, "Subject"),
        "body": _extract_body(raw_email),
        "received_at": _extract_received_at_iso(raw_email),
        "thread_id": str(
            raw_email.get("threadId") or raw_email.get("thread_id") or ""
        ).strip(),
    }


def _extract_message_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("messages", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise EmailAPIError("Email API must return a JSON array or object with message list")


async def fetch_emails(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    for_today: bool,
) -> list[dict]:
    if settings.mock_emails:
        return decrypt_if_needed([dict(e) for e in MOCK_EMAILS], settings)

    if not settings.email_account_id:
        raise EmailAPIError("EMAIL_ACCOUNT_ID is required when MOCK_EMAILS=false")

    from urllib.parse import urlparse, parse_qs

    raw_url = settings.email_api_base_url.strip()
    parsed = urlparse(raw_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)

    headers: dict[str, str] = {"ngrok-skip-browser-warning": "true"}
    if settings.email_api_key:
        headers["Authorization"] = f"Bearer {settings.email_api_key}"

    # Only append params that are not already present in the base URL
    params: dict[str, str] = {}
    if "accountId" not in existing_params:
        params["accountId"] = settings.email_account_id
    if "category" not in existing_params:
        params["category"] = settings.email_category
    if "maxResults" not in existing_params:
        params["maxResults"] = str(settings.email_fetch_limit)
    if "limit" not in existing_params:
        params["limit"] = str(settings.email_fetch_limit)

    url = raw_url

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            messages = _extract_message_list(data)
            normalized = [
                normalize_email(item, settings.email_account_id)
                for item in messages
            ]
            return decrypt_if_needed(normalized, settings)
        except httpx.HTTPStatusError as e:
            last_err = e
            logger.warning(
                "email_fetch_attempt_failed attempt=%s error=%s %s",
                attempt + 1,
                e.response.status_code,
                e.response.text[:200],
            )
            await asyncio.sleep(0.5 * (2**attempt))
        except httpx.HTTPError as e:
            last_err = e
            logger.warning(
                "email_fetch_attempt_failed attempt=%s error=%s: %s",
                attempt + 1,
                type(e).__name__,
                str(e) or repr(e),
            )
            await asyncio.sleep(0.5 * (2**attempt))
        except ValueError as e:
            raise EmailAPIError("Invalid JSON from email API") from e

    assert last_err is not None
    logger.warning(
        "email_fetch_http_error error=%s: %s",
        type(last_err).__name__,
        str(last_err) or repr(last_err),
    )
    raise EmailAPIError(str(last_err)) from last_err
