"""Dostęp do danych dla reguł z app/domain i dla EnrollmentService.

Same odczyty i proste zapisy: zapytania tylko pobierają i zapisują dane, decyzje
zapadają w domenie. To gorąca ścieżka przy otwarciu tury, więc zapytania idą
bezpośrednio przez asyncpg (przygotowane instrukcje, bez narzutu ORM) w tej samej
transakcji co sesja SQLAlchemy. Pomiar: narzut budowania zapytań w ORM był
głównym kosztem CPU API przy 1000 studentów naraz.
"""
import time
from collections import defaultdict
from dataclasses import dataclass

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enrollment_rules import PlanEntry, StudentState, TargetSection, WaitingEntry
from app.domain.rounds import RoundInfo, student_can_enroll
from app.domain.schedule import Slot
from app.errors import NotFound


_START = text("SELECT 1")


async def pg(session: AsyncSession) -> asyncpg.Connection:
    """Połączenie asyncpg bieżącej transakcji sesji.

    SQLAlchemy otwiera transakcję w asyncpg leniwie, przy pierwszym własnym zapytaniu.
    Bez tego zapytania poniżej szłyby w trybie autocommit i FOR UPDATE zwalniałoby
    blokadę od razu (test wyścigu o miejsca to wykrył: CHECK odrzucił 11/10).
    """
    conn = await session.connection()
    driver = (await conn.get_raw_connection()).driver_connection
    if not driver.is_in_transaction():
        await session.execute(_START)
    return driver


@dataclass(frozen=True)
class LockedStudent:
    id: int
    program_id: int


@dataclass
class LockedSection:
    """Stan grupy pod blokadą. Serwis aktualizuje go razem z UPDATE w bazie."""
    id: int
    capacity: int
    enrolled_count: int
    waitlist_limit: int


async def lock_student(session: AsyncSession, student_id: int, *, nowait: bool = False) -> LockedStudent:
    """Blokada wiersza studenta (zawsze przed blokadą grupy, poza awansem z listy)."""
    row = await (await pg(session)).fetchrow(
        "SELECT id, program_id FROM app_user WHERE id = $1 AND role = 'STUDENT' FOR UPDATE"
        + (" NOWAIT" if nowait else ""), student_id)
    if row is None:
        raise NotFound("STUDENT_NOT_FOUND", "Nie ma takiego studenta.")
    return LockedStudent(row[0], row[1])


async def lock_section(session: AsyncSession, section_id: int) -> LockedSection:
    row = await (await pg(session)).fetchrow(
        "SELECT id, capacity, enrolled_count, waitlist_limit FROM section WHERE id = $1 FOR UPDATE", section_id)
    if row is None:
        raise NotFound("SECTION_NOT_FOUND", "Nie ma takiej grupy.")
    return LockedSection(*row)


async def slots_by_section(session: AsyncSession, section_ids) -> dict[int, tuple[Slot, ...]]:
    ids = list(section_ids)
    out: dict[int, list[Slot]] = defaultdict(list)
    if ids:
        rows = await (await pg(session)).fetch(
            "SELECT section_id, weekday, start_time, end_time, week_parity FROM meeting "
            "WHERE section_id = ANY($1::bigint[])", ids)
        for sid, wd, st, en, par in rows:
            out[sid].append(Slot(wd, st, en, par))
    return {sid: tuple(out.get(sid, ())) for sid in ids}


async def load_targets(session: AsyncSession, section_ids) -> dict[int, tuple[TargetSection, int]]:
    """Grupy docelowe i ich semestry (dane katalogu, bez blokady). Trzy zapytania niezależnie od liczby grup."""
    ids = list(section_ids)
    if not ids:
        return {}
    db = await pg(session)
    rows = await db.fetch(
        "SELECT s.id, s.course_id, c.code, s.code, s.kind, s.term_id FROM section s "
        "JOIN course c ON c.id = s.course_id WHERE s.id = ANY($1::bigint[])", ids)
    prereqs: dict[int, dict[int, str]] = defaultdict(dict)
    for course_id, req_id, req_code in await db.fetch(
            "SELECT p.course_id, c.id, c.code FROM course_prerequisite p "
            "JOIN course c ON c.id = p.required_course_id WHERE p.course_id = ANY($1::bigint[])",
            list({r[1] for r in rows})):
        prereqs[course_id][req_id] = req_code
    slots = await slots_by_section(session, [r[0] for r in rows])
    return {sid: (TargetSection(sid, cid, ccode, code, kind, slots[sid], prereqs.get(cid, {})), term_id)
            for sid, cid, ccode, code, kind, term_id in rows}


# Dane katalogowe grupy (kurs, typ, terminy, wymagania) prawie nie zmieniają się w trakcie
# tury, a są potrzebne przy każdym zapisie. Trzymamy je krótko w pamięci procesu; zmiany
# dziekanatu w tym procesie czyszczą cache od razu, w pozostałych po TARGET_TTL_S.
TARGET_TTL_S = 10.0
_targets: dict[int, tuple[float, tuple[TargetSection, int]]] = {}


def forget_targets() -> None:
    _targets.clear()


