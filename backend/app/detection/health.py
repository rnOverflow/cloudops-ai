from __future__ import annotations

from typing import Any

THRESHOLDS = {
    "cpu_percent": 85.0,
    "memory_max_pod_percent": 85.0,
    "error_rate": 0.05,
    "latency_p95_ms": 500.0,
    "queue_depth": 500.0,
    "db_utilization": 0.85,
}


def evaluate_health(service: str, m: dict[str, float], kind: str = "http") -> dict[str, Any]:
    if not m:
        return {"name": service, "status": "UNKNOWN", "reasons": ["no telemetry yet"]}
    reasons: list[str] = []
    status = "HEALTHY"
    replicas = m.get("replicas", 0)
    healthy = m.get("healthy_pods", 0)
    if replicas and healthy == 0:
        return _pack(service, m, "UNHEALTHY", ["no ready pods"])
    if m.get("error_rate", 0) >= 0.2:
        status = "UNHEALTHY"
        reasons.append(f"error rate {m['error_rate'] * 100:.1f}%")
    elif m.get("error_rate", 0) > THRESHOLDS["error_rate"]:
        status = "DEGRADED"
        reasons.append(f"error rate {m['error_rate'] * 100:.1f}%")
    if kind == "database":
        util = m.get("db_utilization", 0)
        if util >= 0.95:
            status = "UNHEALTHY"
            reasons.append(f"connections {util * 100:.0f}% of max")
        elif util > THRESHOLDS["db_utilization"]:
            status = _worse(status, "DEGRADED")
            reasons.append(f"connections {util * 100:.0f}% of max")
    if m.get("cpu_percent", 0) > THRESHOLDS["cpu_percent"]:
        status = _worse(status, "DEGRADED")
        reasons.append(f"CPU {m['cpu_percent']:.0f}%")
    if m.get("memory_max_pod_percent", 0) > THRESHOLDS["memory_max_pod_percent"]:
        status = _worse(status, "DEGRADED")
        reasons.append(f"pod memory {m['memory_max_pod_percent']:.0f}%")
    if kind != "database" and m.get("latency_p95_ms", 0) > THRESHOLDS["latency_p95_ms"]:
        status = _worse(status, "DEGRADED")
        reasons.append(f"p95 {m['latency_p95_ms']:.0f} ms")
    if replicas and healthy < replicas:
        status = _worse(status, "DEGRADED")
        reasons.append(f"{healthy:.0f}/{replicas:.0f} pods ready")
    if m.get("queue_depth", 0) > THRESHOLDS["queue_depth"]:
        status = _worse(status, "DEGRADED")
        reasons.append(f"queue depth {m['queue_depth']:.0f}")
    return _pack(service, m, status, reasons)


def _worse(a: str, b: str) -> str:
    order = {"HEALTHY": 0, "DEGRADED": 1, "UNHEALTHY": 2}
    return a if order[a] >= order[b] else b


def _pack(service: str, m: dict[str, float], status: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "name": service,
        "status": status,
        "reasons": reasons,
        "healthy_pods": m.get("healthy_pods"),
        "replicas": m.get("replicas"),
        "error_rate": m.get("error_rate"),
        "latency_p95_ms": m.get("latency_p95_ms"),
        "cpu_percent": m.get("cpu_percent"),
        "memory_percent": m.get("memory_percent"),
        "availability": m.get("availability"),
        "rps": m.get("rps"),
    }
