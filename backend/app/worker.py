"""Worker w tle: python -m app.worker

- otwiera i zamyka tury według harmonogramu (UC17) i wygasza listy (UC18),
- wysyła e-maile z outboxa (poza transakcjami zapisu, więc wolny SMTP ich nie blokuje),
- okresowo sprawdza niezmienniki.

Można uruchomić kilka instancji: tury i outbox są brane z SKIP LOCKED.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from email.message import EmailMessage

import aiosmtplib
from sqlalchemy import func, select, update

from app.config import settings
from app.db import Session, run_transaction
from app.models import Notification, Section, User, WaitlistEntry
from app.services import audit, rounds

log = logging.getLogger("worker")

SUBJECTS = {
    "PROMOTED": "Zapisano Cię z listy oczekujących",
    "SKIPPED": "Pominięto Cię na liście oczekujących",
    "CANCELLED": "Anulowano wpis na liście oczekujących",
    "EXPIRED": "Wpis na liście oczekujących wygasł",
}
MAX_ATTEMPTS = 5
AUDIT_EVERY_S = 60


async def schedule_rounds() -> None:
    changes = await run_transaction(lambda s: rounds.apply_schedule(s, datetime.now(timezone.utc)))
    for rid, status in changes:
        log.info("tura %s -> %s", rid, status)


async def expire_stragglers() -> None:
    """Wpisy dopisane tuż przy zamknięciu tury (zapis zaczął się, gdy była jeszcze otwarta)."""
    async with Session() as s:
        term_ids = (await s.execute(select(Section.term_id).distinct()
                                    .join(WaitlistEntry, WaitlistEntry.section_id == Section.id)
                                    .where(WaitlistEntry.status == "WAITING"))).scalars().all()
    for term_id in term_ids:
        n = await run_transaction(lambda s: rounds.expire_uncovered(s, term_id))
        if n:
            log.info("semestr %s: wygaszono %d wpisów na listach", term_id, n)


async def send_outbox(batch: int = 100) -> int:
    async with Session() as s, s.begin():
        rows = (await s.execute(
            select(Notification, User.email).join(User, User.id == Notification.user_id)
            .where(Notification.sent_at.is_(None), Notification.attempts < MAX_ATTEMPTS)
            .order_by(Notification.id).limit(batch).with_for_update(of=Notification, skip_locked=True))).all()
        if not rows:
            return 0
        sent, failed = [], []
        try:
            async with aiosmtplib.SMTP(hostname=settings.smtp_host, port=settings.smtp_port, timeout=10) as smtp:
                for n, email in rows:
                    msg = EmailMessage()
                    msg["From"], msg["To"] = settings.smtp_from, email
                    msg["Subject"] = SUBJECTS.get(n.type, "Powiadomienie z systemu zapisów")
                    msg.set_content(n.payload.get("message", ""))
                    try:
                        await smtp.send_message(msg)
                        sent.append(n.id)
                    except aiosmtplib.SMTPException:
                        failed.append(n.id)
        except (OSError, aiosmtplib.SMTPException) as e:
            log.warning("SMTP niedostępny: %s", e)
            failed = [n.id for n, _ in rows if n.id not in sent]
        if sent:
            await s.execute(update(Notification).where(Notification.id.in_(sent)).values(sent_at=func.now()))
        if failed:
            await s.execute(update(Notification).where(Notification.id.in_(failed))
                            .values(attempts=Notification.attempts + 1))
        return len(sent)


async def run_audit() -> None:
    async with Session() as s:
        for v in await audit.violations(s):
            log.error("NARUSZENIE NIEZMIENNIKA grupa %s: %s", v.section_id, v.problem)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info("worker start")
    last_audit = 0.0
    while True:
        started = time.monotonic()
        for step in (schedule_rounds, expire_stragglers, send_outbox):
            try:
                await step()
            except Exception:
                log.exception("błąd w kroku %s", step.__name__)
        if started - last_audit >= AUDIT_EVERY_S:
            last_audit = started
            try:
                await run_audit()
            except Exception:
                log.exception("błąd audytu")
        await asyncio.sleep(max(0.0, settings.worker_interval_s - (time.monotonic() - started)))


if __name__ == "__main__":
    asyncio.run(main())