async def load_target(session: AsyncSession, section_id: int) -> tuple[TargetSection, int]:
    now = time.monotonic()
    hit = _targets.get(section_id)
    if hit and hit[0] > now:
        return hit[1]
    found = (await load_targets(session, [section_id])).get(section_id)
    if found is None:
        raise NotFound("SECTION_NOT_FOUND", "Nie ma takiej grupy.")
    if len(_targets) > 50_000:
        _targets.clear()
    _targets[section_id] = (now + TARGET_TTL_S, found)
    return found


async def room_seats(session: AsyncSession, section_id: int) -> int | None:
    """Najmniejsza sala spośród terminów grupy (limit grupy nie może jej przekroczyć)."""
    return await (await pg(session)).fetchval(
        "SELECT min(r.seats) FROM meeting m JOIN room r ON r.id = m.room_id WHERE m.section_id = $1", section_id)


async def term_rounds(session: AsyncSession, term_id: int, *, only_open: bool = False) -> list[RoundInfo]:
    rows = await (await pg(session)).fetch(
        "SELECT r.id, r.status, r.opens_at, r.closes_at, array_remove(array_agg(rp.program_id), NULL) "
        "FROM enrollment_round r LEFT JOIN round_program rp ON rp.round_id = r.id "
        "WHERE r.term_id = $1 AND ($2 = false OR r.status = 'OPEN') GROUP BY r.id", term_id, only_open)
    return [RoundInfo(rid, st, a, b, frozenset(progs)) for rid, st, a, b, progs in rows]


async def student_plan(session: AsyncSession, student_id: int, term_id: int) -> tuple[PlanEntry, ...]:
    rows = await (await pg(session)).fetch(
        "SELECT s.id, s.code, c.code, s.course_id, s.kind, m.weekday, m.start_time, m.end_time, m.week_parity "
        "FROM enrollment e JOIN section s ON s.id = e.section_id JOIN course c ON c.id = s.course_id "
        "LEFT JOIN meeting m ON m.section_id = s.id "
        "WHERE e.student_id = $1 AND e.status = 'ENROLLED' AND s.term_id = $2", student_id, term_id)
    sections: dict[int, tuple] = {}
    slots: dict[int, list[Slot]] = defaultdict(list)
    for sid, code, ccode, cid, kind, wd, st, en, par in rows:
        sections[sid] = (code, ccode, cid, kind)
        if wd is not None:
            slots[sid].append(Slot(wd, st, en, par))
    return tuple(PlanEntry(sid, code, ccode, tuple(slots[sid]), cid, kind)
                 for sid, (code, ccode, cid, kind) in sections.items())


async def student_waiting(session: AsyncSession, student_id: int, term_id: int) -> list[WaitingEntry]:
    rows = await (await pg(session)).fetch(
        "SELECT w.id, s.id, s.course_id, s.kind FROM waitlist_entry w JOIN section s ON s.id = w.section_id "
        "WHERE w.student_id = $1 AND w.status = 'WAITING' AND s.term_id = $2", student_id, term_id)
    return [WaitingEntry(*r) for r in rows]


async def passed_courses(session: AsyncSession, student_id: int) -> frozenset[int]:
    rows = await (await pg(session)).fetch(
        "SELECT DISTINCT course_id FROM completed_course WHERE student_id = $1 AND passed", student_id)
    return frozenset(r[0] for r in rows)


async def student_state(session: AsyncSession, student: LockedStudent, term_id: int,
                        rounds: list[RoundInfo] | None = None, *,
                        need_passed: bool = True) -> tuple[StudentState, list[WaitingEntry]]:
    """need_passed=False: kurs bez wymagań wstępnych, zaliczeń nie trzeba czytać."""
    if rounds is None:
        rounds = await term_rounds(session, term_id, only_open=True)
    waiting = await student_waiting(session, student.id, term_id)
    state = StudentState(
        round_open=student_can_enroll(rounds, student.program_id),
        plan=await student_plan(session, student.id, term_id),
        passed_course_ids=await passed_courses(session, student.id) if need_passed else frozenset(),
        waiting_section_ids=frozenset(w.section_id for w in waiting),
    )
    return state, waiting


async def waiting_count(session: AsyncSession, section_id: int) -> int:
    return await (await pg(session)).fetchval(
        "SELECT count(*) FROM waitlist_entry WHERE section_id = $1 AND status = 'WAITING'", section_id)


async def section_labels(session: AsyncSession, section_ids) -> dict[int, str]:
    ids = list(section_ids)
    if not ids:
        return {}
    rows = await (await pg(session)).fetch(
        "SELECT s.id, c.code, s.code FROM section s JOIN course c ON c.id = s.course_id "
        "WHERE s.id = ANY($1::bigint[])", ids)
    return {sid: f"{c} {s}" for sid, c, s in rows}


async def waitlist_positions(session: AsyncSession, student_id: int, section_ids=None) -> dict[int, int]:
    """Pozycje studenta na listach (id grupy -> pozycja), jednym zapytaniem."""
    rows = await (await pg(session)).fetch(
        "SELECT w.section_id, (SELECT count(*) FROM waitlist_entry o WHERE o.section_id = w.section_id "
        "  AND o.status = 'WAITING' AND o.id <= w.id) "
        "FROM waitlist_entry w WHERE w.student_id = $1 AND w.status = 'WAITING' "
        "AND ($2::bigint[] IS NULL OR w.section_id = ANY($2::bigint[]))",
        student_id, None if section_ids is None else list(section_ids))
    return {sid: pos for sid, pos in rows}
