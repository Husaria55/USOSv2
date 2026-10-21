"""Generuje diagram ER (TikZ) - etap 3, schemat z backend/migrations/versions/0001_initial.sql.

    python3 er.py            # zapisuje er.tex
    tectonic er.tex          # er.pdf (wektorowo, do prezentacji)

Linie łączą konkretną kolumnę FK z kolumną PK; trasy są ortogonalne
i prowadzone w odstępach między kolumnami tabel.
"""
from itertools import permutations
from pathlib import Path

ROW = 0.42      # wysokość wiersza [cm]
HEAD = 0.50     # wysokość nagłówka
VGAP = 0.55     # odstęp między tabelami w kolumnie
GAP = 1.2       # odstęp między kolumnami
CH = 0.128       # szacowana szerokość znaku [cm]

# Kolor linii = kolor tabeli docelowej (tej z PK).
COLORS = {
    "app_user": "5B6B7F", "program": "1F5EFF", "section": "D9480F", "course": "2B8A3E",
    "term": "7048E8", "enrollment": "C2255C", "room": "8D6E63", "enrollment_round": "0B8A7A",
}

# kolumna: (nazwa, typ, flagi)  flagi: P = PK, F = FK, U = UNIQUE, N = NULL dozwolony
T = {
    "app_user": [("id", "bigserial", "P"), ("email", "varchar(255)", "U"),
                 ("password_hash", "varchar(255)", ""), ("full_name", "varchar(200)", ""),
                 ("role", "varchar(16)", ""), ("created_at", "timestamptz", ""),
                 ("index_no", "varchar(10)", "UN"), ("program_id", "bigint", "FN"),
                 ("semester", "smallint", "N"), ("title", "varchar(50)", "N"),
                 ("department", "varchar(100)", "N")],
    "notification": [("id", "bigserial", "P"), ("user_id", "bigint", "F"),
                     ("type", "varchar(32)", ""), ("payload", "jsonb", ""),
                     ("created_at", "timestamptz", ""), ("sent_at", "timestamptz", "N"),
                     ("read_at", "timestamptz", "N"), ("attempts", "smallint", "")],
    "program": [("id", "bigserial", "P"), ("code", "varchar(20)", "U"), ("name", "varchar(200)", "")],
    "section_lecturer": [("section_id", "bigint", "PF"), ("lecturer_id", "bigint", "PF")],
    "enrollment": [("id", "bigserial", "P"), ("student_id", "bigint", "F"),
                   ("section_id", "bigint", "F"), ("status", "varchar(16)", ""),
                   ("source", "varchar(16)", ""), ("enrolled_at", "timestamptz", ""),
                   ("dropped_at", "timestamptz", "N"), ("created_by", "bigint", "FN"),
                   ("dropped_by", "bigint", "FN")],
    "waitlist_entry": [("id", "bigserial", "P"), ("student_id", "bigint", "F"),
                       ("section_id", "bigint", "F"), ("status", "varchar(16)", ""),
                       ("created_at", "timestamptz", ""), ("resolved_at", "timestamptz", "N"),
                       ("skip_reason", "varchar(255)", "N"), ("enrollment_id", "bigint", "FUN")],
    "completed_course": [("student_id", "bigint", "PF"), ("course_id", "bigint", "PF"),
                         ("term_id", "bigint", "PF"), ("grade", "numeric(2,1)", ""),
                         ("passed", "boolean", "")],
    "round_program": [("round_id", "bigint", "PF"), ("program_id", "bigint", "PF")],
    "enrollment_round": [("id", "bigserial", "P"), ("term_id", "bigint", "F"),
                         ("name", "varchar(50)", ""), ("opens_at", "timestamptz", ""),
                         ("closes_at", "timestamptz", ""), ("status", "varchar(16)", "")],
    "section": [("id", "bigserial", "P"), ("course_id", "bigint", "F"),
                ("term_id", "bigint", "F"), ("code", "varchar(10)", ""),
                ("kind", "varchar(16)", ""), ("capacity", "smallint", ""),
                ("enrolled_count", "smallint", ""), ("waitlist_limit", "smallint", "")],
    "term": [("id", "bigserial", "P"), ("code", "varchar(10)", "U"),
             ("starts_on", "date", ""), ("ends_on", "date", "")],
    "course": [("id", "bigserial", "P"), ("code", "varchar(20)", "U"),
               ("name", "varchar(200)", ""), ("ects", "smallint", ""),
               ("description", "text", "N")],
    "meeting": [("id", "bigserial", "P"), ("section_id", "bigint", "F"),
                ("room_id", "bigint", "FN"), ("weekday", "smallint", ""),
                ("start_time", "time", ""), ("end_time", "time", ""),
                ("week_parity", "varchar(4)", "")],
    "room": [("id", "bigserial", "P"), ("building", "varchar(20)", ""),
             ("number", "varchar(20)", ""), ("seats", "smallint", "")],
    "course_prerequisite": [("course_id", "bigint", "PF"), ("required_course_id", "bigint", "PF")],
}

