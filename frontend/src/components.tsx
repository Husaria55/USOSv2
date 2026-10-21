import { useEffect, useState } from "react";
import { api, fmtDate, KINDS, type NotificationT, type PlanItem, type Round } from "./api";
import { useApp } from "./App";

export function useLoad<T>(url: string | null, deps: unknown[] = []): [T | null, () => void, boolean] {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!url) return;
    let live = true;
    setLoading(true);
    api<T>(url).then((d) => live && setData(d)).catch(() => live && setData(null)).finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, n, ...deps]);
  return [data, () => setN((x) => x + 1), loading];
}

export function RoundBanner() {
  const { term, user } = useApp();
  const [rounds] = useLoad<Round[]>(term ? `/api/me/terms/${term.id}/rounds` : null);
  if (!rounds) return null;
  const open = rounds.find((r) => r.status === "OPEN");
  const next = rounds.find((r) => r.status === "PLANNED");
  const who = `Zalogowano: ${user.full_name} (${user.index_no}), sem. ${user.semester}.`;
  if (open) return <div className="banner">Tura zapisów dla Twojego kierunku jest <b>otwarta</b> do <b>{fmtDate(open.closes_at)}</b>. {who}</div>;
  if (next) return <div className="banner warn">Zapisy dla Twojego kierunku otworzą się <b>{fmtDate(next.opens_at)}</b> (do {fmtDate(next.closes_at)}). Katalog i plan możesz przeglądać już teraz. {who}</div>;
  return <div className="banner warn">W semestrze {term?.code} nie ma otwartej tury zapisów dla Twojego kierunku. {who}</div>;
}

const START_H = 8, END_H = 20, HOUR_PX = 30;

export function Timetable({ plan }: { plan: PlanItem[] }) {
  const toMin = (s: string) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };
  const hours = Array.from({ length: END_H - START_H }, (_, i) => START_H + i);
  const height = (END_H - START_H) * HOUR_PX;
  return (
    <>
      <div className="tt" style={{ gridTemplateRows: `auto ${height}px` }}>
        <div className="h" />
        {["pon", "wt", "śr", "czw", "pt"].map((d) => <div key={d} className="h">{d}</div>)}
        <div style={{ position: "relative" }}>
          {hours.map((h) => <div key={h} className="t" style={{ position: "absolute", top: (h - START_H) * HOUR_PX, height: HOUR_PX, width: "100%" }}>{h}:00</div>)}
        </div>
        {[1, 2, 3, 4, 5].map((day) => (
          <div key={day} className="col">
            {plan.flatMap((p) => p.meetings.filter((m) => m.weekday === day).map((m) => {
              const top = ((toMin(m.start) - START_H * 60) / 60) * HOUR_PX;
              const h = ((toMin(m.end) - toMin(m.start)) / 60) * HOUR_PX;
              const cls = m.parity !== "ALL" ? m.parity.toLowerCase() : p.kind === "LECTURE" ? "" : "lab";
              return (
                <div key={m.id} className={`slot ${cls}`} style={{ top, height: h }} title={`${p.course_name} (${KINDS[p.kind]})`}>
                  {p.course_code} {p.code}<br />{m.start}–{m.end}{m.parity !== "ALL" && <><br />{m.parity === "ODD" ? "tyg. nieparz." : "tyg. parz."}</>}
                </div>
              );
            }))}
          </div>
        ))}
      </div>
      <p className="muted">Paski ukośne = zajęcia co dwa tygodnie. Grupa w tygodnie parzyste w tym samym czasie nie koliduje.</p>
    </>
  );
}

export function Notifications() {
  const [notes, reload] = useLoad<NotificationT[]>("/api/me/notifications");
  useEffect(() => {
    const t = window.setInterval(reload, 30_000);
    return () => window.clearInterval(t);
  }, [reload]);
  if (!notes) return null;
  const unread = notes.some((n) => !n.read);
  return (
    <div className="notes">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Powiadomienia</h2>
        {unread && <button className="secondary" onClick={() => api("/api/me/notifications/read", { body: {} }).then(reload)}>Oznacz jako przeczytane</button>}
      </div>
      {notes.length === 0 && <p className="muted">Brak powiadomień.</p>}
      {notes.slice(0, 10).map((n) => (
        <p key={n.id} className={`${n.type} ${n.read ? "" : "unread"}`}>
          {["PROMOTED", "ADMIN_ENROLLED"].includes(n.type) ? "✓" : "!"} {fmtDate(n.created_at)} – {n.message}
        </p>
      ))}
    </div>
  );
}

export function SeatBar({ used, total }: { used: number; total: number }) {
  const pct = Math.min(100, Math.round((used / total) * 100));
  return <span className="seats">{used}/{total}<div className="bar"><i className={used >= total ? "full" : ""} style={{ width: `${pct}%` }} /></div></span>;
}
