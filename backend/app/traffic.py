"""Kontrola ruchu w procesie API.

- TTLCache: krótki cache odczytów katalogu. Równoczesne chybienia tego samego
  klucza czekają na jedno zapytanie (bez "stada" zapytań po wygaśnięciu).
- RateLimiter: limit operacji zapisu na studenta (okno przesuwne).
- Gate: najwyżej N równoczesnych transakcji zapisu na proces. Kolejne czekają
  krótko, a potem dostają 503 z Retry-After, zamiast trzymać połączenia
  i zjadać pulę bazy.

Wszystko działa w obrębie jednego procesu; przy kilku instancjach API limit
na studenta jest przybliżony (N instancji = do N razy więcej), co przy
krótkim oknie i turach rozłożonych na kierunki wystarcza.
"""
import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from app.errors import AppError


class TooManyRequests(AppError):
    status = 429

    def __init__(self, retry_after: float):
        super().__init__("RATE_LIMITED", "Za dużo żądań - spróbuj za chwilę.")
        self.retry_after = retry_after


class Overloaded(AppError):
    status = 503

    def __init__(self, retry_after: float = 1.0):
        super().__init__("OVERLOADED", "System jest teraz mocno obciążony - spróbuj ponownie za chwilę.")
        self.retry_after = retry_after


class TTLCache:
    def __init__(self, ttl: float, max_items: int = 5000):
        self.ttl, self.max_items = ttl, max_items
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._pending: dict[Any, asyncio.Future] = {}

    async def get(self, key, load: Callable[[], Awaitable[Any]]):
        hit = self._data.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        if key in self._pending:
            return await asyncio.shield(self._pending[key])
        fut = asyncio.get_running_loop().create_future()
        self._pending[key] = fut
        try:
            value = await load()
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)
            fut.set_result(value)
            return value
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()  # oznacz jako odebrany, gdy nikt nie czekał
            raise
        finally:
            del self._pending[key]

    def clear(self):
        self._data.clear()


class RateLimiter:
    def __init__(self, per_minute: int, window: float = 60.0):
        self.limit, self.window = per_minute, window
        self._hits: dict[Any, deque[float]] = {}

    def check(self, key) -> None:
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise TooManyRequests(retry_after=round(hits[0] + self.window - now, 1))
        hits.append(now)
        if len(self._hits) > 100_000:                     # sprzątanie nieaktywnych kluczy
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                del self._hits[k]

    def refund(self, key) -> None:
        """Operacja nie została wykonana (np. odrzuciła ją bramka) - nie liczy się do limitu."""
        hits = self._hits.get(key)
        if hits:
            hits.pop()


class Gate:
    def __init__(self, concurrency: int, timeout: float):
        self._sem = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.rejected = 0

    @asynccontextmanager
    async def slot(self):
        try:
            await asyncio.wait_for(self._sem.acquire(), self.timeout)
        except TimeoutError:
            self.rejected += 1
            raise Overloaded() from None
        try:
            yield
        finally:
            self._sem.release()
