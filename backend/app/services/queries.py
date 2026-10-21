"""Odczyty dla interfejsu (bez blokad). Stan dla studenta liczą te same reguły co zapis."""
from collections import defaultdict

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enrollment_rules import Mode, TargetSection, check_student
from app.domain.rounds import covers
from app.errors import NotFound
from app.models import (
    Course, CoursePrerequisite, Enrollment, EnrollmentRound, Meeting, Notification, Program, Room, Section,
    SectionLecturer, Term, User, WaitlistEntry,
)
from app.services import loaders


KIND_ORDER = case({"LECTURE": 0, "EXERCISE": 1, "SEMINAR": 2, "LAB": 3}, value=Section.kind)


def _t(t) -> str:
    return t.strftime("%H:%M")


async def terms(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(Term).order_by(Term.starts_on.desc()))).scalars()
    return [{"id": t.id, "code": t.code, "starts_on": t.starts_on, "ends_on": t.ends_on} for t in rows]


async def programs(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(Program).order_by(Program.code))).scalars()
    return [{"id": p.id, "code": p.code, "name": p.name} for p in rows]


async def rooms(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(Room).order_by(Room.building, Room.number))).scalars()
    return [{"id": r.id, "building": r.building, "number": r.number, "seats": r.seats} for r in rows]


async def course_list(session: AsyncSession, term_id: int | None, q: str | None, limit: int, offset: int) -> list[dict]:
    """Kursy (z liczbą grup i wolnych miejsc w semestrze, gdy podany)."""
    seats = (select(Section.course_id, func.count().label("n"),
                    func.sum(Section.capacity - Section.enrolled_count).label("free"))
             .where(Section.term_id == term_id).group_by(Section.course_id).subquery())
    query = (select(Course, func.coalesce(seats.c.n, 0), func.coalesce(seats.c.free, 0))
             .outerjoin(seats, seats.c.course_id == Course.id).order_by(Course.code).limit(limit).offset(offset))
    if term_id is not None:
        query = query.where(seats.c.n > 0)
    if q:
        query = query.where(or_(Course.code.ilike(f"%{q}%"), Course.name.ilike(f"%{q}%")))
    return [{"id": c.id, "code": c.code, "name": c.name, "ects": c.ects, "sections": n, "free_seats": int(free)}
            for c, n, free in await session.execute(query)]


