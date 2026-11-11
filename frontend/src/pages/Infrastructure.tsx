import { Cloud, Database } from "lucide-react";
import { Topology } from "../components/Topology";
import { Badge, Card, Meter, PageHeader, SimTag, Table } from "../components/ui";
import { pct } from "../format";
import { usePoll } from "../hooks";

interface Provider { provider: string; simulated: boolean; supports_fault_injection: boolean; tick_seconds: number; available_providers: string[]; planned_providers: string[] }
interface DB { engine: string; max_connections: number; active_connections: number; utilization: number; clients: Record<string, number>; status: string; simulated: boolean }

export default function Infrastructure() {
  const { data: p } = usePoll<Provider>("/api/infrastructure/provider", 0);
  const { data: db } = usePoll<DB>("/api/infrastructure/database", 2500);
  return (
    <>
      <PageHeader title="Infrastructure" subtitle={<span className="flex items-center gap-2">Cloud provider, topology and shared data tier <SimTag simulated={p?.simulated} /></span>} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card title="Service topology" subtitle="Click a node to open the service"><Topology height={320} /></Card>
        <div className="space-y-5">
          <Card title={<span className="flex items-center gap-2"><Cloud className="h-4 w-4 text-sky-300" />Cloud provider</span>}>
            <div className="space-y-2 text-sm">
              <Row k="Active provider" v={<span className="font-mono">{p?.provider}</span>} />
              <Row k="Data" v={p?.simulated ? <Badge value="WARN" label="SIMULATED" /> : <Badge value="OK" label="LIVE" />} />
              <Row k="Fault injection" v={p?.supports_fault_injection ? "supported" : "disabled"} />
              <Row k="Sample interval" v={`${p?.tick_seconds}s`} />
              <Row k="Implemented providers" v={p?.available_providers.join(", ")} />
              <Row k="Planned providers" v={p?.planned_providers.join(", ")} />
            </div>
            <p className="mt-3 text-xs text-ink-400">Switch with <code>CLOUD_PROVIDER=aws</code>. The AWSProvider maps services to ECS Fargate, metrics to CloudWatch and logs to CloudWatch Logs.</p>
          </Card>
          <Card title={<span className="flex items-center gap-2"><Database className="h-4 w-4 text-sky-300" />Database</span>} actions={db && <Badge value={db.status === "SATURATED" ? "UNHEALTHY" : db.status === "WARNING" ? "DEGRADED" : "HEALTHY"} label={db.status} />}>
            {db && (
              <>
                <div className="flex justify-between text-sm"><span className="text-ink-400">{db.engine}</span><span className="num">{db.active_connections}/{db.max_connections} connections</span></div>
                <div className="mt-2"><Meter value={db.utilization} /></div>
                <div className="num mt-1 text-right text-xs text-ink-400">{pct(db.utilization, 0)} utilised</div>
                <Table head={["Client", "Connections", "Share"]} className="mt-3">
                  {Object.entries(db.clients).sort((a, b) => b[1] - a[1]).map(([c, n]) => (
                    <tr key={c}><td className="px-3 py-1.5 font-mono text-xs">{c}</td><td className="num px-3 text-xs">{n.toFixed(0)}</td><td className="num px-3 text-xs">{pct(n / Math.max(1, Object.values(db.clients).reduce((a, b) => a + b, 0)), 0)}</td></tr>
                  ))}
                </Table>
              </>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-ink-400">{k}</span><span className="text-right">{v}</span></div>;
}
