import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import type { Incident, Pod, ServiceHealth } from "../api";
import { MetricGrid } from "../components/MetricGrid";
import { Badge, Card, PageHeader, SimTag, Spinner, Table } from "../components/ui";
import { ago, datetime, duration } from "../format";
import { usePoll } from "../hooks";

interface Detail { name: string; kind: string; tier: string; owner_team: string; description: string; simulated: boolean; health: ServiceHealth; pods: Pod[];
  deployment: { version: string; history: string[]; replicas: number }; dependencies: { name: string; type: string }[]; dependents: string[]; active_incidents: Incident[] }
interface Dep { id: number; version: string; previous_version: string | null; kind: string; actor: string; created_at: string; notes: string }

export default function ServiceDetail() {
  const { name } = useParams();
  const { data } = usePoll<Detail>(`/api/services/${name}`, 2500);
  const { data: deps } = usePoll<Dep[]>(`/api/deployments?service=${name}&limit=10`, 5000);
  if (!data) return <Spinner />;
  return (
    <>
      <Link to="/services" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-400 hover:text-ink-200"><ArrowLeft className="h-3.5 w-3.5" />Services</Link>
      <PageHeader title={data.name} subtitle={<span className="flex items-center gap-2">{data.description} · {data.tier} · owned by {data.owner_team} <SimTag simulated={data.simulated} /></span>}
                  actions={<Badge value={data.health.status} className="text-sm" />} />
      {data.health.reasons.length > 0 && <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">{data.health.reasons.join(" · ")}</div>}
      {data.active_incidents.map((i) => (
        <Link key={i.id} to={`/incidents/${i.incident_id}`} className="mb-4 flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200 hover:bg-rose-500/15">
          <Badge value={i.severity} /> {i.incident_id}: {i.title} <span className="ml-auto text-xs">{ago(i.detected_at)}</span>
        </Link>
      ))}
      <MetricGrid service={data.name} kind={data.kind} />
      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card title={`Pods (${data.pods.length})`} subtitle={`desired replicas ${data.deployment.replicas}`} pad={false}>
          <Table head={["Pod", "Phase", "Ready", "Node", "Version", "Restarts", "Memory", "Age"]}>
            {data.pods.map((p) => (
              <tr key={p.name}>
                <td className="px-3 py-2 font-mono text-xs">{p.name}</td><td className="px-3"><Badge value={p.phase === "Running" ? "HEALTHY" : p.phase === "Terminating" || p.phase === "Pending" ? "UNKNOWN" : "UNHEALTHY"} label={p.phase} /></td>
                <td className="px-3 text-xs">{p.ready ? "✓" : "✗"}</td><td className="px-3 text-xs text-ink-400">{p.node}</td><td className="px-3 font-mono text-xs">{p.version}</td>
                <td className={`num px-3 text-xs ${p.recent_restarts ? "text-rose-300" : ""}`}>{p.restarts}{p.last_termination_reason ? ` (${p.last_termination_reason})` : ""}</td>
                <td className={`num px-3 text-xs ${p.memory_percent > 85 ? "text-rose-300" : ""}`}>{p.memory_mb.toFixed(0)}/{p.memory_limit_mb.toFixed(0)} MiB</td>
                <td className="num px-3 text-xs text-ink-400">{duration(p.age_seconds)}</td>
              </tr>
            ))}
          </Table>
        </Card>
        <div className="space-y-5">
          <Card title="Dependencies">
            <div className="text-xs text-ink-400">Calls</div>
            <div className="mb-2 mt-1 flex flex-wrap gap-1.5">{data.dependencies.length ? data.dependencies.map((d) => <Link key={d.name} to={`/services/${d.name}`} className="rounded bg-ink-800 px-2 py-0.5 font-mono text-xs hover:text-sky-200">{d.name} <span className="text-ink-400">{d.type}</span></Link>) : <span className="text-xs text-ink-400">none</span>}</div>
            <div className="text-xs text-ink-400">Called by</div>
            <div className="mt-1 flex flex-wrap gap-1.5">{data.dependents.length ? data.dependents.map((d) => <Link key={d} to={`/services/${d}`} className="rounded bg-ink-800 px-2 py-0.5 font-mono text-xs hover:text-sky-200">{d}</Link>) : <span className="text-xs text-ink-400">none</span>}</div>
          </Card>
          <Card title="Deployment history" pad={false}>
            <Table head={["When", "Kind", "Version", "Actor"]}>
              {deps?.map((d) => (
                <tr key={d.id} title={d.notes}><td className="px-3 py-1.5 text-xs text-ink-400">{datetime(d.created_at)}</td><td className="px-3 text-xs">{d.kind}</td>
                  <td className="px-3 font-mono text-xs">{d.previous_version ? `${d.previous_version} → ` : ""}{d.version}</td><td className="px-3 text-xs">{d.actor}</td></tr>
              ))}
            </Table>
          </Card>
        </div>
      </div>
    </>
  );
}
