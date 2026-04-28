import asyncio
import httpx
import pytest

from app.config import Settings
from app.email_client import EmailAPIError, fetch_emails, normalize_email


def _settings(**overrides: object) -> Settings:
    return Settings(
        EMAIL_API_BASE_URL="http://localhost:4010/api/google/gmail/email/messages",
        EMAIL_ACCOUNT_ID="acc-1",
        EMAIL_CATEGORY="inbox",
        MOCK_EMAILS=False,
        **overrides,
    )


def test_fetch_emails_accepts_array_payload() -> None:
    payload = [
        {
            "id": "m-1",
            "snippet": "hello",
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Hi"},
                    {"name": "Date", "value": "Tue, 23 Apr 2026 08:30:00 +0000"},
                ]
            },
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["accountId"] == "acc-1"
        assert request.url.params["category"] == "inbox"
        return httpx.Response(status_code=200, json=payload)

    transport = httpx.MockTransport(handler)
    async def run() -> list[dict]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_emails(client, _settings(), for_today=False)

    out = asyncio.run(run())

    assert len(out) == 1
    assert out[0]["id"] == "m-1"
    assert out[0]["account_id"] == "acc-1"
    assert out[0]["from"] == "alice@example.com"
    assert out[0]["subject"] == "Hi"
    assert out[0]["body"] == "hello"
    assert out[0]["received_at"] == "2026-04-23T08:30:00Z"


def test_fetch_emails_accepts_object_wrapped_messages() -> None:
    payload = {
        "messages": [
            {
                "id": "m-2",
                "accountId": "backend-acc",
                "snippet": "wrapped",
                "payload": {"headers": []},
            }
        ]
    }

    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    async def run() -> list[dict]:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_emails(client, _settings(), for_today=True)

    out = asyncio.run(run())

    assert len(out) == 1
    assert out[0]["id"] == "m-2"
    assert out[0]["account_id"] == "backend-acc"
    assert out[0]["from"] == "unknown"
    assert out[0]["subject"] == ""
    assert out[0]["received_at"] == ""


def test_fetch_emails_raises_when_payload_shape_invalid() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True}))

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await fetch_emails(client, _settings(), for_today=False)

    with pytest.raises(EmailAPIError):
        asyncio.run(run())


def test_normalize_email_missing_headers_fallbacks() -> None:
    normalized = normalize_email({"id": "m-3", "snippet": "text"}, "acc-x")
    assert normalized["id"] == "m-3"
    assert normalized["account_id"] == "acc-x"
    assert normalized["from"] == "unknown"
    assert normalized["subject"] == ""
    assert normalized["body"] == "text"
    assert normalized["received_at"] == ""


def test_normalize_email_sender_and_body_priority() -> None:
    normalized = normalize_email(
        {
            "id": "m-4",
            "body": "full-body",
            "snippet": "snippet-body",
            "payload": {"headers": [{"name": "From", "value": "Sundar <sundar@gmail.com>"}]},
        },
        "acc-x",
    )
    assert normalized["from"] == "sundar@gmail.com"
    assert normalized["body"] == "full-body"


def test_normalize_email_prefers_raw_account_id_key() -> None:
    normalized = normalize_email({"id": "m-5", "account_id": "source-acc"}, "fallback-acc")
    assert normalized["account_id"] == "source-acc"
