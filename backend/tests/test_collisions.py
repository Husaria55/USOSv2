"""Brak kolizji w planie studenta: zapisy, listy oczekujących, zmiany harmonogramu w trakcie tury.

Wymaganie etapu 5: "weryfikacja braku kolizji zajęć dla studenta w różnych scenariuszach zapisu
do grup i zmiany harmonogramu w trakcie zapisów, szczególnie w kontekście przydzielania zajęć
z kolejki". Każdy test ma trzy części:
  1) przygotowanie - stan systemu (fabryki w tests/factories.py),
  2) test - wywołania metod serwisów z konkretnymi parametrami,
  3) weryfikacja - wynik metod, stan bazy i audyt niezmienników (assert_no_violations).
Opis scenariuszy w formie algorytmów: etap5/TESTY.md (K1-K16).

Wyrocznia: audit.violations() ma niezależną od app/domain implementację wykrywania kolizji
w SQL, więc test nie sprawdza kodu tym samym kodem.
"""
import asyncio

import pytest
from sqlalchemy import select, text

from app.db import Session, run_transaction
from app.domain.enrollment_rules import Mode
from app.errors import Conflict
from app.models import Meeting, Notification, Section
from app.services import audit, catalog, enrollment, loaders, queries
from tests import factories as f
from tests.factories import t
from tests.test_enrollment import drop, enroll, entry_status, refusal, section_state

MON_10 = (1, "10:00", "11:30")
TUE_10 = (2, "10:00", "11:30")


async def assert_no_violations():
    async with Session() as s:
        assert await audit.violations(s) == []


async def plan_of(student, term):
    async with Session() as s:
        return {(p["course_code"], p["code"]) for p in await queries.student_plan(s, student, term)}


async def move_meeting(meeting_id, weekday, start, end, parity="ALL", room=None):
    """Dziekanat zmienia termin (UC32). Bez czyszczenia cache - jak w innym procesie API."""
    return await run_transaction(lambda s: catalog.update_meeting(s, meeting_id, weekday, t(start), t(end),
                                                                  parity, room))


async def meeting_of(section_id):
    async with Session() as s:
        return (await s.execute(select(Meeting.id).where(Meeting.section_id == section_id))).scalars().first()


async def version_of(section_id):
    async with Session() as s:
        return (await s.execute(select(Section.schedule_version).where(Section.id == section_id))).scalar_one()


@pytest.fixture
async def world():
    p = await f.program("INF")
    term = await f.term()
    await f.round_(term, [p])
    return p, term


# --- zapis bezpośredni ---------------------------------------------------------------

async def test_k1_direct_enrollment_with_conflict_is_refused(world):
    """K1: zapis do grupy nachodzącej na plan -> CONFLICT z nazwą kolidującej grupy, plan i licznik bez zmian."""
    p, term = world
    # 1. przygotowanie: student zapisany do IO L01 (pon 10:00-11:30); BD L01 pon 11:00-12:30
    io, bd = await f.course("IO"), await f.course("BD")
    io_l1 = await f.section(io, term, "L01", meetings=[MON_10])
    bd_l1 = await f.section(bd, term, "L01", meetings=[(1, "11:00", "12:30")])
    st = await f.student(p)
    await enroll(st, io_l1)
    # 2. test
    with pytest.raises(Conflict) as e:
        await enroll(st, bd_l1)
    # 3. weryfikacja
    assert e.value.code == "CONFLICT" and e.value.details == ["IO L01"]
    assert await plan_of(st, term) == {("IO", "L01")}
    assert (await section_state(bd_l1))[0] == 0
    await assert_no_violations()


