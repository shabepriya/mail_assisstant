import pytest
from fastapi.testclient import TestClient

from app import email_client
from app.cache import EmailCache
from app.config import get_settings


@pytest.fixture
def patch_ask_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ask_ai(
        settings,
        *,
        context: str,
        query: str,
        email_count: int,
        priority_count: int | None = None,
        non_priority_count: int | None = None,
        include_calendar_confirmation_guidance: bool = False,
    ) -> str:
        assert email_count >= 0
        assert priority_count is None or priority_count >= 0
        assert non_priority_count is None or non_priority_count >= 0
        if "missingxyz" in query:
            return "Not available in current emails."
        return "mocked-ai-response"

    monkeypatch.setattr("app.routes.chat.ask_ai", fake_ask_ai)


def test_chat_ok(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post("/ai/chat", json={"query": "Summarize emails"})
    assert r.status_code == 200
    data = r.json()
    assert data["response"].startswith("mocked-ai-response")
    assert "request_id" in data
    assert "cache_age_s" in data
    assert "email_count" in data
    assert "priority_email_count" in data
    assert "other_email_count" in data


def test_chat_not_available_sentence(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post("/ai/chat", json={"query": "missingxyz"})
    assert r.status_code == 200
    body = r.json()["response"]
    assert body.startswith("Not available in current emails.")


def test_chat_sender_filter_no_match(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post(
        "/ai/chat", json={"query": "anything from nobody_xyz_123@nowhere.test"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["response"] == "Not available in current emails."
    assert data["email_count"] == 0


def test_chat_sender_filter_match(client: TestClient, patch_ask_ai: None) -> None:
    r = client.post(
        "/ai/chat", json={"query": "summarize from customer@gmail.com"}
    )
    assert r.status_code == 200
    body = r.json()["response"]
    assert body.startswith("mocked-ai-response")


def test_chat_returns_empty_batch_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _empty(*_a, **_k):
        return []

    monkeypatch.setattr("app.routes.chat.fetch_emails", _empty)
    r = client.post("/ai/chat", json={"query": "summarize"})
    assert r.status_code == 200
    assert r.json()["response"] == "No emails found in the current batch."
    assert r.json()["email_count"] == 0


async def _boom(*_a, **_k):
    raise email_client.EmailAPIError("down")


def test_chat_503_when_email_api_fails_and_no_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Must disable mock path so fetch_emails reaches the HTTP branch (patched to fail).
    monkeypatch.setenv("MOCK_EMAILS", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(email_client, "fetch_emails", _boom)
    client.app.state.cache = EmailCache(get_settings().cache_ttl_seconds)

    r = client.post("/ai/chat", json={"query": "hello"})
    assert r.status_code == 503
    body = r.json()
    assert "error" in body
    assert "unavailable" in body["error"].lower()
    assert "request_id" in body
    get_settings.cache_clear()


def test_chat_sanitize_layer_deduplicates_and_validates_output(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _dupes(*_a, **_k):
        return [
            {
                "from": "user@example.com",
                "subject": "Login alert",
                "body": "Use 123456",
                "received_at": "2026-04-22T08:30:00Z",
            },
            {
                "from": " USER@example.com ",
                "subject": " login alert ",
                "body": "Use 987654",
                "received_at": "2026-04-22T08:30:01Z",
            },
        ]

    async def _fake_ask_ai(
        settings,
        *,
        context: str,
        query: str,
        email_count: int,
        priority_count: int | None = None,
        non_priority_count: int | None = None,
        include_calendar_confirmation_guidance: bool = False,
    ) -> str:
        assert email_count == 1
        assert priority_count == 1
        assert non_priority_count == 0
        assert context.count("Email #") == 1
        return "As an AI language model,\nYour login code is 123456."

    monkeypatch.setattr("app.routes.chat.fetch_emails", _dupes)
    monkeypatch.setattr("app.routes.chat.ask_ai", _fake_ask_ai)

    r = client.post("/ai/chat", json={"query": "summarize"})
    assert r.status_code == 200
    assert r.json()["response"] == "Your login code is [REDACTED_CODE]."
    assert r.json()["priority_email_count"] == 1
    assert r.json()["other_email_count"] == 0


def test_chat_returns_calendar_proposals_for_meeting_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _meetings(*_a, **_k):
        return [
            {
                "id": "m1",
                "from": "team@example.com",
                "subject": "Project meeting tomorrow",
                "body": "Meeting tomorrow 9 PM IST",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _meetings)

    r = client.post(
        "/ai/chat",
        json={"query": "any meeting tomorrow?", "client_session_id": "sess-a"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["calendar_proposals"] is not None
    assert len(data["calendar_proposals"]) == 1
    assert data["calendar_proposals"][0]["proposal_id"]


def test_chat_calendar_dismiss_flow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _meetings(*_a, **_k):
        return [
            {
                "id": "m1",
                "from": "team@example.com",
                "subject": "Project meeting tomorrow",
                "body": "Meeting tomorrow 9 PM IST",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _meetings)
    first = client.post(
        "/ai/chat",
        json={"query": "any meeting tomorrow?", "client_session_id": "sess-b"},
    ).json()
    pid = first["calendar_proposals"][0]["proposal_id"]

    r = client.post(
        "/ai/chat",
        json={
            "query": "ignore",
            "client_session_id": "sess-b",
            "calendar_action": "dismiss",
            "calendar_proposal_id": pid,
        },
    )
    assert r.status_code == 200
    assert "ignore" in r.json()["response"].lower()


def test_chat_calendar_approve_flow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _meetings(*_a, **_k):
        return [
            {
                "id": "m1",
                "from": "team@example.com",
                "subject": "Project meeting tomorrow",
                "body": "Meeting tomorrow 9 PM IST",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    class _Result:
        created = True
        duplicate = False

    async def _fake_create_event(self, **_kwargs):
        return _Result()

    monkeypatch.setattr("app.routes.chat.fetch_emails", _meetings)
    monkeypatch.setattr(
        "app.google_calendar.GoogleCalendarClient.create_event",
        _fake_create_event,
    )
    first = client.post(
        "/ai/chat",
        json={"query": "any meeting tomorrow?", "client_session_id": "sess-c"},
    ).json()
    pid = first["calendar_proposals"][0]["proposal_id"]

    r = client.post(
        "/ai/chat",
        json={
            "query": "approve",
            "client_session_id": "sess-c",
            "calendar_action": "approve",
            "calendar_proposal_id": pid,
        },
    )
    assert r.status_code == 200
    assert "added" in r.json()["response"].lower()


def test_chat_ai_fallback_calendar_proposal_requires_time_and_date(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "m2",
                "from": "noreply@example.com",
                "subject": "Status update",
                "body": "Please review the report.",
                "received_at": "2026-04-22T08:30:00Z",
            }
        ]

    async def _fallback_ai(
        settings,
        *,
        context: str,
        query: str,
        email_count: int,
        priority_count: int | None = None,
        non_priority_count: int | None = None,
        include_calendar_confirmation_guidance: bool = False,
    ) -> str:
        return "You have a meeting tomorrow at 9 PM."

    monkeypatch.setenv("CALENDAR_SCHEDULING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.ask_ai", _fallback_ai)

    r = client.post(
        "/ai/chat",
        json={"query": "Any meeting tomorrow?", "client_session_id": "sess-fallback"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["calendar_proposals"] is not None
    assert len(data["calendar_proposals"]) == 1
    assert data["calendar_proposals"][0]["confidence"] <= 0.35
    get_settings.cache_clear()


def test_chat_rejects_empty_query_without_reply_action(client: TestClient) -> None:
    r = client.post("/ai/chat", json={"query": "", "client_session_id": "sess-empty"})
    assert r.status_code == 422


def test_chat_important_mail_without_today_still_gets_reply_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "p1",
                "from": "github@example.com",
                "subject": "Security",
                "body": "sudo code",
                "received_at": "2026-05-04T12:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "any important mail?", "client_session_id": "sess-reply-no-today"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("email_actions")
    assert len(data["email_actions"]) >= 1


def test_chat_important_today_returns_email_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "r1",
                "from": "hr@example.com",
                "subject": "Interview slot",
                "body": "Please confirm your interview.",
                "received_at": "2026-05-04T12:00:00Z",
            },
            {
                "id": "r2",
                "from": "news@example.com",
                "subject": "Weekly digest",
                "body": "Top stories this week.",
                "received_at": "2026-05-04T11:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    r = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-a"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("email_actions")
    assert 1 <= len(data["email_actions"]) <= 2


def test_chat_important_today_fallback_uses_latest_two_when_no_priority(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "n1",
                "from": "a@example.com",
                "subject": "Note one",
                "body": "Short body alpha.",
                "received_at": "2026-05-04T14:00:00Z",
            },
            {
                "id": "n2",
                "from": "b@example.com",
                "subject": "Note two",
                "body": "Short body beta.",
                "received_at": "2026-05-04T13:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    r = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-fb"},
    )
    assert r.status_code == 200
    assert len(r.json()["email_actions"]) == 2


def test_chat_reply_draft_and_send_via_gmail_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "r1",
                "from": "hr@example.com",
                "subject": "Interview slot",
                "body": "Please confirm your interview.",
                "received_at": "2026-05-04T12:00:00Z",
                "thread_id": "thr-seeded",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    first = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-b"},
    ).json()
    aid = first["email_actions"][0]["action_id"]

    async def _fake_draft(
        settings,
        *,
        from_addr: str,
        subject: str,
        body_plain: str,
    ) -> str:
        return "Mock draft body."

    monkeypatch.setattr("app.routes.chat.generate_reply_draft", _fake_draft)

    d = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-b",
            "email_reply_action": "draft",
            "email_reply_action_id": aid,
        },
    ).json()
    assert d.get("reply_composer")
    assert d["reply_composer"]["body"] == "Mock draft body."

    captured: dict[str, str] = {}

    async def _fake_send(_client, _settings, *, to, subject, content, thread_id):
        captured["to"] = to
        captured["subject"] = subject
        captured["content"] = content
        captured["thread_id"] = thread_id
        return (True, "")

    monkeypatch.setattr("app.routes.chat.send_reply_via_service", _fake_send)

    sent = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-b",
            "email_reply_action": "send",
            "email_reply_action_id": aid,
            "reply_to": "hr@example.com",
            "reply_subject": "Re: Interview slot",
            "reply_body": "Thanks.",
        },
    ).json()
    assert "Email sent successfully to hr@example.com ✅" in sent["response"]
    assert captured["to"] == "hr@example.com"
    assert captured["subject"] == "Re: Interview slot"
    assert captured["content"] == "Thanks."
    assert captured["thread_id"] == "thr-seeded"


def test_chat_reply_send_resolves_thread_id_lazily(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "r1",
                "from": "hr@example.com",
                "subject": "Interview slot",
                "body": "Please confirm your interview.",
                "received_at": "2026-05-04T12:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    first = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-lazy"},
    ).json()
    aid = first["email_actions"][0]["action_id"]

    async def _fake_draft(
        settings,
        *,
        from_addr: str,
        subject: str,
        body_plain: str,
    ) -> str:
        return "Draft."

    monkeypatch.setattr("app.routes.chat.generate_reply_draft", _fake_draft)

    client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-lazy",
            "email_reply_action": "draft",
            "email_reply_action_id": aid,
        },
    )

    async def _fake_fetch_thread(_client, _settings, *, message_id):
        assert message_id == "r1"
        return "thr_xyz"

    monkeypatch.setattr("app.routes.chat.fetch_thread_id", _fake_fetch_thread)

    captured: dict[str, str] = {}

    async def _fake_send(_client, _settings, *, to, subject, content, thread_id):
        captured["thread_id"] = thread_id
        return (True, "")

    monkeypatch.setattr("app.routes.chat.send_reply_via_service", _fake_send)

    sent = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-lazy",
            "email_reply_action": "send",
            "email_reply_action_id": aid,
            "reply_to": "hr@example.com",
            "reply_subject": "Re: Interview slot",
            "reply_body": "Thanks.",
        },
    ).json()
    assert "✅" in sent["response"]
    assert captured["thread_id"] == "thr_xyz"


def test_chat_reply_send_failure_keeps_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "r1",
                "from": "hr@example.com",
                "subject": "Interview slot",
                "body": "Please confirm your interview.",
                "received_at": "2026-05-04T12:00:00Z",
                "thread_id": "thr-1",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)
    monkeypatch.setattr("app.routes.chat.filter_today", lambda emails, tz: list(emails))

    first = client.post(
        "/ai/chat",
        json={"query": "any important mail today?", "client_session_id": "sess-reply-fail"},
    ).json()
    aid = first["email_actions"][0]["action_id"]

    async def _fake_draft(
        settings,
        *,
        from_addr: str,
        subject: str,
        body_plain: str,
    ) -> str:
        return "Draft body."

    monkeypatch.setattr("app.routes.chat.generate_reply_draft", _fake_draft)

    async def _fake_send_fail(*_a, **_k):
        return (False, "Your Gmail session has expired. Please reconnect your Gmail account.")

    monkeypatch.setattr("app.routes.chat.send_reply_via_service", _fake_send_fail)

    sent = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-fail",
            "email_reply_action": "send",
            "email_reply_action_id": aid,
            "reply_to": "hr@example.com",
            "reply_subject": "Re: Interview slot",
            "reply_body": "Thanks.",
        },
    ).json()
    assert "Your Gmail session has expired" in sent["response"]
    assert "✅" not in sent["response"]

    d2 = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-reply-fail",
            "email_reply_action": "draft",
            "email_reply_action_id": aid,
        },
    ).json()
    assert d2.get("reply_composer")
    assert d2["reply_composer"]["body"] == "Draft body."


