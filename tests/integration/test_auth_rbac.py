import jwt
import pytest

from tests.conftest import PASSWORDS


def test_login_and_me(harness):
    r = harness.client.post("/api/auth/login", json={"username": "sre", "password": PASSWORDS["sre"]})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "SRE" and body["token_type"] == "bearer"
    me = harness.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    ).json()
    assert me["username"] == "sre" and "remediation:approve" in me["permissions"]


def test_bad_login_is_audited(harness):
    r = harness.client.post("/api/auth/login", json={"username": "sre", "password": "wrong"})
    assert r.status_code == 401
    r = harness.client.post("/api/auth/login", json={"username": "ghost", "password": "wrong"})
    assert r.status_code == 401
    logs = harness.get("/api/audit?action=auth.login", user="admin").json()
    assert sum(1 for a in logs if a["result"] == "DENIED") >= 2


def test_login_rate_limited(harness_factory):
    h = harness_factory(login_rate_limit_per_minute=3)
    codes = [
        h.client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_unauthenticated_and_forged_tokens_rejected(harness):
    assert harness.client.get("/api/incidents").status_code == 401
    forged = jwt.encode(
        {"sub": "admin", "role": "ADMIN", "iss": "cloudops-ai", "exp": 4102444800},
        "not-the-secret",
        algorithm="HS256",
    )
    assert (
        harness.client.get("/api/incidents", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    )
    none_alg = jwt.encode({"sub": "admin", "iss": "cloudops-ai", "exp": 4102444800}, key="", algorithm="none")
    assert (
        harness.client.get("/api/incidents", headers={"Authorization": f"Bearer {none_alg}"}).status_code
        == 401
    )


def test_role_claim_in_token_is_not_trusted(harness):
    """A valid token whose role claim says ADMIN still gets the DB role's permissions."""
    from datetime import UTC, datetime

    from app.core.security import create_token

    token = create_token(harness.cp.settings.jwt_secret, "viewer", "ADMIN", 5, datetime.now(UTC))
    r = harness.client.post(
        "/api/simulator/inject", json={"fault": "high_cpu"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("user", "method", "path", "body", "expected"),
    [
        ("viewer", "post", "/api/simulator/inject", {"fault": "high_cpu"}, 403),
        ("developer", "post", "/api/simulator/inject", {"fault": "high_cpu"}, 403),
        ("viewer", "post", "/api/ai/investigate", {"question": "what is wrong?"}, 403),
        ("developer", "post", "/api/ai/investigate", {"question": "what is wrong?"}, 200),
        ("viewer", "get", "/api/audit", None, 403),
        ("developer", "get", "/api/audit", None, 403),
        ("sre", "get", "/api/audit", None, 200),
        ("sre", "put", "/api/settings", {"autonomous_mode": True, "reason": "test"}, 403),
        ("admin", "put", "/api/settings", {"autonomous_mode": True, "reason": "test"}, 200),
        ("sre", "get", "/api/auth/users", None, 403),
        ("admin", "get", "/api/auth/users", None, 200),
        ("developer", "post", "/api/deployments", {"service": "user-service", "version": "v3.3.0"}, 403),
        ("sre", "post", "/api/deployments", {"service": "user-service", "version": "v3.3.0"}, 201),
    ],
)
def test_permission_matrix(harness, user, method, path, body, expected):
    r = (
        getattr(harness.client, method)(path, json=body, headers=harness.h(user))
        if body is not None
        else getattr(harness.client, method)(path, headers=harness.h(user))
    )
    assert r.status_code == expected, r.text


def test_developer_can_propose_but_not_approve(harness):
    r = harness.post(
        "/api/remediations",
        {"action": "restart_service", "target_service": "user-service", "reason": "testing proposal"},
        user="developer",
    )
    assert r.status_code == 201
    rid = r.json()["id"]
    assert (
        harness.post(f"/api/remediations/{rid}/approve", {"reason": "ok"}, user="developer").status_code
        == 403
    )
    assert (
        harness.post(
            f"/api/remediations/{rid}/approve", {"reason": "approved by sre"}, user="sre"
        ).status_code
        == 200
    )


def test_high_risk_requires_admin(harness):
    r = harness.post(
        "/api/remediations",
        {"action": "rollback_deployment", "target_service": "user-service", "reason": "testing"},
        user="sre",
    )
    # user-service has a single version, so the proposal is valid but execution would fail; we only test the approval gate
    rid = r.json()["id"]
    assert r.json()["risk"] == "HIGH"
    assert (
        harness.post(f"/api/remediations/{rid}/approve", {"reason": "sre tries"}, user="sre").status_code
        == 403
    )
    denied = [
        a
        for a in harness.get("/api/audit?action=remediation.approved", user="admin").json()
        if a["result"] == "DENIED"
    ]
    assert denied
    r = harness.post(f"/api/remediations/{rid}/approve", {"reason": "admin approves"}, user="admin")
    assert r.status_code == 200 and r.json()["status"] == "FAILED"  # provider refused: no previous version
    assert "no previous version" in r.json()["execution_output"]["message"]


def test_admin_can_create_user_with_strong_password(harness):
    weak = harness.post(
        "/api/auth/users", {"username": "newbie", "password": "short", "role": "VIEWER"}, user="admin"
    )
    assert weak.status_code == 422
    ok = harness.post(
        "/api/auth/users",
        {"username": "newbie", "password": "a-long-enough-pass", "role": "VIEWER"},
        user="admin",
    )
    assert ok.status_code == 201
    assert (
        harness.client.post(
            "/api/auth/login", json={"username": "newbie", "password": "a-long-enough-pass"}
        ).status_code
        == 200
    )
