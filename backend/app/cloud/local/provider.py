"""LocalCloudProvider: CloudProvider backed by the in-process Simulation.

All data returned by this provider is labelled SIMULATED in API responses."""

from __future__ import annotations

from typing import Any

from ...core.clock import Clock
from ..base import ActionResult, CloudProvider, ProviderError, TelemetrySnapshot
from .simulation import FAULTS, NODES, Simulation


class LocalCloudProvider(CloudProvider):
    name = "local"
    is_simulated = True
    supports_fault_injection = True

    def __init__(self, clock: Clock, seed: int | None = None, tick_seconds: float = 2.0):
        self.clock = clock
        self.sim = Simulation(seed=seed, tick_seconds=tick_seconds)

    def topology(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "tier": s.tier,
                "owner_team": s.owner,
                "description": s.description,
                "dependencies": [{"name": d, "type": t} for d, t in s.deps],
            }
            for s in self.sim.services.values()
        ]

    def collect(self) -> TelemetrySnapshot:
        now = self.clock.now()
        metrics, logs = self.sim.step(now)
        return TelemetrySnapshot(ts=now, tick=self.sim.tick, metrics=metrics, logs=logs)

    def pods(self, service: str) -> list[dict[str, Any]]:
        try:
            return self.sim.pod_view(service)
        except KeyError as exc:
            raise ProviderError(str(exc)) from exc

    def cluster_status(self) -> dict[str, Any]:
        with self.sim.lock:
            nodes = []
            for node in NODES:
                pods = [p for s in self.sim.services.values() for p in s.pods if p.node == node]
                cpu_req = sum(0.25 for _ in pods)
                mem_req = sum(self.sim.services[p.service].mem_limit_mb for p in pods) / 1024
                nodes.append(
                    {
                        "name": node,
                        "status": "Ready",
                        "pods": len(pods),
                        "cpu_allocatable": 4.0,
                        "cpu_requested": round(cpu_req, 2),
                        "memory_allocatable_gb": 16.0,
                        "memory_requested_gb": round(mem_req, 2),
                        "zone": f"local-{node[-1]}",
                    }
                )
            workloads = []
            for s in self.sim.services.values():
                ready = sum(1 for p in s.pods if p.ready)
                workloads.append(
                    {
                        "name": s.name,
                        "kind": "StatefulSet" if s.kind == "database" else "Deployment",
                        "replicas": s.replicas,
                        "ready_replicas": ready,
                        "version": s.version,
                        "pods": len(s.pods),
                        "hpa": None if s.kind == "database" else {"min": 2, "max": 10, "target_cpu": 70},
                    }
                )
            return {
                "provider": "local",
                "simulated": True,
                "cluster": "local-sim",
                "kubernetes_version": "v1.31 (simulated)",
                "nodes": nodes,
                "workloads": workloads,
                "tick": self.sim.tick,
            }

    def database_status(self) -> dict[str, Any]:
        with self.sim.lock:
            clients = self.sim.db_clients()
            active = min(self.sim.db_max_connections, round(sum(clients.values())))
            util = active / self.sim.db_max_connections
            return {
                "engine": "postgresql (simulated)",
                "max_connections": self.sim.db_max_connections,
                "active_connections": active,
                "utilization": round(util, 3),
                "clients": clients,
                "status": "SATURATED" if util >= 0.95 else "WARNING" if util >= 0.85 else "OK",
            }

    def deployment_state(self, service: str) -> dict[str, Any]:
        s = self.sim.services.get(service)
        if not s:
            raise ProviderError(f"unknown service {service}")
        return {
            "service": service,
            "version": s.version,
            "history": list(s.version_history),
            "replicas": s.replicas,
        }

    def _wrap(self, fn, *args) -> ActionResult:
        try:
            return ActionResult(ok=True, message="ok", details=fn(*args))
        except (KeyError, ValueError) as exc:
            return ActionResult(ok=False, message=str(exc).strip("'\""))

    def restart_pod(self, service: str, pod: str) -> ActionResult:
        return self._wrap(self.sim.restart_pod, service, pod)

    def restart_service(self, service: str) -> ActionResult:
        return self._wrap(self.sim.restart_service, service)

    def scale_deployment(self, service: str, replicas: int) -> ActionResult:
        return self._wrap(self.sim.scale, service, replicas)

    def rollback_deployment(self, service: str) -> ActionResult:
        return self._wrap(self.sim.rollback, service)

    def clear_failed_job(self, service: str, job_id: str) -> ActionResult:
        return self._wrap(self.sim.clear_failed_job, service, job_id)

    def deploy(self, service: str, version: str, defective: bool = False) -> ActionResult:
        return self._wrap(self.sim.deploy, service, version, defective)

    def inject_fault(self, fault: str, service: str | None = None) -> ActionResult:
        if fault not in FAULTS:
            return ActionResult(ok=False, message=f"unknown fault {fault}")
        return self._wrap(self.sim.inject, fault, service)

    def clear_faults(self) -> ActionResult:
        self.sim.clear_all()
        return ActionResult(ok=True, message="all simulated faults cleared")

    def active_faults(self) -> list[dict[str, Any]]:
        return [dict(f) for f in self.sim.faults.values()]
