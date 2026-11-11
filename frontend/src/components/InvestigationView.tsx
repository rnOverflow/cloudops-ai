import { BookOpen, Brain, CheckCircle2, Eye, Wrench, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { InvestigationResult } from "../api";
import { pct } from "../format";
import { Badge, Card } from "./ui";

export function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 0.8 ? "bg-emerald-400" : value >= 0.6 ? "bg-amber-400" : "bg-rose-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-28 overflow-hidden rounded-full bg-ink-800"><div className={`h-full ${color}`} style={{ width: `${value * 100}%` }} /></div>
      <span className="num text-xs text-ink-200">{pct(value, 0)}</span>
    </div>
  );
}

export function InvestigationView({ result, compact = false }: { result: InvestigationResult; compact?: boolean }) {
  const [showTools, setShowTools] = useState(!compact);
  const facts = result.findings.filter((f) => f.kind === "OBSERVED_FACT");
  const inferences = result.findings.filter((f) => f.kind === "AI_INFERENCE");
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-sky-500/25 bg-sky-500/[0.06] p-4">
        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-wider text-sky-300">
          <Brain className="h-3.5 w-3.5" />Conclusion
          <span className="text-ink-400 normal-case tracking-normal">· {result.provider}{result.llm_used ? " (LLM output validated)" : ""}</span>
        </div>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-100">{result.summary}</p>
        {result.root_cause && (
          <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <div><span className="text-ink-400">Root cause service </span><span className="font-mono text-ink-100">{result.root_cause_service}</span></div>
            <div className="flex items-center gap-2"><span className="text-ink-400">Confidence</span><ConfidenceBar value={result.confidence} /></div>
          </div>
        )}
        {result.notes.length > 0 && <ul className="mt-2 space-y-0.5 text-xs text-amber-200/90">{result.notes.map((n, i) => <li key={i}>• {n}</li>)}</ul>}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Eye className="h-4 w-4 text-emerald-400" />Observed facts <Badge value="OBSERVED_FACT" label={`${facts.length}`} /></span>}
              subtitle="Extracted by code from tool output. Never written by a model.">
          <ul className="space-y-1.5">
            {facts.map((f, i) => (
              <li key={i} className="flex gap-2 text-[13px] leading-snug text-ink-200">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                <span className="flex-1">{f.statement}</span>
                <span className="shrink-0 font-mono text-[10px] text-ink-400">{f.source}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={<span className="flex items-center gap-2"><Brain className="h-4 w-4 text-violet-400" />AI inference <Badge value="AI_INFERENCE" label={`${inferences.length}`} /></span>}
              subtitle="Hypotheses ranked on the facts. Treat these as reasoning, not telemetry.">
          <div className="space-y-2">
            {result.hypotheses.slice(0, 4).map((h, i) => (
              <div key={h.key} className={`rounded-lg border p-2.5 ${i === 0 ? "border-violet-500/40 bg-violet-500/[0.07]" : "border-ink-700 bg-ink-850"}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium">{h.title}</span>
                  <span className="num text-xs text-ink-300">score {h.score.toFixed(2)}</span>
                </div>
                <div className="mt-1 text-xs text-ink-400">{h.supporting.join(" · ")}</div>
              </div>
            ))}
            {inferences.filter((f) => !f.data?.hypothesis).map((f, i) => (
              <p key={i} className="text-[13px] text-violet-200/90">• {f.statement} <span className="font-mono text-[10px] text-ink-400">{f.source}</span></p>
            ))}
            {result.hypotheses.length === 0 && <p className="text-sm text-ink-400">No hypothesis had supporting evidence.</p>}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Wrench className="h-4 w-4 text-sky-400" />Recommended remediation</span>}>
          {result.recommendation ? (
            <div className="space-y-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <code className="rounded bg-ink-800 px-2 py-1 font-mono text-sky-200">{result.recommendation.action}({Object.entries(result.recommendation.parameters).map(([k, v]) => `${k}=${v}`).join(", ")})</code>
                <span className="text-ink-400">on</span><span className="font-mono">{result.recommendation.target_service}</span>
                <Badge value={result.recommendation.risk} label={`${result.recommendation.risk} risk`} />
              </div>
              <p className="text-ink-200">{result.recommendation.rationale}</p>
              <p className="text-ink-400"><span className="text-ink-300">Expected impact:</span> {result.recommendation.expected_impact}</p>
            </div>
          ) : <p className="text-sm text-ink-400">No automated action recommended.</p>}
        </Card>
        <Card title={<span className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-amber-400" />Runbooks used</span>}>
          {result.runbooks.length ? (
            <ul className="space-y-2">
              {result.runbooks.map((r) => (
                <li key={r.slug}>
                  <Link to={`/runbooks/${r.slug}`} className="text-[13px] font-medium text-sky-300 hover:underline">{r.title}</Link>
                  {r.score !== undefined && <span className="num ml-2 text-[10px] text-ink-400">BM25 {r.score.toFixed(2)}</span>}
                  <p className="text-xs text-ink-400">{r.summary}</p>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-400">No runbook retrieved.</p>}
        </Card>
      </div>

      <Card title={`Tool calls (${result.tool_calls.length})`} subtitle="Every call the agent made, in order. All tools are read-only and allow-listed."
            actions={compact ? <button className="text-xs text-sky-300" onClick={() => setShowTools((s) => !s)}>{showTools ? "Hide" : "Show"}</button> : undefined} pad={false}>
        {showTools && (
          <div className="divide-y divide-ink-800">
            {result.tool_calls.map((c, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-1.5 text-xs">
                <span className="num w-5 text-ink-400">{i + 1}</span>
                {c.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> : <XCircle className="h-3.5 w-3.5 text-rose-400" />}
                <span className="font-mono text-sky-200">{c.tool}</span>
                <span className="truncate font-mono text-ink-400">{JSON.stringify(c.arguments)}</span>
                <span className="ml-auto shrink-0 text-ink-400">{c.error ?? c.summary}</span>
                <span className="num w-16 shrink-0 text-right text-ink-400">{c.duration_ms.toFixed(1)} ms</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
