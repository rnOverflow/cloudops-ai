import { useState } from "react";
import { Link } from "react-router-dom";
import type { Incident } from "../api";
import { Badge, Card, Empty, PageHeader, Spinner, Table } from "../components/ui";
import { ago, duration, pct } from "../format";
import { usePoll } from "../hooks";

const FILTERS = ["ALL", "ACTIVE", "RESOLVED", "CLOSED"] as const;

export default function Incidents() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("ALL");
  const q = filter === "ALL" ? "" : filter === "ACTIVE" ? "?active=true" : `?status=${filter}`;
  const { data, loading } = usePoll<Incident[]>(`/api/incidents${q}`, 2500);
  return (
    <>
      <PageHeader title="Incidents" subtitle="Correlated along the dependency graph. One incident per root cause, with downstream symptoms attached."
        actions={<div className="flex rounded-lg border border-ink-700 bg-ink-850 p-0.5">{FILTERS.map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={`rounded-md px-2.5 py-1 text-xs ${filter === f ? "bg-ink-700 text-ink-100" : "text-ink-400 hover:text-ink-200"}`}>{f}</button>
        ))}</div>} />
      <Card pad={false}>
        {loading && !data ? <Spinner /> : !data?.length ? <div className="p-4"><Empty>No incidents match this filter.</Empty></div> : (
          <Table head={["Incident", "Severity", "Service", "Status", "Remediation", "Probable root cause", "Confidence", "Detected", "TTD", "TTR"]}>
            {data.map((i) => (
              <tr key={i.id} className="hover:bg-ink-850">
                <td className="px-3 py-2.5"><Link to={`/incidents/${i.incident_id}`} className="font-mono text-sky-300 hover:underline">{i.incident_id}</Link>
                  <div className="max-w-64 truncate text-xs text-ink-400">{i.title}</div></td>
                <td className="px-3"><Badge value={i.severity} /></td>
                <td className="px-3 font-mono text-xs">{i.service}{i.correlated_services.length > 0 && <div className="text-[10px] text-ink-400">+{i.correlated_services.length} impacted</div>}</td>
                <td className="px-3"><Badge value={i.status} /></td>
                <td className="px-3"><Badge value={i.remediation_status} /></td>
                <td className="max-w-72 truncate px-3 text-xs text-ink-200">{i.probable_root_cause ?? "—"}</td>
                <td className="num px-3 text-xs">{pct(i.confidence, 0)}</td>
                <td className="whitespace-nowrap px-3 text-xs text-ink-400">{ago(i.detected_at)}</td>
                <td className="num px-3 text-xs">{duration(i.time_to_detect_seconds)}</td>
                <td className="num px-3 text-xs">{duration(i.time_to_resolve_seconds)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
