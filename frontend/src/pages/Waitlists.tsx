import { ApiError, fmtDate, KINDS, write, type WaitItem } from "../api";
import { useApp } from "../App";
import { useLoad } from "../components";

const LABEL: Record<string, [string, string]> = {
  WAITING: ["czeka", "wait"], PROMOTED: ["zapisany z listy", ""], SKIPPED: ["pominięty", "bad"],
  CANCELLED: ["anulowany", "gray"], EXPIRED: ["wygasł", "gray"],
};

export default function Waitlists() {
  const { term, toast } = useApp();
  const [items, reload] = useLoad<WaitItem[]>(`/api/me/terms/${term!.id}/waitlist`);
  const leave = async (sectionId: number) => {
    try {
      await write(`/api/me/waitlist/${sectionId}`, { method: "DELETE" });
      toast("Zrezygnowano z listy oczekujących.");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Błąd połączenia.", true);
    }
    reload();
  };
  return (
    <main>
      <section className="card">
        <h2>Listy oczekujących – {term!.code}</h2>
        <p className="muted">Gdy zwolni się miejsce, system zapisze Cię automatycznie, o ile nadal spełniasz warunki (wymagania, brak kolizji). Po zakończeniu tury wpisy wygasają.</p>
        {items?.length === 0 && <p className="muted">Nie jesteś na żadnej liście.</p>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Grupa</th><th>Status</th><th>Dopisano</th><th /></tr></thead>
            <tbody>
              {items?.map((w) => (
                <tr key={w.id}>
                  <td><b>{w.course_code} {w.code}</b> <span className="muted">{w.course_name}, {KINDS[w.kind]}</span></td>
                  <td><span className={`tag ${LABEL[w.status][1]}`}>{LABEL[w.status][0]}{w.position ? `: miejsce ${w.position}` : ""}</span>
                    {w.skip_reason && <div className="msg bad">{w.skip_reason}</div>}</td>
                  <td className="muted">{fmtDate(w.created_at)}</td>
                  <td>{w.status === "WAITING" && <button className="secondary" onClick={() => leave(w.section_id)}>Zrezygnuj</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
