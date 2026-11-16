import { useState, type FormEvent } from "react";
import { api, ApiError, fmtDate, type AllocationSummary, type Program, type Round, type RoundMode } from "../api";
import { useApp } from "../App";
import { useLoad } from "../components";

const STATUS: Record<string, string> = { PLANNED: "zaplanowana", OPEN: "otwarta", CLOSED: "zamknięta" };
const MODE: Record<RoundMode, string> = { QUEUE: "kolejka", PREFERENCES: "preferencje" };
const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

export default function AdminRounds() {
  const { term, toast } = useApp();
  const [rounds, reload] = useLoad<Round[]>(`/api/admin/terms/${term!.id}/rounds`);
  const [programs] = useLoad<Program[]>("/api/programs");
  const [report, setReport] = useState<{ round: Round; data: AllocationSummary } | null>(null);
  const showReport = async (r: Round) => {
    try { setReport({ round: r, data: await api<AllocationSummary>(`/api/admin/rounds/${r.id}/allocation`) }); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Błąd.", true); }
  };
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
            <thead><tr><th>Tura</th><th>Tryb</th><th>Kierunki</th><th>Od</th><th>Do</th><th>Status</th><th /></tr></thead>
            <tbody>
              {rounds?.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td>{MODE[r.mode]}{r.points_budget ? <span className="muted"> ({r.points_budget} pkt)</span> : null}</td>
                  <td>{name(r.program_ids)}</td><td>{fmtDate(r.opens_at)}</td><td>{fmtDate(r.closes_at)}</td>
                  <td><span className={`tag ${r.status === "OPEN" ? "" : r.status === "PLANNED" ? "wait" : "gray"}`}>{STATUS[r.status]}</span></td>
                  <td className="row">
                    {r.status !== "OPEN" && <button className="secondary" onClick={() => run(() => api(`/api/admin/rounds/${r.id}/open`, { body: {} }), "Tura otwarta.")}>Otwórz</button>}
                    {r.status === "OPEN" && <button className="danger" onClick={() => confirm("Zamknąć turę? Listy oczekujących tych kierunków wygasną.") &&
                      run(() => api(`/api/admin/rounds/${r.id}/close`, { body: {} }), "Tura zamknięta.")}>Zamknij</button>}
                    <button className="secondary" onClick={() => run(() => api(`/api/admin/rounds/${r.id}`, { method: "PATCH",
                      body: { closes_at: new Date(new Date(r.closes_at).getTime() + 3600_000).toISOString() } }), "Przedłużono o godzinę.")}>+1 h</button>
                    {r.mode === "PREFERENCES" && <>
                      {r.status === "OPEN" && <button className="secondary" onClick={() => run(async () => { await api(`/api/admin/rounds/${r.id}/allocation/preview`, { body: {} }); await showReport(r); }, "Przeliczono symulację.")}>Symulacja</button>}
                      {r.status === "CLOSED" && <button className="primary" onClick={() => run(async () => { await api(`/api/admin/rounds/${r.id}/allocation`, { body: {} }); await showReport(r); }, "Przydzielono miejsca.")}>Przydziel</button>}
                      <button className="secondary" onClick={() => showReport(r)}>Raport</button>
                    </>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {report && <AllocationReport round={report.round} data={report.data} onClose={() => setReport(null)} />}
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
  const [mode, setMode] = useState<RoundMode>("QUEUE");
  const [budget, setBudget] = useState(100);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/admin/rounds", { body: { term_id: term!.id, name, program_ids: ids, mode,
        points_budget: mode === "PREFERENCES" ? budget : null,
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
        <label className="row">tryb <select value={mode} onChange={(e) => setMode(e.target.value as RoundMode)}>
          <option value="QUEUE">kolejka – kto pierwszy, ten lepszy</option>
          <option value="PREFERENCES">preferencje – wagi i optymalny przydział</option></select></label>
        {mode === "PREFERENCES" && <label className="row">pula punktów <input type="number" min={1} max={1000} value={budget}
          onChange={(e) => setBudget(Number(e.target.value))} style={{ width: 90 }} /></label>}
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

function AllocationReport({ round, data, onClose }: { round: Round; data: AllocationSummary; onClose: () => void }) {
  const r = data.run;
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Przydział – {round.name}</h2>
        <button className="secondary" onClick={onClose}>Zamknij</button>
      </div>
      {!r && <p className="muted">Brak przebiegu przydziału (symulacja liczy się co kilka minut w otwartej turze).</p>}
      {r && <p>{r.kind === "FINAL" ? "Przydział końcowy" : "Symulacja"} z {fmtDate(r.created_at)}: przydzielono <b>{r.assigned}</b> z {r.requests} zgłoszeń
        ({r.students} studentów). Suma użyteczności <b>{r.total_utility.toFixed(1)}</b> z górnego ograniczenia {r.upper_bound.toFixed(1)}
        {r.quality !== null && <> (<b>{(r.quality * 100).toFixed(1)}%</b>)</>}. Ziarno losowania: <code>{r.seed}</code>.</p>}
      <div className="table-wrap"><table>
        <thead><tr><th>Przedmiot</th><th>Zgłoszeń</th><th>Suma wag</th><th>Wolne miejsca</th><th>Przydzielono</th></tr></thead>
        <tbody>{data.courses.map((c) => (
          <tr key={c.course_id}><td>{c.code}</td><td>{c.requests}</td><td>{c.weight_sum}</td><td>{c.free_seats}</td><td>{c.assigned}</td></tr>))}
        </tbody>
      </table></div>
    </section>
  );
}
