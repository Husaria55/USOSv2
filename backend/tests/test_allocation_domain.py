"""Optymalizator przydziału (app/domain/allocation.py) bez bazy.

Każdy test: 1) przygotowanie (grupy, zgłoszenia, plany), 2) wywołanie allocate / options_for /
validate_preferences z konkretnymi danymi, 3) weryfikacja wyniku. Opis scenariuszy: etap5/TESTY.md.
"""
import itertools
import random
import time

import pytest

from app.domain.allocation import (
    CourseRequest, Offer, PreferenceInput, SectionInfo, StudentProfile, allocate, options_for, rank_factor, utility,
    validate_preferences, verify,
)
from app.domain.enrollment_rules import PlanEntry
from app.domain.schedule import Slot, any_overlap
from tests.test_domain import s

MON_8, MON_10, TUE_8, WED_8 = s(1, "8:00", "9:30"), s(1, "10:00", "11:30"), s(2, "8:00", "9:30"), s(3, "8:00", "9:30")


def offer(sid, course, kind="LAB", slot=MON_8, free=1):
    return Offer(sid, course, kind, f"K{course} {kind[0]}{sid}", (slot,), free)


def req(student, course, weight, *labs, lecture=(), code=None):
    choices = {"LAB": tuple(labs)} if labs else {}
    if lecture:
        choices["LECTURE"] = tuple(lecture)
    return CourseRequest(student, course, code or f"K{course}", weight, choices)


def profiles(*students, plan=None, passed=None):
    return {st: StudentProfile(st, tuple((plan or {}).get(st, ())), frozenset((passed or {}).get(st, ())))
            for st in students}


def run(requests, offers, prof=None, prereqs=None, seed=1, improve=True):
    prof = prof or profiles(*{r.student_id for r in requests})
    offers = {o.section_id: o for o in offers}
    result = allocate(requests, prof, offers, prereqs or {}, seed=seed, improve=improve)
    assert verify(result, requests, prof, offers, prereqs or {}) == []        # ograniczenia zawsze spełnione
    return result


def got(result):
    return {(a.student_id, a.course_id): a.section_ids for a in result.assignments}


def reasons(result):
    return {(u.student_id, u.course_id): u.reason.code for u in result.unassigned}


# --- podstawy ---------------------------------------------------------------------

def test_rank_factor_and_utility():
    assert [rank_factor(r) for r in (1, 2, 3, 6, 9)] == [1.0, 0.9, 0.8, 0.5, 0.5]
    assert utility(40, [1, 2]) == pytest.approx(38.0)        # 40 * (1.0 + 0.9) / 2


def test_higher_weight_wins_contested_seat():
    """A1: dwie osoby, jedno miejsce - dostaje ta, która dała przedmiotowi więcej punktów."""
    # 1. przygotowanie: grupa 10 z jednym miejscem, student 1 daje 30 pkt, student 2 daje 70 pkt
    result = run([req(1, 100, 30, 10), req(2, 100, 70, 10)], [offer(10, 100, free=1)])
    # 3. weryfikacja
    assert got(result) == {(2, 100): (10,)}
    assert reasons(result) == {(1, 100): "FULL"}
    assert result.total_utility == 70 and result.upper_bound == 100


def test_tie_is_decided_by_seeded_lottery_and_is_reproducible():
    """A2: remis wag - rozstrzyga los z ziarnem; to samo ziarno = ten sam wynik."""
    requests = [req(st, 100, 50, 10) for st in range(1, 9)]
    winners = {seed: next(iter(got(run(requests, [offer(10, 100)], seed=seed)))) for seed in range(20)}
    assert len(set(winners.values())) > 1                              # różne ziarna - różni zwycięzcy
    assert all(next(iter(got(run(requests, [offer(10, 100)], seed=seed)))) == w for seed, w in winners.items())


