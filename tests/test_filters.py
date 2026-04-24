from app.filters import extract_sender_query, filter_by_sender


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
