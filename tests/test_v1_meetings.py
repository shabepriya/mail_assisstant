import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.approvals import mint_approval_token


def test_v1_meeting_extract_empty(v1_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(*_a, **_k):
        return []

    monkeypatch.setattr("app.domain.email_pipeline.fetch_emails", _empty)
    r = v1_client.post(
        "/v1/meeting/extract",
        json={
            "account_id": "acc-test",
            "client_session_id": "sess-meet",
            "correlation_id": "corr-meet-1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["correlation_id"] == "corr-meet-1"
    assert data["proposals"] == []


def test_v1_meeting_schedule_not_found(v1_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPROVAL_SIGNING_SECRET", "test-signing-secret")
    get_settings.cache_clear()
    settings = get_settings()
    payload = {"proposal_id": "missing-prop", "client_session_id": "sess-meet-2"}
    token = mint_approval_token(settings, action="meeting_schedule", payload=payload)

    r = v1_client.post(
        "/v1/meeting/schedule",
        json={
            "client_session_id": "sess-meet-2",
            "proposal_id": "missing-prop",
            "approval_token": token,
            "idempotency_key": "idem-sched-1",
            "correlation_id": "corr-sched-1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data["errors"][0]["code"] == "NOT_FOUND"
    get_settings.cache_clear()
