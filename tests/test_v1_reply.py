import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.approvals import mint_approval_token


def test_v1_reply_draft(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _draft(*_a, **kwargs):
        return "Draft text here."

    monkeypatch.setattr("app.domain.ai_service.draft_reply", _draft)

    r = client.post(
        "/v1/email/reply/draft",
        json={
            "client_session_id": "sess-v1-draft",
            "from_addr": "hr@example.com",
            "subject": "Interview",
            "body_plain": "Please confirm.",
            "correlation_id": "corr-draft-1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["correlation_id"] == "corr-draft-1"
    assert data["reply_handle"]
    assert data["composer"]["body"] == "Draft text here."


def test_v1_reply_send_without_approval_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "test-signing-secret")
    get_settings.cache_clear()

    r = client.post(
        "/v1/email/reply/send",
        json={
            "client_session_id": "sess-v1-send",
            "reply_handle": "rh-missing",
            "to": "hr@example.com",
            "subject": "Re: Interview",
            "body": "Thanks",
            "approval_token": "invalid-token",
            "idempotency_key": "idem-1",
            "correlation_id": "corr-send-1",
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body["errors"][0]["code"] == "APPROVAL_INVALID"

    get_settings.cache_clear()


def test_v1_reply_send_with_valid_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "test-signing-secret")
    get_settings.cache_clear()
    settings = get_settings()

    # seed pending reply via draft
    async def _draft(*_a, **kwargs):
        return "Body"

    monkeypatch.setattr("app.domain.ai_service.draft_reply", _draft)
    draft = client.post(
        "/v1/email/reply/draft",
        json={
            "client_session_id": "sess-v1-send-ok",
            "from_addr": "hr@example.com",
            "subject": "Interview",
            "body_plain": "Hi",
        },
    ).json()
    handle = draft["reply_handle"]
    payload = {
        "reply_handle": handle,
        "to": "hr@example.com",
        "subject": "Re: Interview",
        "body": "Thanks",
    }
    token = mint_approval_token(settings, action="email_send", payload=payload)

    async def _fake_send(*_a, **kwargs):
        return True, ""

    monkeypatch.setattr("app.domain.reply_service.send_reply_via_service", _fake_send)

    r = client.post(
        "/v1/email/reply/send",
        json={
            "client_session_id": "sess-v1-send-ok",
            "reply_handle": handle,
            "to": "hr@example.com",
            "subject": "Re: Interview",
            "body": "Thanks",
            "approval_token": token,
            "idempotency_key": "idem-ok-1",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    get_settings.cache_clear()
