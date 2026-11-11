import type { Pod } from "../api";
import { Badge, Card, Meter, PageHeader, SimTag, Table } from "../components/ui";
import { duration } from "../format";
import { usePoll } from "../hooks";

interface Cluster { provider: string; simulated: boolean; cluster: string; kubernetes_version: string; nodes: { name: string; status: string; pods: number; cpu_allocatable: number; cpu_requested: number; memory_allocatable_gb: number; memory_requested_gb: number; zone: string }[]; workloads: { name: string; kind: string; replicas: number; ready_replicas: number; version: string; pods: number; hpa: { min: number; max: number; target_cpu: number } | null }[] }

export default function Kubernetes() {
  const { data } = usePoll<Cluster>("/api/infrastructure/kubernetes", 2500);
  const { data: pods } = usePoll<{ pods: Pod[] }>("/api/infrastructure/pods", 2500);
  return (
    <>
      <PageHeader title="Kubernetes" subtitle={<span className="flex items-center gap-2">Cluster {data?.cluster} · {data?.kubernetes_version} <SimTag simulated={data?.simulated} /></span>} />
      <div className="grid gap-3 md:grid-cols-3">
        {data?.nodes.map((n) => (
          <Card key={n.name} title={n.name} subtitle={`${n.zone} · ${n.pods} pods`} actions={<Badge value="HEALTHY" label={n.status} />}>
            <div className="text-xs text-ink-400">CPU requested {n.cpu_requested} / {n.cpu_allocatable} cores</div>
            <Meter value={n.cpu_requested / n.cpu_allocatable} />
            <div className="mt-2 text-xs text-ink-400">Memory requested {n.memory_requested_gb} / {n.memory_allocatable_gb} GiB</div>
            <Meter value={n.memory_requested_gb / n.memory_allocatable_gb} />
          </Card>
        ))}
      </div>
      <Card title="Workloads" className="mt-5" pad={false}>
        <Table head={["Name", "Kind", "Ready", "Desired", "Version", "HPA"]}>
          {data?.workloads.map((w) => (
            <tr key={w.name}><td className="px-3 py-2 font-mono text-xs">{w.name}</td><td className="px-3 text-xs">{w.kind}</td>
              <td className={`num px-3 text-xs ${w.ready_replicas < w.replicas ? "text-amber-300" : "text-emerald-300"}`}>{w.ready_replicas}</td><td className="num px-3 text-xs">{w.replicas}</td>
              <td className="px-3 font-mono text-xs">{w.version}</td><td className="px-3 text-xs text-ink-400">{w.hpa ? `${w.hpa.min}–${w.hpa.max} @ ${w.hpa.target_cpu}% CPU` : "—"}</td></tr>
          ))}
        </Table>
      </Card>
      <Card title={`Pods (${pods?.pods.length ?? 0})`} className="mt-5" pad={false}>
        <Table head={["Pod", "Service", "Phase", "Ready", "Node", "Restarts", "Memory", "Age"]}>
          {pods?.pods.map((p) => (
            <tr key={p.name}><td className="px-3 py-1.5 font-mono text-xs">{p.name}</td><td className="px-3 text-xs">{p.service}</td>
              <td className="px-3"><Badge value={p.phase === "Running" ? "HEALTHY" : p.phase === "CrashLoopBackOff" ? "UNHEALTHY" : "UNKNOWN"} label={p.phase} /></td>
              <td className="px-3 text-xs">{p.ready ? "✓" : "✗"}</td><td className="px-3 text-xs text-ink-400">{p.node}</td>
              <td className={`num px-3 text-xs ${p.recent_restarts ? "text-rose-300" : ""}`}>{p.restarts}</td>
              <td className={`num px-3 text-xs ${p.memory_percent > 85 ? "text-rose-300" : ""}`}>{p.memory_percent.toFixed(0)}%</td><td className="num px-3 text-xs text-ink-400">{duration(p.age_seconds)}</td></tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
