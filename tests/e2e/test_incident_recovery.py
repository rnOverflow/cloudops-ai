"""End-to-end incident recovery through the public API.

Healthy -> fault -> metrics change -> alert -> incident -> AI investigation -> root cause
-> runbook -> recommendation -> human approval -> remediation -> verification -> resolution
-> audit trail.
"""

import pytest

pytestmark = pytest.mark.e2e


def active(h):
    return h.get("/api/incidents?active=true").json()


def detail(h, key):
    return h.get(f"/api/incidents/{key}").json()


def test_full_demo_workflow_payment_deployment_failure(harness):
    h = harness
    # 1. Healthy system
    status = h.get("/api/system/status").json()
    assert status["services_healthy"] == status["services_total"] == 5
    assert status["active_incidents"] == 0

    # 2. Trigger payment-service failure (defective release)
    r = h.post("/api/simulator/inject", {"fault": "deployment_failure"}, user="sre")
    assert r.status_code == 200 and r.json()["injected"]["version"] == "v2.5.0"

    # 3. Metrics change
    h.tick(2)
    assert h.get("/api/metrics/overview").json()["services"]["payment-service"]["error_rate"] > 0.2

    # 4/5. Alert -> incident
    h.tick_until(lambda: len(active(h)) > 0, 10)
    incidents = active(h)
    assert len(incidents) == 1, incidents  # gateway symptoms are correlated, not a second incident
    key = incidents[0]["incident_id"]
    inc = detail(h, key)
    assert inc["service"] == "payment-service" and inc["severity"] == "CRITICAL"
    assert inc["time_to_detect_seconds"] is not None and inc["time_to_detect_seconds"] <= 10

    # 6/7/8. AI investigation, root cause, runbook
    assert inc["probable_root_cause"] == "Faulty deployment introduced a regression"
    assert inc["root_cause_service"] == "payment-service" and inc["confidence"] >= 0.8
    inv = inc["investigations"][0]["result"]
    facts = [f for f in inv["findings"] if f["kind"] == "OBSERVED_FACT"]
    inferences = [f for f in inv["findings"] if f["kind"] == "AI_INFERENCE"]
    assert facts and inferences
    assert any("v2.5.0" in f["statement"] for f in facts)
    assert inv["runbooks"][0]["slug"] == "deployment-failure"

    # 9. Recommendation with evidence, risk, expected impact
    rem = inc["remediations"][0]
    assert rem["action"] == "rollback_deployment" and rem["risk"] == "HIGH" and rem["status"] == "PROPOSED"
    assert inc["remediation_status"] == "PENDING_APPROVAL" and rem["expected_impact"]

    # 10. Human approval (HIGH risk: SRE is refused, ADMIN approves)
    assert (
        h.post(f"/api/remediations/{rem['id']}/approve", {"reason": "rollback"}, user="sre").status_code
        == 403
    )
    r = h.post(
        f"/api/remediations/{rem['id']}/approve",
        {"reason": "Errors began with v2.5.0; rolling back"},
        user="admin",
    )
    assert r.status_code == 200 and r.json()["status"] == "VERIFYING"
    assert detail(h, key)["status"] == "MITIGATING"

    # 11/12. Remediation executed; verification reads the infrastructure back
    h.tick(h.cp.settings.verify_after_ticks)
    rem = h.get(f"/api/remediations/{rem['id']}").json()
    assert rem["status"] == "SUCCEEDED"
    assert rem["verification"]["result"] == "SUCCESS"
    assert rem["before_state"]["payment-service"]["error_rate"] > 0.2
    assert rem["after_state"]["payment-service"]["error_rate"] < 0.05
    assert any(
        c["check"] == "running version is v2.4.1" and c["passed"] for c in rem["verification"]["checks"]
    )

    # 13. Incident resolution
    inc = detail(h, key)
    assert inc["status"] == "RESOLVED" and inc["remediation_status"] == "SUCCEEDED"
    types = [e["type"] for e in inc["events"]]
    for expected in [
        "DETECTED",
        "INVESTIGATION_STARTED",
        "ROOT_CAUSE_IDENTIFIED",
        "RUNBOOK_RETRIEVED",
        "RECOMMENDATION",
        "APPROVAL_REQUESTED",
        "APPROVED",
        "REMEDIATION_STARTED",
        "REMEDIATION_EXECUTED",
        "VERIFICATION_PASSED",
        "RESOLVED",
    ]:
        assert expected in types, expected
    assert (
        types.index("DETECTED")
        < types.index("ROOT_CAUSE_IDENTIFIED")
        < types.index("APPROVED")
        < types.index("VERIFICATION_PASSED")
        < types.index("RESOLVED")
    )

    # 14. Audit trail (hash chain intact)
    actions = [a["action"] for a in h.get("/api/audit?limit=500", user="admin").json()]
    for expected in [
        "simulator.inject",
        "deployment.created",
        "incident.created",
        "ai.investigation",
        "remediation.proposed",
        "remediation.approved",
        "remediation.rollback_deployment",
        "remediation.verified",
        "incident.resolved",
    ]:
        assert expected in actions, expected
    approved = next(
        a
        for a in h.get("/api/audit?action=remediation.approved", user="admin").json()
        if a["result"] == "SUCCESS"
    )
    assert approved["actor"] == "admin" and approved["role"] == "ADMIN" and approved["ai_confidence"] >= 0.8
    assert h.get("/api/audit/verify", user="admin").json()["valid"] is True

    # Reliability metrics reflect the incident
    rel = h.get("/api/slo/reliability").json()
    assert rel["incident_count"] == 1 and rel["mttr_seconds"] > 0 and rel["mttd_seconds"] is not None

    # Closing the post-incident review
    assert (
        h.post(
            f"/api/incidents/{key}/status", {"status": "CLOSED", "note": "Postmortem PM-1 filed"}
        ).status_code
        == 200
    )


