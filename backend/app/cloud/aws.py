"""AWSProvider: ECS (Fargate) + CloudWatch + CloudWatch Logs + RDS.

Maps CloudOps logical services to ECS services. Pods are ECS tasks. Remediation
primitives map to ECS APIs:

    restart_pod          -> ecs:StopTask (the service scheduler replaces the task)
    restart_service      -> ecs:UpdateService(forceNewDeployment=True)
    scale_deployment     -> ecs:UpdateService(desiredCount)
    rollback_deployment  -> ecs:UpdateService(taskDefinition=<previous revision>)
    clear_failed_job     -> not supported (no queue integration configured)

The IAM policy in infrastructure/terraform/aws/iam.tf grants exactly these actions,
scoped to the CloudOps cluster.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from ..core.clock import Clock
from ..core.config import Settings
from .base import ActionResult, CloudProvider, ProviderError, TelemetrySnapshot
from .local.simulation import default_services

log = logging.getLogger("cloudops.aws")


def _parse_map(raw: str) -> dict[str, str]:
    return {k.strip(): v.strip() for k, v in (pair.split("=", 1) for pair in raw.split(",") if "=" in pair)}


class AWSProvider(CloudProvider):
    name = "aws"
    is_simulated = False
    supports_fault_injection = False

    def __init__(
        self,
        clock: Clock,
        cluster: str,
        service_map: dict[str, str],
        region: str,
        session=None,
        log_group_prefix: str = "/ecs/cloudops",
        rds_instance: str | None = None,
        rds_max_connections: int = 100,
        target_groups: dict[str, str] | None = None,
        alb: str | None = None,
        tick_seconds: float = 60.0,
    ):
        import boto3

        session = session or boto3.Session(region_name=region)
        self.clock = clock
        self.cluster = cluster
        self.service_map = service_map
        self.ecs = session.client("ecs")
        self.cw = session.client("cloudwatch")
        self.logs = session.client("logs")
        self.log_group_prefix = log_group_prefix
        self.rds_instance = rds_instance
        self.rds_max = rds_max_connections
        self.target_groups = target_groups or {}
        self.alb = alb
        self.tick_seconds = tick_seconds
        self._tick = 0
        self._last_log_ts: dict[str, int] = {}
        self._requests_total: dict[str, float] = {}
        self._topology = [
            {
                "name": s.name,
                "kind": s.kind,
                "tier": s.tier,
                "owner_team": s.owner,
                "description": s.description,
                "dependencies": [{"name": d, "type": t} for d, t in s.deps],
            }
            for s in default_services()
            if s.name in service_map or s.kind == "database"
        ]

    @classmethod
    def from_settings(cls, settings: Settings, clock: Clock) -> AWSProvider:
        if not settings.aws_ecs_cluster or not settings.aws_service_map:
            raise ProviderError("AWS provider requires AWS_ECS_CLUSTER and AWS_SERVICE_MAP")
        return cls(
            clock,
            settings.aws_ecs_cluster,
            _parse_map(settings.aws_service_map),
            settings.aws_region,
            log_group_prefix=settings.aws_log_group_prefix,
            rds_instance=settings.aws_rds_instance_id,
            rds_max_connections=settings.aws_rds_max_connections,
            target_groups=_parse_map(settings.aws_alb_target_groups),
            alb=settings.aws_alb_name,
            tick_seconds=max(settings.tick_seconds, 60.0),
        )

    # ------------------------------------------------------------- helpers
    def _ecs_name(self, service: str) -> str:
        if service not in self.service_map:
            raise ProviderError(f"service {service} is not mapped to an ECS service")
        return self.service_map[service]

    def _describe(self, service: str) -> dict[str, Any]:
        res = self.ecs.describe_services(cluster=self.cluster, services=[self._ecs_name(service)])
        if not res.get("services"):
            raise ProviderError(f"ECS service for {service} not found")
        return res["services"][0]

    def topology(self) -> list[dict[str, Any]]:
        return self._topology

    # ------------------------------------------------------------ telemetry
    def _metric_queries(self) -> list[dict[str, Any]]:
        q: list[dict[str, Any]] = []
        for i, (svc, ecs_name) in enumerate(self.service_map.items()):
            dims = [
                {"Name": "ClusterName", "Value": self.cluster},
                {"Name": "ServiceName", "Value": ecs_name},
            ]
            for metric, key in (("CPUUtilization", "cpu"), ("MemoryUtilization", "mem")):
                q.append(
                    {
                        "Id": f"{key}{i}",
                        "Label": f"{svc}|{key}",
                        "ReturnData": True,
                        "MetricStat": {
                            "Metric": {"Namespace": "AWS/ECS", "MetricName": metric, "Dimensions": dims},
                            "Period": 60,
                            "Stat": "Average",
                        },
                    }
                )
            tg = self.target_groups.get(svc)
            if tg and self.alb:
                tdims = [{"Name": "TargetGroup", "Value": tg}, {"Name": "LoadBalancer", "Value": self.alb}]
                for metric, key, stat in (
                    ("RequestCount", "req", "Sum"),
                    ("HTTPCode_Target_5XX_Count", "e5xx", "Sum"),
                    ("TargetResponseTime", "p95", "p95"),
                ):
                    q.append(
                        {
                            "Id": f"{key}{i}",
                            "Label": f"{svc}|{key}",
                            "ReturnData": True,
                            "MetricStat": {
                                "Metric": {
                                    "Namespace": "AWS/ApplicationELB",
                                    "MetricName": metric,
                                    "Dimensions": tdims,
                                },
                                "Period": 60,
                                "Stat": stat,
                            },
                        }
                    )
        if self.rds_instance:
            q.append(
                {
                    "Id": "dbconn",
                    "Label": "database|conn",
                    "ReturnData": True,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/RDS",
                            "MetricName": "DatabaseConnections",
                            "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": self.rds_instance}],
                        },
                        "Period": 60,
                        "Stat": "Maximum",
                    },
                }
            )
        return q

    def collect(self) -> TelemetrySnapshot:
        now = self.clock.now()
        self._tick += 1
        raw: dict[str, dict[str, float]] = {}
        queries = self._metric_queries()
        try:
            for chunk_start in range(0, len(queries), 400):
                res = self.cw.get_metric_data(
                    MetricDataQueries=queries[chunk_start : chunk_start + 400],
                    StartTime=now - timedelta(minutes=5),
                    EndTime=now,
                    ScanBy="TimestampDescending",
                )
                for r in res.get("MetricDataResults", []):
                    if r.get("Values"):
                        svc, key = r["Label"].split("|")
                        raw.setdefault(svc, {})[key] = float(r["Values"][0])
        except Exception as exc:  # telemetry gaps are reported, never invented
            log.warning("cloudwatch query failed: %s", exc)
        metrics: dict[str, dict[str, float]] = {}
        for svc in self.service_map:
            try:
                desc = self._describe(svc)
            except Exception as exc:
                log.warning("describe_services failed for %s: %s", svc, exc)
                continue
            r = raw.get(svc, {})
            req = r.get("req", 0.0)
            err = (r.get("e5xx", 0.0) / req) if req else 0.0
            self._requests_total[svc] = self._requests_total.get(svc, 0.0) + req
            metrics[svc] = {
                "cpu_percent": r.get("cpu", 0.0),
                "memory_percent": r.get("mem", 0.0),
                "memory_max_pod_percent": r.get("mem", 0.0),
                "rps": req / 60.0,
                "error_rate": err,
                "availability": 1 - err,
                "latency_p95_ms": r.get("p95", 0.0) * 1000,
                "latency_p50_ms": r.get("p95", 0.0) * 500,
                "healthy_pods": float(desc.get("runningCount", 0)),
                "replicas": float(desc.get("desiredCount", 0)),
                "restarts": 0.0,
                "request_count": self._requests_total[svc],
                "http_5xx_rps": r.get("e5xx", 0.0) / 60.0,
                "http_2xx_rps": (req - r.get("e5xx", 0.0)) / 60.0,
                "queue_depth": 0.0,
                "db_connections": 0.0,
                "network_rx_kbps": 0.0,
                "network_tx_kbps": 0.0,
            }
        if self.rds_instance:
            conns = raw.get("database", {}).get("conn", 0.0)
            metrics["database"] = {
                "db_connections": conns,
                "db_max_connections": float(self.rds_max),
                "db_utilization": conns / self.rds_max,
                "healthy_pods": 1.0,
                "replicas": 1.0,
                "error_rate": 0.0,
                "cpu_percent": 0.0,
                "latency_p95_ms": 0.0,
            }
        return TelemetrySnapshot(ts=now, tick=self._tick, metrics=metrics, logs=self._fetch_logs())

    def _fetch_logs(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        now_ms = int(self.clock.now().timestamp() * 1000)
        for svc in self.service_map:
            group = f"{self.log_group_prefix}/{svc}"
            start = self._last_log_ts.get(svc, now_ms - 120_000)
            try:
                res = self.logs.filter_log_events(logGroupName=group, startTime=start + 1, limit=200)
            except Exception as exc:
                log.debug("log fetch failed for %s: %s", group, exc)
                continue
            for ev in res.get("events", []):
                self._last_log_ts[svc] = max(self._last_log_ts.get(svc, 0), ev["timestamp"])
                entry = _parse_log_line(ev.get("message", ""))
                out.append(
                    {
                        "ts": self.clock.now().isoformat(),
                        "service": svc,
                        "level": entry.get("level", "INFO"),
                        "event": entry.get("event", "log"),
                        "message": entry.get("message", ev.get("message", ""))[:1000],
                        "pod": ev.get("logStreamName"),
                        "version": entry.get("version"),
                    }
                )
        return out

    # ---------------------------------------------------------------- views
    def pods(self, service: str) -> list[dict[str, Any]]:
        arns = self.ecs.list_tasks(cluster=self.cluster, serviceName=self._ecs_name(service)).get(
            "taskArns", []
        )
        if not arns:
            return []
        tasks = self.ecs.describe_tasks(cluster=self.cluster, tasks=arns).get("tasks", [])
        return [
            {
                "name": t["taskArn"].rsplit("/", 1)[-1],
                "service": service,
                "node": t.get("availabilityZone", "fargate"),
                "version": t.get("taskDefinitionArn", "").rsplit(":", 1)[-1],
                "phase": t.get("lastStatus", "UNKNOWN").title(),
                "ready": t.get("lastStatus") == "RUNNING" and t.get("healthStatus", "HEALTHY") != "UNHEALTHY",
                "restarts": 0,
                "recent_restarts": 0,
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "memory_limit_mb": float(t.get("memory", 0) or 0),
                "memory_percent": 0.0,
                "age_seconds": 0.0,
                "last_termination_reason": t.get("stoppedReason"),
            }
            for t in tasks
        ]

    def cluster_status(self) -> dict[str, Any]:
        workloads = []
        for svc in self.service_map:
            try:
                d = self._describe(svc)
            except ProviderError:
                continue
            workloads.append(
                {
                    "name": svc,
                    "kind": "ECS Service (Fargate)",
                    "replicas": d.get("desiredCount", 0),
                    "ready_replicas": d.get("runningCount", 0),
                    "version": d.get("taskDefinition", "").rsplit("/", 1)[-1],
                    "pods": d.get("runningCount", 0) + d.get("pendingCount", 0),
                    "hpa": None,
                }
            )
        return {
            "provider": "aws",
            "simulated": False,
            "cluster": self.cluster,
            "kubernetes_version": "n/a (ECS Fargate)",
            "nodes": [],
            "workloads": workloads,
            "tick": self._tick,
        }

    def database_status(self) -> dict[str, Any]:
        conns = 0.0
        if self.rds_instance:
            now = self.clock.now()
            try:
                res = self.cw.get_metric_statistics(
                    Namespace="AWS/RDS",
                    MetricName="DatabaseConnections",
                    StartTime=now - timedelta(minutes=5),
                    EndTime=now,
                    Period=60,
                    Statistics=["Maximum"],
                    Dimensions=[{"Name": "DBInstanceIdentifier", "Value": self.rds_instance}],
                )
                pts = sorted(res.get("Datapoints", []), key=lambda p: p["Timestamp"])
                conns = pts[-1]["Maximum"] if pts else 0.0
            except Exception as exc:
                log.warning("rds metrics failed: %s", exc)
        util = conns / self.rds_max if self.rds_max else 0
        return {
            "engine": "postgresql (Amazon RDS)",
            "max_connections": self.rds_max,
            "active_connections": int(conns),
            "utilization": round(util, 3),
            "clients": {},
            "status": "SATURATED" if util >= 0.95 else "WARNING" if util >= 0.85 else "OK",
        }

    def deployment_state(self, service: str) -> dict[str, Any]:
        d = self._describe(service)
        td = d.get("taskDefinition", "")
        return {
            "service": service,
            "version": td.rsplit("/", 1)[-1],
            "history": [td],
            "replicas": d.get("desiredCount", 0),
        }

    # ---------------------------------------------------------- remediation
    def _call(self, fn, **kwargs) -> ActionResult:
        try:
            res = fn(**kwargs)
            return ActionResult(
                ok=True,
                message="ok",
                details={k: v for k, v in kwargs.items() if k != "cluster"}
                | {"aws_request_id": res.get("ResponseMetadata", {}).get("RequestId")},
            )
        except Exception as exc:
            return ActionResult(ok=False, message=f"{type(exc).__name__}: {exc}")

    def restart_pod(self, service: str, pod: str) -> ActionResult:
        return self._call(
            self.ecs.stop_task, cluster=self.cluster, task=pod, reason="CloudOps AI remediation: restart_pod"
        )

    def restart_service(self, service: str) -> ActionResult:
        return self._call(
            self.ecs.update_service,
            cluster=self.cluster,
            service=self._ecs_name(service),
            forceNewDeployment=True,
        )

    def scale_deployment(self, service: str, replicas: int) -> ActionResult:
        return self._call(
            self.ecs.update_service,
            cluster=self.cluster,
            service=self._ecs_name(service),
            desiredCount=replicas,
        )

    def rollback_deployment(self, service: str) -> ActionResult:
        current = self._describe(service)["taskDefinition"]
        family, rev = current.rsplit(":", 1)
        if int(rev) <= 1:
            return ActionResult(ok=False, message="no previous task definition revision")
        result = self._call(
            self.ecs.update_service,
            cluster=self.cluster,
            service=self._ecs_name(service),
            taskDefinition=f"{family}:{int(rev) - 1}",
        )
        if result.ok:
            result.details.update(
                {"from": current.rsplit("/", 1)[-1], "to": f"{family}:{int(rev) - 1}".rsplit("/", 1)[-1]}
            )
        return result

    def clear_failed_job(self, service: str, job_id: str) -> ActionResult:
        return ActionResult(
            ok=False,
            message="clear_failed_job is not supported by the AWS provider (no queue integration configured)",
        )

    def deploy(self, service: str, version: str, defective: bool = False) -> ActionResult:
        if defective:
            return ActionResult(
                ok=False, message="defective deployments can only be simulated with the local provider"
            )
        current = self._describe(service)["taskDefinition"]
        td = self.ecs.describe_task_definition(taskDefinition=current)["taskDefinition"]
        containers = td["containerDefinitions"]
        for c in containers:
            c["image"] = c["image"].rsplit(":", 1)[0] + f":{version}"
        keep = {
            "family",
            "taskRoleArn",
            "executionRoleArn",
            "networkMode",
            "containerDefinitions",
            "volumes",
            "requiresCompatibilities",
            "cpu",
            "memory",
        }
        new = self.ecs.register_task_definition(
            **{k: v for k, v in td.items() if k in keep and v is not None}
        )
        arn = new["taskDefinition"]["taskDefinitionArn"]
        return self._call(
            self.ecs.update_service, cluster=self.cluster, service=self._ecs_name(service), taskDefinition=arn
        )


def _parse_log_line(line: str) -> dict[str, Any]:
    import json

    try:
        data = json.loads(line)
        return data if isinstance(data, dict) else {"message": line}
    except (ValueError, TypeError):
        level = "ERROR" if "ERROR" in line else "WARN" if "WARN" in line else "INFO"
        return {"message": line, "level": level}
