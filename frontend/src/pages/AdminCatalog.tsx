import { useState, type FormEvent } from "react";
import { api, ApiError, DAYS, KINDS, meetingText, type CourseDetail, type CourseSummary, type User } from "../api";
import { useApp } from "../App";
import { SeatBar, useLoad } from "../components";

interface RoomT { id: number; building: string; number: string; seats: number }

export function useRun() {
  const { toast } = useApp();
  return async (fn: () => Promise<unknown>, ok: string, after?: () => void) => {
    try { await fn(); toast(ok); } catch (e) {
      toast(e instanceof ApiError ? e.message + (e.details.length ? ` (${e.details.join("; ")})` : "") : "Błąd.", true);
    }
    after?.();
  };
}

export default function AdminCatalog() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [courses, reload] = useLoad<CourseSummary[]>(`/api/admin/courses?limit=50${query ? `&q=${encodeURIComponent(query)}` : ""}`);
  const run = useRun();
  const [nc, setNc] = useState({ code: "", name: "", ects: 5 });

  const create = (e: FormEvent) => {
    e.preventDefault();
    run(() => api("/api/admin/courses", { body: nc }), "Dodano kurs.", () => { setNc({ code: "", name: "", ects: 5 }); reload(); });
  };

  return (
    <main>
      <div className="grid2">
        <section className="card">
          <h2>Kursy</h2>
          <form className="search" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
            <input placeholder="kod lub nazwa" value={q} onChange={(e) => setQ(e.target.value)} /><button className="primary">Szukaj</button>
          </form>
          {courses?.map((c) => (
            <div key={c.id} className="course">
              <h3><button onClick={() => setOpen(c.id)}>{c.code} – {c.name}</button></h3>
              <div className="meta">id {c.id} · {c.ects} ECTS</div>
            </div>
          ))}
        </section>
        <section className="card">
          <h2>Nowy kurs</h2>
          <form onSubmit={create} style={{ display: "grid", gap: 8 }}>
            <input placeholder="kod, np. IO" value={nc.code} onChange={(e) => setNc({ ...nc, code: e.target.value })} required />
            <input placeholder="nazwa" value={nc.name} onChange={(e) => setNc({ ...nc, name: e.target.value })} required />
            <label className="row">ECTS <input type="number" min={1} value={nc.ects} onChange={(e) => setNc({ ...nc, ects: Number(e.target.value) })} style={{ width: 80 }} /></label>
            <button className="primary">Dodaj</button>
          </form>
        </section>
      </div>
      {open && <CourseAdmin courseId={open} />}
    </main>
  );
}

