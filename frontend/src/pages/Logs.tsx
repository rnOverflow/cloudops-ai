import { Pause, Play } from "lucide-react";
import { useState } from "react";
import type { LogEntry } from "../api";
import { LogList } from "../components/LogList";
import { Button, Card, PageHeader, SimTag } from "../components/ui";
import { usePoll } from "../hooks";

const SERVICES = ["", "api-gateway", "user-service", "payment-service", "notification-service", "database"];

export default function Logs() {
  const [service, setService] = useState("");
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const [live, setLive] = useState(true);
  const params = new URLSearchParams({ limit: "300" });
  if (service) params.set("service", service);
  if (level) params.set("level", level);
  if (q.trim()) params.set("q", q.trim());
  const { data } = usePoll<{ logs: LogEntry[]; simulated: boolean }>(`/api/logs?${params}`, live ? 2000 : 0);
  return (
    <>
      <PageHeader title="Logs" subtitle={<span className="flex items-center gap-2">Structured JSON logs with event codes. Shipped to Loki in the compose stack. <SimTag simulated={data?.simulated} /></span>} />
      <Card pad={false} title={
        <div className="flex flex-wrap items-center gap-2">
          <select value={service} onChange={(e) => setService(e.target.value)} className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs">{SERVICES.map((s) => <option key={s} value={s}>{s || "all services"}</option>)}</select>
          <select value={level} onChange={(e) => setLevel(e.target.value)} className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs"><option value="">all levels</option><option>INFO</option><option value="WARN">WARN+</option><option value="ERROR">ERROR</option></select>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search message…" maxLength={200} className="w-56 rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs outline-none focus:border-sky-500" />
          <span className="num text-xs font-normal text-ink-400">{data?.logs.length ?? 0} lines</span>
        </div>
      } actions={<Button variant="ghost" onClick={() => setLive((l) => !l)}>{live ? <><Pause className="h-3.5 w-3.5" />Pause</> : <><Play className="h-3.5 w-3.5" />Live</>}</Button>}>
        <LogList logs={data?.logs ?? []} />
      </Card>
    </>
  );
}
