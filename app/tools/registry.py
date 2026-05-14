TOOLS_MANIFEST_VERSION = "1.0.0"

TOOLS: list[dict[str, object]] = [
    {
        "name": "email_list",
        "method": "POST",
        "path": "/v1/email/list",
        "description": "List recent emails for an account",
    },
    {
        "name": "email_important",
        "method": "POST",
        "path": "/v1/email/important",
        "description": "List important emails",
    },
    {
        "name": "email_summarize",
        "method": "POST",
        "path": "/v1/email/summarize",
        "description": "Summarize emails with AI",
    },
    {
        "name": "meeting_extract",
        "method": "POST",
        "path": "/v1/meeting/extract",
        "description": "Extract meeting proposals from emails",
    },
    {
        "name": "meeting_schedule",
        "method": "POST",
        "path": "/v1/meeting/schedule",
        "description": "Schedule a pending meeting proposal (requires approval)",
        "optional": True,
    },
    {
        "name": "email_reply_draft",
        "method": "POST",
        "path": "/v1/email/reply/draft",
        "description": "Draft a reply to an email",
    },
    {
        "name": "email_reply_send",
        "method": "POST",
        "path": "/v1/email/reply/send",
        "description": "Send a drafted reply (requires approval)",
        "optional": True,
    },
    {
        "name": "approvals_intent",
        "method": "POST",
        "path": "/v1/approvals/intent",
        "description": "Mint approval token for send/schedule",
    },
]

ERROR_CODES: list[str] = [
    "GMAIL_SESSION_EXPIRED",
    "GMAIL_FETCH_FAILED",
    "AI_UNAVAILABLE",
    "NOT_FOUND",
    "APPROVAL_INVALID",
    "SEND_FAILED",
    "SCHEDULE_FAILED",
]
