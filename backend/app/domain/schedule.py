"""Kolizje terminów zajęć.

Dwa terminy kolidują, gdy są tego samego dnia, godziny się przecinają
(start1 < end2 i start2 < end1, więc 8:00-9:30 i 9:30-11:00 nie kolidują),
a tygodnie się pokrywają (ALL koliduje ze wszystkim, ODD tylko z ODD,
EVEN tylko z EVEN).
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class Slot:
    weekday: int
    start: time
    end: time
    parity: str = "ALL"


def weeks_overlap(a: str, b: str) -> bool:
    return a == "ALL" or b == "ALL" or a == b


def slots_overlap(a: Slot, b: Slot) -> bool:
    return (
        a.weekday == b.weekday
        and a.start < b.end
        and b.start < a.end
        and weeks_overlap(a.parity, b.parity)
    )


def any_overlap(mine: Iterable[Slot], other: Iterable[Slot]) -> bool:
    other = list(other)
    return any(slots_overlap(a, b) for a in mine for b in other)


@dataclass(frozen=True)
class ScheduledSection:
    """Grupa z planu studenta (albo z planu sali / prowadzącego)."""
    section_id: int
    code: str
    course_code: str
    slots: tuple[Slot, ...]

    @property
    def label(self) -> str:
        return f"{self.course_code} {self.code}"


def conflicting_sections(plan: Iterable[ScheduledSection], new: Iterable[Slot]) -> list[ScheduledSection]:
    """Grupy z planu, których terminy nachodzą na którykolwiek z terminów `new`."""
    new = list(new)
    return [s for s in plan if any_overlap(s.slots, new)]
