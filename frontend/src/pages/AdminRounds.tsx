import { useState, type FormEvent } from "react";
import { api, ApiError, fmtDate, type Program, type Round } from "../api";
import { useApp } from "../App";
import { useLoad } from "../components";

const STATUS: Record<string, string> = { PLANNED: "zaplanowana", OPEN: "otwarta", CLOSED: "zamknięta" };
const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

export default function AdminRounds() {
  const { term, toast } = useApp();
  const [rounds, reload] = useLoad<Round[]>(`/api/admin/terms/${term!.id}/rounds`);
  const [programs] = useLoad<Program[]>("/api/programs");
  const name = (ids: number[] = []) =>
    ids.length === 0 ? "wszystkie kierunki" : ids.map((i) => programs?.find((p) => p.id === i)?.code ?? i).join(", ");

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast(ok); } catch (e) { toast(e instanceof ApiError ? e.message : "Błąd.", true); }
    reload();
  };

  return (
    <main>
      <section className="card">
        <h2>Tury zapisów – {term!.code}</h2>
        <p className="muted">Tury kierunków o różnych godzinach rozkładają szczyt obciążenia: zamiast całej uczelni naraz zapisuje się jeden lub kilka kierunków. Worker otwiera i zamyka tury o zadanych godzinach; tu można to zrobić ręcznie albo przedłużyć turę.</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Tura</th><th>Kierunki</th><th>Od</th><th>Do</th><th>Status</th><th /></tr></thead>
            <tbody>
              {rounds?.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td><td>{name(r.program_ids)}</td><td>{fmtDate(r.opens_at)}</td><td>{fmtDate(r.closes_at)}</td>
                  <td><span className={`tag ${r.status === "OPEN" ? "" : r.status === "PLANNED" ? "wait" : "gray"}`}>{STATUS[r.status]}</span></td>
                  <td className="row">
                    {r.status !== "OPEN" && <button className="secondary" onClick={() => run(() => api(`/api/admin/rounds/${r.id}/open`, { body: {} }), "Tura otwarta.")}>Otwórz</button>}
                    {r.status === "OPEN" && <button className="danger" onClick={() => confirm("Zamknąć turę? Listy oczekujących tych kierunków wygasną.") &&
                      run(() => api(`/api/admin/rounds/${r.id}/close`, { body: {} }), "Tura zamknięta.")}>Zamknij</button>}
                    <button className="secondary" onClick={() => run(() => api(`/api/admin/rounds/${r.id}`, { method: "PATCH",
                      body: { closes_at: new Date(new Date(r.closes_at).getTime() + 3600_000).toISOString() } }), "Przedłużono o godzinę.")}>+1 h</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="grid2">
        <NewRound programs={programs ?? []} onDone={reload} />
        <Stagger programs={programs ?? []} onDone={reload} />
      </div>
    </main>
  );
}

function ProgramPicker({ programs, value, onChange }: { programs: Program[]; value: number[]; onChange: (v: number[]) => void }) {
  return (
    <div className="row">
      {programs.map((p) => (
        <label key={p.id} className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={value.includes(p.id)}
                 onChange={(e) => onChange(e.target.checked ? [...value, p.id] : value.filter((x) => x !== p.id))} />{p.code}
        </label>
      ))}
    </div>
  );
}

function NewRound({ programs, onDone }: { programs: Program[]; onDone: () => void }) {
  const { term, toast } = useApp();
  const [name, setName] = useState("");
  const [opens, setOpens] = useState(local(new Date(Date.now() + 3600_000)));
  const [closes, setCloses] = useState(local(new Date(Date.now() + 7 * 24 * 3600_000)));
  const [ids, setIds] = useState<number[]>([]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/admin/rounds", { body: { term_id: term!.id, name, program_ids: ids,
        opens_at: new Date(opens).toISOString(), closes_at: new Date(closes).toISOString() } });
      toast("Dodano turę.");
      setName("");
      onDone();
    } catch (err) { toast(err instanceof ApiError ? err.message : "Błąd.", true); }
  };
  return (
    <section className="card">
      <h2>Nowa tura</h2>
      <form onSubmit={submit} style={{ display: "grid", gap: 8 }}>
        <input placeholder="nazwa, np. Tura 1 – INF" value={name} onChange={(e) => setName(e.target.value)} required />
        <label className="row">od <input type="datetime-local" value={opens} onChange={(e) => setOpens(e.target.value)} required /></label>
        <label className="row">do <input type="datetime-local" value={closes} onChange={(e) => setCloses(e.target.value)} required /></label>
        <ProgramPicker programs={programs} value={ids} onChange={setIds} />
        <span className="muted">Bez zaznaczonych kierunków tura obejmuje wszystkich.</span>
        <button className="primary">Dodaj</button>
      </form>
    </section>
  );
}

/** Tworzy osobną turę dla każdego kierunku, kolejne co `step` minut. */
function Stagger({ programs, onDone }: { programs: Program[]; onDone: () => void }) {
  const { term, toast } = useApp();
  const [start, setStart] = useState(local(new Date(Date.now() + 24 * 3600_000)));
  const [step, setStep] = useState(30);
  const [hours, setHours] = useState(72);
  const [prefix, setPrefix] = useState("Tura 1");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const t0 = new Date(start).getTime();
    let made = 0;
    for (const [i, p] of programs.entries()) {
      const opens = new Date(t0 + i * step * 60_000);
      try {
        await api("/api/admin/rounds", { body: { term_id: term!.id, name: `${prefix} – ${p.code}`, program_ids: [p.id],
          opens_at: opens.toISOString(), closes_at: new Date(opens.getTime() + hours * 3600_000).toISOString() } });
        made++;
      } catch (err) { toast(`${p.code}: ${err instanceof ApiError ? err.message : "błąd"}`, true); }
    }
    toast(`Utworzono ${made} tur.`);
    onDone();
  };
  return (
    <section className="card">
      <h2>Rozłóż tury kierunków</h2>
      <form onSubmit={submit} style={{ display: "grid", gap: 8 }}>
        <input value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="przedrostek nazwy" />
        <label className="row">pierwsza o <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="row">kolejna co <input type="number" min={1} value={step} onChange={(e) => setStep(Number(e.target.value))} style={{ width: 80 }} /> min</label>
        <label className="row">każda trwa <input type="number" min={1} value={hours} onChange={(e) => setHours(Number(e.target.value))} style={{ width: 80 }} /> h</label>
        <span className="muted">{programs.length} kierunków: {programs.map((p) => p.code).join(", ")}. Przy ~1000 studentów na kierunek w szczycie zapisuje się 1000 osób zamiast 20 000.</span>
        <button className="primary" disabled={!programs.length}>Utwórz tury</button>
      </form>
    </section>
  );
}
