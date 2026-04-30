"""One-time OAuth login: saves token JSON for GOOGLE_CALENDAR_TOKEN_PATH.

Run from repo root after placing OAuth client secrets JSON:

  pip install google-auth-oauthlib
  python scripts/calendar_oauth_setup.py path/to/client_secret.json token.json

Or set CREDENTIALS_JSON and TOKEN_JSON env vars.

Uses scope ``calendar.events`` (enough for create/update inserts).
"""

from __future__ import annotations

import argparse
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Google Calendar OAuth token file")
    parser.add_argument(
        "credentials_json",
        nargs="?",
        default=os.environ.get("CREDENTIALS_JSON", ""),
        help="OAuth client secrets JSON path (desktop app)",
    )
    parser.add_argument(
        "token_out",
        nargs="?",
        default=os.environ.get("TOKEN_JSON", "token.json"),
        help="Output path for authorized user credentials",
    )
    args = parser.parse_args()
    if not args.credentials_json:
        print("Missing credentials path. Pass CREDENTIALS_JSON or first argument.", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials_json, SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = args.token_out
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(f"Saved token to {token_path}")
    print("Set in .env: GOOGLE_CALENDAR_TOKEN_PATH=<abs path>")
    print("Enable: CALENDAR_SCHEDULING_ENABLED=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