# Kolumny układu: lista (tabela, przesunięcie w dół przed tabelą [cm]).
COLS = [
    [("app_user", 0.9), ("notification", 0.9)],
    [("program", 0.0), ("round_program", 0.0), ("section_lecturer", 0.0), ("enrollment", 0.0),
     ("waitlist_entry", 0.0), ("completed_course", 0.0)],
    [("enrollment_round", 0.6), ("section", 0.6), ("term", 0.6), ("course", 0.6)],
    [("meeting", 3.0), ("room", 0.0), ("course_prerequisite", 6.0)],
]

# Relacje: (tabela.kolumna_FK, tabela.kolumna_PK, odstęp, krotność FK, krotność PK)
# odstęp k = przestrzeń na lewo od kolumny układu k (0 = lewy margines, 4 = prawy).
# krotność: "many0" (0..n), "many1" (1..n), "zero1" (0..1), "one" (dokładnie 1)
REL = [
    ("notification.user_id", "app_user.id", 0, "many0", "one"),
    ("app_user.program_id", "program.id", 1, "many0", "zero1"),
    ("section_lecturer.lecturer_id", "app_user.id", 1, "many0", "one"),
    ("enrollment.student_id", "app_user.id", 1, "many0", "one"),
    ("enrollment.created_by", "app_user.id", 1, "many0", "zero1"),
    ("enrollment.dropped_by", "app_user.id", 1, "many0", "zero1"),
    ("waitlist_entry.student_id", "app_user.id", 1, "many0", "one"),
    ("completed_course.student_id", "app_user.id", 1, "many0", "one"),
    ("round_program.program_id", "program.id", 2, "many0", "one"),
    ("round_program.round_id", "enrollment_round.id", 2, "many0", "one"),
    ("waitlist_entry.enrollment_id", "enrollment.id", 2, "zero1", "zero1"),
    ("section_lecturer.section_id", "section.id", 2, "many0", "one"),
    ("enrollment.section_id", "section.id", 2, "many0", "one"),
    ("waitlist_entry.section_id", "section.id", 2, "many0", "one"),
    ("completed_course.term_id", "term.id", 2, "many0", "one"),
    ("completed_course.course_id", "course.id", 2, "many0", "one"),
    ("enrollment_round.term_id", "term.id", 3, "many0", "one"),
    ("section.term_id", "term.id", 3, "many0", "one"),
    ("section.course_id", "course.id", 3, "many0", "one"),
    ("meeting.section_id", "section.id", 3, "many1", "one"),
    ("course_prerequisite.course_id", "course.id", 3, "many0", "one"),
    ("course_prerequisite.required_course_id", "course.id", 3, "many0", "one"),
    ("meeting.room_id", "room.id", 4, "many0", "zero1"),
]


def tex(s):
    return s.replace("_", r"\_")


def layout():
    pos, colx, colw = {}, [], []
    x = 0.0
    for col in COLS:
        w = max(max(len(n) + len(t) for n, t, _ in T[name]) * CH + 1.0 for name, _ in col)
        w = max(w, max(len(name) * CH * 1.1 + 0.4 for name, _ in col))
        y = 0.0
        for name, dy in col:
            y -= dy
            pos[name] = (x, y, w)
            y -= HEAD + ROW * len(T[name]) + VGAP
        colx.append(x)
        colw.append(w)
        x += w + GAP
    return pos, colx, colw


def row_y(pos, table, col):
    x, y, w = pos[table]
    i = [n for n, _, _ in T[table]].index(col)
    return y - HEAD - ROW * (i + 0.5)


