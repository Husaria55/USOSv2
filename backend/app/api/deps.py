from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header

from app.config import settings
from app.db import Session
from app.errors import AppError, Forbidden
from app.security import decode_token
from app.traffic import Gate, Overloaded, RateLimiter, TTLCache


class Unauthorized(AppError):
    status = 401


@dataclass(frozen=True)
class CurrentUser:
    id: int
    role: str


async def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    # Rola z tokenu, bez zapytania do bazy - przy szczycie każde żądanie mniej.
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized("UNAUTHORIZED", "Zaloguj się.")
    try:
        claims = decode_token(authorization.removeprefix("Bearer "))
    except jwt.PyJWTError:
        raise Unauthorized("UNAUTHORIZED", "Sesja wygasła - zaloguj się ponownie.") from None
    return CurrentUser(int(claims["sub"]), claims["role"])


def role(*roles: str):
    async def check(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise Forbidden("FORBIDDEN", "Brak uprawnień.")
        return user
    return check


async def session() -> AsyncIterator:
    async with Session() as s:
        yield s


student = role("STUDENT")
lecturer = role("LECTURER", "ADMIN")
admin = role("ADMIN")

catalog_cache = TTLCache(settings.catalog_cache_ttl_s)
rate_limiter = RateLimiter(settings.rate_limit_per_minute)
write_gate = Gate(settings.enroll_concurrency, settings.enroll_queue_timeout_s)
# Ciężkie odczyty spersonalizowane (status grup dla studenta) - osobny, większy limit,
# żeby przy szczycie nie zagłodziły procesora transakcjom zapisu trzymającym blokady.
read_gate = Gate(settings.read_concurrency, settings.enroll_queue_timeout_s)


@asynccontextmanager
async def write_slot(user_id: int):
    """Limit na studenta + bramka. Odrzucenie przez bramkę nie zużywa limitu."""
    rate_limiter.check(user_id)
    try:
        async with write_gate.slot():
            yield
    except Overloaded:
        rate_limiter.refund(user_id)
        raise
