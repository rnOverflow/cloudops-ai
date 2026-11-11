import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface SeriesPoint { t: string; v: number | null }

const COLORS = ["#38bdf8", "#a78bfa", "#34d399", "#fbbf24", "#f472b6"];

export function TimeChart({ points, height = 160, threshold, unit = "", color = COLORS[0], format }: {
  points: SeriesPoint[]; height?: number; threshold?: number; unit?: string; color?: string; format?: (v: number) => string;
}) {
  const fmt = format ?? ((v: number) => `${Number.isInteger(v) ? v : v.toFixed(2)}${unit}`);
  const id = `g${color.slice(1)}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points} margin={{ top: 6, right: 6, left: -12, bottom: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1c2a3f" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="t" tick={{ fill: "#6b7d99", fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={40}
               tickFormatter={(t) => new Date(t).toLocaleTimeString(undefined, { hour12: false, minute: "2-digit", second: "2-digit" })} />
        <YAxis tick={{ fill: "#6b7d99", fontSize: 10 }} tickLine={false} axisLine={false} width={52} tickFormatter={(v) => fmt(v)} />
        <Tooltip contentStyle={{ background: "#0b111b", border: "1px solid #2a3b55", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#93a3bb" }}
                 labelFormatter={(t) => new Date(t as string).toLocaleTimeString(undefined, { hour12: false })} formatter={(v) => [fmt(Number(v)), ""]} />
        {threshold !== undefined && <ReferenceLine y={threshold} stroke="#f43f5e" strokeDasharray="4 4" label={{ value: "threshold", fill: "#f43f5e", fontSize: 10, position: "insideTopRight" }} />}
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.75} fill={`url(#${id})`} isAnimationActive={false} connectNulls />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function Sparkline({ values, color = COLORS[0], height = 28 }: { values: number[]; color?: string; height?: number }) {
  if (values.length < 2) return <div style={{ height }} />;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const w = 100;
  const d = values.map((v, i) => `${(i / (values.length - 1)) * w},${height - ((v - min) / span) * (height - 4) - 2}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }}>
      <polyline points={d} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export const CHART_COLORS = COLORS;
