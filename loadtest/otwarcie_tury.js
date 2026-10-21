// Test obciążeniowy: otwarcie tury zapisów (k6).
//
// Wszyscy studenci wybranych kierunków zaczynają w tej samej sekundzie: przeglądają
// katalog, zapisują się na 6 przedmiotów (wykład + laboratorium) i sprawdzają plan.
// Przy 429/503 czekają Retry-After i ponawiają, tak jak frontend.
//
//   docker compose run --rm api python -m app.seed --scale university [--open-all]
//   docker run --rm --network usosv2_default -v "$PWD/loadtest:/s" grafana/k6:1.3.0 run \
//       -e PROGRAMS=1 -e PER_PROGRAM=1000 /s/otwarcie_tury.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import exec from "k6/execution";

const BASE = __ENV.BASE || "http://web";
const PROGRAMS = Number(__ENV.PROGRAMS || 1);          // ile kierunków ma turę naraz
const PER_PROGRAM = Number(__ENV.PER_PROGRAM || 1000); // studentów na kierunek
const COURSES = Number(__ENV.COURSES || 6);            // przedmiotów na studenta
const TERM = Number(__ENV.TERM || 2);
const VUS = PROGRAMS * PER_PROGRAM;

export const options = {
  setupTimeout: "10m",
  scenarios: {
    otwarcie: { executor: "per-vu-iterations", vus: VUS, iterations: 1, maxDuration: "10m" },
  },
  thresholds: {
    "http_req_duration{op:enroll}": ["p(95)<2000"],
    "http_req_failed{op:enroll}": ["rate<0.01"],
    checks: ["rate>0.99"],
  },
};

const outcomes = new Counter("wynik_zapisu");
const enrollTime = new Trend("czas_zapisu_z_ponowieniami", true);
const retries = new Counter("ponowienia_429_503");

// 409 to poprawna odmowa (kolizja, brak wymagań), nie błąd systemu.
http.setResponseCallback(http.expectedStatuses(200, 409));

const json = { headers: { "Content-Type": "application/json" } };
const authed = (token) => ({ headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } });

export function setup() {
  // Logowanie przed turą (token ważny kilka godzin), równolegle po 50.
  const tokens = [];
  for (let start = 0; start < VUS; start += 50) {
    const batch = [];
    for (let i = start; i < Math.min(VUS, start + 50); i++) {
      const p = Math.floor(i / PER_PROGRAM), s = i % PER_PROGRAM;
      const index = 100001 + p * 1000 + s;     // seed: 1000 kont na kierunek
      batch.push(["POST", `${BASE}/api/auth/login`, JSON.stringify({ email: `s${index}@uczelnia.pl`, password: "haslo123" }), json]);
    }
    for (const r of http.batch(batch)) tokens.push(r.json("token"));
  }
  // Grupy przedmiotów każdego kierunku (wykład + laboratoria).
  const h = authed(tokens[0]);
  const programs = [];
  for (let p = 0; p < PROGRAMS; p++) {
    const code = `K${String(p + 1).padStart(2, "0")}`;
    const list = http.get(`${BASE}/api/terms/${TERM}/courses?q=${code}-&limit=200`, h).json();
    programs.push(list.map((c) => {
      const d = http.get(`${BASE}/api/terms/${TERM}/courses/${c.id}`, h).json();
      return { id: c.id, lecture: d.sections.find((s) => s.kind === "LECTURE").id,
               labs: d.sections.filter((s) => s.kind === "LAB").map((s) => s.id) };
    }));
  }
  return { tokens, programs };
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function enroll(h, sectionId) {
  const t0 = Date.now();
  for (let attempt = 0; attempt < 6; attempt++) {
    const r = http.post(`${BASE}/api/me/enrollments`, JSON.stringify({ section_id: sectionId }), { ...h, tags: { op: "enroll" } });
    if (r.status === 429 || r.status === 503) {
      retries.add(1);
      sleep((Number(r.headers["Retry-After"]) || 1) * (1 + Math.random()));
      continue;
    }
    enrollTime.add(Date.now() - t0);
    const body = r.json();
    const result = r.status === 200 ? body.status : body.code;
    outcomes.add(1, { wynik: result });
    check(r, { "zapis: odpowiedź 200 albo odmowa 409": (x) => x.status === 200 || x.status === 409 });
    return result;
  }
  outcomes.add(1, { wynik: "NIE_UDALO_SIE" });
  check(null, { "zapis: odpowiedź 200 albo odmowa 409": () => false });
  return null;
}

export default function (data) {
  const i = exec.vu.idInTest - 1;
  const h = authed(data.tokens[i]);
  const courses = shuffle([...data.programs[Math.floor(i / PER_PROGRAM)]]).slice(0, COURSES);

  http.get(`${BASE}/api/me/terms/${TERM}/rounds`, { ...h, tags: { op: "read" } });
  for (const c of courses) {
    http.get(`${BASE}/api/terms/${TERM}/courses/${c.id}`, { ...h, tags: { op: "read" } });
    const status = http.get(`${BASE}/api/me/terms/${TERM}/courses/${c.id}`, { ...h, tags: { op: "status" } });
    check(status, { "status grup 200": (r) => r.status === 200 });
    if (enroll(h, c.lecture) === "PREREQUISITES") continue;
    // laboratorium: próbujemy do 3 losowych grup, aż któraś pasuje do planu
    for (const lab of shuffle([...c.labs]).slice(0, 3)) {
      const res = enroll(h, lab);
      if (res === "ENROLLED" || res === "WAITLISTED" || res === null) break;
    }
  }
  const plan = http.get(`${BASE}/api/me/terms/${TERM}/plan`, { ...h, tags: { op: "read" } });
  check(plan, { "plan 200": (r) => r.status === 200 });
}

export function teardown() {
  console.log("Po teście sprawdź niezmienniki: GET /api/admin/audit (powinno być []).");
}
