"""Przydział miejsc według preferencji (tura PREFERENCES). Czysta logika, bez bazy.

Model
-----
Student zgłasza przedmioty z wagą (punkty z puli tury, suma <= budżet) i dla każdego
przedmiotu akceptowane grupy w kolejności - osobno dla każdego typu zajęć (wykład,
laboratorium...). Zgłoszenie jest spełnione, gdy student dostaje po jednej grupie
z każdego wybranego typu (wszystko albo nic: sam wykład bez laboratorium nic nie daje).

Użyteczność spełnionego zgłoszenia:

    u = waga * średnia(współczynnik_rangi(grupa) dla grup w kombinacji)
    współczynnik_rangi(r) = max(0.5, 1 - 0.1 * (r - 1))     # 1. wybór 1.0, 2. wybór 0.9 ...

Waga decyduje o tym, CZY student dostanie przedmiot, ranga - KTÓRĄ grupę.

Cel: maksymalizacja sumy u przy ograniczeniach (te same reguły co zapis w kolejce):
  (1) przydzielonych do grupy <= wolnych miejsc,
  (2) brak kolizji terminów: między przydzielonymi grupami studenta i z jego planem,
  (3) wymagania wstępne zaliczone,
  (4) jedna grupa danego typu z przedmiotu (typ, z którego student ma już grupę, jest pomijany).
Problem z kolizjami jest NP-trudny (zawiera maksymalny zbiór niezależny), dlatego:

Algorytm
--------
1. Wykonalność: dla zgłoszenia lista kombinacji grup (po jednej z każdego typu) bez
   kolizji z planem i między sobą, malejąco po użyteczności. Brak kombinacji = odmowa
   z powodem (wymagania, kolizja, ...), zanim zacznie się podział miejsc.
2. Zachłannie: zgłoszenia malejąco po wadze; remis rozstrzyga losowanie z ziarnem
   (każdy student dostaje jeden los na cały przebieg - kolejność sprawiedliwa
   i odtwarzalna). Każde zgłoszenie dostaje najlepszą kombinację, która się mieści.
3. Poprawa lokalna, dopóki rośnie suma u. Dla nieprzydzielonego zgłoszenia r
   i jego kombinacji c:
   - kolizja c z innym przydziałem tego samego studenta: zwalniamy go,
   - pełna grupa w c: jedną osobę z tej grupy (h) przenosimy do innej z jej
     akceptowanych kombinacji (gorsza ranga, ale nadal ją akceptowała), a jeśli tam też
     brak miejsca - kolejną osobę dalej (łańcuch przeniesień do długości 2); gdy się nie
     da - zwalniamy przydział o najmniejszej użyteczności,
   - po wstawieniu r zwolnieni studenci dostają, co się mieści, z pozostałych zgłoszeń
     (np. h traci przedmiot, ale zmieści inny, który wcześniej z nim kolidował; zwolniony
     własny przedmiot wraca w innej kombinacji).
   Ruch zostaje tylko, gdy suma u rośnie (inaczej wycofanie z dziennika zmian), więc
   pętla się kończy.
   Jakość względem rozwiązania dokładnego: tests/test_allocation_domain.py.
"""
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import product

from app.domain.enrollment_rules import PlanEntry
from app.domain.schedule import Slot, any_overlap, conflicting_sections

RANK_STEP = 0.1
MIN_RANK_FACTOR = 0.5
MAX_OPTIONS = 256           # kombinacji na zgłoszenie (z limitami walidacji jest ich zwykle kilkanaście)
MAX_PASSES = 10             # przebiegi poprawy lokalnej
CHAIN_DEPTH = 2             # długość łańcucha przeniesień przy zwalnianiu miejsca
MAX_MOVES = 12              # kandydatów do przeniesienia sprawdzanych na każdym poziomie łańcucha
EPS = 1e-9


def rank_factor(rank: int) -> float:
    return max(MIN_RANK_FACTOR, 1.0 - RANK_STEP * (rank - 1))


def utility(weight: int, ranks: Iterable[int]) -> float:
    ranks = list(ranks)
    return weight * sum(rank_factor(r) for r in ranks) / len(ranks)


# --- dane wejściowe -------------------------------------------------------------

@dataclass(frozen=True)
class Offer:
    """Grupa w puli przydziału."""
    section_id: int
    course_id: int
    kind: str
    label: str
    slots: tuple[Slot, ...]
    free_seats: int