@pytest.mark.parametrize("other, collides", [
    ((1, "11:30", "13:00"), False),            # styk: koniec 11:30 = początek 11:30
    ((2, "10:00", "11:30"), False),            # inny dzień
    ((1, "09:00", "10:01"), True),             # zachodzi o minutę
    ((1, "10:30", "11:00"), True),             # zawiera się
])
async def test_k2_time_boundaries(world, other, collides):
    """K2: granice przedziałów - styk nie jest kolizją, minuta wspólna już tak."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    b = await f.section(await f.course(), term, meetings=[other])
    st = await f.student(p)
    await enroll(st, a)
    if collides:
        assert await refusal(enroll(st, b)) == "CONFLICT"
    else:
        assert (await enroll(st, b)).status == "ENROLLED"
    await assert_no_violations()


@pytest.mark.parametrize("mine, other, collides", [
    ("ODD", "EVEN", False),                    # tygodnie nieparzyste i parzyste - nigdy razem
    ("ODD", "ODD", True),
    ("ODD", "ALL", True),
    ("EVEN", "ALL", True),
])
async def test_k3_week_parity(world, mine, other, collides):
    """K3: zajęcia co dwa tygodnie o tej samej porze kolidują tylko przy wspólnych tygodniach."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[(3, "12:00", "13:30", mine)])
    b = await f.section(await f.course(), term, meetings=[(3, "12:00", "13:30", other)])
    st = await f.student(p)
    await enroll(st, a)
    if collides:
        assert await refusal(enroll(st, b)) == "CONFLICT"
    else:
        assert (await enroll(st, b)).status == "ENROLLED"
    await assert_no_violations()


async def test_k4_second_meeting_of_section_collides(world):
    """K4: grupa z dwoma terminami - kolizja drugiego terminu też blokuje zapis."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[(4, "8:00", "9:30")])
    b = await f.section(await f.course(), term, meetings=[MON_10, (4, "9:00", "10:30")])
    st = await f.student(p)
    await enroll(st, a)
    assert await refusal(enroll(st, b)) == "CONFLICT"
    assert await refusal(enroll(st, b, Mode.ADMIN, await f.admin())) == "CONFLICT"   # dziekanat też nie może
    await assert_no_violations()


# --- listy oczekujących ---------------------------------------------------------------

async def test_k5_cannot_join_waitlist_of_colliding_section(world):
    """K5: pełna grupa kolidująca z planem - odmowa CONFLICT zamiast wpisu na listę."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    full = await f.section(await f.course(), term, capacity=1, meetings=[(1, "11:00", "12:00")])
    other, st = await f.students(p, 2)
    await enroll(other, full)
    await enroll(st, a)
    assert await refusal(enroll(st, full)) == "CONFLICT"
    assert (await section_state(full))[3] == []
    await assert_no_violations()


async def test_k6_waiting_student_who_enrolled_elsewhere_is_skipped(world):
    """K6: oczekujący zapisał się w międzyczasie na kolidujące zajęcia - przy awansie SKIPPED, awansuje następny."""
    p, term = world
    # 1. przygotowanie: grupa A (1 miejsce) zajęta przez s0; s1 i s2 czekają; s1 zapisuje się do B (koliduje z A)
    a = await f.section(await f.course("AAA"), term, capacity=1, meetings=[MON_10])
    b = await f.section(await f.course("BBB"), term, meetings=[(1, "11:00", "12:00")])
    s0, s1, s2 = await f.students(p, 3)
    await enroll(s0, a)
    assert (await enroll(s1, a)).position == 1
    assert (await enroll(s2, a)).position == 2
    await enroll(s1, b)                 # wolno: s1 tylko czeka na A, nie jest zapisany
    # 2. test: s0 się wypisuje -> awans
    events = await drop(s0, a)
    # 3. weryfikacja
    assert [(e.student_id, e.status) for e in events] == [(s1, "SKIPPED"), (s2, "PROMOTED")]
    assert "Kolizja" in events[0].reason and "BBB" in events[0].reason
    assert await plan_of(s1, term) == {("BBB", "L01")} and await plan_of(s2, term) == {("AAA", "L01")}
    async with Session() as s:
        notes = (await s.execute(select(Notification.user_id, Notification.type)
                                 .order_by(Notification.id))).all()
    assert notes == [(s1, "SKIPPED"), (s2, "PROMOTED")]
    await assert_no_violations()


