"""Optional Gmail send using the same OAuth token file as Calendar (requires Gmail scope)."""

from __future__ import annotations

import asyncio
import base64
import logging
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import Settings

logger = logging.getLogger(__name__)


def _persist_credentials(path: Path, creds: Credentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(creds.to_json(), encoding="utf-8")
    tmp.replace(path)


def load_user_credentials(settings: Settings) -> Credentials | None:
    path_str = settings.google_calendar_token_path.strip()
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_file():
        logger.warning("gmail_send_token_path_missing path=%s", path)
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(path), scopes=None)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _persist_credentials(path, creds)
        elif creds.expired and not creds.refresh_token:
            logger.warning("gmail_send_token_expired_no_refresh path=%s", path)
            return None
        return creds if creds.valid else None
    except Exception:
        logger.exception("gmail_send_token_load_failed path=%s", path)
        return None


async def send_plain_message(
    settings: Settings,
    *,
    to_addr: str,
    subject: str,
    body: str,
) -> str:
    """Return user-facing status message."""
    if not settings.gmail_send_enabled:
        return "Sending not configured (demo mode)."

    creds = load_user_credentials(settings)
    if not creds:
        return "Sending not configured (demo mode)."

    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to_addr
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def _sync() -> None:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

    try:
        await asyncio.to_thread(_sync)
        return "Message sent."
    except Exception:
        logger.exception("gmail_send_failed")
        return "Could not send email. Check Gmail API access and OAuth scopes."
