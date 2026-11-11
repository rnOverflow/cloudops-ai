import clsx from "clsx";
import {
  ArrowLeft, BadgeCheck, Bot, CheckCircle2, CircleDot, FileSearch, Hammer, Link2, Search, ShieldCheck, Siren, ThumbsDown, ThumbsUp, XCircle,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type IncidentDetail as Detail, type Remediation } from "../api";
import { useAuth } from "../auth";
import { ConfidenceBar, InvestigationView } from "../components/InvestigationView";
import { LogList } from "../components/LogList";
import { Badge, Button, Card, Empty, ErrorNote, Spinner, Table } from "../components/ui";
import { datetime, duration, humanize, pct, time } from "../format";
import { usePoll } from "../hooks";

/** The 8 lifecycle stages the platform tracks, and the event types that complete each. */
const STAGES: { key: string; label: string; events: string[]; icon: typeof Siren }[] = [
  { key: "detection", label: "Detection", events: ["DETECTED"], icon: Siren },
  { key: "investigation", label: "Investigation", events: ["INVESTIGATION_STARTED", "EVIDENCE_COLLECTED"], icon: Search },
  { key: "rca", label: "Root cause", events: ["ROOT_CAUSE_IDENTIFIED"], icon: FileSearch },
  { key: "recommendation", label: "Recommendation", events: ["RECOMMENDATION"], icon: Bot },
  { key: "approval", label: "Approval", events: ["APPROVED", "REJECTED"], icon: ShieldCheck },
  { key: "remediation", label: "Remediation", events: ["REMEDIATION_EXECUTED", "REMEDIATION_FAILED"], icon: Hammer },
  { key: "verification", label: "Verification", events: ["VERIFICATION_PASSED", "VERIFICATION_FAILED"], icon: BadgeCheck },
  { key: "resolution", label: "Resolution", events: ["RESOLVED", "CLOSED"], icon: CheckCircle2 },
];

const EVENT_TONE: Record<string, string> = {
  DETECTED: "text-rose-300", SIGNAL_ADDED: "text-ink-300", CORRELATED: "text-amber-300", MERGED: "text-amber-300", SEVERITY_CHANGED: "text-orange-300",
  INVESTIGATION_STARTED: "text-violet-300", EVIDENCE_COLLECTED: "text-violet-300", ROOT_CAUSE_IDENTIFIED: "text-violet-200", RUNBOOK_RETRIEVED: "text-amber-200",
  RECOMMENDATION: "text-sky-300", APPROVAL_REQUESTED: "text-amber-300", APPROVED: "text-emerald-300", REJECTED: "text-rose-300",
  REMEDIATION_STARTED: "text-sky-300", REMEDIATION_EXECUTED: "text-sky-200", REMEDIATION_FAILED: "text-rose-300", VERIFICATION_PASSED: "text-emerald-300",
  VERIFICATION_FAILED: "text-rose-300", RESOLVED: "text-emerald-300", CLOSED: "text-ink-300", NOTE: "text-ink-300",
};

type Tab = "overview" | "evidence" | "logs" | "signals";