def test_chat_attaches_reply_actions_for_any_query_with_emails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "e1",
                "from": "a@example.com",
                "subject": "One",
                "body": "body one",
                "received_at": "2026-05-04T12:00:00Z",
            },
            {
                "id": "e2",
                "from": "b@example.com",
                "subject": "Two",
                "body": "body two",
                "received_at": "2026-05-04T11:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "summarize my emails", "client_session_id": "sess-any-query"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("email_actions")
    assert len(data["email_actions"]) == 2


def test_chat_includes_system_senders_with_can_reply_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "s1",
                "from": "mailer-daemon@googlemail.com",
                "subject": "Bounce",
                "body": "fail",
                "received_at": "2026-05-04T12:00:00Z",
            },
            {
                "id": "a1",
                "from": "alice@example.com",
                "subject": "Hello",
                "body": "hi",
                "received_at": "2026-05-04T11:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "show my emails", "client_session_id": "sess-skip-daemon"},
    )
    assert r.status_code == 200
    actions = r.json().get("email_actions") or []
    assert len(actions) == 2
    assert actions[0]["email_id"] == "s1"
    assert actions[0]["can_reply"] is False
    assert actions[1]["email_id"] == "a1"
    assert actions[1]["can_reply"] is True
    assert "alice" in actions[1]["sender"].lower()


