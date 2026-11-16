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
from app.domain.rounds import RoundInfo, RoundMode, student_can_enroll
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
    schedule_version: int = 0


async def lock_student(session: AsyncSession, student_id: int, *, nowait: bool = False) -> LockedStudent:
    """Blokada wiersza studenta (zawsze przed blokadą grupy, poza awansem z listy)."""
    row = await (await pg(session)).fetchrow(
        "SELECT id, program_id FROM app_user WHERE id = $1 AND role = 'STUDENT' FOR UPDATE"
        + (" NOWAIT" if nowait else ""), student_id)
    if row is None:
        raise NotFound("STUDENT_NOT_FOUND", "Nie ma takiego studenta.")
    return LockedStudent(row[0], row[1])


async def lock_students(session: AsyncSession, student_ids, *, nowait: bool = False) -> list[int]:
    """Blokada wielu studentów naraz, w kolejności id (stała kolejność - bez zakleszczeń między nimi)."""
    ids = sorted(set(student_ids))
    if not ids:
        return []
    rows = await (await pg(session)).fetch(
        "SELECT id FROM app_user WHERE id = ANY($1::bigint[]) AND role = 'STUDENT' ORDER BY id FOR UPDATE"
        + (" NOWAIT" if nowait else ""), ids)
    return [r[0] for r in rows]


async def lock_section(session: AsyncSession, section_id: int) -> LockedSection:
    row = await (await pg(session)).fetchrow(
        "SELECT id, capacity, enrolled_count, waitlist_limit, schedule_version FROM section WHERE id = $1 FOR UPDATE",
        section_id)
    if row is None:
        raise NotFound("SECTION_NOT_FOUND", "Nie ma takiej grupy.")
    return LockedSection(*row)


async def lock_sections(session: AsyncSession, section_ids) -> dict[int, LockedSection]:
    """Blokada wielu grup w kolejności id (przydział preferencyjny po zamknięciu tury)."""
    ids = sorted(set(section_ids))
    if not ids:
        return {}
    rows = await (await pg(session)).fetch(
        "SELECT id, capacity, enrolled_count, waitlist_limit, schedule_version FROM section "
        "WHERE id = ANY($1::bigint[]) ORDER BY id FOR UPDATE", ids)
    return {r[0]: LockedSection(*r) for r in rows}


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
        "SELECT s.id, s.course_id, c.code, s.code, s.kind, s.term_id, s.schedule_version FROM section s "
        "JOIN course c ON c.id = s.course_id WHERE s.id = ANY($1::bigint[])", ids)
    prereqs: dict[int, dict[int, str]] = defaultdict(dict)
    for course_id, req_id, req_code in await db.fetch(
            "SELECT p.course_id, c.id, c.code FROM course_prerequisite p "
            "JOIN course c ON c.id = p.required_course_id WHERE p.course_id = ANY($1::bigint[])",
            list({r[1] for r in rows})):
        prereqs[course_id][req_id] = req_code
    slots = await slots_by_section(session, [r[0] for r in rows])
    return {sid: (TargetSection(sid, cid, ccode, code, kind, slots[sid], prereqs.get(cid, {}), version), term_id)
            for sid, cid, ccode, code, kind, term_id, version in rows}


# Dane katalogowe grupy (kurs, typ, terminy, wymagania) prawie nie zmieniają się w trakcie
# tury, a są potrzebne przy każdym zapisie. Trzymamy je krótko w pamięci procesu; zmiany
# dziekanatu w tym procesie czyszczą cache od razu, w pozostałych po TARGET_TTL_S.
# Nieaktualne terminy nie prowadzą jednak do kolizji: zapis porównuje wersję harmonogramu
# z cache z section.schedule_version pod blokadą grupy i przy różnicy sprawdza ponownie
# (EnrollmentService._current_target).
TARGET_TTL_S = 10.0
_targets: dict[int, tuple[float, tuple[TargetSection, int]]] = {}


def forget_targets() -> None:
    _targets.clear()


async def load_target(session: AsyncSession, section_id: int, *,
                      fresh: bool = False) -> tuple[TargetSection, int]:
    """Dane katalogowe grupy; fresh=True pomija cache (np. gdy wersja harmonogramu się zmieniła)."""
    now = time.monotonic()
    hit = _targets.get(section_id)
    if hit and hit[0] > now and not fresh:
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


_ROUNDS_SQL = (
    "SELECT r.id, r.status, r.opens_at, r.closes_at, array_remove(array_agg(rp.program_id), NULL), "
    "r.mode, r.points_budget, r.term_id "
    "FROM enrollment_round r LEFT JOIN round_program rp ON rp.round_id = r.id ")


def _round(row) -> RoundInfo:
    rid, st, a, b, progs, mode, budget, _ = row
    return RoundInfo(rid, st, a, b, frozenset(progs), RoundMode(mode), budget)


