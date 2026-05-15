"""Legacy /ai/chat HTTP route — delegates to domain chat_service."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from app.ai import ask_ai, generate_reply_draft
from app.config import Settings, get_settings
from app.domain.chat_service import run_chat_turn
from app.email_client import EmailAPIError, fetch_emails
from app.filters import filter_today
from app.domain.reply_service import (
    extract_email as _extract_email,
    is_system_sender as _is_system_sender,
)
from app.models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

# Re-exported for tests that monkeypatch app.routes.chat.*
from app.gmail_api import fetch_thread_id, send_reply_via_service

__all__ = [
    "router",
    "ask_ai",
    "generate_reply_draft",
    "fetch_emails",
    "EmailAPIError",
    "filter_today",
    "send_reply_via_service",
    "fetch_thread_id",
    "_extract_email",
    "_is_system_sender",
]


def _settings_dep() -> Settings:
    return get_settings()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    settings: Settings = Depends(_settings_dep),
) -> ChatResponse:
    return await run_chat_turn(request, body, settings)
