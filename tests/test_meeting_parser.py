from app.config import get_settings
from app.meeting_parser import extract_meeting_proposals_from_emails


def test_extract_meeting_proposal_with_tomorrow_and_time() -> None:
    settings = get_settings()
    emails = [
        {
            "subject": "Project meeting tomorrow",
            "body": "Let's have a meeting tomorrow at 9 PM IST.",
        }
    ]
    proposals = extract_meeting_proposals_from_emails(emails, settings)
    assert len(proposals) == 1
    assert proposals[0].title == "Project meeting tomorrow"
    assert proposals[0].start_local.hour == 21
    assert proposals[0].end_local > proposals[0].start_local
    assert 0 <= proposals[0].confidence <= 1


def test_extract_meeting_proposal_timezone_conversion() -> None:
    settings = get_settings()
    emails = [
        {
            "subject": "Client call",
            "body": "Client call tomorrow 9 PM PST",
        }
    ]
    proposals = extract_meeting_proposals_from_emails(emails, settings)
    assert len(proposals) == 1
    assert proposals[0].timezone == settings.user_timezone
