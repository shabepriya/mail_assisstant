from app.filters import (
    extract_sender_query,
    filter_by_sender,
    filter_order_emails,
    filter_promotional_emails,
    filter_sales_emails,
    filter_spam_emails,
    is_protected_transactional_email,
    is_trusted_system_sender,
    is_today_intent,
    resolve_query_limit,
    wants_important_mail_help,
    wants_meeting_calendar_help,
    wants_order_mail_help,
    wants_sales_mail_help,
    wants_spam_mail_help,
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
    assert wants_important_mail_help("any emergency mail?") is True
    assert wants_important_mail_help("summarize inbox") is False


def test_wants_sales_mail_help() -> None:
    assert wants_sales_mail_help("any sales mail?") is True
    assert wants_sales_mail_help("show promotional offers") is True
    assert wants_sales_mail_help("summarize inbox") is False


def test_wants_order_mail_help() -> None:
    assert wants_order_mail_help("any order related mail?") is True
    assert wants_order_mail_help("show product updates") is True
    assert wants_order_mail_help("summarize inbox") is False


def test_wants_spam_mail_help() -> None:
    assert wants_spam_mail_help("any spam mails?") is True
    assert wants_spam_mail_help("check junk folder style emails") is True
    assert wants_spam_mail_help("summarize inbox") is False


def test_filter_sales_emails_matches_promotional_content() -> None:
    emails = [
        {"id": "1", "subject": "Get 1 Month Premium for Free", "body": "Offer ends soon"},
        {"id": "2", "subject": "Project update", "body": "Internal status note"},
    ]
    out = filter_sales_emails(emails)
    assert [e["id"] for e in out] == ["1"]


def test_filter_order_emails_matches_order_signals() -> None:
    emails = [
        {"id": "1", "subject": "Order shipped", "body": "Tracking id available"},
        {"id": "2", "subject": "Weekly digest", "body": "Top stories"},
    ]
    out = filter_order_emails(emails)
    assert [e["id"] for e in out] == ["1"]


def test_filter_spam_emails_matches_sender_or_body_hints() -> None:
    emails = [
        {"id": "1", "from": "updates-noreply@x.com", "subject": "Hi", "body": "General update"},
        {"id": "2", "from": "user@example.com", "subject": "Alert", "body": "Limited time offer"},
        {"id": "3", "from": "boss@example.com", "subject": "Meeting", "body": "Please join"},
    ]
    out = filter_spam_emails(emails)
    assert [e["id"] for e in out] == ["2"]


def test_filter_spam_excludes_google_security_alert() -> None:
    emails = [
        {
            "id": "g1",
            "from": "no-reply@accounts.google.com",
            "subject": "Security alert",
            "body": "A new sign-in to your Google Account was detected.",
        },
        {
            "id": "p1",
            "from": "updates-noreply@linkedin.com",
            "subject": "LinkedIn digest",
            "body": "People you may know",
        },
    ]
    out = filter_spam_emails(emails)
    assert [e["id"] for e in out] == ["p1"]


def test_filter_sales_excludes_github_pr_notification() -> None:
    emails = [
        {
            "id": "gh1",
            "from": "notifications@github.com",
            "subject": "[repo] Pull request merged: fix auth",
            "body": "Your pull request was merged into main.",
        },
        {
            "id": "in1",
            "from": "alert@indeed.com",
            "subject": "Better jobs are waiting for you",
            "body": "Apply to new roles near you. Unsubscribe here.",
        },
    ]
    out = filter_sales_emails(emails)
    assert [e["id"] for e in out] == ["in1"]


def test_filter_promotional_union_dedupes() -> None:
    emails = [
        {
            "id": "d1",
            "from": "hello@chess.com",
            "subject": "Get Premium for Free",
            "body": "Limited time offer — unsubscribe",
        }
    ]
    out = filter_promotional_emails(emails)
    assert len(out) == 1


def test_is_protected_transactional_google_and_github() -> None:
    assert is_protected_transactional_email(
        {"from": "no-reply@accounts.google.com", "subject": "Security alert", "body": "new sign-in"}
    )
    assert is_protected_transactional_email(
        {
            "from": "notifications@github.com",
            "subject": "Pull request merged",
            "body": "merged into main",
        }
    )
    assert not is_protected_transactional_email(
        {"from": "alert@indeed.com", "subject": "Better jobs are waiting for you", "body": "apply now"}
    )


def test_is_trusted_system_sender() -> None:
    assert is_trusted_system_sender({"from": "no-reply@accounts.google.com"})
    assert is_trusted_system_sender({"from": "GitHub <notifications@github.com>"})
    assert not is_trusted_system_sender({"from": "alert@indeed.com"})


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
