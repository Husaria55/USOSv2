"""Dane przykładowe.

    python -m app.seed                    # demo: kilka kierunków, kursy z mock-upu, 30 studentów
    python -m app.seed --scale university # 20 kierunków x 1000 studentów, ~600 kursów, ~9000 grup
    python -m app.seed --scale university --open-all   # wszystkie tury otwarte naraz (najgorszy przypadek)

Czyści bazę przed wstawieniem. Wszystkie konta mają hasło "haslo123".
Duże dane idą przez COPY (asyncpg), więc 20 000 studentów to kilka sekund.
"""
import argparse
import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.db import engine
from app.security import hash_password

PASSWORD = "haslo123"
TABLES = ("notification, waitlist_entry, enrollment, completed_course, meeting, section_lecturer, section, "
          "round_program, enrollment_round, room, term, course_prerequisite, course, app_user, program")
BLOCKS = [(time(8, 0), time(9, 30)), (time(9, 45), time(11, 15)), (time(11, 30), time(13, 0)),
          (time(13, 15), time(14, 45)), (time(15, 0), time(16, 30)), (time(16, 45), time(18, 15))]
SLOTS = [(wd, b) for wd in range(1, 6) for b in BLOCKS]          # 30 bloków w tygodniu


class Ids:
    """Kolejne id per tabela (wstawiamy jawne id, sekwencje ustawiamy na końcu)."""
    def __init__(self):
        self.n: dict[str, int] = {}

    def __call__(self, table: str) -> int:
        self.n[table] = self.n.get(table, 0) + 1
        return self.n[table]


class Data:
    def __init__(self):
        self.ids = Ids()
        self.rows: dict[str, list[tuple]] = {}
        self.cols: dict[str, tuple[str, ...]] = {}

    def add(self, table: str, **values) -> int:
        has_id = table not in ("round_program", "section_lecturer", "course_prerequisite", "completed_course")
        if has_id:
            values = {"id": self.ids(table), **values}
        self.cols.setdefault(table, tuple(values))
        self.rows.setdefault(table, []).append(tuple(values.values()))
        return values.get("id", 0)


