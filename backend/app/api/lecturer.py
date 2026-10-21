"""Prowadzący: swoje grupy i listy studentów (UC10)."""
from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, lecturer, session
from app.errors import Forbidden
from app.services import queries

router = APIRouter(prefix="/api")


@router.get("/lecturer/terms/{term_id}/sections")
async def my_sections(term_id: int, user: CurrentUser = Depends(lecturer), db=Depends(session)):
    return await queries.lecturer_sections(db, user.id, term_id)


@router.get("/sections/{section_id}/roster")
async def roster(section_id: int, user: CurrentUser = Depends(lecturer), db=Depends(session)):
    if user.role != "ADMIN" and not await queries.is_lecturer_of(db, user.id, section_id):
        raise Forbidden("FORBIDDEN", "To nie jest Twoja grupa.")
    return await queries.section_roster(db, section_id)
