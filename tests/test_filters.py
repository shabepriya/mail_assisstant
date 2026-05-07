from app.filters import (
    extract_sender_query,
    filter_by_sender,
    is_today_intent,
    resolve_query_limit,
    wants_important_mail_help,
    wants_meeting_calendar_help,
)


def test_extract_sender_query_variants() -> None:
    assert extract_sender_query("emails from Sundar") == "sundar"
    assert extract_sender_query("did I get anything from sundar@gmail.com") == "sundar@gmail.com"
    assert extract_sender_query("any mail from user@example.com?") == "user@example.com"
    assert extract_sender_query("summarize today") is None


def test_filter_by_sender_substring_name() -> None:
    emails = [
        {"id": "1", "from": "sundar@gmail.com", "subject": "Hi"},
        {"id": "2", "from": "other@x.com", "subject": "Yo"},
    ]
    out = filter_by_sender(emails, "sundar")
    assert len(out) == 1 and out[0]["id"] == "1"


def test_filter_by_sender_exact_email() -> None:
    emails = [
        {"id": "1", "from": "sundar@gmail.com"},
        {"id": "2", "from": "notsundar@gmail.com"},
    ]
    out = filter_by_sender(emails, "sundar@gmail.com")
    assert [e["id"] for e in out] == ["1"]


def test_filter_by_sender_sender_key_fallback() -> None:
    emails = [{"id": "1", "sender": "a@b.co"}]
    assert filter_by_sender(emails, "a@b.co")[0]["id"] == "1"


def test_is_today_intent_includes_latest_recent_new() -> None:
    assert is_today_intent("show me latest mails") is True
    assert is_today_intent("any recent emails?") is True
    assert is_today_intent("new updates in inbox") is True
    assert is_today_intent("summarize all complaints") is False


def test_wants_meeting_calendar_help() -> None:
    assert wants_meeting_calendar_help("any meeting tomorrow?") is True
    assert wants_meeting_calendar_help("schedule call") is True
    assert wants_meeting_calendar_help("summarize inbox") is False


def test_wants_important_mail_help() -> None:
    assert wants_important_mail_help("any important mail today?") is True
    assert wants_important_mail_help("priority emails today") is True
    assert wants_important_mail_help("priority emails") is True
    assert wants_important_mail_help("summarize inbox") is False


def test_resolve_query_limit_singular_cue_returns_one() -> None:
    assert resolve_query_limit("what is my last mail", 5) == 1
    assert resolve_query_limit("show me the latest email", 5) == 1
    assert resolve_query_limit("most recent message", 5) == 1


def test_resolve_query_limit_numeric() -> None:
    assert resolve_query_limit("summarize last 5 mails", 5) == 5
    assert resolve_query_limit("show me top 3 emails", 5) == 3
    assert resolve_query_limit("read recent 2 messages", 5) == 2


def test_resolve_query_limit_caps_at_default() -> None:
    assert resolve_query_limit("summarize last 50 mails", 5) == 5


def test_resolve_query_limit_default_when_no_cue() -> None:
    assert resolve_query_limit("any important mail?", 5) == 5
    assert resolve_query_limit("what is in my mail", 5) == 5
    assert resolve_query_limit("", 5) == 5
