from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., max_length=500)
    force_refresh: bool = Field(default=False)
    client_session_id: str | None = Field(default=None, max_length=128)
    calendar_action: Literal["none", "approve", "dismiss"] | None = None
    calendar_proposal_id: str | None = Field(default=None, max_length=128)


class CalendarProposalPayload(BaseModel):
    proposal_id: str
    title: str
    start_iso: str
    end_iso: str
    start_local_display: str
    timezone: str
    confidence: float
    needs_confirmation: bool = True


class ChatResponse(BaseModel):
    response: str
    request_id: str
    email_count: int
    filtered_count: int
    cache_age_s: float
    tokens_used: int
    priority_email_count: int | None = None
    other_email_count: int | None = None
    calendar_proposals: list[CalendarProposalPayload] | None = None
    stale: bool = False


class ErrorResponse(BaseModel):
    error: str
    request_id: str


class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_s: float
