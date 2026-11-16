import { useEffect, useState } from "react";
import {
  ApiError, fmtDate, KINDS, meetingText, write, type AllocationView, type CourseDetail, type CourseSummary,
  type PreferenceWarning, type Preferences as Prefs, type Round, api,
} from "../api";
import { useApp } from "../App";
import { useLoad } from "../components";

/** Zgłoszenie w edycji: przedmiot, waga i akceptowane grupy w kolejności (różne typy mogą się przeplatać). */
interface Draft { course_id: number; code: string; name: string; weight: number; section_ids: number[] }

/** UC28/UC29: preferencje w turze preferencyjnej i przewidywany przydział. */
export default function Preferences() {
  const { term } = useApp();
  const [rounds] = useLoad<Round[]>(`/api/me/terms/${term!.id}/rounds`);
  const prefRounds = (rounds ?? []).filter((r) => r.mode === "PREFERENCES");
  const [roundId, setRoundId] = useState<number | null>(null);
  const round = prefRounds.find((r) => r.id === roundId) ?? prefRounds.find((r) => r.status === "OPEN") ?? prefRounds[0];

  if (!rounds) return <main><p className="muted">Wczytywanie…</p></main>;
  if (!round) return (
    <main><div className="banner warn">W semestrze {term!.code} Twój kierunek nie ma tury preferencyjnej –
      zapisy odbywają się w kolejności zgłoszeń (zakładka „Zapisy”).</div></main>);
  return (
    <main>
      {prefRounds.length > 1 && (
        <div className="tabs">{prefRounds.map((r) => (
          <button key={r.id} className={r.id === round.id ? "on" : ""} onClick={() => setRoundId(r.id)}>{r.name}</button>))}
        </div>)}
      <RoundEditor key={round.id} round={round} />
    </main>
  );
}

