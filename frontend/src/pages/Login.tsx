import { Activity, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { Button, ErrorNote } from "../components/ui";

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { await login(username, password); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="grid min-h-full place-items-center bg-[radial-gradient(ellipse_at_top,rgba(14,165,233,0.12),transparent_60%)] p-6">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-ink-700 bg-ink-900/90 p-7 shadow-2xl shadow-black/40">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-sky-400 to-indigo-500"><Activity className="h-5 w-5 text-white" strokeWidth={2.5} /></div>
          <div>
            <h1 className="text-lg font-semibold">CloudOps AI</h1>
            <p className="text-xs text-ink-400">Reliability, observability &amp; self-healing operations</p>
          </div>
        </div>
        <label className="mb-1 block text-xs font-medium text-ink-300" htmlFor="u">Username</label>
        <input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus
               className="mb-3 w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm outline-none focus:border-sky-500" />
        <label className="mb-1 block text-xs font-medium text-ink-300" htmlFor="p">Password</label>
        <input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
               className="mb-4 w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-sm outline-none focus:border-sky-500" />
        <ErrorNote error={error} />
        <Button type="submit" variant="primary" loading={busy} className="mt-3 w-full py-2"><Lock className="h-3.5 w-3.5" />Sign in</Button>
        <p className="mt-4 text-center text-[11px] leading-relaxed text-ink-400">Local demo accounts (admin, sre, developer, viewer) are created by <code className="text-ink-300">make bootstrap</code>; passwords live in your local <code className="text-ink-300">.env</code>.</p>
      </form>
    </div>
  );
}
