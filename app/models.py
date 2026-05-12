from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    force_refresh: bool = Field(default=False)
    client_session_id: str | None = Field(default=None, max_length=128)
    calendar_action: Literal["none", "approve", "dismiss"] | None = None
    calendar_proposal_id: str | None = Field(default=None, max_length=128)
    email_reply_action: Literal["reply", "view"] | None = None
    email_reply_action_id: str | None = Field(default=None, max_length=128)
    reply_to: str | None = Field(default=None, max_length=320)
    reply_subject: str | None = Field(default=None, max_length=500)
    reply_body: str | None = Field(default=None, max_length=16000)

    @model_validator(mode="after")
    def query_required_without_reply_action(self) -> "ChatRequest":
        if self.email_reply_action:
            return self
        if not self.query.strip():
            raise ValueError("Query cannot be empty unless email_reply_action is set.")
        return self


class CalendarProposalPayload(BaseModel):
    proposal_id: str
    title: str
    start_iso: str
    end_iso: str
    start_local_display: str
    timezone: str
    confidence: float
    needs_confirmation: bool = True


class EmailReplyActionPayload(BaseModel):
    action_id: str
    email_id: str
    sender: str
    sender_email: str | None = None
    subject: str
    preview: str
    can_reply: bool = True
    action_type: Literal["reply"] = "reply"


class ReplyComposerPayload(BaseModel):
    action_id: str
    to: str
    subject: str
    body: str


class EmailOpenView(BaseModel):
    email_id: str
    from_addr: str
    subject: str
    body: str


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
    email_actions: list[EmailReplyActionPayload] | None = None
    reply_composer: ReplyComposerPayload | None = None
    email_open_view: EmailOpenView | None = None
    stale: bool = False


class ErrorResponse(BaseModel):
    error: str
    request_id: str


class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_s: float
