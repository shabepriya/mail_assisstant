import asyncio
import time
import uuid
from dataclasses import dataclass


@dataclass
class PendingReplySnapshot:
    action_id: str
    session_id: str
    email_id: str
    from_addr: str
    subject: str
    body_plain: str
    created_at: float = 0.0


class PendingReplyStore:
    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._items: dict[tuple[str, str], PendingReplySnapshot] = {}

    def _prune(self, now: float) -> None:
        keys = [
            key
            for key, snap in self._items.items()
            if now - snap.created_at > self._ttl
        ]
        for key in keys:
            self._items.pop(key, None)

    async def put(self, snap: PendingReplySnapshot) -> None:
        async with self._lock:
            now = time.monotonic()
            self._prune(now)
            snap.created_at = now
            self._items[(snap.session_id, snap.action_id)] = snap

    async def get(self, session_id: str, action_id: str) -> PendingReplySnapshot | None:
        async with self._lock:
            now = time.monotonic()
            self._prune(now)
            return self._items.get((session_id, action_id))

    async def delete(self, session_id: str, action_id: str) -> None:
        async with self._lock:
            self._items.pop((session_id, action_id), None)

    @staticmethod
    def new_action_id() -> str:
        return f"reply_{uuid.uuid4().hex[:12]}"

