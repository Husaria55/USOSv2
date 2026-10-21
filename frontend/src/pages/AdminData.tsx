import { useState, type FormEvent } from "react";
import { api, type Program } from "../api";
import { useLoad } from "../components";
import { useRun } from "./AdminCatalog";

export default function AdminData() {
  const run = useRun();
  const [programs, reloadPrograms] = useLoad<Program[]>("/api/programs");
  const [audit, setAudit] = useState<{ section_id: number; problem: string }[] | null>(null);
  const [importResult, setImportResult] = useState<{ imported: number; errors: string[] } | null>(null);
  const [csv, setCsv] = useState("index_no,course_code,term_code,grade\n");
  const [user, setUser] = useState({ role: "STUDENT", email: "", password: "", full_name: "", index_no: "", program_id: "",
                                     semester: "1", title: "", department: "" });
  const form = (fields: string[], url: string, ok: string, after?: () => void) => (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body = Object.fromEntries(fields.map((f) => [f, fd.get(f)]));
    run(() => api(url, { body }), ok, () => { e.currentTarget?.reset(); after?.(); });
  };
  const createUser = (e: FormEvent) => {
    e.preventDefault();
    const u = user;
    const body = { email: u.email, password: u.password, full_name: u.full_name, role: u.role,
      ...(u.role === "STUDENT" ? { index_no: u.index_no, program_id: Number(u.program_id), semester: Number(u.semester) } : {}),
      ...(u.role === "LECTURER" ? { title: u.title || null, department: u.department } : {}) };
    run(() => api("/api/admin/users", { body }), "Dodano użytkownika.");
  };
  const set = (k: string) => (e: { target: { value: string } }) => setUser({ ...user, [k]: e.target.value });

  return (
    <main>
      <div className="grid2">
        <section className="card">
          <h2>Import ocen (UC15)</h2>
          <p className="muted">CSV z nagłówkiem <code>index_no,course_code,term_code,grade</code>. Ponowny import nadpisuje ocenę.</p>
          <textarea rows={8} style={{ width: "100%", fontFamily: "monospace" }} value={csv} onChange={(e) => setCsv(e.target.value)} />
          <div className="row">
            <input type="file" accept=".csv,text/csv" onChange={(e) => e.target.files?.[0]?.text().then(setCsv)} />
            <button className="primary" onClick={() => run(async () => setImportResult(await api("/api/admin/grades/import", { body: { csv } })), "Zaimportowano.")}>Importuj</button>
          </div>
          {importResult && <p>Zaimportowano: {importResult.imported}.{importResult.errors.length > 0 && <pre>{importResult.errors.join("\n")}</pre>}</p>}
        </section>
        <section className="card">
          <h2>Audyt niezmienników</h2>
          <p className="muted">Licznik miejsc = liczba zapisanych, nikt nie czeka przy wolnych miejscach, nikt nie jest jednocześnie zapisany i oczekujący. Worker sprawdza to co minutę.</p>
          <button className="primary" onClick={() => api<typeof audit>("/api/admin/audit").then(setAudit)}>Sprawdź teraz</button>
          {audit && (audit.length === 0 ? <p className="msg ok">Wszystkie niezmienniki spełnione.</p>
            : <pre>{audit.map((v) => `grupa ${v.section_id}: ${v.problem}`).join("\n")}</pre>)}
        </section>
      </div>
      <div className="grid2">
        <section className="card">
          <h2>Nowy użytkownik</h2>
          <form onSubmit={createUser} style={{ display: "grid", gap: 8 }}>
            <select value={user.role} onChange={set("role")}><option value="STUDENT">student</option><option value="LECTURER">prowadzący</option><option value="ADMIN">dziekanat</option></select>
            <input placeholder="imię i nazwisko" value={user.full_name} onChange={set("full_name")} required />
            <input type="email" placeholder="e-mail" value={user.email} onChange={set("email")} required />
            <input type="password" placeholder="hasło (min. 6 znaków)" value={user.password} onChange={set("password")} required minLength={6} />
            {user.role === "STUDENT" && <>
              <input placeholder="numer indeksu" value={user.index_no} onChange={set("index_no")} required />
              <select value={user.program_id} onChange={set("program_id")} required><option value="">kierunek</option>{programs?.map((p) => <option key={p.id} value={p.id}>{p.code} – {p.name}</option>)}</select>
              <input type="number" min={1} max={12} value={user.semester} onChange={set("semester")} />
            </>}
            {user.role === "LECTURER" && <>
              <input placeholder="tytuł, np. dr" value={user.title} onChange={set("title")} />
              <input placeholder="jednostka" value={user.department} onChange={set("department")} required />
            </>}
            <button className="primary">Dodaj</button>
          </form>
        </section>
        <section className="card">
          <h2>Słowniki</h2>
          <h3>Kierunek</h3>
          <form className="inline" onSubmit={form(["code", "name"], "/api/admin/programs", "Dodano kierunek.", reloadPrograms)}>
            <input name="code" placeholder="kod" required style={{ width: 80 }} /><input name="name" placeholder="nazwa" required /><button className="secondary">Dodaj</button>
          </form>
          <h3>Semestr</h3>
          <form className="inline" onSubmit={form(["code", "starts_on", "ends_on"], "/api/admin/terms", "Dodano semestr (odśwież stronę).")}>
            <input name="code" placeholder="np. 2027L" required style={{ width: 80 }} /><input name="starts_on" type="date" required /><input name="ends_on" type="date" required /><button className="secondary">Dodaj</button>
          </form>
          <h3>Sala</h3>
          <form className="inline" onSubmit={form(["building", "number", "seats"], "/api/admin/rooms", "Dodano salę.")}>
            <input name="building" placeholder="budynek" required style={{ width: 90 }} /><input name="number" placeholder="numer" required style={{ width: 80 }} />
            <input name="seats" type="number" min={1} placeholder="miejsca" required style={{ width: 90 }} /><button className="secondary">Dodaj</button>
          </form>
        </section>
      </div>
    </main>
  );
}
