"""Implementation of the agent's read-only ToolBackend on top of the control plane."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .detection.health import evaluate_health
from .models import Deployment, Incident, SLODefinition
from .slo.service import slo_status

if TYPE_CHECKING:
    from .control_plane import ControlPlane

LOG_WINDOW_SAMPLES = 30
METRIC_KEYS = [
    "cpu_percent",
    "memory_percent",
    "memory_max_pod_percent",
    "latency_p50_ms",
    "latency_p95_ms",
    "rps",
    "error_rate",
    "restarts",
    "healthy_pods",
    "replicas",
    "db_connections",
    "queue_depth",
    "db_utilization",
]


class PlatformToolBackend:
    def __init__(self, cp: ControlPlane, db: Session):
        self.cp = cp
        self.db = db
        self.label = "SIMULATED (LocalCloudProvider)" if cp.provider.is_simulated else cp.provider.name

    def get_service_health(self, service: str | None = None) -> dict[str, Any]:
        names = [service] if service else list(self.cp.kinds)
        return {
            "data_source": self.label,
            "services": [
                evaluate_health(n, self.cp.store.latest(n), self.cp.kinds.get(n, "http")) for n in names
            ],
        }

    def get_metrics(self, service: str, window: int = 30) -> dict[str, Any]:
        pts = self.cp.store.points(service, window)
        series = {k: [round(p.values.get(k, 0.0), 4) for p in pts] for k in METRIC_KEYS}
        latest = self.cp.store.latest(service)
        baseline = {
            k: self.cp.store.baseline(service, k)
            for k in ("cpu_percent", "latency_p95_ms", "error_rate", "rps", "memory_percent")
        }
        return {
            "data_source": self.label,
            "service": service,
            "samples": len(pts),
            "sample_interval_s": self.cp.settings.tick_seconds,
            "series": series,
            "latest": {k: latest.get(k) for k in METRIC_KEYS},
            "baseline": baseline,
        }

    def query_logs(self, service: str, level: str | None = None, limit: int = 200) -> dict[str, Any]:
        # Only recent lines (last ~60 samples): stale errors from an already-fixed problem must not drive analysis.
        min_tick = self.cp.store.tick - LOG_WINDOW_SAMPLES
        logs = [
            e
            for e in self.cp.store.query_logs(service=service, level=level, limit=limit)
            if e.get("tick", min_tick) >= min_tick
        ]
        return {
            "data_source": self.label,
            "service": service,
            "window_samples": LOG_WINDOW_SAMPLES,
            "count": len(logs),
            "logs": logs,
        }

    def get_recent_deployments(self, service: str | None = None) -> dict[str, Any]:
        q = select(Deployment).order_by(Deployment.id.desc()).limit(20)
        if service:
            q = q.where(Deployment.service == service)
        now = self.cp.clock.now()
        rows = self.db.execute(q).scalars().all()
        return {
            "deployments": [
                {
                    "service": d.service,
                    "version": d.version,
                    "previous_version": d.previous_version,
                    "kind": d.kind,
                    "status": d.status,
                    "actor": d.actor,
                    "deployed_at": d.created_at.isoformat(),
                    "age_seconds": (now - _aware(d.created_at)).total_seconds(),
                }
                for d in rows
            ]
        }

    def get_kubernetes_status(self) -> dict[str, Any]:
        return self.cp.provider.cluster_status()

    def get_pod_status(self, service: str) -> dict[str, Any]:
        return {"data_source": self.label, "service": service, "pods": self.cp.provider.pods(service)}

    def get_database_status(self) -> dict[str, Any]:
        return {"data_source": self.label, **self.cp.provider.database_status()}

    def get_recent_incidents(self, service: str | None = None) -> dict[str, Any]:
        q = select(Incident).order_by(Incident.id.desc()).limit(10)
        if service:
            q = q.where(Incident.service == service)
        return {
            "incidents": [
                {
                    "key": i.incident_key,
                    "service": i.service,
                    "title": i.title,
                    "severity": i.severity,
                    "status": i.status,
                    "root_cause": i.probable_root_cause,
                    "detected_at": i.detected_at.isoformat(),
                }
                for i in self.db.execute(q).scalars()
            ]
        }

    def get_service_dependencies(self, service: str) -> dict[str, Any]:
        deps = self.cp.deps.get(service, [])
        dependents = [s for s, ds in self.cp.deps.items() if any(d["name"] == service for d in ds)]
        health = []
        for d in deps:
            h = evaluate_health(
                d["name"], self.cp.store.latest(d["name"]), self.cp.kinds.get(d["name"], "http")
            )
            health.append(
                {
                    "name": d["name"],
                    "type": d["type"],
                    "status": h["status"],
                    "error_rate": h.get("error_rate") or 0.0,
                    "latency_p95_ms": h.get("latency_p95_ms") or 0.0,
                    "reasons": h.get("reasons", []),
                }
            )
        return {"service": service, "depends_on": deps, "dependents": dependents, "dependency_health": health}

    def get_slo_status(self, service: str | None = None) -> dict[str, Any]:
        q = select(SLODefinition)
        if service:
            q = q.where(SLODefinition.service == service)
        now = self.cp.clock.now()
        return {"slos": [slo_status(self.db, s, now) for s in self.db.execute(q).scalars()]}

    def get_runbook(self, query: str, limit: int = 3) -> dict[str, Any]:
        return {
            "query": query,
            "runbooks": [
                {**d.as_dict(), "score": score} for d, score in self.cp.runbook_index.search(query, limit)
            ],
        }


def _aware(dt):
    from datetime import UTC

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