@dataclass(frozen=True)
class CourseRequest:
    student_id: int
    course_id: int
    course_code: str
    weight: int
    choices: Mapping[str, tuple[int, ...]]   # typ zajęć -> id grup w kolejności (rank 1 = pierwsza)

    @property
    def key(self) -> tuple[int, int]:
        return self.student_id, self.course_id


@dataclass(frozen=True)
class StudentProfile:
    student_id: int
    plan: tuple[PlanEntry, ...]               # zapisy z semestru tury (z wcześniejszych tur, dziekanat)
    passed_course_ids: frozenset[int]


# --- wynik ----------------------------------------------------------------------

@dataclass(frozen=True)
class Option:
    """Kombinacja grup spełniająca zgłoszenie (po jednej z każdego potrzebnego typu)."""
    section_ids: tuple[int, ...]
    ranks: tuple[int, ...]
    utility: float
    slots: tuple[Slot, ...]
    mask: int = 0               # time_mask(slots): kolizja dwóch kombinacji = mask & mask != 0


_DAY_MIN = 24 * 60
_WEEK_BITS = 7 * _DAY_MIN


def time_mask(slots: Iterable[Slot]) -> int:
    """Terminy jako maska bitowa: bit = minuta tygodnia, osobno tygodnie nieparzyste i parzyste.

    Ta sama reguła co schedule.slots_overlap (przedziały [start, end), ALL koliduje z ODD
    i EVEN, ODD nie koliduje z EVEN), ale sprawdzenie kolizji to jedna operacja AND - solver
    sprawdza kolizje miliony razy. Koniec zaokrąglany w górę do pełnej minuty (bezpiecznie:
    co najwyżej fałszywa kolizja, nigdy przeoczona; wynik i tak sprawdza dokładnie verify).
    """
    mask = 0
    for s in slots:
        a = (s.weekday - 1) * _DAY_MIN + s.start.hour * 60 + s.start.minute
        b = (s.weekday - 1) * _DAY_MIN + s.end.hour * 60 + s.end.minute + (1 if s.end.second else 0)
        block = ((1 << (b - a)) - 1) << a
        if s.parity in ("ALL", "ODD"):
            mask |= block
        if s.parity in ("ALL", "EVEN"):
            mask |= block << _WEEK_BITS
    return mask


@dataclass(frozen=True)
class Rejection:
    code: str
    message: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assignment:
    student_id: int
    course_id: int
    weight: int
    section_ids: tuple[int, ...]
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
    upper_bound: float          # suma wag zgłoszeń wykonalnych - lepiej się nie da
    improvements: int           # ruchy poprawy lokalnej
    seed: int

    @property
    def requests(self) -> int:
        return len(self.assignments) + len(self.unassigned)


# --- krok 1: wykonalność ----------------------------------------------------------

def options_for(request: CourseRequest, profile: StudentProfile, offers: Mapping[int, Offer],
                prerequisites: Mapping[int, str]) -> list[Option] | Rejection:
    """Kombinacje grup możliwe dla studenta, malejąco po użyteczności, albo powód odmowy.

    prerequisites: kursy wymagane przez przedmiot zgłoszenia (id -> kod).
    Nie patrzy na wolne miejsca - te zależą od innych zgłoszeń.
    """
    missing = sorted(code for cid, code in prerequisites.items() if cid not in profile.passed_course_ids)
    if missing:
        return Rejection("PREREQUISITES", "Brak zaliczenia: " + ", ".join(missing) + ".", tuple(missing))

    has_kinds = {p.kind for p in profile.plan if p.course_id == request.course_id}
    needed = sorted(k for k in request.choices if k not in has_kinds)
    if not needed:
        return Rejection("ALREADY_ENROLLED", f"Masz już grupy przedmiotu {request.course_code}.")

    per_kind: list[list[tuple[int, int]]] = []          # (rank, id grupy)
    for kind in needed:
        candidates, conflicts = [], set()
        for rank, sid in enumerate(request.choices[kind], start=1):
            offer = offers.get(sid)
            if offer is None or offer.course_id != request.course_id or offer.kind != kind:
                continue
            clash = conflicting_sections(profile.plan, offer.slots)
            if clash:
                conflicts.update(c.label for c in clash)
            else:
                candidates.append((rank, sid))
        if not candidates:
            if conflicts:
                labels = tuple(sorted(conflicts))
                return Rejection("CONFLICT", "Wybrane grupy kolidują z Twoim planem: " + ", ".join(labels) + ".",
                                 labels)
            return Rejection("NO_SECTIONS", f"Żadna z wybranych grup przedmiotu {request.course_code} "
                                            "nie jest dostępna w tej turze.")
        per_kind.append(candidates)

    options = []
    for combo in product(*per_kind):
        slots = [offers[sid].slots for _, sid in combo]
        if any(any_overlap(slots[i], slots[j]) for i in range(len(slots)) for j in range(i + 1, len(slots))):
            continue
        ranks = tuple(r for r, _ in combo)
        flat = tuple(s for group in slots for s in group)
        options.append(Option(tuple(sid for _, sid in combo), ranks, utility(request.weight, ranks), flat,
                              time_mask(flat)))
    if not options:
        return Rejection("CONFLICT", f"Wybrane grupy różnych typów przedmiotu {request.course_code} "
                                     "kolidują ze sobą.")
    options.sort(key=lambda o: (-o.utility, o.ranks, o.section_ids))
    return options[:MAX_OPTIONS]


