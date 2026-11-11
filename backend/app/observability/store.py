"""In-memory hot telemetry store (ring buffers).

Long-term storage is Prometheus (metrics) and Loki (logs) in the docker-compose/K8s
deployments; this store backs the control loop, detection, and the agent's tools."""

from __future__ import annotations

import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Point:
    ts: datetime
    tick: int
    values: dict[str, float]
    alerting: bool = False


@dataclass
class TelemetryStore:
    max_points: int = 1800
    max_logs: int = 20000
    _series: dict[str, deque[Point]] = field(default_factory=dict)
    _logs: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=20000))
    _log_seq: int = 0
    tick: int = 0
    last_ts: datetime | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def ingest(
        self, ts: datetime, tick: int, metrics: dict[str, dict[str, float]], logs: list[dict[str, Any]]
    ) -> None:
        with self.lock:
            self.tick, self.last_ts = tick, ts
            for svc, values in metrics.items():
                self._series.setdefault(svc, deque(maxlen=self.max_points)).append(
                    Point(ts, tick, dict(values))
                )
            for entry in logs:
                self._log_seq += 1
                self._logs.append({"id": self._log_seq, **entry})

    def mark_alerting(self, service: str) -> None:
        with self.lock:
            if self._series.get(service):
                self._series[service][-1].alerting = True

    def services(self) -> list[str]:
        return list(self._series.keys())

    def latest(self, service: str) -> dict[str, float]:
        with self.lock:
            s = self._series.get(service)
            return dict(s[-1].values) if s else {}

    def points(self, service: str, window: int) -> list[Point]:
        with self.lock:
            s = self._series.get(service)
            return list(s)[-window:] if s else []

    def series(self, service: str, metric: str, window: int) -> list[float]:
        return [p.values.get(metric, 0.0) for p in self.points(service, window)]

    def avg_recent(self, service: str, metric: str, n: int = 2) -> float | None:
        vals = self.series(service, metric, n)
        return sum(vals) / len(vals) if vals else None

    def baseline(
        self, service: str, metric: str, lookback: int = 300, exclude_recent: int = 10
    ) -> float | None:
        """Median of recent non-alerting points (robust to the incident itself)."""
        with self.lock:
            s = self._series.get(service)
            if not s:
                return None
            pts = list(s)[-lookback:-exclude_recent] if len(s) > exclude_recent + 5 else list(s)
            vals = [p.values.get(metric, 0.0) for p in pts if not p.alerting] or [
                p.values.get(metric, 0.0) for p in pts
            ]
            return statistics.median(vals) if vals else None

    def query_logs(
        self,
        service: str | None = None,
        level: str | None = None,
        contains: str | None = None,
        limit: int = 200,
        since_id: int = 0,
    ) -> list[dict[str, Any]]:
        levels = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
        min_level = levels.get(level or "DEBUG", 0)
        out: list[dict[str, Any]] = []
        with self.lock:
            for entry in reversed(self._logs):
                if entry["id"] <= since_id:
                    break
                if service and entry.get("service") != service:
                    continue
                if levels.get(entry.get("level", "INFO"), 1) < min_level:
                    continue
                if contains and contains.lower() not in entry.get("message", "").lower():
                    continue
                out.append(entry)
                if len(out) >= limit:
                    break
        return out
