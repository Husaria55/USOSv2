"""EnrollmentService: zapisy, wypisy, listy oczekujących (UC2, UC5, UC6, UC7, UC9, UC13, UC14).

Każda funkcja publiczna to ciało jednej transakcji (wywołuje się ją przez
db.run_transaction, która ponawia ją przy konfliktach blokad).

Kolejność blokad: student -> grupa. Wyjątek to awans z listy (grupa ->
awansowany student), dlatego tam student jest blokowany z NOWAIT: zajęty
wiersz kończy się błędem 55P03 i ponowieniem całej transakcji, a nie
zakleszczeniem. Awansowany nie traci przez to kolejki.
"""
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enrollment_rules import (
    Mode, Outcome, Refusal, SeatState, TargetSection, WaitingEntry, check_student, decide_seat,
    same_kind_waiting,
)
from app.domain.rounds import student_can_enroll
from app.errors import Conflict
from app.services import loaders
from app.services.loaders import LockedSection, pg
from app.services.notifications import notify, notify_many, payload


@dataclass
class EnrollResult:
    status: str                 # ENROLLED | WAITLISTED
    section_id: int
    position: int | None = None
    cancelled_waitlists: list[str] = field(default_factory=list)


@dataclass
class PromotionEvent:
    student_id: int
    status: str                 # PROMOTED | SKIPPED
    reason: str | None = None


def _source(mode: Mode) -> str:
    return mode.value


async def _cancel_same_kind(session: AsyncSession, student_id: int, waiting: list[WaitingEntry],
                            target: TargetSection, keep_entry: int | None = None) -> list[str]:
    """Po zapisie: wpisy WAITING studenta w grupach tego przedmiotu i typu -> CANCELLED."""
    ids = [i for i in same_kind_waiting(waiting, target.course_id, target.kind) if i != keep_entry]
    if not ids:
        return []
    rows = await (await pg(session)).fetch(
        "UPDATE waitlist_entry SET status = 'CANCELLED', resolved_at = now() "
        "WHERE id = ANY($1::bigint[]) AND status = 'WAITING' RETURNING section_id", ids)
    labels = await loaders.section_labels(session, [r[0] for r in rows])
    await notify_many(session, [(student_id, "CANCELLED", payload("CANCELLED", labels[r[0]])) for r in rows])
    return list(labels.values())


async def _insert_enrollment(session: AsyncSession, student_id: int, section_id: int, mode: Mode,
                             actor_id: int | None) -> int:
    return await (await pg(session)).fetchval(
        "INSERT INTO enrollment (student_id, section_id, status, source, created_by) "
        "VALUES ($1, $2, 'ENROLLED', $3, $4) RETURNING id", student_id, section_id, _source(mode), actor_id)


async def _add_to_count(session: AsyncSession, section_id: int, delta: int, capacity_delta: int = 0) -> None:
    await (await pg(session)).execute(
        "UPDATE section SET enrolled_count = enrolled_count + $2, capacity = capacity + $3 WHERE id = $1",
        section_id, delta, capacity_delta)


async def enroll(session: AsyncSession, student_id: int, section_id: int, *,
                 mode: Mode = Mode.DIRECT, actor_id: int | None = None) -> EnrollResult:
    """UC2 (student) / UC14 (dziekanat): zapis do grupy albo na listę oczekujących."""
    student = await loaders.lock_student(session, student_id)          # 1. blokada studenta
    target, term_id = await loaders.load_target(session, section_id)
    # Plan studenta jest stały pod jego blokadą, więc reguły zależne od planu
    # sprawdzamy przed blokadą grupy - popularna grupa jest blokowana krócej.
    state, waiting = await loaders.student_state(session, student, term_id,
                                                 need_passed=bool(target.prerequisites))
    refusals = check_student(state, target, mode)
    if refusals:
        raise Conflict.from_refusal(refusals[0])

    section = await loaders.lock_section(session, section_id)          # 2. blokada grupy
    full = section.enrolled_count >= section.capacity
    seat = SeatState(
        capacity=section.capacity, enrolled_count=section.enrolled_count,
        waitlist_limit=section.waitlist_limit,
        waiting_count=await loaders.waiting_count(session, section_id) if full else 0,
        room_seats=await loaders.room_seats(session, section_id) if full and mode is Mode.ADMIN else None,
    )
    outcome = decide_seat(seat, mode)
    if isinstance(outcome, Refusal):
        raise Conflict.from_refusal(outcome)

    if outcome is Outcome.WAITLIST:
        await (await pg(session)).execute(
            "INSERT INTO waitlist_entry (student_id, section_id) VALUES ($1, $2)", student_id, section_id)
        return EnrollResult("WAITLISTED", section_id, position=seat.waiting_count + 1)

    await _add_to_count(session, section_id, 1, 1 if outcome is Outcome.ENROLL_OVER_CAPACITY else 0)
    await _insert_enrollment(session, student_id, section_id, mode, actor_id)
    cancelled = await _cancel_same_kind(session, student_id, waiting, target)
    if mode is Mode.ADMIN:
        await notify(session, student_id, "ADMIN_ENROLLED", target.label)
    return EnrollResult("ENROLLED", section_id, cancelled_waitlists=cancelled)