# --- kroki 2-3: podział miejsc ------------------------------------------------------

Key = tuple[int, int]   # (student, przedmiot)


@dataclass
class _State:
    """Bieżący przydział z dziennikiem zmian (wycofanie nieopłacalnego ruchu)."""
    free: dict[int, int]
    chosen: dict[Key, Option] = field(default_factory=dict)
    by_student: dict[int, set[Key]] = field(default_factory=lambda: defaultdict(set))
    busy: dict[int, int] = field(default_factory=lambda: defaultdict(int))     # student -> maska zajętych terminów
    holders: dict[int, set[Key]] = field(default_factory=lambda: defaultdict(set))
    journal: list[tuple[str, Key, Option]] = field(default_factory=list)
    total: float = 0.0

    def place(self, key: Key, opt: Option) -> None:
        self.total += opt.utility
        self.chosen[key] = opt
        self.by_student[key[0]].add(key)
        self.busy[key[0]] |= opt.mask
        for sid in opt.section_ids:
            self.free[sid] -= 1
            self.holders[sid].add(key)
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
        for sid in opt.section_ids:
            self.free[sid] += 1
            self.holders[sid].discard(key)
        self.journal.append(("remove", key, opt))
        return opt

    def mark(self) -> int:
        return len(self.journal)

    def rollback(self, mark: int) -> None:
        while len(self.journal) > mark:
            op, key, opt = self.journal.pop()
            if op == "place":
                self.remove(key)
            else:
                self.place(key, opt)
            self.journal.pop()                      # wpis dodany przez operację odwrotną

    def own_conflicts(self, key: Key, opt: Option) -> list[Key]:
        if not self.busy[key[0]] & opt.mask:
            return []
        return [k for k in self.by_student[key[0]] if k != key and self.chosen[k].mask & opt.mask]

    def fits(self, key: Key, opt: Option) -> bool:
        """Czy nieprzydzielone zgłoszenie `key` zmieści się w kombinacji `opt` (miejsca, kolizje)."""
        return not self.busy[key[0]] & opt.mask and all(self.free[sid] > 0 for sid in opt.section_ids)


def _lottery(student_ids: Iterable[int], seed: int) -> dict[int, float]:
    rng = random.Random(seed)
    return {sid: rng.random() for sid in sorted(set(student_ids))}


