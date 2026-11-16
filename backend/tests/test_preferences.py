"""Tura preferencyjna na prawdziwym PostgreSQL: zgłoszenia, symulacja, przydział końcowy, API.

Struktura testów jak w test_collisions.py (przygotowanie / test / weryfikacja).
Opis scenariuszy: etap5/TESTY.md (P1-P13).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app import worker
from app.api import deps
from app.db import Session, run_transaction
from app.domain.allocation import PreferenceInput
from app.domain.enrollment_rules import Mode
from app.errors import Conflict
from app.main import app
from app.models import AllocationRun, Enrollment, EnrollmentRound, Notification
from app.services import allocation, enrollment, preferences, rounds
from tests import factories as f
from tests.test_api import as_user
from tests.test_collisions import MON_10, TUE_10, assert_no_violations, plan_of
from tests.test_enrollment import drop, enroll, refusal, section_state


def P(course, weight, *sections):
    return PreferenceInput(course, weight, tuple(sections))


async def save(student, round_id, *items):
    return await run_transaction(lambda s: preferences.save_preferences(s, student, round_id, list(items)))


async def close(round_id):
    return await run_transaction(lambda s: rounds.close_round(s, round_id))


async def final(round_id, seed=1):
    return await run_transaction(lambda s: allocation.run_allocation(s, round_id, allocation.FINAL, seed=seed))


async def preview(round_id, seed=1):
    return await run_transaction(lambda s: allocation.run_allocation(s, round_id, allocation.PREVIEW, seed=seed))


async def view(student, round_id):
    async with Session() as s:
        return await allocation.student_view(s, student, round_id)


@pytest.fixture
async def world():
    """Kierunek INF z otwartą turą preferencyjną (pula 100 pkt) i katalog: IO (wykład + 2 laby), BD (1 lab)."""
    p = await f.program("INF")
    term = await f.term()
    rid = await f.round_(term, [p], mode="PREFERENCES", budget=100)
    io, bd = await f.course("IO"), await f.course("BD")
    sec = {
        "IO W": await f.section(io, term, "W01", kind="LECTURE", capacity=100, meetings=[(3, "8:00", "9:30")]),
        "IO L1": await f.section(io, term, "L01", capacity=1, meetings=[MON_10]),
        "IO L2": await f.section(io, term, "L02", capacity=1, meetings=[TUE_10]),
        "BD L1": await f.section(bd, term, "L01", capacity=2, meetings=[MON_10]),
    }
    return p, term, rid, io, bd, sec


# --- zgłoszenia ---------------------------------------------------------------------

async def test_p1_preference_round_blocks_queue_operations(world):
    """P1: w turze preferencyjnej nie ma zapisu ani wypisu w kolejce - tylko zgłoszenia."""
    p, term, rid, io, bd, sec = world
    st = await f.student(p)
    assert await refusal(enroll(st, sec["IO L1"])) == "ROUND_CLOSED"
    assert await refusal(drop(st, sec["IO L1"])) == "ROUND_CLOSED"


async def test_p2_save_and_modify_preferences(world):
    """P2: zgłoszenie i jego zmiana w trakcie tury - nowe zastępuje stare w całości."""
    p, term, rid, io, bd, sec = world
    st = await f.student(p)
    # 1-2. zgłoszenie: IO 60 pkt (L2 przed L1, wykład), BD 40 pkt
    r = await save(st, rid, P(io, 60, sec["IO L2"], sec["IO W"], sec["IO L1"]), P(bd, 40, sec["BD L1"]))
    assert (r.used_points, r.budget) == (100, 100)
    # 3. weryfikacja: rangi liczone osobno w każdym typie zajęć
    async with Session() as s:
        got = await preferences.get_preferences(s, st, rid)
    io_pref = next(c for c in got["courses"] if c["course_id"] == io)
    assert io_pref["weight"] == 60
    assert sorted((x["code"], x["kind"], x["rank"]) for x in io_pref["sections"]) == [
        ("L01", "LAB", 2), ("L02", "LAB", 1), ("W01", "LECTURE", 1)]
    # zmiana: tylko BD z wagą 100
    r = await save(st, rid, P(bd, 100, sec["BD L1"]))
    async with Session() as s:
        got = await preferences.get_preferences(s, st, rid)
    assert [(c["code"], c["weight"]) for c in got["courses"]] == [("BD", 100)] and got["used"] == 100


@pytest.mark.parametrize("case, code", [
    ("budget", "BUDGET_EXCEEDED"),
    ("foreign_section", "BAD_SECTION"),
    ("queue_round", "NOT_PREFERENCE_ROUND"),
    ("other_program", "ROUND_CLOSED"),
    ("closed", "ROUND_CLOSED"),
])
async def test_p3_invalid_submissions_are_refused(world, case, code):
    """P3: niepoprawne zgłoszenia - odmowa z kodem, poprzednie zgłoszenie zostaje."""
    p, term, rid, io, bd, sec = world
    st = await f.student(p)
    await save(st, rid, P(bd, 10, sec["BD L1"]))
    target = rid
    if case == "budget":
        items = [P(io, 60, sec["IO L1"]), P(bd, 41, sec["BD L1"])]
    elif case == "foreign_section":
        items = [P(io, 10, sec["BD L1"])]
    elif case == "queue_round":
        target, items = await f.round_(term, [p]), [P(bd, 10, sec["BD L1"])]
    elif case == "other_program":
        st, items = await f.student(await f.program("MAT")), [P(bd, 10, sec["BD L1"])]
    else:
        await close(rid)
        items = [P(bd, 20, sec["BD L1"])]
    with pytest.raises(Conflict) as e:
        await save(st, target, *items)
    assert e.value.code == code
    async with Session() as s:
        kept = await preferences.get_preferences(s, st, rid)
    if case not in ("other_program",):
        assert [c["weight"] for c in kept["courses"]] == [10]


async def test_p4_warnings_show_problems_early(world):
    """P4: zgłoszenie przyjęte, ale z ostrzeżeniami: brak wymagań, kolizja z planem, pełne grupy."""
    p, term, rid, io, bd, sec = world
    am1 = await f.course("AM1")
    zio = await f.course("ZIO", requires=[am1])
    zio_l = await f.section(zio, term, "L01", meetings=[(4, "8:00", "9:30")])
    old = await f.section(await f.course("OLD"), term, meetings=[MON_10])
    st, other = await f.students(p, 2)
    # student ma już (np. z decyzji dziekanatu) zajęcia pon 10:00
    await run_transaction(lambda s: enrollment.enroll(s, st, old, mode=Mode.ADMIN))
    r = await save(st, rid, P(zio, 20, zio_l), P(bd, 30, sec["BD L1"]), P(io, 50, sec["IO W"], sec["IO L2"]))
    warnings = {w["course_id"]: w["code"] for w in r.warnings}
    assert warnings == {zio: "PREREQUISITES", bd: "CONFLICT"}


async def test_p5_save_racing_with_round_close(world):
    """P5: zamknięcie tury w trakcie zapisu preferencji: zgłoszenie albo wchodzi do przydziału,
    albo jest odrzucone (ROUND_CLOSED) - nigdy nie ginie po cichu."""
    p, term, rid, io, bd, sec = world
    for i in range(6):
        rid_i = await f.round_(term, [p], mode="PREFERENCES", name=f"wyścig {i}")
        st = await f.student(p)
        results = await asyncio.gather(save(st, rid_i, P(bd, 50, sec["BD L1"])), close(rid_i),
                                       return_exceptions=True)
        async with Session() as s:
            stored = (await preferences.get_preferences(s, st, rid_i))["courses"]
        if isinstance(results[0], Conflict):
            assert results[0].code == "ROUND_CLOSED" and stored == []
        else:
            assert [c["weight"] for c in stored] == [50]
            summary = await final(rid_i)
            assert summary.requests == 1


# --- przydział ------------------------------------------------------------------------

async def test_p6_preview_does_not_enroll_and_keeps_latest_only(world):
    """P6: symulacja w trakcie tury - wynik widoczny dla studenta, ale bez zapisów; trzymana tylko najnowsza."""
    p, term, rid, io, bd, sec = world
    a, b = await f.students(p, 2)
    await save(a, rid, P(io, 70, sec["IO W"], sec["IO L1"]))
    await save(b, rid, P(io, 30, sec["IO W"], sec["IO L1"]))
    first = await preview(rid)
    second = await preview(rid)
    async with Session() as s:
        runs = (await s.execute(select(AllocationRun.id, AllocationRun.kind))).all()
        enrolled = (await s.execute(select(func.count()).select_from(Enrollment))).scalar_one()
    assert runs == [(second.run_id, "PREVIEW")] and first.run_id != second.run_id
    assert enrolled == 0
    va, vb = await view(a, rid), await view(b, rid)
    assert va["run"]["kind"] == "PREVIEW"
    assert [(x["status"], sorted(x["sections"])) for x in va["results"]] == [("ASSIGNED", ["IO L01", "IO W01"])]
    assert vb["results"][0]["status"] == "UNASSIGNED" and "Brak miejsc" in vb["results"][0]["reason"]


async def test_p7_student_reacts_to_preview_by_changing_weights(world):
    """P7: student widzi w symulacji, że nie dostanie IO, podnosi wagę - kolejna symulacja to odzwierciedla."""
    p, term, rid, io, bd, sec = world
    a, b = await f.students(p, 2)
    await save(a, rid, P(io, 50, sec["IO W"], sec["IO L1"]), P(bd, 50, sec["BD L1"]))
    await save(b, rid, P(io, 40, sec["IO W"], sec["IO L1"]), P(bd, 60, sec["BD L1"]))
    await preview(rid)
    assert {x["code"]: x["status"] for x in (await view(b, rid))["results"]}["IO"] == "UNASSIGNED"
    await save(b, rid, P(io, 90, sec["IO W"], sec["IO L1"]), P(bd, 10, sec["BD L1"]))
    await preview(rid)
    assert {x["code"]: x["status"] for x in (await view(b, rid))["results"]}["IO"] == "ASSIGNED"


async def test_p8_final_allocation_end_to_end(world):
    """P8: zamknięcie tury -> worker robi przydział końcowy: zapisy ALLOCATION, liczniki, powiadomienia,
    brak kolizji; ponowne uruchomienie nic nie zmienia, tury nie da się otworzyć ponownie."""
    p, term, rid, io, bd, sec = world
    # 1. przygotowanie: 3 osoby chcą IO (2 laby po 1 miejscu), wszyscy chcą BD (2 miejsca, pon 10 = IO L1)
    a, b, c = await f.students(p, 3)
    await save(a, rid, P(io, 70, sec["IO W"], sec["IO L1"], sec["IO L2"]), P(bd, 30, sec["BD L1"]))
    await save(b, rid, P(io, 60, sec["IO W"], sec["IO L1"]), P(bd, 40, sec["BD L1"]))
    await save(c, rid, P(io, 20, sec["IO W"], sec["IO L2"]), P(bd, 80, sec["BD L1"]))
    # 2. test
    await close(rid)
    await worker.allocate_closed_rounds()
    await worker.allocate_closed_rounds()                        # drugi przebieg (np. druga instancja)
    # 3. weryfikacja
    plans = {st: await plan_of(st, term) for st in (a, b, c)}
    for st_plan in plans.values():
        assert not ({("IO", "L01"), ("BD", "L01")} <= st_plan)   # pon 10:00 - co najwyżej jedno
    assert ("IO", "L01") in plans[b] and ("IO", "W01") in plans[b]   # b: IO tylko z L1 -> a ustępuje do L2
    assert ("IO", "L02") in plans[a] and ("BD", "L01") in plans[c]
    assert (await section_state(sec["IO L1"]))[0] == 1 and (await section_state(sec["IO L2"]))[0] == 1
    async with Session() as s:
        sources = set((await s.execute(select(Enrollment.source))).scalars())
        finals = (await s.execute(select(func.count()).select_from(AllocationRun)
                                  .where(AllocationRun.kind == "FINAL"))).scalar_one()
        types = {(n.user_id, n.type) for n in (await s.execute(select(Notification))).scalars()}
    assert sources == {"ALLOCATION"} and finals == 1
    assert (a, "ALLOCATED") in types and (b, "NOT_ALLOCATED") in types       # b nie dostał BD (kolizja z IO L1)
    assert await refusal(final(rid)) == "ALREADY_ALLOCATED"
    assert await refusal(run_transaction(lambda s: rounds.open_round(s, rid))) == "ALREADY_ALLOCATED"
    await assert_no_violations()


async def test_p9_final_allocation_respects_existing_plans_and_seats_taken_meanwhile(world):
    """P9: między zgłoszeniem a przydziałem inny kierunek (tura kolejkowa) zajął miejsca, a student
    dostał zajęcia od dziekanatu - przydział końcowy widzi stan z chwili zamknięcia tury."""
    p, term, rid, io, bd, sec = world
    mat = await f.program("MAT")
    await f.round_(term, [mat])                                  # równoległa tura kolejkowa MAT
    st = await f.student(p)
    m1, m2 = await f.students(mat, 2)
    await save(st, rid, P(bd, 50, sec["BD L1"]), P(io, 50, sec["IO W"], sec["IO L1"], sec["IO L2"]))
    await enroll(m1, sec["BD L1"])
    await enroll(m2, sec["BD L1"])                               # BD L1 pełna
    await enroll(st, sec["IO L2"], Mode.ADMIN)
    await close(rid)
    summary = await final(rid)
    assert summary.assigned == 1                                 # IO: tylko brakujący wykład
    assert await plan_of(st, term) == {("IO", "L02"), ("IO", "W01")}
    results = {x["code"]: x for x in (await view(st, rid))["results"]}
    assert results["BD"]["status"] == "UNASSIGNED" and "Brak miejsc" in results["BD"]["reason"]
    await assert_no_violations()


async def test_p10_final_requires_closed_round(world):
    """P10: przydziału końcowego nie da się uruchomić w otwartej turze ani w turze kolejkowej."""
    p, term, rid, io, bd, sec = world
    assert await refusal(final(rid)) == "ROUND_NOT_CLOSED"
    queue = await f.round_(term, [p], status="CLOSED")
    assert await refusal(final(queue)) == "NOT_PREFERENCE_ROUND"


async def test_p11_allocation_is_reproducible_with_seed(world):
    """P11: remis wag rozstrzyga los z ziarnem zapisanym w allocation_run - ten sam seed, ten sam wynik."""
    p, term, rid, io, bd, sec = world
    students = await f.students(p, 6)
    for st in students:
        await save(st, rid, P(io, 50, sec["IO W"], sec["IO L1"]))
    winners = set()
    for _ in range(3):
        await preview(rid, seed=12345)
        statuses = [(await view(st, rid))["results"][0]["status"] for st in students]
        winners.add(tuple(st for st, status in zip(students, statuses) if status == "ASSIGNED"))
    assert len(winners) == 1 and len(next(iter(winners))) == 1


async def test_p12_schedule_change_after_submission_is_respected(world):
    """P12: dziekanat zmienia termin grupy po zgłoszeniu; przydział używa aktualnego terminu
    (lab przeniesiony na porę wykładu IO nie zostanie przydzielony razem z nim)."""
    p, term, rid, io, bd, sec = world
    from tests.test_collisions import meeting_of, move_meeting
    st = await f.student(p)
    await save(st, rid, P(io, 100, sec["IO W"], sec["IO L1"]))
    await move_meeting(await meeting_of(sec["IO L1"]), 3, "8:30", "10:00")   # na wykład IO
    await close(rid)
    summary = await final(rid)
    assert summary.assigned == 0
    assert "kolidują ze sobą" in (await view(st, rid))["results"][0]["reason"]


# --- API -------------------------------------------------------------------------------

async def test_p13_api_flow():
    """P13: pełny przepływ przez REST API: dziekanat tworzy turę, student składa i zmienia
    preferencje, podgląd, zamknięcie, przydział, raport."""
    deps.catalog_cache.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        p, term = await f.program("INF"), await f.term()
        c = await f.course("IO")
        w = await f.section(c, term, "W01", kind="LECTURE", capacity=50, meetings=[(3, "8:00", "9:30")])
        lab = await f.section(c, term, "L01", capacity=1, meetings=[MON_10])
        a, b = await f.students(p, 2)
        adm = await as_user(client, await f.admin())
        now = datetime.now(timezone.utc)
        r = await client.post("/api/admin/rounds", headers=adm, json={
            "term_id": term, "name": "Preferencje INF", "program_ids": [p], "mode": "PREFERENCES",
            "points_budget": 100, "opens_at": (now - timedelta(minutes=5)).isoformat(),
            "closes_at": (now + timedelta(hours=1)).isoformat()})
        rid = r.json()["id"]
        assert (await client.post(f"/api/admin/rounds/{rid}/open", headers=adm)).status_code == 200

        ha, hb = await as_user(client, a), await as_user(client, b)
        rounds_ = (await client.get(f"/api/me/terms/{term}/rounds", headers=ha)).json()
        assert [(x["mode"], x["points_budget"]) for x in rounds_] == [("PREFERENCES", 100)]
        body = lambda wt: {"courses": [{"course_id": c, "weight": wt, "section_ids": [w, lab]}]}
        r = await client.put(f"/api/me/rounds/{rid}/preferences", headers=ha, json=body(40))
        assert r.status_code == 200 and r.json()["used_points"] == 40
        r = await client.put(f"/api/me/rounds/{rid}/preferences", headers=hb, json=body(101))
        assert r.status_code == 409 and r.json()["code"] == "BUDGET_EXCEEDED"
        r = await client.put(f"/api/me/rounds/{rid}/preferences", headers=hb, json=body(0))
        assert r.status_code == 422                               # waga < 1 odrzuca już walidacja wejścia
        r = await client.put(f"/api/me/rounds/{rid}/preferences", headers=hb,
                             json={"courses": [{"course_id": c, "weight": 60, "section_ids": [w, lab]}]})
        assert r.json()["used_points"] == 60
        r = await client.post("/api/me/enrollments", headers=ha, json={"section_id": lab})
        assert r.json()["code"] == "ROUND_CLOSED"

        assert (await client.post(f"/api/admin/rounds/{rid}/allocation/preview", headers=adm, json={})).status_code == 200
        mine = (await client.get(f"/api/me/rounds/{rid}/allocation", headers=hb)).json()
        assert mine["run"]["kind"] == "PREVIEW" and mine["results"][0]["status"] == "ASSIGNED"
        r = await client.post(f"/api/admin/rounds/{rid}/allocation", headers=adm, json={})
        assert r.json()["code"] == "ROUND_NOT_CLOSED"
        await client.post(f"/api/admin/rounds/{rid}/close", headers=adm)
        r = await client.post(f"/api/admin/rounds/{rid}/allocation", headers=adm, json={"seed": 7})
        assert r.status_code == 200 and r.json()["assigned"] == 1
        report = (await client.get(f"/api/admin/rounds/{rid}/allocation", headers=adm)).json()
        assert report["run"]["kind"] == "FINAL" and report["courses"][0]["requests"] == 2
        assert (await client.get(f"/api/me/terms/{term}/plan", headers=hb)).json()[0]["source"] == "ALLOCATION"
        assert (await client.get("/api/admin/audit", headers=adm)).json() == []
