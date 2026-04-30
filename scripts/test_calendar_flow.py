"""Manual smoke-test for calendar proposal + approval flow.

Runs against the FastAPI app in-process (TestClient), so you can validate the
full `/ai/chat` behavior even when your inbox has no meeting emails.

Examples:
  python scripts/test_calendar_flow.py --action approve
  python scripts/test_calendar_flow.py --action dismiss
  python scripts/test_calendar_flow.py --real-calendar --action approve
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


async def _fake_meeting_emails(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "meet_1",
            "from": "team@example.com",
            "subject": "Project meeting tomorrow",
            "body": "Let's meet tomorrow at 9 PM IST for release planning.",
            "received_at": "2026-04-22T08:30:00Z",
        }
    ]


@dataclass
class _MockCreateResult:
    created: bool = True
    duplicate: bool = False
    event_id: str | None = "evt_mock_1"


async def _fake_create_event(self, **_kwargs: Any) -> _MockCreateResult:
    return _MockCreateResult()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test calendar proposal flow")
    parser.add_argument(
        "--action",
        choices=("approve", "dismiss"),
        default="approve",
        help="Second-step calendar action to test",
    )
    parser.add_argument(
        "--session-id",
        default="manual-test-session",
        help="client_session_id sent to /ai/chat",
    )
    parser.add_argument(
        "--query",
        default="any meeting tomorrow?",
        help="Initial query to trigger calendar proposal extraction",
    )
    parser.add_argument(
        "--real-calendar",
        action="store_true",
        help="Use real GoogleCalendarClient.create_event instead of mock",
    )
    args = parser.parse_args()

    with TestClient(app) as client:
        if args.real_calendar:
            patchers = [
                patch("app.routes.chat.fetch_emails", _fake_meeting_emails),
            ]
        else:
            patchers = [
                patch("app.routes.chat.fetch_emails", _fake_meeting_emails),
                patch(
                    "app.google_calendar.GoogleCalendarClient.create_event",
                    _fake_create_event,
                ),
            ]

        for p in patchers:
            p.start()
        try:
            print("\n[1/2] Requesting meeting proposal...")
            r1 = client.post(
                "/ai/chat",
                json={
                    "query": args.query,
                    "client_session_id": args.session_id,
                    "force_refresh": False,
                },
            )
            print("status:", r1.status_code)
            data1 = r1.json()
            print("response:", data1.get("response"))
            proposals = data1.get("calendar_proposals") or []
            if not proposals:
                print("FAIL: no calendar_proposals returned.")
                return 1
            proposal_id = proposals[0]["proposal_id"]
            print("proposal_id:", proposal_id)
            print("proposal_start:", proposals[0].get("start_local_display"))

            print(f"\n[2/2] Sending action={args.action}...")
            r2 = client.post(
                "/ai/chat",
                json={
                    "query": args.action,
                    "client_session_id": args.session_id,
                    "calendar_action": args.action,
                    "calendar_proposal_id": proposal_id,
                },
            )
            print("status:", r2.status_code)
            data2 = r2.json()
            print("response:", data2.get("response"))
            if r2.status_code != 200:
                print("FAIL: action request failed.")
                return 1
            print("\nPASS: calendar flow executed successfully.")
            return 0
        finally:
            for p in reversed(patchers):
                p.stop()


if __name__ == "__main__":
    raise SystemExit(main())
