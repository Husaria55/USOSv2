"""AllocationService: przydział miejsc w turze PREFERENCES (UC30, UC31, UC33).

- run_allocation(kind=PREVIEW) - symulacja w trakcie tury (worker co kilka minut albo
  dziekanat na żądanie): wynik trafia tylko do allocation_run / allocation_result, student
  widzi przewidywany przydział i może zmienić wagi. Bez blokad - to podgląd.
- run_allocation(kind=FINAL) - po zamknięciu tury: przydział zapisywany jako zapisy
  (enrollment.source = 'ALLOCATION'), jednorazowo (indeks allocation_one_final).

Przydział końcowy, jak każda decyzja o miejscach, zapada w jednej transakcji pod blokadami:
tura (FOR UPDATE) -> studenci zgłoszeń (FOR UPDATE, kolejność id) -> grupy (FOR UPDATE,
kolejność id). Kolejność student -> grupa jest ta sama co przy zwykłym zapisie, więc
równoległe zapisy innych kierunków do tych samych grup tylko poczekają (bez zakleszczeń),
a przydział widzi stan, który nie zmieni się przed zatwierdzeniem: wolne miejsca, plany,
zaliczenia i harmonogram.
"""
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.allocation import (
    AllocationResult, CourseRequest, Offer, StudentProfile, allocate, verify,
)
from app.domain.rounds import RoundMode
from app.errors import Conflict
from app.services import loaders
from app.services.enrollment import cancel_same_kind
from app.services.loaders import pg
from app.services.notifications import notify_many, payload

PREVIEW, FINAL = "PREVIEW", "FINAL"


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    kind: str
    seed: int
    students: int
    requests: int
    assigned: int
    total_utility: float
    upper_bound: float
    improvements: int
    seconds: float


async def _requests(session: AsyncSession, round_id: int) -> list[CourseRequest]:
    """Zgłoszenia wszystkich studentów tury (jedno zapytanie)."""
    rows = await (await pg(session)).fetch(
        "SELECT cp.student_id, cp.course_id, c.code, cp.weight, s.kind, sp.section_id "
        "FROM course_preference cp JOIN course c ON c.id = cp.course_id "
        "JOIN section_preference sp ON (sp.round_id, sp.student_id, sp.course_id) "
        "     = (cp.round_id, cp.student_id, cp.course_id) "
        "JOIN section s ON s.id = sp.section_id "
        "WHERE cp.round_id = $1 ORDER BY cp.student_id, cp.course_id, s.kind, sp.rank", round_id)
    heads: dict[tuple[int, int], tuple[str, int]] = {}
    choices: dict[tuple[int, int], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for student, course, code, weight, kind, sid in rows:
        heads[(student, course)] = (code, weight)
        choices[(student, course)][kind].append(sid)
    return [CourseRequest(st, c, code, w, {k: tuple(v) for k, v in choices[(st, c)].items()})
            for (st, c), (code, w) in heads.items()]


async def run_allocation(session: AsyncSession, round_id: int, kind: str, *, seed: int | None = None) -> RunSummary:
    """UC30 (FINAL) / UC31 (PREVIEW). Błędy: NOT_PREFERENCE_ROUND, ROUND_NOT_CLOSED, ALREADY_ALLOCATED."""
    round_, term_id = await loaders.round_info(session, round_id, lock="UPDATE" if kind == FINAL else None)
    if round_.mode is not RoundMode.PREFERENCES:
        raise Conflict("NOT_PREFERENCE_ROUND", "To nie jest tura preferencyjna.")
    db = await pg(session)
    if await db.fetchval("SELECT 1 FROM allocation_run WHERE round_id = $1 AND kind = 'FINAL'", round_id):
        raise Conflict("ALREADY_ALLOCATED", "Przydział dla tej tury został już wykonany.")
    if kind == FINAL and round_.status != "CLOSED":
        raise Conflict("ROUND_NOT_CLOSED", "Przydział końcowy można wykonać dopiero po zamknięciu tury.")

    requests = await _requests(session, round_id)
    students = sorted({r.student_id for r in requests})
    section_ids = sorted({sid for r in requests for group in r.choices.values() for sid in group})
    if kind == FINAL:
        await loaders.lock_students(session, students)
        await loaders.lock_sections(session, section_ids)
    targets = await loaders.load_targets(session, section_ids)          # bez cache: aktualny harmonogram
    seats = dict(await db.fetch(
        "SELECT id, capacity - enrolled_count FROM section WHERE id = ANY($1::bigint[])", section_ids))
    offers = {sid: Offer(sid, t.course_id, t.kind, t.label, t.slots, seats[sid]) for sid, (t, _) in targets.items()}
    prereqs = {t.course_id: t.prerequisites for t, _ in targets.values()}
    plans = await loaders.plans(session, students, term_id)
    passed = await loaders.passed_by_student(session, students)
    profiles = {st: StudentProfile(st, plans[st], passed[st]) for st in students}

    seed = seed if seed is not None else secrets.randbits(62)
    started = time.perf_counter()
    result = allocate(requests, profiles, offers, prereqs, seed=seed)
    seconds = time.perf_counter() - started
    problems = verify(result, requests, profiles, offers, prereqs)
    if problems:                                   # błąd w algorytmie - nic nie zapisujemy
        raise RuntimeError("Przydział narusza ograniczenia: " + "; ".join(problems[:5]))

    run_id = await _store(session, round_id, kind, result, len(students))
    if kind == PREVIEW:
        await db.execute("DELETE FROM allocation_run WHERE round_id = $1 AND kind = 'PREVIEW' AND id < $2",
                         round_id, run_id)
    else:
        await _apply(session, result, {sid: t for sid, (t, _) in targets.items()}, term_id, round_id)
    return RunSummary(run_id, kind, seed, len(students), result.requests, len(result.assignments),
                      result.total_utility, result.upper_bound, result.improvements, round(seconds, 3))


async def _store(session: AsyncSession, round_id: int, kind: str, result: AllocationResult, students: int) -> int:
    db = await pg(session)
    run_id = await db.fetchval(
        "INSERT INTO allocation_run (round_id, kind, seed, students, requests, assigned, total_utility, upper_bound) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
        round_id, kind, result.seed, students, result.requests, len(result.assignments),
        round(result.total_utility, 2), round(result.upper_bound, 2))
    await db.executemany(
        "INSERT INTO allocation_result (run_id, student_id, course_id, weight, status, utility, reason) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        [(run_id, a.student_id, a.course_id, a.weight, "ASSIGNED", round(a.utility, 2), None)
         for a in result.assignments]
        + [(run_id, u.student_id, u.course_id, u.weight, "UNASSIGNED", 0, u.reason.message[:255])
           for u in result.unassigned])
    await db.executemany(
        "INSERT INTO allocation_assignment (run_id, student_id, course_id, section_id) VALUES ($1, $2, $3, $4)",
        [(run_id, a.student_id, a.course_id, sid) for a in result.assignments for sid in a.section_ids])
    return run_id


