"""Discrete-time simulation of a small microservice platform.

SIMULATION — this module models a Kubernetes-style deployment of five services. It is
the LocalCloudProvider's "infrastructure". Metrics are *computed* from the modelled
state (traffic, replicas, pod health, faults, database pool), so remediation actions
change state and therefore change the telemetry that verification reads back. Nothing
here is hard-coded to look healthy after an action.
"""

from __future__ import annotations

import math
import random
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

NODES = ["sim-node-a", "sim-node-b", "sim-node-c"]


@dataclass
class Pod:
    name: str
    service: str
    version: str
    node: str
    created_tick: int
    warmup: int = 1
    phase: str = "Pending"
    ready: bool = False
    restarts: int = 0
    restart_ticks: deque[int] = field(default_factory=lambda: deque(maxlen=50))
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    leak_mb_per_tick: float = 0.0
    crash_looping: bool = False
    terminate_at: int | None = None
    last_termination_reason: str | None = None


@dataclass
class ServiceModel:
    name: str
    kind: str  # http | worker | database
    tier: str
    owner: str
    description: str
    traffic_share: float  # fraction of edge rps reaching this service
    capacity_per_pod: float  # rps one pod can serve at 100% CPU
    base_latency_ms: float
    mem_limit_mb: float
    base_mem_mb: float
    deps: list[tuple[str, str]]  # (name, sync|async|db)
    replicas: int
    version: str
    conns_per_pod: int = 0
    pods: list[Pod] = field(default_factory=list)
    version_history: list[str] = field(default_factory=list)
    defective_versions: set[str] = field(default_factory=set)
    leaked_conns: float = 0.0
    conn_leak_rate: float = 0.0
    runaway_cpu: bool = False
    threadpool_starved: bool = False
    outage: bool = False
    queue_depth: float = 0.0
    stuck_job: str | None = None
    request_total: float = 0.0
    errors_total: float = 0.0
    last_conns: float = 0.0
    last: dict[str, float] = field(default_factory=dict)


def default_services() -> list[ServiceModel]:
    return [
        ServiceModel(
            "api-gateway",
            "http",
            "tier-1",
            "edge-platform",
            "Edge routing, auth, rate limiting",
            1.0,
            80,
            12,
            512,
            180,
            [("user-service", "sync"), ("payment-service", "sync")],
            3,
            "v1.8.2",
        ),
        ServiceModel(
            "user-service",
            "http",
            "tier-1",
            "identity",
            "Accounts, sessions and profiles",
            0.6,
            90,
            18,
            512,
            220,
            [("database", "db")],
            2,
            "v3.2.0",
            conns_per_pod=5,
        ),
        ServiceModel(
            "payment-service",
            "http",
            "tier-0",
            "payments",
            "Payment authorisation and capture",
            0.3,
            30,
            45,
            768,
            300,
            [("database", "db"), ("notification-service", "async")],
            3,
            "v2.4.1",
            conns_per_pod=6,
        ),
        ServiceModel(
            "notification-service",
            "worker",
            "tier-2",
            "messaging",
            "Asynchronous receipts and alerts (queue worker)",
            0.3,
            60,
            25,
            384,
            150,
            [],
            2,
            "v1.3.7",
        ),
        ServiceModel(
            "database",
            "database",
            "tier-0",
            "data-platform",
            "Primary PostgreSQL cluster (simulated)",
            0.9,
            1000,
            3,
            4096,
            1800,
            [],
            1,
            "pg-16.4",
        ),
    ]


FAULTS = {
    "high_cpu": "Runaway worker threads spin on every payment-service pod",
    "memory_leak": "One payment-service pod leaks memory on every request",
    "db_saturation": "payment-service leaks database connections until the pool is exhausted",
    "pod_crash": "A payment-service pod enters CrashLoopBackOff",
    "latency_spike": "payment-service request thread pool is starved; latency spikes",
    "deployment_failure": "A defective payment-service release is deployed",
    "traffic_spike": "Edge traffic surges 3.5x on gateway-served endpoints",
    "outage": "Every payment-service instance fails readiness",
    "queue_backlog": "A poison job blocks the notification-service worker",
}
DEFAULT_FAULT_TARGET = {k: "payment-service" for k in FAULTS} | {
    "traffic_spike": "api-gateway",
    "queue_backlog": "notification-service",
}