def build_demo(d: Data, pw: str, now: datetime) -> None:
    programs = {code: d.add("program", code=code, name=name) for code, name in
                [("INF", "Informatyka"), ("MAT", "Matematyka"), ("FIZ", "Fizyka techniczna")]}
    prev = d.add("term", code="2026L", starts_on=date(2026, 2, 23), ends_on=date(2026, 6, 30))
    term = d.add("term", code="2026Z", starts_on=date(2026, 10, 1), ends_on=date(2027, 2, 15))
    d.add("app_user", email="admin@uczelnia.pl", password_hash=pw, full_name="Dziekanat WIEiT", role="ADMIN",
          index_no=None, program_id=None, semester=None, title=None, department=None)
    lect = {}
    for key, title, name in [("zachara", "dr", "Marek Zachara"), ("nowak", "mgr", "Jan Nowak"),
                             ("wisniewska", "mgr", "Katarzyna Wiśniewska"), ("lis", "dr", "Anna Lis"),
                             ("kowal", "prof.", "Piotr Kowal")]:
        lect[key] = d.add("app_user", email=f"{'dr.' if title != 'mgr' else ''}{key}@uczelnia.pl", password_hash=pw,
                          full_name=name, role="LECTURER", index_no=None, program_id=None, semester=None,
                          title=title, department="Katedra Informatyki")
    rooms = {n: d.add("room", building=b, number=n, seats=s) for b, n, s in
             [("C-2", "3.21", 160), ("C-2", "4.27", 16), ("C-2", "4.28", 16), ("D-17", "1.38", 32), ("D-17", "2.41", 32)]}

    courses = {}
    for code, name, ects, desc in [
        ("AM1", "Analiza matematyczna 1", 6, None), ("PO", "Programowanie obiektowe", 5, None),
        ("IO", "Inżynieria oprogramowania", 5, "Procesy wytwarzania, wymagania, UML, testowanie."),
        ("ZIO", "Zaawansowana inżynieria oprogramowania", 4, None), ("BD", "Bazy danych", 5, None),
        ("TS", "Testowanie oprogramowania", 3, None), ("PS", "Programowanie systemowe", 4, None),
        ("AM3", "Analiza matematyczna 3", 5, None), ("FIZ1", "Fizyka 1", 6, None),
    ]:
        courses[code] = d.add("course", code=code, name=name, ects=ects, description=desc)
    for c, r in [("IO", "PO"), ("ZIO", "IO"), ("AM3", "AM1"), ("PS", "PO")]:
        d.add("course_prerequisite", course_id=courses[c], required_course_id=courses[r])

    def section(course, code, kind, cap, lecturer, meetings, wl=50):
        sid = d.add("section", course_id=courses[course], term_id=term, code=code, kind=kind, capacity=cap,
                    enrolled_count=0, waitlist_limit=wl)
        d.add("section_lecturer", section_id=sid, lecturer_id=lect[lecturer])
        for wd, a, b, par, room in meetings:
            d.add("meeting", section_id=sid, room_id=rooms[room], weekday=wd, start_time=time.fromisoformat(a),
                  end_time=time.fromisoformat(b), week_parity=par)

    section("IO", "W01", "LECTURE", 150, "zachara", [(1, "10:00", "11:30", "ALL", "3.21")])
    section("IO", "L03", "LAB", 15, "nowak", [(4, "08:00", "09:30", "ALL", "4.27")])
    section("IO", "L04", "LAB", 15, "nowak", [(4, "09:45", "11:15", "ALL", "4.27")])
    section("IO", "L05", "LAB", 15, "wisniewska", [(5, "12:00", "13:30", "ALL", "4.28")])
    section("ZIO", "W01", "LECTURE", 120, "zachara", [(2, "14:00", "15:30", "ALL", "3.21")])
    section("BD", "W01", "LECTURE", 150, "kowal", [(2, "12:00", "13:30", "ALL", "3.21")])
    section("BD", "L05", "LAB", 15, "wisniewska", [(4, "09:30", "11:00", "ALL", "4.28")])
    section("BD", "L06", "LAB", 15, "wisniewska", [(3, "08:00", "09:30", "ALL", "4.28")])
    section("TS", "C01", "EXERCISE", 4, "lis", [(3, "12:00", "13:30", "EVEN", "1.38")], wl=10)
    section("PS", "L02", "LAB", 15, "nowak", [(1, "12:00", "13:30", "ALL", "4.27")])
    section("AM3", "C02", "EXERCISE", 30, "lis", [(3, "12:00", "13:30", "ODD", "2.41")])
    section("AM3", "W01", "LECTURE", 150, "kowal", [(5, "08:00", "09:30", "ALL", "3.21")])
    section("FIZ1", "W01", "LECTURE", 150, "kowal", [(1, "08:00", "09:30", "ALL", "3.21")])
    section("FIZ1", "C01", "EXERCISE", 30, "lis", [(2, "08:00", "09:30", "ALL", "1.38")])

    names = ["Anna Kowalska", "Bartosz Nowicki", "Celina Wójcik", "Dawid Kamiński", "Ewa Lewandowska",
             "Filip Zieliński", "Gabriela Szymańska", "Hubert Woźniak", "Iga Dąbrowska", "Jakub Kozłowski"]
    rng = random.Random(7)
    for i in range(30):
        prog = ["INF", "INF", "MAT"][i % 3] if i < 27 else "FIZ"
        sid = d.add("app_user", email=f"s{400001 + i}@uczelnia.pl", password_hash=pw,
                    full_name=f"{names[i % 10]}{'' if i < 10 else f' {i // 10 + 1}'}", role="STUDENT",
                    index_no=str(400001 + i), program_id=programs[prog], semester=3, title=None, department=None)
        for code in ("PO", "AM1"):
            grade = Decimal("4.5") if i == 0 else Decimal(rng.choice(["2.0", "3.0", "3.5", "4.0", "4.5", "5.0"]))
            d.add("completed_course", student_id=sid, course_id=courses[code], term_id=prev, grade=grade)

    rounds = [("Tura 1 – INF", "INF", now - timedelta(hours=1), now + timedelta(days=7), "OPEN"),
              ("Tura 1 – MAT", "MAT", now + timedelta(minutes=30), now + timedelta(days=7), "PLANNED"),
              ("Tura 1 – FIZ", "FIZ", now + timedelta(hours=1), now + timedelta(days=7), "PLANNED"),
              ("Tura 2 – wszyscy", None, now + timedelta(days=8), now + timedelta(days=10), "PLANNED")]
    for name, prog, a, b, st in rounds:
        rid = d.add("enrollment_round", term_id=term, name=name, opens_at=a, closes_at=b, status=st)
        if prog:
            d.add("round_program", round_id=rid, program_id=programs[prog])


