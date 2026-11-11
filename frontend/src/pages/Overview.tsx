import { AlertTriangle, CheckCircle2, Clock, Gauge, ShieldAlert, Timer } from "lucide-react";
import { Link } from "react-router-dom";
import type { Incident, ServiceInfo, SLO } from "../api";
import { Sparkline } from "../components/Chart";
import { SimulatorPanel } from "../components/SimulatorPanel";
import { Topology } from "../components/Topology";
import { Badge, Card, Dot, Empty, PageHeader, SimTag, Stat } from "../components/ui";
import { usePoll } from "../hooks";
import { ago, duration, ms, pct } from "../format";

interface Rel { mttd_seconds: number | null; mttr_seconds: number | null; incident_count: number; incidents_per_day: number; availability: Record<string, number>; auto_remediated_count: number }
interface Status { active_incidents: number; pending_approvals: number; services_healthy: number; services_total: number; simulated: boolean }

export default function Overview() {
  const { data: svc } = usePoll<{ services: ServiceInfo[]; simulated: boolean }>("/api/services", 2500);
  const { data: incidents } = usePoll<Incident[]>("/api/incidents?limit=8", 2500);
  const { data: rel } = usePoll<Rel>("/api/slo/reliability", 5000);
  const { data: st } = usePoll<Status>("/api/system/status", 2500);
  const { data: slos } = usePoll<SLO[]>("/api/slo", 5000);
  const { data: series } = usePoll<{ series: Record<string, number[]> }>("/api/metrics/api-gateway?metric=rps&metric=error_rate&metric=latency_p95_ms&window=90", 2500);
  const gw = svc?.services.find((s) => s.name === "api-gateway");
  const availability = rel ? Object.values(rel.availability) : [];
  const minAvail = availability.length ? Math.min(...availability) : null;
  const budgetLow = slos?.filter((s) => s.status !== "OK").length ?? 0;

  return (
    <>
      <PageHeader title="Operations Overview" subtitle={<span className="flex items-center gap-2">What is wrong, why, what to do — and can it be fixed safely? <SimTag simulated={svc?.simulated} /></span>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Service health" value={st ? `${st.services_healthy}/${st.services_total}` : "—"} accent={st && st.services_healthy < st.services_total ? "warn" : "good"} icon={<CheckCircle2 className="h-4 w-4" />} hint="healthy services" />
        <Stat label="Active incidents" value={st?.active_incidents ?? "—"} accent={st?.active_incidents ? "bad" : "good"} icon={<AlertTriangle className="h-4 w-4" />} hint={`${st?.pending_approvals ?? 0} awaiting approval`} />
        <Stat label="MTTD" value={duration(rel?.mttd_seconds)} icon={<Clock className="h-4 w-4" />} hint="mean time to detect" />
        <Stat label="MTTR" value={duration(rel?.mttr_seconds)} icon={<Timer className="h-4 w-4" />} hint="mean time to resolve" />
        <Stat label="Lowest availability" value={pct(minAvail, 3)} accent={minAvail != null && minAvail < 0.999 ? "warn" : "good"} icon={<Gauge className="h-4 w-4" />} hint="across SLO'd services" />
        <Stat label="SLOs at risk" value={budgetLow} accent={budgetLow ? "warn" : "good"} icon={<ShieldAlert className="h-4 w-4" />} hint={`${rel?.auto_remediated_count ?? 0} incidents auto-verified`} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Card title="Service health" subtitle="Live status computed from the latest telemetry sample" pad={false}>
          <div className="grid divide-y divide-ink-800 md:grid-cols-1">
            {svc?.services.map((s) => (
              <Link key={s.name} to={`/services/${s.name}`} className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-2.5 hover:bg-ink-850 md:grid-cols-[auto_1.2fr_repeat(4,minmax(0,0.6fr))_auto]">
                <Dot status={s.health.status} />
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{s.name}</div>
                  <div className="truncate text-[11px] text-ink-400">{s.health.reasons.join(" · ") || `${s.tier} · ${s.version}`}</div>
                </div>
                <Metric label="CPU" value={`${(s.health.cpu_percent ?? 0).toFixed(0)}%`} bad={(s.health.cpu_percent ?? 0) > 85} />
                <Metric label="p95" value={ms(s.health.latency_p95_ms)} bad={(s.health.latency_p95_ms ?? 0) > 500 && s.kind !== "database"} />
                <Metric label="Errors" value={pct(s.health.error_rate, 2)} bad={(s.health.error_rate ?? 0) > 0.05} />
                <Metric label="Pods" value={`${s.health.healthy_pods ?? 0}/${s.health.replicas ?? 0}`} bad={(s.health.healthy_pods ?? 0) < (s.health.replicas ?? 0)} />
                <Badge value={s.health.status} />
              </Link>
            ))}
          </div>
        </Card>
        <Card title="Dependency map" subtitle="Edges show synchronous, async and database calls">
          <Topology height={250} />
        </Card>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_1fr]">
        <Card title="Recent incidents" actions={<Link to="/incidents" className="text-xs text-sky-300 hover:underline">View all</Link>} pad={false}>
          {incidents && incidents.length === 0 && <div className="p-4"><Empty>No incidents yet. Use the simulator to inject a failure.</Empty></div>}
          <div className="divide-y divide-ink-800">
            {incidents?.map((i) => (
              <Link key={i.id} to={`/incidents/${i.incident_id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-ink-850">
                <Badge value={i.severity} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px]"><span className="font-mono text-ink-400">{i.incident_id}</span> {i.title}</div>
                  <div className="truncate text-[11px] text-ink-400">{i.probable_root_cause ? `RCA: ${i.probable_root_cause} (${pct(i.confidence, 0)})` : "Investigating…"}</div>
                </div>
                <Badge value={i.remediation_status === "PENDING_APPROVAL" ? "PENDING_APPROVAL" : i.status} />
                <span className="w-20 text-right text-[11px] text-ink-400">{ago(i.detected_at)}</span>
              </Link>
            ))}
          </div>
        </Card>
        <SimulatorPanel compact />
      </div>

      {gw && series && (
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {([["Edge throughput (req/s)", "rps", "#38bdf8"], ["Edge error rate", "error_rate", "#f43f5e"], ["Edge p95 latency (ms)", "latency_p95_ms", "#a78bfa"]] as const).map(([label, key, color]) => (
            <Card key={key} title={label} subtitle="api-gateway · last 3 minutes">
              <Sparkline values={series.series[key] ?? []} color={color} height={46} />
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

function Metric({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="hidden md:block">
      <div className="text-[10px] uppercase tracking-wider text-ink-400">{label}</div>
      <div className={`num text-[13px] ${bad ? "text-rose-300" : "text-ink-200"}`}>{value}</div>
    </div>
  );
}