export default function IncidentDetail() {
  const { key } = useParams();
  const { data, error, refresh } = usePoll<Detail>(`/api/incidents/${key}`, 2000);
  const [tab, setTab] = useState<Tab>("overview");
  if (error && !data) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;
  const latestInv = data.investigations[data.investigations.length - 1]?.result;
  const pending = data.remediations.find((r) => r.status === "PROPOSED");
  const latestRem = data.remediations[data.remediations.length - 1];

  return (
    <>
      <Link to="/incidents" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-400 hover:text-ink-200"><ArrowLeft className="h-3.5 w-3.5" />Incidents</Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-ink-400">{data.incident_id}</span>
            <Badge value={data.severity} /><Badge value={data.status} /><Badge value={data.remediation_status} />
          </div>
          <h1 className="mt-1.5 text-xl font-semibold">{data.title}</h1>
          <p className="mt-1 text-sm text-ink-400">
            Service <Link className="font-mono text-ink-200 hover:underline" to={`/services/${data.service}`}>{data.service}</Link>
            {data.correlated_services.length > 0 && <> · impacting <span className="font-mono text-ink-200">{data.correlated_services.join(", ")}</span></>}
            {" "}· detected {datetime(data.detected_at)}
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-right text-xs">
          <KV label="Time to detect" value={duration(data.time_to_detect_seconds)} />
          <KV label="Time to resolve" value={duration(data.time_to_resolve_seconds)} />
          <KV label="Signals" value={String(data.signals.length)} />
        </div>
      </div>

      <Lifecycle detail={data} />

      {pending && <ApprovalPanel rem={pending} detail={data} onDone={refresh} />}

      <div className="mb-4 mt-5 flex gap-1 border-b border-ink-800">
        {(["overview", "evidence", "logs", "signals"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={clsx("-mb-px border-b-2 px-3 py-2 text-[13px] capitalize", tab === t ? "border-sky-400 text-ink-100" : "border-transparent text-ink-400 hover:text-ink-200")}>
            {t === "evidence" ? "View evidence" : t === "logs" ? "View logs" : t}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="space-y-5">
            <Card title="Root cause analysis">
              {data.probable_root_cause ? (
                <div className="space-y-2">
                  <p className="text-[15px]">{data.probable_root_cause} <span className="text-ink-400">in</span> <span className="font-mono">{data.root_cause_service}</span></p>
                  <div className="flex items-center gap-2 text-sm text-ink-400">AI confidence <ConfidenceBar value={data.confidence ?? 0} /></div>
                  {latestInv && <p className="text-sm text-ink-300">{latestInv.summary}</p>}
                </div>
              ) : <p className="text-sm text-ink-400">Investigation in progress…</p>}
              {data.resolution_note && <p className="mt-3 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{data.resolution_note}</p>}
            </Card>
            {data.remediations.length > 0 && <RemediationHistory rems={data.remediations} />}
            {latestRem?.verification?.checks && <VerificationCard rem={latestRem} />}
          </div>
          <Timeline detail={data} />
        </div>
      )}
      {tab === "evidence" && (latestInv ? <InvestigationView result={latestInv} /> : <Empty>No investigation recorded yet.</Empty>)}
      {tab === "logs" && <LogsTab detail={data} />}
      {tab === "signals" && (
        <Card pad={false}>
          <Table head={["Rule", "Service", "Metric", "Value", "Threshold", "Severity", "Type", "First breach"]}>
            {data.signals.map((s, i) => (
              <tr key={i}>
                <td className="px-3 py-2 font-mono text-xs">{s.rule}</td><td className="px-3 font-mono text-xs">{s.service}</td><td className="px-3 text-xs">{s.metric}</td>
                <td className="num px-3 text-xs">{s.value.toFixed(4)}</td><td className="num px-3 text-xs">{s.threshold}</td><td className="px-3"><Badge value={s.severity} /></td>
                <td className="px-3 text-xs">{s.kind}{s.detail?.zscore != null && <span className="text-ink-400"> (z={String(s.detail.zscore)})</span>}</td><td className="px-3 text-xs text-ink-400">{time(s.first_breach_ts)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2"><div className="text-[10px] uppercase tracking-wider text-ink-400">{label}</div><div className="num text-sm">{value}</div></div>;
}

function Lifecycle({ detail }: { detail: Detail }) {
  const types = new Set(detail.events.map((e) => e.type));
  const firstTs = (events: string[]) => detail.events.find((e) => events.includes(e.type))?.ts;
  const failed = (k: string) => (k === "approval" && types.has("REJECTED") && !types.has("APPROVED")) || (k === "verification" && types.has("VERIFICATION_FAILED") && !types.has("VERIFICATION_PASSED")) || (k === "remediation" && types.has("REMEDIATION_FAILED") && !types.has("REMEDIATION_EXECUTED"));
  const doneIdx = STAGES.reduce((acc, s, i) => (s.events.some((e) => types.has(e)) ? i : acc), -1);
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-700/70 bg-ink-900/80 p-4">
      <ol className="flex min-w-[820px] items-start">
        {STAGES.map((s, i) => {
          const done = s.events.some((e) => types.has(e));
          const bad = failed(s.key);
          const current = !done && i === doneIdx + 1 && detail.status !== "RESOLVED" && detail.status !== "CLOSED";
          const Icon = s.icon;
          return (
            <li key={s.key} className="relative flex flex-1 flex-col items-center text-center">
              {i > 0 && <span className={clsx("absolute right-1/2 top-4 h-0.5 w-full -translate-y-1/2", i <= doneIdx ? "bg-emerald-500/60" : "bg-ink-700")} />}
              <span className={clsx("relative z-10 grid h-8 w-8 place-items-center rounded-full ring-2",
                bad ? "bg-rose-500/20 text-rose-300 ring-rose-500/60" : done ? "bg-emerald-500/20 text-emerald-300 ring-emerald-500/60" : current ? "bg-amber-500/15 text-amber-300 ring-amber-500/60 animate-pulse" : "bg-ink-850 text-ink-400 ring-ink-700")}>
                {bad ? <XCircle className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </span>
              <span className={clsx("mt-2 text-[12px] font-medium", done ? "text-ink-100" : "text-ink-400")}>{s.label}</span>
              <span className="num text-[10px] text-ink-400">{time(firstTs(s.events)) === "—" ? (current ? "in progress" : "") : time(firstTs(s.events))}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function ApprovalPanel({ rem, detail, onDone }: { rem: Remediation; detail: Detail; onDone: () => void }) {
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const needsAdmin = rem.risk === "HIGH";
  const allowed = needsAdmin ? can("remediation:approve_high") : can("remediation:approve");
  const decide = async (kind: "approve" | "reject") => {
    setBusy(kind); setError(null);
    try { await api(`/api/remediations/${rem.id}/${kind}`, { method: "POST", json: { reason } }); setReason(""); onDone(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const before = rem.before_state?.[rem.target_service] ?? detail.metrics;
  return (
    <div className="mt-5 rounded-xl border border-amber-500/40 bg-gradient-to-br from-amber-500/[0.08] to-transparent p-5">
      <div className="flex flex-wrap items-center gap-2">
        <ShieldCheck className="h-5 w-5 text-amber-300" />
        <h2 className="text-[15px] font-semibold">Human approval required</h2>
        <Badge value={rem.risk} label={`${rem.risk} risk`} />
        {needsAdmin && <span className="text-xs text-amber-200/80">HIGH-risk actions require an ADMIN</span>}
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-4">
        <Field label="Recommended action"><code className="font-mono text-sky-200">{rem.action}({Object.entries(rem.parameters).map(([k, v]) => `${k}=${v}`).join(", ")})</code><div className="text-xs text-ink-400">on <span className="font-mono">{rem.target_service}</span> · proposed by {rem.proposed_by}</div></Field>
        <Field label="AI confidence">{rem.ai_confidence != null ? <ConfidenceBar value={rem.ai_confidence} /> : <span className="text-ink-400">n/a (operator proposal)</span>}</Field>
        <Field label="Risk assessment (policy engine)"><ul className="text-xs text-ink-300">{(rem.verification?.risk_reasons ?? []).map((r) => <li key={r}>• {r}</li>)}</ul></Field>
        <Field label="Expected impact"><span className="text-[13px] text-ink-200">{rem.expected_impact}</span></Field>
      </div>
      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_1fr]">
        <Field label="Evidence"><p className="text-[13px] text-ink-200">{rem.rationale}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">{detail.signals.filter((s) => s.kind === "rule").slice(0, 5).map((s, i) => <span key={i} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-300">{s.service}:{s.rule}</span>)}</div></Field>
        <Field label="Current state">
          <div className="num grid grid-cols-4 gap-2 text-xs">
            <span>CPU {Number(before.cpu_percent ?? 0).toFixed(0)}%</span><span>err {pct(Number(before.error_rate ?? 0), 1)}</span>
            <span>p95 {Number(before.latency_p95_ms ?? 0).toFixed(0)}ms</span><span>pods {before.healthy_pods ?? "—"}/{before.replicas ?? "—"}</span>
          </div>
        </Field>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Decision reason (recorded in the audit log)…" disabled={!allowed}
               className="min-w-64 flex-1 rounded-lg border border-ink-600 bg-ink-850 px-3 py-1.5 text-sm outline-none focus:border-sky-500 disabled:opacity-50" />
        <Button variant="success" disabled={!allowed || reason.trim().length < 3} loading={busy === "approve"} onClick={() => decide("approve")}><ThumbsUp className="h-3.5 w-3.5" />Approve &amp; execute</Button>
        <Button variant="danger" disabled={!allowed || reason.trim().length < 3} loading={busy === "reject"} onClick={() => decide("reject")}><ThumbsDown className="h-3.5 w-3.5" />Reject</Button>
      </div>
      {!allowed && <p className="mt-2 text-xs text-ink-400">Your role cannot approve this remediation.</p>}
      <ErrorNote error={error} />
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</div>{children}</div>;
}

function Timeline({ detail }: { detail: Detail }) {
  return (
    <Card title="Incident timeline" subtitle={`${detail.events.length} events`}>
      <ol className="relative space-y-3 border-l border-ink-700 pl-4">
        {detail.events.map((e) => (
          <li key={e.id} className="relative">
            <span className="absolute -left-[21px] top-1 grid h-2.5 w-2.5 place-items-center rounded-full bg-ink-900 ring-2 ring-ink-600"><CircleDot className={clsx("h-2.5 w-2.5", EVENT_TONE[e.type] ?? "text-ink-400")} /></span>
            <div className="flex items-baseline gap-2">
              <span className={clsx("text-[11px] font-semibold uppercase tracking-wider", EVENT_TONE[e.type] ?? "text-ink-300")}>{humanize(e.type)}</span>
              <span className="num text-[10px] text-ink-400">{time(e.ts)}</span>
              <span className="ml-auto truncate text-[10px] text-ink-400">{e.actor}</span>
            </div>
            <p className="mt-0.5 text-[12.5px] leading-snug text-ink-200">{e.message}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function RemediationHistory({ rems }: { rems: Remediation[] }) {
  return (
    <Card title="Remediations" pad={false}>
      <Table head={["#", "Action", "Target", "Risk", "Status", "Decided by", "Reason", "Executed"]}>
        {rems.map((r) => (
          <tr key={r.id}>
            <td className="num px-3 py-2 text-xs">{r.id}</td>
            <td className="px-3 font-mono text-xs text-sky-200">{r.action}{Object.keys(r.parameters).length ? ` ${JSON.stringify(r.parameters)}` : ""}</td>
            <td className="px-3 font-mono text-xs">{r.target_service}</td><td className="px-3"><Badge value={r.risk} /></td><td className="px-3"><Badge value={r.status} /></td>
            <td className="px-3 text-xs">{r.decided_by ?? "—"}{r.autonomous && <span className="ml-1 text-violet-300">(autopilot)</span>}</td>
            <td className="max-w-56 truncate px-3 text-xs text-ink-400">{r.decision_reason ?? "—"}</td><td className="px-3 text-xs text-ink-400">{time(r.executed_at)}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

function VerificationCard({ rem }: { rem: Remediation }) {
  const checks = rem.verification.checks ?? [];
  const services = Object.keys(rem.before_state).filter((k) => typeof rem.before_state[k] === "object" && k !== "deployment");
  const keys = ["cpu_percent", "memory_max_pod_percent", "latency_p95_ms", "error_rate", "healthy_pods", "db_utilization", "queue_depth"];
  return (
    <Card title={<span className="flex items-center gap-2">Verification <Badge value={rem.verification.result ?? rem.status} /></span>}
          subtitle="Success is decided by re-reading the infrastructure, not by the command's exit status.">
      <ul className="mb-4 space-y-1">
        {checks.map((c, i) => (
          <li key={i} className="flex items-center gap-2 text-[13px]">
            {c.passed ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <XCircle className="h-4 w-4 text-rose-400" />}
            <span className="flex-1">{c.check}</span>
            {c.before != null && <span className="num text-xs text-ink-400">{fmt(c.metric, c.before)} → <span className={c.passed ? "text-emerald-300" : "text-rose-300"}>{fmt(c.metric, c.after as number)}</span></span>}
          </li>
        ))}
      </ul>
      <Table head={["Service", "Metric", "Before", "After"]}>
        {services.flatMap((svc) => keys.filter((k) => rem.before_state[svc]?.[k] !== undefined).map((k) => (
          <tr key={svc + k}>
            <td className="px-3 py-1.5 font-mono text-xs">{svc}</td><td className="px-3 text-xs text-ink-300">{k}</td>
            <td className="num px-3 text-xs">{fmt(k, rem.before_state[svc][k])}</td>
            <td className="num px-3 text-xs">{rem.after_state?.[svc] ? fmt(k, rem.after_state[svc][k]) : "pending"}</td>
          </tr>
        )))}
      </Table>
      <p className="mt-3 flex items-center gap-1 text-xs text-ink-400"><Link2 className="h-3 w-3" />Before captured at execution; after captured {rem.verified_at ? `at ${time(rem.verified_at)}` : "after the verification window"}.</p>
    </Card>
  );
}

function fmt(metric: string | undefined, v: number | null | undefined) {
  if (v == null || typeof v !== "number") return String(v ?? "—");
  if (metric?.includes("error_rate") || metric === "db_utilization") return pct(v, 2);
  if (metric?.includes("percent")) return `${v.toFixed(1)}%`;
  if (metric?.includes("ms")) return `${v.toFixed(0)} ms`;
  return v.toFixed(0);
}

function LogsTab({ detail }: { detail: Detail }) {
  const services = [detail.service, ...detail.correlated_services].join(",");
  const { data } = usePoll<{ logs: Detail["logs"] }>(`/api/logs?service=${detail.root_cause_service ?? detail.service}&level=WARN&limit=150`, 4000);
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card title="Logs captured at detection" subtitle={`WARN+ from ${detail.service}`} pad={false}><LogList logs={detail.logs} /></Card>
      <Card title="Live logs" subtitle={`WARN+ from ${detail.root_cause_service ?? detail.service} · related: ${services}`} pad={false}><LogList logs={data?.logs ?? []} /></Card>
    </div>
  );
}
