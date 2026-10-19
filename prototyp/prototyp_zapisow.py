"""Prototyp najbardziej ryzykownych elementów systemu zapisów na zajęcia.

Sprawdza:
  1. wyścig o ostatnie miejsca w chwili otwarcia zapisów (wersja naiwna vs bezpieczna),
  2. wymagania wstępne (zaliczone przedmioty),
     oraz regułę "jedna grupa danego typu na przedmiot" i limit listy oczekujących (scen. 5),
  3. wykrywanie kolizji w planie: dzień, godziny, tygodnie parzyste/nieparzyste,
  4. listę oczekujących: automatyczny zapis po zwolnieniu miejsca, pomijanie osób,
     które w międzyczasie mają kolizję, równoczesne wypisy, zwiększenie limitu.

Tylko biblioteka standardowa (sqlite3 + threading). W docelowym systemie
(PostgreSQL) rolę BEGIN IMMEDIATE pełni SELECT ... FOR UPDATE na wierszu grupy.

Uruchomienie:  python3 prototyp_zapisow.py
"""

import os
import sqlite3
import tempfile
import threading
import time

SCHEMA = """
CREATE TABLE student (
    id       INTEGER PRIMARY KEY,
    index_no TEXT NOT NULL UNIQUE
);

CREATE TABLE course (
    id   INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE
);

CREATE TABLE course_prerequisite (
    course_id          INTEGER NOT NULL REFERENCES course(id),
    required_course_id INTEGER NOT NULL REFERENCES course(id),
    PRIMARY KEY (course_id, required_course_id)
);

CREATE TABLE completed_course (
    student_id INTEGER NOT NULL REFERENCES student(id),
    course_id  INTEGER NOT NULL REFERENCES course(id),
    passed     INTEGER NOT NULL,
    PRIMARY KEY (student_id, course_id)
);

CREATE TABLE section (
    id             INTEGER PRIMARY KEY,
    course_id      INTEGER NOT NULL REFERENCES course(id),
    code           TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'LAB', -- LECTURE | EXERCISE | LAB | SEMINAR
    capacity       INTEGER NOT NULL,
    waitlist_limit INTEGER NOT NULL DEFAULT 50,
    enrolled_count INTEGER NOT NULL DEFAULT 0,
    CHECK (enrolled_count <= capacity)
);

CREATE TABLE meeting (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES section(id),
    weekday     INTEGER NOT NULL,           -- 1 = poniedziałek
    start_time  TEXT NOT NULL,              -- 'HH:MM'
    end_time    TEXT NOT NULL,
    week_parity TEXT NOT NULL DEFAULT 'ALL' -- ALL | ODD | EVEN
);

CREATE TABLE enrollment (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES student(id),
    section_id INTEGER NOT NULL REFERENCES section(id),
    status     TEXT NOT NULL,               -- ENROLLED | DROPPED
    source     TEXT NOT NULL                -- DIRECT | WAITLIST | ADMIN
);
CREATE UNIQUE INDEX one_active_enrollment
    ON enrollment(student_id, section_id) WHERE status = 'ENROLLED';

CREATE TABLE waitlist_entry (
    id            INTEGER PRIMARY KEY,      -- rosnące id = kolejność na liście
    student_id    INTEGER NOT NULL REFERENCES student(id),
    section_id    INTEGER NOT NULL REFERENCES section(id),
    status        TEXT NOT NULL,            -- WAITING | PROMOTED | SKIPPED | CANCELLED
    skip_reason   TEXT,
    enrollment_id INTEGER REFERENCES enrollment(id)
);
CREATE UNIQUE INDEX one_waiting_entry
    ON waitlist_entry(student_id, section_id) WHERE status = 'WAITING';

CREATE TABLE notification (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL,
    type       TEXT NOT NULL,
    message    TEXT NOT NULL
);
"""


class EnrollmentError(Exception):
    pass


class SectionFull(EnrollmentError):
    pass


class MissingPrerequisite(EnrollmentError):
    pass


class ScheduleConflict(EnrollmentError):
    pass


class AlreadyInCourse(EnrollmentError):
    pass