async def test_k7_waiting_on_two_colliding_sections_gets_at_most_one(world):
    """K7: student czeka na dwie kolidujące ze sobą grupy, obie zwalniają się naraz -> dostaje co najwyżej jedną."""
    p, term = world
    for _ in range(5):                                   # powtórzenia: różne przeplecenia transakcji
        # 1. przygotowanie
        a = await f.section(await f.course(), term, capacity=1, meetings=[MON_10])
        b = await f.section(await f.course(), term, capacity=1, meetings=[(1, "11:00", "12:00")])
        holder_a, holder_b, st = await f.students(p, 3)
        await enroll(holder_a, a)
        await enroll(holder_b, b)
        await enroll(st, a)                              # czeka na A
        await enroll(st, b)                              # czeka na B (wolno: nie jest zapisany do A)
        # 2. test: dwa wypisy równolegle - dwa awanse tego samego studenta
        await asyncio.gather(drop(holder_a, a), drop(holder_b, b))
        # 3. weryfikacja: dokładnie jedna grupa, druga ma wolne miejsce, wpis drugiej SKIPPED
        in_a, in_b = st in (await section_state(a))[2], st in (await section_state(b))[2]
        assert in_a != in_b
        assert {await entry_status(st, a), await entry_status(st, b)} == {"PROMOTED", "SKIPPED"}
    await assert_no_violations()


async def test_k8_capacity_increase_promotes_only_non_conflicting(world):
    """K8: dziekanat zwiększa limit o 2 - awansują dwie pierwsze osoby bez kolizji, kolidujące są pomijane."""
    p, term = world
    a = await f.section(await f.course(), term, capacity=1, meetings=[MON_10])
    clash = await f.section(await f.course(), term, capacity=10, meetings=[(1, "9:00", "10:30")])
    s0, w1, w2, w3, w4 = await f.students(p, 5)
    await enroll(s0, a)
    for w in (w1, w2, w3, w4):
        await enroll(w, a)
    for w in (w1, w3):
        await enroll(w, clash)                           # w1 i w3 mają teraz kolizję z A
    events = await run_transaction(lambda s: enrollment.change_limits(s, a, capacity=3))
    assert [(e.student_id, e.status) for e in events] == [
        (w1, "SKIPPED"), (w2, "PROMOTED"), (w3, "SKIPPED"), (w4, "PROMOTED")]
    count, cap, enrolled, waiting = await section_state(a)
    assert (count, cap, enrolled, waiting) == (3, 3, {s0, w2, w4}, [])
    await assert_no_violations()


async def test_k9_promotion_races_with_direct_enrollment_of_same_student(world):
    """K9: awans z listy do A i równoległy zapis tego samego studenta do kolidującej B - nigdy obie."""
    p, term = world
    outcomes = set()
    for _ in range(10):
        a = await f.section(await f.course(), term, capacity=1, meetings=[MON_10])
        b = await f.section(await f.course(), term, meetings=[(1, "11:00", "12:00")])
        holder, st = await f.students(p, 2)
        await enroll(holder, a)
        await enroll(st, a)                              # czeka na A
        results = await asyncio.gather(drop(holder, a), enroll(st, b), return_exceptions=True)
        in_a, in_b = st in (await section_state(a))[2], st in (await section_state(b))[2]
        assert not (in_a and in_b)
        assert in_a or in_b                              # dostaje jedną z nich, zależnie od kolejności
        outcomes.add("A" if in_a else "B")
        if in_a:
            assert isinstance(results[1], Conflict) and results[1].code == "CONFLICT"
    await assert_no_violations()


# --- zmiana harmonogramu w trakcie tury (UC32) ----------------------------------------

