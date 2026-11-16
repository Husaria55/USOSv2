"""Prototyp PreferenceAllocator – przydział sekcji według preferencji (etap 5).

Prototyp klasy domenowej z projektu (README §6.3): czysty Python, bez bazy danych, żeby zmierzyć
jakość i czas algorytmu, zanim zostanie wpięty w AllocationService. Nazwy odpowiadają modelom
z otrzymanego projektu: ScheduleSlot (tabela schedules) z metodą overlaps_with, sekcja należy do
jednego kursu, student może mieć jedną sekcję kursu w semestrze (is_already_enrolled_in_course).

Model
-----
Zgłoszenie (CoursePreference): student, kurs, waga (punkty z puli semestru, suma <= points_budget)
i akceptowane sekcje kursu w kolejności (SectionPreference.rank). Użyteczność przydziału:

    u = waga * max(0.5, 1 - 0.1 * (ranga - 1))      # 1. wybór 100%, 2. wybór 90% ...

Cel: max sum(u) przy ograniczeniach takich samych jak w EnrollmentRuleEngine.check_rules:
  (1) przydzielonych do sekcji <= wolnych miejsc (capacity - liczba ENROLLED),
  (2) brak kolizji (ScheduleSlot.overlaps_with) między przydzielonymi sekcjami studenta
      i z jego dotychczasowym planem,
  (3) wymagania wstępne zaliczone (COMPLETED),
  (4) nie więcej niż jedna sekcja kursu (kurs, z którego student już ma sekcję, odpada).

Algorytm
--------
1. Wykonalność: dla zgłoszenia lista sekcji bez kolizji z planem (w kolejności rang),
   zgłoszenia niewykonalne dostają powód od razu.
2. Zachłannie: zgłoszenia malejąco po wadze, remis – los studenta z ziarnem (seed).
3. Poprawa lokalna: dla nieprzydzielonego zgłoszenia przenosimy kogoś z pełnej sekcji do jego
   innej akceptowanej sekcji (łańcuch do 2 przeniesień), a gdy się nie da – zwalniamy przydział
   o najmniejszej użyteczności; zwalniamy też kolidujące własne przydziały studenta; zwolnionym
   przydzielamy, co się mieści. Ruch zostaje tylko, gdy suma u rośnie (inaczej wycofanie).
"""
from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import time

RANK_STEP = 0.1
MIN_RANK_FACTOR = 0.5
MAX_PASSES = 10
CHAIN_DEPTH = 2
MAX_MOVES = 12
EPS = 1e-9
_DAY_MIN = 24 * 60


# --- modele (odpowiedniki z projektu) ----------------------------------------------

@dataclass(frozen=True)
class ScheduleSlot:
    """Termin zajęć (schedules). Przedziały [start_time, end_time): 8:00-9:30 i 9:30-11:00 nie kolidują."""
    day_of_week: int
    start_time: time
    end_time: time

    def overlaps_with(self, other: "ScheduleSlot") -> bool:
        return (self.day_of_week == other.day_of_week
                and self.start_time < other.end_time and other.start_time < self.end_time)


def slots_overlap(a: Iterable[ScheduleSlot], b: Iterable[ScheduleSlot]) -> bool:
    b = list(b)
    return any(x.overlaps_with(y) for x in a for y in b)


@dataclass(frozen=True)
class SectionOffer:
    """Sekcja w puli przydziału: kurs, terminy, wolne miejsca."""
    section_id: int
    course_id: int
    label: str
    slots: tuple[ScheduleSlot, ...]
    free_seats: int


@dataclass(frozen=True)
class EnrolledSection:
    """Sekcja, na którą student jest już zapisany (ENROLLED) w semestrze."""
    section_id: int
    course_id: int
    label: str
    slots: tuple[ScheduleSlot, ...]


@dataclass(frozen=True)
class CourseRequest:
    """CoursePreference + jej SectionPreference (sekcje w kolejności rang)."""
    student_id: int
    course_id: int
    course_code: str
    weight: int
    section_ids: tuple[int, ...]

    @property
    def key(self) -> tuple[int, int]:
        return self.student_id, self.course_id


@dataclass(frozen=True)
class StudentProfile:
    student_id: int
    plan: tuple[EnrolledSection, ...]
    completed_course_ids: frozenset[int]