def connect(path):
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_db():
    path = os.path.join(tempfile.mkdtemp(prefix="zapisy-"), "zapisy.db")
    conn = connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return path, conn


def add(conn, sql, *args):
    return conn.execute(sql, args).lastrowid


def add_section(conn, course_id, code, capacity, meetings, kind="LAB", waitlist_limit=50):
    """meetings: lista krotek (dzień, od, do[, parzystość])."""
    sid = add(conn, "INSERT INTO section(course_id, code, kind, capacity, waitlist_limit) "
                    "VALUES (?, ?, ?, ?, ?)", course_id, code, kind, capacity, waitlist_limit)
    for m in meetings:
        day, start, end, parity = (*m, "ALL")[:4]
        add(conn, "INSERT INTO meeting(section_id, weekday, start_time, end_time, week_parity) "
                  "VALUES (?, ?, ?, ?, ?)", sid, day, start, end, parity)
    return sid


# --- reguły ------------------------------------------------------------------

def missing_prerequisites(conn, student_id, section_id):
    """Kody przedmiotów wymaganych przez kurs grupy, których student nie zaliczył."""
    rows = conn.execute(
        "SELECT c.code FROM section s "
        "JOIN course_prerequisite p ON p.course_id = s.course_id "
        "JOIN course c ON c.id = p.required_course_id "
        "WHERE s.id = ? AND NOT EXISTS ("
        "  SELECT 1 FROM completed_course cc "
        "  WHERE cc.student_id = ? AND cc.course_id = p.required_course_id AND cc.passed = 1)",
        (section_id, student_id),
    ).fetchall()
    return [r[0] for r in rows]


def find_conflicts(conn, student_id, section_id):
    """Grupy w planie studenta, których terminy nachodzą na terminy nowej grupy.

    Dwa terminy kolidują, gdy:
      - są tego samego dnia tygodnia,
      - przedziały godzin się przecinają: start1 < end2 AND start2 < end1
        (zajęcia 8:00-9:30 i 9:30-11:00 NIE kolidują),
      - tygodnie się pokrywają: ALL koliduje ze wszystkim, ODD z ODD, EVEN z EVEN.
    """
    rows = conn.execute(
        "SELECT DISTINCT s.code FROM enrollment e "
        "JOIN meeting mine ON mine.section_id = e.section_id "
        "JOIN meeting new  ON new.section_id = ? "
        "JOIN section s    ON s.id = e.section_id "
        "WHERE e.student_id = ? AND e.status = 'ENROLLED' AND e.section_id <> ? "
        "  AND mine.weekday = new.weekday "
        "  AND mine.start_time < new.end_time AND new.start_time < mine.end_time "
        "  AND (mine.week_parity = 'ALL' OR new.week_parity = 'ALL' "
        "       OR mine.week_parity = new.week_parity)",
        (section_id, student_id, section_id),
    ).fetchall()
    return [r[0] for r in rows]


def same_course_and_kind(conn, student_id, section_id):
    """Grupa tego samego przedmiotu i typu, do której student już jest zapisany.

    Student może mieć wykład i laboratorium z IO, ale nie dwa laboratoria z IO.
    """
    row = conn.execute(
        "SELECT other.code FROM enrollment e "
        "JOIN section other ON other.id = e.section_id "
        "JOIN section new   ON new.id = ? "
        "WHERE e.student_id = ? AND e.status = 'ENROLLED' AND other.id <> new.id "
        "  AND other.course_id = new.course_id AND other.kind = new.kind",
        (section_id, student_id),
    ).fetchone()
    return row[0] if row else None


def check_rules(conn, student_id, section_id):
    taken = same_course_and_kind(conn, student_id, section_id)
    if taken:
        raise AlreadyInCourse(f"już zapisany do grupy {taken} tego przedmiotu")
    missing = missing_prerequisites(conn, student_id, section_id)
    if missing:
        raise MissingPrerequisite(f"brak zaliczenia: {', '.join(missing)}")
    conflicts = find_conflicts(conn, student_id, section_id)
    if conflicts:
        raise ScheduleConflict(f"kolizja z: {', '.join(conflicts)}")


