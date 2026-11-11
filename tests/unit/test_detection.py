from datetime import UTC, datetime, timedelta

from app.detection.anomaly import robust_zscore
from app.detection.engine import DetectionEngine
from app.detection.health import evaluate_health
from app.observability.store import TelemetryStore

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def feed(store, engine, values, start_tick=0):
    sigs = []
    for i, v in enumerate(values):
        t = start_tick + i + 1
        store.ingest(
            T0 + timedelta(seconds=2 * t),
            t,
            {
                "svc": {
                    "cpu_percent": v,
                    "error_rate": 0.001,
                    "latency_p95_ms": 100,
                    "rps": 100,
                    "healthy_pods": 3,
                    "replicas": 3,
                    "memory_max_pod_percent": 40,
                    "restarts": 0,
                }
            },
            [],
        )
        sigs = engine.evaluate(T0 + timedelta(seconds=2 * t), t)
    return sigs


def test_rule_requires_consecutive_breaches():
    store = TelemetryStore()
    eng = DetectionEngine(store, {"svc": "http"})
    assert not [s for s in feed(store, eng, [90, 90]) if s.rule == "HIGH_CPU"]
    sigs = feed(store, eng, [90], start_tick=2)
    cpu = [s for s in sigs if s.rule == "HIGH_CPU"]
    assert cpu and cpu[0].severity == "MEDIUM"
    assert cpu[0].first_breach_ts == T0 + timedelta(seconds=2)


def test_flapping_resets_counter():
    store = TelemetryStore()
    eng = DetectionEngine(store, {"svc": "http"})
    assert not [s for s in feed(store, eng, [90, 90, 50, 90, 90]) if s.rule == "HIGH_CPU"]


def test_robust_zscore():
    hist = [100 + (i % 5) for i in range(50)]
    assert abs(robust_zscore(hist, 102)) < 2
    assert robust_zscore(hist, 400) > 50
    assert robust_zscore(hist[:5], 400) == 0.0  # not enough history


def test_health_evaluation():
    assert evaluate_health("x", {"healthy_pods": 0, "replicas": 3})["status"] == "UNHEALTHY"
    assert (
        evaluate_health("x", {"healthy_pods": 3, "replicas": 3, "error_rate": 0.07})["status"] == "DEGRADED"
    )
    assert (
        evaluate_health(
            "x",
            {"healthy_pods": 3, "replicas": 3, "error_rate": 0.001, "cpu_percent": 30, "latency_p95_ms": 50},
        )["status"]
        == "HEALTHY"
    )
    assert evaluate_health("x", {})["status"] == "UNKNOWN"