@dataclass(frozen=True)
class Rejection:
    code: str          # PREREQUISITES | ALREADY_ENROLLED | CONFLICT | NO_SECTIONS | FULL | OWN_CONFLICT
    message: str


@dataclass(frozen=True)
class Assignment:
    student_id: int
    course_id: int
    weight: int
    section_id: int
    utility: float


@dataclass(frozen=True)
class Unassigned:
    student_id: int
    course_id: int
    weight: int
    reason: Rejection


@dataclass(frozen=True)
class AllocationResult:
    assignments: tuple[Assignment, ...]
    unassigned: tuple[Unassigned, ...]
    total_utility: float
    upper_bound: float
    improvements: int
    seed: int


# --- krok 1: wykonalność ------------------------------------------------------------

def rank_factor(rank: int) -> float:
    return max(MIN_RANK_FACTOR, 1.0 - RANK_STEP * (rank - 1))


def _mask(slots: Iterable[ScheduleSlot]) -> int:
    """Terminy jako maska bitowa minut tygodnia - kolizja = jedno AND (solver sprawdza je miliony razy)."""
    m = 0
    for s in slots:
        a = (s.day_of_week - 1) * _DAY_MIN + s.start_time.hour * 60 + s.start_time.minute
        b = (s.day_of_week - 1) * _DAY_MIN + s.end_time.hour * 60 + s.end_time.minute + (1 if s.end_time.second else 0)
        m |= ((1 << (b - a)) - 1) << a
    return m


@dataclass(frozen=True)
class Option:
    section_id: int
    rank: int
    utility: float
    mask: int


def options_for(request: CourseRequest, profile: StudentProfile, offers: Mapping[int, SectionOffer],
                prerequisites: Mapping[int, str]) -> list[Option] | Rejection:
    """Sekcje możliwe dla studenta (w kolejności rang) albo powód odmowy - reguły check_rules."""
    missing = sorted(code for cid, code in prerequisites.items() if cid not in profile.completed_course_ids)
    if missing:
        return Rejection("PREREQUISITES", "Brak zaliczenia: " + ", ".join(missing) + ".")
    if any(p.course_id == request.course_id for p in profile.plan):
        return Rejection("ALREADY_ENROLLED", f"Masz już sekcję kursu {request.course_code}.")
    options, clashes = [], set()
    for rank, sid in enumerate(request.section_ids, start=1):
        offer = offers.get(sid)
        if offer is None or offer.course_id != request.course_id:
            continue
        hit = [p.label for p in profile.plan if slots_overlap(p.slots, offer.slots)]
        if hit:
            clashes.update(hit)
            continue
        options.append(Option(sid, rank, request.weight * rank_factor(rank), _mask(offer.slots)))
    if options:
        return options
    if clashes:
        return Rejection("CONFLICT", "Wybrane sekcje kolidują z Twoim planem: " + ", ".join(sorted(clashes)) + ".")
    return Rejection("NO_SECTIONS", f"Żadna z wybranych sekcji kursu {request.course_code} nie jest dostępna.")


# --- kroki 2-3 -------------------------------------------------------------------------

Key = tuple[int, int]


@dataclass
class _State:
    free: dict[int, int]
    chosen: dict[Key, Option] = field(default_factory=dict)
    by_student: dict[int, set[Key]] = field(default_factory=lambda: defaultdict(set))
    busy: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    holders: dict[int, set[Key]] = field(default_factory=lambda: defaultdict(set))
    journal: list[tuple[str, Key, Option]] = field(default_factory=list)
    total: float = 0.0

    def place(self, key: Key, opt: Option) -> None:
        self.total += opt.utility
        self.chosen[key] = opt
        self.by_student[key[0]].add(key)
        self.busy[key[0]] |= opt.mask
        self.free[opt.section_id] -= 1
        self.holders[opt.section_id].add(key)
        self.journal.append(("place", key, opt))

    def remove(self, key: Key) -> Option:
        opt = self.chosen.pop(key)
        self.total -= opt.utility
        mine = self.by_student[key[0]]
        mine.discard(key)
        mask = 0
        for k in mine:
            mask |= self.chosen[k].mask
        self.busy[key[0]] = mask
        self.free[opt.section_id] += 1
        self.holders[opt.section_id].discard(key)
        self.journal.append(("remove", key, opt))
        return opt

    def mark(self) -> int:
        return len(self.journal)

    def rollback(self, mark: int) -> None:
        while len(self.journal) > mark:
            op, key, opt = self.journal.pop()
            self.remove(key) if op == "place" else self.place(key, opt)
            self.journal.pop()

    def own_conflicts(self, key: Key, opt: Option) -> list[Key]:
        if not self.busy[key[0]] & opt.mask:
            return []
        return [k for k in self.by_student[key[0]] if k != key and self.chosen[k].mask & opt.mask]

    def fits(self, key: Key, opt: Option) -> bool:
        return not self.busy[key[0]] & opt.mask and self.free[opt.section_id] > 0


