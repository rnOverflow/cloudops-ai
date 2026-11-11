"""The CloudOps AI control plane.

One `step()` is one control-loop iteration:

    collect telemetry -> store/export -> detect -> correlate into incidents
    -> investigate new incidents (AI agent) -> propose remediation (policy)
    -> [human approval | autonomous for LOW risk] -> execute -> verify -> resolve
    -> record SLO measurements

The background loop calls step() every TICK_SECONDS; tests call it directly with a
ManualClock so the full workflow is deterministic.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cloudops_agent import Investigator
from cloudops_agent.providers import NullProvider, OpenAICompatibleProvider
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .agent_tools import PlatformToolBackend
from .cloud.base import ActionResult, CloudProvider
from .core import audit
from .core.clock import Clock
from .core.config import Settings
from .core.security import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS, RoleName, hash_password
from .detection.engine import RULES, SEVERITY_ORDER, DetectionEngine, Signal
from .detection.health import evaluate_health
from .models import (
    AIInvestigation,
    Deployment,
    Incident,
    IncidentEvent,
    Remediation,
    Role,
    Runbook,
    Service,
    SLODefinition,
    SystemSetting,
    User,
)
from .observability import prom
from .observability.store import TelemetryStore
from .remediation import policy
from .runbooks.retrieval import BM25Index, RunbookDoc, load_runbooks
from .slo import service as slo_service

log = logging.getLogger("cloudops.control_plane")

ACTIVE = ("OPEN", "INVESTIGATING", "MITIGATING")
DEFAULT_SETTINGS = {
    "autonomous_mode": False,
    "autonomous_min_confidence": 0.7,
    "max_remediations_per_incident": 3,
    "blast_radius_max_executions": 3,  # per service per policy.EXECUTION_WINDOW_SECONDS
}
AUTOPILOT = "autopilot"
LAGGING_RULES = {r.key for r in RULES if r.lagging}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class RemediationError(ValueError):
    pass


class ControlPlane:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        session_factory: sessionmaker[Session],
        provider: CloudProvider,
    ):
        self.settings = settings
        self.clock = clock
        self.sf = session_factory
        self.provider = provider
        self.store = TelemetryStore()
        self.lock = threading.RLock()
        topo = provider.topology()
        self.kinds = {s["name"]: s["kind"] for s in topo}
        self.tiers = {s["name"]: s["tier"] for s in topo}
        self.deps = {s["name"]: s["dependencies"] for s in topo}
        self.detector = DetectionEngine(self.store, self.kinds)
        self.runbook_index = BM25Index([])
        self.llm = self._make_llm()
        self._slo_cache: list[SLODefinition] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_step_error: str | None = None

    # ------------------------------------------------------------- bootstrap
    def _make_llm(self):
        if self.settings.llm_provider == "openai" and (
            self.settings.openai_api_key or "localhost" in self.settings.openai_base_url
        ):
            return OpenAICompatibleProvider(
                self.settings.openai_api_key, self.settings.openai_model, self.settings.openai_base_url
            )
        return NullProvider()

    def runbooks_dir(self) -> Path:
        if self.settings.runbooks_dir:
            return Path(self.settings.runbooks_dir)
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "runbooks").is_dir() and any((parent / "runbooks").glob("*.md")):
                return parent / "runbooks"
        return Path("/app/runbooks")

    def bootstrap(self) -> None:
        with self.sf() as db:
            now = self.clock.now()
            for role in RoleName:
                existing = db.execute(select(Role).where(Role.name == role.value)).scalar_one_or_none()
                perms = [p.value for p in ROLE_PERMISSIONS[role]]
                if existing:
                    existing.permissions = perms
                else:
                    db.add(Role(name=role.value, description=ROLE_DESCRIPTIONS[role], permissions=perms))
            db.flush()
            if self.settings.seed_demo_users:
                for username, role, pw in (
                    ("admin", "ADMIN", self.settings.seed_admin_password),
                    ("sre", "SRE", self.settings.seed_sre_password),
                    ("developer", "DEVELOPER", self.settings.seed_developer_password),
                    ("viewer", "VIEWER", self.settings.seed_viewer_password),
                ):
                    if (
                        not pw
                        or db.execute(select(User).where(User.username == username)).scalar_one_or_none()
                    ):
                        continue
                    role_row = db.execute(select(Role).where(Role.name == role)).scalar_one()
                    db.add(
                        User(
                            username=username,
                            full_name=f"Demo {role.title()}",
                            hashed_password=hash_password(pw, self.settings.bcrypt_rounds),
                            role_id=role_row.id,
                            created_at=now,
                        )
                    )
            for s in self.provider.topology():
                row = db.execute(select(Service).where(Service.name == s["name"])).scalar_one_or_none()
                if row is None:
                    db.add(
                        Service(
                            name=s["name"],
                            tier=s["tier"],
                            owner_team=s["owner_team"],
                            description=s["description"],
                            kind=s["kind"],
                            dependencies=s["dependencies"],
                            provider=self.provider.name,
                        )
                    )
                else:
                    row.dependencies, row.kind, row.provider = (
                        s["dependencies"],
                        s["kind"],
                        self.provider.name,
                    )
            slo_service.seed_slos(db)
            for key, value in DEFAULT_SETTINGS.items():
                if db.get(SystemSetting, key) is None:
                    db.add(SystemSetting(key=key, value=value, updated_by="system", updated_at=now))
            self._sync_runbooks(db)
            db.commit()
            self._slo_cache = list(db.execute(select(SLODefinition)).scalars())
            for slo in self._slo_cache:
                db.expunge(slo)
            # Seed the deployment ledger with the currently running versions (observed from provider).
            if not db.execute(select(func.count(Deployment.id))).scalar():
                for name in self.kinds:
                    st = self.provider.deployment_state(name)
                    db.add(
                        Deployment(
                            service=name,
                            version=st["version"],
                            previous_version=None,
                            kind="BASELINE",
                            status="SUCCEEDED",
                            actor="bootstrap",
                            created_at=now,
                            notes="Initial version observed at platform start",
                        )
                    )
                db.commit()

    def _sync_runbooks(self, db: Session) -> None:
        directory = self.runbooks_dir()
        docs = load_runbooks(directory) if directory.is_dir() else []
        now = self.clock.now()
        for d in docs:
            row = db.execute(select(Runbook).where(Runbook.slug == d.slug)).scalar_one_or_none()
            fields = dict(
                title=d.title,
                tags=d.tags,
                symptoms=d.symptoms,
                actions=d.actions,
                severity=d.severity,
                summary=d.summary,
                content=d.content,
            )
            if row is None:
                db.add(Runbook(slug=d.slug, updated_at=now, **fields))
            else:
                for k, v in fields.items():
                    setattr(row, k, v)
                row.updated_at = now
        db.flush()
        rows = db.execute(select(Runbook)).scalars().all()
        self.runbook_index = BM25Index(
            [
                RunbookDoc(r.slug, r.title, r.severity, r.tags, r.symptoms, r.actions, r.summary, r.content)
                for r in rows
            ]
        )

    # -------------------------------------------------------------- settings
    def get_setting(self, db: Session, key: str) -> Any:
        row = db.get(SystemSetting, key)
        return row.value if row else DEFAULT_SETTINGS.get(key)

    # ---------------------------------------------------------- control loop
    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="control-loop", daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.step()
                self.last_step_error = None
            except Exception as exc:  # keep the loop alive; surface via /api/system/status
                self.last_step_error = f"{type(exc).__name__}: {exc}"
                log.exception("control loop step failed")
            self._stop.wait(max(0.05, self.settings.tick_seconds - (time.monotonic() - started)))

    def step(self) -> dict[str, Any]:
        with self.lock, prom.CONTROL_LOOP_SECONDS.time():
            snap = self.provider.collect()
            self.store.ingest(snap.ts, snap.tick, snap.metrics, snap.logs)
            prom.export_snapshot(self.provider.name, snap.metrics)
            signals = self.detector.evaluate(snap.ts, snap.tick)
            for s in signals:
                prom.ALERT_SIGNALS.labels(service=s.service, rule=s.rule).inc()
            with self.sf() as db:
                created = self._process_signals(db, signals, snap.ts)
                db.commit()
                for inc_id in created:
                    self.investigate_incident(db, inc_id, actor="ai-agent")
                    db.commit()
                self._verify_due(db, snap.tick)
                self._auto_resolve(db, signals)
                slo_service.record_measurements(
                    db, snap.ts, snap.metrics, self.settings.tick_seconds, self._slo_cache
                )
                if snap.tick % 300 == 0:
                    slo_service.prune(db, snap.ts)
                prom.ACTIVE_INCIDENTS.set(
                    db.execute(select(func.count(Incident.id)).where(Incident.status.in_(ACTIVE))).scalar()
                    or 0
                )
                db.commit()
            return {
                "tick": snap.tick,
                "signals": [s.as_dict() for s in signals],
                "incidents_created": created,
            }

    # -------------------------------------------------------------- incidents
    def _event(
        self,
        db: Session,
        inc: Incident,
        type_: str,
        message: str,
        actor: str = "system",
        data: dict | None = None,
    ) -> None:
        now = self.clock.now()
        db.add(
            IncidentEvent(
                incident_id=inc.id, ts=now, type=type_, actor=actor, message=message, data=data or {}
            )
        )
        inc.updated_at = now

    def _active_incident(self, db: Session, service: str) -> Incident | None:
        return (
            db.execute(
                select(Incident)
                .where(Incident.service == service, Incident.status.in_(ACTIVE))
                .order_by(Incident.id.desc())
            )
            .scalars()
            .first()
        )

    def _levels(self) -> dict[str, int]:
        """Topological level: leaves (no sync deps) are 0; callers are 1 + max(level of deps)."""
        memo: dict[str, int] = {}

        def lvl(n: str, seen: frozenset[str] = frozenset()) -> int:
            if n in memo:
                return memo[n]
            deps = [d["name"] for d in self.deps.get(n, []) if d["type"] != "async" and d["name"] not in seen]
            memo[n] = 0 if not deps else 1 + max(lvl(d, seen | {n}) for d in deps)
            return memo[n]

        return {n: lvl(n) for n in self.kinds}

    def transitive_deps(self, service: str) -> set[str]:
        out: set[str] = set()
        stack = [service]
        while stack:
            for d in self.deps.get(stack.pop(), []):
                if d["type"] != "async" and d["name"] not in out:
                    out.add(d["name"])
                    stack.append(d["name"])
        return out

    def _related_incident(self, db: Session, service: str) -> Incident | None:
        """An active incident on a (transitive) dependency of `service`, directly or via its correlated services."""
        deps = self.transitive_deps(service)
        for inc in db.execute(
            select(Incident).where(Incident.status.in_(ACTIVE)).order_by(Incident.id)
        ).scalars():
            if inc.service in deps or deps & set(inc.correlated_services or []):
                return inc
        return None

    def _attach(self, db: Session, inc: Incident, sig: Signal) -> None:
        if sig.service != inc.service and sig.service not in (inc.correlated_services or []):
            inc.correlated_services = [*(inc.correlated_services or []), sig.service]
            self._event(
                db,
                inc,
                "CORRELATED",
                f"{sig.service} symptoms attached (depends on {inc.service}): {sig.message}",
                data={"service": sig.service, "rule": sig.rule},
            )
        existing = {(s["service"], s["rule"]) for s in inc.signals or []}
        if (sig.service, sig.rule) not in existing:
            inc.signals = [*(inc.signals or []), sig.as_dict()]
            self._event(db, inc, "SIGNAL_ADDED", sig.message, data=sig.as_dict())
            if SEVERITY_ORDER[sig.severity] > SEVERITY_ORDER[inc.severity] and sig.kind == "rule":
                self._event(db, inc, "SEVERITY_CHANGED", f"Severity {inc.severity} -> {sig.severity}")
                inc.severity = sig.severity

    def _merge_upstream(self, db: Session, root: Incident) -> None:
        """A dependency just opened an incident: fold in recently opened incidents of its callers that are
        still awaiting action (their symptoms are downstream effects of this root)."""
        for other in (
            db.execute(select(Incident).where(Incident.status.in_(ACTIVE), Incident.id != root.id))
            .scalars()
            .all()
        ):
            if root.service not in self.transitive_deps(other.service):
                continue
            if other.remediation_status in ("EXECUTING", "VERIFYING", "APPROVED"):
                continue
            for sig in other.signals or []:
                if (sig["service"], sig["rule"]) not in {
                    (s["service"], s["rule"]) for s in root.signals or []
                }:
                    root.signals = [*(root.signals or []), sig]
            root.correlated_services = list(
                dict.fromkeys(
                    [*(root.correlated_services or []), other.service, *(other.correlated_services or [])]
                )
            )
            for rem in db.execute(
                select(Remediation).where(
                    Remediation.incident_id == other.id, Remediation.status == "PROPOSED"
                )
            ).scalars():
                rem.status, rem.decided_by, rem.decided_at = "REJECTED", "system", self.clock.now()
                rem.decision_reason = f"Superseded: incident merged into {root.incident_key}"
            other.status, other.closed_at, other.remediation_status = "CLOSED", self.clock.now(), "SUPERSEDED"
            other.resolution_note = (
                f"Merged into {root.incident_key}: symptoms are downstream of {root.service}."
            )
            self._event(db, other, "MERGED", other.resolution_note)
            self._event(
                db, root, "MERGED", f"Absorbed {other.incident_key} ({other.service}) as downstream impact."
            )

    def _process_signals(self, db: Session, signals: list[Signal], ts: datetime) -> list[int]:
        created: list[int] = []
        level = self._levels()
        # Leaf services first, so root causes open incidents before their callers' symptoms.
        for sig in sorted(signals, key=lambda s: (level.get(s.service, 0), -SEVERITY_ORDER[s.severity])):
            inc = self._active_incident(db, sig.service) or self._related_incident(db, sig.service)
            if inc is not None:
                self._attach(db, inc, sig)
                continue
            if (sig.kind == "anomaly" or sig.rule in LAGGING_RULES) and not any(
                s.service == sig.service and s.kind == "rule" and s.rule not in LAGGING_RULES for s in signals
            ):
                # Anomalies and lagging budget signals corroborate; they never open an incident alone (noise control).
                continue
            now = self.clock.now()
            inc = Incident(
                incident_key="PENDING",
                title=f"{sig.title} on {sig.service}",
                service=sig.service,
                severity=sig.severity,
                status="OPEN",
                detected_at=now,
                updated_at=now,
                impact_started_at=sig.first_breach_ts,
                signals=[sig.as_dict()],
                metrics=self.store.latest(sig.service),
                logs=self.store.query_logs(sig.service, level="WARN", limit=40),
                correlated_services=[],
                remediation_status="NONE",
            )
            db.add(inc)
            db.flush()
            inc.incident_key = f"INC-{inc.id:04d}"
            self._event(db, inc, "DETECTED", sig.message, data=sig.as_dict())
            audit.record(
                db,
                self.clock,
                actor="detection-engine",
                role="SYSTEM",
                action="incident.created",
                target=inc.incident_key,
                reason=sig.message,
                after={"severity": inc.severity, "service": inc.service},
            )
            prom.INCIDENTS_OPENED.labels(service=inc.service, severity=inc.severity).inc()
            self._merge_upstream(db, inc)
            created.append(inc.id)
        return created

    def _auto_resolve(self, db: Session, signals: list[Signal]) -> None:
        for inc in db.execute(select(Incident).where(Incident.status.in_(ACTIVE))).scalars():
            if inc.remediation_status in ("EXECUTING", "VERIFYING"):
                continue
            rule_sigs = [
                s for s in inc.signals or [] if s.get("kind") == "rule" and s["rule"] not in LAGGING_RULES
            ]
            if rule_sigs and all(self.detector.is_rule_clear(s["rule"], s["service"]) for s in rule_sigs):
                inc.clear_ticks = (inc.clear_ticks or 0) + 1
                if inc.clear_ticks >= 10:
                    self._resolve(
                        db,
                        inc,
                        "Signals returned to normal without remediation (self-recovered or fault removed).",
                        actor="system",
                    )
            else:
                inc.clear_ticks = 0

    def _resolve(self, db: Session, inc: Incident, note: str, actor: str) -> None:
        inc.status = "RESOLVED"
        inc.resolved_at = self.clock.now()
        inc.resolution_note = note
        self._event(db, inc, "RESOLVED", note, actor=actor)
        prom.INCIDENTS_RESOLVED.labels(service=inc.service).inc()
        audit.record(
            db,
            self.clock,
            actor=actor,
            role="SYSTEM" if actor in ("system", AUTOPILOT) else "SRE",
            action="incident.resolved",
            target=inc.incident_key,
            reason=note,
            before={"status": "MITIGATING"},
            after={"status": "RESOLVED"},
        )

    # ---------------------------------------------------------- investigation
    def make_investigator(self, db: Session) -> Investigator:
        return Investigator(PlatformToolBackend(self, db), set(self.kinds), provider=self.llm)

    def run_investigation(
        self, db: Session, question: str, service: str | None, actor: str, incident_id: int | None = None
    ) -> AIInvestigation:
        started = time.perf_counter()
        result = self.make_investigator(db).investigate(question, service)
        duration = (time.perf_counter() - started) * 1000
        payload = result.model_dump(mode="json")
        for call in payload["tool_calls"]:  # keep stored evidence compact
            call["output"] = _truncate(call.get("output"))
        row = AIInvestigation(
            incident_id=incident_id,
            question=question,
            service=result.service,
            actor=actor,
            provider=result.provider,
            root_cause=result.root_cause,
            confidence=result.confidence,
            duration_ms=round(duration, 1),
            result=payload,
            created_at=self.clock.now(),
        )
        db.add(row)
        db.flush()
        return row

    def investigate_incident(self, db: Session, incident_id: int, actor: str) -> AIInvestigation | None:
        inc = db.get(Incident, incident_id)
        if inc is None or inc.status not in ACTIVE:
            return None
        inc.status = "INVESTIGATING"
        self._event(
            db,
            inc,
            "INVESTIGATION_STARTED",
            f"AI investigation started ({'LLM: ' + self.llm.name if self.llm.available else 'local analyzer'})",
            actor=actor,
        )
        signals_text = "; ".join(s["title"] for s in inc.signals or [])
        inv = self.run_investigation(
            db, f"Why is {inc.service} unhealthy? Active signals: {signals_text}", inc.service, actor, inc.id
        )
        res = inv.result
        facts = sum(1 for f in res["findings"] if f["kind"] == "OBSERVED_FACT")
        inferences = len(res["findings"]) - facts
        self._event(
            db,
            inc,
            "EVIDENCE_COLLECTED",
            f"{len(res['tool_calls'])} tool calls; {facts} observed facts, {inferences} inferences",
            actor="ai-agent",
            data={"investigation_id": inv.id},
        )
        inc.probable_root_cause = res["root_cause"]
        inc.root_cause_service = res["root_cause_service"]
        inc.confidence = res["confidence"]
        if res["root_cause"]:
            self._event(
                db,
                inc,
                "ROOT_CAUSE_IDENTIFIED",
                f"{res['root_cause']} in {res['root_cause_service']} (confidence {res['confidence']:.0%})",
                actor="ai-agent",
                data={"investigation_id": inv.id},
            )
        if res["runbooks"]:
            self._event(
                db,
                inc,
                "RUNBOOK_RETRIEVED",
                ", ".join(r["title"] for r in res["runbooks"]),
                actor="ai-agent",
                data={"runbooks": [r["slug"] for r in res["runbooks"]]},
            )
        rec = res.get("recommendation")
        audit.record(
            db,
            self.clock,
            actor="ai-agent",
            role="SYSTEM",
            action="ai.investigation",
            target=inc.incident_key,
            reason=res["summary"],
            ai_confidence=res["confidence"],
            after={"investigation_id": inv.id, "provider": inv.provider},
        )
        if not rec:
            self._event(
                db,
                inc,
                "NOTE",
                "No safe automated remediation identified; human investigation required.",
                actor="ai-agent",
            )
            return inv
        prior = db.execute(select(Remediation).where(Remediation.incident_id == inc.id)).scalars().all()
        if any(
            r.action == rec["action"]
            and r.parameters == rec["parameters"]
            and r.target_service == rec["target_service"]
            and r.status == "FAILED"
            for r in prior
        ):
            self._event(
                db,
                inc,
                "NOTE",
                f"Recommended {rec['action']} already failed for this incident; escalating to a human.",
                actor="ai-agent",
            )
            return inv
        if len(prior) >= int(self.get_setting(db, "max_remediations_per_incident")):
            self._event(
                db, inc, "NOTE", "Remediation attempt limit reached; escalating to a human.", actor="ai-agent"
            )
            return inv
        try:
            rem = self.propose(
                db,
                inc,
                rec["action"],
                rec["target_service"],
                rec["parameters"],
                rationale=rec["rationale"],
                expected_impact=rec["expected_impact"],
                confidence=res["confidence"],
                actor="ai-agent",
                role="SYSTEM",
            )
        except (policy.PolicyViolation, RemediationError) as exc:
            self._event(db, inc, "NOTE", f"Recommendation rejected by policy: {exc}", actor="policy-engine")
            return inv
        self._maybe_autonomous(db, inc, rem)
        return inv

    # ------------------------------------------------------------ remediation
    def _current_replicas(self, service: str) -> int:
        return int(self.provider.deployment_state(service)["replicas"])

    def propose(
        self,
        db: Session,
        inc: Incident | None,
        action: str,
        target: str,
        params: dict[str, Any],
        *,
        rationale: str,
        expected_impact: str,
        confidence: float | None,
        actor: str,
        role: str,
    ) -> Remediation:
        if target not in self.kinds:
            raise RemediationError(f"unknown service {target}")
        if action not in policy.ACTIONS:
            raise policy.PolicyViolation(f"action '{action}' is not permitted")
        params = policy.validate_params(action, params)
        risk = policy.assess(
            action, target, params, self._current_replicas(target), self.tiers.get(target, "tier-2")
        )
        if action == "restart_pod" and params["pod"] not in {p["name"] for p in self.provider.pods(target)}:
            raise RemediationError(f"pod {params['pod']} does not exist in {target}")
        now = self.clock.now()
        rem = Remediation(
            incident_id=inc.id if inc else None,
            action=action,
            target_service=target,
            parameters=params,
            risk=risk.risk,
            status="PROPOSED",
            rationale=rationale,
            expected_impact=expected_impact,
            ai_confidence=confidence,
            proposed_by=actor,
            proposed_at=now,
            verification={"risk_reasons": risk.reasons},
        )
        db.add(rem)
        db.flush()
        if inc:
            inc.recommended_action = {
                "remediation_id": rem.id,
                "action": action,
                "target_service": target,
                "parameters": params,
                "rationale": rationale,
                "expected_impact": expected_impact,
            }
            inc.risk = risk.risk
            inc.remediation_status = "PENDING_APPROVAL"
            self._event(
                db,
                inc,
                "RECOMMENDATION",
                f"{action} on {target} {params or ''} — {risk.risk} risk ({'; '.join(risk.reasons)})",
                actor=actor,
                data={"remediation_id": rem.id},
            )
            self._event(
                db,
                inc,
                "APPROVAL_REQUESTED",
                f"Awaiting approval for remediation #{rem.id}",
                actor="policy-engine",
            )
        audit.record(
            db,
            self.clock,
            actor=actor,
            role=role,
            action="remediation.proposed",
            target=f"{target}:{action}",
            reason=rationale,
            after={"remediation_id": rem.id, "params": params, "risk": risk.risk},
            ai_confidence=confidence,
        )
        return rem

    def _maybe_autonomous(self, db: Session, inc: Incident, rem: Remediation) -> None:
        if not self.get_setting(db, "autonomous_mode"):
            return
        min_conf = float(self.get_setting(db, "autonomous_min_confidence"))
        if rem.risk != "LOW":
            self._event(
                db,
                inc,
                "NOTE",
                f"Autonomous mode on, but {rem.risk}-risk actions require human approval.",
                actor="policy-engine",
            )
            return
        if (rem.ai_confidence or 0) < min_conf:
            self._event(
                db,
                inc,
                "NOTE",
                f"Autonomous mode on, but confidence {rem.ai_confidence:.0%} < {min_conf:.0%}; human approval required.",
                actor="policy-engine",
            )
            return
        self.decide(
            db,
            rem,
            approve=True,
            actor=AUTOPILOT,
            role="SYSTEM",
            reason=f"Autonomous policy: LOW risk, confidence {rem.ai_confidence:.0%}",
            autonomous=True,
        )

    def decide(
        self,
        db: Session,
        rem: Remediation,
        *,
        approve: bool,
        actor: str,
        role: str,
        reason: str,
        autonomous: bool = False,
        source_ip: str | None = None,
    ) -> Remediation:
        with self.lock:
            if rem.status != "PROPOSED":
                raise RemediationError(f"remediation is {rem.status}, not PROPOSED")
            inc = db.get(Incident, rem.incident_id) if rem.incident_id else None
            now = self.clock.now()
            rem.decided_by, rem.decided_at, rem.decision_reason, rem.autonomous = (
                actor,
                now,
                reason,
                autonomous,
            )
            if not approve:
                rem.status = "REJECTED"
                if inc:
                    inc.remediation_status = "REJECTED"
                    self._event(
                        db,
                        inc,
                        "REJECTED",
                        f"Remediation #{rem.id} rejected by {actor}: {reason}",
                        actor=actor,
                    )
                audit.record(
                    db,
                    self.clock,
                    actor=actor,
                    role=role,
                    action="remediation.rejected",
                    target=f"{rem.target_service}:{rem.action}",
                    reason=reason,
                    ai_confidence=rem.ai_confidence,
                    result="REJECTED",
                    source_ip=source_ip,
                )
                return rem
            rem.status = "APPROVED"
            if inc:
                self._event(
                    db,
                    inc,
                    "APPROVED",
                    f"Remediation #{rem.id} approved by {actor}"
                    + (" (autonomous)" if autonomous else "")
                    + f": {reason}",
                    actor=actor,
                )
            audit.record(
                db,
                self.clock,
                actor=actor,
                role=role,
                action="remediation.approved",
                target=f"{rem.target_service}:{rem.action}",
                reason=reason,
                ai_confidence=rem.ai_confidence,
                source_ip=source_ip,
            )
            self._execute(db, rem, inc, actor, role)
            return rem

    def _snapshot(self, services: list[str]) -> dict[str, Any]:
        keys = (
            "cpu_percent",
            "memory_max_pod_percent",
            "latency_p95_ms",
            "error_rate",
            "rps",
            "healthy_pods",
            "replicas",
            "db_connections",
            "db_utilization",
            "queue_depth",
            "restarts",
        )
        out: dict[str, Any] = {"tick": self.store.tick}
        for s in dict.fromkeys(services):
            m = self.store.latest(s)
            out[s] = {k: round(m[k], 4) for k in keys if k in m}
            out[s]["status"] = evaluate_health(s, m, self.kinds.get(s, "http"))["status"]
        return out

    def _execute(self, db: Session, rem: Remediation, inc: Incident | None, actor: str, role: str) -> None:
        recent = (
            db.execute(
                select(func.count(Remediation.id)).where(
                    Remediation.target_service == rem.target_service,
                    Remediation.executed_at.is_not(None),
                    Remediation.executed_at
                    >= datetime.fromtimestamp(
                        self.clock.now().timestamp() - policy.EXECUTION_WINDOW_SECONDS, UTC
                    ),
                )
            ).scalar()
            or 0
        )
        in_flight = (
            db.execute(
                select(func.count(Remediation.id)).where(
                    Remediation.target_service == rem.target_service,
                    Remediation.status.in_(("EXECUTING", "VERIFYING")),
                )
            ).scalar()
            or 0
        )
        limit = int(self.get_setting(db, "blast_radius_max_executions"))
        if recent >= limit or in_flight:
            rem.status = "FAILED"
            rem.execution_output = {
                "error": "blocked by blast-radius guard"
                if in_flight == 0
                else "another remediation is in progress on this service"
            }
            if inc:
                inc.remediation_status = "FAILED"
                self._event(
                    db,
                    inc,
                    "NOTE",
                    f"Execution blocked: {rem.execution_output['error']}",
                    actor="policy-engine",
                )
            audit.record(
                db,
                self.clock,
                actor=actor,
                role=role,
                action="remediation.blocked",
                target=f"{rem.target_service}:{rem.action}",
                reason=rem.execution_output["error"],
                result="BLOCKED",
            )
            return
        services = [rem.target_service] + ([inc.service] + list(inc.correlated_services or []) if inc else [])
        rem.before_state = self._snapshot(services)
        if rem.action == "rollback_deployment":
            rem.before_state["deployment"] = self.provider.deployment_state(rem.target_service)
        rem.status = "EXECUTING"
        if inc:
            inc.status = "MITIGATING"
            inc.remediation_status = "EXECUTING"
            self._event(
                db,
                inc,
                "REMEDIATION_STARTED",
                f"Executing {rem.action} on {rem.target_service} {rem.parameters or ''}",
                actor=actor,
            )
        result = self._dispatch(rem)
        rem.executed_at = self.clock.now()
        rem.execution_output = {"ok": result.ok, "message": result.message, **result.details}
        if not result.ok:
            rem.status = "FAILED"
            prom.REMEDIATIONS.labels(action=rem.action, result="execution_failed").inc()
            if inc:
                inc.status = "INVESTIGATING"
                inc.remediation_status = "FAILED"
                self._event(
                    db, inc, "REMEDIATION_FAILED", f"Provider rejected action: {result.message}", actor=actor
                )
            audit.record(
                db,
                self.clock,
                actor=actor,
                role=role,
                action=f"remediation.{rem.action}",
                target=rem.target_service,
                reason=result.message,
                before=rem.before_state,
                result="FAILED",
                ai_confidence=rem.ai_confidence,
            )
            return
        self._record_deployment_event(db, rem, actor)
        rem.status = "VERIFYING"
        rem.verify_at_tick = self.store.tick + self.settings.verify_after_ticks
        if inc:
            inc.remediation_status = "VERIFYING"
            self._event(
                db,
                inc,
                "REMEDIATION_EXECUTED",
                f"{rem.action} executed: {result.details}; verifying after {self.settings.verify_after_ticks} samples",
                actor=actor,
                data=result.details,
            )
        audit.record(
            db,
            self.clock,
            actor=actor,
            role=role,
            action=f"remediation.{rem.action}",
            target=rem.target_service,
            reason=rem.decision_reason or "",
            before=rem.before_state,
            after={"execution": rem.execution_output},
            ai_confidence=rem.ai_confidence,
            result="EXECUTED",
        )

    def _dispatch(self, rem: Remediation) -> ActionResult:
        p, svc = rem.parameters, rem.target_service
        if rem.action == "restart_pod":
            return self.provider.restart_pod(svc, p["pod"])
        if rem.action == "restart_service":
            return self.provider.restart_service(svc)
        if rem.action == "scale_deployment":
            return self.provider.scale_deployment(svc, int(p["replicas"]))
        if rem.action == "rollback_deployment":
            return self.provider.rollback_deployment(svc)
        if rem.action == "clear_failed_job":
            return self.provider.clear_failed_job(svc, p["job_id"])
        raise policy.PolicyViolation(rem.action)

    def _record_deployment_event(self, db: Session, rem: Remediation, actor: str) -> None:
        kind = {
            "rollback_deployment": "ROLLBACK",
            "scale_deployment": "SCALE",
            "restart_service": "RESTART",
        }.get(rem.action)
        if not kind:
            return
        st = self.provider.deployment_state(rem.target_service)
        prev = rem.before_state.get("deployment", {}).get("version") if kind == "ROLLBACK" else st["version"]
        db.add(
            Deployment(
                service=rem.target_service,
                version=st["version"],
                previous_version=prev,
                kind=kind,
                status="SUCCEEDED",
                actor=actor,
                created_at=self.clock.now(),
                notes=f"Remediation #{rem.id}: {rem.action} {rem.parameters or ''}",
            )
        )

    def _verify_due(self, db: Session, tick: int) -> None:
        due = (
            db.execute(
                select(Remediation).where(
                    Remediation.status == "VERIFYING", Remediation.verify_at_tick <= tick
                )
            )
            .scalars()
            .all()
        )
        for rem in due:
            self.verify(db, rem)

    def verify(self, db: Session, rem: Remediation) -> None:
        inc = db.get(Incident, rem.incident_id) if rem.incident_id else None
        checks: list[dict[str, Any]] = []
        if inc:
            for s in {
                (s["service"], s["rule"]): s
                for s in inc.signals or []
                if s.get("kind") == "rule" and s["rule"] not in LAGGING_RULES
            }.values():
                clear = self.detector.is_rule_clear(s["rule"], s["service"])
                cur = self.store.avg_recent(s["service"], s["metric"], 2)
                checks.append(
                    {
                        "check": f"{s['rule']} cleared on {s['service']}",
                        "passed": clear,
                        "metric": s["metric"],
                        "before": rem.before_state.get(s["service"], {}).get(s["metric"]),
                        "after": None if cur is None else round(cur, 4),
                        "threshold": s["threshold"],
                    }
                )
        pods = self.provider.pods(rem.target_service)
        live = [p for p in pods if p["phase"] != "Terminating"]
        ready = sum(1 for p in live if p["ready"])
        desired = self._current_replicas(rem.target_service)
        if rem.action == "restart_pod":
            gone = rem.parameters["pod"] not in {p["name"] for p in pods}
            checks.append({"check": f"pod {rem.parameters['pod']} replaced", "passed": gone})
        if rem.action == "rollback_deployment":
            expected = rem.execution_output.get("to")
            actual = self.provider.deployment_state(rem.target_service)["version"]
            checks.append(
                {"check": f"running version is {expected}", "passed": actual == expected, "after": actual}
            )
        if rem.action == "clear_failed_job":
            q = self.store.series(rem.target_service, "queue_depth", 3)
            checks.append(
                {
                    "check": "queue draining",
                    "passed": len(q) >= 2 and q[-1] <= q[0],
                    "after": q[-1] if q else None,
                }
            )
        checks.append({"check": f"{ready}/{desired} pods ready", "passed": ready >= desired, "after": ready})
        health = evaluate_health(
            rem.target_service,
            self.store.latest(rem.target_service),
            self.kinds.get(rem.target_service, "http"),
        )
        checks.append(
            {
                "check": f"{rem.target_service} not UNHEALTHY",
                "passed": health["status"] != "UNHEALTHY",
                "after": health["status"],
            }
        )
        services = [rem.target_service] + ([inc.service] + list(inc.correlated_services or []) if inc else [])
        rem.after_state = self._snapshot(services)
        success = all(c["passed"] for c in checks)
        rem.verification = {
            **(rem.verification or {}),
            "checks": checks,
            "result": "SUCCESS" if success else "FAILED",
        }
        rem.verified_at = self.clock.now()
        rem.status = "SUCCEEDED" if success else "FAILED"
        prom.REMEDIATIONS.labels(action=rem.action, result=rem.status.lower()).inc()
        audit.record(
            db,
            self.clock,
            actor="verification-engine",
            role="SYSTEM",
            action="remediation.verified",
            target=f"{rem.target_service}:{rem.action}",
            reason="; ".join(f"{c['check']}: {'PASS' if c['passed'] else 'FAIL'}" for c in checks),
            before=rem.before_state,
            after=rem.after_state,
            ai_confidence=rem.ai_confidence,
            result=rem.status,
        )
        if not inc:
            return
        if success:
            inc.remediation_status = "SUCCEEDED"
            self._event(
                db,
                inc,
                "VERIFICATION_PASSED",
                "; ".join(c["check"] for c in checks),
                actor="verification-engine",
                data={"checks": checks},
            )
            self._resolve(
                db,
                inc,
                f"Resolved by {rem.action} on {rem.target_service} (remediation #{rem.id}); verified by {len(checks)} checks.",
                actor=rem.decided_by or "system",
            )
        else:
            inc.status = "INVESTIGATING"
            inc.remediation_status = "FAILED"
            failed = [c["check"] for c in checks if not c["passed"]]
            self._event(
                db,
                inc,
                "VERIFICATION_FAILED",
                "Failed checks: " + "; ".join(failed),
                actor="verification-engine",
                data={"checks": checks},
            )
            db.flush()
            self.investigate_incident(db, inc.id, actor="ai-agent")

    # ------------------------------------------------------------ deployments
    def deploy(
        self,
        db: Session,
        service: str,
        version: str,
        actor: str,
        role: str,
        defective: bool = False,
        notes: str = "",
    ) -> Deployment:
        with self.lock:
            before = self.provider.deployment_state(service)
            res = self.provider.deploy(service, version, defective)
            if not res.ok:
                raise RemediationError(res.message)
            dep = Deployment(
                service=service,
                version=version,
                previous_version=before["version"],
                kind="DEPLOY",
                status="SUCCEEDED",
                actor=actor,
                created_at=self.clock.now(),
                notes=notes,
            )
            db.add(dep)
            audit.record(
                db,
                self.clock,
                actor=actor,
                role=role,
                action="deployment.created",
                target=service,
                reason=notes,
                before={"version": before["version"]},
                after={"version": version},
            )
            return dep


def _truncate(obj: Any, max_items: int = 40) -> Any:
    if isinstance(obj, dict):
        return {k: _truncate(v, max_items) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate(v, max_items) for v in obj[-max_items:]]
    return obj