def test_chat_includes_system_senders_with_display_name_can_reply_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "s2",
                "from": "Mail Delivery <mailer-daemon@x.com>",
                "subject": "Failed",
                "body": "bounce",
                "received_at": "2026-05-04T12:00:00Z",
            },
            {
                "id": "b1",
                "from": "Bob <bob@example.com>",
                "subject": "Hey",
                "body": "yo",
                "received_at": "2026-05-04T11:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "inbox please", "client_session_id": "sess-display-name"},
    )
    assert r.status_code == 200
    actions = r.json().get("email_actions") or []
    assert len(actions) == 2
    assert actions[0]["email_id"] == "s2"
    assert actions[0]["can_reply"] is False
    assert actions[1]["email_id"] == "b1"
    assert actions[1]["can_reply"] is True
    assert "bob" in actions[1]["sender"].lower()


def test_chat_includes_empty_subject_in_reply_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "a1",
                "from": "alice@example.com",
                "subject": "",
                "body": "no subject",
                "received_at": "2026-05-04T12:00:00Z",
            },
            {
                "id": "b1",
                "from": "bob@example.com",
                "subject": "Hi",
                "body": "hello",
                "received_at": "2026-05-04T11:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "what is in my mail", "client_session_id": "sess-empty-subj"},
    )
    assert r.status_code == 200
    actions = r.json().get("email_actions") or []
    assert len(actions) == 2
    assert actions[0]["email_id"] == "a1"
    assert actions[0]["subject"] == "(no subject)"
    assert actions[0]["can_reply"] is True
    assert actions[1]["email_id"] == "b1"
    assert actions[1]["can_reply"] is True