def test_group_rank_is_respected_when_seats_allow():
    """A3: student dostaje grupę z 1. wyboru, jeśli jest miejsce; inaczej kolejną."""
    offers = [offer(10, 100, free=1), offer(11, 100, slot=TUE_8, free=5)]
    result = run([req(1, 100, 60, 10, 11), req(2, 100, 40, 10, 11)], offers)
    assert got(result) == {(1, 100): (10,), (2, 100): (11,)}
    assert {a.student_id: a.utility for a in result.assignments} == {1: 60, 2: pytest.approx(36)}


def test_lecture_and_lab_all_or_nothing():
    """A4: przedmiot z wykładem i laboratorium - albo oba, albo nic (miejsca wykładu nie przepadają)."""
    offers = [offer(1, 100, "LECTURE", WED_8, free=5), offer(10, 100, "LAB", MON_8, free=1)]
    result = run([req(1, 100, 80, 10, lecture=[1]), req(2, 100, 20, 10, lecture=[1])], offers)
    assert got(result) == {(1, 100): (10, 1)} or got(result) == {(1, 100): (1, 10)}
    assert reasons(result) == {(2, 100): "FULL"}                      # sam wykład bez laba - nie


def test_no_conflict_between_assigned_courses_of_one_student():
    """A5: dwa przedmioty o tej samej porze - student dostaje ważniejszy, drugi z powodem OWN_CONFLICT."""
    offers = [offer(10, 100, slot=MON_8, free=5), offer(20, 200, slot=MON_8, free=5)]
    result = run([req(1, 100, 30, 10), req(1, 200, 70, 20)], offers)
    assert got(result) == {(1, 200): (20,)}
    assert reasons(result) == {(1, 100): "OWN_CONFLICT"}


def test_existing_plan_prerequisites_and_already_enrolled():
    """A6: kolizja z planem z wcześniejszej tury, brak zaliczenia i posiadana grupa są wykluczane przed podziałem."""
    plan = (PlanEntry(99, "L01", "K300", (MON_8,), 300, "LAB"),)
    prof = profiles(1, plan={1: plan})
    offers = [offer(10, 100, slot=MON_8), offer(20, 200, slot=TUE_8), offer(30, 300, slot=WED_8)]
    result = run([req(1, 100, 20, 10), req(1, 200, 30, 20), req(1, 300, 50, 30)], offers, prof,
                 prereqs={200: {7: "AM1"}})
    assert got(result) == {}
    assert reasons(result) == {(1, 100): "CONFLICT", (1, 200): "PREREQUISITES", (1, 300): "ALREADY_ENROLLED"}
    assert result.upper_bound == 0                                     # nic z tego nie było wykonalne


def test_parity_groups_do_not_conflict():
    """A7: grupy co dwa tygodnie (ODD/EVEN) o tej samej porze nie kolidują - oba przedmioty przydzielone."""
    offers = [offer(10, 100, slot=s(1, "8:00", "9:30", "ODD")), offer(20, 200, slot=s(1, "8:00", "9:30", "EVEN"))]
    result = run([req(1, 100, 50, 10), req(1, 200, 50, 20)], offers)
    assert set(got(result)) == {(1, 100), (1, 200)}


# --- poprawa lokalna ---------------------------------------------------------------------

def test_improvement_moves_flexible_student_to_second_choice():
    """A8: sam algorytm zachłanny daje wynik 60, poprawa lokalna - 104.

    Student 2 (waga 60) akceptuje L10 i L11, student 1 (waga 50) tylko L10; po jednym miejscu.
    Zachłanny daje L10 studentowi 2 i nic studentowi 1. Poprawa przenosi studenta 2 do L11
    (strata 6) i zwalnia L10 dla studenta 1 (zysk 50).
    """
    offers = [offer(10, 100, free=1), offer(11, 100, slot=TUE_8, free=1)]
    requests = [req(1, 100, 50, 10), req(2, 100, 60, 10, 11)]
    greedy = run(requests, offers, improve=False)
    assert got(greedy) == {(2, 100): (10,)} and greedy.total_utility == 60
    better = run(requests, offers)
    assert got(better) == {(1, 100): (10,), (2, 100): (11,)}
    assert better.total_utility == pytest.approx(104) and better.improvements == 1


