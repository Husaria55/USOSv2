"""Reguły domenowe bez bazy."""
from datetime import datetime, time, timedelta, timezone

import pytest

from app.domain.enrollment_rules import (
    Mode, Outcome, PlanEntry, Refusal, SeatState, StudentState, TargetSection, check_student, decide_seat,
)
from app.domain.prerequisites import creates_cycle, missing_prerequisites
from app.domain.rounds import RoundInfo, scheduled_transition, student_can_enroll
from app.domain.schedule import Slot, slots_overlap


def s(wd, a, b, par="ALL"):
    return Slot(wd, time(*map(int, a.split(":"))), time(*map(int, b.split(":"))), par)


MON_10 = s(1, "10:00", "11:30")
WED_12_ODD = s(3, "12:00", "13:30", "ODD")


@pytest.mark.parametrize("slot, expected", [
    (s(1, "11:00", "12:30"), True),          # nachodzi
    (s(1, "11:30", "13:00"), False),         # styka się końcem
    (s(2, "10:00", "11:30"), False),         # inny dzień
    (s(1, "09:00", "12:00"), True),          # obejmuje
])
def test_overlap_hours(slot, expected):
    assert slots_overlap(MON_10, slot) is expected


@pytest.mark.parametrize("slot, expected", [
    (s(3, "12:00", "13:30", "EVEN"), False),
    (s(3, "13:00", "14:30", "ALL"), True),
    (s(3, "13:00", "14:30", "ODD"), True),
])
def test_overlap_parity(slot, expected):
    assert slots_overlap(WED_12_ODD, slot) is expected


def test_prerequisites():
    assert missing_prerequisites({1, 2}, {2, 3}) == {1}
    assert missing_prerequisites(set(), set()) == set()


def test_cycles():
    graph = {2: [1], 3: [2]}                 # 3 wymaga 2, 2 wymaga 1
    assert creates_cycle(graph, 1, 3)        # 1 -> 3 zamknęłoby cykl
    assert not creates_cycle(graph, 3, 1)
    assert creates_cycle(graph, 4, 4)


def plan_entry(sid, course, kind, slot, code="L01"):
    return PlanEntry(sid, code, f"K{course}", (slot,), course, kind)


def state(plan=(), passed=(), waiting=(), round_open=True):
    return StudentState(round_open, tuple(plan), frozenset(passed), frozenset(waiting))


def target(sid=100, course=1, kind="LAB", slot=MON_10, prereqs=None):
    return TargetSection(sid, course, f"K{course}", "L02", kind, (slot,), prereqs or {})


def codes(refusals):
    return [r.code for r in refusals]


def test_rules_ok():
    assert check_student(state(), target(), Mode.DIRECT) == []


def test_rules_refusals():
    plan = [plan_entry(1, 1, "LAB", s(2, "8:00", "9:00")), plan_entry(2, 7, "LECTURE", MON_10)]
    got = check_student(state(plan, round_open=False), target(prereqs={5: "AM1"}), Mode.DIRECT)
    assert codes(got) == ["ROUND_CLOSED", "SAME_KIND", "PREREQUISITES", "CONFLICT"]
    assert got[3].details == ("K7 L01",)


def test_lecture_and_lab_of_same_course_allowed():
    plan = [plan_entry(1, 1, "LECTURE", s(2, "8:00", "9:00"))]
    assert check_student(state(plan), target(kind="LAB"), Mode.DIRECT) == []


def test_admin_skips_round_and_prerequisites_but_not_conflicts():
    plan = [plan_entry(2, 7, "LECTURE", MON_10)]
    got = check_student(state(plan, round_open=False), target(prereqs={5: "AM1"}), Mode.ADMIN)
    assert codes(got) == ["CONFLICT"]


def test_waitlist_mode_ignores_own_waiting_entry_and_round():
    got = check_student(state(waiting={100}, round_open=False), target(), Mode.WAITLIST)
    assert got == []
    assert codes(check_student(state(waiting={100}), target(), Mode.DIRECT)) == ["ALREADY_WAITING"]


def seat(cap=10, n=10, wl=2, waiting=0, room=None):
    return SeatState(cap, n, wl, waiting, room)


def test_seats():
    assert decide_seat(seat(n=9), Mode.DIRECT) is Outcome.ENROLL
    assert decide_seat(seat(waiting=1), Mode.DIRECT) is Outcome.WAITLIST
    assert decide_seat(seat(waiting=2), Mode.DIRECT).code == "WAITLIST_FULL"
    assert decide_seat(seat(room=11), Mode.ADMIN) is Outcome.ENROLL_OVER_CAPACITY
    assert decide_seat(seat(room=10), Mode.ADMIN).code == "ROOM_FULL"
    assert isinstance(decide_seat(seat(), Mode.WAITLIST), Refusal)


def test_rounds():
    now = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    r = lambda st, progs=(), a=-1, b=1: RoundInfo(1, st, now + timedelta(hours=a), now + timedelta(hours=b),
                                                   frozenset(progs))
    assert student_can_enroll([r("OPEN", {1})], 1)
    assert not student_can_enroll([r("OPEN", {2})], 1)
    assert student_can_enroll([r("OPEN")], 1)                  # tura dla wszystkich
    assert not student_can_enroll([r("PLANNED")], 1)
    assert scheduled_transition(r("PLANNED"), now) == "OPEN"
    assert scheduled_transition(r("PLANNED", a=1, b=2), now) is None
    assert scheduled_transition(r("OPEN", a=-2, b=-1), now) == "CLOSED"
    assert scheduled_transition(r("CLOSED"), now) is None     # zamkniętej ręcznie nie otwiera