def notify(conn, student_id, type_, message):
    # W systemie docelowym: tabela notification jako outbox, worker wysyła e-maile.
    conn.execute("INSERT INTO notification(student_id, type, message) VALUES (?, ?, ?)",
                 (student_id, type_, message))


# --- operacje ----------------------------------------------------------------

def _take_seat(conn, section_id):
    """Atomowe zajęcie miejsca: sprawdzenie limitu i inkrementacja to jeden UPDATE."""
    cur = conn.execute(
        "UPDATE section SET enrolled_count = enrolled_count + 1 "
        "WHERE id = ? AND enrolled_count < capacity",
        (section_id,),
    )
    return cur.rowcount == 1


def enroll(conn, student_id, section_id, join_waitlist=True):
    """UC2. Zwraca 'ENROLLED' albo 'WAITLISTED'."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        check_rules(conn, student_id, section_id)
        if _take_seat(conn, section_id):
            add(conn, "INSERT INTO enrollment(student_id, section_id, status, source) "
                      "VALUES (?, ?, 'ENROLLED', 'DIRECT')", student_id, section_id)
            result = "ENROLLED"
        elif join_waitlist:  # UC5 rozszerza UC2 w punkcie "brak wolnych miejsc"
            waiting, limit = conn.execute(
                "SELECT (SELECT COUNT(*) FROM waitlist_entry WHERE section_id = s.id "
                "        AND status = 'WAITING'), s.waitlist_limit FROM section s WHERE s.id = ?",
                (section_id,),
            ).fetchone()
            if waiting >= limit:
                raise SectionFull(f"grupa {section_id}: brak miejsc i pełna lista oczekujących")
            add(conn, "INSERT INTO waitlist_entry(student_id, section_id, status) "
                      "VALUES (?, ?, 'WAITING')", student_id, section_id)
            result = "WAITLISTED"
        else:
            raise SectionFull(f"grupa {section_id}: brak miejsc")
        conn.execute("COMMIT")
        return result
    except Exception:
        conn.execute("ROLLBACK")
        raise


def naive_enroll(conn, student_id, section_id):
    """CELOWO BŁĘDNY: odczyt liczby zapisanych, a potem osobny zapis (check-then-act)."""
    count, capacity = conn.execute(
        "SELECT enrolled_count, capacity FROM section WHERE id = ?", (section_id,)
    ).fetchone()
    if count >= capacity:
        raise SectionFull(f"grupa {section_id}: brak miejsc")
    time.sleep(0.01)  # okno wyścigu
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO enrollment(student_id, section_id, status, source) "
                 "VALUES (?, ?, 'ENROLLED', 'DIRECT')", (student_id, section_id))
    # Nadpisanie licznika wartością policzoną wcześniej (lost update), bez CHECK-a
    # licznik zostaje zaniżony, a zapisanych jest więcej niż miejsc.
    conn.execute("UPDATE section SET enrolled_count = ? WHERE id = ?", (count + 1, section_id))
    conn.execute("COMMIT")


def promote_from_waitlist(conn, section_id):
    """UC9. Wywoływane WEWNĄTRZ transakcji, która zwolniła miejsce lub zwiększyła limit.

    Bierze oczekujących po kolei. Każdego sprawdza ponownie (od dopisania do listy
    mógł się zapisać na kolidujące zajęcia). Kogo nie da się zapisać, oznacza jako
    SKIPPED z powodem. Kończy, gdy brak miejsc albo pusta lista. Zwraca listę
    (student_id, wynik).
    """
    results = []
    while True:
        entry = conn.execute(
            "SELECT id, student_id FROM waitlist_entry "
            "WHERE section_id = ? AND status = 'WAITING' ORDER BY id LIMIT 1",
            (section_id,),
        ).fetchone()
        if entry is None:
            return results
        entry_id, student_id = entry
        try:
            check_rules(conn, student_id, section_id)
        except EnrollmentError as e:
            conn.execute("UPDATE waitlist_entry SET status = 'SKIPPED', skip_reason = ? WHERE id = ?",
                         (str(e), entry_id))
            notify(conn, student_id, "SKIPPED", f"Nie zapisano z listy oczekujących: {e}")
            results.append((student_id, f"SKIPPED ({e})"))
            continue
        if not _take_seat(conn, section_id):
            return results
        enr_id = add(conn, "INSERT INTO enrollment(student_id, section_id, status, source) "
                           "VALUES (?, ?, 'ENROLLED', 'WAITLIST')", student_id, section_id)
        conn.execute("UPDATE waitlist_entry SET status = 'PROMOTED', enrollment_id = ? WHERE id = ?",
                     (enr_id, entry_id))
        notify(conn, student_id, "PROMOTED", "Zwolniło się miejsce - zostałeś zapisany.")
        results.append((student_id, "PROMOTED"))


def drop(conn, student_id, section_id):
    """UC6: wypis + automatyczny awans z listy w tej samej transakcji."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE enrollment SET status = 'DROPPED' "
            "WHERE student_id = ? AND section_id = ? AND status = 'ENROLLED'",
            (student_id, section_id),
        )
        if cur.rowcount == 0:
            raise EnrollmentError("student nie jest zapisany do tej grupy")
        conn.execute("UPDATE section SET enrolled_count = enrolled_count - 1 WHERE id = ?", (section_id,))
        promoted = promote_from_waitlist(conn, section_id)
        conn.execute("COMMIT")
        return promoted
    except Exception:
        conn.execute("ROLLBACK")
        raise


