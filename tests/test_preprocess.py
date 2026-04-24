from app.preprocess import emails_to_context, normalize_sender_field


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
