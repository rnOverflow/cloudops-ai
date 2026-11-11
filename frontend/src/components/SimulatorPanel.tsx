import { Cpu, Database, Flame, Gauge, MemoryStick, Rocket, ServerCrash, Skull, TrendingUp, Workflow, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { usePoll } from "../hooks";
import { Button, Card, ErrorNote, SimTag } from "./ui";

export const FAULT_BUTTONS = [
  { fault: "high_cpu", label: "Simulate High CPU", icon: Cpu },
  { fault: "memory_leak", label: "Simulate Memory Leak", icon: MemoryStick },
  { fault: "db_saturation", label: "Simulate Database Saturation", icon: Database },
  { fault: "pod_crash", label: "Simulate Pod Crash", icon: Skull },
  { fault: "latency_spike", label: "Simulate Latency Spike", icon: Gauge },
  { fault: "deployment_failure", label: "Simulate Deployment Failure", icon: Rocket },
  { fault: "traffic_spike", label: "Simulate Traffic Spike", icon: TrendingUp },
  { fault: "outage", label: "Simulate Service Outage", icon: ServerCrash },
  { fault: "queue_backlog", label: "Simulate Queue Backlog", icon: Workflow },
];

interface SimState { enabled: boolean; simulated: boolean; faults: Record<string, string>; active: { type: string; service: string; since_tick: number; pod?: string; version?: string; job_id?: string }[] }

export function SimulatorPanel({ compact = false }: { compact?: boolean }) {
  const { can } = useAuth();
  const { data, refresh } = usePoll<SimState>("/api/simulator", 3000);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allowed = can("simulator:run");

  async function run(path: string, json?: unknown, key = path) {
    setBusy(key); setError(null);
    try { await api(path, { method: "POST", json }); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <Card title={<span className="flex items-center gap-2"><Flame className="h-4 w-4 text-orange-400" />Failure Simulator <SimTag simulated /></span>}
          subtitle="Injects real faults into the LocalCloudProvider. Telemetry, detection and remediation react to the modelled state."
          actions={<Button variant="ghost" disabled={!allowed || !data?.active.length} loading={busy === "clear"} onClick={() => run("/api/simulator/clear", undefined, "clear")}><XCircle className="h-3.5 w-3.5" />Clear all</Button>}>
      {!data?.enabled && data && <ErrorNote error="The active cloud provider does not support fault injection." />}
      <div className={compact ? "grid grid-cols-1 gap-2 sm:grid-cols-2" : "grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3"}>
        {FAULT_BUTTONS.map(({ fault, label, icon: Icon }) => {
          const active = data?.active.some((a) => a.type === fault);
          return (
            <button key={fault} disabled={!allowed || !!busy || !data?.enabled} onClick={() => run("/api/simulator/inject", { fault }, fault)}
              title={data?.faults[fault]}
              className={`group flex items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-[13px] transition disabled:cursor-not-allowed disabled:opacity-50 ${active ? "border-orange-500/50 bg-orange-500/10 text-orange-200" : "border-ink-700 bg-ink-850 text-ink-200 hover:border-orange-500/40 hover:bg-ink-800"}`}>
              <Icon className={`h-4 w-4 shrink-0 ${active ? "text-orange-300" : "text-ink-400 group-hover:text-orange-300"}`} />
              <span className="flex-1">{label}</span>
              {active && <span className="h-2 w-2 animate-pulse rounded-full bg-orange-400" />}
            </button>
          );
        })}
      </div>
      {!allowed && <p className="mt-3 text-xs text-ink-400">Your role cannot run simulations (requires SRE or ADMIN).</p>}
      <ErrorNote error={error} />
      {data && data.active.length > 0 && (
        <div className="mt-3 space-y-1">
          {data.active.map((a, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md bg-ink-850 px-2.5 py-1.5 text-xs text-ink-300">
              <span className="h-1.5 w-1.5 rounded-full bg-orange-400" />
              <span className="font-semibold text-orange-200">{a.type}</span> on <span className="font-mono">{a.service}</span>
              {a.pod && <span className="font-mono text-ink-400">pod {a.pod}</span>}
              {a.version && <span className="font-mono text-ink-400">{a.version}</span>}
              {a.job_id && <span className="font-mono text-ink-400">{a.job_id}</span>}
              <span className="ml-auto text-ink-400">{data.faults[a.type]}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
