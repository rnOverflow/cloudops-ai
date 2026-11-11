from datetime import UTC, datetime

import pytest
from app.cloud.local.simulation import FAULTS, Simulation

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def run(sim: Simulation, n: int):
    out = None
    for _ in range(n):
        out, _ = sim.step(NOW)
    return out


def test_baseline_is_healthy():
    sim = Simulation(seed=1)
    m = run(sim, 20)
    for name, v in m.items():
        assert v["error_rate"] < 0.02, name
        assert v["cpu_percent"] < 70, name
        if name != "database":
            assert v["latency_p95_ms"] < 500, name
        assert v["healthy_pods"] == v["replicas"]


@pytest.mark.parametrize(
    ("fault", "service", "metric", "predicate"),
    [
        ("high_cpu", "payment-service", "cpu_percent", lambda v: v > 85),
        ("memory_leak", "payment-service", "memory_max_pod_percent", lambda v: v > 85),
        ("db_saturation", "database", "db_utilization", lambda v: v > 0.9),
        ("pod_crash", "payment-service", "healthy_pods", lambda v: v < 3),
        ("latency_spike", "payment-service", "latency_p95_ms", lambda v: v > 1000),
        ("deployment_failure", "payment-service", "error_rate", lambda v: v > 0.2),
        ("traffic_spike", "api-gateway", "cpu_percent", lambda v: v > 90),
        ("outage", "payment-service", "healthy_pods", lambda v: v == 0),
        ("queue_backlog", "notification-service", "queue_depth", lambda v: v > 500),
    ],
)
def test_faults_change_telemetry(fault, service, metric, predicate):
    sim = Simulation(seed=2)
    run(sim, 10)
    sim.inject(fault)
    m = run(sim, 12)
    assert predicate(m[service][metric]), (fault, m[service][metric])


def test_fault_catalog_complete():
    assert set(FAULTS) >= {
        "high_cpu",
        "memory_leak",
        "db_saturation",
        "pod_crash",
        "latency_spike",
        "deployment_failure",
        "traffic_spike",
        "outage",
    }


def test_restart_pod_replaces_pod_and_clears_crash_loop():
    sim = Simulation(seed=3)
    run(sim, 5)
    info = sim.inject("pod_crash")
    run(sim, 6)
    sim.restart_pod("payment-service", info["pod"])
    m = run(sim, 3)
    assert info["pod"] not in [p["name"] for p in sim.pod_view("payment-service")]
    assert m["payment-service"]["healthy_pods"] == 3


def test_wrong_remediation_does_not_fix_runaway_cpu():
    """Scaling out does not fix runaway threads: CPU per pod stays high (verification must catch this)."""
    sim = Simulation(seed=4)
    run(sim, 5)
    sim.inject("high_cpu")
    run(sim, 5)
    sim.scale("payment-service", 6)
    m = run(sim, 4)
    assert m["payment-service"]["cpu_percent"] > 85


def test_rollback_restores_previous_version():
    sim = Simulation(seed=5)
    run(sim, 3)
    sim.deploy("payment-service", "v2.5.0", defective=True)
    run(sim, 5)
    res = sim.rollback("payment-service")
    m = run(sim, 3)
    assert res == {"from": "v2.5.0", "to": "v2.4.1"}
    assert m["payment-service"]["error_rate"] < 0.05


def test_unknown_inputs_rejected():
    sim = Simulation(seed=6)
    with pytest.raises(ValueError):
        sim.inject("rm -rf /")
    with pytest.raises(KeyError):
        sim.restart_pod("payment-service", "nope")
    with pytest.raises(KeyError):
        sim.clear_failed_job("notification-service", "job-x")
