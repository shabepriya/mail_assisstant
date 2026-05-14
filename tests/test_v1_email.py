import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def v1_client(client: TestClient) -> TestClient:
    return client


def test_v1_email_list_echoes_correlation_id(
    v1_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "v1-1",
                "from": "a@example.com",
                "subject": "One",
                "body": "body",
                "received_at": "2026-05-04T12:00:00Z",
            }
        ]

    monkeypatch.setattr("app.domain.email_pipeline.fetch_emails", _emails)
    r = v1_client.post(
        "/v1/email/list",
        json={"account_id": "acc-test", "correlation_id": "corr-list-1"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["correlation_id"] == "corr-list-1"
    assert len(data["emails"]) == 1
    assert data["emails"][0]["id"] == "v1-1"


def test_v1_email_summarize_mocked_ai(
    v1_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "s1",
                "from": "b@example.com",
                "subject": "Subj",
                "body": "Content",
                "received_at": "2026-05-04T12:00:00Z",
            }
        ]

    async def _summarize(*_a, **kwargs):
        return "Short summary."

    monkeypatch.setattr("app.domain.email_pipeline.fetch_emails", _emails)
    monkeypatch.setattr("app.domain.ai_service.summarize_emails", _summarize)

    r = v1_client.post(
        "/v1/email/summarize",
        json={"account_id": "acc-test", "query": "summarize", "correlation_id": "corr-sum-1"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["correlation_id"] == "corr-sum-1"
    assert data["summary"] == "Short summary."
    assert data["email_count"] == 1
