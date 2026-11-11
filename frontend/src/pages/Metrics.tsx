import { useState } from "react";
import type { ServiceInfo } from "../api";
import { MetricGrid } from "../components/MetricGrid";
import { PageHeader, SimTag } from "../components/ui";
import { usePoll } from "../hooks";

const WINDOWS = [{ label: "2 min", v: 60 }, { label: "5 min", v: 150 }, { label: "15 min", v: 450 }, { label: "1 h", v: 1800 }];

export default function Metrics() {
  const { data } = usePoll<{ services: ServiceInfo[]; simulated: boolean }>("/api/services", 0);
  const [svc, setSvc] = useState("payment-service");
  const [win, setWin] = useState(150);
  const kind = data?.services.find((s) => s.name === svc)?.kind ?? "http";
  return (
    <>
      <PageHeader title="Metrics" subtitle={<span className="flex items-center gap-2">CPU, memory, latency, throughput, errors, HTTP status, restarts, connections, network, availability <SimTag simulated={data?.simulated} /></span>}
        actions={<>
          <select value={svc} onChange={(e) => setSvc(e.target.value)} className="rounded-lg border border-ink-600 bg-ink-850 px-2.5 py-1.5 text-sm">
            {data?.services.map((s) => <option key={s.name}>{s.name}</option>)}
          </select>
          <div className="flex rounded-lg border border-ink-700 bg-ink-850 p-0.5">{WINDOWS.map((w) => (
            <button key={w.v} onClick={() => setWin(w.v)} className={`rounded-md px-2.5 py-1 text-xs ${win === w.v ? "bg-ink-700 text-ink-100" : "text-ink-400"}`}>{w.label}</button>
          ))}</div>
        </>} />
      <MetricGrid service={svc} kind={kind} window={win} />
      <p className="mt-4 text-xs text-ink-400">Long-term retention lives in Prometheus (scraped from <code>/metrics</code>) with Grafana dashboards in the docker-compose stack.</p>
    </>
  );
}
