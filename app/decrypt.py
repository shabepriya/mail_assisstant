import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings
from app.errors import EmailAPIError

logger = logging.getLogger(__name__)


def _decrypt_fields(email: dict[str, Any], f: Fernet, fields: list[str]) -> dict[str, Any]:
    new = dict(email)
    for field in fields:
        if field not in new:
            continue
        val = new[field]
        if not isinstance(val, str) or not val.strip():
            continue
        new[field] = f.decrypt(val.strip().encode("ascii")).decode("utf-8")
    return new


def decrypt_if_needed(
    emails: list[dict[str, Any]], settings: Settings
) -> list[dict[str, Any]]:
    """Decrypt configured string fields per email (Fernet). Skip emails that fail."""
    if not settings.email_payload_encrypted:
        return emails
    key = settings.email_decrypt_key.strip()
    if not key:
        raise EmailAPIError("EMAIL_DECRYPT_KEY is required when EMAIL_PAYLOAD_ENCRYPTED=true")
    try:
        f = Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as e:
        raise EmailAPIError(f"Invalid Fernet key: {e}") from e

    fields = [x.strip() for x in settings.email_encrypted_fields.split(",") if x.strip()]
    if not fields:
        return emails

    out: list[dict[str, Any]] = []
    for email in emails:
        try:
            out.append(_decrypt_fields(email, f, fields))
        except (InvalidToken, ValueError, TypeError, UnicodeDecodeError) as e:
            logger.warning(
                "decrypt_failed id=%s type=%s",
                email.get("id"),
                type(e).__name__,
            )
    if not out and emails:
        raise EmailAPIError("All emails failed decryption")
    return out
