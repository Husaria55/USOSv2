"""Outbox powiadomień: wpis w tej samej transakcji co zmiana, wysyłkę robi worker."""
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.loaders import pg

MESSAGES = {
    "PROMOTED": "Zwolniło się miejsce w grupie {label} - zostałeś zapisany z listy oczekujących.",
    "SKIPPED": "Nie zapisano Cię z listy oczekujących do grupy {label}: {reason}",
    "CANCELLED": "Wpis na liście oczekujących grupy {label} anulowano, bo masz już grupę tego typu z tego przedmiotu.",
    "EXPIRED": "Tura zapisów się zakończyła - wpis na liście oczekujących grupy {label} wygasł.",
    "ADMIN_ENROLLED": "Dziekanat zapisał Cię do grupy {label}.",
    "ADMIN_DROPPED": "Dziekanat wypisał Cię z grupy {label}.",
}


def payload(type_: str, label: str, **extra) -> dict:
    return {"label": label, "message": MESSAGES[type_].format(label=label, **extra), **extra}


async def notify_many(session: AsyncSession, rows: list[tuple[int, str, dict]]) -> None:
    """rows: (id użytkownika, typ, payload)."""
    if rows:
        await (await pg(session)).executemany(
            "INSERT INTO notification (user_id, type, payload) VALUES ($1, $2, $3::jsonb)",
            [(u, t, json.dumps(p, ensure_ascii=False)) for u, t, p in rows])


async def notify(session: AsyncSession, user_id: int, type_: str, label: str, **extra) -> None:
    await notify_many(session, [(user_id, type_, payload(type_, label, **extra))])