def gap_bounds(k, colx, colw):
    left = colx[k - 1] + colw[k - 1] if k > 0 else colx[0] - 0.7
    right = colx[k] if k < len(colx) else left + 0.7
    return left, right


def endpoints(pos, colx, colw):
    """Dla każdej relacji: (x1, y1, x2, y2, przedział [lo, hi] na trasę pionową)."""
    eps = []
    for fk, pk, k, *_ in REL:
        ft, fc = fk.split(".")
        pt, pc = pk.split(".")
        lo, hi = gap_bounds(k, colx, colw)
        def side(t):
            x, _, w = pos[t]
            return x + w if abs(x + w - lo) < 1e-6 else x
        eps.append((side(ft), row_y(pos, ft, fc), side(pt), row_y(pos, pt, pc), lo, hi))
    return eps


def crossings(segs):
    """segs: lista (xa, ya, xc, xb, yb) – poziomo ya od xa do xc, pionowo xc, poziomo yb do xb."""
    n = 0
    for i, (xa, ya, xc, xb, yb) in enumerate(segs):
        for j, (xa2, ya2, xc2, xb2, yb2) in enumerate(segs):
            if i == j:
                continue
            lo, hi = sorted((ya2, yb2))
            for y, x0, x1 in ((ya, xa, xc), (yb, xc, xb)):
                a, b = sorted((x0, x1))
                if a < xc2 < b and lo < y < hi:
                    n += 1
    return n


def assign_channels(eps):
    """Wybiera kolejność tras pionowych w każdym odstępie, minimalizując przecięcia."""
    xc = [None] * len(REL)
    for k in {r[2] for r in REL}:
        idx = [i for i, r in enumerate(REL) if r[2] == k]
        lo, hi = eps[idx[0]][4], eps[idx[0]][5]
        m = 0.28
        slots = [lo + m + (hi - lo - 2 * m) * s / max(len(idx) - 1, 1) for s in range(len(idx))]
        if len(idx) == 1:
            slots = [(lo + hi) / 2]
        best = None
        for perm in permutations(range(len(idx))):
            segs = [(eps[i][0], eps[i][1], slots[p], eps[i][2], eps[i][3]) for i, p in zip(idx, perm)]
            # przy remisie wolimy krótsze poziome odcinki
            score = (crossings(segs), sum(abs(s[2] - s[0]) + abs(s[3] - s[2]) for s in segs))
            if best is None or score < best[0]:
                best = (score, perm)
        for i, p in zip(idx, best[1]):
            xc[i] = slots[p]
    return xc


def marker(x, y, d, kind, color):
    """Znacznik krotności przy krawędzi tabeli; d = +1 gdy linia wychodzi w prawo."""
    out = []
    a, b = 0.13, 0.30  # odległości kresek od krawędzi tabeli
    bar = lambda t: out.append(f"\\draw[{color}] ({x + d * t:.3f},{y - 0.11:.3f}) -- ({x + d * t:.3f},{y + 0.11:.3f});")
    if kind.startswith("many"):
        out.append(f"\\draw[{color}] ({x + d * a:.3f},{y:.3f}) -- ({x:.3f},{y + 0.12:.3f})"
                   f" ({x + d * a:.3f},{y:.3f}) -- ({x:.3f},{y - 0.12:.3f});")
        if kind == "many1":
            bar(b)
        else:
            out.append(f"\\draw[{color}, fill=white] ({x + d * (b + 0.05):.3f},{y:.3f}) circle (0.055);")
    elif kind == "one":
        bar(a); bar(a + 0.08)
    elif kind == "zero1":
        bar(a)
        out.append(f"\\draw[{color}, fill=white] ({x + d * (a + 0.17):.3f},{y:.3f}) circle (0.055);")
    return out


