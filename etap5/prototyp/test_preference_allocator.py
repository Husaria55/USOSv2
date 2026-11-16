"""Testy prototypu PreferenceAllocator (przygotowanie -> wywołanie allocate -> weryfikacja).

Uruchomienie:  python -m pytest test_preference_allocator.py   (wymaga tylko pytest)
"""
import itertools
import random
import time as clock
from datetime import time

import pytest

from preference_allocator import (
    CourseRequest, EnrolledSection, ScheduleSlot, SectionOffer, StudentProfile, allocate, options_for, rank_factor,
    slots_overlap, verify,
)


def slot(day, a, b):
    h1, m1 = map(int, a.split(":"))
    h2, m2 = map(int, b.split(":"))
    return ScheduleSlot(day, time(h1, m1), time(h2, m2))


MON_8, MON_10, TUE_8 = slot(1, "8:00", "9:30"), slot(1, "10:00", "11:30"), slot(2, "8:00", "9:30")


def sec(sid, course, s=MON_8, free=1):
    return SectionOffer(sid, course, f"K{course}-S{sid}", (s,), free)


def req(student, course, weight, *sections):
    return CourseRequest(student, course, f"K{course}", weight, tuple(sections))


def profiles(*students, plan=None, done=None):
    return {s: StudentProfile(s, tuple((plan or {}).get(s, ())), frozenset((done or {}).get(s, ()))) for s in students}


def run(requests, offers, prof=None, prereq=None, seed=1, improve=True):
    prof = prof or profiles(*{r.student_id for r in requests})
    offers = {o.section_id: o for o in offers}
    result = allocate(requests, prof, offers, prereq or {}, seed=seed, improve=improve)
    assert verify(result, requests, prof, offers, prereq or {}) == []
    return result


def got(result):
    return {(a.student_id, a.course_id): a.section_id for a in result.assignments}


def why(result):
    return {(u.student_id, u.course_id): u.reason.code for u in result.unassigned}


def test_overlaps_with_boundaries():
    assert MON_8.overlaps_with(slot(1, "9:00", "10:00"))
    assert not MON_8.overlaps_with(slot(1, "9:30", "11:00"))           # styk końcem nie jest kolizją
    assert not MON_8.overlaps_with(TUE_8)                               # inny dzień
    assert [rank_factor(r) for r in (1, 2, 6, 9)] == [1.0, 0.9, 0.5, 0.5]


def test_higher_weight_wins():
    r = run([req(1, 100, 30, 10), req(2, 100, 70, 10)], [sec(10, 100)])
    assert got(r) == {(2, 100): 10} and why(r) == {(1, 100): "FULL"}


def test_tie_decided_by_seed_reproducibly():
    reqs = [req(s, 100, 50, 10) for s in range(1, 9)]
    w = {seed: got(run(reqs, [sec(10, 100)], seed=seed)) for seed in range(20)}
    assert len({tuple(v) for v in w.values()}) > 1
    assert all(got(run(reqs, [sec(10, 100)], seed=s)) == v for s, v in w.items())


def test_no_conflict_between_assigned_courses():
    r = run([req(1, 100, 30, 10), req(1, 200, 70, 20)], [sec(10, 100, MON_8, 5), sec(20, 200, MON_8, 5)])
    assert got(r) == {(1, 200): 20} and why(r) == {(1, 100): "OWN_CONFLICT"}


def test_plan_prerequisites_and_already_enrolled():
    plan = {1: (EnrolledSection(99, 300, "K300-S99", (MON_8,)),)}
    r = run([req(1, 100, 20, 10), req(1, 200, 30, 20), req(1, 300, 50, 30)],
            [sec(10, 100, MON_8), sec(20, 200, TUE_8), sec(30, 300, slot(3, "8:00", "9:30"))],
            profiles(1, plan=plan), prereq={200: {7: "AM1"}})
    assert why(r) == {(1, 100): "CONFLICT", (1, 200): "PREREQUISITES", (1, 300): "ALREADY_ENROLLED"}


def test_improvement_moves_flexible_student():
    reqs, offers = [req(1, 100, 50, 10), req(2, 100, 60, 10, 11)], [sec(10, 100), sec(11, 100, TUE_8)]
    assert run(reqs, offers, improve=False).total_utility == 60
    better = run(reqs, offers)
    assert got(better) == {(1, 100): 10, (2, 100): 11} and better.total_utility == pytest.approx(104)


