import httpx
import pytest

from app.ai import _openclaw_error_message, _openclaw_headers
from app.config import Settings


def test_openclaw_headers_includes_model_override() -> None:
    settings = Settings(
        gemini_api_key="x",
        openclaw_gateway_token="secret",
        openclaw_model_override="google/gemini-2.5-flash",
    )
    headers = _openclaw_headers(settings)
    assert headers["Authorization"] == "Bearer secret"
    assert headers["x-openclaw-model"] == "google/gemini-2.5-flash"
    assert headers["x-openclaw-scopes"] == "operator.write"


def test_openclaw_backend_model_empty_without_override() -> None:
    settings = Settings(gemini_api_key="x", gemini_model="gemini-2.5-flash")
    assert settings.openclaw_backend_model == ""


def test_openclaw_headers_omit_model_when_override_empty() -> None:
    settings = Settings(gemini_api_key="x", openclaw_gateway_token="secret")
    headers = _openclaw_headers(settings)
    assert "x-openclaw-model" not in headers


def test_openclaw_connect_error_message() -> None:
    settings = Settings(gemini_api_key="x")
    msg = _openclaw_error_message(httpx.ConnectError("refused"), settings)
    assert "not reachable" in msg
    assert "openclaw gateway" in msg.lower()


def test_openclaw_timeout_error_message() -> None:
    settings = Settings(gemini_api_key="x", openclaw_timeout=90)
    msg = _openclaw_error_message(httpx.ReadTimeout("slow"), settings)
    assert "90s" in msg
    assert "models auth" in msg
