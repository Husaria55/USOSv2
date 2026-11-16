"""Tury zapisów: kto może się zapisywać i kiedy worker zmienia status tury.

Tura ma tryb:
- QUEUE: zapis "kto pierwszy, ten lepszy" z listami oczekujących (etap 3),
- PREFERENCES: student zgłasza preferencje (wagi przedmiotów), miejsca przydziela
  optymalizator po zamknięciu tury (app/domain/allocation.py).
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RoundMode(StrEnum):
    QUEUE = "QUEUE"
    PREFERENCES = "PREFERENCES"


@dataclass(frozen=True)
class RoundInfo:
    id: int
    status: str
    opens_at: datetime
    closes_at: datetime
    program_ids: frozenset[int]  # pusty zbiór = tura dla wszystkich kierunków
    mode: RoundMode = RoundMode.QUEUE
    points_budget: int | None = None


def covers(round_: RoundInfo, program_id: int) -> bool:
    return not round_.program_ids or program_id in round_.program_ids


def student_can_enroll(rounds: Iterable[RoundInfo], program_id: int) -> bool:
    """Czy któraś z otwartych tur kolejkowych semestru obejmuje kierunek studenta.

    Tura preferencyjna nie pozwala na bezpośredni zapis ani wypis - w niej student
    tylko zgłasza preferencje, a o miejscach decyduje przydział po zamknięciu tury.
    """
    return any(r.status == "OPEN" and r.mode is RoundMode.QUEUE and covers(r, program_id) for r in rounds)


def can_submit_preferences(round_: RoundInfo, program_id: int) -> bool:
    """Czy student danego kierunku może teraz zgłaszać / zmieniać preferencje w tej turze."""
    return round_.mode is RoundMode.PREFERENCES and round_.status == "OPEN" and covers(round_, program_id)


def scheduled_transition(round_: RoundInfo, now: datetime) -> str | None:
    """Nowy status według harmonogramu (UC17) albo None, gdy bez zmian.

    Worker tylko otwiera zaplanowane i zamyka otwarte tury. Tury zamkniętej
    ręcznie przez dziekanat nie otwiera ponownie, a przedłużenie tury to
    zmiana closes_at.
    """
    if round_.status == "PLANNED" and round_.opens_at <= now < round_.closes_at:
        return "OPEN"
    if round_.status in ("PLANNED", "OPEN") and now >= round_.closes_at:
        return "CLOSED"
    return None
