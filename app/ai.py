from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_OPENCLAW_AGENT_MODEL = "openclaw"


def _openclaw_timeout(settings: Settings) -> httpx.Timeout:
    read_s = max(5.0, float(settings.openclaw_timeout))
    return httpx.Timeout(connect=10.0, read=read_s, write=30.0, pool=10.0)


def _openclaw_headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "x-openclaw-scopes": "operator.write",
    }
    token = (settings.openclaw_gateway_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    model_override = settings.openclaw_backend_model.strip()
    if model_override:
        headers["x-openclaw-model"] = model_override
    return headers


def _openclaw_chat_url(settings: Settings) -> str:
    base = settings.openclaw_base_url.rstrip("/")
    return f"{base}/v1/chat/completions"


def _extract_chat_content(data: object) -> str:
    if not isinstance(data, dict):
        return "No response from agent."
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "No response from agent."
    first = choices[0]
    if not isinstance(first, dict):
        return "No response from agent."
    message = first.get("message")
    if not isinstance(message, dict):
        return "No response from agent."
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return "No response from agent."


def _openclaw_error_message(exc: Exception, settings: Settings) -> str:
    base = settings.openclaw_base_url.rstrip("/")
    if isinstance(exc, httpx.ConnectError):
        return (
            f"OpenClaw gateway is not reachable at {base}. "
            "Start it on this machine (for example: openclaw gateway), then try again."
        )
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"OpenClaw gateway at {base} did not respond within "
            f"{int(settings.openclaw_timeout)}s. "
            "Check that the gateway is running and model auth is configured "
            "(openclaw models auth)."
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text[:500].strip()
        body_lower = body.lower()
        if status == 401:
            if "gateway" in body_lower and "token" in body_lower:
                return (
                    "OpenClaw gateway rejected the token. "
                    "Set OPENCLAW_GATEWAY_TOKEN in mail_assistant/.env to match "
                    "gateway.auth.token in ~/.openclaw/openclaw.json."
                )
            return (
                "OpenClaw has no API key for the selected model provider. "
                f"Run: openclaw models auth login --provider google "
                f"(using GEMINI_API_KEY), or set models.providers.google.apiKey "
                f"in ~/.openclaw/openclaw.json. Details: {body[:200]}"
            )
        if status == 404 and "unknown model" in body_lower:
            return (
                f"OpenClaw does not recognize model '{settings.openclaw_backend_model}'. "
                "Set OPENCLAW_MODEL_OVERRIDE in mail_assistant/.env to a model from "
                "`openclaw models list`, then restart the gateway."
            )
        if status == 404:
            return (
                "OpenClaw /v1/chat/completions is not enabled. "
                "Set gateway.http.endpoints.chatCompletions.enabled to true "
                "in ~/.openclaw/openclaw.json and restart the gateway."
            )
        detail = f" ({body})" if body else ""
        return f"OpenClaw gateway returned HTTP {status}{detail}."
    return "Error: Could not reach OpenClaw agent."


async def _openclaw_chat_completion(
    settings: Settings,
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
) -> str:
    url = _openclaw_chat_url(settings)
    payload: dict[str, object] = {
        "model": _OPENCLAW_AGENT_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    async with httpx.AsyncClient(timeout=_openclaw_timeout(settings)) as client:
        response = await client.post(
            url,
            json=payload,
            headers=_openclaw_headers(settings),
        )
        response.raise_for_status()
        return _extract_chat_content(response.json())


async def ask_ai(
    settings: Settings,
    *,
    context: str,
    query: str,
    email_count: int,
    priority_count: int | None = None,
    non_priority_count: int | None = None,
    include_calendar_confirmation_guidance: bool = False,
) -> str:
    _ = (email_count, priority_count, non_priority_count, include_calendar_confirmation_guidance)
    system_prompt = (
        "You are a helpful email assistant. "
        "Answer using only the email context provided. Be concise."
    )
    user_prompt = f"Emails Context:\n{context}\n\nQuestion: {query}"
    try:
        return await _openclaw_chat_completion(
            settings,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=settings.gemini_max_tokens,
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "openclaw_ask_http_error url=%s status=%s",
            _openclaw_chat_url(settings),
            exc.response.status_code,
        )
        return _openclaw_error_message(exc, settings)
    except Exception as exc:
        logger.warning("openclaw_ask_failed url=%s error=%s", _openclaw_chat_url(settings), exc)
        return _openclaw_error_message(exc, settings)


async def generate_reply_draft(
    settings: Settings,
    *,
    from_addr: str,
    subject: str,
    body_plain: str,
) -> str:
    system_prompt = "You write ONLY the body of a professional email reply."
    user_prompt = (
        f"Draft a reply to: {from_addr}\nSubject: {subject}\nBody: {body_plain}"
    )
    try:
        return await _openclaw_chat_completion(
            settings,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=min(settings.gemini_max_tokens, 800),
        )
    except Exception as exc:
        logger.warning(
            "openclaw_reply_draft_failed url=%s error=%s",
            _openclaw_chat_url(settings),
            exc,
        )
        return "Thank you for your email. I will follow up shortly."
