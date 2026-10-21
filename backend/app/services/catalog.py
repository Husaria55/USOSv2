"""CatalogService: kursy, wymagania, semestry, sale, grupy, prowadzący, terminy (UC11, UC12)."""
from collections import defaultdict
from datetime import date, time

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.prerequisites import creates_cycle
from app.domain.schedule import ScheduledSection, Slot, conflicting_sections
from app.errors import Conflict, NotFound
from app.models import (
    Course, CoursePrerequisite, Meeting, Program, Room, Section, SectionLecturer, Term, User,
)
from app.services import loaders

# Klucze blokad doradczych (pg_advisory_xact_lock): serializują zmiany, których
# poprawność zależy od wielu wierszy naraz (cykl wymagań, kolizje sal/prowadzących).
LOCK_PREREQUISITES = (1, 0)
LOCK_ROOM = 2
LOCK_LECTURER = 3


async def _advisory(session: AsyncSession, *keys: tuple[int, int]) -> None:
    for a, b in sorted(set(keys)):                 # stała kolejność - bez zakleszczeń
        await session.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": a, "b": b})


async def _insert(session: AsyncSession, model, what: str, **values) -> int:
    try:
        async with session.begin_nested():
            return (await session.execute(insert(model).values(**values).returning(model.id))).scalar_one()
    except IntegrityError as e:
        raise Conflict("DUPLICATE", f"{what} już istnieje albo dane są niepoprawne.") from e


async def create_program(session: AsyncSession, code: str, name: str) -> int:
    return await _insert(session, Program, "Kierunek", code=code, name=name)


async def create_term(session: AsyncSession, code: str, starts_on: date, ends_on: date) -> int:
    if starts_on >= ends_on:
        raise Conflict("BAD_DATES", "Semestr musi się kończyć po rozpoczęciu.")
    return await _insert(session, Term, "Semestr", code=code, starts_on=starts_on, ends_on=ends_on)


async def create_room(session: AsyncSession, building: str, number: str, seats: int) -> int:
    return await _insert(session, Room, "Sala", building=building, number=number, seats=seats)


async def create_course(session: AsyncSession, code: str, name: str, ects: int, description: str | None) -> int:
    return await _insert(session, Course, "Kurs", code=code, name=name, ects=ects, description=description)


async def update_course(session: AsyncSession, course_id: int, **values) -> None:
    values = {k: v for k, v in values.items() if v is not None}
    if values:
        res = await session.execute(update(Course).where(Course.id == course_id).values(**values))
        if res.rowcount == 0:
            raise NotFound("COURSE_NOT_FOUND", "Nie ma takiego kursu.")


async def add_prerequisite(session: AsyncSession, course_id: int, required_id: int) -> None:
    await _advisory(session, LOCK_PREREQUISITES)
    graph: dict[int, set[int]] = defaultdict(set)
    for c, r in await session.execute(select(CoursePrerequisite.course_id, CoursePrerequisite.required_course_id)):
        graph[c].add(r)
    if creates_cycle(graph, course_id, required_id):
        raise Conflict("PREREQUISITE_CYCLE", "To wymaganie utworzyłoby cykl (kurs pośrednio wymagałby sam siebie).")
    try:
        async with session.begin_nested():
            await session.execute(insert(CoursePrerequisite).values(course_id=course_id, required_course_id=required_id))
    except IntegrityError as e:
        raise Conflict("DUPLICATE", "Takie wymaganie już istnieje albo kurs nie istnieje.") from e


async def remove_prerequisite(session: AsyncSession, course_id: int, required_id: int) -> None:
    await session.execute(delete(CoursePrerequisite).where(CoursePrerequisite.course_id == course_id,
                                                           CoursePrerequisite.required_course_id == required_id))


async def create_section(session: AsyncSession, course_id: int, term_id: int, code: str, kind: str,
                         capacity: int, waitlist_limit: int) -> int:
    return await _insert(session, Section, "Grupa", course_id=course_id, term_id=term_id, code=code, kind=kind,
                         capacity=capacity, waitlist_limit=waitlist_limit)


async def _section(session: AsyncSession, section_id: int) -> Section:
    s = (await session.execute(select(Section).where(Section.id == section_id))).scalar_one_or_none()
    if s is None:
        raise NotFound("SECTION_NOT_FOUND", "Nie ma takiej grupy.")
    return s


async def _lecturers(session: AsyncSession, section_id: int) -> list[int]:
    return list((await session.execute(select(SectionLecturer.lecturer_id)
                                       .where(SectionLecturer.section_id == section_id))).scalars())


