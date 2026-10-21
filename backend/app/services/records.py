"""StudentRecordsService: import zaliczonych przedmiotów (UC15)."""
import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompletedCourse, Course, Term, User

GRADES = {Decimal(g) for g in ("2.0", "3.0", "3.5", "4.0", "4.5", "5.0")}


@dataclass
class ImportResult:
    imported: int = 0
    errors: list[str] = field(default_factory=list)


async def import_grades(session: AsyncSession, data: str) -> ImportResult:
    """CSV z nagłówkiem: index_no,course_code,term_code,grade.

    Błędne wiersze są pomijane i raportowane; ponowny import tego samego
    wiersza nadpisuje ocenę (poprawka oceny w systemie źródłowym).
    """
    result = ImportResult()
    rows = list(csv.DictReader(io.StringIO(data.strip())))
    students = dict((await session.execute(select(User.index_no, User.id).where(
        User.index_no.in_({r.get("index_no", "").strip() for r in rows})))).all())
    courses = dict((await session.execute(select(Course.code, Course.id).where(
        Course.code.in_({r.get("course_code", "").strip() for r in rows})))).all())
    terms = dict((await session.execute(select(Term.code, Term.id))).all())

    values = {}
    for line, r in enumerate(rows, start=2):
        idx, ccode, tcode = (r.get(k, "").strip() for k in ("index_no", "course_code", "term_code"))
        try:
            grade = Decimal(r.get("grade", "").strip().replace(",", "."))
        except InvalidOperation:
            grade = None
        problems = [msg for ok, msg in (
            (idx in students, f"nieznany indeks {idx!r}"),
            (ccode in courses, f"nieznany kurs {ccode!r}"),
            (tcode in terms, f"nieznany semestr {tcode!r}"),
            (grade in GRADES, f"niepoprawna ocena {r.get('grade')!r}"),
        ) if not ok]
        if problems:
            result.errors.append(f"wiersz {line}: " + ", ".join(problems))
            continue
        key = (students[idx], courses[ccode], terms[tcode])
        values[key] = grade
    if values:
        stmt = insert(CompletedCourse).values(
            [{"student_id": s, "course_id": c, "term_id": t, "grade": g} for (s, c, t), g in values.items()])
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["student_id", "course_id", "term_id"], set_={"grade": stmt.excluded.grade}))
    result.imported = len(values)
    return result
