"""Student: katalog, zapisy, plan, listy oczekujących, powiadomienia."""
from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, update

from app.api.deps import CurrentUser, catalog_cache, current_user, read_gate, session, student, write_slot
from app.api.schemas import PreferencesIn, SectionRef
from app.db import run_transaction
from app.domain.allocation import PreferenceInput
from app.models import Notification, User
from app.services import allocation, enrollment, preferences, queries

router = APIRouter(prefix="/api")


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user), db=Depends(session)):
    u = await db.get(User, user.id)
    return queries.user_dict(u)


@router.get("/terms")
async def terms(_: CurrentUser = Depends(current_user), db=Depends(session)):
    return await catalog_cache.get("terms", lambda: queries.terms(db))


@router.get("/programs")
async def programs(_: CurrentUser = Depends(current_user), db=Depends(session)):
    return await catalog_cache.get("programs", lambda: queries.programs(db))


@router.get("/terms/{term_id}/courses")
async def courses(term_id: int, q: str | None = None, limit: int = 50, offset: int = 0,
                  _: CurrentUser = Depends(current_user), db=Depends(session)):
    limit = min(limit, 200)
    return await catalog_cache.get(("courses", term_id, q, limit, offset),
                                   lambda: queries.course_list(db, term_id, q, limit, offset))


@router.get("/terms/{term_id}/courses/{course_id}")
async def course(term_id: int, course_id: int, _: CurrentUser = Depends(current_user), db=Depends(session)):
    return await catalog_cache.get(("course", term_id, course_id),
                                   lambda: queries.course_detail(db, course_id, term_id))


@router.get("/me/terms/{term_id}/courses/{course_id}")
async def course_status(term_id: int, course_id: int, user: CurrentUser = Depends(student), db=Depends(session)):
    async with read_gate.slot():
        return await queries.student_course_status(db, user.id, course_id, term_id)


@router.get("/me/terms/{term_id}/plan")
async def plan(term_id: int, user: CurrentUser = Depends(student), db=Depends(session)):
    return await queries.student_plan(db, user.id, term_id)


@router.get("/me/terms/{term_id}/waitlist")
async def waitlist(term_id: int, user: CurrentUser = Depends(student), db=Depends(session)):
    return await queries.student_waitlist(db, user.id, term_id)


@router.get("/me/terms/{term_id}/rounds")
async def rounds(term_id: int, user: CurrentUser = Depends(student), db=Depends(session)):
    return await queries.student_rounds(db, user.id, term_id)


@router.post("/me/enrollments")
async def enroll(body: SectionRef, user: CurrentUser = Depends(student)):
    """UC2/UC5: zapis albo dopisanie do listy oczekujących."""
    async with write_slot(user.id):
        result = await run_transaction(lambda s: enrollment.enroll(s, user.id, body.section_id))
    return asdict(result)


@router.delete("/me/enrollments/{section_id}")
async def drop(section_id: int, user: CurrentUser = Depends(student)):
    """UC6 (+ UC9 w tej samej transakcji)."""
    async with write_slot(user.id):
        await run_transaction(lambda s: enrollment.drop(s, user.id, section_id, actor_id=user.id))
    return {"status": "DROPPED"}


@router.delete("/me/waitlist/{section_id}")
async def leave_waitlist(section_id: int, user: CurrentUser = Depends(student)):
    """UC7."""
    async with write_slot(user.id):
        await run_transaction(lambda s: enrollment.leave_waitlist(s, user.id, section_id))
    return {"status": "CANCELLED"}


@router.get("/me/rounds/{round_id}/preferences")
async def get_preferences(round_id: int, user: CurrentUser = Depends(student), db=Depends(session)):
    """UC28: moje zgłoszenie w turze preferencyjnej."""
    return await preferences.get_preferences(db, user.id, round_id)


@router.put("/me/rounds/{round_id}/preferences")
async def save_preferences(round_id: int, body: PreferencesIn, user: CurrentUser = Depends(student)):
    """UC28: zastąpienie zgłoszenia (wagi przedmiotów + grupy w kolejności). Można wielokrotnie w trakcie tury."""
    items = [PreferenceInput(c.course_id, c.weight, tuple(c.section_ids)) for c in body.courses]
    async with write_slot(user.id):
        result = await run_transaction(lambda s: preferences.save_preferences(s, user.id, round_id, items))
    return asdict(result)


@router.get("/me/rounds/{round_id}/allocation")
async def my_allocation(round_id: int, user: CurrentUser = Depends(student), db=Depends(session)):
    """UC29: przewidywany (symulacja) albo końcowy przydział z powodami odmów."""
    return await allocation.student_view(db, user.id, round_id)


@router.get("/me/notifications")
async def notifications(user: CurrentUser = Depends(current_user), db=Depends(session)):
    return await queries.notifications(db, user.id)


@router.post("/me/notifications/read")
async def read_notifications(user: CurrentUser = Depends(current_user)):
    async def mark(s):
        await s.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                        .values(read_at=func.now()))
    await run_transaction(mark)
    return {"status": "OK"}
