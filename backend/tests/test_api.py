"""API: uwierzytelnianie, role, przepływy studenta, prowadzącego i dziekanatu."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api import deps
from app.main import app
from app.traffic import Gate, RateLimiter
from tests import factories as f


@pytest.fixture
async def client():
    deps.catalog_cache.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def login(client, email, password="haslo") -> dict:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def email_of(uid):
    from sqlalchemy import select
    from app.db import Session
    from app.models import User
    async with Session() as s:
        return (await s.execute(select(User.email).where(User.id == uid))).scalar_one()


async def as_user(client, uid):
    return await login(client, await email_of(uid))


async def test_login_and_roles(client):
    p = await f.program()
    st = await f.student(p)
    r = await client.post("/api/auth/login", json={"email": await email_of(st), "password": "złe"})
    assert r.status_code == 401 and r.json()["code"] == "BAD_CREDENTIALS"
    h = await as_user(client, st)
    assert (await client.get("/api/me", headers=h)).json()["role"] == "STUDENT"
    assert (await client.get("/api/admin/audit", headers=h)).status_code == 403
    assert (await client.get("/api/me")).status_code == 401


async def test_admin_builds_catalog_and_student_enrolls(client):
    adm = await as_user(client, await f.admin())
    post = lambda url, body: client.post(url, json=body, headers=adm)

    prog = (await post("/api/admin/programs", {"code": "INF", "name": "Informatyka"})).json()["id"]
    term = (await post("/api/admin/terms", {"code": "2026Z", "starts_on": "2026-10-01",
                                             "ends_on": "2027-02-15"})).json()["id"]
    room = (await post("/api/admin/rooms", {"building": "C-2", "number": "101", "seats": 20})).json()["id"]
    am1 = (await post("/api/admin/courses", {"code": "AM1", "name": "Analiza 1", "ects": 6})).json()["id"]
    io = (await post("/api/admin/courses", {"code": "IO", "name": "Inżynieria opr.", "ects": 5})).json()["id"]
    assert (await post(f"/api/admin/courses/{io}/prerequisites", {"required_course_id": am1})).status_code == 200
    r = await post(f"/api/admin/courses/{am1}/prerequisites", {"required_course_id": io})
    assert r.status_code == 409 and r.json()["code"] == "PREREQUISITE_CYCLE"

    lab = (await post("/api/admin/sections", {"course_id": io, "term_id": term, "code": "L01", "kind": "LAB",
                                               "capacity": 15})).json()["id"]
    big = (await post("/api/admin/sections", {"course_id": io, "term_id": term, "code": "W01", "kind": "LECTURE",
                                               "capacity": 150})).json()["id"]
    meeting = {"weekday": 1, "start": "10:00", "end": "11:30", "room_id": room}
    assert (await post(f"/api/admin/sections/{lab}/meetings", meeting)).status_code == 200
    r = await post(f"/api/admin/sections/{big}/meetings", meeting)
    assert r.json()["code"] == "ROOM_TOO_SMALL"
    lec = (await post("/api/admin/users", {"email": "k@uczelnia.pl", "password": "haslo12", "full_name": "Kowalski",
                                            "role": "LECTURER", "title": "dr", "department": "KI"})).json()["id"]
    assert (await post(f"/api/admin/sections/{lab}/lecturers", {"lecturer_id": lec})).status_code == 200
    r = await post(f"/api/admin/sections/{big}/meetings", {"weekday": 1, "start": "11:00", "end": "12:00"})
    assert r.status_code == 200                                   # wykład bez prowadzącego i bez sali
    assert (await post(f"/api/admin/sections/{big}/lecturers", {"lecturer_id": lec})).json()["code"] == "LECTURER_BUSY"

    st = (await post("/api/admin/users", {"email": "ania@uczelnia.pl", "password": "haslo12", "full_name": "Ania",
                                           "role": "STUDENT", "index_no": "400001", "program_id": prog,
                                           "semester": 3})).json()["id"]
    r = await post("/api/admin/grades/import", {"csv": "index_no,course_code,term_code,grade\n"
                                                       "400001,AM1,2026Z,4.5\n400002,AM1,2026Z,4.5\n"})
    assert r.json()["imported"] == 1 and "nieznany indeks" in r.json()["errors"][0]

    now = datetime.now(timezone.utc)
    rnd = (await post("/api/admin/rounds", {"term_id": term, "name": "Tura INF", "program_ids": [prog],
                                             "opens_at": (now + timedelta(hours=1)).isoformat(),
                                             "closes_at": (now + timedelta(hours=2)).isoformat()})).json()["id"]

    h = await login(client, "ania@uczelnia.pl", "haslo12")
    courses = (await client.get(f"/api/terms/{term}/courses?q=IO", headers=h)).json()
    assert [c["code"] for c in courses] == ["IO"]
    status = (await client.get(f"/api/me/terms/{term}/courses/{io}", headers=h)).json()
    assert status["round_open"] is False
    r = await client.post("/api/me/enrollments", json={"section_id": lab}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "ROUND_CLOSED"

    assert (await client.post(f"/api/admin/rounds/{rnd}/open", headers=adm)).status_code == 200
    rounds = (await client.get(f"/api/me/terms/{term}/rounds", headers=h)).json()
    assert [r["status"] for r in rounds] == ["OPEN"]
    r = await client.post("/api/me/enrollments", json={"section_id": lab}, headers=h)
    assert r.json()["status"] == "ENROLLED"
    plan = (await client.get(f"/api/me/terms/{term}/plan", headers=h)).json()
    assert [(p["course_code"], p["code"], p["meetings"][0]["room"]) for p in plan] == [("IO", "L01", "C-2 101")]
    status = (await client.get(f"/api/me/terms/{term}/courses/{io}", headers=h)).json()
    states = {s["section_id"]: s for s in status["sections"]}
    assert states[lab]["state"] == "ENROLLED"
    assert states[big]["state"] == "BLOCKED" and states[big]["refusals"][0]["code"] == "CONFLICT"

    hl = await login(client, "k@uczelnia.pl", "haslo12")
    sections = (await client.get(f"/api/lecturer/terms/{term}/sections", headers=hl)).json()
    assert [s["id"] for s in sections] == [lab]
    roster = (await client.get(f"/api/sections/{lab}/roster", headers=hl)).json()
    assert [s["index_no"] for s in roster["enrolled"]] == ["400001"]
    assert (await client.get(f"/api/sections/{big}/roster", headers=hl)).status_code == 403

    assert (await client.delete(f"/api/me/enrollments/{lab}", headers=h)).status_code == 200
    assert (await client.get(f"/api/admin/audit", headers=adm)).json() == []


async def test_waitlist_flow_and_notifications(client):
    p, t = await f.program(), await f.term()
    await f.round_(t, [p])
    sec = await f.section(await f.course(), t, capacity=1)
    a, b = await f.students(p, 2)
    ha, hb = await as_user(client, a), await as_user(client, b)
    await client.post("/api/me/enrollments", json={"section_id": sec}, headers=ha)
    r = await client.post("/api/me/enrollments", json={"section_id": sec}, headers=hb)
    assert r.json() == {"status": "WAITLISTED", "section_id": sec, "position": 1, "cancelled_waitlists": []}
    wl = (await client.get(f"/api/me/terms/{t}/waitlist", headers=hb)).json()
    assert [(w["status"], w["position"]) for w in wl] == [("WAITING", 1)]
    await client.delete(f"/api/me/enrollments/{sec}", headers=ha)
    notes = (await client.get("/api/me/notifications", headers=hb)).json()
    assert [n["type"] for n in notes] == ["PROMOTED"] and not notes[0]["read"]
    await client.post("/api/me/notifications/read", headers=hb)
    assert (await client.get("/api/me/notifications", headers=hb)).json()[0]["read"]


async def test_rate_limit_and_gate(client, monkeypatch):
    p, t = await f.program(), await f.term()
    await f.round_(t, [p])
    sec = await f.section(await f.course(), t, capacity=100)
    st = await f.student(p)
    h = await as_user(client, st)
    monkeypatch.setattr(deps, "rate_limiter", RateLimiter(per_minute=2))
    await client.post("/api/me/enrollments", json={"section_id": sec}, headers=h)
    await client.post("/api/me/enrollments", json={"section_id": sec}, headers=h)
    r = await client.post("/api/me/enrollments", json={"section_id": sec}, headers=h)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1

    gate = Gate(concurrency=1, timeout=0.05)
    monkeypatch.setattr(deps, "rate_limiter", RateLimiter(per_minute=1))
    monkeypatch.setattr(deps, "write_gate", gate)
    async with gate.slot():                                         # zajmujemy jedyny slot
        r = await client.post("/api/me/enrollments", json={"section_id": sec}, headers=h)
    assert r.status_code == 503 and r.json()["code"] == "OVERLOADED"
    # odrzucenie przez bramkę nie zużyło limitu (1 na minutę)
    r = await client.post("/api/me/enrollments", json={"section_id": sec}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_ENROLLED"


async def test_catalog_cache_coalesces_misses():
    from app.traffic import TTLCache
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    cache = TTLCache(ttl=10)
    assert await asyncio.gather(*(cache.get("k", load) for _ in range(50))) == [1] * 50
    assert calls == 1
