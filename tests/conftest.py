import os

# Configure before importing the app (settings are cached).
os.environ.setdefault("MOCK_EMAILS", "true")
os.environ.setdefault("EMAIL_ACCOUNT_ID", "acc-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key")
os.environ.setdefault("EMAIL_API_BASE_URL", "http://example.invalid")
os.environ.setdefault("CORS_ORIGINS", "http://127.0.0.1:8000")

import pytest
from fastapi.testclient import TestClient

from app.cache import EmailCache
from app.config import get_settings
from app.main import app


@pytest.fixture
def v1_client(client: TestClient) -> TestClient:
    return client


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        c.app.state.cache = EmailCache(get_settings().cache_ttl_seconds)
        yield c