async def _scheduled(session: AsyncSession, section_ids, exclude: int) -> list[ScheduledSection]:
    ids = [i for i in set(section_ids) if i != exclude]
    labels = await loaders.section_labels(session, ids)
    slots = await loaders.slots_by_section(session, ids)
    return [ScheduledSection(i, labels[i], "", slots[i]) for i in ids]


async def _lecturer_conflicts(session: AsyncSession, lecturer_ids: list[int], term_id: int,
                              section_id: int, slots: list[Slot]) -> list[str]:
    if not lecturer_ids or not slots:
        return []
    their = (await session.execute(
        select(SectionLecturer.section_id).join(Section, Section.id == SectionLecturer.section_id)
        .where(SectionLecturer.lecturer_id.in_(lecturer_ids), Section.term_id == term_id))).scalars()
    return [s.code for s in conflicting_sections(await _scheduled(session, their, section_id), slots)]


async def _room_conflicts(session: AsyncSession, room_id: int, term_id: int, section_id: int,
                          slot: Slot) -> list[str]:
    in_room = (await session.execute(
        select(Meeting.section_id).join(Section, Section.id == Meeting.section_id)
        .where(Meeting.room_id == room_id, Section.term_id == term_id))).scalars()
    # exclude=-1: liczą się też inne terminy tej samej grupy w tej sali
    plan = await _scheduled(session, in_room, -1)
    return [s.code for s in conflicting_sections(plan, [slot])]


async def add_meeting(session: AsyncSession, section_id: int, weekday: int, start: time, end: time,
                      parity: str, room_id: int | None) -> int:
    """UC12: termin grupy. Wykrywa kolizje sali i prowadzących (UC4)."""
    if start >= end:
        raise Conflict("BAD_TIME", "Zajęcia muszą się kończyć po rozpoczęciu.")
    section = await _section(session, section_id)
    lecturers = await _lecturers(session, section_id)
    keys = [(LOCK_LECTURER, lid) for lid in lecturers]
    if room_id is not None:
        keys.append((LOCK_ROOM, room_id))
    await _advisory(session, *keys)

    slot = Slot(weekday, start, end, parity)
    if room_id is not None:
        seats = (await session.execute(select(Room.seats).where(Room.id == room_id))).scalar()
        if seats is None:
            raise NotFound("ROOM_NOT_FOUND", "Nie ma takiej sali.")
        if section.capacity > seats:
            raise Conflict("ROOM_TOO_SMALL", f"Sala ma {seats} miejsc, a limit grupy to {section.capacity}.")
        busy = await _room_conflicts(session, room_id, section.term_id, section_id, slot)
        if busy:
            raise Conflict("ROOM_BUSY", "Sala jest zajęta: " + ", ".join(busy) + ".", busy)
    busy = await _lecturer_conflicts(session, lecturers, section.term_id, section_id, [slot])
    if busy:
        raise Conflict("LECTURER_BUSY", "Prowadzący ma wtedy zajęcia: " + ", ".join(busy) + ".", busy)
    return (await session.execute(insert(Meeting).values(
        section_id=section_id, weekday=weekday, start_time=start, end_time=end, week_parity=parity,
        room_id=room_id).returning(Meeting.id))).scalar_one()


async def remove_meeting(session: AsyncSession, meeting_id: int) -> None:
    await session.execute(delete(Meeting).where(Meeting.id == meeting_id))


async def assign_lecturer(session: AsyncSession, section_id: int, lecturer_id: int) -> None:
    section = await _section(session, section_id)
    role = (await session.execute(select(User.role).where(User.id == lecturer_id))).scalar()
    if role != "LECTURER":
        raise NotFound("LECTURER_NOT_FOUND", "Nie ma takiego prowadzącego.")
    await _advisory(session, (LOCK_LECTURER, lecturer_id))
    slots = (await loaders.slots_by_section(session, [section_id]))[section_id]
    busy = await _lecturer_conflicts(session, [lecturer_id], section.term_id, section_id, list(slots))
    if busy:
        raise Conflict("LECTURER_BUSY", "Prowadzący ma wtedy zajęcia: " + ", ".join(busy) + ".", busy)
    try:
        async with session.begin_nested():
            await session.execute(insert(SectionLecturer).values(section_id=section_id, lecturer_id=lecturer_id))
    except IntegrityError as e:
        raise Conflict("DUPLICATE", "Prowadzący jest już przypisany do tej grupy.") from e


async def remove_lecturer(session: AsyncSession, section_id: int, lecturer_id: int) -> None:
    await session.execute(delete(SectionLecturer).where(SectionLecturer.section_id == section_id,
                                                        SectionLecturer.lecturer_id == lecturer_id))

