from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

SERVICE_METRICS = {
    "cpu_percent": "CPU utilisation percent (avg across pods)",
    "memory_percent": "Memory utilisation percent (avg across pods)",
    "memory_max_pod_percent": "Highest pod memory utilisation percent",
    "latency_p50_ms": "p50 request latency in ms",
    "latency_p95_ms": "p95 request latency in ms",
    "rps": "Requests per second",
    "error_rate": "Fraction of requests failing",
    "availability": "Fraction of requests succeeding",
    "restarts": "Total container restarts of live pods",
    "healthy_pods": "Ready pods",
    "replicas": "Desired replicas",
    "db_connections": "Database connections held",
    "network_rx_kbps": "Network receive KB/s",
    "network_tx_kbps": "Network transmit KB/s",
    "queue_depth": "Queue depth (workers)",
    "http_2xx_rps": "HTTP 2xx per second",
    "http_5xx_rps": "HTTP 5xx per second",
}

_gauges = {
    m: Gauge(f"cloudops_service_{m}", desc, ["service", "provider"], registry=REGISTRY)
    for m, desc in SERVICE_METRICS.items()
}
_requests_total = Gauge(
    "cloudops_service_requests_total",
    "Cumulative requests (provider counter)",
    ["service", "provider"],
    registry=REGISTRY,
)

INCIDENTS_OPENED = Counter(
    "cloudops_incidents_opened_total", "Incidents opened", ["service", "severity"], registry=REGISTRY
)
INCIDENTS_RESOLVED = Counter(
    "cloudops_incidents_resolved_total", "Incidents resolved", ["service"], registry=REGISTRY
)
ACTIVE_INCIDENTS = Gauge("cloudops_active_incidents", "Currently active incidents", registry=REGISTRY)
REMEDIATIONS = Counter(
    "cloudops_remediations_total", "Remediation outcomes", ["action", "result"], registry=REGISTRY
)
ALERT_SIGNALS = Counter(
    "cloudops_alert_signals_total", "Detection signals fired", ["service", "rule"], registry=REGISTRY
)
API_REQUESTS = Counter(
    "cloudops_api_requests_total",
    "Control-plane API requests",
    ["method", "route", "status"],
    registry=REGISTRY,
)
API_LATENCY = Histogram(
    "cloudops_api_request_seconds", "Control-plane API latency", ["method", "route"], registry=REGISTRY
)
CONTROL_LOOP_SECONDS = Histogram(
    "cloudops_control_loop_seconds", "Duration of one control-loop tick", registry=REGISTRY
)


def export_snapshot(provider: str, metrics: dict[str, dict[str, float]]) -> None:
    for svc, values in metrics.items():
        for m, g in _gauges.items():
            if m in values:
                g.labels(service=svc, provider=provider).set(values[m])
        if "request_count" in values:
            _requests_total.labels(service=svc, provider=provider).set(values["request_count"])
