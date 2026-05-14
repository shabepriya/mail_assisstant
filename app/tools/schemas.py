from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.models import ToolError as DomainToolError


class ToolErrorItem(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None

    @classmethod
    def from_domain(cls, e: DomainToolError) -> "ToolErrorItem":
        return cls(code=e.code, message=e.message, retryable=e.retryable, details=e.details)


class ToolMeta(BaseModel):
    request_id: str
    correlation_id: str | None = None
    success: bool = True


class EmailRow(BaseModel):
    id: str
    sender: str
    subject: str
    preview: str
    received_at: str
    priority: bool = False
    thread_id: str = ""


class EmailListRequest(BaseModel):
    account_id: str = Field(..., max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    category: str = Field(default="inbox", max_length=32)
    force_refresh: bool = False
    for_today: bool = False
    correlation_id: str | None = Field(default=None, max_length=128)


class EmailListResponse(ToolMeta):
    emails: list[EmailRow] = Field(default_factory=list)
    cache: dict[str, Any] = Field(default_factory=dict)
    errors: list[ToolErrorItem] = Field(default_factory=list)


class EmailImportantRequest(EmailListRequest):
    pass


class EmailSummarizeRequest(BaseModel):
    account_id: str = Field(..., max_length=128)
    query: str = Field(..., max_length=500)
    email_ids: list[str] | None = None
    force_refresh: bool = False
    for_today: bool = False
    correlation_id: str | None = None


class EmailSummarizeResponse(ToolMeta):
    summary: str = ""
    email_count: int = 0
    tokens_used: int = 0
    errors: list[ToolErrorItem] = Field(default_factory=list)


class MeetingExtractRequest(BaseModel):
    account_id: str = Field(..., max_length=128)
    client_session_id: str = Field(..., max_length=256)
    force_refresh: bool = False
    for_today: bool = False
    correlation_id: str | None = None


class MeetingProposalRow(BaseModel):
    proposal_id: str
    title: str
    start_iso: str
    end_iso: str
    start_local_display: str = ""
    timezone: str
    confidence: float


class MeetingExtractResponse(ToolMeta):
    proposals: list[MeetingProposalRow] = Field(default_factory=list)
    errors: list[ToolErrorItem] = Field(default_factory=list)


class MeetingScheduleRequest(BaseModel):
    client_session_id: str = Field(..., max_length=256)
    proposal_id: str = Field(..., max_length=128)
    approval_token: str = ""
    idempotency_key: str = ""
    correlation_id: str | None = None


class MeetingScheduleResponse(ToolMeta):
    ok: bool = False
    message: str = ""
    errors: list[ToolErrorItem] = Field(default_factory=list)


class ReplyDraftRequest(BaseModel):
    client_session_id: str = Field(..., max_length=256)
    from_addr: str = Field(..., max_length=320)
    subject: str = Field(default="", max_length=500)
    body_plain: str = Field(default="", max_length=8000)
    email_id: str = Field(default="", max_length=128)
    thread_id: str = Field(default="", max_length=128)
    correlation_id: str | None = None


class ReplyDraftResponse(ToolMeta):
    reply_handle: str = ""
    composer: dict[str, str] = Field(default_factory=dict)
    errors: list[ToolErrorItem] = Field(default_factory=list)


class ReplySendRequest(BaseModel):
    client_session_id: str = Field(..., max_length=256)
    reply_handle: str = Field(..., max_length=128)
    to: str = Field(..., max_length=320)
    subject: str = Field(..., max_length=500)
    body: str = Field(..., max_length=16000)
    idempotency_key: str = Field(..., max_length=128)
    approval_token: str = ""
    correlation_id: str | None = None


class ReplySendResponse(ToolMeta):
    ok: bool = False
    message: str = ""
    errors: list[ToolErrorItem] = Field(default_factory=list)


class ApprovalIntentRequest(BaseModel):
    action: Literal["email_send", "meeting_schedule"]
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class ApprovalIntentResponse(ToolMeta):
    approval_token: str = ""
    expires_in_seconds: int = 900


class TasksFollowupRequest(BaseModel):
    account_id: str = Field(..., max_length=128)
    title: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=8000)
    correlation_id: str | None = None


class TasksFollowupResponse(ToolMeta):
    ok: bool = True
    message: str = ""
    errors: list[ToolErrorItem] = Field(default_factory=list)
