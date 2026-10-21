"""Audyt niezmienników (test regresyjny, okresowe sprawdzenie przez worker).

Pusta lista = wszystko w porządku. To nie są reguły decydujące o zapisie,
tylko kontrola, czy kod ich nie złamał.
"""
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Enrollment, Section, WaitlistEntry


@dataclass(frozen=True)
class Violation:
    section_id: int
    problem: str


async def violations(session: AsyncSession) -> list[Violation]:
    out: list[Violation] = []

    enrolled = (select(Enrollment.section_id, func.count().label("n"))
                .where(Enrollment.status == "ENROLLED").group_by(Enrollment.section_id).subquery())
    rows = await session.execute(
        select(Section.id, Section.enrolled_count, func.coalesce(enrolled.c.n, 0))
        .outerjoin(enrolled, enrolled.c.section_id == Section.id)
        .where(Section.enrolled_count != func.coalesce(enrolled.c.n, 0)))
    out += [Violation(sid, f"licznik {cnt} <> liczba zapisanych {n}") for sid, cnt, n in rows]

    rows = await session.execute(
        select(Section.id).distinct().join(WaitlistEntry, WaitlistEntry.section_id == Section.id)
        .where(WaitlistEntry.status == "WAITING", Section.enrolled_count < Section.capacity))
    out += [Violation(sid, "wolne miejsca, a ktoś czeka na liście") for (sid,) in rows]

    rows = await session.execute(
        select(WaitlistEntry.section_id).distinct()
        .join(Enrollment, and_(Enrollment.student_id == WaitlistEntry.student_id,
                               Enrollment.section_id == WaitlistEntry.section_id))
        .where(WaitlistEntry.status == "WAITING", Enrollment.status == "ENROLLED"))
    out += [Violation(sid, "student jednocześnie zapisany i oczekujący") for (sid,) in rows]

    # czeka na grupę przedmiotu, z którego ma już grupę tego samego typu
    ws, es = aliased(Section), aliased(Section)
    rows = await session.execute(
        select(WaitlistEntry.section_id).distinct()
        .join(ws, ws.id == WaitlistEntry.section_id)
        .join(Enrollment, Enrollment.student_id == WaitlistEntry.student_id)
        .join(es, es.id == Enrollment.section_id)
        .where(WaitlistEntry.status == "WAITING", Enrollment.status == "ENROLLED",
               es.course_id == ws.course_id, es.kind == ws.kind, es.term_id == ws.term_id))
    out += [Violation(sid, "czeka mimo grupy tego samego typu") for (sid,) in rows]
    return out
