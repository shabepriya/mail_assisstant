from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")
    gemini_timeout: float = Field(default=15.0, validation_alias="GEMINI_TIMEOUT")
    gemini_max_tokens: int = Field(default=300, validation_alias="GEMINI_MAX_TOKENS")

    email_api_base_url: str = Field(
        default="http://localhost:8001", validation_alias="EMAIL_API_BASE_URL"
    )
    email_api_timeout: float = Field(
        default=30.0, validation_alias="EMAIL_API_TIMEOUT"
    )
    email_fetch_limit: int = Field(
        default=20, validation_alias="EMAIL_FETCH_LIMIT"
    )
    email_account_id: str = Field(default="", validation_alias="EMAIL_ACCOUNT_ID")
    email_category: str = Field(default="inbox", validation_alias="EMAIL_CATEGORY")
    email_api_key: str = Field(default="", validation_alias="EMAIL_API_KEY")
    mock_emails: bool = Field(default=True, validation_alias="MOCK_EMAILS")
    email_api_supports_since: bool = Field(
        default=False, validation_alias="EMAIL_API_SUPPORTS_SINCE"
    )

    email_payload_encrypted: bool = Field(
        default=False, validation_alias="EMAIL_PAYLOAD_ENCRYPTED"
    )
    email_decrypt_key: str = Field(default="", validation_alias="EMAIL_DECRYPT_KEY")
    email_encrypted_fields: str = Field(
        default="body,subject", validation_alias="EMAIL_ENCRYPTED_FIELDS"
    )

    max_emails: int = Field(default=50, ge=1, le=500, validation_alias="MAX_EMAILS")
    max_body_chars: int = Field(default=500, ge=50, le=10000, validation_alias="MAX_BODY_CHARS")
    today_fetch_limit: int = Field(
        default=200, ge=1, le=1000, validation_alias="TODAY_FETCH_LIMIT"
    )
    cache_ttl_seconds: float = Field(default=60.0, ge=0, validation_alias="CACHE_TTL_SECONDS")
    max_query_length: int = Field(default=500, ge=1, le=2000, validation_alias="MAX_QUERY_LENGTH")
    max_context_tokens: int = Field(
        default=6000, ge=500, validation_alias="MAX_CONTEXT_TOKENS"
    )
    context_reserve_tokens: int = Field(
        default=1500, ge=200, validation_alias="CONTEXT_RESERVE_TOKENS"
    )
    trim_chunk: int = Field(default=3, ge=1, le=10, validation_alias="TRIM_CHUNK")

    user_timezone: str = Field(default="Asia/Kolkata", validation_alias="USER_TIMEZONE")
    calendar_pending_ttl_seconds: float = Field(
        default=900.0, ge=60, validation_alias="CALENDAR_PENDING_TTL_SECONDS"
    )
    calendar_scheduling_enabled: bool = Field(
        default=False, validation_alias="CALENDAR_SCHEDULING_ENABLED"
    )
    calendar_default_duration_minutes: int = Field(
        default=30, ge=5, le=480, validation_alias="CALENDAR_DEFAULT_DURATION_MINUTES"
    )
    google_calendar_id: str = Field(default="primary", validation_alias="GOOGLE_CALENDAR_ID")
    #: Legacy: static OAuth access token only (expires ~1h; no auto-refresh). Prefer token file.
    google_calendar_token: str = Field(default="", validation_alias="GOOGLE_CALENDAR_TOKEN")
    #: OAuth user token file from InstalledAppFlow (contains refresh_token); auto-refreshes.
    google_calendar_token_path: str = Field(
        default="", validation_alias="GOOGLE_CALENDAR_TOKEN_PATH"
    )
    gmail_send_enabled: bool = Field(default=False, validation_alias="GMAIL_SEND_ENABLED")
    reply_pending_ttl_seconds: float = Field(
        default=900.0, ge=60.0, validation_alias="REPLY_PENDING_TTL_SECONDS"
    )

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    cors_origins: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000",
        validation_alias="CORS_ORIGINS",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