class Simulation:
    def __init__(self, seed: int | None = None, tick_seconds: float = 2.0):
        self.rng = random.Random(seed)
        self.tick_seconds = tick_seconds
        self.tick = 0
        self.lock = threading.RLock()
        self.services: dict[str, ServiceModel] = {s.name: s for s in default_services()}
        self.traffic_multiplier = 1.0
        self.edge_rps_base = 120.0
        self.db_max_connections = 100
        self.db_util_prev = 0.0
        self.faults: dict[str, dict[str, Any]] = {}
        self.logs: list[dict[str, Any]] = []
        for svc in self.services.values():
            svc.version_history = [svc.version]
            for _ in range(svc.replicas):
                p = self._new_pod(svc, warmup=0)
                p.phase, p.ready = "Running", True
                svc.pods.append(p)

    # ------------------------------------------------------------------ pods
    def _new_pod(self, svc: ServiceModel, warmup: int = 1) -> Pod:
        suffix = uuid.UUID(int=self.rng.getrandbits(128)).hex[:5]
        node = NODES[self.rng.randrange(len(NODES))]
        return Pod(
            name=f"{svc.name}-{svc.version.replace('.', '').lower()[-3:]}-{suffix}",
            service=svc.name,
            version=svc.version,
            node=node,
            created_tick=self.tick,
            warmup=warmup,
            phase="Pending" if warmup else "Running",
            ready=warmup == 0,
            memory_mb=svc.base_mem_mb * self.rng.uniform(0.95, 1.05),
        )

    def _live_pods(self, svc: ServiceModel) -> list[Pod]:
        return [p for p in svc.pods if p.terminate_at is None]

    def _roll(self, svc: ServiceModel) -> None:
        """Surge-style rolling replacement: new pods start; old ones terminate next tick."""
        for p in svc.pods:
            if p.terminate_at is None:
                p.terminate_at = self.tick + 1
        for _ in range(svc.replicas):
            svc.pods.append(self._new_pod(svc))

    # ----------------------------------------------------------- remediation
    def restart_pod(self, service: str, pod: str) -> dict[str, Any]:
        with self.lock:
            svc = self._svc(service)
            target = next((p for p in self._live_pods(svc) if p.name == pod), None)
            if target is None:
                raise KeyError(f"pod {pod} not found in {service}")
            svc.pods.remove(target)
            new = self._new_pod(svc)
            svc.pods.append(new)
            self._clear_pod_faults(target.name)
            self._log(
                svc,
                "INFO",
                "pod_deleted",
                f"Pod {pod} deleted by remediation; replacement {new.name} scheduled on {new.node}",
                pod=new.name,
            )
            return {"deleted": pod, "replacement": new.name}

    def restart_service(self, service: str) -> dict[str, Any]:
        with self.lock:
            svc = self._svc(service)
            old = [p.name for p in self._live_pods(svc)]
            svc.runaway_cpu = svc.threadpool_starved = svc.outage = False
            svc.leaked_conns = 0.0
            svc.conn_leak_rate = 0.0
            for name in old:
                self._clear_pod_faults(name)
            for key in [
                k
                for k, f in self.faults.items()
                if f["service"] == service
                and f["type"]
                in ("high_cpu", "latency_spike", "outage", "db_saturation", "memory_leak", "pod_crash")
            ]:
                self.faults.pop(key)
            self._roll(svc)
            self._log(
                svc, "INFO", "rollout_restart", f"Rolling restart of {service}: replacing {len(old)} pods"
            )
            return {"replaced": old}

    def scale(self, service: str, replicas: int) -> dict[str, Any]:
        with self.lock:
            svc = self._svc(service)
            before = svc.replicas
            svc.replicas = replicas
            live = self._live_pods(svc)
            if replicas > len(live):
                for _ in range(replicas - len(live)):
                    svc.pods.append(self._new_pod(svc))
            else:
                # remove unhealthy pods first, then newest
                victims = sorted(live, key=lambda p: (p.ready, -p.created_tick))[: len(live) - replicas]
                for v in victims:
                    v.terminate_at = self.tick
            self._log(svc, "INFO", "scaled", f"Deployment {service} scaled {before} -> {replicas}")
            return {"from": before, "to": replicas}

    def deploy(self, service: str, version: str, defective: bool = False) -> dict[str, Any]:
        with self.lock:
            svc = self._svc(service)
            prev = svc.version
            svc.version = version
            svc.version_history.append(version)
            if defective:
                svc.defective_versions.add(version)
                self.faults[f"deployment_failure:{service}"] = {
                    "type": "deployment_failure",
                    "service": service,
                    "since_tick": self.tick,
                    "version": version,
                }
            self._roll(svc)
            self._log(svc, "INFO", "deploy_started", f"Rolling out {service} {prev} -> {version}")
            return {"from": prev, "to": version}

    def rollback(self, service: str) -> dict[str, Any]:
        with self.lock:
            svc = self._svc(service)
            if len(svc.version_history) < 2:
                raise ValueError(f"{service} has no previous version to roll back to")
            bad = svc.version_history.pop()
            svc.version = svc.version_history[-1]
            self.faults.pop(f"deployment_failure:{service}", None)
            self._roll(svc)
            self._log(svc, "INFO", "rollback_started", f"Rolling back {service} {bad} -> {svc.version}")
            return {"from": bad, "to": svc.version}

    def clear_failed_job(self, service: str, job_id: str) -> dict[str, Any]:
        with self.lock:
            svc = self._svc(service)
            if svc.stuck_job != job_id:
                raise KeyError(f"job {job_id} is not a failed job in {service}")
            svc.stuck_job = None
            self.faults.pop(f"queue_backlog:{service}", None)
            self._log(
                svc,
                "INFO",
                "job_dead_lettered",
                f"Job {job_id} moved to dead-letter queue; worker resumed",
                job_id=job_id,
            )
            return {"dead_lettered": job_id}

    def _clear_pod_faults(self, pod_name: str) -> None:
        for key in [k for k, f in self.faults.items() if f.get("pod") == pod_name]:
            self.faults.pop(key)

    # --------------------------------------------------------------- faults
    def inject(self, fault: str, service: str | None = None) -> dict[str, Any]:
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault}")
        with self.lock:
            service = service or DEFAULT_FAULT_TARGET[fault]
            svc = self._svc(service)
            key = f"{fault}:{service}"
            info: dict[str, Any] = {
                "type": fault,
                "service": service,
                "since_tick": self.tick,
                "description": FAULTS[fault],
            }
            live = [p for p in self._live_pods(svc) if p.ready] or self._live_pods(svc)
            if fault == "high_cpu":
                svc.runaway_cpu = True
            elif fault == "memory_leak":
                pod = live[0]
                pod.leak_mb_per_tick = svc.mem_limit_mb * 0.06
                info["pod"] = pod.name
            elif fault == "db_saturation":
                svc.conn_leak_rate = 7.0
            elif fault == "pod_crash":
                pod = live[-1]
                pod.crash_looping = True
                info["pod"] = pod.name
            elif fault == "latency_spike":
                svc.threadpool_starved = True
            elif fault == "deployment_failure":
                major, minor, patch = (svc.version.lstrip("v").split(".") + ["0", "0"])[:3]
                version = f"v{major}.{int(minor) + 1}.0"
                self.deploy(service, version, defective=True)
                info["version"] = version
                key = f"deployment_failure:{service}"
            elif fault == "traffic_spike":
                self.traffic_multiplier = 3.5
            elif fault == "outage":
                svc.outage = True
            elif fault == "queue_backlog":
                svc.stuck_job = f"job-{uuid.UUID(int=self.rng.getrandbits(128)).hex[:8]}"
                info["job_id"] = svc.stuck_job
            self.faults[key] = info
            return info

    def clear_all(self) -> None:
        with self.lock:
            self.traffic_multiplier = 1.0
            for svc in self.services.values():
                svc.runaway_cpu = svc.threadpool_starved = svc.outage = False
                svc.conn_leak_rate = svc.leaked_conns = 0.0
                svc.stuck_job = None
                svc.queue_depth = 0.0
                for p in svc.pods:
                    p.leak_mb_per_tick = 0.0
                    p.crash_looping = False
                    p.memory_mb = min(p.memory_mb, svc.base_mem_mb * 1.05)
                if svc.version in svc.defective_versions:
                    svc.defective_versions.discard(svc.version)
            self.faults.clear()

    # ----------------------------------------------------------------- tick
    def _svc(self, name: str) -> ServiceModel:
        if name not in self.services:
            raise KeyError(f"unknown service {name}")
        return self.services[name]

    def _noise(self, scale: float) -> float:
        return self.rng.gauss(0, scale)

    def _log(self, svc: ServiceModel, level: str, event: str, message: str, **extra: Any) -> None:
        pods = self._live_pods(svc)
        entry = {
            "tick": self.tick,
            "level": level,
            "service": svc.name,
            "event": event,
            "message": message,
            "pod": extra.pop("pod", pods[self.rng.randrange(len(pods))].name if pods else None),
            "version": svc.version,
            **extra,
        }
        self.logs.append(entry)

    def step(self, now: datetime) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
        with self.lock:
            self.tick += 1
            self.logs = []
            for svc in self.services.values():
                self._advance_pods(svc)
            diurnal = 1 + 0.08 * math.sin(self.tick / 120)
            edge_rps = max(1.0, self.edge_rps_base * diurnal * (1 + self._noise(0.03)))
            out: dict[str, dict[str, float]] = {}
            order = ["database", "notification-service", "user-service", "payment-service", "api-gateway"]
            for name in order:
                svc = self.services[name]
                if name == "api-gateway":
                    rps = edge_rps * self.traffic_multiplier
                else:
                    rps = edge_rps * svc.traffic_share
                if svc.kind == "database":
                    out[name] = self._compute_db(svc, edge_rps)
                elif svc.kind == "worker":
                    out[name] = self._compute_worker(svc, rps)
                else:
                    out[name] = self._compute_http(svc, rps, out)
                svc.last = out[name]
            for entry in self.logs:
                entry["ts"] = now.isoformat()
            return out, list(self.logs)

    def _advance_pods(self, svc: ServiceModel) -> None:
        for p in list(svc.pods):
            if p.terminate_at is not None and p.terminate_at <= self.tick:
                svc.pods.remove(p)
                continue
            if p.warmup > 0:
                p.warmup -= 1
                if p.warmup == 0:
                    p.phase, p.ready = "Running", True
                continue
            if p.crash_looping:
                if (self.tick - p.created_tick) % 2 == 0:
                    p.restarts += 1
                    p.restart_ticks.append(self.tick)
                    p.last_termination_reason = "Error (exit code 137)"
                    self._log(
                        svc,
                        "ERROR",
                        "process_crash",
                        f"Process exited with code 137: SIGSEGV in native payment-crypto module (restart #{p.restarts})",
                        pod=p.name,
                    )
                p.phase, p.ready = "CrashLoopBackOff", False
                continue
            if svc.outage:
                p.phase, p.ready = "Running", False
                continue
            p.phase, p.ready = "Running", True
            if p.leak_mb_per_tick:
                headroom = svc.mem_limit_mb * 0.97 - p.memory_mb
                p.memory_mb += min(p.leak_mb_per_tick, max(0.0, headroom) * 0.5 + 1)
            else:
                p.memory_mb += (svc.base_mem_mb - p.memory_mb) * 0.2 + self._noise(svc.base_mem_mb * 0.01)

    def _compute_http(
        self, svc: ServiceModel, rps: float, done: dict[str, dict[str, float]]
    ) -> dict[str, float]:
        live = self._live_pods(svc)
        ready = [p for p in svc.pods if p.ready]
        n = len(ready)
        err = 0.0002 + abs(self._noise(0.0001))  # healthy background error rate (~0.03%)
        if n == 0:
            util = 0.0
            cpu = 2.0
            p50, p95 = 1500.0, 3000.0
            err = 1.0
        else:
            util = rps / (n * svc.capacity_per_pod)
            q = 1 / (1 - min(util, 0.95))
            p50 = svc.base_latency_ms * (0.7 + 0.3 * q) * (1 + self._noise(0.03))
            p95 = p50 * 2.3
            cpu = 6 + min(util, 1.25) * 76 + self._noise(1.5)
            if svc.runaway_cpu:
                cpu += 70  # spinning threads burn CPU independent of load
            cpu = max(1.0, min(100.0, cpu))
            if cpu > 92:
                p95 *= 1 + (cpu - 92) / 4
            if util > 1:
                err += (util - 1) / util
                if self.rng.random() < 0.7:
                    self._log(
                        svc,
                        "WARN",
                        "request_queue_saturated",
                        f"Request queue saturated ({util * 100:.0f}% of capacity); shedding load",
                    )
            if svc.runaway_cpu and self.rng.random() < 0.8:
                self._log(
                    svc,
                    "WARN",
                    "worker_hot_loop",
                    "Worker thread pool: 8 threads busy > 30s in ReconciliationLoop.run (possible hot loop)",
                )
            gc_pods = [p for p in ready if p.memory_mb / svc.mem_limit_mb > 0.85]
            if gc_pods:
                frac = len(gc_pods) / n
                p95 += svc.base_latency_ms * 9 * frac
                p50 += svc.base_latency_ms * 2 * frac
                for gp in gc_pods:
                    if self.rng.random() < 0.8:
                        self._log(
                            svc,
                            "WARN",
                            "gc_pressure",
                            f"GC overhead {self.rng.randint(35, 70)}% of CPU time; heap {gp.memory_mb:.0f}/{svc.mem_limit_mb:.0f} MiB",
                            pod=gp.name,
                        )
            if svc.threadpool_starved:
                p50 += 380 + self._noise(30)
                p95 += 1900 + self._noise(120)
                err += 0.015
                if self.rng.random() < 0.85:
                    self._log(
                        svc,
                        "WARN",
                        "threadpool_exhausted",
                        "HTTP worker pool exhausted (200/200 busy); requests queued > 2s",
                    )
                    self._log(
                        svc,
                        "WARN",
                        "slow_request",
                        f"Slow request POST /v1/charges took {self.rng.randint(1800, 3200)} ms",
                    )
            if svc.version in svc.defective_versions:
                err += 0.28 + self._noise(0.02)
                for _ in range(self.rng.randint(2, 5)):
                    self._log(
                        svc,
                        "ERROR",
                        "unhandled_exception",
                        f"Unhandled NullPointerException in ChargeController.capture (currency=null) [{svc.version}]",
                    )
        # dependencies
        for dep_name, kind in svc.deps:
            dep = done.get(dep_name)
            if not dep or kind == "async":
                continue
            if kind == "sync":
                p95 += dep["latency_p95_ms"] * 0.8
                p50 += dep["latency_p50_ms"] * 0.8
                dep_err = (
                    dep["error_rate"] * self.services[dep_name].traffic_share / max(svc.traffic_share, 0.01)
                )
                err += dep_err
                if dep["error_rate"] > 0.05 and self.rng.random() < 0.9:
                    self._log(
                        svc,
                        "ERROR",
                        "upstream_error",
                        f"Upstream {dep_name} returned 503 ({dep['error_rate'] * 100:.0f}% failures)",
                    )
                if dep["latency_p95_ms"] > 800 and self.rng.random() < 0.7:
                    self._log(
                        svc,
                        "WARN",
                        "upstream_timeout",
                        f"Upstream {dep_name} p95 {dep['latency_p95_ms']:.0f} ms approaching timeout",
                    )
            elif kind == "db" and n > 0:
                if self.db_util_prev >= 0.97:
                    err += 0.22
                    p95 += 1000
                    p50 += 200
                    for _ in range(self.rng.randint(1, 4)):
                        self._log(
                            svc,
                            "ERROR",
                            "db_too_many_connections",
                            "FATAL: sorry, too many clients already (SQLSTATE 53300)",
                        )
                elif self.db_util_prev >= 0.85:
                    p95 += 350
                    if self.rng.random() < 0.8:
                        self._log(
                            svc,
                            "WARN",
                            "db_pool_exhausted",
                            "Timed out after 1000 ms waiting for a connection from the pool",
                        )
        if svc.outage and self.rng.random() < 0.95:
            self._log(
                svc,
                "ERROR",
                "readiness_probe_failed",
                "Readiness probe failed: GET /ready -> connection refused",
            )
            self._log(
                svc,
                "ERROR",
                "process_exit",
                "Process exited: failed to bind listener (address already in use)",
            )

        # connection accounting
        if svc.conns_per_pod:
            if svc.conn_leak_rate:
                svc.leaked_conns += svc.conn_leak_rate
                if self.rng.random() < 0.6:
                    self._log(
                        svc,
                        "WARN",
                        "db_conn_not_returned",
                        f"Connection checked out > 30s without release (leaked={svc.leaked_conns:.0f})",
                    )
            base_conns = svc.conns_per_pod * len(live) + rps * 0.04
            svc.last_conns = base_conns + svc.leaked_conns
        err = max(0.0, min(1.0, err))
        dt = self.tick_seconds
        reqs = rps * dt
        svc.request_total += reqs
        svc.errors_total += reqs * err
        if err < 0.02 and self.rng.random() < 0.6:
            self._log(svc, "INFO", "request", f"GET /v1/{svc.name.split('-')[0]} 200 {p50:.0f}ms")
        mem = (sum(p.memory_mb for p in ready) / n / svc.mem_limit_mb * 100) if n else 0.0
        return self._pack(svc, rps=rps, cpu=cpu, mem=mem, p50=p50, p95=p95, err=err, util=util)

    def _compute_worker(self, svc: ServiceModel, rps: float) -> dict[str, float]:
        ready = [p for p in svc.pods if p.ready]
        n = len(ready)
        capacity = 0.0 if svc.stuck_job else n * svc.capacity_per_pod
        incoming = rps
        svc.queue_depth = max(0.0, svc.queue_depth + (incoming - capacity) * self.tick_seconds)
        processed = min(capacity, incoming + svc.queue_depth / self.tick_seconds) if capacity else 0
        util = processed / (n * svc.capacity_per_pod) if n else 0
        cpu = max(1.0, min(100.0, 5 + util * 70 + (25 if svc.stuck_job else 0) + self._noise(1.5)))
        err = 0.001
        if svc.stuck_job:
            err = 0.0
            self._log(
                svc,
                "ERROR",
                "job_failed_retrying",
                f"Job {svc.stuck_job} failed (TemplateRenderError: missing 'locale'); retry 1/inf - worker blocked",
                job_id=svc.stuck_job,
            )
            if svc.queue_depth > 300:
                self._log(
                    svc,
                    "WARN",
                    "queue_backlog",
                    f"Queue depth {svc.queue_depth:.0f} exceeds 300; oldest message age {svc.queue_depth / max(incoming, 1):.0f}s",
                )
        p50 = svc.base_latency_ms * (1 + self._noise(0.03))
        p95 = p50 * 2.1
        reqs = processed * self.tick_seconds
        svc.request_total += reqs
        mem = (sum(p.memory_mb for p in ready) / n / svc.mem_limit_mb * 100) if n else 0.0
        return self._pack(
            svc,
            rps=processed,
            cpu=cpu,
            mem=mem,
            p50=p50,
            p95=p95,
            err=err,
            util=util,
            queue_depth=svc.queue_depth,
        )

    def _compute_db(self, svc: ServiceModel, edge_rps: float) -> dict[str, float]:
        clients = self.db_clients()
        active = min(self.db_max_connections, sum(clients.values()))
        util = active / self.db_max_connections
        self.db_util_prev = util
        qps = edge_rps * 0.9 * 4
        cpu = max(1.0, min(100.0, 12 + qps * 0.04 + util * 25 + self._noise(1.0)))
        p50 = svc.base_latency_ms * (1 + util * 3)
        p95 = p50 * 2.5
        demand = sum(clients.values())
        err = (
            max(0.0, (demand - self.db_max_connections) / demand) if demand > self.db_max_connections else 0.0
        )
        if util >= 0.97:
            self._log(
                svc,
                "ERROR",
                "max_connections_reached",
                f"FATAL: remaining connection slots are reserved ({active}/{self.db_max_connections})",
            )
        elif util >= 0.85 and self.rng.random() < 0.7:
            self._log(
                svc,
                "WARN",
                "connections_high",
                f"Connection count {active}/{self.db_max_connections} above 85%",
            )
        for p in svc.pods:
            p.memory_mb = svc.base_mem_mb * (1 + util * 0.3)
        svc.request_total += qps * self.tick_seconds
        svc.errors_total += qps * self.tick_seconds * err
        out = self._pack(
            svc,
            rps=qps,
            cpu=cpu,
            mem=svc.pods[0].memory_mb / svc.mem_limit_mb * 100 if svc.pods else 0,
            p50=p50,
            p95=p95,
            err=err,
            util=util,
        )
        out["db_connections"] = float(active)
        out["db_max_connections"] = float(self.db_max_connections)
        out["db_utilization"] = util
        return out

    def db_clients(self) -> dict[str, float]:
        return {
            s.name: round(s.last_conns or s.conns_per_pod * len(s.pods), 1)
            for s in self.services.values()
            if s.conns_per_pod
        }

    def _pack(
        self,
        svc: ServiceModel,
        *,
        rps: float,
        cpu: float,
        mem: float,
        p50: float,
        p95: float,
        err: float,
        util: float,
        queue_depth: float = 0.0,
    ) -> dict[str, float]:
        ready = sum(1 for p in svc.pods if p.ready)
        live = self._live_pods(svc)
        restarts = sum(p.restarts for p in live)
        net = rps * self.rng.uniform(1.8, 2.2)  # KB/s
        return {
            "cpu_percent": round(cpu, 2),
            "memory_percent": round(mem, 2),
            "memory_max_pod_percent": round(
                max((p.memory_mb / svc.mem_limit_mb * 100 for p in live if p.ready), default=0.0), 2
            ),
            "latency_p50_ms": round(max(1.0, p50), 2),
            "latency_p95_ms": round(max(1.0, p95), 2),
            "rps": round(rps, 2),
            "error_rate": round(err, 5),
            "http_2xx_rps": round(rps * (1 - err), 2),
            "http_5xx_rps": round(rps * err, 2),
            "request_count": round(svc.request_total),
            "availability": round(1 - err, 5),
            "restarts": float(restarts),
            "healthy_pods": float(ready),
            "replicas": float(svc.replicas),
            "network_rx_kbps": round(net, 1),
            "network_tx_kbps": round(net * 1.6, 1),
            "db_connections": round(svc.last_conns, 1),
            "queue_depth": round(queue_depth, 1),
            "utilization": round(util, 3),
        }

    # --------------------------------------------------------------- views
    def pod_view(self, service: str) -> list[dict[str, Any]]:
        with self.lock:
            svc = self._svc(service)
            out = []
            for p in svc.pods:
                recent = sum(1 for t in p.restart_ticks if self.tick - t <= 15)
                out.append(
                    {
                        "name": p.name,
                        "service": service,
                        "node": p.node,
                        "version": p.version,
                        "phase": "Terminating" if p.terminate_at is not None else p.phase,
                        "ready": p.ready,
                        "restarts": p.restarts,
                        "recent_restarts": recent,
                        "cpu_percent": svc.last.get("cpu_percent", 0.0) if p.ready else 0.0,
                        "memory_mb": round(p.memory_mb, 1),
                        "memory_limit_mb": svc.mem_limit_mb,
                        "memory_percent": round(p.memory_mb / svc.mem_limit_mb * 100, 1),
                        "age_seconds": (self.tick - p.created_tick) * self.tick_seconds,
                        "last_termination_reason": p.last_termination_reason,
                    }
                )
            return out