async def _apply(session: AsyncSession, result: AllocationResult, targets: dict, term_id: int, round_id: int) -> None:
    """Przydział końcowy -> zapisy, liczniki grup, anulowanie list tego samego typu, powiadomienia."""
    db = await pg(session)
    rows = [(a.student_id, sid) for a in result.assignments for sid in a.section_ids]
    await db.executemany(
        "INSERT INTO enrollment (student_id, section_id, status, source) VALUES ($1, $2, 'ENROLLED', 'ALLOCATION')",
        rows)
    per_section: dict[int, int] = defaultdict(int)
    for _, sid in rows:
        per_section[sid] += 1
    # CHECK (enrolled_count <= capacity) odrzuci całą transakcję, gdyby przydział przekroczył limit
    await db.executemany("UPDATE section SET enrolled_count = enrolled_count + $2 WHERE id = $1",
                         sorted(per_section.items()))

    waiting = await loaders.waiting_by_student(session, {st for st, _ in rows}, term_id)
    for st, sid in rows:
        if waiting[st]:
            await cancel_same_kind(session, st, waiting[st], targets[sid])

    name = await db.fetchval("SELECT name FROM enrollment_round WHERE id = $1", round_id)
    groups: dict[int, list[str]] = defaultdict(list)
    for st, sid in rows:
        groups[st].append(targets[sid].label)
    codes = dict(await db.fetch("SELECT id, code FROM course WHERE id = ANY($1::bigint[])",
                                list({u.course_id for u in result.unassigned})))
    missing: dict[int, list[str]] = defaultdict(list)
    for u in result.unassigned:
        missing[u.student_id].append(codes[u.course_id])
    notes = [(st, "ALLOCATED", payload("ALLOCATED", name, groups=", ".join(g))) for st, g in groups.items()]
    notes += [(st, "NOT_ALLOCATED", payload("NOT_ALLOCATED", name, courses=", ".join(sorted(c))))
              for st, c in missing.items()]
    await notify_many(session, notes)