function CourseAdmin({ courseId }: { courseId: number }) {
  const { term } = useApp();
  const [d, reload] = useLoad<CourseDetail>(`/api/admin/courses/${courseId}?term_id=${term!.id}`);
  const [rooms] = useLoad<RoomT[]>("/api/admin/rooms");
  const [lecturers] = useLoad<User[]>("/api/admin/users?role=LECTURER");
  const run = useRun();
  const [req, setReq] = useState("");
  const [ns, setNs] = useState({ code: "", kind: "LAB", capacity: 15, waitlist_limit: 50 });
  if (!d) return null;

  const addPrereq = async (e: FormEvent) => {
    e.preventDefault();
    const found = await api<CourseSummary[]>(`/api/admin/courses?q=${encodeURIComponent(req)}`);
    const c = found.find((x) => x.code.toLowerCase() === req.toLowerCase());
    if (!c) return run(() => Promise.reject(new ApiError(404, "NF", `Nie ma kursu ${req}.`)), "");
    run(() => api(`/api/admin/courses/${courseId}/prerequisites`, { body: { required_course_id: c.id } }), "Dodano wymaganie.", reload);
    setReq("");
  };

  return (
    <section className="card">
      <h2>{d.code} – {d.name} <span className="muted">({term!.code})</span></h2>
      <div className="row">
        <b>Wymagania:</b>
        {d.prerequisites.length === 0 && <span className="muted">brak</span>}
        {d.prerequisites.map((p) => (
          <span key={p.id} className="tag gray">{p.code}{" "}
            <button className="link" style={{ padding: 0, background: "none" }} title="usuń"
                    onClick={() => run(() => api(`/api/admin/courses/${courseId}/prerequisites/${p.id}`, { method: "DELETE" }), "Usunięto.", reload)}>×</button>
          </span>
        ))}
        <form className="inline" onSubmit={addPrereq}><input placeholder="kod kursu wymaganego" value={req} onChange={(e) => setReq(e.target.value)} required /><button className="secondary">Dodaj</button></form>
      </div>

      <h3 style={{ marginTop: 12 }}>Grupy</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Grupa</th><th>Terminy</th><th>Prowadzący</th><th>Miejsca</th><th>Limity</th></tr></thead>
          <tbody>
            {d.sections.map((s) => (
              <tr key={s.id}>
                <td><b>{s.code}</b> {KINDS[s.kind]}<div className="muted">id {s.id}</div></td>
                <td>
                  {s.meetings.map((m) => (
                    <div key={m.id}>{meetingText(m)} <button className="danger" style={{ padding: "0 6px" }}
                      onClick={() => run(() => api(`/api/admin/meetings/${m.id}`, { method: "DELETE" }), "Usunięto termin.", reload)}>×</button></div>
                  ))}
                  <MeetingForm sectionId={s.id} rooms={rooms ?? []} onDone={reload} />
                </td>
                <td>
                  {s.lecturers.map((l) => (
                    <div key={l.id}>{l.name} <button className="danger" style={{ padding: "0 6px" }}
                      onClick={() => run(() => api(`/api/admin/sections/${s.id}/lecturers/${l.id}`, { method: "DELETE" }), "Usunięto.", reload)}>×</button></div>
                  ))}
                  <select defaultValue="" onChange={(e) => e.target.value && run(() => api(`/api/admin/sections/${s.id}/lecturers`,
                    { body: { lecturer_id: Number(e.target.value) } }), "Przypisano prowadzącego.", reload)}>
                    <option value="">+ prowadzący</option>
                    {lecturers?.map((l) => <option key={l.id} value={l.id}>{l.title} {l.full_name}</option>)}
                  </select>
                </td>
                <td><SeatBar used={s.enrolled_count} total={s.capacity} /><div className="muted">czeka: {s.waiting_count}</div></td>
                <td><LimitForm key={`${s.capacity}-${s.waitlist_limit}`} id={s.id} capacity={s.capacity} waitlist={s.waitlist_limit} onDone={reload} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="inline" onSubmit={(e) => { e.preventDefault();
        run(() => api("/api/admin/sections", { body: { ...ns, course_id: courseId, term_id: term!.id } }), "Dodano grupę.", reload); }}>
        <b>Nowa grupa:</b>
        <input placeholder="kod, np. L03" value={ns.code} onChange={(e) => setNs({ ...ns, code: e.target.value })} required style={{ width: 90 }} />
        <select value={ns.kind} onChange={(e) => setNs({ ...ns, kind: e.target.value })}>
          {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="row">limit <input type="number" min={1} value={ns.capacity} onChange={(e) => setNs({ ...ns, capacity: Number(e.target.value) })} style={{ width: 70 }} /></label>
        <label className="row">lista <input type="number" min={0} value={ns.waitlist_limit} onChange={(e) => setNs({ ...ns, waitlist_limit: Number(e.target.value) })} style={{ width: 70 }} /></label>
        <button className="primary">Dodaj</button>
      </form>
    </section>
  );
}

function MeetingForm({ sectionId, rooms, onDone }: { sectionId: number; rooms: RoomT[]; onDone: () => void }) {
  const run = useRun();
  const [m, setM] = useState({ weekday: 1, start: "08:00", end: "09:30", parity: "ALL", room_id: "" });
  return (
    <form className="inline" onSubmit={(e) => { e.preventDefault();
      run(() => api(`/api/admin/sections/${sectionId}/meetings`, { body: { ...m, room_id: m.room_id ? Number(m.room_id) : null } }), "Dodano termin.", onDone); }}>
      <select value={m.weekday} onChange={(e) => setM({ ...m, weekday: Number(e.target.value) })}>{DAYS.slice(1).map((d, i) => <option key={d} value={i + 1}>{d}</option>)}</select>
      <input type="time" value={m.start} onChange={(e) => setM({ ...m, start: e.target.value })} />
      <input type="time" value={m.end} onChange={(e) => setM({ ...m, end: e.target.value })} />
      <select value={m.parity} onChange={(e) => setM({ ...m, parity: e.target.value })}><option value="ALL">co tydz.</option><option value="ODD">nieparz.</option><option value="EVEN">parz.</option></select>
      <select value={m.room_id} onChange={(e) => setM({ ...m, room_id: e.target.value })}>
        <option value="">bez sali</option>{rooms.map((r) => <option key={r.id} value={r.id}>{r.building} {r.number} ({r.seats})</option>)}
      </select>
      <button className="secondary">+</button>
    </form>
  );
}

function LimitForm({ id, capacity, waitlist, onDone }: { id: number; capacity: number; waitlist: number; onDone: () => void }) {
  const run = useRun();
  const [cap, setCap] = useState(capacity);
  const [wl, setWl] = useState(waitlist);
  return (
    <form className="inline" onSubmit={(e) => { e.preventDefault();
      run(async () => {
        const r = await api<{ promotions: { status: string }[] }>(`/api/admin/sections/${id}`, { method: "PATCH", body: { capacity: cap, waitlist_limit: wl } });
        const n = r.promotions.filter((p) => p.status === "PROMOTED").length;
        if (n) alert(`Zapisano z listy oczekujących: ${n} os.`);
      }, "Zmieniono limity.", onDone); }}>
      <input type="number" min={1} value={cap} onChange={(e) => setCap(Number(e.target.value))} style={{ width: 70 }} title="limit miejsc" />
      <input type="number" min={0} value={wl} onChange={(e) => setWl(Number(e.target.value))} style={{ width: 70 }} title="limit listy" />
      <button className="secondary">Zapisz</button>
    </form>
  );
}
