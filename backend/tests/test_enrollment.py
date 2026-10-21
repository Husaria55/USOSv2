"""EnrollmentService na prawdziwym PostgreSQL: reguły, listy oczekujących, wyścigi."""
import asyncio

import pytest
from sqlalchemy import select, text

from app.db import Session, run_transaction
from app.domain.enrollment_rules import Mode
from app.errors import Conflict
from app.models import Enrollment, Notification, Section, WaitlistEntry
from app.services import audit, enrollment, rounds
from tests import factories as f


async def enroll(student, section, mode=Mode.DIRECT, actor=None):
    return await run_transaction(lambda s: enrollment.enroll(s, student, section, mode=mode, actor_id=actor))


async def drop(student, section, mode=Mode.DIRECT, actor=None):
    return await run_transaction(lambda s: enrollment.drop(s, student, section, mode=mode, actor_id=actor))


async def refusal(coro) -> str:
    with pytest.raises(Conflict) as e:
        await coro
    return e.value.code


async def section_state(sid):
    async with Session() as s:
        sec = (await s.execute(select(Section).where(Section.id == sid))).scalar_one()
        waiting = (await s.execute(select(WaitlistEntry.student_id).where(
            WaitlistEntry.section_id == sid, WaitlistEntry.status == "WAITING").order_by(WaitlistEntry.id))).scalars().all()
        enrolled = (await s.execute(select(Enrollment.student_id).where(
            Enrollment.section_id == sid, Enrollment.status == "ENROLLED"))).scalars().all()
        return sec.enrolled_count, sec.capacity, set(enrolled), list(waiting)


async def entry_status(student, sid):
    async with Session() as s:
        return (await s.execute(select(WaitlistEntry.status).where(
            WaitlistEntry.student_id == student, WaitlistEntry.section_id == sid)
            .order_by(WaitlistEntry.id.desc()))).scalars().first()


async def assert_invariants():
    async with Session() as s:
        assert await audit.violations(s) == []


@pytest.fixture
async def world():
    p = await f.program("INF")
    t = await f.term()
    await f.round_(t, [p])
    return p, t


async def test_enroll_and_refusals(world):
    p, t = world
    am1 = await f.course("AM1")
    io = await f.course("IO", requires=[am1])
    bd = await f.course("BD")
    ania, bartek = await f.student(p), await f.student(p)
    await f.passed(ania, am1, t, "4.5")
    await f.passed(bartek, am1, t, "2.0")
    io_l1 = await f.section(io, t, "L01")
    io_l2 = await f.section(io, t, "L02", meetings=[(2, "10:00", "11:30")])
    io_w = await f.section(io, t, "W01", kind="LECTURE", meetings=[(3, "8:00", "9:30")])
    bd_l = await f.section(bd, t, "L01", meetings=[(1, "11:00", "12:30")])

    assert (await enroll(ania, io_l1)).status == "ENROLLED"
    assert await refusal(enroll(bartek, io_l1)) == "PREREQUISITES"
    assert await refusal(enroll(ania, io_l1)) == "ALREADY_ENROLLED"
    assert await refusal(enroll(ania, io_l2)) == "SAME_KIND"
    assert (await enroll(ania, io_w)).status == "ENROLLED"        # wykład i lab z IO - wolno
    assert await refusal(enroll(ania, bd_l)) == "CONFLICT"
    await assert_invariants()


async def test_round_per_program(world):
    p, t = world
    other = await f.program("MAT")
    c = await f.course()
    sec = await f.section(c, t)
    mat_student = await f.student(other)
    assert await refusal(enroll(mat_student, sec)) == "ROUND_CLOSED"
    await f.round_(t, [other])
    assert (await enroll(mat_student, sec)).status == "ENROLLED"


