export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
export const num = (v: number | null | undefined, digits = 0) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }));
export const ms = (v: number | null | undefined) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${v.toFixed(0)} ms`);

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 5) return "just now";
  return `${duration(s)} ago`;
}

export const time = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour12: false }) : "—");
export const datetime = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { hour12: false }) : "—");

export function humanize(s: string): string {
  return s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}