function RoundEditor({ round }: { round: Round }) {
  const { term, toast } = useApp();
  const [saved, reloadSaved] = useLoad<Prefs>(`/api/me/rounds/${round.id}/preferences`);
  const [alloc, reloadAlloc] = useLoad<AllocationView>(`/api/me/rounds/${round.id}/allocation`);
  const [draft, setDraft] = useState<Draft[] | null>(null);
  const [details, setDetails] = useState<Record<number, CourseDetail>>({});
  const [warnings, setWarnings] = useState<PreferenceWarning[]>([]);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const editable = round.status === "OPEN";
  const budget = round.points_budget ?? 100;

  useEffect(() => {                                     // zgłoszenie z serwera -> edycja
    if (saved && draft === null)
      setDraft(saved.courses.map((c) => ({ course_id: c.course_id, code: c.code, name: c.name, weight: c.weight,
        section_ids: [...c.sections].sort((a, b) => a.rank - b.rank || a.kind.localeCompare(b.kind)).map((s) => s.section_id) })));
  }, [saved, draft]);

  useEffect(() => {                                     // szczegóły grup (terminy) dla zgłoszonych przedmiotów
    for (const d of draft ?? [])
      if (!details[d.course_id])
        api<CourseDetail>(`/api/terms/${term!.id}/courses/${d.course_id}`)
          .then((c) => setDetails((x) => ({ ...x, [c.id]: c }))).catch(() => undefined);
  }, [draft, details, term]);

  const used = (draft ?? []).reduce((n, d) => n + (Number(d.weight) || 0), 0);
  const change = (fn: (ds: Draft[]) => Draft[]) => { setDraft((ds) => fn(ds ?? [])); setDirty(true); };
  const update = (id: number, fn: (d: Draft) => Draft) => change((ds) => ds.map((d) => (d.course_id === id ? fn(d) : d)));

  const add = (c: CourseSummary, detail: CourseDetail) => {
    setDetails((x) => ({ ...x, [c.id]: detail }));
    change((ds) => [...ds, { course_id: c.id, code: c.code, name: c.name, weight: Math.max(1, Math.min(10, budget - used)),
      section_ids: detail.sections.map((s) => s.id) }]);
  };

  const save = async () => {
    setBusy(true);
    try {
      const r = await write<{ used_points: number; warnings: PreferenceWarning[] }>(`/api/me/rounds/${round.id}/preferences`, {
        method: "PUT", body: { courses: draft!.map((d) => ({ course_id: d.course_id, weight: Number(d.weight), section_ids: d.section_ids })) } });
      setWarnings(r.warnings);
      toast(`Zapisano preferencje (${r.used_points}/${budget} pkt).`);
      setDirty(false);
      reloadSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Brak połączenia z serwerem.", true);
    } finally { setBusy(false); }
  };

  return (
    <div className="grid2">
      <section className="card">
        <h2>{round.name}</h2>
        <div className={`banner ${editable ? "" : "warn"}`}>
          {editable
            ? <>Rozdziel <b>{budget} punktów</b> między przedmioty, które chcesz mieć – im więcej punktów, tym większa szansa na miejsce.
                Dla każdego przedmiotu ułóż akceptowane grupy od najbardziej chcianej. Zgłoszenie możesz zmieniać do <b>{fmtDate(round.closes_at)}</b>;
                po zamknięciu tury system przydzieli miejsca tak, by łączne dopasowanie było jak najlepsze (bez kolizji w planie).</>
            : round.status === "PLANNED" ? <>Tura zaczyna się {fmtDate(round.opens_at)}.</> : <>Tura zamknięta – wynik przydziału poniżej.</>}
        </div>
        <p>Wykorzystano <b className={used > budget ? "msg bad" : ""}>{used}</b> / {budget} pkt
          <span className="bar" style={{ display: "inline-block", marginLeft: 8, verticalAlign: "middle" }}>
            <i className={used > budget ? "full" : ""} style={{ width: `${Math.min(100, (used / budget) * 100)}%` }} /></span></p>
        {draft?.length === 0 && <p className="muted">Nie zgłoszono jeszcze żadnego przedmiotu.</p>}
        {draft?.map((d) => (
          <div className="course" key={d.course_id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3>{d.code} – {d.name}</h3>
              <span className="row">
                <label className="row">waga <input type="number" min={1} max={budget} value={d.weight} disabled={!editable} style={{ width: 70 }}
                  onChange={(e) => update(d.course_id, (x) => ({ ...x, weight: Number(e.target.value) }))} /> pkt</label>
                {editable && <button className="danger" onClick={() => change((ds) => ds.filter((x) => x.course_id !== d.course_id))}>Usuń</button>}
              </span>
            </div>
            {warnings.filter((w) => w.course_id === d.course_id).map((w) => <div key={w.code} className="msg warn">⚠ {w.message}</div>)}
            <SectionRanking draft={d} detail={details[d.course_id]} editable={editable}
                            onChange={(ids) => update(d.course_id, (x) => ({ ...x, section_ids: ids }))} />
          </div>
        ))}
        {editable && <AddCourse exclude={(draft ?? []).map((d) => d.course_id)} onAdd={add} />}
        {editable && <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" disabled={busy || used > budget || !draft} onClick={save}>{busy ? "…" : "Zapisz preferencje"}</button>
          {dirty && <span className="muted">Zmiany nie są zapisane.</span>}
        </div>}
      </section>
      <aside className="card">
        <h2>{alloc?.run?.kind === "FINAL" ? "Wynik przydziału" : "Przewidywany przydział"}</h2>
        {!alloc?.run && <p className="muted">Symulacja jeszcze się nie odbyła – system przelicza ją co kilka minut.</p>}
        {alloc?.run && <p className="muted">{alloc.run.kind === "FINAL" ? "Przydział końcowy" : "Symulacja na zgłoszeniach wszystkich studentów"} z {fmtDate(alloc.run.created_at)}.
          {alloc.run.kind === "PREVIEW" && " Wynik może się zmienić, jeśli inni zmienią swoje preferencje."}
          <button className="link secondary" style={{ marginLeft: 6 }} onClick={reloadAlloc}>odśwież</button></p>}
        <div className="table-wrap"><table><tbody>
          {alloc?.results.map((r) => (
            <tr key={r.course_id}>
              <td><b>{r.code}</b> <span className="muted">{r.weight} pkt</span></td>
              <td>{r.status === "ASSIGNED"
                ? <><span className="tag">przydzielony</span> <span className="muted">{r.sections.join(", ")}</span></>
                : <><span className="tag bad">bez miejsca</span><div className="msg bad">{r.reason}</div></>}</td>
            </tr>))}
        </tbody></table></div>
      </aside>
    </div>
  );
}

function SectionRanking({ draft, detail, editable, onChange }: {
  draft: Draft; detail?: CourseDetail; editable: boolean; onChange: (ids: number[]) => void;
}) {
  if (!detail) return <p className="muted">Wczytywanie grup…</p>;
  const byId = new Map(detail.sections.map((s) => [s.id, s]));
  const chosen = draft.section_ids.filter((id) => byId.has(id));
  const rest = detail.sections.filter((s) => !chosen.includes(s.id));
  const move = (i: number, by: number) => {
    const ids = [...chosen];
    [ids[i], ids[i + by]] = [ids[i + by], ids[i]];
    onChange(ids);
  };
  const rankOf = (id: number) => chosen.filter((x) => byId.get(x)!.kind === byId.get(id)!.kind).indexOf(id) + 1;
  return (
    <div className="table-wrap"><table><tbody>
      {chosen.map((id, i) => {
        const s = byId.get(id)!;
        return (
          <tr key={id}>
            <td><b>{rankOf(id)}.</b> {s.code} {KINDS[s.kind]}</td>
            <td>{s.meetings.map((m) => <div key={m.id}>{meetingText(m)}</div>)}</td>
            <td className="muted">{s.capacity - s.enrolled_count} wolnych</td>
            {editable && <td className="row">
              <button className="secondary" disabled={i === 0} onClick={() => move(i, -1)} aria-label="wyżej">↑</button>
              <button className="secondary" disabled={i === chosen.length - 1} onClick={() => move(i, 1)} aria-label="niżej">↓</button>
              <button className="danger" onClick={() => onChange(chosen.filter((x) => x !== id))} aria-label="nie akceptuję">×</button>
            </td>}
          </tr>);
      })}
      {editable && rest.map((s) => (
        <tr key={s.id} className="muted">
          <td>{s.code} {KINDS[s.kind]}</td><td>{s.meetings.map((m) => <div key={m.id}>{meetingText(m)}</div>)}</td><td />
          <td><button className="secondary" onClick={() => onChange([...chosen, s.id])}>Akceptuję</button></td>
        </tr>))}
    </tbody></table></div>
  );
}

function AddCourse({ exclude, onAdd }: { exclude: number[]; onAdd: (c: CourseSummary, d: CourseDetail) => void }) {
  const { term, toast } = useApp();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => setQuery(q.trim()), 300);
    return () => window.clearTimeout(t);
  }, [q]);
  const [found] = useLoad<CourseSummary[]>(query ? `/api/terms/${term!.id}/courses?limit=10&q=${encodeURIComponent(query)}` : null);
  return (
    <div style={{ marginTop: 12 }}>
      <input placeholder="Dodaj przedmiot – szukaj po kodzie lub nazwie" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%" }} />
      {query && found?.filter((c) => !exclude.includes(c.id)).map((c) => (
        <div key={c.id} className="row" style={{ justifyContent: "space-between", padding: "4px 0" }}>
          <span>{c.code} – {c.name} <span className="muted">({c.sections} grup)</span></span>
          <button className="secondary" onClick={async () => {
            try { onAdd(c, await api<CourseDetail>(`/api/terms/${term!.id}/courses/${c.id}`)); setQ(""); }
            catch { toast("Nie udało się wczytać grup.", true); }
          }}>Dodaj</button>
        </div>))}
    </div>
  );
}
