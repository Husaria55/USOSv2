"""Audyt niezmienników (test regresyjny, okresowe sprawdzenie przez worker).

Pusta lista = wszystko w porządku. To nie są reguły decydujące o zapisie,
tylko kontrola, czy kod ich nie złamał.
"""
from dataclasses import dataclass

from sqlalchemy import and_, func, select, text
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

    # Kolizje w planach studentów. Celowo niezależna implementacja reguły z app/domain/schedule.py
    # (w SQL): audyt ma wykryć błąd w kodzie decydującym o zapisie, a nie powtórzyć ten sam błąd.
    rows = await session.execute(text(
        "SELECT DISTINCT e1.section_id, e1.student_id, e2.section_id "
        "FROM enrollment e1 JOIN enrollment e2 ON e2.student_id = e1.student_id AND e2.section_id > e1.section_id "
        "JOIN section s1 ON s1.id = e1.section_id JOIN section s2 ON s2.id = e2.section_id AND s2.term_id = s1.term_id "
        "JOIN meeting m1 ON m1.section_id = s1.id JOIN meeting m2 ON m2.section_id = s2.id "
        "WHERE e1.status = 'ENROLLED' AND e2.status = 'ENROLLED' AND m1.weekday = m2.weekday "
        "  AND m1.start_time < m2.end_time AND m2.start_time < m1.end_time "
        "  AND (m1.week_parity = 'ALL' OR m2.week_parity = 'ALL' OR m1.week_parity = m2.week_parity)"))
    out += [Violation(a, f"student {st} ma kolizję z grupą {b}") for a, st, b in rows]

    rows = await session.execute(text(
        "SELECT DISTINCT e1.section_id, e1.student_id, e2.section_id "
        "FROM enrollment e1 JOIN enrollment e2 ON e2.student_id = e1.student_id AND e2.section_id > e1.section_id "
        "JOIN section s1 ON s1.id = e1.section_id JOIN section s2 ON s2.id = e2.section_id "
        "WHERE e1.status = 'ENROLLED' AND e2.status = 'ENROLLED' AND s1.term_id = s2.term_id "
        "  AND s1.course_id = s2.course_id AND s1.kind = s2.kind"))
    out += [Violation(a, f"student {st} ma drugą grupę tego samego typu: {b}") for a, st, b in rows]
    return out
