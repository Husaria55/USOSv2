import asyncio
import random

import asyncpg
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)
Session = async_sessionmaker(engine, expire_on_commit=False)

T = TypeVar("T")

# 55P03 lock_not_available (FOR UPDATE NOWAIT przy awansie z listy),
# 40P01 deadlock_detected, 40001 serialization_failure.
RETRYABLE_SQLSTATES = {"55P03", "40P01", "40001"}


def sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    for e in (exc, orig, getattr(orig, "__cause__", None)):
        code = getattr(e, "sqlstate", None) or getattr(e, "pgcode", None)
        if code:
            return code
    return None


class TooManyRetries(Exception):
    pass


# Liczniki ponowień według SQLSTATE (eksponowane w /api/health jako metryka).
retry_stats: dict[str, int] = {}


async def run_transaction(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Wykonuje fn w osobnej transakcji, ponawiając ją przy konfliktach blokad.

    fn może zostać wywołana kilka razy, więc nie może mieć skutków ubocznych poza
    bazą (powiadomienia idą przez outbox w tej samej transakcji).
    """
    for attempt in range(settings.tx_max_retries):
        try:
            async with Session() as session, session.begin():
                return await fn(session)
        except (DBAPIError, asyncpg.PostgresError) as e:
            code = sqlstate(e)
            if code not in RETRYABLE_SQLSTATES:
                raise
            retry_stats[code] = retry_stats.get(code, 0) + 1
            await asyncio.sleep(random.uniform(0.005, 0.02) * 2**attempt)
    raise TooManyRetries()
