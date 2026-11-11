import clsx from "clsx";
import {
  Activity, BookOpen, Bot, Boxes, FlaskConical, Gauge, LayoutDashboard, LogOut, Network, ScrollText, Server, Settings, ShieldCheck, Siren, TerminalSquare,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { usePoll } from "../hooks";

const NAV = [
  { group: "Operate", items: [
    { to: "/", label: "Overview", icon: LayoutDashboard },
    { to: "/incidents", label: "Incidents", icon: Siren, badge: true },
    { to: "/ai", label: "AI Operations", icon: Bot },
    { to: "/simulator", label: "Failure Simulator", icon: FlaskConical },
  ] },
  { group: "Observe", items: [
    { to: "/services", label: "Services", icon: Server },
    { to: "/metrics", label: "Metrics", icon: Activity },
    { to: "/logs", label: "Logs", icon: TerminalSquare },
    { to: "/slo", label: "SLO / Reliability", icon: Gauge },
  ] },
  { group: "Infrastructure", items: [
    { to: "/infrastructure", label: "Infrastructure", icon: Network },
    { to: "/kubernetes", label: "Kubernetes", icon: Boxes },
  ] },
  { group: "Govern", items: [
    { to: "/runbooks", label: "Runbooks", icon: BookOpen },
    { to: "/audit", label: "Audit Logs", icon: ScrollText },
    { to: "/settings", label: "Settings", icon: Settings },
  ] },
];

interface Status { provider: string; simulated: boolean; tick: number; active_incidents: number; pending_approvals: number; autonomous_mode: boolean; llm_configured: boolean; control_loop_error: string | null; services_healthy: number; services_total: number }

export function Layout() {
  const { user, logout } = useAuth();
  const { data: st } = usePoll<Status>("/api/system/status", 2500);
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-ink-800 bg-ink-900/70 lg:flex">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-sky-400 to-indigo-500 shadow-lg shadow-sky-500/20">
            <Activity className="h-4.5 w-4.5 text-white" strokeWidth={2.5} />
          </div>
          <div>
            <div className="text-sm font-semibold leading-tight">CloudOps AI</div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-ink-400">Reliability Platform</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          {NAV.map((g) => (
            <div key={g.group} className="mt-4">
              <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400/80">{g.group}</div>
              {g.items.map(({ to, label, icon: Icon, badge }) => (
                <NavLink key={to} to={to} end={to === "/"}
                  className={({ isActive }) => clsx("group flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition",
                    isActive ? "bg-sky-500/10 text-sky-200 ring-1 ring-inset ring-sky-500/25" : "text-ink-300 hover:bg-ink-800 hover:text-ink-100")}>
                  <Icon className="h-4 w-4 opacity-80" />
                  <span className="flex-1">{label}</span>
                  {badge && st && st.active_incidents > 0 && <span className="num rounded-full bg-rose-500 px-1.5 text-[10px] font-bold text-white">{st.active_incidents}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-ink-800 p-3">
          <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5">
            <div className="grid h-8 w-8 place-items-center rounded-full bg-ink-700 text-xs font-semibold uppercase">{user?.username.slice(0, 2)}</div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium">{user?.username}</div>
              <div className="flex items-center gap-1 text-[11px] text-ink-400"><ShieldCheck className="h-3 w-3" />{user?.role}</div>
            </div>
            <button onClick={logout} title="Sign out" className="rounded-md p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100"><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-ink-800 bg-ink-900/40 px-5 text-xs backdrop-blur">
          <span className="flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-ink-300">
            <span className={clsx("h-1.5 w-1.5 rounded-full", st?.control_loop_error ? "bg-rose-500" : "bg-emerald-400 animate-pulse")} />
            Control loop {st?.control_loop_error ? "error" : "running"}
            <span className="num text-ink-400">· sample {st?.tick ?? "—"}</span>
          </span>
          <span className="rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-ink-300">
            Provider: <span className="font-semibold text-ink-100">{st?.provider ?? "—"}</span>
          </span>
          {st?.simulated && <span className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 font-semibold uppercase tracking-wider text-amber-300">Local simulation</span>}
          <span className={clsx("rounded-md border px-2 py-1", st?.autonomous_mode ? "border-violet-500/40 bg-violet-500/10 text-violet-300" : "border-ink-700 bg-ink-850 text-ink-300")}>
            Autopilot: {st?.autonomous_mode ? "LOW-risk auto" : "approval required"}
          </span>
          <span className="rounded-md border border-ink-700 bg-ink-850 px-2 py-1 text-ink-300">AI: {st?.llm_configured ? "LLM-assisted" : "local analyzer"}</span>
          <div className="flex-1" />
          {st && st.pending_approvals > 0 && (
            <NavLink to="/incidents" className="rounded-md bg-amber-500/15 px-2 py-1 font-semibold text-amber-300 ring-1 ring-amber-500/30">
              {st.pending_approvals} awaiting approval
            </NavLink>
          )}
          <span className="num text-ink-400">{st ? `${st.services_healthy}/${st.services_total} healthy` : ""}</span>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1500px] px-5 py-6 lg:px-8"><Outlet /></div>
        </main>
      </div>
    </div>
  );
}
