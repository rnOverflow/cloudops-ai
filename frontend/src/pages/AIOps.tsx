import { Bot, Send, ShieldCheck, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, type Investigation } from "../api";
import { useAuth } from "../auth";
import { InvestigationView } from "../components/InvestigationView";
import { Badge, Button, Card, ErrorNote, PageHeader } from "../components/ui";
import { ago, pct } from "../format";
import { usePoll } from "../hooks";

const SUGGESTIONS = [
  "What is wrong with my infrastructure?",
  "Why is payment-service unhealthy?",
  "Why is api-gateway slow?",
  "Is the database saturated?",
  "Why is notification-service backing up?",
];

interface AIStatus { provider: string; llm_configured: boolean; mode: string; tools: { name: string; description: string }[]; guardrails: string[] }

export default function AIOps() {
  const { can } = useAuth();
  const { data: status } = usePoll<AIStatus>("/api/ai/status", 0);
  const { data: history, refresh } = usePoll<Investigation[]>("/api/ai/investigations?limit=15", 5000);
  const [question, setQuestion] = useState("");
  const [current, setCurrent] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(q: string, e?: FormEvent) {
    e?.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true); setError(null);
    try {
      const inv = await api<Investigation>("/api/ai/investigate", { method: "POST", json: { question: q } });
      setCurrent(inv); setQuestion(""); refresh();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function open(id: number) {
    setCurrent(await api<Investigation>(`/api/ai/investigations/${id}`));
  }

  return (
    <>
      <PageHeader title="AI Operations" subtitle="Ask about your infrastructure. The agent investigates through read-only tools and shows its work." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <Card>
            <form onSubmit={(e) => ask(question, e)} className="flex gap-2">
              <div className="relative flex-1">
                <Sparkles className="absolute left-3 top-2.5 h-4 w-4 text-violet-300" />
                <input value={question} onChange={(e) => setQuestion(e.target.value)} disabled={!can("ai:investigate")} maxLength={500}
                       placeholder={can("ai:investigate") ? "e.g. Why is payment-service unhealthy?" : "Your role cannot run investigations"}
                       className="w-full rounded-lg border border-ink-600 bg-ink-850 py-2 pl-9 pr-3 text-sm outline-none focus:border-violet-400" />
              </div>
              <Button type="submit" variant="primary" loading={busy} disabled={!can("ai:investigate")}><Send className="h-3.5 w-3.5" />Investigate</Button>
            </form>
            <div className="mt-3 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} disabled={busy || !can("ai:investigate")} onClick={() => ask(s)} className="rounded-full border border-ink-700 bg-ink-850 px-3 py-1 text-xs text-ink-300 hover:border-violet-400/50 hover:text-ink-100 disabled:opacity-50">{s}</button>
              ))}
            </div>
            <ErrorNote error={error} />
          </Card>
          {current?.result ? (
            <div>
              <div className="mb-3 flex items-center gap-2 text-sm text-ink-300"><Bot className="h-4 w-4 text-violet-300" /><span className="text-ink-100">“{current.question}”</span><span className="text-ink-400">· {current.duration_ms.toFixed(0)} ms</span></div>
              <InvestigationView result={current.result} />
            </div>
          ) : (
            <Card><p className="text-sm text-ink-400">Ask a question or pick a suggestion. Each answer separates <Badge value="OBSERVED_FACT" label="observed facts" /> from <Badge value="AI_INFERENCE" label="AI inference" />, cites the tools it used, and never invents telemetry.</p></Card>
          )}
        </div>
        <div className="space-y-5">
          <Card title="Agent configuration">
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-ink-400">Mode</span><span className="text-right">{status?.mode}</span></div>
              <div className="flex justify-between"><span className="text-ink-400">Provider</span><span className="font-mono text-xs">{status?.provider}</span></div>
            </div>
            <div className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-ink-400">Guardrails</div>
            <ul className="mt-1 space-y-1">{status?.guardrails.map((g) => <li key={g} className="flex gap-1.5 text-xs text-ink-300"><ShieldCheck className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />{g}</li>)}</ul>
            <div className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-ink-400">Tools ({status?.tools.length})</div>
            <div className="mt-1 flex flex-wrap gap-1">{status?.tools.map((t) => <span key={t.name} title={t.description} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-sky-200">{t.name}()</span>)}</div>
          </Card>
          <Card title="Recent investigations" pad={false}>
            <div className="divide-y divide-ink-800">
              {history?.map((h) => (
                <button key={h.id} onClick={() => open(h.id)} className="block w-full px-4 py-2 text-left hover:bg-ink-850">
                  <div className="truncate text-[13px]">{h.question}</div>
                  <div className="flex justify-between text-[11px] text-ink-400"><span className="truncate">{h.root_cause ?? "no root cause"} · {pct(h.confidence, 0)}</span><span className="shrink-0 pl-2">{h.actor} · {ago(h.created_at)}</span></div>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
