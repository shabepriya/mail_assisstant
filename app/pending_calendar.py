import asyncio
import time
from dataclasses import dataclass


@dataclass
class PendingProposal:
    proposal_id: str
    session_id: str
    title: str
    start_iso: str
    end_iso: str
    timezone: str
    confidence: float
    summary_for_user: str
    requested_confirmation: bool = False
    created_at: float = 0.0


class PendingCalendarStore:
    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._items: dict[tuple[str, str], PendingProposal] = {}

    def _prune(self, now: float) -> None:
        keys = [
            key
            for key, proposal in self._items.items()
            if now - proposal.created_at > self._ttl
        ]
        for key in keys:
            self._items.pop(key, None)

    async def put(self, proposal: PendingProposal) -> None:
        async with self._lock:
            now = time.monotonic()
            self._prune(now)
            proposal.created_at = now
            self._items[(proposal.session_id, proposal.proposal_id)] = proposal

    async def get(self, session_id: str, proposal_id: str) -> PendingProposal | None:
        async with self._lock:
            now = time.monotonic()
            self._prune(now)
            return self._items.get((session_id, proposal_id))

    async def delete(self, session_id: str, proposal_id: str) -> None:
        async with self._lock:
            self._items.pop((session_id, proposal_id), None)

    async def mark_confirmation_requested(self, session_id: str, proposal_id: str) -> None:
        async with self._lock:
            item = self._items.get((session_id, proposal_id))
            if item:
                item.requested_confirmation = True

    async def list_for_session(self, session_id: str) -> list[PendingProposal]:
        async with self._lock:
            now = time.monotonic()
            self._prune(now)
            return [p for (sid, _), p in self._items.items() if sid == session_id]
