# OpenClaw mail plugin (deferred)

Phase 3 follow-up: TypeScript OpenClaw plugin that calls this backend’s `/v1` HTTP API.

## Planned tools

- `POST /v1/email/list` — list emails
- `POST /v1/email/important` — priority-filtered list
- `POST /v1/email/summarize` — AI summary
- `POST /v1/meeting/extract` — meeting proposals
- `POST /v1/email/reply/draft` — reply draft
- `POST /v1/approvals/intent` — mint HMAC approval for send/schedule
- `POST /v1/email/reply/send` — send (requires approval)
- `POST /v1/meeting/schedule` — schedule (requires approval)

## Headers

- `X-API-Key` when `TOOL_REQUIRE_AUTH=true`
- `X-Correlation-Id` or body `correlation_id` for tracing

## Error handling

All responses include `errors[]` with stable `code` values (e.g. `GMAIL_SESSION_EXPIRED`, `APPROVAL_INVALID`). See `GET /v1/tools/manifest`.

No Python changes are required once `/v1` is stable.
