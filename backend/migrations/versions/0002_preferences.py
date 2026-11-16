"""Etap 5: tury preferencyjne, przydział, wersja harmonogramu (treść w 0002_preferences.sql).

Revision ID: 0002
Revises: 0001
"""
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision = "0002"
down_revision = "0001"
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
    run_script(
        "DROP TABLE allocation_assignment, allocation_result, allocation_run, section_preference, "
        "course_preference;"
        # zapisy z przydziału zostają (liczniki grup muszą się zgadzać), jako decyzje dziekanatu
        "UPDATE enrollment SET source = 'ADMIN' WHERE source = 'ALLOCATION';"
        "ALTER TABLE enrollment DROP CONSTRAINT enrollment_source_check;"
        "ALTER TABLE enrollment ADD CONSTRAINT enrollment_source_check "
        "CHECK (source IN ('DIRECT', 'WAITLIST', 'ADMIN'));"
        "ALTER TABLE section DROP COLUMN schedule_version;"
        "ALTER TABLE enrollment_round DROP CONSTRAINT enrollment_round_budget, "
        "DROP COLUMN points_budget, DROP COLUMN mode;"
    )
