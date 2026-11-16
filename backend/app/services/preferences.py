"""PreferenceService: zgłaszanie i zmiana preferencji w turze PREFERENCES (UC28, UC29).

Student w trakcie otwartej tury może dowolnie często zastąpić swoje zgłoszenie nowym
(wagi przedmiotów + grupy w kolejności). Zapis jest atomowy: całe zgłoszenie albo nic.

Blokady: tura (FOR SHARE) -> student (FOR UPDATE).
- FOR SHARE na turze szereguje zapis preferencji z zamknięciem tury (FOR UPDATE): albo
  zgłoszenie zapisze się przed zamknięciem i wejdzie do przydziału, albo po zamknięciu
  zostanie odrzucone (ROUND_CLOSED). Nie ma zgłoszeń "zgubionych" w trakcie zamykania.
- blokada studenta szereguje równoległe zapisy z kilku kart przeglądarki
  (ostatni wygrywa, suma wag zawsze w budżecie).
Kolejność tura -> student jest taka sama jak w przydziale końcowym (AllocationService).
"""
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.allocation import (
    CourseRequest, Offer, PreferenceInput, Rejection, SectionInfo, StudentProfile, choices_by_kind, options_for,
    validate_preferences,
)
from app.domain.rounds import RoundMode, can_submit_preferences
from app.errors import Conflict
from app.services import loaders
from app.services.loaders import pg


@dataclass
class SaveResult:
    used_points: int
    budget: int
    warnings: list[dict] = field(default_factory=list)   # {course_id, code, message}: zgłoszenie przyjęte, ale...


async def section_infos(session: AsyncSession, section_ids) -> dict[int, SectionInfo]:
    rows = await (await pg(session)).fetch(
        "SELECT id, course_id, kind, term_id FROM section WHERE id = ANY($1::bigint[])", list(set(section_ids)))
    return {r[0]: SectionInfo(*r) for r in rows}


async def save_preferences(session: AsyncSession, student_id: int, round_id: int,
                           items: list[PreferenceInput]) -> SaveResult:
    """UC28: zastępuje zgłoszenie studenta w turze. Zwraca wykorzystane punkty i ostrzeżenia.

    Błędy (409): NOT_PREFERENCE_ROUND, ROUND_CLOSED, BUDGET_EXCEEDED, BAD_WEIGHT, BAD_SECTION,
    DUPLICATE_COURSE, DUPLICATE_SECTION, NO_SECTIONS, TOO_MANY_COURSES, TOO_MANY_SECTIONS.
    """
    round_, term_id = await loaders.round_info(session, round_id, lock="SHARE")      # 1. tura
    student = await loaders.lock_student(session, student_id)                         # 2. student
    if round_.mode is not RoundMode.PREFERENCES:
        raise Conflict("NOT_PREFERENCE_ROUND", "W tej turze zapisy są w kolejności zgłoszeń - preferencji się nie składa.")
    if not can_submit_preferences(round_, student.program_id):
        raise Conflict("ROUND_CLOSED", "Tura preferencyjna dla Twojego kierunku nie jest teraz otwarta.")

    infos = await section_infos(session, [sid for i in items for sid in i.section_ids])
    errors = validate_preferences(items, round_.points_budget, term_id, infos)
    if errors:
        e = errors[0]
        raise Conflict(e.code, e.message, e.details)

    db = await pg(session)
    await db.execute("DELETE FROM course_preference WHERE round_id = $1 AND student_id = $2", round_id, student_id)
    if items:
        await db.executemany(
            "INSERT INTO course_preference (round_id, student_id, course_id, weight) VALUES ($1, $2, $3, $4)",
            [(round_id, student_id, i.course_id, i.weight) for i in items])
        await db.executemany(
            "INSERT INTO section_preference (round_id, student_id, course_id, section_id, rank) "
            "VALUES ($1, $2, $3, $4, $5)",
            [(round_id, student_id, i.course_id, sid, rank)
             for i in items for sids in choices_by_kind(i.section_ids, infos).values()
             for rank, sid in enumerate(sids, start=1)])
    return SaveResult(sum(i.weight for i in items), round_.points_budget,
                      await _warnings(session, student.id, term_id, items, infos))


async def _warnings(session: AsyncSession, student_id: int, term_id: int, items: list[PreferenceInput],
                    infos: dict[int, SectionInfo]) -> list[dict]:
    """Problemy widoczne już teraz (wymagania, kolizje z planem, pełne grupy) - te same reguły co przydział.

    To tylko podpowiedź: przydział sprawdzi wszystko ponownie na stanie z chwili zamknięcia tury
    (np. ocena może zostać zaimportowana później).
    """
    if not items:
        return []
    targets = await loaders.load_targets(session, list(infos))
    seats = dict(await (await pg(session)).fetch(
        "SELECT id, capacity - enrolled_count FROM section WHERE id = ANY($1::bigint[])", list(infos)))
    offers = {sid: Offer(sid, t.course_id, t.kind, t.label, t.slots, seats[sid]) for sid, (t, _) in targets.items()}
    profile = StudentProfile(student_id, await loaders.student_plan(session, student_id, term_id),
                             await loaders.passed_courses(session, student_id))
    codes = dict(await (await pg(session)).fetch(
        "SELECT id, code FROM course WHERE id = ANY($1::bigint[])", [i.course_id for i in items]))
    prereqs = {t.course_id: t.prerequisites for t, _ in targets.values()}
    out = []
    for item in items:
        request = CourseRequest(student_id, item.course_id, codes.get(item.course_id, "?"), item.weight,
                                choices_by_kind(item.section_ids, infos))
        got = options_for(request, profile, offers, prereqs.get(item.course_id, {}))
        if isinstance(got, Rejection):
            out.append({"course_id": item.course_id, "code": got.code, "message": got.message})
        elif all(any(offers[sid].free_seats <= 0 for sid in opt.section_ids) for opt in got):
            out.append({"course_id": item.course_id, "code": "FULL",
                        "message": f"{request.course_code}: wszystkie wybrane grupy są już pełne."})
    return out


async def get_preferences(session: AsyncSession, student_id: int, round_id: int) -> dict:
    """UC28 (odczyt): bieżące zgłoszenie studenta z kolejnością grup."""
    round_, _ = await loaders.round_info(session, round_id)
    rows = await (await pg(session)).fetch(
        "SELECT cp.course_id, c.code, c.name, cp.weight, cp.updated_at, sp.section_id, s.code, s.kind, sp.rank "
        "FROM course_preference cp JOIN course c ON c.id = cp.course_id "
        "LEFT JOIN section_preference sp ON (sp.round_id, sp.student_id, sp.course_id) "
        "     = (cp.round_id, cp.student_id, cp.course_id) "
        "LEFT JOIN section s ON s.id = sp.section_id "
        "WHERE cp.round_id = $1 AND cp.student_id = $2 ORDER BY cp.weight DESC, c.code, s.kind, sp.rank",
        round_id, student_id)
    courses: dict[int, dict] = {}
    for cid, ccode, cname, weight, updated, sid, scode, kind, rank in rows:
        c = courses.setdefault(cid, {"course_id": cid, "code": ccode, "name": cname, "weight": weight,
                                     "updated_at": updated, "sections": []})
        if sid is not None:
            c["sections"].append({"section_id": sid, "code": scode, "kind": kind, "rank": rank})
    return {"round_id": round_id, "status": round_.status, "mode": round_.mode.value,
            "budget": round_.points_budget, "used": sum(c["weight"] for c in courses.values()),
            "courses": list(courses.values())}
