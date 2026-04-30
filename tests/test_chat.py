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
