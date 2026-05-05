"""Call the external Gmail service for threaded replies (POST /email/send)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


def reply_subject_for_send(subject: str) -> str:
    """Avoid doubling Re: when the composer already has Re: prefix."""
    s = (subject or "").strip()
    if not s.lower().startswith("re:"):
        return f"Re: {s}"
    return s


def _gmail_headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {"ngrok-skip-browser-warning": "true"}
    if settings.email_api_key:
        headers["Authorization"] = f"Bearer {settings.email_api_key}"
    return headers


def _messages_list_path_and_params(
    settings: Settings,
) -> tuple[str, str, str, dict[str, str]]:
    """Return scheme, netloc, messages list path, merged query params."""
    raw = settings.email_api_base_url.strip()
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    merged = parse_qs(parsed.query, keep_blank_values=True)
    params: dict[str, str] = {}
    for k, v in merged.items():
        if v:
            params[k] = v[0]
    if "accountId" not in merged and settings.email_account_id:
        params["accountId"] = settings.email_account_id
    return parsed.scheme, parsed.netloc, path, params


def _send_url(settings: Settings) -> str:
    scheme, netloc, path, _ = _messages_list_path_and_params(settings)
    if not path.endswith("/messages"):
        raise ValueError(
            "EMAIL_API_BASE_URL must end with /messages for Gmail service integration"
        )
    send_path = path[: -len("messages")] + "send"
    return f"{scheme}://{netloc}{send_path}"


def _message_detail_url(settings: Settings, message_id: str) -> str:
    scheme, netloc, path, _ = _messages_list_path_and_params(settings)
    if not path.endswith("/messages"):
        raise ValueError(
            "EMAIL_API_BASE_URL must end with /messages for Gmail service integration"
        )
    detail_path = f"{path}/{message_id}"
    return f"{scheme}://{netloc}{detail_path}"


def _extract_thread_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    tid = data.get("threadId") or data.get("thread_id")
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    inner = data.get("data")
    if isinstance(inner, dict):
        tid2 = inner.get("threadId") or inner.get("thread_id")
        if isinstance(tid2, str) and tid2.strip():
            return tid2.strip()
    return None


async def fetch_thread_id(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    message_id: str,
) -> str | None:
    """GET /email/messages/:id — single attempt, no retries."""
    if not message_id.strip():
        return None
    try:
        url = _message_detail_url(settings)
        _, _, _, params = _messages_list_path_and_params(settings)
        headers = _gmail_headers(settings)
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        return _extract_thread_id(data)
    except Exception:
        logger.exception("fetch_thread_id_failed message_id=%s", message_id)
        return None


async def send_reply_via_service(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    to: str,
    subject: str,
    content: str,
    thread_id: str,
) -> tuple[bool, str]:
    """
    POST /email/send. Retries only on 5xx and network errors (not 4xx).
    Returns (ok, error_message). error_message is empty on success.
    """
    subj = reply_subject_for_send(subject)
    logger.info(
        "gmail_send_attempt thread_id=%s to=%s subject_len=%d",
        thread_id or "(none)",
        to,
        len(subj),
    )

    payload: dict[str, Any] = {
        "to": to,
        "subject": subj,
        "content": content,
    }
    if thread_id.strip():
        payload["threadId"] = thread_id.strip()

    try:
        url = _send_url(settings)
    except ValueError as e:
        logger.warning("gmail_send_bad_config error=%s", e)
        return (False, "Could not send email. Email API URL is not configured correctly.")

    _, _, _, params = _messages_list_path_and_params(settings)
    headers = _gmail_headers(settings)
    headers["Content-Type"] = "application/json"

    last_err: str | None = None
    for attempt in range(3):
        try:
            resp = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
            )
            if 200 <= resp.status_code < 300:
                logger.info("gmail_send_ok thread_id=%s", thread_id or "(none)")
                return (True, "")

            text = resp.text
            if resp.status_code >= 500:
                logger.warning(
                    "gmail_send_failed_retryable attempt=%s status=%s body=%s",
                    attempt + 1,
                    resp.status_code,
                    text[:300],
                )
                last_err = f"HTTP {resp.status_code}"
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            if resp.status_code == 401:
                logger.warning(
                    "gmail_send_failed status=%s body=%s",
                    resp.status_code,
                    text[:300],
                )
                return (
                    False,
                    "Your Gmail session has expired. Please reconnect your Gmail account.",
                )

            logger.warning(
                "gmail_send_failed status=%s body=%s",
                resp.status_code,
                text[:300],
            )
            return (False, "Could not send email. Please try again.")

        except httpx.RequestError as e:
            last_err = str(e) or type(e).__name__
            logger.warning(
                "gmail_send_network_error attempt=%s error=%s",
                attempt + 1,
                last_err,
            )
            await asyncio.sleep(0.5 * (2**attempt))

    logger.warning("gmail_send_exhausted_retries error=%s", last_err or "unknown")
    return (False, "Could not send email. Please try again.")
