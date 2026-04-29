from app.ai import validate_ai_output


def test_validate_ai_output_redacts_numeric_codes() -> None:
    output = validate_ai_output("Please use code 123456 to continue.")
    assert output == "Please use code [REDACTED_CODE] to continue."


def test_validate_ai_output_removes_prefix_disclaimer_only_at_start() -> None:
    raw = "As an AI language model,\nHere is the update with code 1234."
    output = validate_ai_output(raw)
    assert output == "Here is the update with code [REDACTED_CODE]."
