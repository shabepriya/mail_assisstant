import pytest
from fastapi.testclient import TestClient

from app import email_client
from app.cache import EmailCache
from app.config import get_settings


@pytest.fixture
def patch_ask_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ask_ai(settings, *, context: str, query: str, email_count: int) -> str:
        assert email_count >= 0
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

    async def _fake_ask_ai(settings, *, context: str, query: str, email_count: int) -> str:
        assert email_count == 1
        assert context.count("Email #") == 1
        return "As an AI language model,\nYour login code is 123456."

    monkeypatch.setattr("app.routes.chat.fetch_emails", _dupes)
    monkeypatch.setattr("app.routes.chat.ask_ai", _fake_ask_ai)

    r = client.post("/ai/chat", json={"query": "summarize"})
    assert r.status_code == 200
    assert r.json()["response"] == "Your login code is [REDACTED_CODE]."
