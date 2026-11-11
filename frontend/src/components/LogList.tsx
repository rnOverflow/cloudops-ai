import clsx from "clsx";
import type { LogEntry } from "../api";
import { time } from "../format";
import { Empty } from "./ui";

export function LogList({ logs }: { logs: LogEntry[] }) {
  if (!logs.length) return <div className="p-4"><Empty>No log lines.</Empty></div>;
  return (
    <div className="max-h-[520px] overflow-y-auto font-mono text-[11.5px]">
      {logs.map((l) => (
        <div key={`${l.id}-${l.ts}`} className="flex gap-2 border-b border-ink-800/60 px-3 py-1 hover:bg-ink-850">
          <span className="shrink-0 text-ink-400">{time(l.ts)}</span>
          <span className={clsx("w-11 shrink-0 font-semibold", l.level === "ERROR" ? "text-rose-400" : l.level === "WARN" ? "text-amber-300" : "text-ink-400")}>{l.level}</span>
          <span className="w-36 shrink-0 truncate text-sky-300/80">{l.service}</span>
          <span className="flex-1 break-words text-ink-200">{l.message} <span className="text-ink-400">event={l.event}{l.pod ? ` pod=${l.pod}` : ""}</span></span>
        </div>
      ))}
    </div>
  );
}
