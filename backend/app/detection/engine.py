from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..observability.store import TelemetryStore
from .anomaly import robust_zscore


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    metric: str
    threshold: float
    for_ticks: int
    severity: Callable[[float], str]
    kinds: tuple[str, ...] = ("http", "worker", "database")
    compare: str = ">"
    unit: str = ""
    derive: Callable[[TelemetryStore, str], float | None] | None = None
    lagging: bool = False  # budget-style indicators are excluded from verification


def _sev(levels: list[tuple[float, str]], default: str) -> Callable[[float], str]:
    def f(v: float) -> str:
        for bound, sev in levels:
            if v >= bound:
                return sev
        return default

    return f


def _restart_delta(store: TelemetryStore, service: str) -> float | None:
    vals = store.series(service, "restarts", 11)
    if len(vals) < 2:
        return None
    return max(0.0, vals[-1] - min(vals))


def _slo_burn(store: TelemetryStore, service: str) -> float | None:
    vals = store.series(service, "error_rate", 30)
    if len(vals) < 10:
        return None
    return (sum(vals) / len(vals)) / 0.001  # burn vs a 99.9% objective


RULES: list[Rule] = [
    Rule(
        "HIGH_CPU", "High CPU utilisation", "cpu_percent", 85.0, 3, _sev([(97, "HIGH")], "MEDIUM"), unit="%"
    ),
    Rule(
        "HIGH_MEMORY",
        "High memory utilisation",
        "memory_max_pod_percent",
        85.0,
        3,
        _sev([(95, "HIGH")], "MEDIUM"),
        ("http", "worker"),
        unit="%",
    ),
    Rule(
        "HIGH_ERROR_RATE",
        "Elevated error rate",
        "error_rate",
        0.05,
        2,
        _sev([(0.2, "CRITICAL")], "HIGH"),
        ("http", "worker"),
    ),
    Rule(
        "HIGH_LATENCY",
        "High p95 latency",
        "latency_p95_ms",
        500.0,
        3,
        _sev([(1500, "HIGH")], "MEDIUM"),
        ("http", "worker"),
        unit="ms",
    ),
    Rule(
        "POD_CRASHLOOP",
        "Repeated pod crashes",
        "restarts",
        3.0,
        1,
        _sev([(6, "HIGH")], "HIGH"),
        ("http", "worker"),
        ">=",
        derive=_restart_delta,
    ),
    Rule(
        "DB_CONNECTION_SATURATION",
        "Database connection saturation",
        "db_utilization",
        0.85,
        2,
        _sev([(0.97, "CRITICAL")], "HIGH"),
        ("database",),
    ),
    Rule(
        "SERVICE_UNAVAILABLE",
        "Service unavailable (no ready pods)",
        "healthy_pods",
        0.0,
        2,
        lambda v: "CRITICAL",
        ("http", "worker"),
        "<=",
    ),
    Rule(
        "QUEUE_BACKLOG",
        "Queue backlog",
        "queue_depth",
        500.0,
        2,
        _sev([(3000, "HIGH")], "MEDIUM"),
        ("worker",),
    ),
    Rule(
        "SLO_FAST_BURN",
        "SLO error-budget fast burn",
        "slo_burn_rate",
        14.4,
        3,
        lambda v: "HIGH",
        ("http",),
        derive=_slo_burn,
        lagging=True,
    ),
]
ANOMALY_METRICS = ("latency_p95_ms", "error_rate", "rps")
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass
class Signal:
    rule: str
    title: str
    service: str
    metric: str
    value: float
    threshold: float
    severity: str
    first_breach_ts: datetime
    tick: int
    kind: str = "rule"  # rule | anomaly
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def message(self) -> str:
        return (
            f"{self.title} on {self.service}: {self.metric}={self.value:.4g} (threshold {self.threshold:.4g})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "title": self.title,
            "service": self.service,
            "metric": self.metric,
            "value": round(self.value, 5),
            "threshold": self.threshold,
            "severity": self.severity,
            "first_breach_ts": self.first_breach_ts.isoformat(),
            "tick": self.tick,
            "kind": self.kind,
            "detail": self.detail,
        }


