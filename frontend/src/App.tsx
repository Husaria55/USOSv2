import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, auth, type Term, type User } from "./api";
import Login from "./pages/Login";
import Catalog from "./pages/Catalog";
import Plan from "./pages/Plan";
import Waitlists from "./pages/Waitlists";
import LecturerSections from "./pages/LecturerSections";
import AdminRounds from "./pages/AdminRounds";
import AdminCatalog from "./pages/AdminCatalog";
import AdminStudents from "./pages/AdminStudents";
import AdminData from "./pages/AdminData";

interface Ctx {
  user: User;
  term: Term | null;
  terms: Term[];
  toast: (msg: string, bad?: boolean) => void;
}

const AppCtx = createContext<Ctx>(null!);
export const useApp = () => useContext(AppCtx);

const TERM_KEY = "usos.term";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(!!auth.token);
  const [terms, setTerms] = useState<Term[]>([]);
  const [termId, setTermId] = useState<number | null>(() => {
    try { return Number(localStorage.getItem(TERM_KEY)) || null; } catch { return null; }
  });
  const [toastMsg, setToastMsg] = useState<{ msg: string; bad: boolean } | null>(null);

  const toast = useCallback((msg: string, bad = false) => {
    setToastMsg({ msg, bad });
    window.setTimeout(() => setToastMsg((t) => (t?.msg === msg ? null : t)), 4000);
  }, []);

  useEffect(() => {
    const out = () => setUser(null);
    window.addEventListener("usos:logout", out);
    if (auth.token) api<User>("/api/me").then(setUser).catch(() => auth.token = null).finally(() => setChecking(false));
    return () => window.removeEventListener("usos:logout", out);
  }, []);

  useEffect(() => {
    if (user) api<Term[]>("/api/terms").then(setTerms);
  }, [user]);

  const term = terms.find((t) => t.id === termId) ?? terms[0] ?? null;
  const chooseTerm = (id: number) => {
    setTermId(id);
    try { localStorage.setItem(TERM_KEY, String(id)); } catch { /* bez zapamiętania */ }
  };

  if (checking) return null;
  if (!user) return <Login onLogin={(token, u) => { auth.token = token; setUser(u); }} />;

  const links: [string, string][] = {
    STUDENT: [["/zapisy", "Zapisy"], ["/plan", "Mój plan"], ["/listy", "Listy oczekujących"]],
    LECTURER: [["/grupy", "Moje grupy"]],
    ADMIN: [["/admin/tury", "Tury"], ["/admin/katalog", "Katalog"], ["/admin/studenci", "Studenci"],
            ["/admin/dane", "Dane i audyt"], ["/grupy", "Listy grup"]],
  }[user.role] as [string, string][];

  return (
    <AppCtx.Provider value={{ user, term, terms, toast }}>
      <header className="top">
        <strong>Zapisy na zajęcia</strong>
        <nav>
          {links.map(([to, label]) => <NavLink key={to} to={to}>{label}</NavLink>)}
          {terms.length > 0 && (
            <select value={term?.id} onChange={(e) => chooseTerm(Number(e.target.value))} aria-label="Semestr">
              {terms.map((t) => <option key={t.id} value={t.id}>{t.code}</option>)}
            </select>
          )}
          <button className="link" onClick={() => { auth.token = null; setUser(null); }}>Wyloguj</button>
        </nav>
      </header>
      <Routes>
        {user.role === "STUDENT" && <>
          <Route path="/zapisy" element={<Need><Catalog /></Need>} />
          <Route path="/plan" element={<Need><Plan /></Need>} />
          <Route path="/listy" element={<Need><Waitlists /></Need>} />
        </>}
        {user.role !== "STUDENT" && <Route path="/grupy" element={<Need><LecturerSections /></Need>} />}
        {user.role === "ADMIN" && <>
          <Route path="/admin/tury" element={<Need><AdminRounds /></Need>} />
          <Route path="/admin/katalog" element={<Need><AdminCatalog /></Need>} />
          <Route path="/admin/studenci" element={<Need><AdminStudents /></Need>} />
          <Route path="/admin/dane" element={<AdminData />} />
        </>}
        <Route path="*" element={<Navigate to={links[0][0]} replace />} />
      </Routes>
      {toastMsg && <div className={`toast ${toastMsg.bad ? "bad" : ""}`} role="status">{toastMsg.msg}</div>}
    </AppCtx.Provider>
  );
}

/** Strony, które wymagają wybranego semestru. */
function Need({ children }: { children: ReactNode }) {
  const { term, user } = useApp();
  if (term) return <>{children}</>;
  return <main><div className="banner">Brak semestrów w systemie.{user.role === "ADMIN" && " Dodaj semestr w zakładce „Dane i audyt”."}</div>{user.role === "ADMIN" && <AdminData />}</main>;
}
