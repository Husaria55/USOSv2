import { useState, type FormEvent } from "react";
import { api, ApiError, type User } from "../api";

export default function Login({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<{ token: string; user: User }>("/api/auth/login", { body: { email, password } });
      onLogin(r.token, r.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Brak połączenia z serwerem.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main>
      <section className="card login">
        <h2>Zapisy na zajęcia – logowanie</h2>
        <form onSubmit={submit}>
          <input type="email" placeholder="e-mail" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          <input type="password" placeholder="hasło" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button className="primary" disabled={busy}>{busy ? "Logowanie…" : "Zaloguj"}</button>
          {error && <div className="msg bad">{error}</div>}
        </form>
        <p className="muted">Konta demonstracyjne (po <code>python -m app.seed</code>): admin@uczelnia.pl, dr.zachara@uczelnia.pl, s400001@uczelnia.pl – hasło <code>haslo123</code>.</p>
      </section>
    </main>
  );
}