def test_improvement_evicts_own_less_valuable_course():
    """A9: kolizja z własnym przydziałem o mniejszej użyteczności - przenosimy go do innej grupy."""
    offers = [offer(10, 100, slot=MON_8, free=1), offer(20, 200, slot=MON_8, free=1), offer(21, 200, slot=TUE_8)]
    # student 2 zabiera L21; student 1: K200 (waga 30, L20 albo L21), K100 (waga 70, tylko L10 o tej porze co L20)
    requests = [req(2, 200, 90, 21), req(1, 200, 30, 20, 21), req(1, 100, 70, 10)]
    result = run(requests, offers)
    assert got(result)[(1, 100)] == (10,)
    assert (1, 200) not in got(result) and reasons(result)[(1, 200)] in ("FULL", "OWN_CONFLICT")


# --- jakość względem rozwiązania dokładnego -------------------------------------------------

def exact_optimum(requests, prof, offers, prereqs) -> float:
    """Przegląd zupełny (tylko małe instancje): maksimum sumy użyteczności."""
    choices = []
    for r in requests:
        opts = options_for(r, prof[r.student_id], offers, prereqs.get(r.course_id, {}))
        choices.append([None] + (opts if isinstance(opts, list) else []))
    best = 0.0
    for combo in itertools.product(*choices):
        used, slots_of, total, ok = {}, {}, 0.0, True
        for r, opt in zip(requests, combo):
            if opt is None:
                continue
            for sid in opt.section_ids:
                used[sid] = used.get(sid, 0) + 1
                if used[sid] > offers[sid].free_seats:
                    ok = False
            mine = slots_of.setdefault(r.student_id, [])
            if any(any_overlap(other, opt.slots) for other in mine):
                ok = False
            mine.append(opt.slots)
            total += opt.utility
            if not ok:
                break
        if ok:
            best = max(best, total)
    return best


def random_instance(rng: random.Random):
    slots = [MON_8, MON_10, TUE_8, s(1, "9:00", "10:30")]
    offers, sid = {}, 0
    for course in (1, 2, 3):
        kinds = ["LAB"] if course != 3 else ["LECTURE", "LAB"]
        for kind in kinds:
            for _ in range(rng.randint(1, 2)):
                sid += 1
                offers[sid] = Offer(sid, course, kind, f"K{course} {sid}", (rng.choice(slots),), rng.randint(1, 2))
    requests = []
    for st in range(1, rng.randint(3, 5) + 1):
        for course in rng.sample([1, 2, 3], rng.randint(1, 2)):
            choices = {}
            for kind in sorted({o.kind for o in offers.values() if o.course_id == course}):
                ids = [o.section_id for o in offers.values() if o.course_id == course and o.kind == kind]
                rng.shuffle(ids)
                choices[kind] = tuple(ids[:rng.randint(1, len(ids))])
            requests.append(CourseRequest(st, course, f"K{course}", rng.randint(1, 60), choices))
    return requests, profiles(*{r.student_id for r in requests}), offers


def test_quality_against_exact_optimum_on_random_instances():
    """A10: 300 losowych małych instancji - ograniczenia zawsze spełnione, wynik blisko optimum.

    Zachłanny bez poprawy jest wyraźnie gorszy; poprawa lokalna zmniejsza stratę.
    Progi są zachowawcze - zmierzone wartości są w etap5/TESTY.md.
    """
    ratios, greedy_ratios = [], []
    for seed in range(300):
        rng = random.Random(seed)
        requests, prof, offers = random_instance(rng)
        opt = exact_optimum(requests, prof, offers, {})
        result = allocate(requests, prof, offers, {}, seed=seed)
        greedy = allocate(requests, prof, offers, {}, seed=seed, improve=False)
        assert verify(result, requests, prof, offers, {}) == []
        assert result.total_utility <= opt + 1e-6 and result.total_utility <= result.upper_bound + 1e-6
        if opt:
            ratios.append(result.total_utility / opt)
            greedy_ratios.append(greedy.total_utility / opt)
    mean, greedy_mean = sum(ratios) / len(ratios), sum(greedy_ratios) / len(greedy_ratios)
    assert mean >= 0.99, mean
    assert mean > greedy_mean
    assert sum(r > 0.999 for r in ratios) / len(ratios) >= 0.93        # prawie zawsze dokładnie optimum


