"""Tury zapisów: kto może się zapisywać i kiedy worker zmienia status tury."""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RoundInfo:
    id: int
    status: str
    opens_at: datetime
    closes_at: datetime
    program_ids: frozenset[int]  # pusty zbiór = tura dla wszystkich kierunków


def covers(round_: RoundInfo, program_id: int) -> bool:
    return not round_.program_ids or program_id in round_.program_ids


def student_can_enroll(rounds: Iterable[RoundInfo], program_id: int) -> bool:
    """Czy któraś z otwartych tur semestru obejmuje kierunek studenta."""
    return any(r.status == "OPEN" and covers(r, program_id) for r in rounds)


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