async def test_race_for_last_seats(world):
    """30 studentów naraz do grupy na 10 miejsc."""
    p, t = world
    sec = await f.section(await f.course(), t, capacity=10)
    students = await f.students(p, 30)
    results = await asyncio.gather(*(enroll(s, sec) for s in students))
    assert sorted(r.status for r in results) == ["ENROLLED"] * 10 + ["WAITLISTED"] * 20
    count, cap, enrolled, waiting = await section_state(sec)
    assert count == 10 and len(enrolled) == 10 and len(waiting) == 20
    # pozycje na liście są unikalne i zgodne z kolejnością
    positions = sorted(r.position for r in results if r.position)
    assert positions == list(range(1, 21))
    await assert_invariants()


async def test_same_student_two_tabs(world):
    """Dwa równoległe zapisy jednego studenta do kolidujących grup: przechodzi jeden."""
    p, t = world
    a = await f.section(await f.course(), t)
    b = await f.section(await f.course(), t)                   # ten sam termin
    st = await f.student(p)
    results = await asyncio.gather(enroll(st, a), enroll(st, b), return_exceptions=True)
    assert sum(1 for r in results if isinstance(r, Conflict) and r.code == "CONFLICT") == 1
    assert sum(1 for r in results if not isinstance(r, Exception)) == 1


async def test_waitlist_promotion_with_skip(world):
    """Scenariusz 4 z prototypu."""
    p, t = world
    c, bd = await f.course(), await f.course()
    l1 = await f.section(c, t, "L01", capacity=2)
    bd_l5 = await f.section(bd, t, "L05", meetings=[(1, "10:00", "11:30")])   # koliduje z L01
    s1, s2, s3, s4, s5 = await f.students(p, 5)
    for s in (s1, s2, s3, s4, s5):
        await enroll(s, l1)
    assert (await section_state(l1))[3] == [s3, s4, s5]

    await enroll(s3, bd_l5)                                     # s3 ma teraz kolizję
    assert await run_transaction(lambda s: enrollment.change_limits(s, l1, capacity=2)) == []
    assert await entry_status(s3, l1) == "WAITING"              # bez miejsca nikt nie jest pomijany

    events = await drop(s1, l1)
    assert [(e.student_id, e.status) for e in events] == [(s3, "SKIPPED"), (s4, "PROMOTED")]
    events = await run_transaction(lambda s: enrollment.change_limits(s, l1, capacity=3))
    assert [(e.student_id, e.status) for e in events] == [(s5, "PROMOTED")]
    async with Session() as s:
        types = (await s.execute(select(Notification.user_id, Notification.type).order_by(Notification.id))).all()
    assert types == [(s3, "SKIPPED"), (s4, "PROMOTED"), (s5, "PROMOTED")]
    await assert_invariants()


async def test_concurrent_drops_promote_in_order(world):
    p, t = world
    sec = await f.section(await f.course(), t, capacity=4)
    students = await f.students(p, 8)
    for s in students:
        await enroll(s, sec)
    await asyncio.gather(drop(students[0], sec), drop(students[1], sec))
    count, _, enrolled, waiting = await section_state(sec)
    assert count == 4 and set(students[4:6]) <= enrolled and waiting == students[6:]
    await assert_invariants()


async def test_promotion_vs_enrollment_no_deadlock(world):
    """Wypis A awansuje B, a B w tej samej chwili zapisuje się gdzie indziej.

    Zwykłe FOR UPDATE kończyłoby się zakleszczeniem; NOWAIT + ponowienie daje
    spójny wynik w każdej kolejności.
    """
    p, t = world
    for _ in range(10):
        c = await f.course()
        sec = await f.section(c, t, "L01", capacity=1)
        other = await f.section(c, t, "L02", meetings=[(4, "8:00", "9:30")])
        a, b = await f.students(p, 2)
        await enroll(a, sec)
        await enroll(b, sec)                                     # b czeka
        await asyncio.gather(drop(a, sec), enroll(b, other), return_exceptions=True)
        count, _, enrolled, waiting = await section_state(sec)
        _, _, enrolled_other, _ = await section_state(other)
        # b ma dokładnie jedną grupę LAB z tego przedmiotu
        assert (b in enrolled) != (b in enrolled_other)
        assert waiting == []
    await assert_invariants()