def test_chat_caps_reply_actions_at_max(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": str(i),
                "from": f"u{i}@example.com",
                "subject": f"Subject {i}",
                "body": "x",
                "received_at": "2026-05-04T12:00:00Z",
            }
            for i in range(1, 8)
        ]

    monkeypatch.setenv("REPLY_ACTION_MAX", "3")
    get_settings.cache_clear()
    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={"query": "list emails", "client_session_id": "sess-cap"},
    )
    assert r.status_code == 200
    assert len(r.json().get("email_actions") or []) == 3
    get_settings.cache_clear()


def test_chat_query_last_mail_returns_one_action(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": str(i),
                "from": f"u{i}@example.com",
                "subject": f"S{i}",
                "body": "x",
                "received_at": "2026-05-04T12:00:00Z",
            }
            for i in range(1, 6)
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={
            "query": "what is my last mail",
            "client_session_id": "sess-last-one",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["email_actions"]) == 1
    assert data["email_actions"][0]["email_id"] == "1"
    assert data["email_count"] == 1


def test_chat_query_summarize_last_5_returns_five(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": str(i),
                "from": f"u{i}@example.com",
                "subject": f"S{i}",
                "body": "x",
                "received_at": "2026-05-04T12:00:00Z",
            }
            for i in range(1, 8)
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    r = client.post(
        "/ai/chat",
        json={
            "query": "summarize last 5 mails",
            "client_session_id": "sess-last-five",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["email_actions"]) == 5
    assert data["email_count"] == 5


def test_extract_email_helpers() -> None:
    from app.routes.chat import _extract_email, _is_system_sender

    assert _extract_email("Name <a@b.c>") == "a@b.c"
    assert _extract_email("a@b.c") == "a@b.c"
    assert _extract_email("") == ""
    assert _is_system_sender("updates@learn.mailgun.com")
    assert _is_system_sender("notification@priority.facebookmail.com")
    assert _is_system_sender("notifications-noreply@linkedin.com")
    assert not _is_system_sender("hr@company.com")


def test_chat_open_action_returns_view_and_composer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, patch_ask_ai: None
) -> None:
    async def _emails(*_a, **_k):
        return [
            {
                "id": "e1",
                "from": "hr@company.com",
                "subject": "Interview",
                "body": "Hello there",
                "received_at": "2026-05-04T12:00:00Z",
            },
        ]

    monkeypatch.setattr("app.routes.chat.fetch_emails", _emails)

    first = client.post(
        "/ai/chat",
        json={"query": "summarize my emails", "client_session_id": "sess-open-view"},
    ).json()
    aid = first["email_actions"][0]["action_id"]

    async def _mock_draft(
        settings,
        *,
        from_addr: str,
        subject: str,
        body_plain: str,
    ) -> str:
        return "Mock draft"

    monkeypatch.setattr("app.routes.chat.generate_reply_draft", _mock_draft)

    r = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-open-view",
            "email_reply_action": "open",
            "email_reply_action_id": aid,
        },
    )
    assert r.status_code == 200
    d = r.json()
    assert d.get("email_open_view")
    assert d["email_open_view"]["email_id"] == "e1"
    assert d["email_open_view"]["from_addr"] == "hr@company.com"
    assert d["email_open_view"]["subject"] == "Interview"
    assert "Hello" in d["email_open_view"]["body"]
    assert d.get("reply_composer")
    assert d["reply_composer"]["body"] == "Mock draft"
    assert d["reply_composer"]["subject"].lower().startswith("re:")


def test_chat_open_action_missing_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-open-miss",
            "email_reply_action": "open",
            "email_reply_action_id": "reply_nonexistent999",
        },
    )
    assert r.status_code == 200
    assert "no longer available" in r.json()["response"].lower()


def test_chat_open_action_missing_id(client: TestClient) -> None:
    r = client.post(
        "/ai/chat",
        json={
            "query": "",
            "client_session_id": "sess-open-noid",
            "email_reply_action": "open",
        },
    )
    assert r.status_code == 200
    assert "Missing reply action id" in r.json()["response"]
