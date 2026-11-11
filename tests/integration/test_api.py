import pytest

READ_ENDPOINTS = [
    "/api/services",
    "/api/services/topology",
    "/api/services/payment-service",
    "/api/incidents",
    "/api/metrics/overview",
    "/api/metrics/catalog",
    "/api/metrics/payment-service?metric=cpu_percent&window=30",
    "/api/logs?service=payment-service&limit=5",
    "/api/deployments",
    "/api/remediations",
    "/api/remediations/policy",
    "/api/slo",
    "/api/slo/reliability",
    "/api/runbooks",
    "/api/runbooks/high-cpu",
    "/api/runbooks/search?q=database%20connections",
    "/api/ai/status",
    "/api/ai/investigations",
    "/api/infrastructure/kubernetes",
    "/api/infrastructure/pods",
    "/api/infrastructure/database",
    "/api/infrastructure/provider",
    "/api/simulator",
    "/api/settings",
    "/api/system/status",
    "/api/auth/roles",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_viewer_can_read(harness, path):
    r = harness.get(path)
    assert r.status_code == 200, r.text


def test_openapi_and_health(harness):
    spec = harness.client.get("/api/openapi.json").json()
    for prefix in [
        "/api/auth",
        "/api/services",
        "/api/incidents",
        "/api/metrics",
        "/api/logs",
        "/api/deployments",
        "/api/remediations",
        "/api/slo",
        "/api/runbooks",
        "/api/ai",
        "/api/audit",
    ]:
        assert any(p.startswith(prefix) for p in spec["paths"]), prefix
    assert harness.client.get("/healthz").json() == {"status": "ok"}
    assert harness.client.get("/readyz").status_code == 200
    metrics = harness.client.get("/metrics").text
    assert 'cloudops_service_cpu_percent{provider="local",service="payment-service"}' in metrics


def test_security_headers(harness):
    r = harness.get("/api/services")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers


def test_cors_only_allows_configured_origins(harness):
    ok = harness.client.options(
        "/api/services", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = harness.client.options(
        "/api/services", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in bad.headers


@pytest.mark.parametrize(
    "body",
    [
        {"fault": "high_cpu", "extra": 1},
        {"fault": "format_disk"},
        {"fault": "high_cpu", "service": "../../etc"},
    ],
)
def test_input_validation(harness, body):
    assert harness.post("/api/simulator/inject", body).status_code == 422


def test_remediation_policy_violations_rejected(harness):
    r = harness.post(
        "/api/remediations",
        {
            "action": "scale_deployment",
            "target_service": "api-gateway",
            "parameters": {"replicas": 99},
            "reason": "too big",
        },
    )
    assert r.status_code == 422
    r = harness.post(
        "/api/remediations",
        {
            "action": "restart_pod",
            "target_service": "api-gateway",
            "parameters": {"pod": "does-not-exist"},
            "reason": "x y z",
        },
    )
    assert r.status_code == 422
    r = harness.post(
        "/api/remediations", {"action": "delete_cluster", "target_service": "api-gateway", "reason": "nope"}
    )
    assert r.status_code == 422


def test_metrics_and_logs_reflect_simulation(harness):
    m = harness.get("/api/metrics/overview").json()
    assert m["simulated"] is True and m["provider"] == "local"
    assert set(m["services"]) == {
        "api-gateway",
        "user-service",
        "payment-service",
        "notification-service",
        "database",
    }
    series = harness.get("/api/metrics/api-gateway?metric=rps&window=20").json()
    assert len(series["series"]["rps"]) == 20 and all(v > 0 for v in series["series"]["rps"])


def test_ai_fleet_question_when_healthy(harness):
    r = harness.post(
        "/api/ai/investigate", {"question": "What is wrong with my infrastructure?"}, user="developer"
    ).json()
    assert r["result"]["status"] == "HEALTHY"
    assert r["result"]["recommendation"] is None


def test_manual_deploy_recorded(harness):
    r = harness.post(
        "/api/deployments", {"service": "user-service", "version": "v3.3.0", "notes": "feature flag"}
    )
    assert r.status_code == 201
    deps = harness.get("/api/deployments?service=user-service").json()
    assert deps[0]["version"] == "v3.3.0" and deps[0]["previous_version"] == "v3.2.0"