async def term_rounds(session: AsyncSession, term_id: int, *, only_open: bool = False) -> list[RoundInfo]:
    rows = await (await pg(session)).fetch(
        _ROUNDS_SQL + "WHERE r.term_id = $1 AND ($2 = false OR r.status = 'OPEN') GROUP BY r.id", term_id, only_open)
    return [_round(r) for r in rows]


async def round_info(session: AsyncSession, round_id: int, *, lock: str | None = None) -> tuple[RoundInfo, int]:
    """Tura i jej semestr. lock: None | "SHARE" | "UPDATE" (blokada wiersza tury przed odczytem)."""
    db = await pg(session)
    if lock:
        await db.execute(f"SELECT 1 FROM enrollment_round WHERE id = $1 FOR {'SHARE' if lock == 'SHARE' else 'UPDATE'}",
                         round_id)
    row = await db.fetchrow(_ROUNDS_SQL + "WHERE r.id = $1 GROUP BY r.id", round_id)
    if row is None:
        raise NotFound("ROUND_NOT_FOUND", "Nie ma takiej tury.")
    return _round(row), row[7]


async def plans(session: AsyncSession, student_ids, term_id: int) -> dict[int, tuple[PlanEntry, ...]]:
    """Plany wielu studentów w semestrze (grupy ENROLLED z terminami) jednym zapytaniem."""
    ids = list(set(student_ids))
    rows = await (await pg(session)).fetch(
        "SELECT e.student_id, s.id, s.code, c.code, s.course_id, s.kind, "
        "       m.weekday, m.start_time, m.end_time, m.week_parity "
        "FROM enrollment e JOIN section s ON s.id = e.section_id JOIN course c ON c.id = s.course_id "
        "LEFT JOIN meeting m ON m.section_id = s.id "
        "WHERE e.student_id = ANY($1::bigint[]) AND e.status = 'ENROLLED' AND s.term_id = $2", ids, term_id)
    sections: dict[int, dict[int, tuple]] = defaultdict(dict)
    slots: dict[int, list[Slot]] = defaultdict(list)
    for st_id, sid, code, ccode, cid, kind, wd, st, en, par in rows:
        sections[st_id][sid] = (code, ccode, cid, kind)
        if wd is not None:
            slots[sid].append(Slot(wd, st, en, par))
    return {st_id: tuple(PlanEntry(sid, code, ccode, tuple(slots[sid]), cid, kind)
                         for sid, (code, ccode, cid, kind) in sections[st_id].items())
            for st_id in ids}


async def student_plan(session: AsyncSession, student_id: int, term_id: int) -> tuple[PlanEntry, ...]:
    return (await plans(session, [student_id], term_id))[student_id]


async def enrolled_students(session: AsyncSession, section_id: int) -> list[int]:
    rows = await (await pg(session)).fetch(
        "SELECT student_id FROM enrollment WHERE section_id = $1 AND status = 'ENROLLED' ORDER BY student_id",
        section_id)
    return [r[0] for r in rows]


async def waiting_students(session: AsyncSession, section_id: int) -> list[int]:
    rows = await (await pg(session)).fetch(
        "SELECT student_id FROM waitlist_entry WHERE section_id = $1 AND status = 'WAITING' ORDER BY id", section_id)
    return [r[0] for r in rows]


async def student_waiting(session: AsyncSession, student_id: int, term_id: int) -> list[WaitingEntry]:
    return (await waiting_by_student(session, [student_id], term_id))[student_id]


async def waiting_by_student(session: AsyncSession, student_ids, term_id: int) -> dict[int, list[WaitingEntry]]:
    ids = list(set(student_ids))
    rows = await (await pg(session)).fetch(
        "SELECT w.student_id, w.id, s.id, s.course_id, s.kind FROM waitlist_entry w "
        "JOIN section s ON s.id = w.section_id "
        "WHERE w.student_id = ANY($1::bigint[]) AND w.status = 'WAITING' AND s.term_id = $2", ids, term_id)
    out: dict[int, list[WaitingEntry]] = {st: [] for st in ids}
    for st, *entry in rows:
        out[st].append(WaitingEntry(*entry))
    return out


async def passed_courses(session: AsyncSession, student_id: int) -> frozenset[int]:
    return (await passed_by_student(session, [student_id]))[student_id]


async def passed_by_student(session: AsyncSession, student_ids) -> dict[int, frozenset[int]]:
    ids = list(set(student_ids))
    rows = await (await pg(session)).fetch(
        "SELECT DISTINCT student_id, course_id FROM completed_course WHERE student_id = ANY($1::bigint[]) AND passed",
        ids)
    out: dict[int, set[int]] = defaultdict(set)
    for st, c in rows:
        out[st].add(c)
    return {st: frozenset(out[st]) for st in ids}


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
