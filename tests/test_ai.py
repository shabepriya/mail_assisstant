from app.ai import build_system_message, validate_ai_output
from app.config import get_settings


def test_validate_ai_output_redacts_numeric_codes() -> None:
    output = validate_ai_output("Please use code 123456 to continue.")
    assert output == "Please use code [REDACTED_CODE] to continue."


def test_validate_ai_output_removes_prefix_disclaimer_only_at_start() -> None:
    raw = "As an AI language model,\nHere is the update with code 1234."
    output = validate_ai_output(raw)
    assert output == "Here is the update with code [REDACTED_CODE]."


def test_build_system_message_includes_server_fact_counts() -> None:
    settings = get_settings()
    msg = build_system_message(
        settings,
        email_count=5,
        priority_count=2,
        non_priority_count=3,
    )
    assert "FACTS FROM SERVER" in msg
    assert "priority_tagged=2" in msg
    assert "other=3" in msg