async def rounds_to_allocate(session: AsyncSession) -> list[int]:
    """Zamknięte tury preferencyjne bez przydziału końcowego (worker, UC30)."""
    rows = await (await pg(session)).fetch(
        "SELECT r.id FROM enrollment_round r WHERE r.mode = 'PREFERENCES' AND r.status = 'CLOSED' "
        "AND NOT EXISTS (SELECT 1 FROM allocation_run a WHERE a.round_id = r.id AND a.kind = 'FINAL') ORDER BY r.id")
    return [r[0] for r in rows]


async def rounds_to_preview(session: AsyncSession) -> list[int]:
    rows = await (await pg(session)).fetch(
        "SELECT id FROM enrollment_round WHERE mode = 'PREFERENCES' AND status = 'OPEN' ORDER BY id")
    return [r[0] for r in rows]


# --- odczyty -------------------------------------------------------------------------------

async def _latest_run(session: AsyncSession, round_id: int):
    """Przydział końcowy, a jeśli go nie ma - najnowsza symulacja."""
    return await (await pg(session)).fetchrow(
        "SELECT id, kind, created_at, seed, students, requests, assigned, total_utility, upper_bound "
        "FROM allocation_run WHERE round_id = $1 ORDER BY (kind = 'FINAL') DESC, id DESC LIMIT 1", round_id)


async def student_view(session: AsyncSession, student_id: int, round_id: int) -> dict:
    """UC29: (przewidywany) przydział studenta z powodami odmów."""
    run = await _latest_run(session, round_id)
    if run is None:
        return {"run": None, "results": []}
    db = await pg(session)
    rows = await db.fetch(
        "SELECT r.course_id, c.code, c.name, r.weight, r.status, r.utility, r.reason "
        "FROM allocation_result r JOIN course c ON c.id = r.course_id "
        "WHERE r.run_id = $1 AND r.student_id = $2 ORDER BY r.weight DESC, c.code", run[0], student_id)
    groups: dict[int, list[str]] = defaultdict(list)
    for cid, label in await db.fetch(
            "SELECT a.course_id, c.code || ' ' || s.code FROM allocation_assignment a "
            "JOIN section s ON s.id = a.section_id JOIN course c ON c.id = s.course_id "
            "WHERE a.run_id = $1 AND a.student_id = $2 ORDER BY s.kind", run[0], student_id):
        groups[cid].append(label)
    return {
        "run": {"id": run[0], "kind": run[1], "created_at": run[2]},
        "results": [{"course_id": cid, "code": code, "name": name, "weight": w, "status": st,
                     "utility": float(u), "reason": reason, "sections": groups[cid]}
                    for cid, code, name, w, st, u, reason in rows],
    }


async def summary(session: AsyncSession, round_id: int) -> dict:
    """UC33: raport dla dziekanatu - jakość przydziału i popyt na przedmioty."""
    run = await _latest_run(session, round_id)
    db = await pg(session)
    # wolne miejsca przedmiotu = najmniejsza suma po typach zajęć (np. 3 laby po 15 przy wykładzie na 150 -> 45)
    demand = await db.fetch(
        "SELECT c.id, c.code, count(*), sum(cp.weight), "
        "  (SELECT min(k.free) FROM (SELECT sum(s.capacity - s.enrolled_count) AS free FROM section s "
        "    WHERE s.term_id = r.term_id AND s.course_id = c.id GROUP BY s.kind) k) "
        "FROM course_preference cp JOIN course c ON c.id = cp.course_id "
        "JOIN enrollment_round r ON r.id = cp.round_id WHERE cp.round_id = $1 "
        "GROUP BY c.id, r.term_id ORDER BY sum(cp.weight) DESC", round_id)
    assigned = {}
    if run is not None:
        assigned = dict(await db.fetch(
            "SELECT course_id, count(*) FROM allocation_result WHERE run_id = $1 AND status = 'ASSIGNED' "
            "GROUP BY course_id", run[0]))
    return {
        "run": None if run is None else {
            "id": run[0], "kind": run[1], "created_at": run[2], "seed": run[3], "students": run[4],
            "requests": run[5], "assigned": run[6], "total_utility": float(run[7]), "upper_bound": float(run[8]),
            "quality": round(float(run[7]) / float(run[8]), 4) if run[8] else None},
        "courses": [{"course_id": cid, "code": code, "requests": n, "weight_sum": int(w),
                     "free_seats": int(free or 0), "assigned": assigned.get(cid, 0)}
                    for cid, code, n, w, free in demand],
    }
