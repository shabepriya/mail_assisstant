import pytest

from app.config import get_settings
from app.security.approvals import mint_approval_token, verify_approval_token


def test_mint_and_verify_approval_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "unit-test-secret")
    get_settings.cache_clear()
    settings = get_settings()
    payload = {"reply_handle": "rh-1", "to": "a@b.com", "subject": "S", "body": "B"}
    token = mint_approval_token(settings, action="email_send", payload=payload, ttl_seconds=900)
    assert token != "dev_unverified"
    assert verify_approval_token(
        settings, token=token, action="email_send", payload=payload
    )
    get_settings.cache_clear()


def test_verify_rejects_wrong_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "unit-test-secret")
    get_settings.cache_clear()
    settings = get_settings()
    payload = {"proposal_id": "p1", "client_session_id": "s1"}
    token = mint_approval_token(settings, action="meeting_schedule", payload=payload)
    assert not verify_approval_token(
        settings, token=token, action="email_send", payload=payload
    )
    get_settings.cache_clear()


def test_dev_mode_allows_empty_token_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPROVAL_SIGNING_SECRET", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert verify_approval_token(
        settings, token="", action="email_send", payload={"x": 1}
    )
    get_settings.cache_clear()
