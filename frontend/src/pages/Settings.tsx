import { Bot, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, ErrorNote, PageHeader, Table } from "../components/ui";
import { datetime } from "../format";
import { usePoll } from "../hooks";

interface SettingsResp { settings: Record<string, { value: any; updated_by: string; updated_at: string }>; runtime: Record<string, any> }
interface Role { name: string; description: string; permissions: string[] }
interface UserRow { username: string; full_name: string; role: string; is_active: boolean; last_login_at: string | null }
const PERMS = ["read", "ai:investigate", "remediation:propose", "remediation:approve", "remediation:approve_high", "incident:update", "simulator:run", "deployment:create", "audit:read", "settings:write", "users:manage"];

export default function SettingsPage() {
  const { can } = useAuth();
  const { data, refresh } = usePoll<SettingsResp>("/api/settings", 0);
  const { data: roles } = usePoll<Role[]>("/api/auth/roles", 0);
  const { data: users } = usePoll<UserRow[]>(can("users:manage") ? "/api/auth/users" : null, 0);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const writable = can("settings:write");
  const s = data?.settings;

  async function save(patch: Record<string, unknown>) {
    setBusy(true); setError(null);
    try { await api("/api/settings", { method: "PUT", json: { ...patch, reason: reason || "updated from settings page" } }); setReason(""); refresh(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Settings" subtitle="Changes are permission-checked (ADMIN) and recorded in the audit log." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Bot className="h-4 w-4 text-violet-300" />Autonomous remediation</span>}
              subtitle="Autopilot may execute LOW-risk actions (restart_pod, clear_failed_job) when AI confidence meets the threshold. MEDIUM/HIGH always need a human.">
          {s && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div><div className="text-sm font-medium">Autopilot for LOW-risk actions</div><div className="text-xs text-ink-400">last changed by {s.autonomous_mode.updated_by} · {datetime(s.autonomous_mode.updated_at)}</div></div>
                <button disabled={!writable || busy} onClick={() => save({ autonomous_mode: !s.autonomous_mode.value })}
                        className={`relative h-6 w-11 rounded-full transition disabled:opacity-50 ${s.autonomous_mode.value ? "bg-violet-500" : "bg-ink-600"}`} aria-label="toggle autonomous mode">
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${s.autonomous_mode.value ? "left-5.5" : "left-0.5"}`} />
                </button>
              </div>
              <div>
                <div className="flex justify-between text-sm"><span>Minimum AI confidence for autopilot</span><span className="num">{Math.round(s.autonomous_min_confidence.value * 100)}%</span></div>
                <input type="range" min={50} max={99} defaultValue={Math.round(s.autonomous_min_confidence.value * 100)} disabled={!writable}
                       onMouseUp={(e) => save({ autonomous_min_confidence: Number((e.target as HTMLInputElement).value) / 100 })} className="mt-2 w-full accent-violet-500" />
              </div>
              <div className="flex items-center justify-between text-sm"><span>Max remediation attempts per incident</span>
                <select disabled={!writable} value={s.max_remediations_per_incident.value} onChange={(e) => save({ max_remediations_per_incident: Number(e.target.value) })} className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs">
                  {[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}
                </select></div>
              <input value={reason} onChange={(e) => setReason(e.target.value)} disabled={!writable} placeholder="Reason for change (audited)" className="w-full rounded-lg border border-ink-600 bg-ink-850 px-3 py-1.5 text-sm disabled:opacity-50" />
              {!writable && <p className="text-xs text-ink-400">Read-only: changing settings requires ADMIN.</p>}
              <ErrorNote error={error} />
            </div>
          )}
        </Card>
        <Card title="Runtime">
          <Table head={["Key", "Value"]}>
            {data && Object.entries(data.runtime).map(([k, v]) => <tr key={k}><td className="px-3 py-1.5 font-mono text-xs text-ink-300">{k}</td><td className="px-3 font-mono text-xs">{String(v)}</td></tr>)}
          </Table>
          <p className="mt-3 text-xs text-ink-400">Secrets (JWT key, DB password, LLM API key) come from environment variables / Kubernetes Secrets and are never returned by the API.</p>
        </Card>
      </div>
      <Card title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-300" />Role-based access control</span>} subtitle="Enforced on the backend for every request; the UI only mirrors it." className="mt-5" pad={false}>
        <Table head={["Permission", ...(roles?.map((r) => r.name) ?? [])]}>
          {PERMS.map((p) => (
            <tr key={p}><td className="px-3 py-1.5 font-mono text-xs">{p}</td>
              {roles?.map((r) => <td key={r.name} className="px-3 text-center text-xs">{r.permissions.includes(p) ? <span className="text-emerald-300">●</span> : <span className="text-ink-600">○</span>}</td>)}</tr>
          ))}
        </Table>
      </Card>
      {users && (
        <Card title="Users" className="mt-5" pad={false}>
          <Table head={["Username", "Name", "Role", "Active", "Last login"]}>
            {users.map((u) => <tr key={u.username}><td className="px-3 py-1.5 font-mono text-xs">{u.username}</td><td className="px-3 text-xs">{u.full_name}</td><td className="px-3"><Badge value="INFO" label={u.role} /></td><td className="px-3 text-xs">{u.is_active ? "yes" : "no"}</td><td className="px-3 text-xs text-ink-400">{datetime(u.last_login_at)}</td></tr>)}
          </Table>
        </Card>
      )}
    </>
  );
}
