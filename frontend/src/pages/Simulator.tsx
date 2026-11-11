import { SimulatorPanel } from "../components/SimulatorPanel";
import { Card, PageHeader } from "../components/ui";

export default function Simulator() {
  return (
    <>
      <PageHeader title="Failure Simulator" subtitle="Chaos engineering against the local cloud. Every injection is RBAC-checked and audited." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <SimulatorPanel />
        <Card title="What happens next">
          <ol className="list-decimal space-y-2 pl-4 text-sm text-ink-300">
            <li>The simulation state changes (threads spin, memory leaks, connections leak, a bad version rolls out…).</li>
            <li>Metrics and structured logs are <em>computed</em> from that state every sample.</li>
            <li>The detection engine evaluates threshold rules (with <em>for</em>-durations) and robust anomaly scores.</li>
            <li>Signals are correlated along the dependency graph into a single incident.</li>
            <li>The AI agent investigates with read-only tools, retrieves runbooks and recommends an allow-listed action.</li>
            <li>The policy engine assigns risk. LOW risk may run on autopilot; everything else waits for approval.</li>
            <li>After execution, verification re-reads the infrastructure. Only recovered telemetry resolves the incident.</li>
          </ol>
        </Card>
      </div>
    </>
  );
}
