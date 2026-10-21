import { KINDS, meetingText, type PlanItem } from "../api";
import { useApp } from "../App";
import { RoundBanner, Timetable, useLoad } from "../components";

export default function Plan() {
  const { term } = useApp();
  const [plan] = useLoad<PlanItem[]>(`/api/me/terms/${term!.id}/plan`);
  const source: Record<string, string> = { DIRECT: "zapis", WAITLIST: "z listy oczekujących", ADMIN: "dziekanat" };
  return (
    <main>
      <RoundBanner />
      <div className="grid2">
        <section className="card">
          <h2>Mój plan – {term!.code}</h2>
          {plan && <Timetable plan={plan} />}
        </section>
        <section className="card">
          <h2>Grupy</h2>
          {plan?.length === 0 && <p className="muted">Nie jesteś zapisany do żadnej grupy.</p>}
          <div className="table-wrap">
            <table>
              <tbody>
                {plan?.map((p) => (
                  <tr key={p.section_id}>
                    <td><b>{p.course_code} {p.code}</b><div className="muted">{p.course_name}, {KINDS[p.kind]}</div></td>
                    <td>{p.meetings.map((m) => <div key={m.id}>{meetingText(m)}</div>)}<div className="muted">{p.lecturers.map((l) => l.name).join(", ")}</div></td>
                    <td><span className="tag gray">{source[p.source]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
