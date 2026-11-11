import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Fragment, useState } from "react";
import type { AuditEntry } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, Empty, PageHeader, Table } from "../components/ui";
import { datetime, pct } from "../format";
import { usePoll } from "../hooks";

export default function Audit() {
  const { can } = useAuth();
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const params = new URLSearchParams({ limit: "300" });
  if (actor) params.set("actor", actor);
  if (action) params.set("action", action);
  const allowed = can("audit:read");
  const { data } = usePoll<AuditEntry[]>(allowed ? `/api/audit?${params}` : null, 3000);
  const { data: chain } = usePoll<{ valid: boolean; checked: number; broken_at?: number }>(allowed ? "/api/audit/verify" : null, 10000);
  if (!allowed) return <><PageHeader title="Audit Logs" /><Empty>Your role cannot read the audit log (requires SRE or ADMIN).</Empty></>;
  return (
    <>
      <PageHeader title="Audit Logs" subtitle="Append-only and SHA-256 hash-chained: each record commits to the previous one, so edits to history are detectable."
        actions={chain && (chain.valid
          ? <span className="flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-300 ring-1 ring-emerald-500/30"><ShieldCheck className="h-4 w-4" />Chain verified · {chain.checked} records</span>
          : <span className="flex items-center gap-1.5 rounded-lg bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300 ring-1 ring-rose-500/30"><ShieldAlert className="h-4 w-4" />Tampering detected at #{chain.broken_at}</span>)} />
      <Card pad={false} title={<div className="flex gap-2">
        <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="actor" className="w-36 rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs" />
        <input value={action} onChange={(e) => setAction(e.target.value)} placeholder="action prefix (e.g. remediation)" className="w-60 rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs" />
      </div>}>
        <Table head={["Time", "Actor", "Role", "Action", "Target", "Result", "AI conf.", "Reason", ""]}>
          {data?.map((a) => (
            <Fragment key={a.id}>
              <tr className="cursor-pointer hover:bg-ink-850" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-ink-400">{datetime(a.timestamp)}</td>
                <td className="px-3 font-mono text-xs">{a.actor}</td><td className="px-3 text-xs">{a.role}</td>
                <td className="px-3 font-mono text-xs text-sky-200">{a.action}</td><td className="max-w-40 truncate px-3 font-mono text-xs">{a.target}</td>
                <td className="px-3"><Badge value={a.result} /></td><td className="num px-3 text-xs">{pct(a.ai_confidence, 0)}</td>
                <td className="max-w-80 truncate px-3 text-xs text-ink-300">{a.reason}</td><td className="px-3 text-xs text-ink-400">{open === a.id ? "▾" : "▸"}</td>
              </tr>
              {open === a.id && (
                <tr><td colSpan={9} className="bg-ink-850 px-4 py-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div><div className="mb-1 text-[10px] uppercase tracking-wider text-ink-400">Before state</div><pre className="max-h-64 overflow-auto rounded bg-ink-950 p-2 text-[11px] text-ink-300">{JSON.stringify(a.before_state, null, 2)}</pre></div>
                    <div><div className="mb-1 text-[10px] uppercase tracking-wider text-ink-400">After state</div><pre className="max-h-64 overflow-auto rounded bg-ink-950 p-2 text-[11px] text-ink-300">{JSON.stringify(a.after_state, null, 2)}</pre></div>
                  </div>
                  <div className="mt-2 break-all font-mono text-[10px] text-ink-400">hash {a.hash} ← prev {a.prev_hash}{a.source_ip ? ` · ip ${a.source_ip}` : ""}</div>
                </td></tr>
              )}
            </Fragment>
          ))}
        </Table>
      </Card>
    </>
  );
}
