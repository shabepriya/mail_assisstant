from app.domain import errors as err_codes
from app.domain.email_pipeline import map_email_api_error
from app.errors import EmailAPIError


def test_gmail_401_maps_to_session_expired() -> None:
    te = map_email_api_error(EmailAPIError("401 Unauthorized: Gmail session has expired"))
    assert te.code == err_codes.GMAIL_SESSION_EXPIRED
    assert te.retryable is True


def test_gmail_generic_fetch_failed() -> None:
    te = map_email_api_error(EmailAPIError("connection reset"))
    assert te.code == err_codes.GMAIL_FETCH_FAILED
    assert te.retryable is True