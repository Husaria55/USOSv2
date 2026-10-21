"""Reguły zapisu do grupy.

Funkcje dostają gotowe dane (wczytane przez EnrollmentService pod blokadami)
i zwracają decyzję. Nie znają bazy, więc testuje się je bez niej.

Sprawdzenia są w dwóch krokach, zgodnie z kolejnością blokad:
1. check_student: wszystko, co zależy od planu studenta (stałego pod
   blokadą studenta),
2. decide_seat: miejsce w grupie (stałe dopiero pod blokadą grupy).
Dzięki temu blokada popularnej grupy jest trzymana możliwie krótko.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.prerequisites import missing_prerequisites
from app.domain.schedule import ScheduledSection, Slot, conflicting_sections


class Mode(StrEnum):
    DIRECT = "DIRECT"      # student sam (UC2)
    WAITLIST = "WAITLIST"  # awans z listy oczekujących (UC9)
    ADMIN = "ADMIN"        # decyzja dziekanatu (UC14)


class Outcome(StrEnum):
    ENROLL = "ENROLL"
    WAITLIST = "WAITLIST"
    ENROLL_OVER_CAPACITY = "ENROLL_OVER_CAPACITY"  # dziekanat: limit + 1


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanEntry(ScheduledSection):
    """Grupa, do której student jest zapisany w semestrze nowej grupy."""
    course_id: int
    kind: str


@dataclass(frozen=True)
class TargetSection:
    id: int
    course_id: int
    course_code: str
    code: str
    kind: str
    slots: tuple[Slot, ...]
    prerequisites: Mapping[int, str] = field(default_factory=dict)  # id kursu -> kod

    @property
    def label(self) -> str:
        return f"{self.course_code} {self.code}"


@dataclass(frozen=True)
class StudentState:
    round_open: bool
    plan: tuple[PlanEntry, ...]
    passed_course_ids: frozenset[int]
    waiting_section_ids: frozenset[int]


@dataclass(frozen=True)
class WaitingEntry:
    id: int
    section_id: int
    course_id: int
    kind: str


@dataclass(frozen=True)
class SeatState:
    capacity: int
    enrolled_count: int
    waitlist_limit: int
    waiting_count: int
    room_seats: int | None  # najmniejsza sala z terminów grupy, None = bez sali


def check_student(student: StudentState, target: TargetSection, mode: Mode) -> list[Refusal]:
    """Wszystkie powody odmowy wynikające z sytuacji studenta (pusta lista = OK)."""
    refusals: list[Refusal] = []
    if mode is Mode.DIRECT and not student.round_open:
        refusals.append(Refusal("ROUND_CLOSED", "Tura zapisów dla Twojego kierunku jest zamknięta."))

    if any(p.section_id == target.id for p in student.plan):
        refusals.append(Refusal("ALREADY_ENROLLED", f"Jesteś już zapisany do grupy {target.label}."))
    elif mode is Mode.DIRECT and target.id in student.waiting_section_ids:
        refusals.append(Refusal("ALREADY_WAITING", f"Już czekasz na liście grupy {target.label}."))

    same_kind = [p for p in student.plan
                 if p.course_id == target.course_id and p.kind == target.kind and p.section_id != target.id]
    if same_kind:
        refusals.append(Refusal(
            "SAME_KIND",
            f"Masz już grupę tego typu z tego przedmiotu: {same_kind[0].label}.",
            tuple(p.label for p in same_kind),
        ))

    if mode is not Mode.ADMIN:
        missing = missing_prerequisites(target.prerequisites, student.passed_course_ids)
        if missing:
            codes = tuple(sorted(target.prerequisites[c] for c in missing))
            refusals.append(Refusal("PREREQUISITES", "Brak zaliczenia: " + ", ".join(codes) + ".", codes))

    others = [p for p in student.plan if p.section_id != target.id]
    conflicts = conflicting_sections(others, target.slots)
    if conflicts:
        labels = tuple(c.label for c in conflicts)
        refusals.append(Refusal("CONFLICT", "Kolizja w planie z: " + ", ".join(labels) + ".", labels))
    return refusals


def decide_seat(seat: SeatState, mode: Mode) -> Outcome | Refusal:
    if seat.enrolled_count < seat.capacity:
        return Outcome.ENROLL
    if mode is Mode.ADMIN:
        if seat.room_seats is not None and seat.capacity + 1 > seat.room_seats:
            return Refusal("ROOM_FULL", f"Sala ma tylko {seat.room_seats} miejsc.")
        return Outcome.ENROLL_OVER_CAPACITY
    if mode is Mode.WAITLIST:
        # awans wywołujemy tylko przy wolnym miejscu
        return Refusal("NO_SEAT", "Brak wolnego miejsca.")
    if seat.waiting_count >= seat.waitlist_limit:
        return Refusal("WAITLIST_FULL", "Brak miejsc, a lista oczekujących jest pełna.")
    return Outcome.WAITLIST


def same_kind_waiting(waiting: Iterable[WaitingEntry], course_id: int, kind: str) -> list[int]:
    """Wpisy na listach grup tego samego przedmiotu i typu (id wpisów).

    Po zapisie do grupy wpisy te dostają CANCELLED: zostałyby i tak pominięte
    przy awansie, a zajmują innym miejsce na liście.
    """
    return [w.id for w in waiting if w.course_id == course_id and w.kind == kind]
