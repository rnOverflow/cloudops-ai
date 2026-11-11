import type { SLO } from "../api";
import { Badge, Card, Meter, PageHeader, Spinner, Stat } from "../components/ui";
import { duration, num, pct } from "../format";
import { usePoll } from "../hooks";

interface Rel { window_days: number; incident_count: number; incidents_by_service: Record<string, number>; incidents_by_severity: Record<string, number>; mttd_seconds: number | null; mttr_seconds: number | null; incidents_per_day: number; resolved_count: number; auto_remediated_count: number; availability: Record<string, number> }

export default function SLOPage() {
  const { data: slos } = usePoll<SLO[]>("/api/slo", 4000);
  const { data: rel } = usePoll<Rel>("/api/slo/reliability", 4000);
  return (
    <>
      <PageHeader title="SLO / Reliability" subtitle="Availability SLIs are request-based; latency SLIs are window-based (share of samples with p95 under threshold). 30-day rolling window." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="MTTD" value={duration(rel?.mttd_seconds)} hint="impact start → detection" />
        <Stat label="MTTR" value={duration(rel?.mttr_seconds)} hint="detection → verified resolution" />
        <Stat label="Incidents" value={rel?.incident_count ?? "—"} hint={`${rel?.window_days ?? 30}-day window`} />
        <Stat label="Incident frequency" value={`${num(rel?.incidents_per_day, 1)}/day`} hint="normalised to observed span" />
        <Stat label="Resolved" value={rel?.resolved_count ?? "—"} accent="good" />
        <Stat label="Verified auto-remediations" value={rel?.auto_remediated_count ?? "—"} accent="good" />
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {!slos ? <Spinner /> : slos.map((s) => (
          <Card key={s.id} title={s.name} subtitle={`${s.service} · ${s.sli_type} · target ${pct(s.target, s.target >= 0.999 ? 1 : 2)}`} actions={<Badge value={s.status} />}>
            <div className="flex items-baseline justify-between">
              <span className={`num text-2xl font-semibold ${s.attainment < s.target ? "text-rose-300" : "text-emerald-300"}`}>{pct(s.attainment, 3)}</span>
              <span className="text-xs text-ink-400">{num(s.bad_events, 0)} bad / {num(s.total_events, 0)} {s.sli_type === "latency" ? "samples" : "requests"}</span>
            </div>
            <div className="mt-3 flex justify-between text-xs text-ink-400"><span>Error budget remaining</span><span className="num text-ink-200">{pct(Math.max(0, s.error_budget_remaining), 1)}</span></div>
            <div className="mt-1"><Meter value={Math.max(0, Math.min(1, s.error_budget_consumed))} warn={0.5} bad={0.75} /></div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-md bg-ink-850 px-2 py-1.5"><div className="text-ink-400">Burn rate 5m</div><div className={`num ${s.burn_rate_5m > 14.4 ? "text-rose-300" : "text-ink-100"}`}>{s.burn_rate_5m.toFixed(1)}x</div></div>
              <div className="rounded-md bg-ink-850 px-2 py-1.5"><div className="text-ink-400">Burn rate 1h</div><div className={`num ${s.burn_rate_1h > 6 ? "text-amber-300" : "text-ink-100"}`}>{s.burn_rate_1h.toFixed(1)}x</div></div>
            </div>
          </Card>
        ))}
      </div>
      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <Card title="Incidents by service">{rel && Object.entries(rel.incidents_by_service).length ? Object.entries(rel.incidents_by_service).map(([k, v]) => (
          <div key={k} className="mb-2"><div className="flex justify-between text-xs"><span className="font-mono">{k}</span><span className="num">{v}</span></div><Meter value={v / Math.max(...Object.values(rel.incidents_by_service))} warn={2} bad={2} /></div>
        )) : <p className="text-sm text-ink-400">No incidents in window.</p>}</Card>
        <Card title="Incidents by severity">{rel && Object.entries(rel.incidents_by_severity).length ? Object.entries(rel.incidents_by_severity).map(([k, v]) => (
          <div key={k} className="mb-2 flex items-center justify-between"><Badge value={k} /><span className="num text-sm">{v}</span></div>
        )) : <p className="text-sm text-ink-400">No incidents in window.</p>}</Card>
      </div>
      <p className="mt-4 text-xs text-ink-400">Burn-rate alerting follows the multi-window approach from the Google SRE workbook: 14.4x over a short window pages; 6x over 1h is a ticket.</p>
    </>
  );
}
