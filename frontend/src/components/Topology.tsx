import { useNavigate } from "react-router-dom";
import { usePoll } from "../hooks";

interface Topo { nodes: { id: string; kind: string; tier: string; status: string }[]; edges: { from: string; to: string; type: string }[] }

const POS: Record<string, [number, number]> = {
  "api-gateway": [80, 125], "user-service": [300, 55], "payment-service": [300, 195], "notification-service": [520, 235], database: [520, 100],
};
const COLOR: Record<string, string> = { HEALTHY: "#34d399", DEGRADED: "#fbbf24", UNHEALTHY: "#f43f5e", UNKNOWN: "#6b7d99" };

export function Topology({ height = 260 }: { height?: number }) {
  const { data } = usePoll<Topo>("/api/services/topology", 2500);
  const nav = useNavigate();
  if (!data) return <div style={{ height }} />;
  return (
    <svg viewBox="0 0 620 280" className="w-full" style={{ height }} role="img" aria-label="Service dependency graph">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#2a3b55" /></marker>
      </defs>
      {data.edges.map((e) => {
        const [x1, y1] = POS[e.from] ?? [0, 0];
        const [x2, y2] = POS[e.to] ?? [0, 0];
        const bad = data.nodes.find((n) => n.id === e.to)?.status !== "HEALTHY";
        return (
          <g key={`${e.from}-${e.to}`}>
            <line x1={x1 + 58} y1={y1} x2={x2 - 62} y2={y2} stroke={bad ? "#f59e0b" : "#2a3b55"} strokeWidth={1.5} strokeDasharray={e.type === "async" ? "5 4" : undefined} markerEnd="url(#arrow)" />
            <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 5} fill="#6b7d99" fontSize="9" textAnchor="middle">{e.type}</text>
          </g>
        );
      })}
      {data.nodes.map((n) => {
        const [x, y] = POS[n.id] ?? [0, 0];
        return (
          <g key={n.id} transform={`translate(${x - 60},${y - 20})`} className="cursor-pointer" onClick={() => nav(`/services/${n.id}`)}>
            <rect width="120" height="40" rx="9" fill="#0f1724" stroke={COLOR[n.status]} strokeWidth={n.status === "HEALTHY" ? 1 : 2} />
            <circle cx="14" cy="20" r="4" fill={COLOR[n.status]}>{n.status !== "HEALTHY" && <animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite" />}</circle>
            <text x="26" y="18" fill="#e4eaf3" fontSize="11" fontWeight="600">{n.id.replace("-service", "")}</text>
            <text x="26" y="31" fill="#6b7d99" fontSize="9">{n.kind} · {n.tier}</text>
          </g>
        );
      })}
    </svg>
  );
}