async def _meetings(session: AsyncSession, section_ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    ids = list(section_ids)
    if ids:
        rows = await session.execute(
            select(Meeting, Room.building, Room.number).outerjoin(Room, Room.id == Meeting.room_id)
            .where(Meeting.section_id.in_(ids)).order_by(Meeting.weekday, Meeting.start_time))
        for m, b, n in rows:
            out[m.section_id].append({"id": m.id, "weekday": m.weekday, "start": _t(m.start_time),
                                      "end": _t(m.end_time), "parity": m.week_parity,
                                      "room": f"{b} {n}" if b else None, "room_id": m.room_id})
    return out


async def _lecturer_names(session: AsyncSession, section_ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    ids = list(section_ids)
    if ids:
        rows = await session.execute(select(SectionLecturer.section_id, User.id, User.title, User.full_name)
                                     .join(User, User.id == SectionLecturer.lecturer_id)
                                     .where(SectionLecturer.section_id.in_(ids)))
        for sid, uid, title, name in rows:
            out[sid].append({"id": uid, "name": f"{title} {name}" if title else name})
    return out


async def course_detail(session: AsyncSession, course_id: int, term_id: int | None) -> dict:
    course = (await session.execute(select(Course).where(Course.id == course_id))).scalar_one_or_none()
    if course is None:
        raise NotFound("COURSE_NOT_FOUND", "Nie ma takiego kursu.")
    prereqs = (await session.execute(
        select(Course.id, Course.code, Course.name)
        .join(CoursePrerequisite, CoursePrerequisite.required_course_id == Course.id)
        .where(CoursePrerequisite.course_id == course_id).order_by(Course.code))).all()
    waiting = (select(WaitlistEntry.section_id, func.count().label("n")).where(WaitlistEntry.status == "WAITING")
               .group_by(WaitlistEntry.section_id).subquery())
    q = (select(Section, func.coalesce(waiting.c.n, 0)).outerjoin(waiting, waiting.c.section_id == Section.id)
         .where(Section.course_id == course_id).order_by(KIND_ORDER, Section.code))
    if term_id is not None:
        q = q.where(Section.term_id == term_id)
    rows = (await session.execute(q)).all()
    ids = [s.id for s, _ in rows]
    meetings, lecturers = await _meetings(session, ids), await _lecturer_names(session, ids)
    return {
        "id": course.id, "code": course.code, "name": course.name, "ects": course.ects,
        "description": course.description,
        "prerequisites": [{"id": i, "code": c, "name": n} for i, c, n in prereqs],
        "sections": [{
            "id": s.id, "term_id": s.term_id, "code": s.code, "kind": s.kind, "capacity": s.capacity,
            "enrolled_count": s.enrolled_count, "waitlist_limit": s.waitlist_limit, "waiting_count": w,
            "meetings": meetings[s.id], "lecturers": lecturers[s.id],
        } for s, w in rows],
    }


async def _student(session: AsyncSession, student_id: int) -> loaders.LockedStudent:
    pid = (await session.execute(select(User.program_id).where(User.id == student_id))).scalar_one()
    return loaders.LockedStudent(student_id, pid)


async def student_course_status(session: AsyncSession, student_id: int, course_id: int, term_id: int) -> dict:
    """Dla każdej grupy kursu: czy student może się zapisać, a jeśli nie, to dlaczego.

    Podgląd bez blokad - ostateczną decyzję i tak podejmuje transakcja zapisu.
    """
    student = await _student(session, student_id)
    state, _ = await loaders.student_state(session, student, term_id)
    sections = (await session.execute(select(Section.id).where(
        Section.course_id == course_id, Section.term_id == term_id))).scalars().all()
    targets = await loaders.load_targets(session, sections)
    positions = await loaders.waitlist_positions(session, student_id, sections) if state.waiting_section_ids else {}
    out = []
    for sid in sections:
        refusals = check_student(state, targets[sid][0], Mode.DIRECT)
        enrolled = any(p.section_id == sid for p in state.plan)
        waiting = sid in state.waiting_section_ids
        out.append({
            "section_id": sid,
            "state": "ENROLLED" if enrolled else "WAITING" if waiting else "BLOCKED" if refusals else "AVAILABLE",
            "position": positions.get(sid),
            "refusals": [{"code": r.code, "message": r.message} for r in refusals
                         if r.code not in ("ALREADY_ENROLLED", "ALREADY_WAITING")],
        })
    return {"round_open": state.round_open, "sections": out}


async def student_plan(session: AsyncSession, student_id: int, term_id: int) -> list[dict]:
    rows = (await session.execute(
        select(Section, Course.code, Course.name, Enrollment.source, Enrollment.enrolled_at)
        .join(Enrollment, Enrollment.section_id == Section.id).join(Course, Course.id == Section.course_id)
        .where(Enrollment.student_id == student_id, Enrollment.status == "ENROLLED", Section.term_id == term_id)
        .order_by(Course.code, KIND_ORDER))).all()
    ids = [r[0].id for r in rows]
    meetings, lecturers = await _meetings(session, ids), await _lecturer_names(session, ids)
    return [{"section_id": s.id, "course_id": s.course_id, "course_code": cc, "course_name": cn, "code": s.code,
             "kind": s.kind, "source": src, "enrolled_at": at, "meetings": meetings[s.id],
             "lecturers": lecturers[s.id]} for s, cc, cn, src, at in rows]


async def student_waitlist(session: AsyncSession, student_id: int, term_id: int) -> list[dict]:
    """Aktualne wpisy z pozycją oraz ostatnie rozstrzygnięte (historia)."""
    rows = (await session.execute(
        select(WaitlistEntry, Section, Course.code, Course.name)
        .join(Section, Section.id == WaitlistEntry.section_id).join(Course, Course.id == Section.course_id)
        .where(WaitlistEntry.student_id == student_id, Section.term_id == term_id)
        .order_by(WaitlistEntry.id.desc()).limit(100))).all()
    positions = await loaders.waitlist_positions(session, student_id)
    out = []
    for w, s, cc, cn in rows:
        out.append({"id": w.id, "section_id": s.id, "course_id": s.course_id, "course_code": cc,
                    "course_name": cn, "code": s.code, "kind": s.kind, "status": w.status,
                    "created_at": w.created_at, "resolved_at": w.resolved_at, "skip_reason": w.skip_reason,
                    "position": positions.get(s.id) if w.status == "WAITING" else None})
    return out


async def student_rounds(session: AsyncSession, student_id: int, term_id: int) -> list[dict]:
    student = await _student(session, student_id)
    rounds = await loaders.term_rounds(session, term_id)
    return [{"id": r.id, "status": r.status, "opens_at": r.opens_at, "closes_at": r.closes_at}
            for r in sorted(rounds, key=lambda r: r.opens_at) if covers(r, student.program_id)]


async def all_rounds(session: AsyncSession, term_id: int) -> list[dict]:
    rounds = await loaders.term_rounds(session, term_id)
    names = dict((await session.execute(select(EnrollmentRound.id, EnrollmentRound.name)
                                        .where(EnrollmentRound.term_id == term_id))).all())
    return [{"id": r.id, "name": names[r.id], "status": r.status, "opens_at": r.opens_at,
             "closes_at": r.closes_at, "program_ids": sorted(r.program_ids)}
            for r in sorted(rounds, key=lambda r: r.opens_at)]


async def notifications(session: AsyncSession, user_id: int, limit: int = 50) -> list[dict]:
    rows = (await session.execute(select(Notification).where(Notification.user_id == user_id)
                                  .order_by(Notification.id.desc()).limit(limit))).scalars()
    return [{"id": n.id, "type": n.type, "message": n.payload.get("message"), "created_at": n.created_at,
             "read": n.read_at is not None} for n in rows]


async def lecturer_sections(session: AsyncSession, lecturer_id: int, term_id: int) -> list[dict]:
    rows = (await session.execute(
        select(Section, Course.code, Course.name).join(SectionLecturer, SectionLecturer.section_id == Section.id)
        .join(Course, Course.id == Section.course_id)
        .where(SectionLecturer.lecturer_id == lecturer_id, Section.term_id == term_id)
        .order_by(Course.code, Section.code))).all()
    meetings = await _meetings(session, [s.id for s, *_ in rows])
    return [{"id": s.id, "course_code": cc, "course_name": cn, "code": s.code, "kind": s.kind,
             "capacity": s.capacity, "enrolled_count": s.enrolled_count, "meetings": meetings[s.id]}
            for s, cc, cn in rows]


async def is_lecturer_of(session: AsyncSession, lecturer_id: int, section_id: int) -> bool:
    return (await session.execute(select(SectionLecturer).where(
        SectionLecturer.lecturer_id == lecturer_id, SectionLecturer.section_id == section_id))).first() is not None


async def section_roster(session: AsyncSession, section_id: int) -> dict:
    """UC10: zapisani i oczekujący (w kolejności)."""
    label = (await loaders.section_labels(session, [section_id])).get(section_id)
    if label is None:
        raise NotFound("SECTION_NOT_FOUND", "Nie ma takiej grupy.")
    student = select(User.id, User.full_name, User.index_no, User.email, Program.code.label("program"))
    enrolled = (await session.execute(
        student.add_columns(Enrollment.source, Enrollment.enrolled_at)
        .join(Enrollment, Enrollment.student_id == User.id).join(Program, Program.id == User.program_id)
        .where(Enrollment.section_id == section_id, Enrollment.status == "ENROLLED")
        .order_by(User.full_name))).mappings().all()
    waiting = (await session.execute(
        student.add_columns(WaitlistEntry.created_at)
        .join(WaitlistEntry, WaitlistEntry.student_id == User.id).join(Program, Program.id == User.program_id)
        .where(WaitlistEntry.section_id == section_id, WaitlistEntry.status == "WAITING")
        .order_by(WaitlistEntry.id))).mappings().all()
    return {"label": label, "enrolled": [dict(r) for r in enrolled],
            "waiting": [dict(r) | {"position": i} for i, r in enumerate(waiting, start=1)]}


def user_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "index_no": u.index_no,
            "program_id": u.program_id, "semester": u.semester, "title": u.title, "department": u.department}
