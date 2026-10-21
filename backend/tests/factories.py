"""Szybkie tworzenie danych testowych (z pominięciem API)."""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import insert

from app.db import Session
from app.models import (
    CompletedCourse, Course, CoursePrerequisite, EnrollmentRound, Meeting, Program, Room, RoundProgram,
    Section, Term, User,
)
from app.security import hash_password

_n = 0


def _next() -> int:
    global _n
    _n += 1
    return _n


async def _ins(model, **values) -> int:
    async with Session() as s, s.begin():
        return (await s.execute(insert(model).values(**values).returning(model.id))).scalar_one()


async def program(code: str | None = None) -> int:
    code = code or f"P{_next()}"
    return await _ins(Program, code=code, name=f"Kierunek {code}")


async def term(code: str = "2026Z") -> int:
    return await _ins(Term, code=code, starts_on=date(2026, 10, 1), ends_on=date(2027, 2, 15))


async def round_(term_id: int, programs: list[int] = (), status: str = "OPEN", name: str | None = None) -> int:
    now = datetime.now(timezone.utc)
    rid = await _ins(EnrollmentRound, term_id=term_id, name=name or f"tura {_next()}", status=status,
                     opens_at=now - timedelta(hours=1), closes_at=now + timedelta(hours=1))
    async with Session() as s, s.begin():
        for p in programs:
            await s.execute(insert(RoundProgram).values(round_id=rid, program_id=p))
    return rid


async def student(program_id: int, name: str | None = None, password: str = "haslo") -> int:
    n = _next()
    return await _ins(User, email=f"s{n}@uczelnia.pl", password_hash=hash_password(password),
                      full_name=name or f"Student {n}", role="STUDENT", index_no=str(400000 + n),
                      program_id=program_id, semester=3)


async def students(program_id: int, count: int) -> list[int]:
    h = hash_password("haslo")
    async with Session() as s, s.begin():
        ids = []
        for _ in range(count):
            n = _next()
            ids.append((await s.execute(insert(User).values(
                email=f"s{n}@uczelnia.pl", password_hash=h, full_name=f"Student {n}", role="STUDENT",
                index_no=str(400000 + n), program_id=program_id, semester=3).returning(User.id))).scalar_one())
        return ids


async def lecturer(name: str = "dr Kowalski") -> int:
    n = _next()
    return await _ins(User, email=f"l{n}@uczelnia.pl", password_hash=hash_password("haslo"), full_name=name,
                      role="LECTURER", title="dr", department="Katedra Informatyki")


async def admin() -> int:
    n = _next()
    return await _ins(User, email=f"a{n}@uczelnia.pl", password_hash=hash_password("haslo"),
                      full_name="Dziekanat", role="ADMIN")


async def course(code: str | None = None, requires: list[int] = ()) -> int:
    code = code or f"K{_next()}"
    cid = await _ins(Course, code=code, name=f"Przedmiot {code}", ects=5)
    async with Session() as s, s.begin():
        for r in requires:
            await s.execute(insert(CoursePrerequisite).values(course_id=cid, required_course_id=r))
    return cid


async def room(seats: int = 30) -> int:
    n = _next()
    return await _ins(Room, building="C-2", number=str(n), seats=seats)


def t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


async def section(course_id: int, term_id: int, code: str = "L01", kind: str = "LAB", capacity: int = 10,
                  meetings: list[tuple] = ((1, "10:00", "11:30"),), waitlist_limit: int = 50,
                  room_id: int | None = None) -> int:
    sid = await _ins(Section, course_id=course_id, term_id=term_id, code=code, kind=kind, capacity=capacity,
                     waitlist_limit=waitlist_limit)
    async with Session() as s, s.begin():
        for m in meetings:
            wd, st, en, *par = m
            await s.execute(insert(Meeting).values(section_id=sid, weekday=wd, start_time=t(st),
                                                   end_time=t(en), week_parity=par[0] if par else "ALL",
                                                   room_id=room_id))
    return sid


async def passed(student_id: int, course_id: int, term_id: int, grade: str = "4.0") -> None:
    async with Session() as s, s.begin():
        await s.execute(insert(CompletedCourse).values(student_id=student_id, course_id=course_id,
                                                       term_id=term_id, grade=grade))