def main():
    pos, colx, colw = layout()
    eps = endpoints(pos, colx, colw)
    xc = assign_channels(eps)
    L = [r"""% Wygenerowane przez er.py – nie edytować ręcznie.
\documentclass[tikz,border=4pt]{standalone}
\usepackage[sfdefault]{FiraSans}
\usetikzlibrary{arrows.meta}
\definecolor{head}{HTML}{23373B}
\definecolor{grid}{HTML}{C9CED6}
\definecolor{typ}{HTML}{8A929C}
\definecolor{pk}{HTML}{B7791F}
"""]
    for t, c in COLORS.items():
        L.append(f"\\definecolor{{c-{t}}}{{HTML}}{{{c}}}\n")
    L.append(r"\begin{document}" "\n" r"\begin{tikzpicture}[font=\fontsize{7.5}{9}\selectfont]" "\n")

    fk_target = {r[0]: r[1].split(".")[0] for r in REL}
    for name, (x, y, w) in pos.items():
        h = HEAD + ROW * len(T[name])
        L.append(f"\\fill[white] ({x:.3f},{y:.3f}) rectangle ({x + w:.3f},{y - h:.3f});\n")
        L.append(f"\\fill[head] ({x:.3f},{y:.3f}) rectangle ({x + w:.3f},{y - HEAD:.3f});\n")
        L.append(f"\\node[white, font=\\fontsize{{8}}{{9}}\\selectfont\\bfseries] at ({x + w / 2:.3f},{y - HEAD / 2:.3f}) {{{tex(name)}}};\n")
        for i, (col, typ, fl) in enumerate(T[name]):
            ry = y - HEAD - ROW * (i + 0.5)
            if i:
                L.append(f"\\draw[grid, line width=0.3pt] ({x:.3f},{ry + ROW / 2:.3f}) -- ({x + w:.3f},{ry + ROW / 2:.3f});\n")
            tags = []
            if "P" in fl:
                tags.append(r"\textcolor{pk}{PK}")
            if "F" in fl:
                tags.append(f"\\textcolor{{c-{fk_target[name + '.' + col]}}}{{FK}}")
            if "U" in fl and "F" not in fl:
                tags.append(r"\textcolor{typ}{UQ}")
            tag = "\\,".join(tags)
            label = tex(col)
            if "P" in fl:
                label = f"\\textbf{{{label}}}"
            if "N" in fl:
                label = f"\\textcolor{{typ}}{{\\itshape {label}}}"
            L.append(f"\\node[anchor=west, inner sep=0, font=\\fontsize{{5}}{{6}}\\selectfont\\bfseries] at ({x + 0.08:.3f},{ry:.3f}) {{{tag}}};\n")
            L.append(f"\\node[anchor=west, inner sep=0] at ({x + 0.66:.3f},{ry:.3f}) {{{label}}};\n")
            L.append(f"\\node[anchor=east, inner sep=0, text=typ] at ({x + w - 0.08:.3f},{ry:.3f}) {{{typ}}};\n")
        L.append(f"\\draw[head, line width=0.6pt] ({x:.3f},{y:.3f}) rectangle ({x + w:.3f},{y - h:.3f});\n")

    for (fk, pk, k, fkind, pkind), (x1, y1, x2, y2, lo, hi), c in zip(REL, eps, xc):
        color = "c-" + pk.split(".")[0]
        L.append(f"\\draw[{color}, line width=0.8pt, rounded corners=2pt] ({x1:.3f},{y1:.3f}) -- ({c:.3f},{y1:.3f}) -- ({c:.3f},{y2:.3f}) -- ({x2:.3f},{y2:.3f});\n")
        style = f"{color}, line width=0.8pt"
        L.extend(s + "\n" for s in marker(x1, y1, 1 if c > x1 else -1, fkind, style))
        L.extend(s + "\n" for s in marker(x2, y2, 1 if c > x2 else -1, pkind, style))

    # legenda pod tabelami w pierwszej kolumnie
    lx = colx[0]
    ly = min(pos[t][1] - HEAD - ROW * len(T[t]) for t, _ in COLS[0]) - 0.9
    legend = [
        r"\textcolor{pk}{\bfseries PK} klucz główny",
        r"\bfseries FK\mdseries{} klucz obcy (kolor = tabela docelowa)",
        r"\textcolor{typ}{\bfseries UQ} wartość unikalna",
        r"\textcolor{typ}{\itshape kursywa} -- NULL dozwolony",
    ]
    for i, s in enumerate(legend):
        L.append(f"\\node[anchor=west, inner sep=0, font=\\fontsize{{6.5}}{{8}}\\selectfont] at ({lx:.3f},{ly - i * 0.36:.3f}) {{{s}}};\n")

    L.append(r"\end{tikzpicture}" "\n" r"\end{document}" "\n")
    Path(__file__).with_name("er.tex").write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
