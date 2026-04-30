from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class CalendarInsertResult:
    created: bool
    event_id: str | None = None
    duplicate: bool = False


def _persist_credentials(path: Path, creds: Credentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(creds.to_json(), encoding="utf-8")
    tmp.replace(path)


def _load_and_refresh_credentials(settings: Settings) -> Credentials | None:
    path_str = settings.google_calendar_token_path.strip()
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_file():
        logger.warning("google_calendar_token_path_missing path=%s", path)
        return None
    try:
        # Do not pass scopes= so existing tokens (e.g. full calendar scope) still load.
        creds = Credentials.from_authorized_user_file(str(path), scopes=None)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _persist_credentials(path, creds)
        elif creds.expired and not creds.refresh_token:
            logger.warning("google_calendar_token_expired_no_refresh path=%s", path)
            return None
        return creds if creds.valid else None
    except Exception:
        logger.exception("google_calendar_token_load_failed path=%s", path)
        return None


class GoogleCalendarClient:
    """Calendar writes via google-api-python-client + OAuth (auto-refresh).

    Falls back to raw ``GOOGLE_CALENDAR_TOKEN`` + httpx REST only when no token file is set
    (legacy; access tokens expire without refresh).
    """

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http_client
        self._settings = settings

    def _use_oauth_file(self) -> bool:
        return bool(self._settings.google_calendar_token_path.strip())

    async def _find_existing_by_proposal_oauth(
        self,
        proposal_id: str,
        start_utc: datetime,
        creds: Credentials,
    ) -> bool:
        time_min = (start_utc - timedelta(hours=3)).isoformat()
        time_max = (start_utc + timedelta(hours=3)).isoformat()
        calendar_id = self._settings.google_calendar_id
        marker = f"[proposal_id={proposal_id}]"

        def _sync() -> bool:
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            resp = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    q=marker,
                )
                .execute()
            )
            for item in resp.get("items", []):
                if marker in str(item.get("description", "")):
                    return True
            return False

        return await asyncio.to_thread(_sync)

    async def _find_existing_by_proposal_httpx(
        self,
        proposal_id: str,
        start_utc: datetime,
    ) -> bool:
        token = self._settings.google_calendar_token
        if not token:
            return False
        time_min = (start_utc - timedelta(hours=3)).isoformat()
        time_max = (start_utc + timedelta(hours=3)).isoformat()
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{self._settings.google_calendar_id}/events"
        )
        headers = {"Authorization": f"Bearer {token}"}
        resp = await self._http.get(
            url,
            headers=headers,
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "q": f"[proposal_id={proposal_id}]",
            },
        )
        if resp.status_code >= 400:
            return False
        items = resp.json().get("items", [])
        marker = f"[proposal_id={proposal_id}]"
        return any(marker in str(item.get("description", "")) for item in items)

    async def _create_event_oauth(
        self,
        *,
        proposal_id: str,
        title: str,
        start_iso: str,
        end_iso: str,
        timezone: str,
        creds: Credentials,
    ) -> CalendarInsertResult:
        calendar_id = self._settings.google_calendar_id
        body = {
            "summary": title,
            "description": f"[proposal_id={proposal_id}]",
            "start": {"dateTime": start_iso, "timeZone": timezone},
            "end": {"dateTime": end_iso, "timeZone": timezone},
        }

        def _sync() -> dict:
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            return (
                service.events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )

        try:
            data = await asyncio.to_thread(_sync)
            return CalendarInsertResult(created=True, event_id=data.get("id"))
        except Exception:
            logger.exception("google_calendar_oauth_insert_failed")
            return CalendarInsertResult(created=False)

    async def create_event(
        self,
        *,
        proposal_id: str,
        title: str,
        start_iso: str,
        end_iso: str,
        timezone: str,
    ) -> CalendarInsertResult:
        if not self._settings.calendar_scheduling_enabled:
            return CalendarInsertResult(created=False)

        normalized = start_iso.replace("Z", "+00:00") if start_iso.endswith("Z") else start_iso
        start_dt = datetime.fromisoformat(normalized)

        if self._use_oauth_file():
            creds = _load_and_refresh_credentials(self._settings)
            if not creds or not creds.valid:
                logger.warning("google_calendar_credentials_unavailable")
                return CalendarInsertResult(created=False)

            if await self._find_existing_by_proposal_oauth(
                proposal_id, start_dt, creds
            ):
                return CalendarInsertResult(created=False, duplicate=True)

            return await self._create_event_oauth(
                proposal_id=proposal_id,
                title=title,
                start_iso=start_iso,
                end_iso=end_iso,
                timezone=timezone,
                creds=creds,
            )

        token = self._settings.google_calendar_token
        if not token:
            return CalendarInsertResult(created=False)

        if await self._find_existing_by_proposal_httpx(proposal_id, start_dt):
            return CalendarInsertResult(created=False, duplicate=True)

        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{self._settings.google_calendar_id}/events"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "summary": title,
            "description": f"[proposal_id={proposal_id}]",
            "start": {"dateTime": start_iso, "timeZone": timezone},
            "end": {"dateTime": end_iso, "timeZone": timezone},
        }
        resp = await self._http.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            return CalendarInsertResult(created=False)
        data = resp.json()
        return CalendarInsertResult(created=True, event_id=data.get("id"))
