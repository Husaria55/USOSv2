"""Dziekanat: katalog, harmonogram, tury, użytkownicy, decyzje o zapisach, import ocen, audyt."""
from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api import schemas as sc
from app.api.deps import CurrentUser, admin, catalog_cache, session
from app.db import run_transaction
from app.domain.enrollment_rules import Mode
from app.services import audit, catalog, enrollment, loaders, queries, records, rounds, users

router = APIRouter(prefix="/api/admin")


async def tx(fn):
    """Transakcja zmieniająca katalog; po niej odświeżamy cache odczytów."""
    result = await run_transaction(fn)
    catalog_cache.clear()
    loaders.forget_targets()
    return result


# --- słowniki ---------------------------------------------------------------

@router.post("/programs")
async def create_program(body: sc.NewProgram, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: catalog.create_program(s, body.code, body.name))}


@router.get("/rooms")
async def list_rooms(_: CurrentUser = Depends(admin), db=Depends(session)):
    return await queries.rooms(db)


@router.post("/rooms")
async def create_room(body: sc.NewRoom, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: catalog.create_room(s, body.building, body.number, body.seats))}


@router.post("/terms")
async def create_term(body: sc.NewTerm, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: catalog.create_term(s, body.code, body.starts_on, body.ends_on))}


# --- kursy (UC11) -----------------------------------------------------------

@router.get("/courses")
async def list_courses(q: str | None = None, limit: int = 50, offset: int = 0,
                       _: CurrentUser = Depends(admin), db=Depends(session)):
    return await queries.course_list(db, None, q, min(limit, 200), offset)


@router.get("/courses/{course_id}")
async def course_detail(course_id: int, term_id: int | None = None, _: CurrentUser = Depends(admin),
                        db=Depends(session)):
    return await queries.course_detail(db, course_id, term_id)


@router.post("/courses")
async def create_course(body: sc.NewCourse, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: catalog.create_course(s, body.code, body.name, body.ects, body.description))}


@router.patch("/courses/{course_id}")
async def update_course(course_id: int, body: sc.CourseUpdate, _: CurrentUser = Depends(admin)):
    await tx(lambda s: catalog.update_course(s, course_id, **body.model_dump()))
    return {"status": "OK"}


@router.post("/courses/{course_id}/prerequisites")
async def add_prerequisite(course_id: int, body: sc.Prerequisite, _: CurrentUser = Depends(admin)):
    await tx(lambda s: catalog.add_prerequisite(s, course_id, body.required_course_id))
    return {"status": "OK"}


@router.delete("/courses/{course_id}/prerequisites/{required_id}")
async def remove_prerequisite(course_id: int, required_id: int, _: CurrentUser = Depends(admin)):
    await tx(lambda s: catalog.remove_prerequisite(s, course_id, required_id))
    return {"status": "OK"}


# --- grupy i harmonogram (UC12, UC13) ---------------------------------------

@router.post("/sections")
async def create_section(body: sc.NewSection, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: catalog.create_section(
        s, body.course_id, body.term_id, body.code, body.kind, body.capacity, body.waitlist_limit))}


@router.patch("/sections/{section_id}")
async def change_limits(section_id: int, body: sc.SectionLimits, _: CurrentUser = Depends(admin)):
    """UC13: zmiana limitu; wolne miejsca od razu idą do oczekujących (UC9)."""
    events = await tx(lambda s: enrollment.change_limits(
        s, section_id, capacity=body.capacity, waitlist_limit=body.waitlist_limit))
    return {"promotions": [asdict(e) for e in events]}


@router.post("/sections/{section_id}/meetings")
async def add_meeting(section_id: int, body: sc.NewMeeting, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: catalog.add_meeting(
        s, section_id, body.weekday, body.start, body.end, body.parity, body.room_id))}


@router.delete("/meetings/{meeting_id}")
async def remove_meeting(meeting_id: int, _: CurrentUser = Depends(admin)):
    await tx(lambda s: catalog.remove_meeting(s, meeting_id))
    return {"status": "OK"}


@router.post("/sections/{section_id}/lecturers")
async def assign_lecturer(section_id: int, body: sc.LecturerRef, _: CurrentUser = Depends(admin)):
    await tx(lambda s: catalog.assign_lecturer(s, section_id, body.lecturer_id))
    return {"status": "OK"}


@router.delete("/sections/{section_id}/lecturers/{lecturer_id}")
async def remove_lecturer(section_id: int, lecturer_id: int, _: CurrentUser = Depends(admin)):
    await tx(lambda s: catalog.remove_lecturer(s, section_id, lecturer_id))
    return {"status": "OK"}


# --- decyzje dziekanatu (UC14) ----------------------------------------------

@router.post("/enrollments")
async def admin_enroll(body: sc.AdminEnroll, user: CurrentUser = Depends(admin)):
    result = await tx(lambda s: enrollment.enroll(s, body.student_id, body.section_id, mode=Mode.ADMIN,
                                                  actor_id=user.id))
    return asdict(result)


@router.delete("/enrollments/{student_id}/{section_id}")
async def admin_drop(student_id: int, section_id: int, user: CurrentUser = Depends(admin)):
    events = await tx(lambda s: enrollment.drop(s, student_id, section_id, mode=Mode.ADMIN, actor_id=user.id))
    return {"promotions": [asdict(e) for e in events]}


@router.get("/students/{student_id}/terms/{term_id}/plan")
async def student_plan(student_id: int, term_id: int, _: CurrentUser = Depends(admin), db=Depends(session)):
    return await queries.student_plan(db, student_id, term_id)


# --- tury (UC16) --------------------------------------------------------------

@router.get("/terms/{term_id}/rounds")
async def list_rounds(term_id: int, _: CurrentUser = Depends(admin), db=Depends(session)):
    return await queries.all_rounds(db, term_id)


@router.post("/rounds")
async def create_round(body: sc.NewRound, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: rounds.create_round(
        s, body.term_id, body.name, body.opens_at, body.closes_at, body.program_ids))}


@router.patch("/rounds/{round_id}")
async def update_round(round_id: int, body: sc.RoundUpdate, _: CurrentUser = Depends(admin)):
    await tx(lambda s: rounds.update_round(s, round_id, opens_at=body.opens_at, closes_at=body.closes_at,
                                           program_ids=body.program_ids))
    return {"status": "OK"}


@router.post("/rounds/{round_id}/open")
async def open_round(round_id: int, _: CurrentUser = Depends(admin)):
    await tx(lambda s: rounds.open_round(s, round_id))
    return {"status": "OPEN"}


@router.post("/rounds/{round_id}/close")
async def close_round(round_id: int, _: CurrentUser = Depends(admin)):
    expired = await tx(lambda s: rounds.close_round(s, round_id))
    return {"status": "CLOSED", "expired_waitlist_entries": expired}


# --- użytkownicy i oceny (UC15) ---------------------------------------------

@router.get("/users")
async def search_users(q: str | None = None, role: str | None = None, _: CurrentUser = Depends(admin),
                       db=Depends(session)):
    return [queries.user_dict(u) for u in await users.search(db, q, role)]


@router.post("/users")
async def create_user(body: sc.NewUser, _: CurrentUser = Depends(admin)):
    return {"id": await tx(lambda s: users.create_user(s, **body.model_dump()))}


@router.post("/grades/import")
async def import_grades(body: sc.GradesImport, _: CurrentUser = Depends(admin)):
    return asdict(await tx(lambda s: records.import_grades(s, body.csv)))


@router.get("/audit")
async def run_audit(_: CurrentUser = Depends(admin), db=Depends(session)):
    return [asdict(v) for v in await audit.violations(db)]
