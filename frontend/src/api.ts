export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type Health = "HEALTHY" | "DEGRADED" | "UNHEALTHY" | "UNKNOWN";

export interface User { username: string; full_name?: string; role: string; permissions: string[] }
export interface ServiceHealth {
  name: string; status: Health; reasons: string[]; healthy_pods?: number; replicas?: number; error_rate?: number;
  latency_p95_ms?: number; cpu_percent?: number; memory_percent?: number; availability?: number; rps?: number;
}
export interface ServiceInfo {
  name: string; kind: string; tier: string; owner_team: string; description: string; version: string;
  dependencies: { name: string; type: string }[]; health: ServiceHealth;
}
export interface Incident {
  id: number; incident_id: string; title: string; service: string; severity: Severity; status: string; detected_at: string;
  updated_at: string; resolved_at?: string | null; closed_at?: string | null; impact_started_at?: string | null;
  probable_root_cause?: string | null; root_cause_service?: string | null; confidence?: number | null;
  recommended_action?: Record<string, unknown> | null; risk?: string | null; remediation_status: string;
  correlated_services: string[]; resolution_note?: string | null; signal_count: number;
  time_to_resolve_seconds?: number; time_to_detect_seconds?: number;
}
export interface Signal { rule: string; title: string; service: string; metric: string; value: number; threshold: number; severity: string; kind: string; first_breach_ts: string; detail?: Record<string, unknown> }
export interface IncidentEvent { id: number; ts: string; type: string; actor: string; message: string; data: Record<string, unknown> }
export interface Check { check: string; passed: boolean; before?: number | null; after?: unknown; threshold?: number; metric?: string }
export interface Remediation {
  id: number; incident_id: number | null; action: string; target_service: string; parameters: Record<string, unknown>; risk: string;
  status: string; rationale: string; expected_impact: string; ai_confidence: number | null; autonomous: boolean; proposed_by: string;
  proposed_at: string; decided_by?: string | null; decided_at?: string | null; decision_reason?: string | null; executed_at?: string | null;
  verified_at?: string | null; before_state: Record<string, any>; after_state: Record<string, any>;
  verification: { checks?: Check[]; result?: string; risk_reasons?: string[] }; execution_output: Record<string, unknown>;
}
export interface Finding { kind: "OBSERVED_FACT" | "AI_INFERENCE"; statement: string; source: string; data?: Record<string, unknown> }
export interface ToolCall { tool: string; arguments: Record<string, unknown>; ok: boolean; duration_ms: number; summary: string; error?: string | null }
export interface InvestigationResult {
  service: string | null; question: string; summary: string; status: string; findings: Finding[];
  hypotheses: { key: string; title: string; score: number; confidence: number; supporting: string[]; root_cause_service: string }[];
  root_cause: string | null; root_cause_service: string | null; confidence: number;
  recommendation: { action: string; target_service: string; parameters: Record<string, unknown>; rationale: string; expected_impact: string; risk: string } | null;
  runbooks: { slug: string; title: string; summary: string; score?: number; actions: string[] }[]; tool_calls: ToolCall[]; provider: string; llm_used: boolean; notes: string[];
}
export interface Investigation { id: number; incident_id: number | null; question: string; service: string | null; actor: string; provider: string; root_cause: string | null; confidence: number | null; duration_ms: number; created_at: string; summary?: string; result?: InvestigationResult }
export interface IncidentDetail extends Incident { signals: Signal[]; metrics: Record<string, number>; logs: LogEntry[]; events: IncidentEvent[]; remediations: Remediation[]; investigations: Investigation[] }
export interface LogEntry { id: number; ts: string; level: string; service: string; event: string; message: string; pod?: string | null; version?: string; job_id?: string }
export interface Pod { name: string; service: string; node: string; version: string; phase: string; ready: boolean; restarts: number; recent_restarts: number; cpu_percent: number; memory_mb: number; memory_limit_mb: number; memory_percent: number; age_seconds: number; last_termination_reason?: string | null }
export interface SLO { id: number; service: string; name: string; sli_type: string; target: number; threshold_ms: number | null; window_days: number; attainment: number; error_budget_remaining: number; error_budget_consumed: number; total_events: number; bad_events: number; burn_rate_5m: number; burn_rate_1h: number; status: string }
export interface AuditEntry { id: number; timestamp: string; actor: string; role: string; action: string; target: string; reason: string; before_state: unknown; after_state: unknown; ai_confidence: number | null; result: string; source_ip: string | null; hash: string; prev_hash: string }

const TOKEN_KEY = "cloudops.token";
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = init.body;
  if (init.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(init.json); }
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) }, body });
  if (res.status === 401 && onUnauthorized) onUnauthorized();
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? data.detail.map((d: any) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ") : msg;
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}
