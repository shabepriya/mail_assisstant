import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.decrypt import decrypt_if_needed
from app.errors import EmailAPIError


def _settings_with_key(key: bytes, encrypted: bool = True) -> Settings:
    return Settings(
        gemini_api_key="x",
        email_payload_encrypted=encrypted,
        email_decrypt_key=key.decode("ascii"),
        email_encrypted_fields="body,subject",
    )


def test_decrypt_if_needed_disabled_passthrough() -> None:
    emails = [{"id": "1", "body": "plain"}]
    s = _settings_with_key(Fernet.generate_key(), encrypted=False)
    assert decrypt_if_needed(emails, s) == emails


def test_decrypt_if_needed_decrypts_fields() -> None:
    key = Fernet.generate_key()
    f = Fernet(key)
    enc_body = f.encrypt(b"hello body").decode("ascii")
    enc_sub = f.encrypt(b"hi subj").decode("ascii")
    emails = [{"id": "1", "body": enc_body, "subject": enc_sub}]
    s = _settings_with_key(key, encrypted=True)
    out = decrypt_if_needed(emails, s)
    assert len(out) == 1
    assert out[0]["body"] == "hello body"
    assert out[0]["subject"] == "hi subj"


def test_decrypt_if_needed_skips_bad_email_keeps_good() -> None:
    key = Fernet.generate_key()
    f = Fernet(key)
    good = {"id": "1", "body": f.encrypt(b"ok").decode("ascii")}
    bad = {"id": "2", "body": "not-a-fernet-token"}
    s = _settings_with_key(key, encrypted=True)
    out = decrypt_if_needed([bad, good], s)
    assert len(out) == 1 and out[0]["id"] == "1"


def test_decrypt_if_needed_all_fail_raises() -> None:
    key = Fernet.generate_key()
    s = _settings_with_key(key, encrypted=True)
    with pytest.raises(EmailAPIError, match="All emails failed"):
        decrypt_if_needed([{"id": "1", "body": "x"}], s)


def test_decrypt_if_needed_missing_key_raises() -> None:
    s = Settings(gemini_api_key="x", email_payload_encrypted=True, email_decrypt_key="")
    with pytest.raises(EmailAPIError, match="EMAIL_DECRYPT_KEY"):
        decrypt_if_needed([{"id": "1"}], s)
