import asyncio

from app.pending_calendar import PendingCalendarStore, PendingProposal


def test_pending_calendar_store_session_scoped() -> None:
    store = PendingCalendarStore(ttl_seconds=120)
    proposal = PendingProposal(
        proposal_id="p1",
        session_id="s1",
        title="Meeting",
        start_iso="2026-05-01T21:00:00+05:30",
        end_iso="2026-05-01T21:30:00+05:30",
        timezone="Asia/Kolkata",
        confidence=0.9,
        summary_for_user="Meeting at 9 PM",
    )
    asyncio.run(store.put(proposal))
    assert asyncio.run(store.get("s1", "p1")) is not None
    assert asyncio.run(store.get("s2", "p1")) is None


def test_pending_calendar_store_ttl_expiry() -> None:
    store = PendingCalendarStore(ttl_seconds=0.001)
    proposal = PendingProposal(
        proposal_id="p2",
        session_id="s1",
        title="Meeting",
        start_iso="2026-05-01T21:00:00+05:30",
        end_iso="2026-05-01T21:30:00+05:30",
        timezone="Asia/Kolkata",
        confidence=0.9,
        summary_for_user="Meeting at 9 PM",
    )
    asyncio.run(store.put(proposal))
    asyncio.run(asyncio.sleep(0.01))
    assert asyncio.run(store.get("s1", "p2")) is None
