from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app import worker
from app.config import settings
from app.db import Session, run_transaction
from app.models import EnrollmentRound, Notification, WaitlistEntry
from app.services import enrollment, notifications
from tests import factories as f


async def test_schedule_opens_and_closes_rounds():
    p, t = await f.program(), await f.term()
    planned = await f.round_(t, [p], status="PLANNED")
    sec = await f.section(await f.course(), t, capacity=1)
    a, b = await f.students(p, 2)
    await worker.schedule_rounds()                         # opens_at minął -> OPEN
    async with Session() as s:
        assert (await s.get(EnrollmentRound, planned)).status == "OPEN"
    for st in (a, b):
        await run_transaction(lambda s: enrollment.enroll(s, st, sec))

    async with Session() as s, s.begin():                  # czas tury minął
        await s.execute(update(EnrollmentRound).values(closes_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                                                       opens_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    await worker.schedule_rounds()
    async with Session() as s:
        assert (await s.get(EnrollmentRound, planned)).status == "CLOSED"
        statuses = (await s.execute(select(WaitlistEntry.status))).scalars().all()
    assert statuses == ["EXPIRED"]


async def test_straggler_waitlist_entries_expire():
    """Wpis dodany po zamknięciu tury (wyścig z zamknięciem) wygasa w kolejnym przebiegu."""
    p, t = await f.program(), await f.term()
    await f.round_(t, [p], status="CLOSED")
    sec = await f.section(await f.course(), t, capacity=1)
    a = await f.student(p)
    async with Session() as s, s.begin():
        s.add(WaitlistEntry(student_id=a, section_id=sec))
    await worker.expire_stragglers()
    async with Session() as s:
        assert (await s.execute(select(WaitlistEntry.status))).scalar_one() == "EXPIRED"


async def test_outbox_counts_failed_attempts_when_smtp_is_down(monkeypatch):
    p = await f.program()
    st = await f.student(p)
    async with Session() as s, s.begin():
        await notifications.notify(s, st, "PROMOTED", "IO L01")
    monkeypatch.setattr(settings, "smtp_port", 1)          # nic tam nie słucha
    assert await worker.send_outbox() == 0
    async with Session() as s:
        n = (await s.execute(select(Notification))).scalar_one()
    assert n.attempts == 1 and n.sent_at is None
