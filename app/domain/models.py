from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class NormalizedEmail(BaseModel):
    id: str
    account_id: str
    sender: str
    subject: str
    body: str
    preview: str
    received_at: str
    thread_id: str = ""
    priority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "from": self.sender,
            "subject": self.subject,
            "body": self.body,
            "received_at": self.received_at,
            "thread_id": self.thread_id,
            "priority": self.priority,
        }


class MeetingProposal(BaseModel):
    proposal_id: str
    title: str
    start_iso: str
    end_iso: str
    start_local_display: str = ""
    timezone: str
    confidence: float
    summary_for_user: str | None = None
    needs_confirmation: bool = True


class ReplyDraft(BaseModel):
    reply_handle: str
    to: str
    subject: str
    body: str
    email_id: str = ""
    thread_id: str = ""


class FetchEmailsResult(BaseModel):
    emails: list[NormalizedEmail] = Field(default_factory=list)
    cache_age_s: float = 0.0
    stale: bool = False
    filtered_count: int = 0
    errors: list[ToolError] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