def allocate(requests: Sequence[CourseRequest], profiles: Mapping[int, StudentProfile],
             offers: Mapping[int, SectionOffer], prerequisites: Mapping[int, Mapping[int, str]], *,
             seed: int, improve: bool = True) -> AllocationResult:
    by_key = {r.key: r for r in requests}
    if len(by_key) != len(requests):
        raise ValueError("Zdublowane zgłoszenie (student, kurs).")
    options: dict[Key, list[Option]] = {}
    rejected: dict[Key, Rejection] = {}
    for r in requests:
        got = options_for(r, profiles[r.student_id], offers, prerequisites.get(r.course_id, {}))
        (rejected if isinstance(got, Rejection) else options)[r.key] = got

    rng = random.Random(seed)
    lottery = {st: rng.random() for st in sorted({r.student_id for r in requests})}
    order = sorted(options, key=lambda k: (-by_key[k].weight, lottery[k[0]], k[1]))
    keys_by_student: dict[int, list[Key]] = defaultdict(list)
    for k in order:
        keys_by_student[k[0]].append(k)

    state = _State(free={sid: max(0, o.free_seats) for sid, o in offers.items()})
    for key in order:
        for opt in options[key]:
            if state.fits(key, opt):
                state.place(key, opt)
                break

    improvements = 0
    if improve:
        sections_of = {k: {o.section_id for o in opts} for k, opts in options.items()}
        candidates = [k for k in order if k not in state.chosen]
        for _ in range(MAX_PASSES):
            changed_sections, changed_students = set(), set()
            for key in candidates:
                if key in state.chosen:
                    continue
                mark = state.mark()
                if _try_insert(state, key, options, keys_by_student):
                    improvements += 1
                    for _, k, opt in state.journal[mark:]:
                        changed_sections.add(opt.section_id)
                        changed_students.add(k[0])
                state.journal.clear()
            if not changed_sections:
                break
            candidates = [k for k in order if k not in state.chosen
                          and (k[0] in changed_students or sections_of[k] & changed_sections)]

    assignments, unassigned = [], []
    for r in requests:
        if r.key in state.chosen:
            o = state.chosen[r.key]
            assignments.append(Assignment(r.student_id, r.course_id, r.weight, o.section_id, o.utility))
        else:
            reason = rejected.get(r.key) or _why_not(state, r, options[r.key], by_key)
            unassigned.append(Unassigned(r.student_id, r.course_id, r.weight, reason))
    return AllocationResult(tuple(assignments), tuple(unassigned), round(sum(a.utility for a in assignments), 6),
                            float(sum(by_key[k].weight for k in options)), improvements, seed)


def _try_insert(state: _State, key: Key, options, keys_by_student) -> bool:
    for opt in options[key]:
        mark, before = state.mark(), state.total
        evicted = state.own_conflicts(key, opt)
        for k in evicted:
            state.remove(k)
        if _make_room(state, opt.section_id, {key[0]}, options, CHAIN_DEPTH, evicted) and state.fits(key, opt):
            state.place(key, opt)
            _refill(state, evicted, options, keys_by_student, protect=key[0])
            if state.total > before + EPS:
                return True
        state.rollback(mark)
    return False