SCENARIOS = [
    ("high_cpu", "payment-service", "restart_service", "payment-service"),
    ("memory_leak", "payment-service", "restart_pod", "payment-service"),
    ("db_saturation", "database", "restart_service", "payment-service"),
    ("pod_crash", "payment-service", "restart_pod", "payment-service"),
    ("latency_spike", "payment-service", "restart_service", "payment-service"),
    ("traffic_spike", "api-gateway", "scale_deployment", "api-gateway"),
    ("outage", "payment-service", "restart_service", "payment-service"),
    ("queue_backlog", "notification-service", "clear_failed_job", "notification-service"),
]


@pytest.mark.parametrize(("fault", "incident_service", "action", "target"), SCENARIOS)
def test_every_failure_mode_is_detected_diagnosed_and_recovered(
    harness, fault, incident_service, action, target
):
    h = harness
    assert h.post("/api/simulator/inject", {"fault": fault}).status_code == 200
    h.tick_until(lambda: any(i["remediation_status"] == "PENDING_APPROVAL" for i in active(h)), 20)
    incs = active(h)
    assert len(incs) == 1, [(i["incident_id"], i["service"]) for i in incs]
    inc = detail(h, incs[0]["incident_id"])
    assert inc["service"] == incident_service
    rem = inc["remediations"][-1]
    assert (rem["action"], rem["target_service"]) == (action, target), inc["probable_root_cause"]
    approver = "admin" if rem["risk"] == "HIGH" else "sre"
    assert (
        h.post(
            f"/api/remediations/{rem['id']}/approve", {"reason": "approve per runbook"}, user=approver
        ).status_code
        == 200
    )
    h.tick(h.cp.settings.verify_after_ticks)
    inc = detail(h, inc["incident_id"])
    assert inc["status"] == "RESOLVED", [(e["type"], e["message"]) for e in inc["events"]]
    remaining = h.get("/api/system/status").json()["active_faults"]
    # Remediation removes internal faults. A traffic surge is external: scaling absorbs it, the traffic remains.
    assert remaining == [] or (
        fault == "traffic_spike" and [f["type"] for f in remaining] == ["traffic_spike"]
    )


def test_autonomous_mode_fixes_low_risk_without_human(harness):
    h = harness
    assert (
        h.put(
            "/api/settings", {"autonomous_mode": True, "reason": "enable autopilot for LOW risk"}
        ).status_code
        == 200
    )
    h.post("/api/simulator/inject", {"fault": "pod_crash"})
    h.tick_until(lambda: len(h.get("/api/incidents").json()) > 0, 15)
    key = h.get("/api/incidents").json()[0]["incident_id"]
    h.tick_until(lambda: detail(h, key)["status"] == "RESOLVED", 10)
    inc = detail(h, key)
    rem = inc["remediations"][0]
    assert rem["autonomous"] and rem["decided_by"] == "autopilot" and rem["risk"] == "LOW"
    audit_rows = h.get("/api/audit?actor=autopilot", user="admin").json()
    assert any(a["action"] == "remediation.approved" for a in audit_rows)


def test_autonomous_mode_still_requires_approval_for_medium_risk(harness):
    h = harness
    h.put("/api/settings", {"autonomous_mode": True, "reason": "enable autopilot"})
    h.post("/api/simulator/inject", {"fault": "high_cpu"})
    h.tick_until(lambda: any(i["remediation_status"] == "PENDING_APPROVAL" for i in active(h)), 15)
    h.tick(5)
    inc = detail(h, active(h)[0]["incident_id"])
    assert inc["status"] == "INVESTIGATING" and inc["remediations"][0]["status"] == "PROPOSED"
    assert any("require human approval" in e["message"] for e in inc["events"])


