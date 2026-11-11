from pathlib import Path

import pytest
from app.core import audit
from app.core.clock import ManualClock
from app.db import Base, make_engine
from app.models import AuditLog
from app.remediation.policy import PolicyViolation, assess, validate_params
from app.runbooks.retrieval import BM25Index, load_runbooks
from sqlalchemy.orm import Session

RUNBOOKS = Path(__file__).resolve().parents[2] / "runbooks"


def test_risk_levels():
    assert assess("restart_pod", "s", {"pod": "p"}, 3, "tier-1").risk == "LOW"
    assert assess("restart_pod", "s", {"pod": "p"}, 3, "tier-1").autonomous_eligible
    assert assess("restart_service", "s", {}, 3, "tier-0").risk == "MEDIUM"
    assert assess("scale_deployment", "s", {"replicas": 6}, 3, "tier-1").risk == "MEDIUM"
    assert assess("scale_deployment", "s", {"replicas": 1}, 3, "tier-1").risk == "HIGH"
    assert assess("rollback_deployment", "s", {}, 3, "tier-1").risk == "HIGH"
    with pytest.raises(PolicyViolation):
        assess("exec_shell", "s", {}, 3, "tier-1")


@pytest.mark.parametrize(
    ("action", "params"),
    [
        ("scale_deployment", {"replicas": 50}),
        ("scale_deployment", {"replicas": "3"}),
        ("scale_deployment", {"replicas": True}),
        ("restart_pod", {"pod": "p; rm -rf /"}),
        ("restart_pod", {}),
        ("restart_service", {"cmd": "x"}),
        ("clear_failed_job", {"job_id": "../etc"}),
    ],
)
def test_param_validation_rejects(action, params):
    with pytest.raises(PolicyViolation):
        validate_params(action, params)


def test_all_runbooks_parse_and_cover_required_topics():
    docs = load_runbooks(RUNBOOKS)
    slugs = {d.slug for d in docs}
    assert slugs >= {
        "high-cpu",
        "high-memory",
        "database-saturation",
        "pod-crash-loop",
        "api-latency",
        "high-error-rate",
        "deployment-failure",
        "service-outage",
        "disk-exhaustion",
        "queue-backlog",
    }
    allowed = {
        "restart_pod",
        "restart_service",
        "scale_deployment",
        "rollback_deployment",
        "clear_failed_job",
    }
    for d in docs:
        assert set(d.actions) <= allowed, d.slug


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("database connection pool exhausted too many clients", "database-saturation"),
        ("pod restarts crashloopbackoff exit code", "pod-crash-loop"),
        ("errors started after new release version rollback", "deployment-failure"),
        ("queue depth growing poison job", "queue-backlog"),
        ("heap memory gc pressure oom", "high-memory"),
        ("no space left on device", "disk-exhaustion"),
    ],
)
def test_runbook_retrieval_relevance(query, expected):
    idx = BM25Index(load_runbooks(RUNBOOKS))
    assert idx.search(query, 1)[0][0].slug == expected


def test_audit_chain_detects_tampering():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    clock = ManualClock()
    with Session(engine) as db:
        for i in range(5):
            audit.record(db, clock, actor="u", role="SRE", action=f"a{i}", reason="r")
        db.commit()
        assert audit.verify_chain(db) == {"valid": True, "checked": 5}
        rec = db.get(AuditLog, 3)
        rec.reason = "rewritten history"
        db.commit()
        result = audit.verify_chain(db)
        assert result["valid"] is False and result["broken_at"] == 3