def allocate(requests: Sequence[CourseRequest], profiles: Mapping[int, StudentProfile],
             offers: Mapping[int, Offer], prerequisites: Mapping[int, Mapping[int, str]], *,
             seed: int, improve: bool = True) -> AllocationResult:
    """Przydział miejsc maksymalizujący sumę użyteczności (opis algorytmu w docstringu modułu).

    requests: zgłoszenia (student, przedmiot) - co najwyżej jedno na parę,
    profiles: plan i zaliczenia każdego studenta z requests,
    offers: grupy z liczbą wolnych miejsc,
    prerequisites: przedmiot -> wymagane kursy (id -> kod),
    seed: ziarno losowania kolejności przy równych wagach,
    improve: False = sam algorytm zachłanny (do porównań w testach).
    """
    by_key = {r.key: r for r in requests}
    if len(by_key) != len(requests):
        raise ValueError("Zdublowane zgłoszenie (student, przedmiot).")

    options: dict[Key, list[Option]] = {}
    rejected: dict[Key, Rejection] = {}
    for r in requests:
        got = options_for(r, profiles[r.student_id], offers, prerequisites.get(r.course_id, {}))
        if isinstance(got, Rejection):
            rejected[r.key] = got
        else:
            options[r.key] = got

    lottery = _lottery((r.student_id for r in requests), seed)
    order = sorted(options, key=lambda k: (-by_key[k].weight, lottery[k[0]], k[1]))
    keys_by_student: dict[int, list[Key]] = defaultdict(list)
    for key in order:
        keys_by_student[key[0]].append(key)

    state = _State(free={sid: max(0, o.free_seats) for sid, o in offers.items()})
    for key in order:                                                   # krok 2
        for opt in options[key]:
            if state.fits(key, opt):
                state.place(key, opt)
                break

    improvements = 0
    if improve:                                                         # krok 3
        sections_of = {k: {sid for o in opts for sid in o.section_ids} for k, opts in options.items()}
        candidates = [k for k in order if k not in state.chosen]
        for _ in range(MAX_PASSES):
            changed_sections: set[int] = set()
            changed_students: set[int] = set()
            for key in candidates:
                if key in state.chosen:
                    continue
                mark = state.mark()
                if _try_insert(state, key, options, keys_by_student):
                    improvements += 1
                    for _, k, opt in state.journal[mark:]:
                        changed_sections.update(opt.section_ids)
                        changed_students.add(k[0])
                state.journal.clear()               # ruch przyjęty albo wycofany - historia zbędna
            if not changed_sections:
                break
            # w kolejnym przebiegu tylko zgłoszenia, których sytuacja mogła się zmienić
            candidates = [k for k in order if k not in state.chosen
                          and (k[0] in changed_students or sections_of[k] & changed_sections)]

    assignments, unassigned = [], []
    for r in requests:
        if r.key in state.chosen:
            opt = state.chosen[r.key]
            assignments.append(Assignment(r.student_id, r.course_id, r.weight, opt.section_ids, opt.utility))
        else:
            reason = rejected.get(r.key) or _why_not(state, r, options[r.key], offers, by_key)
            unassigned.append(Unassigned(r.student_id, r.course_id, r.weight, reason))
    return AllocationResult(
        assignments=tuple(assignments), unassigned=tuple(unassigned),
        total_utility=round(sum(a.utility for a in assignments), 6),
        upper_bound=float(sum(by_key[k].weight for k in options)),
        improvements=improvements, seed=seed,
    )


def _try_insert(state: _State, key: Key, options: Mapping[Key, list[Option]],
                keys_by_student: Mapping[int, list[Key]]) -> bool:
    """Ruch poprawy dla nieprzydzielonego zgłoszenia; True, gdy suma użyteczności wzrosła."""
    for opt in options[key]:
        mark, before = state.mark(), state.total
        # własne kolidujące przydziały zwalniamy, nawet droższe: _refill może je przenieść
        # do innej kombinacji (np. inny wykład tego przedmiotu) - o opłacalności decyduje bilans
        evicted = state.own_conflicts(key, opt)
        for k in evicted:
            state.remove(k)
        if (all(_make_room(state, sid, {key[0]}, options, CHAIN_DEPTH, evicted) for sid in opt.section_ids)
                and state.fits(key, opt)):
            state.place(key, opt)
            _refill(state, evicted, options, keys_by_student, protect=key[0])
            if state.total > before + EPS:
                return True
        state.rollback(mark)
    return False