def build_university(d: Data, pw: str, now: datetime, open_all: bool, programs_n: int = 20,
                     students_per_program: int = 1000, courses_per_program: int = 30) -> None:
    rng = random.Random(42)
    prev = d.add("term", code="2026L", starts_on=date(2026, 2, 23), ends_on=date(2026, 6, 30))
    term = d.add("term", code="2026Z", starts_on=date(2026, 10, 1), ends_on=date(2027, 2, 15))
    d.add("app_user", email="admin@uczelnia.pl", password_hash=pw, full_name="Dziekanat", role="ADMIN",
          index_no=None, program_id=None, semester=None, title=None, department=None)
    halls = [d.add("room", building="A", number=f"H{i:03}", seats=250) for i in range(25)]
    labs = [d.add("room", building="B", number=f"L{i:03}", seats=16) for i in range(300)]
    lecture_n = lab_n = 0
    lecturer_n = 0

    def lecturer() -> int:
        nonlocal lecturer_n
        lecturer_n += 1
        return d.add("app_user", email=f"prowadzacy{lecturer_n}@uczelnia.pl", password_hash=pw,
                     full_name=f"Prowadzący {lecturer_n}", role="LECTURER", index_no=None, program_id=None,
                     semester=None, title="dr", department="Wydział")

    def meeting(section_id, slot_i, room):
        wd, (a, b) = SLOTS[slot_i % len(SLOTS)]
        d.add("meeting", section_id=section_id, room_id=room, weekday=wd, start_time=a, end_time=b, week_parity="ALL")

    index = 100000
    for p in range(programs_n):
        code = f"K{p + 1:02}"
        pid = d.add("program", code=code, name=f"Kierunek {p + 1}")
        course_ids = []
        for c in range(courses_per_program):
            cid = d.add("course", code=f"{code}-{c:02}", name=f"Przedmiot {c} ({code})", ects=rng.choice([3, 4, 5, 6]),
                        description=None)
            course_ids.append(cid)
            if c >= 20:
                d.add("course_prerequisite", course_id=cid, required_course_id=course_ids[c - 10])
            # wykład dla ok. 220 osób, 14 laboratoriów po 15
            sid = d.add("section", course_id=cid, term_id=term, code="W01", kind="LECTURE", capacity=220,
                        enrolled_count=0, waitlist_limit=50)
            d.add("section_lecturer", section_id=sid, lecturer_id=lecturer())
            meeting(sid, lecture_n, halls[lecture_n // len(SLOTS)])
            lecture_n += 1
            lab_lecturers = [lecturer(), lecturer()]
            for k in range(14):
                sid = d.add("section", course_id=cid, term_id=term, code=f"L{k + 1:02}", kind="LAB", capacity=15,
                            enrolled_count=0, waitlist_limit=20)
                d.add("section_lecturer", section_id=sid, lecturer_id=lab_lecturers[k // 7])
                meeting(sid, lab_n, labs[lab_n // len(SLOTS)])
                lab_n += 1
        for s in range(students_per_program):
            index += 1
            sid = d.add("app_user", email=f"s{index}@uczelnia.pl", password_hash=pw, full_name=f"Student {index}",
                        role="STUDENT", index_no=str(index), program_id=pid, semester=rng.randint(1, 7),
                        title=None, department=None)
            for c in range(10):
                if rng.random() < 0.9:
                    d.add("completed_course", student_id=sid, course_id=course_ids[c], term_id=prev,
                          grade=Decimal(rng.choice(["3.0", "3.5", "4.0", "4.5", "5.0"])))
        opens = now - timedelta(minutes=5) if open_all or p == 0 else now + timedelta(minutes=30 * p)
        rid = d.add("enrollment_round", term_id=term, name=f"Tura 1 – {code}", opens_at=opens,
                    closes_at=now + timedelta(days=7), status="OPEN" if open_all or p == 0 else "PLANNED")
        d.add("round_program", round_id=rid, program_id=pid)


async def load(d: Data) -> None:
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        pg = raw.driver_connection
        await pg.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        order = ["program", "term", "app_user", "room", "course", "course_prerequisite", "section",
                 "section_lecturer", "meeting", "completed_course", "enrollment_round", "round_program"]
        for table in order:
            if table in d.rows:
                await pg.copy_records_to_table(table, records=d.rows[table], columns=list(d.cols[table]))
        for table, n in d.ids.n.items():
            await pg.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {n})")
        await pg.execute("ANALYZE")
        await conn.commit()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", choices=["demo", "university"], default="demo")
    ap.add_argument("--open-all", action="store_true", help="university: wszystkie tury otwarte naraz")
    args = ap.parse_args()
    d = Data()
    pw = hash_password(PASSWORD)
    now = datetime.now(timezone.utc)
    if args.scale == "demo":
        build_demo(d, pw, now)
    else:
        build_university(d, pw, now, args.open_all)
    await load(d)
    async with engine.connect() as conn:
        counts = {t: (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar()
                  for t in ("program", "app_user", "course", "section", "meeting", "completed_course")}
    print("Załadowano:", ", ".join(f"{t}={n}" for t, n in counts.items()))
    print(f"Hasło do wszystkich kont: {PASSWORD}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