def test_wrong_remediation_fails_verification_and_agent_reinvestigates(harness):
    h = harness
    h.post("/api/simulator/inject", {"fault": "high_cpu"})
    h.tick_until(lambda: any(i["remediation_status"] == "PENDING_APPROVAL" for i in active(h)), 15)
    inc = active(h)[0]
    ai_rem = detail(h, inc["incident_id"])["remediations"][0]
    # Human overrides the AI: rejects restart and scales out instead (does not fix runaway threads)
    h.post(f"/api/remediations/{ai_rem['id']}/reject", {"reason": "prefer scaling"})
    r = h.post(
        "/api/remediations",
        {
            "action": "scale_deployment",
            "target_service": "payment-service",
            "parameters": {"replicas": 5},
            "incident_key": inc["incident_id"],
            "reason": "operator believes it is load",
        },
    )
    assert r.status_code == 201
    h.post(f"/api/remediations/{r.json()['id']}/approve", {"reason": "go ahead"})
    h.tick(h.cp.settings.verify_after_ticks)
    scaled = h.get(f"/api/remediations/{r.json()['id']}").json()
    assert scaled["status"] == "FAILED"  # the command ran fine, but the infrastructure did not recover
    assert scaled["execution_output"]["ok"] is True
    assert not next(c for c in scaled["verification"]["checks"] if c["check"].startswith("HIGH_CPU"))[
        "passed"
    ]
    d = detail(h, inc["incident_id"])
    assert d["status"] == "INVESTIGATING"
    assert "VERIFICATION_FAILED" in [e["type"] for e in d["events"]]
    latest = d["remediations"][-1]
    assert latest["status"] == "PROPOSED" and latest["action"] == "restart_service"


def test_reject_keeps_incident_open_and_is_audited(harness):
    h = harness
    h.post("/api/simulator/inject", {"fault": "memory_leak"})
    h.tick_until(lambda: any(i["remediation_status"] == "PENDING_APPROVAL" for i in active(h)), 15)
    inc = active(h)[0]
    rem = detail(h, inc["incident_id"])["remediations"][0]
    assert (
        h.post(f"/api/remediations/{rem['id']}/reject", {"reason": "capture heap dump first"}).status_code
        == 200
    )
    d = detail(h, inc["incident_id"])
    assert d["remediation_status"] == "REJECTED" and d["status"] in ("INVESTIGATING", "OPEN")
    assert h.post(f"/api/remediations/{rem['id']}/approve", {"reason": "too late"}).status_code == 409
    assert any(
        a["result"] == "REJECTED"
        for a in h.get("/api/audit?action=remediation.rejected", user="admin").json()
    )


def test_ai_answers_why_is_payment_service_unhealthy(harness):
    h = harness
    h.post("/api/simulator/inject", {"fault": "db_saturation"})
    h.tick(8)
    r = h.post(
        "/api/ai/investigate", {"question": "Why is payment-service unhealthy?"}, user="developer"
    ).json()
    res = r["result"]
    assert res["root_cause_service"] == "payment-service"
    assert "connection leak" in res["root_cause"].lower()
    assert res["recommendation"]["action"] == "restart_service"
    tools = [c["tool"] for c in res["tool_calls"]]
    for t in [
        "get_service_health",
        "get_metrics",
        "query_logs",
        "get_recent_deployments",
        "get_service_dependencies",
        "get_runbook",
        "get_database_status",
    ]:
        assert t in tools


def test_agent_does_not_blame_stale_evidence_after_recovery(harness):
    """After a verified rollback, asking again must not resurrect the old root cause from stale logs or a rolled-back deploy."""
    h = harness
    h.post("/api/simulator/inject", {"fault": "deployment_failure"})
    h.tick_until(lambda: any(i["remediation_status"] == "PENDING_APPROVAL" for i in active(h)), 15)
    rem = detail(h, active(h)[0]["incident_id"])["remediations"][0]
    h.post(f"/api/remediations/{rem['id']}/approve", {"reason": "roll back"}, user="admin")
    h.tick(h.cp.settings.verify_after_ticks + 35)  # recovery + log window passes
    res = h.post(
        "/api/ai/investigate", {"question": "Why is payment-service unhealthy?"}, user="developer"
    ).json()["result"]
    assert res["status"] == "HEALTHY"
    assert res["root_cause"] is None and res["recommendation"] is None
    assert any("rolled back" in f["statement"] for f in res["findings"])


def test_blast_radius_guard_blocks_rapid_repeat_executions(harness):
    h = harness
    assert (
        h.put("/api/settings", {"blast_radius_max_executions": 1, "reason": "tighten guard"}).status_code
        == 200
    )
    first = h.post(
        "/api/remediations",
        {"action": "restart_service", "target_service": "user-service", "reason": "first restart"},
    ).json()
    assert (
        h.post(f"/api/remediations/{first['id']}/approve", {"reason": "ok go"}).json()["status"]
        == "VERIFYING"
    )
    h.tick(h.cp.settings.verify_after_ticks)
    second = h.post(
        "/api/remediations",
        {"action": "restart_service", "target_service": "user-service", "reason": "second restart"},
    ).json()
    blocked = h.post(f"/api/remediations/{second['id']}/approve", {"reason": "ok go"}).json()
    assert blocked["status"] == "FAILED" and "blast-radius" in blocked["execution_output"]["error"]
    assert any(
        a["result"] == "BLOCKED" for a in h.get("/api/audit?action=remediation.blocked", user="admin").json()
    )