async def test_enrollment_cancels_same_kind_waitlists(world):
    p, t = world
    c = await f.course()
    l3 = await f.section(c, t, "L03", capacity=1)
    l5 = await f.section(c, t, "L05", meetings=[(2, "8:00", "9:30")])
    ola, piotr = await f.students(p, 2)
    await enroll(ola, l3)
    assert (await enroll(piotr, l3)).status == "WAITLISTED"
    res = await enroll(piotr, l5)
    assert res.cancelled_waitlists == [f"{(await section_label(l3))}"]
    assert await entry_status(piotr, l3) == "CANCELLED"
    assert await refusal(enroll(piotr, l3)) == "SAME_KIND"


async def section_label(sid):
    async with Session() as s:
        return (await s.execute(text("SELECT c.code || ' ' || s.code FROM section s JOIN course c ON c.id = s.course_id "
                                     "WHERE s.id = :id"), {"id": sid})).scalar_one()


async def test_waitlist_limit(world):
    p, t = world
    sec = await f.section(await f.course(), t, capacity=1, waitlist_limit=1)
    a, b, c = await f.students(p, 3)
    await enroll(a, sec)
    await enroll(b, sec)
    assert await refusal(enroll(c, sec)) == "WAITLIST_FULL"
    assert await refusal(enroll(b, sec)) == "ALREADY_WAITING"
    await run_transaction(lambda s: enrollment.leave_waitlist(s, b, sec))
    assert (await enroll(c, sec)).position == 1


async def test_admin_over_capacity_and_round_closing(world):
    """Scenariusz 6 z prototypu."""
    p, t = world
    adm = await f.admin()
    room = await f.room(seats=3)
    c = await f.course()
    req = await f.course()
    c_req = await f.course(requires=[req])
    sec = await f.section(c_req, t, "L07", capacity=2, room_id=room)
    ola, ala, kuba, ewa = await f.students(p, 4)
    for s in (ola, ala):
        await f.passed(s, req, t)
    await f.passed(kuba, req, t)
    await enroll(ola, sec)
    await enroll(ala, sec)
    assert (await enroll(kuba, sec)).status == "WAITLISTED"
    # dziekanat: bez wymagań, ponad limit (sala ma 3 miejsca)
    assert (await enroll(ewa, sec, Mode.ADMIN, adm)).status == "ENROLLED"
    count, cap, _, waiting = await section_state(sec)
    assert (count, cap, waiting) == (3, 3, [kuba])
    extra = await f.student(p)
    assert await refusal(enroll(extra, sec, Mode.ADMIN, adm)) == "ROOM_FULL"

    async with Session() as s:
        rid = (await s.execute(text("SELECT id FROM enrollment_round"))).scalar_one()
    assert await run_transaction(lambda s: rounds.close_round(s, rid)) == 1
    assert await entry_status(kuba, sec) == "EXPIRED"
    assert await refusal(drop(ola, sec)) == "ROUND_CLOSED"
    assert await drop(ola, sec, Mode.ADMIN, adm) == []         # po turze nikt nie awansuje
    await assert_invariants()


async def test_closing_one_program_round_keeps_other_programs_waiting(world):
    p, t = world
    mat = await f.program("MAT")
    mat_round = await f.round_(t, [mat])
    sec = await f.section(await f.course(), t, capacity=1)
    inf1, inf2 = await f.students(p, 2)
    m1 = await f.student(mat)
    await enroll(inf1, sec)
    await enroll(inf2, sec)
    await enroll(m1, sec)
    assert await run_transaction(lambda s: rounds.close_round(s, mat_round)) == 1
    assert await entry_status(m1, sec) == "EXPIRED"
    assert await entry_status(inf2, sec) == "WAITING"

