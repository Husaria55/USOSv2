import { useEffect, useState } from "react";
import {
  ApiError, KINDS, meetingText, write, type CourseDetail, type CourseSummary, type PlanItem, type SectionStatus,
} from "../api";
import { useApp } from "../App";
import { Notifications, RoundBanner, SeatBar, Timetable, useLoad } from "../components";

export default function Catalog() {
  const { term } = useApp();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [plan, reloadPlan] = useLoad<PlanItem[]>(`/api/me/terms/${term!.id}/plan`);
  const [courses] = useLoad<CourseSummary[]>(
    `/api/terms/${term!.id}/courses?limit=50${query ? `&q=${encodeURIComponent(query)}` : ""}`);

  useEffect(() => {
    const t = window.setTimeout(() => setQuery(q.trim()), 300);   // bez zapytania na każdy znak
    return () => window.clearTimeout(t);
  }, [q]);

  return (
    <main>
      <RoundBanner />
      <div className="grid2">
        <section className="card">
          <h2>Katalog kursów – {term!.code}</h2>
          <div className="search">
            <input placeholder="Szukaj po kodzie lub nazwie" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {courses?.length === 0 && <p className="muted">Nic nie znaleziono.</p>}
          {courses?.map((c) => (
            <div className="course" key={c.id}>
              <h3><button onClick={() => setOpen(open === c.id ? null : c.id)}>{open === c.id ? "▾" : "▸"} {c.code} – {c.name}</button></h3>
              <div className="meta">{c.ects} ECTS · grup: {c.sections} · wolnych miejsc: {c.free_seats}</div>
              {open === c.id && <CourseSections courseId={c.id} onChange={reloadPlan} />}
            </div>
          ))}
        </section>
        <aside className="card">
          <h2>Mój plan – {term!.code}</h2>
          {plan && <Timetable plan={plan} />}
          <Notifications />
        </aside>
      </div>
    </main>
  );
}

function CourseSections({ courseId, onChange }: { courseId: number; onChange: () => void }) {
  const { term, toast } = useApp();
  const [detail, reloadDetail] = useLoad<CourseDetail>(`/api/terms/${term!.id}/courses/${courseId}`);
  const [status, reloadStatus] = useLoad<{ round_open: boolean; sections: SectionStatus[] }>(
    `/api/me/terms/${term!.id}/courses/${courseId}`);
  const [busy, setBusy] = useState<number | null>(null);

  if (!detail || !status) return <p className="muted">Wczytywanie…</p>;
  const byId = new Map(status.sections.map((s) => [s.section_id, s]));
  const missing = status.sections.flatMap((s) => s.refusals).find((r) => r.code === "PREREQUISITES");

  const act = async (sectionId: number, method: string, url: string, body?: unknown) => {
    setBusy(sectionId);
    try {
      const r = await write<{ status: string; position?: number; cancelled_waitlists?: string[] }>(
        url, { method, body }, (s) => toast(`Duży ruch – ponawiam za ${s} s…`));
      if (r.status === "ENROLLED") toast("Zapisano." + (r.cancelled_waitlists?.length ? ` Usunięto z list: ${r.cancelled_waitlists.join(", ")}.` : ""));
      else if (r.status === "WAITLISTED") toast(`Brak miejsc – jesteś na liście oczekujących (miejsce ${r.position}).`);
      else if (r.status === "DROPPED") toast("Wypisano.");
      else toast("Zrezygnowano z listy oczekujących.");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Brak połączenia z serwerem.", true);
    } finally {
      setBusy(null);
      reloadDetail();
      reloadStatus();
      onChange();
    }
  };

  return (
    <>
      <div className="meta">
        {detail.prerequisites.length === 0 ? "bez wymagań wstępnych" : <>wymaga: {detail.prerequisites.map((p) => p.code).join(", ")}{" "}
          {missing ? <span className="msg bad">({missing.message.toLowerCase()} – zapis niemożliwy)</span> : <span className="tag">wymagania spełnione</span>}</>}
      </div>
      {detail.description && <p className="muted">{detail.description}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Grupa</th><th>Termin</th><th>Prowadzący</th><th>Miejsca</th><th /></tr></thead>
          <tbody>
            {detail.sections.map((s) => {
              const st = byId.get(s.id);
              const full = s.enrolled_count >= s.capacity;
              const leaving = detail.sections.filter((o) => o.id !== s.id && o.kind === s.kind && byId.get(o.id)?.state === "WAITING");
              const blocking = st?.refusals.filter((r) => r.code !== "PREREQUISITES") ?? [];
              return (
                <tr key={s.id}>
                  <td>{s.code} {KINDS[s.kind]}</td>
                  <td>{s.meetings.map((m) => <div key={m.id}>{meetingText(m)}</div>)}</td>
                  <td>{s.lecturers.map((l) => l.name).join(", ")}</td>
                  <td><SeatBar used={s.enrolled_count} total={s.capacity} /></td>
                  <td>
                    {st?.state === "ENROLLED" && <><span className="tag">zapisany</span>{" "}
                      <button className="secondary" disabled={busy !== null} onClick={() => act(s.id, "DELETE", `/api/me/enrollments/${s.id}`)}>Wypisz</button></>}
                    {st?.state === "WAITING" && <><span className="tag wait">lista: miejsce {st.position} z {s.waiting_count}</span>{" "}
                      <button className="secondary" disabled={busy !== null} onClick={() => act(s.id, "DELETE", `/api/me/waitlist/${s.id}`)}>Zrezygnuj</button></>}
                    {(st?.state === "AVAILABLE" || st?.state === "BLOCKED") && <>
                      <button className={full ? "secondary" : "primary"} disabled={busy !== null || st.state === "BLOCKED"}
                              onClick={() => act(s.id, "POST", "/api/me/enrollments", { section_id: s.id })}>
                        {busy === s.id ? "…" : full ? "Dołącz do listy" : "Zapisz"}
                      </button>
                      {blocking.map((r) => <div key={r.code} className="msg bad">{r.message}</div>)}
                      {st.state === "AVAILABLE" && full && <div className="msg warn">brak miejsc · {s.waiting_count} os. czeka{s.waiting_count >= s.waitlist_limit ? " · lista pełna" : ""}</div>}
                      {st.state === "AVAILABLE" && !full && leaving.length > 0 && <div className="msg warn">zapis usunie Cię z listy {leaving.map((o) => o.code).join(", ")}</div>}
                    </>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
