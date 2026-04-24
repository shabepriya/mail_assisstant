import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class EmailCache:
    """In-memory TTL cache with stale fallback on fetch failure."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._emails: list[dict[str, Any]] | None = None
        self._last_fetch: float = 0.0
        self._strategy: str | None = None

    async def get(
        self,
        force_refresh: bool,
        strategy: str,
        fetch_fn: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> tuple[list[dict[str, Any]], float, bool]:
        """
        Returns (emails, cache_age_s, stale).
        stale=True when returning cached data after a failed refresh attempt.
        """
        async with self._lock:
            now = time.monotonic()
            age = now - self._last_fetch if self._last_fetch > 0 else float("inf")
            cache_hit = (
                self._emails is not None
                and age < self._ttl
                and not force_refresh
                and self._strategy == strategy
            )
            if cache_hit:
                return self._emails or [], age, False

            try:
                emails = await fetch_fn()
                self._emails = emails
                self._last_fetch = time.monotonic()
                self._strategy = strategy
                return emails, 0.0, False
            except Exception as exc:
                if self._emails is not None:
                    stale_age = now - self._last_fetch
                    logger.warning(
                        "email_api_failed_serving_stale age_s=%s error=%s",
                        stale_age,
                        exc,
                    )
                    return list(self._emails), stale_age, True
                raise