def _make_room(state: _State, section_id: int, forbidden: set[int], options: Mapping[Key, list[Option]],
               depth: int, evicted: list[Key], blocked: frozenset[int] = frozenset()) -> bool:
    """Zwalnia jedno miejsce w grupie (True = jest wolne miejsce).

    Najpierw próbuje przenieść kogoś z grupy do innej jego kombinacji, w kolejności
    najmniejszej straty; miejsce w tamtych grupach robi rekurencyjnie (łańcuch przeniesień
    do długości `depth`). Gdy się nie da - zwalnia przydział o najmniejszej użyteczności
    (trafia do `evicted`; _refill spróbuje go potem umieścić gdzie indziej).
    forbidden: studenci, których przydziałów w tym ruchu nie ruszamy,
    blocked: grupy zwalniane wyżej w łańcuchu - nikt nie może się do nich przenieść.
    """
    if state.free[section_id] > 0:
        return True
    blocked = blocked | {section_id}
    if depth > 0:
        moves = sorted(
            ((state.chosen[h].utility - alt.utility, h, alt) for h in state.holders[section_id]
             if h[0] not in forbidden for alt in options[h]
             if alt is not state.chosen[h] and not blocked.intersection(alt.section_ids)),
            key=lambda m: (m[0], m[1], m[2].section_ids))
        for _, holder, alt in moves[:MAX_MOVES]:
            mark, n_evicted = state.mark(), len(evicted)
            state.remove(holder)
            if (not state.busy[holder[0]] & alt.mask
                    and all(_make_room(state, sid, forbidden | {holder[0]}, options, depth - 1, evicted, blocked)
                            for sid in alt.section_ids)
                    and state.fits(holder, alt)):
                state.place(holder, alt)
                return True
            state.rollback(mark)
            del evicted[n_evicted:]
    others = [h for h in state.holders[section_id] if h[0] not in forbidden]
    if not others:
        return False
    victim = min(others, key=lambda h: (state.chosen[h].utility, h))
    state.remove(victim)
    evicted.append(victim)
    return True


def _refill(state: _State, evicted: Iterable[Key], options: Mapping[Key, list[Option]],
            keys_by_student: Mapping[int, list[Key]], protect: int, rounds: int = 2) -> None:
    """Po ruchu: zwolnione przydziały wracają w innej kombinacji, jeśli się da i lokalnie
    się to opłaca (także kosztem przeniesienia albo zwolnienia tańszego przydziału - ten
    trafia do kolejnej rundy), a ich właściciele dostają, co się teraz mieści z pozostałych
    zgłoszeń (np. przedmiot, który kolidował ze zwolnionym).
    protect: student, dla którego wykonano ruch - jego przydziałów uzupełnianie nie rusza."""
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
                if (all(_make_room(state, sid, {k[0], protect}, options, 1, out) for sid in alt.section_ids)
                        and state.fits(k, alt)):
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


def _why_not(state: _State, request: CourseRequest, opts: list[Option], offers: Mapping[int, Offer],
             by_key: Mapping[Key, CourseRequest]) -> Rejection:
    """Powód odmowy dla zgłoszenia wykonalnego, które nie dostało miejsc."""
    for opt in opts:
        if all(state.free[s] > 0 for s in opt.section_ids):
            # miejsca są, więc przeszkodą jest kolizja z ważniejszym przydziałem tego studenta
            codes = tuple(sorted(by_key[k].course_code for k in state.own_conflicts(request.key, opt)))
            return Rejection("OWN_CONFLICT", "Wolne grupy kolidują z przedmiotem, który dostałeś z wyższym "
                                             "priorytetem: " + ", ".join(codes) + ".", codes)
    full = sorted({offers[s].label for o in opts for s in o.section_ids if state.free[s] <= 0})
    return Rejection("FULL", "Brak miejsc w wybranych grupach - zajęły je zgłoszenia z wyższą wagą "
                             "albo wygrane w losowaniu.", tuple(full[:5]))


# --- walidacja zgłoszenia studenta ------------------------------------------------------

MAX_COURSES = 20
MAX_SECTIONS_PER_COURSE = 30


@dataclass(frozen=True)
class SectionInfo:
    id: int
    course_id: int
    kind: str
    term_id: int


@dataclass(frozen=True)
class PreferenceInput:
    course_id: int
    weight: int
    section_ids: tuple[int, ...]       # akceptowane grupy w kolejności (różne typy mogą się przeplatać)


