"""Schemat początkowy (treść w 0001_initial.sql).

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def run_script(sql: str) -> None:
    # Skrypt ma wiele poleceń, a asyncpg wykonuje takie tylko bez przygotowania
    # zapytania, więc idzie bezpośrednio przez połączenie sterownika.
    driver = op.get_bind().connection.driver_connection
    await_only(driver.execute(sql))


def upgrade() -> None:
    run_script(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    run_script("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