def test_scale_one_program_round_is_fast():
    """A11: skala jednego kierunku (1000 studentów x 6 przedmiotów, 180 grup) - kilka sekund, poprawny wynik."""
    rng = random.Random(5)
    blocks = [s(d, f"{h}:00", f"{h + 1}:30") for d in range(1, 6) for h in (8, 10, 12, 14, 16)]
    offers, sid = {}, 0
    for course in range(1, 31):
        sid += 1
        offers[sid] = Offer(sid, course, "LECTURE", f"K{course} W", (rng.choice(blocks),), 200)
        for _ in range(5):
            sid += 1
            offers[sid] = Offer(sid, course, "LAB", f"K{course} L{sid}", (rng.choice(blocks),), 15)
    requests = []
    for st in range(1, 1001):
        courses = rng.sample(range(1, 31), 6)
        weights = [rng.randint(1, 40) for _ in courses]
        for course, w in zip(courses, weights):
            labs = [o.section_id for o in offers.values() if o.course_id == course and o.kind == "LAB"]
            rng.shuffle(labs)
            lecture = next(o.section_id for o in offers.values() if o.course_id == course and o.kind == "LECTURE")
            requests.append(CourseRequest(st, course, f"K{course}", w,
                                          {"LECTURE": (lecture,), "LAB": tuple(labs[:3])}))
    prof = profiles(*range(1, 1001))
    started = time.perf_counter()
    result = allocate(requests, prof, offers, {}, seed=3)
    elapsed = time.perf_counter() - started
    assert verify(result, requests, prof, offers, {}) == []
    assert elapsed < 30, elapsed
    # popyt (6000 zgłoszeń) > miejsca w laboratoriach (30 x 5 x 15 = 2250): prawie wszystkie zajęte
    lab_seats = sum(o.free_seats for o in offers.values() if o.kind == "LAB")
    assert len(result.assignments) >= 0.9 * lab_seats


# --- walidacja zgłoszenia ---------------------------------------------------------------

SECTIONS = {10: SectionInfo(10, 100, "LAB", 1), 11: SectionInfo(11, 100, "LECTURE", 1),
            20: SectionInfo(20, 200, "LAB", 1), 30: SectionInfo(30, 300, "LAB", 2)}


@pytest.mark.parametrize("items, code", [
    ([PreferenceInput(100, 60, (10,)), PreferenceInput(200, 50, (20,))], "BUDGET_EXCEEDED"),
    ([PreferenceInput(100, 0, (10,))], "BAD_WEIGHT"),
    ([PreferenceInput(100, 10, (20,))], "BAD_SECTION"),                 # grupa innego przedmiotu
    ([PreferenceInput(300, 10, (30,))], "BAD_SECTION"),                 # grupa z innego semestru
    ([PreferenceInput(100, 10, (999,))], "BAD_SECTION"),                # nie istnieje
    ([PreferenceInput(100, 10, (10, 10))], "DUPLICATE_SECTION"),
    ([PreferenceInput(100, 10, (10,)), PreferenceInput(100, 10, (11,))], "DUPLICATE_COURSE"),
    ([PreferenceInput(100, 10, ())], "NO_SECTIONS"),
])
def test_validate_preferences_errors(items, code):
    """A12: walidacja zgłoszenia - każdy błąd ma swój kod."""
    assert code in [e.code for e in validate_preferences(items, 100, 1, SECTIONS)]


def test_validate_preferences_ok():
    items = [PreferenceInput(100, 60, (11, 10)), PreferenceInput(200, 40, (20,))]
    assert validate_preferences(items, 100, 1, SECTIONS) == []
    assert validate_preferences([], 100, 1, SECTIONS) == []             # puste = rezygnacja z tury
