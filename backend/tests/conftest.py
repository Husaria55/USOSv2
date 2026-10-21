"""Testy na prawdziwym PostgreSQL (docker compose up -d db).

Baza testowa: USOS_TEST_DATABASE_URL, domyślnie usos_test w kontenerze db.
"""
import os

os.environ.setdefault("USOS_DATABASE_URL", os.environ.get(
    "USOS_TEST_DATABASE_URL", "postgresql+asyncpg://usos:usos@localhost:5433/usos_test"))
os.environ.setdefault("USOS_DB_POOL_SIZE", "40")
os.environ.setdefault("USOS_DB_MAX_OVERFLOW", "20")
os.environ.setdefault("USOS_BCRYPT_ROUNDS", "4")
os.environ.setdefault("USOS_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("USOS_ENROLL_CONCURRENCY", "40")

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import Session, engine

TABLES = ("notification, waitlist_entry, enrollment, completed_course, meeting, section_lecturer, "
          "section, round_program, enrollment_round, room, term, course_prerequisite, course, "
          "app_user, program")


@pytest.fixture(scope="session", autouse=True)
async def schema():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    cfg.attributes["url"] = os.environ["USOS_DATABASE_URL"]
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # alembic (env.py) uruchamia własną pętlę zdarzeń, więc w osobnym wątku
    import asyncio
    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean():
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    from app.services import loaders
    loaders.forget_targets()
    yield


@pytest.fixture
async def db():
    async with Session() as s:
        yield s