def exact(requests, prof, offers):
    choices = []
    for r in requests:
        o = options_for(r, prof[r.student_id], offers, {})
        choices.append([None] + (o if isinstance(o, list) else []))
    best = 0.0
    for combo in itertools.product(*choices):
        used, mine, total, ok = {}, {}, 0.0, True
        for r, o in zip(requests, combo):
            if o is None:
                continue
            used[o.section_id] = used.get(o.section_id, 0) + 1
            slots = offers[o.section_id].slots
            if used[o.section_id] > offers[o.section_id].free_seats or \
                    any(slots_overlap(s, slots) for s in mine.get(r.student_id, [])):
                ok = False
                break
            mine.setdefault(r.student_id, []).append(slots)
            total += o.utility
        if ok:
            best = max(best, total)
    return best


def instance(rng):
    slots = [MON_8, MON_10, TUE_8, slot(1, "9:00", "10:30")]
    offers, sid = {}, 0
    for course in (1, 2, 3, 4):
        for _ in range(rng.randint(1, 3)):
            sid += 1
            offers[sid] = SectionOffer(sid, course, f"K{course}-S{sid}", (rng.choice(slots),), rng.randint(1, 2))
    requests = []
    for st in range(1, rng.randint(3, 5) + 1):
        for course in rng.sample([1, 2, 3, 4], rng.randint(1, 2)):
            ids = [o.section_id for o in offers.values() if o.course_id == course]
            rng.shuffle(ids)
            requests.append(CourseRequest(st, course, f"K{course}", rng.randint(1, 60), tuple(ids[:rng.randint(1, len(ids))])))
    return requests, profiles(*{r.student_id for r in requests}), offers


def quality(n):
    """(średnio % optimum, najgorszy, odsetek dokładnie optymalnych) dla heurystyki i samego zachłannego."""
    out = {True: [], False: []}
    for seed in range(n):
        reqs, prof, offers = instance(random.Random(seed))
        opt = exact(reqs, prof, offers)
        for improve in (True, False):
            r = allocate(reqs, prof, offers, {}, seed=seed, improve=improve)
            assert verify(r, reqs, prof, offers, {}) == []
            if opt:
                out[improve].append(r.total_utility / opt)
    return {k: (sum(v) / len(v), min(v), sum(x > 0.999 for x in v) / len(v)) for k, v in out.items()}


def test_quality_against_exact_optimum():
    q = quality(300)
    assert q[True][0] >= 0.99 and q[True][2] >= 0.9 and q[True][0] > q[False][0]


def scale_instance(students=1000, courses=30, sections=5, cap=30, per=6, take=3, seed=5):
    rng = random.Random(seed)
    blocks = [slot(d, f"{h}:00", f"{h + 1}:30") for d in range(1, 6) for h in (8, 10, 12, 14, 16)]
    offers, sid = {}, 0
    for c in range(1, courses + 1):
        for _ in range(sections):
            sid += 1
            offers[sid] = SectionOffer(sid, c, f"K{c}-S{sid}", (rng.choice(blocks),), cap)
    reqs = []
    for st in range(1, students + 1):
        for c in rng.sample(range(1, courses + 1), per):
            ids = [o.section_id for o in offers.values() if o.course_id == c]
            rng.shuffle(ids)
            reqs.append(CourseRequest(st, c, f"K{c}", rng.randint(1, 40), tuple(ids[:take])))
    return reqs, profiles(*range(1, students + 1)), offers


def test_scale_one_program():
    reqs, prof, offers = scale_instance()
    t0 = clock.perf_counter()
    r = allocate(reqs, prof, offers, {}, seed=3)
    assert clock.perf_counter() - t0 < 30
    assert verify(r, reqs, prof, offers, {}) == []


if __name__ == "__main__":                       # python test_preference_allocator.py -> tabela do README
    q = quality(1000)
    for k, name in ((False, "zachłanny"), (True, "zachłanny + poprawa lokalna")):
        print(f"{name:30s} średnio {q[k][0]:.2%}  najgorszy {q[k][1]:.0%}  optimum {q[k][2]:.1%}")
    reqs, prof, offers = scale_instance()
    t0 = clock.perf_counter()
    r = allocate(reqs, prof, offers, {}, seed=3)
    print(f"skala: {len(reqs)} zgłoszeń, {len(offers)} sekcji, {clock.perf_counter() - t0:.1f} s, "
          f"przydzielono {len(r.assignments)}, {r.total_utility / r.upper_bound:.1%} górnego ograniczenia")
