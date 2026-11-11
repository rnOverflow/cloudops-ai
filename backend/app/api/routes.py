"""REST API. Every mutating endpoint is permission-checked on the server and audited."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..cloud.local.simulation import FAULTS
from ..control_plane import ACTIVE, ControlPlane, RemediationError
from ..core import audit
from ..core.security import DUMMY_HASH, Perm, RoleName, create_token, hash_password, verify_password
from ..detection.engine import RULES
from ..detection.health import THRESHOLDS, evaluate_health
from ..models import (
    AIInvestigation,
    AuditLog,
    Deployment,
    Incident,
    IncidentEvent,
    Remediation,
    Role,
    Runbook,
    SLODefinition,
    SystemSetting,
    User,
)
from ..observability.prom import SERVICE_METRICS
from ..remediation import policy
from ..slo.service import reliability_summary, slo_status
from . import schemas
from .deps import Principal, client_ip, current_user, get_cp, get_db, require
from .serializers import (
    audit_out,
    deployment_out,
    event_out,
    incident_out,
    investigation_out,
    remediation_out,
)

auth = APIRouter(prefix="/api/auth", tags=["auth"])
services = APIRouter(prefix="/api/services", tags=["services"])
incidents = APIRouter(prefix="/api/incidents", tags=["incidents"])
metrics = APIRouter(prefix="/api/metrics", tags=["metrics"])
logs = APIRouter(prefix="/api/logs", tags=["logs"])
deployments = APIRouter(prefix="/api/deployments", tags=["deployments"])
remediations = APIRouter(prefix="/api/remediations", tags=["remediations"])
slo = APIRouter(prefix="/api/slo", tags=["slo"])
runbooks = APIRouter(prefix="/api/runbooks", tags=["runbooks"])
ai = APIRouter(prefix="/api/ai", tags=["ai"])
audit_router = APIRouter(prefix="/api/audit", tags=["audit"])
infra = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])
simulator = APIRouter(prefix="/api/simulator", tags=["simulator"])
settings_router = APIRouter(prefix="/api/settings", tags=["settings"])
system = APIRouter(prefix="/api/system", tags=["system"])

READ = Depends(require(Perm.READ))


def _source(cp: ControlPlane) -> dict[str, Any]:
    return {"provider": cp.provider.name, "simulated": cp.provider.is_simulated}


# ------------------------------------------------------------------- auth
@auth.post("/login", response_model=schemas.TokenResponse)
def login(
    body: schemas.LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
):
    ip = client_ip(request) or "unknown"
    if not request.app.state.limiter.allow(f"login:{ip}", cp.settings.login_rate_limit_per_minute):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts; try again in a minute"
        )
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    ok = verify_password(body.password, user.hashed_password if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit.record(
            db,
            cp.clock,
            actor=body.username[:64],
            role="UNKNOWN",
            action="auth.login",
            result="DENIED",
            reason="invalid credentials",
            source_ip=ip,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    now = cp.clock.now()
    user.last_login_at = now
    # Tokens always use wall-clock time (never the simulation/test clock) so expiry is real.
    token = create_token(
        cp.settings.jwt_secret, user.username, user.role.name, cp.settings.jwt_ttl_minutes, datetime.now(UTC)
    )
    audit.record(db, cp.clock, actor=user.username, role=user.role.name, action="auth.login", source_ip=ip)
    return {
        "access_token": token,
        "expires_in": cp.settings.jwt_ttl_minutes * 60,
        "user": {
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.name,
            "permissions": user.role.permissions,
        },
    }


@auth.get("/me")
def me(user: Principal = Depends(current_user)):
    return {"username": user.username, "role": user.role, "permissions": sorted(user.permissions)}


@auth.get("/roles")
def roles(db: Session = Depends(get_db), _: Principal = READ):
    return [
        {"name": r.name, "description": r.description, "permissions": r.permissions}
        for r in db.execute(select(Role)).scalars()
    ]


@auth.get("/users")
def list_users(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.USERS_MANAGE))):
    return [
        {
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role.name,
            "is_active": u.is_active,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in db.execute(select(User)).scalars()
    ]


@auth.post("/users", status_code=201)
def create_user(
    body: schemas.CreateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    admin: Principal = Depends(require(Perm.USERS_MANAGE)),
):
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none():
        raise HTTPException(409, "username already exists")
    role = db.execute(select(Role).where(Role.name == body.role)).scalar_one()
    db.add(
        User(
            username=body.username,
            full_name=body.full_name,
            hashed_password=hash_password(body.password, cp.settings.bcrypt_rounds),
            role_id=role.id,
            created_at=cp.clock.now(),
        )
    )
    audit.record(
        db,
        cp.clock,
        actor=admin.username,
        role=admin.role,
        action="user.created",
        target=body.username,
        after={"role": body.role},
        source_ip=client_ip(request),
    )
    return {"username": body.username, "role": body.role}


# --------------------------------------------------------------- services
@services.get("")
def list_services(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    out = []
    for s in cp.provider.topology():
        h = evaluate_health(s["name"], cp.store.latest(s["name"]), s["kind"])
        out.append({**s, "health": h, "version": cp.provider.deployment_state(s["name"])["version"]})
    return {**_source(cp), "services": out}


@services.get("/topology")
def topology(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    nodes = [
        {
            "id": s["name"],
            "kind": s["kind"],
            "tier": s["tier"],
            "status": evaluate_health(s["name"], cp.store.latest(s["name"]), s["kind"])["status"],
        }
        for s in cp.provider.topology()
    ]
    edges = [{"from": s, "to": d["name"], "type": d["type"]} for s, ds in cp.deps.items() for d in ds]
    return {**_source(cp), "nodes": nodes, "edges": edges}


@services.get("/{name}")
def get_service(
    name: str, cp: ControlPlane = Depends(get_cp), db: Session = Depends(get_db), _: Principal = READ
):
    if name not in cp.kinds:
        raise HTTPException(404, "service not found")
    topo = next(s for s in cp.provider.topology() if s["name"] == name)
    active = (
        db.execute(select(Incident).where(Incident.service == name, Incident.status.in_(ACTIVE)))
        .scalars()
        .all()
    )
    return {
        **_source(cp),
        **topo,
        "health": evaluate_health(name, cp.store.latest(name), cp.kinds[name]),
        "metrics": cp.store.latest(name),
        "pods": cp.provider.pods(name),
        "deployment": cp.provider.deployment_state(name),
        "dependents": [s for s, ds in cp.deps.items() if any(d["name"] == name for d in ds)],
        "active_incidents": [incident_out(i) for i in active],
    }


# -------------------------------------------------------------- incidents
def _incident(db: Session, key: str) -> Incident:
    inc = db.execute(select(Incident).where(Incident.incident_key == key)).scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "incident not found")
    return inc


@incidents.get("")
def list_incidents(
    db: Session = Depends(get_db),
    _: Principal = READ,
    status_: str | None = Query(None, alias="status"),
    service: str | None = None,
    severity: str | None = None,
    active: bool = False,
    limit: int = Query(100, le=500),
):
    q = select(Incident).order_by(Incident.id.desc()).limit(limit)
    if status_:
        q = q.where(Incident.status == status_.upper())
    if active:
        q = q.where(Incident.status.in_(ACTIVE))
    if service:
        q = q.where(Incident.service == service)
    if severity:
        q = q.where(Incident.severity == severity.upper())
    return [incident_out(i) for i in db.execute(q).scalars()]


@incidents.get("/{key}")
def get_incident(key: str, db: Session = Depends(get_db), _: Principal = READ):
    inc = _incident(db, key)
    rems = (
        db.execute(select(Remediation).where(Remediation.incident_id == inc.id).order_by(Remediation.id))
        .scalars()
        .all()
    )
    invs = (
        db.execute(
            select(AIInvestigation).where(AIInvestigation.incident_id == inc.id).order_by(AIInvestigation.id)
        )
        .scalars()
        .all()
    )
    return {
        **incident_out(inc, full=True),
        "events": [event_out(e) for e in inc.events],
        "remediations": [remediation_out(r) for r in rems],
        "investigations": [investigation_out(x) for x in invs],
    }


@incidents.get("/{key}/events")
def incident_events(key: str, db: Session = Depends(get_db), _: Principal = READ):
    return [event_out(e) for e in _incident(db, key).events]


@incidents.post("/{key}/investigate")
def reinvestigate(
    key: str,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.AI_INVESTIGATE)),
):
    inc = _incident(db, key)
    if inc.status not in ACTIVE:
        raise HTTPException(409, f"incident is {inc.status}")
    if any(
        r.status == "PROPOSED"
        for r in db.execute(select(Remediation).where(Remediation.incident_id == inc.id)).scalars()
    ):
        raise HTTPException(409, "a remediation is already awaiting approval")
    inv = cp.investigate_incident(db, inc.id, actor=user.username)
    return investigation_out(inv) if inv else {}


@incidents.post("/{key}/status")
def set_incident_status(
    key: str,
    body: schemas.IncidentStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.INCIDENT_UPDATE)),
):
    inc = _incident(db, key)
    allowed = {
        "OPEN": {"INVESTIGATING", "RESOLVED"},
        "INVESTIGATING": {"RESOLVED"},
        "MITIGATING": {"RESOLVED"},
        "RESOLVED": {"CLOSED", "INVESTIGATING"},
        "CLOSED": set(),
    }
    if body.status not in allowed.get(inc.status, set()):
        raise HTTPException(409, f"cannot move incident from {inc.status} to {body.status}")
    before = inc.status
    now = cp.clock.now()
    inc.status = body.status
    if body.status == "RESOLVED":
        inc.resolved_at, inc.resolution_note = now, body.note
    if body.status == "CLOSED":
        inc.closed_at = now
    db.add(
        IncidentEvent(incident_id=inc.id, ts=now, type=body.status, actor=user.username, message=body.note)
    )
    inc.updated_at = now
    audit.record(
        db,
        cp.clock,
        actor=user.username,
        role=user.role,
        action="incident.status_changed",
        target=key,
        reason=body.note,
        before={"status": before},
        after={"status": body.status},
        source_ip=client_ip(request),
    )
    return incident_out(inc)


# ---------------------------------------------------------------- metrics
@metrics.get("/catalog")
def metric_catalog(_: Principal = READ):
    return {
        "metrics": SERVICE_METRICS,
        "thresholds": THRESHOLDS,
        "rules": [
            {
                "key": r.key,
                "title": r.title,
                "metric": r.metric,
                "threshold": r.threshold,
                "for_samples": r.for_ticks,
                "compare": r.compare,
                "applies_to": list(r.kinds),
            }
            for r in RULES
        ],
    }


@metrics.get("/overview")
def metrics_overview(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    return {
        **_source(cp),
        "tick": cp.store.tick,
        "ts": cp.store.last_ts.isoformat() if cp.store.last_ts else None,
        "services": {s: cp.store.latest(s) for s in cp.kinds},
    }


@metrics.get("/{service}")
def metric_series(
    service: str,
    cp: ControlPlane = Depends(get_cp),
    _: Principal = READ,
    metric: list[str] = Query(default=["cpu_percent", "latency_p95_ms", "error_rate", "rps"]),
    window: int = Query(150, ge=5, le=1800),
):
    if service not in cp.kinds:
        raise HTTPException(404, "service not found")
    pts = cp.store.points(service, window)
    return {
        **_source(cp),
        "service": service,
        "interval_seconds": cp.settings.tick_seconds,
        "timestamps": [p.ts.isoformat() for p in pts],
        "series": {m: [p.values.get(m) for p in pts] for m in metric},
    }


# ------------------------------------------------------------------- logs
@logs.get("")
def query_logs(
    cp: ControlPlane = Depends(get_cp),
    _: Principal = READ,
    service: str | None = None,
    level: str | None = Query(None, pattern="^(DEBUG|INFO|WARN|ERROR)$"),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(200, ge=1, le=1000),
):
    return {**_source(cp), "logs": cp.store.query_logs(service=service, level=level, contains=q, limit=limit)}


# ------------------------------------------------------------ deployments
@deployments.get("")
def list_deployments(
    db: Session = Depends(get_db),
    _: Principal = READ,
    service: str | None = None,
    limit: int = Query(50, le=500),
):
    q = select(Deployment).order_by(Deployment.id.desc()).limit(limit)
    if service:
        q = q.where(Deployment.service == service)
    return [deployment_out(d) for d in db.execute(q).scalars()]


@deployments.post("", status_code=201)
def create_deployment(
    body: schemas.DeployRequest,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.DEPLOY)),
):
    if body.service not in cp.kinds:
        raise HTTPException(404, "service not found")
    try:
        return deployment_out(
            cp.deploy(db, body.service, body.version, user.username, user.role, notes=body.notes)
        )
    except RemediationError as exc:
        raise HTTPException(409, str(exc)) from exc


# ----------------------------------------------------------- remediations
@remediations.get("")
def list_remediations(
    db: Session = Depends(get_db),
    _: Principal = READ,
    status_: str | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
):
    q = select(Remediation).order_by(Remediation.id.desc()).limit(limit)
    if status_:
        q = q.where(Remediation.status == status_.upper())
    return [remediation_out(r) for r in db.execute(q).scalars()]


@remediations.get("/policy")
def remediation_policy(_: Principal = READ):
    return {
        "actions": {
            a: {
                "base_risk": {
                    "restart_pod": "LOW",
                    "clear_failed_job": "LOW",
                    "restart_service": "MEDIUM",
                    "scale_deployment": "MEDIUM (HIGH if scaling down)",
                    "rollback_deployment": "HIGH",
                }[a]
            }
            for a in policy.ACTIONS
        },
        "autonomous_eligible": ["LOW"],
        "max_replicas": policy.MAX_REPLICAS,
        "blast_radius": {
            "max_executions_per_service": "setting blast_radius_max_executions (default 3)",
            "window_seconds": policy.EXECUTION_WINDOW_SECONDS,
        },
        "approvals": {"LOW": "SRE or ADMIN", "MEDIUM": "SRE or ADMIN", "HIGH": "ADMIN"},
    }


@remediations.get("/{rem_id}")
def get_remediation(rem_id: int, db: Session = Depends(get_db), _: Principal = READ):
    r = db.get(Remediation, rem_id)
    if not r:
        raise HTTPException(404, "remediation not found")
    return remediation_out(r)


@remediations.post("", status_code=201)
def propose_remediation(
    body: schemas.ProposeRemediationRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.REMEDIATION_PROPOSE)),
):
    inc = _incident(db, body.incident_key) if body.incident_key else None
    if (
        inc
        and db.execute(
            select(Remediation).where(Remediation.incident_id == inc.id, Remediation.status == "PROPOSED")
        )
        .scalars()
        .first()
    ):
        raise HTTPException(409, "incident already has a remediation awaiting approval")
    try:
        rem = cp.propose(
            db,
            inc,
            body.action,
            body.target_service,
            body.parameters,
            rationale=body.reason,
            expected_impact="Operator-proposed action",
            confidence=None,
            actor=user.username,
            role=user.role,
        )
    except (policy.PolicyViolation, RemediationError) as exc:
        audit.record(
            db,
            cp.clock,
            actor=user.username,
            role=user.role,
            action="remediation.proposed",
            target=f"{body.target_service}:{body.action}",
            reason=str(exc),
            result="DENIED",
            source_ip=client_ip(request),
        )
        db.commit()
        raise HTTPException(422, str(exc)) from exc
    return remediation_out(rem)


def _decide(
    rem_id: int,
    approve: bool,
    body: schemas.DecisionRequest,
    request: Request,
    db: Session,
    cp: ControlPlane,
    user: Principal,
):
    rem = db.get(Remediation, rem_id)
    if not rem:
        raise HTTPException(404, "remediation not found")
    if approve and rem.risk == "HIGH" and not user.can(Perm.REMEDIATION_APPROVE_HIGH):
        audit.record(
            db,
            cp.clock,
            actor=user.username,
            role=user.role,
            action="remediation.approved",
            target=f"{rem.target_service}:{rem.action}",
            reason="HIGH-risk approval requires ADMIN",
            result="DENIED",
            source_ip=client_ip(request),
        )
        db.commit()
        raise HTTPException(403, "HIGH-risk remediation requires ADMIN approval")
    try:
        cp.decide(
            db,
            rem,
            approve=approve,
            actor=user.username,
            role=user.role,
            reason=body.reason,
            source_ip=client_ip(request),
        )
    except RemediationError as exc:
        raise HTTPException(409, str(exc)) from exc
    return remediation_out(rem)


@remediations.post("/{rem_id}/approve")
def approve(
    rem_id: int,
    body: schemas.DecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.REMEDIATION_APPROVE)),
):
    return _decide(rem_id, True, body, request, db, cp, user)


@remediations.post("/{rem_id}/reject")
def reject(
    rem_id: int,
    body: schemas.DecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.REMEDIATION_APPROVE)),
):
    return _decide(rem_id, False, body, request, db, cp, user)


# -------------------------------------------------------------------- slo
@slo.get("")
def slo_list(db: Session = Depends(get_db), cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    now = cp.clock.now()
    return [
        slo_status(db, s, now)
        for s in db.execute(select(SLODefinition).order_by(SLODefinition.service)).scalars()
    ]


@slo.get("/reliability")
def reliability(
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    _: Principal = READ,
    days: int = Query(30, ge=1, le=90),
):
    now = cp.clock.now()
    summary = reliability_summary(db, now, days)
    summary["availability"] = {
        s.service: slo_status(db, s, now)["attainment"]
        for s in db.execute(select(SLODefinition).where(SLODefinition.sli_type == "availability")).scalars()
    }
    return summary


# --------------------------------------------------------------- runbooks
@runbooks.get("")
def list_runbooks(db: Session = Depends(get_db), _: Principal = READ):
    return [
        {
            "slug": r.slug,
            "title": r.title,
            "severity": r.severity,
            "tags": r.tags,
            "summary": r.summary,
            "actions": r.actions,
        }
        for r in db.execute(select(Runbook).order_by(Runbook.title)).scalars()
    ]


@runbooks.get("/search")
def search_runbooks(
    q: str = Query(min_length=2, max_length=300), cp: ControlPlane = Depends(get_cp), _: Principal = READ
):
    return [{**d.as_dict(), "score": score} for d, score in cp.runbook_index.search(q, 5)]


@runbooks.get("/{slug}")
def get_runbook(slug: str, db: Session = Depends(get_db), _: Principal = READ):
    r = db.execute(select(Runbook).where(Runbook.slug == slug)).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "runbook not found")
    return {
        "slug": r.slug,
        "title": r.title,
        "severity": r.severity,
        "tags": r.tags,
        "symptoms": r.symptoms,
        "actions": r.actions,
        "summary": r.summary,
        "content": r.content,
        "updated_at": r.updated_at.isoformat(),
    }


# --------------------------------------------------------------------- ai
@ai.get("/status")
def ai_status(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    from cloudops_agent.tools import TOOL_SPECS

    return {
        "provider": cp.llm.name if cp.llm.available else "local-analyzer",
        "llm_configured": cp.llm.available,
        "mode": "LLM-assisted (validated)"
        if cp.llm.available
        else "Deterministic evidence analyzer (no LLM configured)",
        "tools": [{"name": t.name, "description": t.description} for t in TOOL_SPECS.values()],
        "guardrails": [
            "read-only allow-listed tools; no shell access",
            "tool arguments schema-validated",
            "facts extracted by code, never by the model",
            "LLM recommendations validated against the remediation allow-list",
            "risk assessed by policy engine, not by the model",
            "non-LOW actions require human approval",
        ],
    }


@ai.post("/investigate")
def investigate(
    body: schemas.InvestigateRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.AI_INVESTIGATE)),
):
    if not request.app.state.limiter.allow(f"ai:{user.username}", cp.settings.ai_rate_limit_per_minute):
        raise HTTPException(429, "AI investigation rate limit exceeded")
    if body.service and body.service not in cp.kinds:
        raise HTTPException(404, "service not found")
    inv = cp.run_investigation(db, body.question, body.service, user.username)
    audit.record(
        db,
        cp.clock,
        actor=user.username,
        role=user.role,
        action="ai.investigation",
        target=inv.service or "fleet",
        reason=body.question,
        ai_confidence=inv.confidence,
        after={"investigation_id": inv.id, "root_cause": inv.root_cause},
        source_ip=client_ip(request),
    )
    return investigation_out(inv)


@ai.get("/investigations")
def list_investigations(db: Session = Depends(get_db), _: Principal = READ, limit: int = Query(30, le=200)):
    return [
        investigation_out(x, full=False)
        for x in db.execute(
            select(AIInvestigation).order_by(AIInvestigation.id.desc()).limit(limit)
        ).scalars()
    ]


@ai.get("/investigations/{inv_id}")
def get_investigation(inv_id: int, db: Session = Depends(get_db), _: Principal = READ):
    x = db.get(AIInvestigation, inv_id)
    if not x:
        raise HTTPException(404, "investigation not found")
    return investigation_out(x)


# ------------------------------------------------------------------ audit
@audit_router.get("")
def list_audit(
    db: Session = Depends(get_db),
    _: Principal = Depends(require(Perm.AUDIT_READ)),
    actor: str | None = None,
    action: str | None = None,
    limit: int = Query(200, le=1000),
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if actor:
        q = q.where(AuditLog.actor == actor)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    return [audit_out(a) for a in db.execute(q).scalars()]


@audit_router.get("/verify")
def verify_audit(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.AUDIT_READ))):
    return audit.verify_chain(db)


# ---------------------------------------------------------- infrastructure
@infra.get("/kubernetes")
def kubernetes(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    return cp.provider.cluster_status()


@infra.get("/pods")
def pods(cp: ControlPlane = Depends(get_cp), _: Principal = READ, service: str | None = None):
    names = [service] if service else list(cp.kinds)
    return {**_source(cp), "pods": [p for n in names for p in cp.provider.pods(n)]}


@infra.get("/database")
def database(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    return {**_source(cp), **cp.provider.database_status()}


@infra.get("/provider")
def provider_info(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    return {
        **_source(cp),
        "supports_fault_injection": cp.provider.supports_fault_injection,
        "tick_seconds": cp.settings.tick_seconds,
        "available_providers": ["local", "aws"],
        "planned_providers": ["azure", "gcp"],
    }


# -------------------------------------------------------------- simulator
@simulator.get("")
def simulator_state(cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    return {
        **_source(cp),
        "enabled": cp.provider.supports_fault_injection,
        "faults": FAULTS,
        "active": cp.provider.active_faults(),
    }


@simulator.post("/inject")
def inject(
    body: schemas.InjectFaultRequest,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.SIMULATOR_RUN)),
):
    if not cp.provider.supports_fault_injection:
        raise HTTPException(400, f"provider '{cp.provider.name}' does not support fault injection")
    if body.service and body.service not in cp.kinds:
        raise HTTPException(404, "service not found")
    with cp.lock:
        if body.fault == "deployment_failure":
            svc = body.service or "payment-service"
            cur = cp.provider.deployment_state(svc)["version"]
            major, minor, _patch = (cur.lstrip("v").split(".") + ["0", "0"])[:3]
            version = f"v{major}.{int(minor) + 1}.0"
            cp.deploy(
                db,
                svc,
                version,
                user.username,
                user.role,
                defective=True,
                notes="SIMULATION: defective release injected by failure simulator",
            )
            info = {"type": "deployment_failure", "service": svc, "version": version}
        else:
            res = cp.provider.inject_fault(body.fault, body.service)
            if not res.ok:
                raise HTTPException(400, res.message)
            info = res.details
    audit.record(
        db,
        cp.clock,
        actor=user.username,
        role=user.role,
        action="simulator.inject",
        target=info.get("service", ""),
        reason=f"SIMULATION: {body.fault}",
        after=info,
        source_ip=client_ip(request),
    )
    return {"injected": info, "simulated": True}


@simulator.post("/clear")
def clear(
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.SIMULATOR_RUN)),
):
    if not cp.provider.supports_fault_injection:
        raise HTTPException(400, "fault injection unsupported")
    before = cp.provider.active_faults()
    with cp.lock:
        cp.provider.clear_faults()
    audit.record(
        db,
        cp.clock,
        actor=user.username,
        role=user.role,
        action="simulator.clear",
        reason="SIMULATION: clear all faults",
        before={"faults": before},
        source_ip=client_ip(request),
    )
    return {"cleared": len(before)}


# --------------------------------------------------------------- settings
@settings_router.get("")
def get_settings_(db: Session = Depends(get_db), cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    values = {
        r.key: {"value": r.value, "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat()}
        for r in db.execute(select(SystemSetting)).scalars()
    }
    return {
        "settings": values,
        "runtime": {
            "provider": cp.provider.name,
            "simulated": cp.provider.is_simulated,
            "tick_seconds": cp.settings.tick_seconds,
            "verify_after_samples": cp.settings.verify_after_ticks,
            "llm_provider": cp.llm.name if cp.llm.available else "none",
            "environment": cp.settings.environment,
            "jwt_ttl_minutes": cp.settings.jwt_ttl_minutes,
        },
    }


@settings_router.put("")
def update_settings(
    body: schemas.SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    cp: ControlPlane = Depends(get_cp),
    user: Principal = Depends(require(Perm.SETTINGS_WRITE)),
):
    changes = body.model_dump(exclude_none=True, exclude={"reason"})
    if not changes:
        raise HTTPException(422, "no settings supplied")
    before, now = {}, cp.clock.now()
    for key, value in changes.items():
        row = db.get(SystemSetting, key)
        before[key] = row.value if row else None
        if row:
            row.value, row.updated_by, row.updated_at = value, user.username, now
        else:
            db.add(SystemSetting(key=key, value=value, updated_by=user.username, updated_at=now))
    audit.record(
        db,
        cp.clock,
        actor=user.username,
        role=user.role,
        action="settings.updated",
        target=",".join(changes),
        reason=body.reason,
        before=before,
        after=changes,
        source_ip=client_ip(request),
    )
    return {"updated": changes}


# ----------------------------------------------------------------- system
@system.get("/status")
def system_status(db: Session = Depends(get_db), cp: ControlPlane = Depends(get_cp), _: Principal = READ):
    now = cp.clock.now()
    active = db.execute(select(func.count(Incident.id)).where(Incident.status.in_(ACTIVE))).scalar()
    pending = db.execute(select(func.count(Remediation.id)).where(Remediation.status == "PROPOSED")).scalar()
    last_hour = db.execute(
        select(func.count(Incident.id)).where(Incident.detected_at >= now - timedelta(hours=1))
    ).scalar()
    healths = [evaluate_health(s, cp.store.latest(s), k) for s, k in cp.kinds.items()]
    return {
        **_source(cp),
        "tick": cp.store.tick,
        "last_sample": cp.store.last_ts.isoformat() if cp.store.last_ts else None,
        "control_loop_error": cp.last_step_error,
        "active_incidents": active,
        "pending_approvals": pending,
        "incidents_last_hour": last_hour,
        "services_total": len(healths),
        "services_healthy": sum(1 for h in healths if h["status"] == "HEALTHY"),
        "autonomous_mode": bool(cp.get_setting(db, "autonomous_mode")),
        "llm_configured": cp.llm.available,
        "active_faults": cp.provider.active_faults(),
    }


ALL_ROUTERS = [
    auth,
    services,
    incidents,
    metrics,
    logs,
    deployments,
    remediations,
    slo,
    runbooks,
    ai,
    audit_router,
    infra,
    simulator,
    settings_router,
    system,
]
_ = RoleName  # re-exported for type checkers