async def drop(session: AsyncSession, student_id: int, section_id: int, *,
               mode: Mode = Mode.DIRECT, actor_id: int | None = None) -> list[PromotionEvent]:
    """UC6 (student, tylko w otwartej turze) / UC14 (dziekanat, zawsze). Obejmuje UC9."""
    student = await loaders.lock_student(session, student_id)
    target, term_id = await loaders.load_target(session, section_id)
    if mode is Mode.DIRECT:
        rounds = await loaders.term_rounds(session, term_id, only_open=True)
        if not student_can_enroll(rounds, student.program_id):
            raise Conflict("ROUND_CLOSED", "Tura zapisów dla Twojego kierunku jest zamknięta.")
    section = await loaders.lock_section(session, section_id)
    dropped = await (await pg(session)).fetchval(
        "UPDATE enrollment SET status = 'DROPPED', dropped_at = now(), dropped_by = $3 "
        "WHERE student_id = $1 AND section_id = $2 AND status = 'ENROLLED' RETURNING id",
        student_id, section_id, actor_id)
    if dropped is None:
        raise Conflict("NOT_ENROLLED", f"Nie jesteś zapisany do grupy {target.label}.")
    await _add_to_count(session, section_id, -1)
    section.enrolled_count -= 1
    if mode is Mode.ADMIN:
        await notify(session, student_id, "ADMIN_DROPPED", target.label)
    return await promote(session, section, target, term_id)


async def leave_waitlist(session: AsyncSession, student_id: int, section_id: int) -> None:
    """UC7. Blokada studenta wystarcza: awans tego studenta potrzebowałby jej z NOWAIT."""
    await loaders.lock_student(session, student_id)
    cancelled = await (await pg(session)).fetchval(
        "UPDATE waitlist_entry SET status = 'CANCELLED', resolved_at = now() "
        "WHERE student_id = $1 AND section_id = $2 AND status = 'WAITING' RETURNING id", student_id, section_id)
    if cancelled is None:
        raise Conflict("NOT_WAITING", "Nie czekasz na liście tej grupy.")


async def change_limits(session: AsyncSession, section_id: int, *, capacity: int | None = None,
                        waitlist_limit: int | None = None) -> list[PromotionEvent]:
    """UC13: zmiana limitu miejsc (i długości listy). Wolne miejsce -> UC9."""
    target, term_id = await loaders.load_target(session, section_id)
    section = await loaders.lock_section(session, section_id)
    if capacity is not None:
        if capacity < section.enrolled_count:
            raise Conflict("BELOW_ENROLLED",
                           f"Zapisanych jest {section.enrolled_count} osób - limit nie może być mniejszy.")
        seats = await loaders.room_seats(session, section_id)
        if seats is not None and capacity > seats:
            raise Conflict("ROOM_FULL", f"Sala ma tylko {seats} miejsc.")
        section.capacity = capacity
    if waitlist_limit is not None:
        section.waitlist_limit = waitlist_limit
    await (await pg(session)).execute("UPDATE section SET capacity = $2, waitlist_limit = $3 WHERE id = $1",
                                      section_id, section.capacity, section.waitlist_limit)
    return await promote(session, section, target, term_id)


async def promote(session: AsyncSession, section: LockedSection, target: TargetSection,
                  term_id: int) -> list[PromotionEvent]:
    """UC9: dopóki są wolne miejsca, zapisuje kolejnych oczekujących.

    Wymaga blokady grupy. Każdego kandydata sprawdza ponownie (od dopisania do
    listy jego plan mógł się zmienić); niespełniający warunków dostaje SKIPPED.
    """
    events: list[PromotionEvent] = []
    while section.enrolled_count < section.capacity:
        entry = await (await pg(session)).fetchrow(
            "SELECT id, student_id FROM waitlist_entry WHERE section_id = $1 AND status = 'WAITING' "
            "ORDER BY id LIMIT 1", section.id)
        if entry is None:
            break
        entry_id, candidate_id = entry
        candidate = await loaders.lock_student(session, candidate_id, nowait=True)
        state, waiting = await loaders.student_state(session, candidate, term_id,
                                                     need_passed=bool(target.prerequisites))
        refusals = check_student(state, target, Mode.WAITLIST)
        if refusals:
            reason = refusals[0].message
            await (await pg(session)).execute(
                "UPDATE waitlist_entry SET status = 'SKIPPED', resolved_at = now(), skip_reason = $2 WHERE id = $1",
                entry_id, reason[:255])
            await notify(session, candidate_id, "SKIPPED", target.label, reason=reason)
            events.append(PromotionEvent(candidate_id, "SKIPPED", reason))
            continue

        enrollment_id = await _insert_enrollment(session, candidate_id, section.id, Mode.WAITLIST, None)
        await (await pg(session)).execute(
            "UPDATE waitlist_entry SET status = 'PROMOTED', resolved_at = now(), enrollment_id = $2 WHERE id = $1",
            entry_id, enrollment_id)
        await _add_to_count(session, section.id, 1)
        section.enrolled_count += 1
        await _cancel_same_kind(session, candidate_id, waiting, target, keep_entry=entry_id)
        await notify(session, candidate_id, "PROMOTED", target.label)
        events.append(PromotionEvent(candidate_id, "PROMOTED"))
    return events


async def waitlist_position(session: AsyncSession, student_id: int, section_id: int) -> int | None:
    return (await loaders.waitlist_positions(session, student_id, [section_id])).get(section_id)
