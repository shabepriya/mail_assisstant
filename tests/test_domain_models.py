from app.domain.mappers import (
    email_row_from_normalized,
    normalized_email_from_dict,
    normalized_emails_from_dicts,
    reply_draft_from_composer,
)
from app.domain.models import NormalizedEmail, ReplyDraft


def test_normalized_email_from_dict_round_trip() -> None:
    raw = {
        "id": "e1",
        "account_id": "acc-1",
        "from": "user@example.com",
        "subject": "Hello",
        "body": "Body text\nline two",
        "received_at": "2026-05-04T12:00:00Z",
        "thread_id": "thr-1",
        "priority": True,
    }
    email = normalized_email_from_dict(raw, account_id="acc-fallback")
    assert email.id == "e1"
    assert email.account_id == "acc-1"
    assert email.sender == "user@example.com"
    assert email.priority is True
    assert email.to_dict()["from"] == "user@example.com"

    row = email_row_from_normalized(email)
    assert row["id"] == "e1"
    assert row["sender"] == "user@example.com"
    assert row["priority"] is True


def test_normalized_email_from_dict_uses_account_fallback() -> None:
    email = normalized_email_from_dict(
        {"from": "a@b.com", "subject": "S", "body": "B"},
        account_id="acc-x",
    )
    assert email.account_id == "acc-x"
    assert email.preview


def test_normalized_emails_from_dicts_batch() -> None:
    rows = normalized_emails_from_dicts(
        [{"id": "1", "from": "a@x.com", "subject": "A", "body": "a"}],
        account_id="acc",
    )
    assert len(rows) == 1
    assert isinstance(rows[0], NormalizedEmail)


def test_reply_draft_from_composer() -> None:
    draft = reply_draft_from_composer(
        reply_handle="rh-1",
        to="hr@example.com",
        subject="Re: Interview",
        body="Thanks.",
        email_id="e1",
        thread_id="t1",
    )
    assert isinstance(draft, ReplyDraft)
    assert draft.reply_handle == "rh-1"
    assert draft.thread_id == "t1"
