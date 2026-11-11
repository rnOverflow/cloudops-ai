"""Deterministic evidence extraction and hypothesis scoring.

Every OBSERVED_FACT produced here is derived directly from a tool output. Hypothesis
scores are transparent weighted sums of those facts and are reported as AI_INFERENCE.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .policy import ALLOWED_ACTIONS, MAX_REPLICAS
from .types import Finding, FindingKind, Hypothesis, Recommendation

THRESHOLDS = {"cpu": 85.0, "memory": 85.0, "latency_p95_ms": 500.0, "error_rate": 0.05, "db_util": 0.85}


@dataclass
class Evidence:
    service: str
    health: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, Any] = field(default_factory=dict)
    deployments: list[dict[str, Any]] = field(default_factory=list)
    pods: list[dict[str, Any]] = field(default_factory=list)
    database: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    slo: list[dict[str, Any]] = field(default_factory=list)


def _latest(ev: Evidence, key: str, default: float = 0.0) -> float:
    return float(ev.metrics.get("latest", {}).get(key, default) or 0.0)


def _baseline(ev: Evidence, key: str, default: float = 0.0) -> float:
    return float(ev.metrics.get("baseline", {}).get(key, default) or 0.0)


def _series(ev: Evidence, key: str) -> list[float]:
    return [float(v) for v in ev.metrics.get("series", {}).get(key, []) if v is not None]


def _fact(statement: str, source: str, **data: Any) -> Finding:
    return Finding(kind=FindingKind.OBSERVED_FACT, statement=statement, source=source, data=data)


def extract_facts(ev: Evidence) -> tuple[list[Finding], dict[str, Any]]:
    """Return facts and a signal dictionary used for scoring."""
    facts: list[Finding] = []
    s: dict[str, Any] = {}
    svc = ev.service

    status = ev.health.get("status", "UNKNOWN")
    s["status"] = status
    facts.append(
        _fact(
            f"{svc} health status is {status}"
            + (f" ({'; '.join(ev.health.get('reasons', []))})" if ev.health.get("reasons") else ""),
            "get_service_health",
            status=status,
        )
    )

    cpu, cpu_b = _latest(ev, "cpu_percent"), _baseline(ev, "cpu_percent")
    mem = _latest(ev, "memory_percent")
    lat, lat_b = _latest(ev, "latency_p95_ms"), _baseline(ev, "latency_p95_ms")
    err, err_b = _latest(ev, "error_rate"), _baseline(ev, "error_rate")
    rps, rps_b = _latest(ev, "rps"), _baseline(ev, "rps")
    s.update(cpu=cpu, cpu_b=cpu_b, mem=mem, lat=lat, lat_b=lat_b, err=err, err_b=err_b, rps=rps, rps_b=rps_b)
    s["rps_ratio"] = (rps / rps_b) if rps_b > 0 else 1.0
    s["lat_ratio"] = (lat / lat_b) if lat_b > 0 else 1.0

    if ev.metrics:
        facts.append(
            _fact(
                f"CPU {cpu:.1f}% (baseline {cpu_b:.1f}%, threshold {THRESHOLDS['cpu']:.0f}%)",
                "get_metrics",
                cpu=cpu,
                baseline=cpu_b,
            )
        )
        facts.append(
            _fact(
                f"p95 latency {lat:.0f} ms (baseline {lat_b:.0f} ms, threshold {THRESHOLDS['latency_p95_ms']:.0f} ms)",
                "get_metrics",
                latency_p95_ms=lat,
                baseline=lat_b,
            )
        )
        facts.append(
            _fact(
                f"Error rate {err * 100:.2f}% (baseline {err_b * 100:.2f}%, threshold {THRESHOLDS['error_rate'] * 100:.0f}%)",
                "get_metrics",
                error_rate=err,
                baseline=err_b,
            )
        )
        facts.append(
            _fact(
                f"Throughput {rps:.0f} req/s (baseline {rps_b:.0f} req/s, {s['rps_ratio']:.1f}x)",
                "get_metrics",
                rps=rps,
                baseline=rps_b,
            )
        )
        mem_series = _series(ev, "memory_percent")
        s["mem_rising"] = len(mem_series) >= 6 and mem_series[-1] - mem_series[-6] > 5
        conn_series = _series(ev, "db_connections")
        s["conn_rising"] = len(conn_series) >= 6 and conn_series[-1] - conn_series[-6] > 5

    # Pods
    pods = ev.pods
    s["replicas"] = len(pods)
    s["ready_pods"] = sum(1 for p in pods if p.get("ready"))
    crash = [p for p in pods if p.get("phase") == "CrashLoopBackOff" or p.get("recent_restarts", 0) >= 3]
    s["crash_pods"] = crash
    hot_mem = sorted(pods, key=lambda p: p.get("memory_percent", 0), reverse=True)
    s["top_mem_pod"] = hot_mem[0] if hot_mem else None
    s["max_pod_mem"] = hot_mem[0].get("memory_percent", 0) if hot_mem else mem
    others = [p.get("memory_percent", 0) for p in hot_mem[1:]]
    s["mem_outlier"] = bool(others) and s["max_pod_mem"] - statistics.median(others) > 25
    if pods:
        facts.append(
            _fact(
                f"{s['ready_pods']}/{len(pods)} pods ready",
                "get_pod_status",
                ready=s["ready_pods"],
                replicas=len(pods),
            )
        )
        for p in crash:
            facts.append(
                _fact(
                    f"Pod {p['name']} is {p.get('phase')} with {p.get('restarts', 0)} restarts ({p.get('recent_restarts', 0)} recent); last termination: {p.get('last_termination_reason') or 'n/a'}",
                    "get_pod_status",
                    pod=p["name"],
                )
            )
        if s["max_pod_mem"] >= THRESHOLDS["memory"] and s["top_mem_pod"]:
            p = s["top_mem_pod"]
            facts.append(
                _fact(
                    f"Pod {p['name']} memory at {p.get('memory_percent', 0):.0f}% of limit ({p.get('memory_mb', 0):.0f}/{p.get('memory_limit_mb', 0):.0f} MiB)",
                    "get_pod_status",
                    pod=p["name"],
                )
            )

    # Logs
    events: Counter[str] = Counter()
    event_samples: dict[str, dict[str, Any]] = {}
    for entry in ev.logs.get("logs", []):
        if entry.get("level") in ("WARN", "ERROR"):
            events[entry.get("event", "unknown")] += 1
            event_samples.setdefault(entry.get("event", "unknown"), entry)
    s["events"] = events
    s["event_samples"] = event_samples
    total_err_logs = sum(1 for e in ev.logs.get("logs", []) if e.get("level") == "ERROR")
    facts.append(
        _fact(f"{total_err_logs} ERROR log lines in the inspected window", "query_logs", count=total_err_logs)
    )
    for event, count in events.most_common(3):
        sample = event_samples[event]
        facts.append(
            _fact(
                f"Log event '{event}' x{count}: \"{sample.get('message', '')[:160]}\"",
                "query_logs",
                event=event,
                count=count,
            )
        )

    # Deployments
    # The newest version-changing event decides what is running: a later ROLLBACK supersedes a DEPLOY.
    changes = sorted(
        (
            d
            for d in ev.deployments
            if d.get("service") == svc and d.get("kind", "DEPLOY") in ("DEPLOY", "ROLLBACK")
        ),
        key=lambda d: d.get("age_seconds", 1e9),
    )
    latest = changes[0] if changes else None
    recent = (
        [latest]
        if latest and latest.get("kind", "DEPLOY") == "DEPLOY" and latest.get("age_seconds", 1e9) <= 900
        else []
    )
    s["recent_deploy"] = recent[0] if recent else None
    if latest and latest.get("kind") == "ROLLBACK" and latest.get("age_seconds", 1e9) <= 900:
        facts.append(
            _fact(
                f"{svc} was rolled back to {latest.get('version')} {int(latest['age_seconds'])}s ago",
                "get_recent_deployments",
            )
        )
    if recent:
        d = recent[0]
        facts.append(
            _fact(
                f"{d.get('kind', 'DEPLOY')} {d.get('previous_version')} -> {d.get('version')} {int(d['age_seconds'])}s ago by {d.get('actor')}",
                "get_recent_deployments",
                version=d.get("version"),
            )
        )
    elif not latest or latest.get("kind") != "ROLLBACK":
        facts.append(_fact(f"No deployments to {svc} in the last 15 minutes", "get_recent_deployments"))

    # Database
    db = ev.database
    if db:
        util = float(db.get("utilization", 0))
        s["db_util"] = util
        clients = db.get("clients", {})
        top = max(clients.items(), key=lambda kv: kv[1]) if clients else (None, 0)
        s["db_top_client"] = top[0]
        s["db_top_share"] = (top[1] / db["active_connections"]) if db.get("active_connections") else 0
        facts.append(
            _fact(
                f"Database connections {db.get('active_connections')}/{db.get('max_connections')} ({util * 100:.0f}% utilised); largest client {top[0]} holds {top[1]}",
                "get_database_status",
                utilization=util,
                top_client=top[0],
            )
        )

    # Dependencies
    degraded_deps = [
        d
        for d in ev.dependencies.get("dependency_health", [])
        if d.get("status") in ("DEGRADED", "UNHEALTHY") and d.get("type") != "async"
    ]
    s["degraded_deps"] = degraded_deps
    for d in degraded_deps:
        facts.append(
            _fact(
                f"Dependency {d['name']} is {d['status']} (error rate {d.get('error_rate', 0) * 100:.1f}%, p95 {d.get('latency_p95_ms', 0):.0f} ms)",
                "get_service_dependencies",
                dependency=d["name"],
            )
        )

    # Queue
    qd = _latest(ev, "queue_depth")
    q_series = _series(ev, "queue_depth")
    s["queue_depth"] = qd
    s["queue_growing"] = len(q_series) >= 4 and q_series[-1] > q_series[-4]
    if qd > 0:
        facts.append(
            _fact(
                f"Queue depth {qd:.0f} jobs ({'growing' if s['queue_growing'] else 'stable/draining'})",
                "get_metrics",
                queue_depth=qd,
            )
        )

    for slo in ev.slo:
        facts.append(
            _fact(
                f"SLO '{slo.get('name')}' attainment {slo.get('attainment', 0) * 100:.3f}% vs target {slo.get('target', 0) * 100:.2f}%; error budget remaining {slo.get('error_budget_remaining', 0) * 100:.1f}%",
                "get_slo_status",
            )
        )
    return facts, s


def _h(key: str, title: str, score: float, supporting: list[str], service: str) -> Hypothesis:
    return Hypothesis(
        key=key,
        title=title,
        score=round(score, 3),
        confidence=0.0,
        supporting=supporting,
        root_cause_service=service,
    )


def score_hypotheses(service: str, s: dict[str, Any]) -> list[Hypothesis]:
    ev: Counter[str] = s.get("events", Counter())
    out: list[Hypothesis] = []
    elevated_err = s.get("err", 0) >= THRESHOLDS["error_rate"] or s.get("err", 0) > 3 * max(
        s.get("err_b", 0), 0.005
    )
    elevated_lat = s.get("lat", 0) >= THRESHOLDS["latency_p95_ms"] or s.get("lat_ratio", 1) >= 2.5

    # Bad deployment
    sc, sup = 0.0, []
    if s.get("recent_deploy"):
        sc += 0.3
        sup.append(f"deployment {s['recent_deploy'].get('version')} in last 15 min")
    if s.get("recent_deploy") and elevated_err:
        sc += 0.35
        sup.append("error rate elevated after deployment")
    if ev.get("unhandled_exception"):
        sc += 0.25
        sup.append(f"{ev['unhandled_exception']} unhandled exceptions in logs")
    out.append(_h("bad_deployment", "Faulty deployment introduced a regression", sc, sup, service))

    # DB connection leak / saturation
    sc, sup = 0.0, []
    if s.get("db_util", 0) >= THRESHOLDS["db_util"]:
        sc += 0.4
        sup.append(f"database {s['db_util'] * 100:.0f}% saturated")
    if s.get("db_util", 0) >= 0.7 and s.get("db_top_share", 0) >= 0.5:
        sc += 0.2
        sup.append(f"{s['db_top_client']} holds {s['db_top_share'] * 100:.0f}% of connections")
    if ev.get("db_pool_exhausted") or ev.get("db_too_many_connections"):
        sc += 0.25
        sup.append("connection pool exhaustion in logs")
    if s.get("conn_rising"):
        sc += 0.1
        sup.append("connection count rising")
    out.append(
        _h(
            "db_connection_leak",
            "Database connection leak saturating the shared database",
            sc,
            sup,
            s.get("db_top_client") or service,
        )
    )

    # Memory leak
    sc, sup = 0.0, []
    if s.get("max_pod_mem", 0) >= THRESHOLDS["memory"]:
        sc += 0.4
        sup.append(f"pod memory at {s['max_pod_mem']:.0f}%")
    if s.get("mem_rising"):
        sc += 0.2
        sup.append("memory trending upward")
    if s.get("mem_outlier"):
        sc += 0.15
        sup.append("single pod is a memory outlier")
    if ev.get("gc_pressure"):
        sc += 0.2
        sup.append("GC pressure warnings in logs")
    out.append(_h("memory_leak", "Memory leak in a single pod", sc, sup, service))

    # Crash loop
    sc, sup = 0.0, []
    if s.get("crash_pods"):
        sc += 0.55
        sup.append(f"{len(s['crash_pods'])} pod(s) crash looping")
    if ev.get("process_crash"):
        sc += 0.3
        sup.append("process crash events in logs")
    out.append(_h("crash_loop", "Pod crash loop", sc, sup, service))

    # Runaway CPU
    sc, sup = 0.0, []
    if s.get("cpu", 0) >= THRESHOLDS["cpu"]:
        sc += 0.4
        sup.append(f"CPU {s['cpu']:.0f}%")
    if s.get("cpu", 0) >= 75 and s.get("rps_ratio", 1) < 1.5:
        sc += 0.25
        sup.append("traffic is near baseline, so load does not explain CPU")
    if ev.get("worker_hot_loop"):
        sc += 0.25
        sup.append("hot-loop warnings from worker threads")
    out.append(_h("runaway_cpu", "Runaway worker threads consuming CPU", sc, sup, service))

    # Traffic saturation
    sc, sup = 0.0, []
    if s.get("rps_ratio", 1) >= 2.0:
        sc += 0.4
        sup.append(f"traffic {s['rps_ratio']:.1f}x baseline")
    if s.get("rps_ratio", 1) >= 1.8 and s.get("cpu", 0) >= 75:
        sc += 0.25
        sup.append(f"CPU {s['cpu']:.0f}% under load")
    if s.get("rps_ratio", 1) >= 1.8 and elevated_lat:
        sc += 0.15
        sup.append("latency rising with load")
    if ev.get("request_queue_saturated"):
        sc += 0.1
        sup.append("request queue saturation in logs")
    out.append(_h("traffic_saturation", "Traffic surge exceeding provisioned capacity", sc, sup, service))

    # Outage
    sc, sup = 0.0, []
    if s.get("replicas", 0) > 0 and s.get("ready_pods", 1) == 0:
        sc += 0.6
        sup.append("no ready pods")
    if ev.get("readiness_probe_failed") or ev.get("process_exit"):
        sc += 0.25
        sup.append("readiness failures / process exits in logs")
    out.append(_h("service_outage", "Service outage: all instances unavailable", sc, sup, service))

    # Thread pool starvation
    sc, sup = 0.0, []
    if s.get("lat_ratio", 1) >= 3:
        sc += 0.35
        sup.append(f"p95 latency {s['lat_ratio']:.1f}x baseline")
    if elevated_lat and s.get("cpu", 0) < 70:
        sc += 0.15
        sup.append("CPU is not saturated")
    if elevated_lat and not s.get("degraded_deps"):
        sc += 0.1
        sup.append("dependencies are healthy")
    if ev.get("threadpool_exhausted"):
        sc += 0.3
        sup.append("thread pool exhaustion in logs")
    out.append(
        _h("threadpool_starvation", "Request thread pool starvation causing latency", sc, sup, service)
    )

    # Dependency degradation
    sc, sup = 0.0, []
    dep_svc = service
    if s.get("degraded_deps"):
        dep = sorted(s["degraded_deps"], key=lambda d: d["status"] == "UNHEALTHY", reverse=True)[0]
        dep_svc = dep["name"]
        sc += 0.5
        sup.append(f"dependency {dep_svc} is {dep['status']}")
        if s.get("cpu", 0) < 75 and s.get("max_pod_mem", 0) < 80 and not s.get("crash_pods"):
            sc += 0.2
            sup.append(f"{service}'s own resources look normal")
        if ev.get("upstream_error") or ev.get("upstream_timeout"):
            sc += 0.15
            sup.append("upstream call failures in logs")
    out.append(
        _h("dependency_degradation", "Symptoms propagated from a degraded dependency", sc, sup, dep_svc)
    )

    # Queue backlog
    sc, sup = 0.0, []
    if s.get("queue_depth", 0) > 300:
        sc += 0.35
        sup.append(f"queue depth {s['queue_depth']:.0f}")
    if s.get("queue_growing"):
        sc += 0.2
        sup.append("backlog growing")
    if ev.get("job_failed_retrying"):
        sc += 0.3
        sup.append("a failed job is being retried in a loop")
    out.append(_h("queue_backlog", "Queue backlog caused by a poison job", sc, sup, service))

    out = [h for h in out if h.score > 0]
    out.sort(key=lambda h: h.score, reverse=True)
    for i, h in enumerate(out):
        conf = min(0.95, h.score)
        if i == 0 and len(out) > 1 and out[0].score - out[1].score < 0.15:
            conf -= 0.15  # ambiguity penalty: two competing explanations
        h.confidence = round(max(0.05, conf), 2)
    return out


RUNBOOK_QUERIES = {
    "bad_deployment": "deployment failure regression error rate rollback",
    "db_connection_leak": "database connection saturation pool exhausted",
    "memory_leak": "high memory leak oom pod",
    "crash_loop": "pod crash loop restarts crashloopbackoff",
    "runaway_cpu": "high cpu runaway threads",
    "traffic_saturation": "traffic spike high cpu latency scale out capacity",
    "service_outage": "service outage unavailable no healthy instances",
    "threadpool_starvation": "api latency slow requests thread pool",
    "dependency_degradation": "high error rate dependency upstream failures",
    "queue_backlog": "queue backlog failed job poison message",
}


def recommend(h: Hypothesis, s: dict[str, Any]) -> Recommendation | None:
    svc = h.root_cause_service
    if h.key == "bad_deployment" and s.get("recent_deploy"):
        d = s["recent_deploy"]
        return Recommendation(
            action="rollback_deployment",
            target_service=svc,
            parameters={},
            rationale=f"Errors began after {d.get('version')} was deployed; rolling back restores the last known-good version {d.get('previous_version')}.",
            expected_impact="Error rate returns to baseline once the previous version is serving traffic.",
            risk=ALLOWED_ACTIONS["rollback_deployment"],
        )
    if h.key == "db_connection_leak":
        return Recommendation(
            action="restart_service",
            target_service=svc,
            parameters={},
            rationale=f"{svc} holds most database connections and they keep growing; a rolling restart releases leaked connections.",
            expected_impact="Database utilisation drops below 70% and dependent services stop failing to acquire connections.",
            risk=ALLOWED_ACTIONS["restart_service"],
        )
    if h.key == "memory_leak" and s.get("top_mem_pod"):
        pod = s["top_mem_pod"]["name"]
        return Recommendation(
            action="restart_pod",
            target_service=svc,
            parameters={"pod": pod},
            rationale=f"Pod {pod} is leaking memory while siblings are normal; replacing it reclaims memory without a full restart.",
            expected_impact="Pod memory returns to baseline; GC-induced latency disappears.",
            risk=ALLOWED_ACTIONS["restart_pod"],
        )
    if h.key == "crash_loop" and s.get("crash_pods"):
        pod = s["crash_pods"][0]["name"]
        return Recommendation(
            action="restart_pod",
            target_service=svc,
            parameters={"pod": pod},
            rationale=f"Pod {pod} is crash looping on its node-local state; deleting it lets the scheduler create a fresh replica.",
            expected_impact="All replicas Ready and restart counter stops increasing.",
            risk=ALLOWED_ACTIONS["restart_pod"],
        )
    if h.key in ("runaway_cpu", "service_outage", "threadpool_starvation"):
        return Recommendation(
            action="restart_service",
            target_service=svc,
            parameters={},
            rationale={
                "runaway_cpu": "CPU is saturated without extra traffic, pointing to stuck worker threads that a rolling restart clears.",
                "service_outage": "No instance is serving; a rolling restart brings processes back through readiness checks.",
                "threadpool_starvation": "Latency rose without CPU or dependency pressure, consistent with an exhausted request pool that a restart resets.",
            }[h.key],
            expected_impact="Service metrics return to baseline after pods pass readiness.",
            risk=ALLOWED_ACTIONS["restart_service"],
        )
    if h.key == "traffic_saturation":
        current = max(1, int(s.get("replicas", 1)))
        # Size for ~60% CPU: use the larger of the CPU-based estimate (capped at 100%, so it under-counts when
        # saturated) and the traffic-based estimate (traffic ratio x baseline CPU).
        need = max(s.get("cpu", 60) / 60, s.get("rps_ratio", 1) * max(s.get("cpu_b", 40), 1) / 60)
        target = min(MAX_REPLICAS, max(current + 1, math.ceil(current * need)))
        return Recommendation(
            action="scale_deployment",
            target_service=svc,
            parameters={"replicas": target},
            rationale=f"Load is {s.get('rps_ratio', 1):.1f}x baseline; scaling {current} -> {target} replicas targets ~60% CPU per pod.",
            expected_impact="CPU per pod and p95 latency fall back under thresholds.",
            risk=ALLOWED_ACTIONS["scale_deployment"],
        )
    if h.key == "queue_backlog":
        sample = s.get("event_samples", {}).get("job_failed_retrying", {})
        job = sample.get("job_id")
        if not job:
            return None
        return Recommendation(
            action="clear_failed_job",
            target_service=svc,
            parameters={"job_id": job},
            rationale=f"Job {job} fails and is retried indefinitely, blocking the worker; moving it to the dead-letter queue unblocks processing.",
            expected_impact="Queue drains and depth trends toward zero.",
            risk=ALLOWED_ACTIONS["clear_failed_job"],
        )
    return None
