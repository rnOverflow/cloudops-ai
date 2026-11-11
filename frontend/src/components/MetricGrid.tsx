import { usePoll } from "../hooks";
import { CHART_COLORS, TimeChart } from "./Chart";
import { Card } from "./ui";

const HTTP_METRICS = [
  { key: "cpu_percent", label: "CPU utilisation", unit: "%", threshold: 85 },
  { key: "memory_max_pod_percent", label: "Memory (max pod)", unit: "%", threshold: 85 },
  { key: "latency_p95_ms", label: "Latency p95", unit: " ms", threshold: 500 },
  { key: "rps", label: "Throughput", unit: " rps" },
  { key: "error_rate", label: "Error rate", unit: "", threshold: 0.05, pct: true },
  { key: "http_5xx_rps", label: "HTTP 5xx / s", unit: "" },
  { key: "healthy_pods", label: "Ready pods", unit: "" },
  { key: "restarts", label: "Container restarts", unit: "" },
  { key: "db_connections", label: "DB connections held", unit: "" },
  { key: "network_rx_kbps", label: "Network RX", unit: " KB/s" },
  { key: "availability", label: "Availability", unit: "", pct: true },
  { key: "queue_depth", label: "Queue depth", unit: "", threshold: 500 },
];
const DB_METRICS = [
  { key: "db_utilization", label: "Connection utilisation", unit: "", threshold: 0.85, pct: true },
  { key: "db_connections", label: "Active connections", unit: "" },
  { key: "cpu_percent", label: "CPU", unit: "%" },
  { key: "latency_p95_ms", label: "Query p95", unit: " ms" },
  { key: "rps", label: "Queries / s", unit: "" },
  { key: "error_rate", label: "Rejected connections", unit: "", pct: true },
];

export function MetricGrid({ service, kind = "http", window = 150 }: { service: string; kind?: string; window?: number }) {
  const metrics = kind === "database" ? DB_METRICS : HTTP_METRICS.filter((m) => kind === "worker" || m.key !== "queue_depth");
  const q = metrics.map((m) => `metric=${m.key}`).join("&");
  const { data } = usePoll<{ timestamps: string[]; series: Record<string, (number | null)[]> }>(`/api/metrics/${service}?${q}&window=${window}`, 2500);
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {metrics.map((m, i) => {
        const vals = data?.series[m.key] ?? [];
        const last = vals[vals.length - 1];
        const fmt = m.pct ? (v: number) => `${(v * 100).toFixed(2)}%` : undefined;
        return (
          <Card key={m.key} title={m.label} actions={<span className="num text-sm text-ink-100">{last == null ? "—" : fmt ? fmt(last) : `${last.toFixed(m.key.includes("rate") ? 3 : 1)}${m.unit}`}</span>}>
            <TimeChart points={(data?.timestamps ?? []).map((t, j) => ({ t, v: vals[j] ?? null }))} threshold={m.threshold} unit={m.unit.trim() === "%" ? "%" : ""} format={fmt} color={CHART_COLORS[i % CHART_COLORS.length]} height={140} />
          </Card>
        );
      })}
    </div>
  );
}