def _make_room(state: _State, section_id: int, forbidden: set[int], options, depth: int, evicted: list[Key],
               blocked: frozenset[int] = frozenset()) -> bool:
    if state.free[section_id] > 0:
        return True
    blocked = blocked | {section_id}
    if depth > 0:
        moves = sorted(((state.chosen[h].utility - alt.utility, h, alt) for h in state.holders[section_id]
                        if h[0] not in forbidden for alt in options[h]
                        if alt is not state.chosen[h] and alt.section_id not in blocked),
                       key=lambda m: (m[0], m[1], m[2].section_id))
        for _, holder, alt in moves[:MAX_MOVES]:
            mark, n = state.mark(), len(evicted)
            state.remove(holder)
            if (not state.busy[holder[0]] & alt.mask
                    and _make_room(state, alt.section_id, forbidden | {holder[0]}, options, depth - 1, evicted, blocked)
                    and state.fits(holder, alt)):
                state.place(holder, alt)
                return True
            state.rollback(mark)
            del evicted[n:]
    others = [h for h in state.holders[section_id] if h[0] not in forbidden]
    if not others:
        return False
    victim = min(others, key=lambda h: (state.chosen[h].utility, h))
    state.remove(victim)
    evicted.append(victim)
    return True


def _refill(state: _State, evicted, options, keys_by_student, protect: int, rounds: int = 2) -> None:
    pending, touched = sorted(set(evicted)), {k[0] for k in evicted}
    for _ in range(rounds):
        more: list[Key] = []
        for k in pending:
            if k in state.chosen:
                continue
            for alt in options[k]:
                if state.busy[k[0]] & alt.mask:
                    continue
                mark, before, out = state.mark(), state.total, []
                if _make_room(state, alt.section_id, {k[0], protect}, options, 1, out) and state.fits(k, alt):
                    state.place(k, alt)
                    if state.total > before + EPS:
                        more += out
                        break
                state.rollback(mark)
        touched.update(k[0] for k in more)
        pending = sorted(set(more))
        if not pending:
            break
    for st in sorted(touched):
        for k in keys_by_student.get(st, ()):
            if k not in state.chosen:
                for alt in options[k]:
                    if state.fits(k, alt):
                        state.place(k, alt)
                        break


def _why_not(state: _State, request: CourseRequest, opts: list[Option], by_key) -> Rejection:
    for opt in opts:
        if state.free[opt.section_id] > 0:
            codes = sorted(by_key[k].course_code for k in state.own_conflicts(request.key, opt))
            return Rejection("OWN_CONFLICT", "Wolne sekcje kolidują z kursem przydzielonym z wyższym priorytetem: "
                             + ", ".join(codes) + ".")
    return Rejection("FULL", "Brak miejsc w wybranych sekcjach - zajęły je zgłoszenia z wyższą wagą "
                             "albo wygrane w losowaniu.")


# --- niezależna kontrola wyniku ------------------------------------------------------

def verify(result: AllocationResult, requests: Sequence[CourseRequest], profiles: Mapping[int, StudentProfile],
           offers: Mapping[int, SectionOffer], prerequisites: Mapping[int, Mapping[int, str]]) -> list[str]:
    """Ograniczenia (1)-(4) sprawdzone niezależnie od algorytmu (overlaps_with, bez masek)."""
    problems = []
    by_key = {r.key: r for r in requests}
    used: dict[int, int] = defaultdict(int)
    taken: dict[int, list[SectionOffer]] = defaultdict(list)
    for a in result.assignments:
        r, offer, profile = by_key.get((a.student_id, a.course_id)), offers[a.section_id], profiles[a.student_id]
        if r is None or a.section_id not in r.section_ids or offer.course_id != a.course_id:
            problems.append(f"student {a.student_id}: sekcja {offer.label} spoza zgłoszenia")
        if set(prerequisites.get(a.course_id, {})) - profile.completed_course_ids:
            problems.append(f"student {a.student_id}: brak wymagań do kursu {a.course_id}")
        if any(p.course_id == a.course_id for p in profile.plan):
            problems.append(f"student {a.student_id}: druga sekcja kursu {a.course_id}")
        if any(slots_overlap(p.slots, offer.slots) for p in profile.plan):
            problems.append(f"student {a.student_id}: {offer.label} koliduje z planem")
        if any(slots_overlap(o.slots, offer.slots) for o in taken[a.student_id]):
            problems.append(f"student {a.student_id}: {offer.label} koliduje z innym przydziałem")
        taken[a.student_id].append(offer)
        used[a.section_id] += 1
    problems += [f"sekcja {offers[s].label}: {n} > {offers[s].free_seats}" for s, n in used.items()
                 if n > offers[s].free_seats]
    return problems