async def test_k10_schedule_change_refused_when_enrolled_student_would_collide(world):
    """K10: przeniesienie terminu B na porę zajętą przez A u zapisanego studenta -> STUDENT_CONFLICT, nic się nie zmienia."""
    p, term = world
    # 1. przygotowanie: student w A (pon 10:00) i B (wt 10:00)
    a = await f.section(await f.course("AAA"), term, meetings=[MON_10])
    b = await f.section(await f.course("BBB"), term, meetings=[TUE_10])
    st = await f.student(p)
    await enroll(st, a)
    await enroll(st, b)
    meeting, version = await meeting_of(b), await version_of(b)
    # 2. test: dziekanat przenosi B na pon 10:30
    with pytest.raises(Conflict) as e:
        await move_meeting(meeting, 1, "10:30", "12:00")
    # 3. weryfikacja: odmowa ze wskazaniem studenta i grupy, termin i wersja bez zmian
    assert e.value.code == "STUDENT_CONFLICT"
    assert len(e.value.details) == 1 and "AAA L01" in e.value.details[0]
    async with Session() as s:
        m = await s.get(Meeting, meeting)
    assert (m.weekday, m.start_time) == (2, t("10:00"))
    assert await version_of(b) == version
    await assert_no_violations()


async def test_k11_schedule_change_allowed_bumps_version_and_notifies(world):
    """K11: zmiana bez kolizji przechodzi - nowa wersja harmonogramu, powiadomienia zapisanych i oczekujących."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    b = await f.section(await f.course(), term, capacity=1, meetings=[TUE_10])
    st, waiting = await f.students(p, 2)
    await enroll(st, a)
    await enroll(st, b)
    await enroll(waiting, b)
    meeting, version = await meeting_of(b), await version_of(b)
    await move_meeting(meeting, 3, "12:00", "13:30")
    assert await version_of(b) == version + 1
    async with Session() as s:
        notes = (await s.execute(select(Notification.user_id).where(Notification.type == "SCHEDULE_CHANGED")
                                 .order_by(Notification.user_id))).scalars().all()
        plan = await queries.student_plan(s, st, term)
    assert notes == sorted([st, waiting])
    assert {(m["weekday"], m["start"]) for p_ in plan if p_["section_id"] == b for m in p_["meetings"]} == {(3, "12:00")}
    await assert_no_violations()


async def test_k12_adding_meeting_checks_enrolled_students(world):
    """K12: nowy (dodatkowy) termin grupy też nie może kolidować z planem zapisanych; po wypisie - wolno."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    b = await f.section(await f.course(), term, meetings=[TUE_10])
    st = await f.student(p)
    await enroll(st, a)
    await enroll(st, b)
    add = lambda: run_transaction(lambda s: catalog.add_meeting(s, b, 1, t("11:00"), t("12:00"), "ALL", None))
    assert await refusal(add()) == "STUDENT_CONFLICT"
    await drop(st, a)
    assert await add() > 0
    await assert_no_violations()