def validate_preferences(items: Sequence[PreferenceInput], budget: int, term_id: int,
                         sections: Mapping[int, SectionInfo]) -> list[Rejection]:
    """Błędy blokujące zapis preferencji (pusta lista = poprawne)."""
    errors: list[Rejection] = []
    if len(items) > MAX_COURSES:
        errors.append(Rejection("TOO_MANY_COURSES", f"Można zgłosić najwyżej {MAX_COURSES} przedmiotów."))
    courses = [i.course_id for i in items]
    dup = sorted({c for c in courses if courses.count(c) > 1})
    if dup:
        errors.append(Rejection("DUPLICATE_COURSE", "Przedmiot zgłoszony więcej niż raz.", tuple(map(str, dup))))
    if any(i.weight < 1 for i in items):
        errors.append(Rejection("BAD_WEIGHT", "Waga przedmiotu musi być dodatnia."))
    used = sum(i.weight for i in items)
    if used > budget:
        errors.append(Rejection("BUDGET_EXCEEDED", f"Rozdzielono {used} punktów, a pula tury to {budget}."))
    seen: set[int] = set()
    for item in items:
        if not item.section_ids:
            errors.append(Rejection("NO_SECTIONS", "Dla każdego przedmiotu wybierz co najmniej jedną grupę.",
                                    (str(item.course_id),)))
        if len(item.section_ids) > MAX_SECTIONS_PER_COURSE:
            errors.append(Rejection("TOO_MANY_SECTIONS",
                                    f"Najwyżej {MAX_SECTIONS_PER_COURSE} grup na przedmiot."))
        for sid in item.section_ids:
            info = sections.get(sid)
            if sid in seen:
                errors.append(Rejection("DUPLICATE_SECTION", "Grupa wybrana więcej niż raz.", (str(sid),)))
            elif info is None or info.course_id != item.course_id or info.term_id != term_id:
                errors.append(Rejection("BAD_SECTION", "Grupa nie należy do tego przedmiotu w semestrze tury.",
                                        (str(sid),)))
            seen.add(sid)
    return errors


def choices_by_kind(section_ids: Sequence[int], sections: Mapping[int, SectionInfo]) -> dict[str, tuple[int, ...]]:
    """Lista grup w kolejności -> grupy per typ zajęć (ranga = pozycja w obrębie typu)."""
    out: dict[str, list[int]] = defaultdict(list)
    for sid in section_ids:
        out[sections[sid].kind].append(sid)
    return {k: tuple(v) for k, v in out.items()}


# --- niezależna kontrola wyniku ------------------------------------------------------------

def verify(result: AllocationResult, requests: Sequence[CourseRequest], profiles: Mapping[int, StudentProfile],
           offers: Mapping[int, Offer], prerequisites: Mapping[int, Mapping[int, str]]) -> list[str]:
    """Sprawdza ograniczenia (1)-(4) wyniku niezależnie od algorytmu; pusta lista = poprawny.

    AllocationService wywołuje ją przed zapisaniem przydziału: błąd w optymalizatorze kończy
    się wycofaniem transakcji, a nie kolizją w planie studenta. Używają jej też testy.
    """
    problems: list[str] = []
    by_key = {r.key: r for r in requests}
    used: dict[int, int] = defaultdict(int)
    taken: dict[int, list[tuple[int, Offer]]] = defaultdict(list)       # student -> (kurs, grupa)
    for a in result.assignments:
        r = by_key.get((a.student_id, a.course_id))
        if r is None:
            problems.append(f"przydział bez zgłoszenia: student {a.student_id}, kurs {a.course_id}")
            continue
        profile = profiles[a.student_id]
        missing = set(prerequisites.get(a.course_id, {})) - profile.passed_course_ids
        if missing:
            problems.append(f"student {a.student_id}: brak wymagań do kursu {a.course_id}")
        has_kinds = {p.kind for p in profile.plan if p.course_id == a.course_id}
        kinds = [offers[s].kind for s in a.section_ids]
        if sorted(kinds) != sorted(k for k in r.choices if k not in has_kinds):
            problems.append(f"student {a.student_id}, kurs {a.course_id}: zły zestaw typów zajęć {kinds}")
        for sid in a.section_ids:
            offer = offers[sid]
            used[sid] += 1
            if sid not in r.choices.get(offer.kind, ()):
                problems.append(f"student {a.student_id}: grupa {offer.label} spoza zgłoszenia")
            if conflicting_sections(profile.plan, offer.slots):
                problems.append(f"student {a.student_id}: {offer.label} koliduje z planem")
            for course, other in taken[a.student_id]:
                if any_overlap(other.slots, offer.slots):
                    problems.append(f"student {a.student_id}: {offer.label} koliduje z {other.label}")
            taken[a.student_id].append((a.course_id, offer))
    for sid, n in used.items():
        if n > offers[sid].free_seats:
            problems.append(f"grupa {offers[sid].label}: przydzielono {n}, wolnych {offers[sid].free_seats}")
    return problems
