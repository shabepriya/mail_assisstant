from app.preprocess import emails_to_context, normalize_sender_field, sanitize_emails


def test_normalize_sender_field_lowercases_and_strips() -> None:
    e = {"from": "  Sundar@gmail.com  "}
    assert normalize_sender_field(e) == "sundar@gmail.com"


def test_normalize_sender_field_sender_fallback() -> None:
    e = {"sender": "A@B.CO"}
    assert normalize_sender_field(e) == "a@b.co"


def test_emails_to_context_structured_includes_normalized_from() -> None:
    emails = [
        {
            "id": "1",
            "account_id": "acc1",
            "branch": "Chennai",
            "from": "Sundar@gmail.com ",
            "subject": "Meeting",
            "body": "Hello",
            "received_at": "2026-04-24T08:30:00Z",
        }
    ]
    ctx = emails_to_context(emails, max_body_chars=500)
    assert "Email #1" in ctx
    assert "From: sundar@gmail.com" in ctx
    assert "Account: acc1" in ctx
    assert "Branch: Chennai" in ctx
    assert "Subject: Meeting" in ctx
    assert "Date: 2026-04-24T08:30:00Z" in ctx
    assert "Body: Hello" in ctx


def test_sanitize_emails_deduplicates_with_normalized_from_subject_fallback() -> None:
    emails = [
        {
            "from": " User@Example.com ",
            "subject": " Login Alert ",
            "body": "Code 123456",
        },
        {
            "from": "user@example.com",
            "subject": "login alert",
            "body": "Code 999999",
        },
    ]
    cleaned = sanitize_emails(emails)
    assert len(cleaned) == 1
    assert cleaned[0]["from"] == " User@Example.com "
    assert cleaned[0]["body"] == "Code [REDACTED_CODE]"


def test_sanitize_emails_priority_keyword_and_body_only_masking() -> None:
    emails = [
        {
            "id": "42",
            "from": "alerts@example.com",
            "subject": "Security Alert",
            "body": "Verification code is 456789.",
        }
    ]
    cleaned = sanitize_emails(emails)
    assert cleaned[0]["priority"] is True
    assert cleaned[0]["body"] == "Verification code is [REDACTED_CODE]."
