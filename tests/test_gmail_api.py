from app.gmail_api import reply_subject_for_send


def test_reply_subject_no_double_re_prefix() -> None:
    assert reply_subject_for_send("Re: Interview slot") == "Re: Interview slot"


def test_reply_subject_adds_re_when_missing() -> None:
    assert reply_subject_for_send("Interview slot") == "Re: Interview slot"


def test_reply_subject_strips_whitespace() -> None:
    assert reply_subject_for_send("  Hello  ") == "Re: Hello"
