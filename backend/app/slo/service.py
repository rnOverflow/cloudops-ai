"""SLO / error-budget computation.

Availability SLIs are request-based (good requests / total requests).
Latency SLIs are window-based: a sample is good if its p95 is within the threshold."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import Incident, SLODefinition, SLOMeasurement

DEFAULT_SLOS = [
    ("api-gateway", "Gateway availability", "availability", 0.999, None),
    ("api-gateway", "Gateway p95 latency < 500ms", "latency", 0.99, 500.0),
    ("payment-service", "Payment availability", "availability", 0.999, None),
    ("payment-service", "Payment p95 latency < 500ms", "latency", 0.99, 500.0),
    ("user-service", "User availability", "availability", 0.995, None),
    ("user-service", "User p95 latency < 500ms", "latency", 0.99, 500.0),
    ("notification-service", "Notification availability", "availability", 0.99, None),
]


def seed_slos(db: Session) -> None:
    if db.execute(select(func.count(SLODefinition.id))).scalar():
        return
    for svc, name, sli, target, thr in DEFAULT_SLOS:
        db.add(
            SLODefinition(
                service=svc, name=name, sli_type=sli, target=target, threshold_ms=thr, window_days=30
            )
        )


def record_measurements(
    db: Session,
    ts: datetime,
    metrics: dict[str, dict[str, float]],
    tick_seconds: float,
    slos: list[SLODefinition],
) -> None:
    for slo in slos:
        m = metrics.get(slo.service)
        if not m:
            continue
        if slo.sli_type == "availability":
            total = m.get("rps", 0.0) * tick_seconds
            good = total * (1 - m.get("error_rate", 0.0))
        else:
            total = 1.0
            good = (
                1.0
                if m.get("latency_p95_ms", 0.0) <= (slo.threshold_ms or 500) and m.get("healthy_pods", 1) > 0
                else 0.0
            )
        db.add(SLOMeasurement(slo_id=slo.id, ts=ts, good=good, total=total))


def prune(db: Session, now: datetime, days: int = 30) -> None:
    db.execute(delete(SLOMeasurement).where(SLOMeasurement.ts < now - timedelta(days=days)))


def _ratio(db: Session, slo_id: int, since: datetime) -> tuple[float, float]:
    good, total = db.execute(
        select(
            func.coalesce(func.sum(SLOMeasurement.good), 0.0),
            func.coalesce(func.sum(SLOMeasurement.total), 0.0),
        ).where(SLOMeasurement.slo_id == slo_id, SLOMeasurement.ts >= since)
    ).one()
    return float(good), float(total)


def slo_status(db: Session, slo: SLODefinition, now: datetime) -> dict[str, Any]:
    good, total = _ratio(db, slo.id, now - timedelta(days=slo.window_days))
    attainment = good / total if total else 1.0
    budget = 1 - slo.target
    consumed = ((1 - attainment) / budget) if budget else 0.0
    out = {
        "id": slo.id,
        "service": slo.service,
        "name": slo.name,
        "sli_type": slo.sli_type,
        "target": slo.target,
        "threshold_ms": slo.threshold_ms,
        "window_days": slo.window_days,
        "attainment": round(attainment, 6),
        "error_budget_remaining": round(1 - consumed, 4),
        "error_budget_consumed": round(consumed, 4),
        "total_events": round(total, 1),
        "bad_events": round(total - good, 1),
    }
    for label, delta in (("burn_rate_5m", timedelta(minutes=5)), ("burn_rate_1h", timedelta(hours=1))):
        g, t = _ratio(db, slo.id, now - delta)
        out[label] = round(((1 - g / t) / budget) if t and budget else 0.0, 2)
    out["status"] = (
        "BREACHED"
        if attainment < slo.target
        else "AT_RISK"
        if out["burn_rate_1h"] > 6 or out["error_budget_remaining"] < 0.25
        else "OK"
    )
    return out


def reliability_summary(db: Session, now: datetime, days: int = 30) -> dict[str, Any]:
    since = now - timedelta(days=days)
    incidents = db.execute(select(Incident).where(Incident.detected_at >= since)).scalars().all()
    ttd = [(i.detected_at - i.impact_started_at).total_seconds() for i in incidents if i.impact_started_at]
    ttr = [(i.resolved_at - i.detected_at).total_seconds() for i in incidents if i.resolved_at]
    by_service: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for i in incidents:
        by_service[i.service] = by_service.get(i.service, 0) + 1
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
    span_days = max(
        1 / 24,
        min(days, (now - min((i.detected_at for i in incidents), default=now)).total_seconds() / 86400),
    )
    return {
        "window_days": days,
        "incident_count": len(incidents),
        "incidents_by_service": by_service,
        "incidents_by_severity": by_sev,
        "mttd_seconds": round(sum(ttd) / len(ttd), 1) if ttd else None,
        "mttr_seconds": round(sum(ttr) / len(ttr), 1) if ttr else None,
        "incidents_per_day": round(len(incidents) / span_days, 2) if incidents else 0.0,
        "resolved_count": len(ttr),
        "auto_remediated_count": sum(1 for i in incidents if i.remediation_status == "SUCCEEDED"),
    }
