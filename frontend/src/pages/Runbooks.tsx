import { Search } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Markdown } from "../components/Markdown";
import { Badge, Card, Empty, PageHeader } from "../components/ui";
import { usePoll } from "../hooks";

interface RB { slug: string; title: string; severity: string; tags: string[]; summary: string; actions: string[]; score?: number }
interface RBFull extends RB { symptoms: string[]; content: string; updated_at: string }

export default function Runbooks() {
  const { slug } = useParams();
  const [q, setQ] = useState("");
  const { data: all } = usePoll<RB[]>("/api/runbooks", 0);
  const { data: hits } = usePoll<RB[]>(q.trim().length >= 2 ? `/api/runbooks/search?q=${encodeURIComponent(q.trim())}` : null, 0);
  const { data: doc } = usePoll<RBFull>(slug ? `/api/runbooks/${slug}` : null, 0);
  const list = q.trim().length >= 2 ? hits ?? [] : all ?? [];
  return (
    <>
      <PageHeader title="Runbooks" subtitle="Operational knowledge retrieved by the AI agent (BM25 over title, tags, symptoms and body)." />
      <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Card pad={false}>
          <div className="border-b border-ink-800 p-3">
            <div className="relative"><Search className="absolute left-2.5 top-2 h-4 w-4 text-ink-400" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search symptoms, e.g. pool exhausted" className="w-full rounded-lg border border-ink-600 bg-ink-850 py-1.5 pl-8 pr-2 text-sm outline-none focus:border-sky-500" /></div>
          </div>
          <div className="divide-y divide-ink-800">
            {list.map((r) => (
              <Link key={r.slug} to={`/runbooks/${r.slug}`} className={`block px-4 py-2.5 hover:bg-ink-850 ${slug === r.slug ? "bg-sky-500/10" : ""}`}>
                <div className="flex items-center justify-between gap-2"><span className="text-[13px] font-medium">{r.title}</span>{r.score !== undefined ? <span className="num text-[10px] text-ink-400">{r.score.toFixed(2)}</span> : <Badge value={r.severity} />}</div>
                <p className="mt-0.5 line-clamp-2 text-xs text-ink-400">{r.summary}</p>
              </Link>
            ))}
          </div>
        </Card>
        {doc ? (
          <Card title={doc.title} subtitle={`slug: ${doc.slug} · updated ${new Date(doc.updated_at).toLocaleDateString()}`} actions={<Badge value={doc.severity} />}>
            <div className="mb-4 flex flex-wrap gap-1.5">
              {doc.actions.map((a) => <span key={a} className="rounded bg-sky-500/10 px-2 py-0.5 font-mono text-[11px] text-sky-200 ring-1 ring-sky-500/25">{a}()</span>)}
              {doc.tags.map((t) => <span key={t} className="rounded bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">#{t}</span>)}
            </div>
            <div className="mb-4 rounded-lg bg-ink-850 p-3 text-xs text-ink-300"><span className="font-semibold text-ink-200">Symptoms:</span> {doc.symptoms.join(" · ")}</div>
            <Markdown source={doc.content} />
          </Card>
        ) : <Empty>Select a runbook.</Empty>}
      </div>
    </>
  );
}
