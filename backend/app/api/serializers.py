from __future__ import annotations

from typing import Any

from ..models import AIInvestigation, AuditLog, Deployment, Incident, IncidentEvent, Remediation


def _iso(dt):
    return dt.isoformat() if dt else None


def incident_out(i: Incident, full: bool = False) -> dict[str, Any]:
    out = {
        "id": i.id,
        "incident_id": i.incident_key,
        "title": i.title,
        "service": i.service,
        "severity": i.severity,
        "status": i.status,
        "detected_at": _iso(i.detected_at),
        "updated_at": _iso(i.updated_at),
        "resolved_at": _iso(i.resolved_at),
        "closed_at": _iso(i.closed_at),
        "impact_started_at": _iso(i.impact_started_at),
        "probable_root_cause": i.probable_root_cause,
        "root_cause_service": i.root_cause_service,
        "confidence": i.confidence,
        "recommended_action": i.recommended_action,
        "risk": i.risk,
        "remediation_status": i.remediation_status,
        "correlated_services": i.correlated_services or [],
        "resolution_note": i.resolution_note,
        "signal_count": len(i.signals or []),
    }
    if i.resolved_at and i.detected_at:
        out["time_to_resolve_seconds"] = (i.resolved_at - i.detected_at).total_seconds()
    if i.impact_started_at and i.detected_at:
        out["time_to_detect_seconds"] = (i.detected_at - i.impact_started_at).total_seconds()
    if full:
        out.update(signals=i.signals or [], metrics=i.metrics or {}, logs=i.logs or [])
    return out


def event_out(e: IncidentEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "ts": _iso(e.ts),
        "type": e.type,
        "actor": e.actor,
        "message": e.message,
        "data": e.data or {},
    }


def remediation_out(r: Remediation) -> dict[str, Any]:
    return {
        "id": r.id,
        "incident_id": r.incident_id,
        "action": r.action,
        "target_service": r.target_service,
        "parameters": r.parameters,
        "risk": r.risk,
        "status": r.status,
        "rationale": r.rationale,
        "expected_impact": r.expected_impact,
        "ai_confidence": r.ai_confidence,
        "autonomous": r.autonomous,
        "proposed_by": r.proposed_by,
        "proposed_at": _iso(r.proposed_at),
        "decided_by": r.decided_by,
        "decided_at": _iso(r.decided_at),
        "decision_reason": r.decision_reason,
        "executed_at": _iso(r.executed_at),
        "verified_at": _iso(r.verified_at),
        "before_state": r.before_state,
        "after_state": r.after_state,
        "verification": r.verification,
        "execution_output": r.execution_output,
    }


def deployment_out(d: Deployment) -> dict[str, Any]:
    return {
        "id": d.id,
        "service": d.service,
        "version": d.version,
        "previous_version": d.previous_version,
        "kind": d.kind,
        "status": d.status,
        "actor": d.actor,
        "created_at": _iso(d.created_at),
        "notes": d.notes,
    }


def audit_out(a: AuditLog) -> dict[str, Any]:
    return {
        "id": a.id,
        "timestamp": _iso(a.ts),
        "actor": a.actor,
        "role": a.role,
        "action": a.action,
        "target": a.target,
        "reason": a.reason,
        "before_state": a.before_state,
        "after_state": a.after_state,
        "ai_confidence": a.ai_confidence,
        "result": a.result,
        "source_ip": a.source_ip,
        "hash": a.hash,
        "prev_hash": a.prev_hash,
    }


def investigation_out(x: AIInvestigation, full: bool = True) -> dict[str, Any]:
    out = {
        "id": x.id,
        "incident_id": x.incident_id,
        "question": x.question,
        "service": x.service,
        "actor": x.actor,
        "provider": x.provider,
        "root_cause": x.root_cause,
        "confidence": x.confidence,
        "duration_ms": x.duration_ms,
        "created_at": _iso(x.created_at),
        "summary": (x.result or {}).get("summary"),
    }
    if full:
        out["result"] = x.result
    return out