def change_capacity(conn, section_id, new_capacity):
    """UC13: zmiana limitu; przy zwiększeniu od razu awans z listy."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE section SET capacity = ? WHERE id = ?", (new_capacity, section_id))
        promoted = promote_from_waitlist(conn, section_id)
        conn.execute("COMMIT")
        return promoted
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --- niezmienniki ------------------------------------------------------------

def check_invariants(conn):
    bad_count = conn.execute(
        "SELECT s.id, s.enrolled_count, COUNT(e.id) FROM section s "
        "LEFT JOIN enrollment e ON e.section_id = s.id AND e.status = 'ENROLLED' "
        "GROUP BY s.id HAVING s.enrolled_count <> COUNT(e.id)"
    ).fetchall()
    assert not bad_count, f"licznik != liczba zapisanych: {bad_count}"
    over = conn.execute("SELECT id FROM section WHERE enrolled_count > capacity").fetchall()
    assert not over, f"przekroczony limit: {over}"
    idle_waitlist = conn.execute(
        "SELECT DISTINCT s.id FROM section s JOIN waitlist_entry w ON w.section_id = s.id "
        "WHERE w.status = 'WAITING' AND s.enrolled_count < s.capacity"
    ).fetchall()
    assert not idle_waitlist, f"wolne miejsca, a ktoś czeka na liście: {idle_waitlist}"
    both = conn.execute(
        "SELECT w.student_id, w.section_id FROM waitlist_entry w JOIN enrollment e "
        "ON e.student_id = w.student_id AND e.section_id = w.section_id "
        "WHERE w.status = 'WAITING' AND e.status = 'ENROLLED'"
    ).fetchall()
    assert not both, f"student jednocześnie zapisany i oczekujący: {both}"


# --- scenariusze -------------------------------------------------------------

def make_students(conn, n, start=1):
    return [add(conn, "INSERT INTO student(index_no) VALUES (?)", f"{400000 + i}")
            for i in range(start, start + n)]


def run_concurrently(path, fn, args_list):
    """Uruchamia fn(conn, *args) dla każdego zestawu argumentów w osobnym wątku, naraz."""
    results: list = [None] * len(args_list)
    barrier = threading.Barrier(len(args_list))

    def worker(i, args):
        conn = connect(path)
        barrier.wait()
        try:
            results[i] = fn(conn, *args)
        except EnrollmentError as e:
            results[i] = e
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i, a)) for i, a in enumerate(args_list)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def scenario_race(fn, label):
    path, conn = create_db()
    course = add(conn, "INSERT INTO course(code) VALUES ('IO')")
    lab = add_section(conn, course, "L01", 10, [(1, "08:00", "09:30")])
    students = make_students(conn, 30)
    run_concurrently(path, fn, [(s, lab) for s in students])
    enrolled = conn.execute(
        "SELECT COUNT(*) FROM enrollment WHERE section_id = ? AND status = 'ENROLLED'", (lab,)
    ).fetchone()[0]
    counter = conn.execute("SELECT enrolled_count FROM section WHERE id = ?", (lab,)).fetchone()[0]
    print(f"[{label}] zapisanych: {enrolled} / 10 miejsc, licznik w grupie: {counter}")
    return path, conn, enrolled


def main():
    print("== 1. Otwarcie zapisów: 30 studentów jednocześnie, grupa na 10 miejsc ==")
    _, _, enrolled = scenario_race(lambda c, s, sec: naive_enroll(c, s, sec), "naiwny ")
    if enrolled > 10:
        print("    -> wersja naiwna zapisała więcej osób niż jest miejsc (overbooking)")
    path, conn, enrolled = scenario_race(lambda c, s, sec: enroll(c, s, sec), "bezpieczny")
    waiting = conn.execute("SELECT COUNT(*) FROM waitlist_entry WHERE status = 'WAITING'").fetchone()[0]
    assert enrolled == 10 and waiting == 20
    check_invariants(conn)
    print(f"    -> 10 zapisanych, {waiting} na liście oczekujących, niezmienniki OK")

    print("\n== 2. Wymagania wstępne ==")
    path, conn = create_db()
    am1 = add(conn, "INSERT INTO course(code) VALUES ('AM1')")
    am2 = add(conn, "INSERT INTO course(code) VALUES ('AM2')")
    add(conn, "INSERT INTO course_prerequisite VALUES (?, ?)", am2, am1)
    am2_c1 = add_section(conn, am2, "C01", 30, [(2, "10:00", "11:30")])
    ania, bartek = make_students(conn, 2)
    add(conn, "INSERT INTO completed_course VALUES (?, ?, 1)", ania, am1)
    add(conn, "INSERT INTO completed_course VALUES (?, ?, 0)", bartek, am1)  # niezaliczony
    print(f"    Ania (zaliczyła AM1):     {enroll(conn, ania, am2_c1)}")
    try:
        enroll(conn, bartek, am2_c1)
    except MissingPrerequisite as e:
        print(f"    Bartek (nie zaliczył AM1): odrzucono - {e}")

    print("\n== 3. Wykrywanie kolizji w planie ==")
    path, conn = create_db()
    c = add(conn, "INSERT INTO course(code) VALUES ('X')")
    base = add_section(conn, c, "BAZA", 30, [(1, "10:00", "11:30"), (3, "12:00", "13:30", "ODD")])
    cases = [
        ("pon 11:00-12:30 (nachodzi)",            [(1, "11:00", "12:30")],        True),
        ("pon 11:30-13:00 (styka się końcem)",    [(1, "11:30", "13:00")],        False),
        ("wt  10:00-11:30 (inny dzień)",          [(2, "10:00", "11:30")],        False),
        ("śr  12:00-13:30 tyg. parzyste",         [(3, "12:00", "13:30", "EVEN")], False),
        ("śr  13:00-14:30 co tydzień",            [(3, "13:00", "14:30")],        True),
    ]
    stud = make_students(conn, 1)[0]
    enroll(conn, stud, base)
    print("    plan studenta: pon 10:00-11:30, śr 12:00-13:30 (tyg. nieparzyste)")
    for i, (label, meetings, expected) in enumerate(cases):
        sec = add_section(conn, c, f"G{i}", 30, meetings)
        found = find_conflicts(conn, stud, sec)
        assert bool(found) == expected, label
        print(f"    {label:<38} -> {'KOLIZJA' if found else 'ok'}")

    print("\n== 4. Lista oczekujących ==")
    path, conn = create_db()
    io = add(conn, "INSERT INTO course(code) VALUES ('IO')")
    other = add(conn, "INSERT INTO course(code) VALUES ('BD')")
    lab = add_section(conn, io, "L01", 2, [(4, "08:00", "09:30")])
    bd = add_section(conn, other, "L05", 30, [(4, "08:30", "10:00")])  # koliduje z L01
    s1, s2, w1, w2, w3, w4 = make_students(conn, 6)
    enroll(conn, s1, lab)
    enroll(conn, s2, lab)
    for w in (w1, w2, w3, w4):
        assert enroll(conn, w, lab) == "WAITLISTED"
    print(f"    grupa L01 pełna (2/2), oczekują kolejno: {w1}, {w2}, {w3}, {w4}")
    enroll(conn, w1, bd)  # pierwszy oczekujący zapisał się w międzyczasie na kolidujące zajęcia
    print(f"    student {w1} zapisał się tymczasem na BD L05 (kolizja z L01)")
    print(f"    student {s1} wypisuje się -> {drop(conn, s1, lab)}")
    check_invariants(conn)

    print(f"    dziekanat zwiększa limit do 3 -> {change_capacity(conn, lab, 3)}")
    check_invariants(conn)

    print("    dwóch zapisanych wypisuje się w tej samej chwili:")
    holders = [r[0] for r in conn.execute(
        "SELECT student_id FROM enrollment WHERE section_id = ? AND status = 'ENROLLED' LIMIT 2", (lab,))]
    extra = make_students(conn, 3, start=100)
    for s in extra:
        enroll(conn, s, lab)
    first_two = [r[0] for r in conn.execute(
        "SELECT student_id FROM waitlist_entry WHERE section_id = ? AND status = 'WAITING' "
        "ORDER BY id LIMIT 2", (lab,))]
    results = run_concurrently(path, drop, [(h, lab) for h in holders])
    promoted = [p for r in results for p in r]
    assert len(promoted) == 2 and len({p[0] for p in promoted}) == 2
    # Kolejność zapisów z listy (id zapisu) musi odpowiadać kolejności na liście (id wpisu).
    by_enrollment = [r[0] for r in conn.execute(
        "SELECT id FROM waitlist_entry WHERE section_id = ? AND status = 'PROMOTED' "
        "ORDER BY enrollment_id", (lab,))]
    assert by_enrollment == sorted(by_enrollment), "awans z pominięciem kolejności"
    assert sorted(p[0] for p in promoted) == sorted(first_two)
    print(f"    -> awansowani: {sorted(p[0] for p in promoted)} (pierwsi dwaj z listy: {first_two})")
    check_invariants(conn)
    print("    -> każde zwolnione miejsce zajęte dokładnie raz, kolejność listy zachowana")

    notes = conn.execute("SELECT student_id, type, message FROM notification ORDER BY id").fetchall()
    print("    powiadomienia (outbox):")
    for n in notes:
        print(f"      {n[0]}: {n[1]:<8} {n[2]}")

    print("\n== 5. Jedna grupa danego typu na przedmiot, limit listy oczekujących ==")
    path, conn = create_db()
    io = add(conn, "INSERT INTO course(code) VALUES ('IO')")
    w01 = add_section(conn, io, "W01", 150, [(1, "10:00", "11:30")], kind="LECTURE")
    l03 = add_section(conn, io, "L03", 1, [(4, "08:00", "09:30")], waitlist_limit=1)
    l05 = add_section(conn, io, "L05", 15, [(5, "12:00", "13:30")])
    ola, piotr, kuba = make_students(conn, 3)
    enroll(conn, ola, l03)
    print(f"    Piotr do pełnej L03:          {enroll(conn, piotr, l03)}")
    try:
        enroll(conn, kuba, l03)
    except SectionFull as e:
        print(f"    Kuba do pełnej L03:           odrzucono - {e}")
    print(f"    Piotr na wykład W01:          {enroll(conn, piotr, w01)}  (inny typ zajęć - wolno)")
    print(f"    Piotr do L05 (czeka na L03):  {enroll(conn, piotr, l05)}")
    try:
        enroll(conn, piotr, l03, join_waitlist=False)
    except AlreadyInCourse as e:
        print(f"    Piotr ponownie do L03:        odrzucono - {e}")
    print(f"    Ola wypisuje się z L03 ->     {drop(conn, ola, l03)}")
    assert conn.execute("SELECT status FROM waitlist_entry WHERE student_id = ?", (piotr,)).fetchone()[0] == "SKIPPED"
    check_invariants(conn)
    print("    -> Piotr nie dostał drugiego laboratorium z IO; L03 ma wolne miejsce i pustą listę")

    print("\nWszystkie niezmienniki spełnione.")


if __name__ == "__main__":
    main()
