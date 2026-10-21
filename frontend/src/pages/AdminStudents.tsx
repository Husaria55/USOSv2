import { useState } from "react";
import { api, KINDS, meetingText, type PlanItem, type Program, type User } from "../api";
import { useApp } from "../App";
import { useLoad } from "../components";
import { useRun } from "./AdminCatalog";

/** UC14: decyzje dziekanatu - zapis (bez wymagań, poza turą, ponad limit) i wypis studenta. */
export default function AdminStudents() {
  const { term } = useApp();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState<User | null>(null);
  const [found] = useLoad<User[]>(query ? `/api/admin/users?role=STUDENT&q=${encodeURIComponent(query)}` : null);
  const [programs] = useLoad<Program[]>("/api/programs");
  return (
    <main>
      <div className="grid2">
        <section className="card">
          <h2>Studenci</h2>
          <form className="search" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
            <input placeholder="nazwisko, e-mail lub indeks" value={q} onChange={(e) => setQ(e.target.value)} /><button className="primary">Szukaj</button>
          </form>
          <table><tbody>
            {found?.map((u) => (
              <tr key={u.id}><td>{u.index_no}</td><td>{u.full_name}</td>
                <td className="muted">{programs?.find((p) => p.id === u.program_id)?.code}, sem. {u.semester}</td>
                <td><button className="secondary" onClick={() => setSel(u)}>Wybierz</button></td></tr>
            ))}
          </tbody></table>
        </section>
        {sel && <StudentPanel key={sel.id} student={sel} termId={term!.id} />}
      </div>
    </main>
  );
}

function StudentPanel({ student, termId }: { student: User; termId: number }) {
  const [plan, reload] = useLoad<PlanItem[]>(`/api/admin/students/${student.id}/terms/${termId}/plan`);
  const [sectionId, setSectionId] = useState("");
  const run = useRun();
  return (
    <section className="card">
      <h2>{student.full_name} ({student.index_no})</h2>
      <form className="inline" onSubmit={(e) => { e.preventDefault();
        run(() => api("/api/admin/enrollments", { body: { student_id: student.id, section_id: Number(sectionId) } }),
            "Zapisano (decyzja dziekanatu).", reload); }}>
        <input placeholder="id grupy" value={sectionId} onChange={(e) => setSectionId(e.target.value)} inputMode="numeric" required />
        <button className="primary">Zapisz studenta</button>
      </form>
      <p className="muted">Dziekanat może pominąć wymagania i działać poza turą. Pełna grupa dostaje limit +1 (nie ponad salę). Kolizje i reguła „jedna grupa danego typu” obowiązują zawsze.</p>
      <table><tbody>
        {plan?.map((p) => (
          <tr key={p.section_id}>
            <td><b>{p.course_code} {p.code}</b> <span className="muted">{KINDS[p.kind]}</span></td>
            <td>{p.meetings.map((m) => <div key={m.id}>{meetingText(m)}</div>)}</td>
            <td><button className="danger" onClick={() => confirm(`Wypisać z ${p.course_code} ${p.code}?`) &&
              run(() => api(`/api/admin/enrollments/${student.id}/${p.section_id}`, { method: "DELETE" }), "Wypisano.", reload)}>Wypisz</button></td>
          </tr>
        ))}
        {plan?.length === 0 && <tr><td className="muted">Brak zapisów w tym semestrze.</td></tr>}
      </tbody></table>
    </section>
  );
}
