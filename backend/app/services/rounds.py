"""Tury zapisów (UC16, UC17, UC18)."""
from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.rounds import RoundInfo, covers, scheduled_transition
from app.errors import Conflict, NotFound
from app.models import EnrollmentRound, Program, RoundProgram, Section, User, WaitlistEntry
from app.services import loaders
from app.services.notifications import notify_many, payload


async def create_round(session: AsyncSession, term_id: int, name: str, opens_at: datetime,
                       closes_at: datetime, program_ids: list[int]) -> int:
    if opens_at >= closes_at:
        raise Conflict("BAD_DATES", "Tura musi się kończyć po rozpoczęciu.")
    await _check_programs(session, program_ids)
    rid = (await session.execute(insert(EnrollmentRound).values(
        term_id=term_id, name=name, opens_at=opens_at, closes_at=closes_at)
        .returning(EnrollmentRound.id))).scalar_one()
    await _set_programs(session, rid, program_ids)
    return rid


async def update_round(session: AsyncSession, round_id: int, *, opens_at: datetime | None = None,
                       closes_at: datetime | None = None, program_ids: list[int] | None = None) -> None:
    r = await _get(session, round_id)
    opens_at, closes_at = opens_at or r.opens_at, closes_at or r.closes_at
    if opens_at >= closes_at:
        raise Conflict("BAD_DATES", "Tura musi się kończyć po rozpoczęciu.")
    await session.execute(update(EnrollmentRound).where(EnrollmentRound.id == round_id)
                          .values(opens_at=opens_at, closes_at=closes_at))
    if program_ids is not None:
        await _check_programs(session, program_ids)
        await session.execute(delete(RoundProgram).where(RoundProgram.round_id == round_id))
        await _set_programs(session, round_id, program_ids)
        if r.status == "OPEN":
            await expire_uncovered(session, r.term_id)


async def open_round(session: AsyncSession, round_id: int) -> None:
    """UC16: ręczne otwarcie (także ponowne, np. po awarii)."""
    await _get(session, round_id, lock=True)
    await session.execute(update(EnrollmentRound).where(EnrollmentRound.id == round_id).values(status="OPEN"))


async def close_round(session: AsyncSession, round_id: int) -> int:
    """UC16/UC17 + UC18: zamknięcie i wygaszenie list. Zwraca liczbę wygasłych wpisów."""
    r = await _get(session, round_id, lock=True)
    await session.execute(update(EnrollmentRound).where(EnrollmentRound.id == round_id).values(status="CLOSED"))
    return await expire_uncovered(session, r.term_id)


async def expire_uncovered(session: AsyncSession, term_id: int) -> int:
    """UC18: wpisy WAITING studentów, których kierunku nie obejmuje już żadna otwarta tura.

    Bez tego wypis przez dziekanat po turze zapisałby kogoś z listy bez jego
    wiedzy. Worker woła to też okresowo, bo zapis, który zaczął się tuż przed
    zamknięciem tury, mógł dopisać kogoś na listę już po wygaszeniu.
    """
    open_rounds = await loaders.term_rounds(session, term_id, only_open=True)
    programs = (await session.execute(select(Program.id))).scalars().all()
    uncovered = [p for p in programs if not any(covers(r, p) for r in open_rounds)]
    if not uncovered:
        return 0
    rows = (await session.execute(
        update(WaitlistEntry)
        .where(WaitlistEntry.status == "WAITING",
               WaitlistEntry.section_id.in_(select(Section.id).where(Section.term_id == term_id)),
               WaitlistEntry.student_id.in_(select(User.id).where(User.program_id.in_(uncovered))))
        .values(status="EXPIRED", resolved_at=func.now())
        .returning(WaitlistEntry.student_id, WaitlistEntry.section_id))).all()
    labels = await loaders.section_labels(session, {sid for _, sid in rows})
    await notify_many(session, [(uid, "EXPIRED", payload("EXPIRED", labels[sid])) for uid, sid in rows])
    return len(rows)


async def apply_schedule(session: AsyncSession, now: datetime) -> list[tuple[int, str]]:
    """UC17: worker otwiera i zamyka tury według opens_at / closes_at."""
    rounds = (await session.execute(
        select(EnrollmentRound).where(EnrollmentRound.status.in_(["PLANNED", "OPEN"]))
        .with_for_update(skip_locked=True))).scalars().all()
    changes = []
    for r in rounds:
        info = RoundInfo(r.id, r.status, r.opens_at, r.closes_at, frozenset())
        new = scheduled_transition(info, now)
        if new == "OPEN":
            await open_round(session, r.id)
        elif new == "CLOSED":
            await close_round(session, r.id)
        if new:
            changes.append((r.id, new))
    return changes


async def _get(session: AsyncSession, round_id: int, lock: bool = False) -> EnrollmentRound:
    q = select(EnrollmentRound).where(EnrollmentRound.id == round_id)
    if lock:
        q = q.with_for_update()
    r = (await session.execute(q)).scalar_one_or_none()
    if r is None:
        raise NotFound("ROUND_NOT_FOUND", "Nie ma takiej tury.")
    return r


async def _check_programs(session: AsyncSession, program_ids: list[int]) -> None:
    if program_ids:
        found = (await session.execute(select(func.count()).select_from(Program)
                                       .where(Program.id.in_(program_ids)))).scalar_one()
        if found != len(set(program_ids)):
            raise NotFound("PROGRAM_NOT_FOUND", "Nie ma takiego kierunku.")


async def _set_programs(session: AsyncSession, round_id: int, program_ids: list[int]) -> None:
    if program_ids:
        await session.execute(insert(RoundProgram),
                              [{"round_id": round_id, "program_id": p} for p in set(program_ids)])