async def test_k13_schedule_change_for_waiting_student_leads_to_skip(world):
    """K13: termin grupy zmienia się tak, że koliduje z planem OCZEKUJĄCEGO - zmiana dozwolona,
    ale przy awansie oczekujący jest pomijany (SKIPPED), a miejsce dostaje następny."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    b = await f.section(await f.course(), term, capacity=1, meetings=[TUE_10])
    holder, w1, w2 = await f.students(p, 3)
    await enroll(w1, a)                                  # w1 ma pon 10:00
    await enroll(holder, b)
    await enroll(w1, b)                                  # w1 czeka na B (wt - bez kolizji)
    await enroll(w2, b)
    await move_meeting(await meeting_of(b), 1, "10:30", "12:00")       # B przechodzi na pon 10:30
    events = await drop(holder, b)
    assert [(e.student_id, e.status) for e in events] == [(w1, "SKIPPED"), (w2, "PROMOTED")]
    await assert_no_violations()


async def test_k14_stale_cached_schedule_does_not_let_conflict_through(world):
    """K14: proces API ma w cache stary termin grupy (do 10 s), dziekanat zmienia termin w innym
    procesie. Zapis porównuje wersję harmonogramu pod blokadą grupy i wykrywa kolizję."""
    p, term = world
    a = await f.section(await f.course("AAA"), term, meetings=[MON_10])
    b = await f.section(await f.course("BBB"), term, meetings=[TUE_10])
    st = await f.student(p)
    await enroll(st, a)
    async with Session() as s:
        cached, _ = await loaders.load_target(s, b)                   # cache tego procesu: wt 10:00
    await move_meeting(await meeting_of(b), 1, "10:30", "12:00")       # "inny proces" - cache nie czyszczony
    async with Session() as s:
        still, _ = await loaders.load_target(s, b)
    assert still is cached and still.slots[0].weekday == 2            # cache naprawdę jest nieaktualny
    assert await refusal(enroll(st, b)) == "CONFLICT"                  # ...a mimo to kolizja wykryta
    assert await plan_of(st, term) == {("AAA", "L01")}
    await assert_no_violations()


async def test_k15_promotion_uses_current_schedule_not_cache(world):
    """K15: jak K14, ale miejsce zwalnia się w grupie ze zmienionym terminem: awans sprawdza
    oczekującego na aktualnym terminie (kolizja -> SKIPPED), nie na terminie z cache."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    b = await f.section(await f.course(), term, capacity=1, meetings=[TUE_10])
    holder, w = await f.students(p, 2)
    await enroll(w, a)
    await enroll(holder, b)
    await enroll(w, b)                                   # cache procesu: B we wtorek
    await move_meeting(await meeting_of(b), 1, "11:00", "12:00")
    events = await drop(holder, b)
    assert [(e.student_id, e.status) for e in events] == [(w, "SKIPPED")]
    await assert_no_violations()


async def test_k16_schedule_change_races_with_enrollment(world):
    """K16: równolegle (a) dziekanat przenosi termin B na porę kolidującą z A, (b) student zapisuje się.

    Wariant 1: student ma A i zapisuje się do B. Wariant 2: student ma B i zapisuje się do A.
    W każdym przepleceniu przechodzi dokładnie jedna operacja - druga dostaje odmowę
    (CONFLICT dla studenta albo STUDENT_CONFLICT dla dziekanatu). Kolizja nigdy nie powstaje.
    """
    p, term = world
    seen = set()
    for variant in (1, 2) * 6:
        a = await f.section(await f.course(), term, meetings=[MON_10])
        b = await f.section(await f.course(), term, meetings=[TUE_10])
        st = await f.student(p)
        await enroll(st, a if variant == 1 else b)
        target = b if variant == 1 else a
        results = await asyncio.gather(move_meeting(await meeting_of(b), 1, "10:30", "12:00"),
                                       enroll(st, target), return_exceptions=True)
        codes = sorted(r.code if isinstance(r, Conflict) else "OK" for r in results)
        assert codes in (["CONFLICT", "OK"], ["OK", "STUDENT_CONFLICT"]), results
        seen.add(tuple(codes))
        await assert_no_violations()


async def test_k17_audit_detects_conflict_written_around_the_rules(world):
    """K17: kontrola wyroczni - zapis z pominięciem serwisu (symulacja błędu w kodzie) jest wykrywany przez audyt."""
    p, term = world
    a = await f.section(await f.course(), term, meetings=[MON_10])
    b = await f.section(await f.course(), term, meetings=[(1, "11:00", "12:00")])
    st = await f.student(p)
    await enroll(st, a)
    async with Session() as s, s.begin():
        await s.execute(text("INSERT INTO enrollment (student_id, section_id, status, source) "
                             "VALUES (:st, :b, 'ENROLLED', 'ADMIN')"), {"st": st, "b": b})
        await s.execute(text("UPDATE section SET enrolled_count = enrolled_count + 1 WHERE id = :b"), {"b": b})
    async with Session() as s:
        problems = [v.problem for v in await audit.violations(s)]
    assert problems == [f"student {st} ma kolizję z grupą {b}"]
