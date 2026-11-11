import { Link } from "react-router-dom";
import type { ServiceInfo } from "../api";
import { Badge, Card, Dot, PageHeader, SimTag, Spinner, Table } from "../components/ui";
import { ms, num, pct } from "../format";
import { usePoll } from "../hooks";

export default function Services() {
  const { data } = usePoll<{ services: ServiceInfo[]; simulated: boolean }>("/api/services", 2500);
  return (
    <>
      <PageHeader title="Services" subtitle={<span className="flex items-center gap-2">Service catalog with live health and ownership <SimTag simulated={data?.simulated} /></span>} />
      <Card pad={false}>
        {!data ? <Spinner /> : (
          <Table head={["Service", "Status", "Tier", "Owner", "Version", "Pods", "RPS", "CPU", "p95", "Error rate", "Availability", "Depends on"]}>
            {data.services.map((s) => (
              <tr key={s.name} className="hover:bg-ink-850">
                <td className="px-3 py-2.5"><Link to={`/services/${s.name}`} className="flex items-center gap-2 font-medium text-sky-200 hover:underline"><Dot status={s.health.status} />{s.name}</Link>
                  <div className="pl-[18px] text-[11px] text-ink-400">{s.description}</div></td>
                <td className="px-3"><Badge value={s.health.status} /></td>
                <td className="px-3 text-xs">{s.tier}</td><td className="px-3 text-xs text-ink-300">{s.owner_team}</td>
                <td className="px-3 font-mono text-xs">{s.version}</td>
                <td className="num px-3 text-xs">{s.health.healthy_pods}/{s.health.replicas}</td>
                <td className="num px-3 text-xs">{num(s.health.rps, 0)}</td>
                <td className="num px-3 text-xs">{num(s.health.cpu_percent, 0)}%</td>
                <td className="num px-3 text-xs">{ms(s.health.latency_p95_ms)}</td>
                <td className="num px-3 text-xs">{pct(s.health.error_rate, 2)}</td>
                <td className="num px-3 text-xs">{pct(s.health.availability, 2)}</td>
                <td className="px-3 text-[11px] text-ink-400">{s.dependencies.map((d) => `${d.name} (${d.type})`).join(", ") || "—"}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