@dataclass
class _State:
    count: int = 0
    first_ts: datetime | None = None


class DetectionEngine:
    def __init__(self, store: TelemetryStore, kinds: dict[str, str]):
        self.store = store
        self.kinds = kinds
        self._state: dict[tuple[str, str], _State] = {}

    def value_for(self, rule: Rule, service: str) -> float | None:
        if rule.derive:
            return rule.derive(self.store, service)
        latest = self.store.latest(service)
        return latest.get(rule.metric) if latest else None

    @staticmethod
    def breached(rule: Rule, value: float) -> bool:
        if rule.compare == ">":
            return value > rule.threshold
        if rule.compare == ">=":
            return value >= rule.threshold
        return value <= rule.threshold

    def is_rule_clear(self, rule_key: str, service: str) -> bool:
        rule = next((r for r in RULES if r.key == rule_key), None)
        if rule is None:  # anomaly signal: clear when back within 3 robust sigma
            metric = rule_key.removeprefix("ANOMALY_").lower()
            hist = self.store.series(service, metric, 150)[:-5]
            cur = self.store.avg_recent(service, metric, 2)
            return cur is None or abs(robust_zscore([h for h in hist], cur)) < 4
        if rule.derive:
            v = rule.derive(self.store, service)
        else:
            v = self.store.avg_recent(service, rule.metric, 2)
        return v is None or not self.breached(rule, v)

    def evaluate(self, ts: datetime, tick: int) -> list[Signal]:
        signals: list[Signal] = []
        for service, kind in self.kinds.items():
            for rule in RULES:
                if kind not in rule.kinds:
                    continue
                value = self.value_for(rule, service)
                st = self._state.setdefault((service, rule.key), _State())
                if value is not None and self.breached(rule, value):
                    st.count += 1
                    st.first_ts = st.first_ts or ts
                    if st.count >= rule.for_ticks:
                        signals.append(
                            Signal(
                                rule.key,
                                rule.title,
                                service,
                                rule.metric,
                                value,
                                rule.threshold,
                                rule.severity(value),
                                st.first_ts,
                                tick,
                            )
                        )
                else:
                    st.count, st.first_ts = 0, None
            if kind != "database":
                signals.extend(self._anomalies(service, ts, tick))
        for s in signals:
            self.store.mark_alerting(s.service)
        return signals

    def _anomalies(self, service: str, ts: datetime, tick: int) -> list[Signal]:
        out = []
        for metric in ANOMALY_METRICS:
            pts = self.store.points(service, 160)
            if len(pts) < 40:
                continue
            hist = [p.values.get(metric, 0.0) for p in pts[:-3] if not p.alerting]
            recent = [p.values.get(metric, 0.0) for p in pts[-3:]]
            zs = [robust_zscore(hist, v) for v in recent]
            med = sorted(hist)[len(hist) // 2] if hist else 0
            rel = (recent[-1] - med) / med if med else 0
            key = f"ANOMALY_{metric.upper()}"
            st = self._state.setdefault((service, key), _State())
            if all(abs(z) > 6 for z in zs) and abs(rel) > 0.5:
                st.first_ts = st.first_ts or ts
                out.append(
                    Signal(
                        key,
                        f"Anomalous {metric}",
                        service,
                        metric,
                        recent[-1],
                        round(med, 4),
                        "MEDIUM",
                        st.first_ts,
                        tick,
                        kind="anomaly",
                        detail={
                            "zscore": round(zs[-1], 1),
                            "baseline_median": round(med, 4),
                            "relative_change": round(rel, 2),
                        },
                    )
                )
            else:
                st.first_ts = None
        return out
