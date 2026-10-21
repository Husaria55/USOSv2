import { useState } from "react";
import { KINDS, meetingText, type MeetingT } from "../api";
import { useApp } from "../App";
import { SeatBar, useLoad } from "../components";

interface Sec { id: number; course_code: string; course_name: string; code: string; kind: string; capacity: number; enrolled_count: number; meetings: MeetingT[] }
interface Person { id: number; full_name: string; index_no: string; email: string; program: string; position?: number }

export default function LecturerSections() {
  const { term, user } = useApp();
  const [mine] = useLoad<Sec[]>(user.role === "LECTURER" ? `/api/lecturer/terms/${term!.id}/sections` : null);
  const [id, setId] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  return (
    <main>
      <div className="grid2">
        <section className="card">
          <h2>{user.role === "LECTURER" ? "Moje grupy" : "Lista studentów grupy"} – {term!.code}</h2>
          {user.role === "ADMIN" && (
            <form className="inline" onSubmit={(e) => { e.preventDefault(); setOpen(Number(id)); }}>
              <input placeholder="id grupy" value={id} onChange={(e) => setId(e.target.value)} inputMode="numeric" />
              <button className="primary">Pokaż</button>
              <span className="muted">id grupy znajdziesz w zakładce Katalog</span>
            </form>
          )}
          {mine?.length === 0 && <p className="muted">Nie prowadzisz grup w tym semestrze.</p>}
          <div className="table-wrap">
            <table><tbody>
              {mine?.map((s) => (
                <tr key={s.id}>
                  <td><b>{s.course_code} {s.code}</b><div className="muted">{s.course_name}, {KINDS[s.kind]}</div></td>
                  <td>{s.meetings.map((m) => <div key={m.id}>{meetingText(m)}</div>)}</td>
                  <td><SeatBar used={s.enrolled_count} total={s.capacity} /></td>
                  <td><button className="secondary" onClick={() => setOpen(s.id)}>Lista</button></td>
                </tr>
              ))}
            </tbody></table>
          </div>
        </section>
        {open && <Roster sectionId={open} />}
      </div>
    </main>
  );
}

function Roster({ sectionId }: { sectionId: number }) {
  const [r] = useLoad<{ label: string; enrolled: Person[]; waiting: Person[] }>(`/api/sections/${sectionId}/roster`);
  if (!r) return <section className="card"><p className="muted">Brak danych (sprawdź id grupy).</p></section>;
  const csv = () => {
    const rows = [["indeks", "imię i nazwisko", "e-mail", "kierunek"], ...r.enrolled.map((p) => [p.index_no, p.full_name, p.email, p.program])];
    const blob = new Blob([rows.map((x) => x.join(";")).join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${r.label.replace(" ", "_")}.csv`;
    a.click();
  };
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{r.label}</h2><button className="secondary" onClick={csv}>Pobierz CSV</button></div>
      <h3 style={{ marginTop: 12 }}>Zapisani ({r.enrolled.length})</h3>
      <table><tbody>{r.enrolled.map((p) => <tr key={p.id}><td>{p.index_no}</td><td>{p.full_name}</td><td className="muted">{p.program}</td></tr>)}</tbody></table>
      <h3 style={{ marginTop: 12 }}>Oczekujący ({r.waiting.length})</h3>
      <table><tbody>{r.waiting.map((p) => <tr key={p.id}><td>{p.position}.</td><td>{p.index_no}</td><td>{p.full_name}</td><td className="muted">{p.program}</td></tr>)}</tbody></table>
    </section>
  );
}
