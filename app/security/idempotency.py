"""In-memory idempotency store for risky /v1 operations."""

from __future__ import annotations

import asyncio
from typing import Any


class IdempotencyStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            return self._data.get(key)

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = value
