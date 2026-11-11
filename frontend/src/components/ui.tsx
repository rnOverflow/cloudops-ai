import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Card({ title, subtitle, actions, children, className, pad = true }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx("rounded-xl border border-ink-700/70 bg-ink-900/80 shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset]", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-ink-700/60 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-[13px] font-semibold tracking-wide text-ink-100">{title}</h2>
            {subtitle && <p className="mt-0.5 truncate text-xs text-ink-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx(pad && "p-4")}>{children}</div>
    </section>
  );
}

const tone: Record<string, string> = {
  CRITICAL: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  HIGH: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  MEDIUM: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  LOW: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  HEALTHY: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  DEGRADED: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  UNHEALTHY: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  UNKNOWN: "bg-ink-700 text-ink-300 ring-ink-600",
  OPEN: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  INVESTIGATING: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  MITIGATING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  RESOLVED: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  CLOSED: "bg-ink-700 text-ink-300 ring-ink-600",
  PROPOSED: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  PENDING_APPROVAL: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  APPROVED: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  EXECUTING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  VERIFYING: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  SUCCEEDED: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  SUCCESS: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  FAILED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  REJECTED: "bg-ink-700 text-ink-300 ring-ink-600",
  DENIED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  BLOCKED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  SUPERSEDED: "bg-ink-700 text-ink-300 ring-ink-600",
  OK: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  AT_RISK: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  BREACHED: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  ERROR: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  WARN: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  INFO: "bg-ink-700/80 text-ink-300 ring-ink-600",
  NONE: "bg-ink-700 text-ink-300 ring-ink-600",
  OBSERVED_FACT: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  AI_INFERENCE: "bg-violet-500/10 text-violet-300 ring-violet-500/30",
};

export function Badge({ value, label, className }: { value: string; label?: string; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-semibold tracking-wide ring-1 ring-inset", tone[value] ?? "bg-ink-700 text-ink-200 ring-ink-600", className)}>
      {label ?? value.replace(/_/g, " ")}
    </span>
  );
}

export function Dot({ status }: { status: string }) {
  const c = status === "HEALTHY" ? "bg-emerald-400" : status === "DEGRADED" ? "bg-amber-400" : status === "UNHEALTHY" ? "bg-rose-500" : "bg-ink-400";
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {status !== "HEALTHY" && <span className={clsx("absolute inset-0 animate-ping rounded-full opacity-60", c)} />}
      <span className={clsx("relative inline-flex h-2.5 w-2.5 rounded-full", c)} />
    </span>
  );
}

export function Stat({ label, value, hint, accent, icon }: { label: string; value: ReactNode; hint?: ReactNode; accent?: "good" | "warn" | "bad"; icon?: ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-900/80 p-4">
      <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-[0.08em] text-ink-400">
        {label}
        {icon && <span className="text-ink-400">{icon}</span>}
      </div>
      <div className={clsx("num mt-2 text-2xl font-semibold", accent === "good" && "text-emerald-300", accent === "warn" && "text-amber-300", accent === "bad" && "text-rose-300")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-400">{hint}</div>}
    </div>
  );
}

export function Button({ variant = "secondary", loading, className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" | "success"; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-sky-500 text-white hover:bg-sky-400",
        variant === "success" && "bg-emerald-600 text-white hover:bg-emerald-500",
        variant === "danger" && "bg-rose-600/90 text-white hover:bg-rose-500",
        variant === "secondary" && "border border-ink-600 bg-ink-800 text-ink-100 hover:bg-ink-700",
        variant === "ghost" && "text-ink-300 hover:bg-ink-800 hover:text-ink-100",
        className,
      )}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="flex min-h-24 items-center justify-center rounded-lg border border-dashed border-ink-700 p-6 text-center text-sm text-ink-400">{children}</div>;
}

export function Spinner() {
  return <div className="flex min-h-24 items-center justify-center text-ink-400"><Loader2 className="h-5 w-5 animate-spin" /></div>;
}

export function SimTag({ simulated }: { simulated?: boolean }) {
  if (!simulated) return null;
  return <span title="Data produced by the LocalCloudProvider simulation" className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">Simulated</span>;
}

export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-ink-700/70 text-[11px] uppercase tracking-[0.08em] text-ink-400">
            {head.map((h, i) => <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">{children}</tbody>
      </table>
    </div>
  );
}

export function Meter({ value, warn = 0.7, bad = 0.85 }: { value: number; warn?: number; bad?: number }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-800">
      <div className={clsx("h-full rounded-full transition-all", v >= bad ? "bg-rose-500" : v >= warn ? "bg-amber-400" : "bg-emerald-400")} style={{ width: `${v * 100}%` }} />
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink-100">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
