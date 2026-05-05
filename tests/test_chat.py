import pytest
from fastapi.testclient import TestClient

from app import email_client
from app.cache import EmailCache
from app.config import get_settings


@pytest.fixture
def patch_ask_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ask_ai(
        settings,
        *,
        context: str,
        query: str,
        email_count: int,
        priority_count: int | None = None,
        non_priority_count: int | None = None,
        include_calendar_confirmation_guidance: bool = False,
    ) -> str:
        assert email_count >= 0
        assert priority_count is None or priority_count >= 0
        assert non_priority_count is None or non_priority_count >= 0
        if "missingxyz" in query:
            return "Not available in current emails."
        return "mocked-ai-response"

    monkeypatch.setattr("app.routes.chat.ask_ai", fake_ask_ai)


def test_chat_ok(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post("/ai/chat", json={"query": "Summarize emails"})
    assert r.status_code == 200
    data = r.json()
    assert data["response"] == "mocked-ai-response"
    assert "request_id" in data
    assert "cache_age_s" in data
    assert "email_count" in data
    assert "priority_email_count" in data
    assert "other_email_count" in data


def test_chat_not_available_sentence(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post("/ai/chat", json={"query": "missingxyz"})
    assert r.status_code == 200
    assert r.json()["response"] == "Not available in current emails."


def test_chat_sender_filter_no_match(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post(
        "/ai/chat", json={"query": "anything from nobody_xyz_123@nowhere.test"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["response"] == "Not available in current emails."
    assert data["email_count"] == 0


def test_chat_sender_filter_match(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post(
        "/ai/chat", json={"query": "summarize from customer@gmail.com"}
    )
    assert r.status_code == 200
    assert r.json()["response"] == "mocked-ai-response"


def test_chat_returns_empty_batch_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _empty(*_a, **_k):
        return []

    monkeypatch.setattr("app.routes.chat.fetch_emails", _empty)
    r = client.post("/ai/chat", json={"query": "summarize"})
    assert r.status_code == 200
    assert r.json()["response"] == "No emails found in the current batch."
    assert r.json()["email_count"] == 0


async def _boom(*_a, **_k):
    raise email_client.EmailAPIError("down")


def test_chat_503_when_email_api_fails_and_no_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Must disable mock path so fetch_emails reaches the HTTP branch (patched to fail).
    monkeypatch.setenv("MOCK_EMAILS", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(email_client, "fetch_emails", _boom)
    client.app.state.cache = EmailCache(get_settings().cache_ttl_seconds)

    r = client.post("/ai/chat", json={"query": "hello"})
    assert r.status_code == 503
    body = r.json()
    assert "error" in body
    assert "unavailable" in body["error"].lower()
    assert "request_id" in body
    get_settings.cache_clear()


def test_chat_sanitize_layer_deduplicates_and_validates_output(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _dupes(*_a, **_k):
        return [
            {
                "from": "user@example.com",
                "subject": "Login alert",
                "body": "Use 123456",
                "received_at": "2026-04-22T08:30:00Z",
            },
            {
                "from": " USER@example.com ",
                "subject": " login alert ",
                "body": "Use 987654",
                "received_at": "2026-04-22T08:30:01Z",
            },
        ]

    async def _fake_ask_ai(
        settings,
        *,
        context: str,
        query: str,
        email_count: int,
        priority_count: int | None = None,
        non_priority_count: int | None = None,
        include_calendar_confirmation_guidance: bool = False,
    ) -> str:
        assert email_count == 1
        assert priority_count == 1
        assert non_priority_count == 0
        assert context.count("Email #") == 1
        return "As an AI language model,\nYour login code is 123456."

    monkeypatch.setattr("app.routes.chat.fetch_emails", _dupes)
    monkeypatch.setattr("app.routes.chat.ask_ai", _fake_ask_ai)

    r = client.post("/ai/chat", json={"query": "summarize"})
    assert r.status_code == 200
    assert r.json()["response"] == "Your login code is [REDACTED_CODE]."
    assert r.json()["priority_email_count"] == 1
    assert r.json()["other_email_count"] == 0


def test_chat_returns_calendar_proposals_for_meeting_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _meetings(*_a, **_k):
        return [
            {
                "id": "m1",
                "from": "team@example.com",
                "subject": "Project meeting tomorrow",
                "body": "Meeting tomorrow 9 PM IST",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _meetings)

    r = client.post(
        "/ai/chat",
        json={"query": "any meeting tomorrow?", "client_session_id": "sess-a"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["calendar_proposals"] is not None
    assert len(data["calendar_proposals"]) == 1
    assert data["calendar_proposals"][0]["proposal_id"]


def test_chat_calendar_dismiss_flow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _meetings(*_a, **_k):
        return [
            {
                "id": "m1",
                "from": "team@example.com",
                "subject": "Project meeting tomorrow",
                "body": "Meeting tomorrow 9 PM IST",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _meetings)
    first = client.post(
        "/ai/chat",
        json={"query": "any meeting tomorrow?", "client_session_id": "sess-b"},
    ).json()
    pid = first["calendar_proposals"][0]["proposal_id"]

    r = client.post(
        "/ai/chat",
        json={
            "query": "ignore",
            "client_session_id": "sess-b",
            "calendar_action": "dismiss",
            "calendar_proposal_id": pid,
        },
    )
    assert r.status_code == 200
    assert "ignore" in r.json()["response"].lower()


def test_chat_calendar_approve_flow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _meetings(*_a, **_k):
        return [
            {
                "id": "m1",
                "from": "team@example.com",
                "subject": "Project meeting tomorrow",
                "body": "Meeting tomorrow 9 PM IST",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    class _Result:
        created = True
        duplicate = False

    async def _fake_create_event(self, **_kwargs):
        return _Result()

    monkeypatch.setattr("app.routes.chat.fetch_emails", _meetings)
    monkeypatch.setattr(
        "app.google_calendar.GoogleCalendarClient.create_event",
        _fake_create_event,
    )
    first = client.post(
        "/ai/chat",
        json={"query": "any meeting tomorrow?", "client_session_id": "sess-c"},
    ).json()
    pid = first["calendar_proposals"][0]["proposal_id"]

    r = client.post(
        "/ai/chat",
        json={
            "query": "approve",
            "client_session_id": "sess-c",
            "calendar_action": "approve",
            "calendar_proposal_id": pid,
        },
    )
    assert r.status_code == 200
    assert "added" in r.json()["response"].lower()


def test_chat_ai_fallback_calendar_proposal_requires_time_and_date(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "m2",
                "from": "noreply@example.com",
                "subject": "Status update",
                "body": "Please review the report.",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    async def _fallback_ai(
        settings,
        *,
        context: str,
        query: str,
        email_count: int,
        priority_count: int | None = None,
        non_priority_count: int | None = None,
        include_calendar_confirmation_guidance: bool = False,
    ) -> str:
        return "You have a meeting tomorrow at 9 PM."

    monkeypatch.setenv("CALENDAR_SCHEDULING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.ask_ai", _fallback_ai)

    r = client.post(
        "/ai/chat",
        json={"query": "Any meeting tomorrow?", "client_session_id": "sess-fallback"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["calendar_proposals"] is not None
    assert len(data["calendar_proposals"]) == 1
    assert data["calendar_proposals"][0]["confidence"] <= 0.35
    get_settings.cache_clear()


def test_chat_rejects_empty_query_without_reply_action(client: TestClient) -> None:
    r = client.post("/ai/chat", json={"query": "", "client_session_id": "sess-empty"})
    assert r.status_code == 422


def test_chat_important_mail_without_today_still_gets_reply_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "p1",
                "from": "github@example.com",
                "subject": "Security",
                "body": "sudo code",
                "received_at": "2026-05-04T12:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "any important mail?", "client_session_id": "sess-reply-no-today"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("email_actions")
    assert len(data["email_actions"]) >= 1


def test_chat_important_today_returns_email_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "r1",
                "from": "hr@example.com",
                "subject": "Interview slot",
                "body": "Please confirm your interview.",
                "received_at": "2026-05-04T12:00:00Z",
            },
            {
                "id": "r2",
                "from": "news@example.com",
                "subject": "Weekly digest",
                "body": "Top stories this week.",
                "received_at": "2026-05-04T11:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    r = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-a"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("email_actions")
    assert 1 <= len(data["email_actions"]) <= 2


def test_chat_important_today_fallback_uses_latest_two_when_no_priority(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "n1",
                "from": "a@example.com",
                "subject": "Note one",
                "body": "Short body alpha.",
                "received_at": "2026-05-04T14:00:00Z",
            },
            {
                "id": "n2",
                "from": "b@example.com",
                "subject": "Note two",
                "body": "Short body beta.",
                "received_at": "2026-05-04T13:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    r = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-fb"},
    )
    assert r.status_code == 200
    assert len(r.json()["email_actions"]) == 2


def test_chat_reply_draft_and_send_demo_mode(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "r1",
                "from": "hr@example.com",
                "subject": "Interview slot",
                "body": "Please confirm your interview.",
                "received_at": "2026-05-04T12:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    first = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-b"},
    ).json()
    aid = first["email_actions"][0]["action_id"]

    async def _fake_draft(
        settings,
        *,
        from_addr: str,
        subject: str,
        body_plain: str,
    ) -> str:
        return "Mock draft body."

    monkeypatch.setattr("app.routes.chat.generate_reply_draft", _fake_draft)

    d = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-b",
            "email_reply_action": "draft",
            "email_reply_action_id": aid,
        },
    ).json()
    assert d.get("reply_composer")
    assert d["reply_composer"]["body"] == "Mock draft body."

    monkeypatch.setenv("GMAIL_SEND_ENABLED", "false")
    get_settings.cache_clear()
    sent = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-b",
            "email_reply_action": "send",
            "email_reply_action_id": aid,
            "reply_to": "hr@example.com",
            "reply_subject": "Re: Interview slot",
            "reply_body": "Thanks.",
        },
    ).json()
    assert "Sending not configured (demo mode)" in sent["response"]
    get_settings.cache_clear()
