"""Scripted end-to-end demo against a running CloudOps AI API.

    uv run python scripts/demo.py --base http://localhost:8000 [--fault deployment_failure]

Credentials are read from the environment / .env (SEED_SRE_PASSWORD, SEED_ADMIN_PASSWORD).
Every step goes through the public, RBAC-protected API exactly as the UI does.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def step(n: int, msg: str) -> None:
    print(f"\n\033[1;36m[{n:02d}] {msg}\033[0m")


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--fault", default="deployment_failure")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=30)

    def login(user: str) -> dict[str, str]:
        pw = os.environ.get(f"SEED_{user.upper()}_PASSWORD")
        if not pw:
            sys.exit(f"SEED_{user.upper()}_PASSWORD not set (run scripts/bootstrap_env.sh)")
        r = c.post("/api/auth/login", json={"username": user, "password": pw})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    sre, admin = login("sre"), login("admin")

    step(1, "Healthy system")
    st = c.get("/api/system/status", headers=sre).json()
    print(f"    {st['services_healthy']}/{st['services_total']} services healthy, {st['active_incidents']} active incidents, provider={st['provider']}")
    if st["active_incidents"]:
        print("    (there are already active incidents; continuing)")

    step(2, f"Trigger failure: {args.fault}")
    print("   ", c.post("/api/simulator/inject", json={"fault": args.fault}, headers=sre).raise_for_status().json())

    step(3, "Waiting for detection → incident → AI investigation → recommendation")
    inc = None
    for _ in range(60):
        actives = c.get("/api/incidents?active=true", headers=sre).json()
        pending = [i for i in actives if i["remediation_status"] == "PENDING_APPROVAL"]
        if pending:
            inc = pending[0]
            break
        time.sleep(1)
    if not inc:
        sys.exit("no incident reached PENDING_APPROVAL in 60s")
    d = c.get(f"/api/incidents/{inc['incident_id']}", headers=sre).json()
    print(f"    {d['incident_id']} [{d['severity']}] {d['title']}  (detected {d.get('time_to_detect_seconds')}s after impact)")
    inv = d["investigations"][-1]["result"]
    for f in inv["findings"][:8]:
        tag = "FACT " if f["kind"] == "OBSERVED_FACT" else "INFER"
        print(f"    {tag} {f['statement']}")
    print(f"    ROOT CAUSE: {d['probable_root_cause']} in {d['root_cause_service']} (confidence {d['confidence']:.0%})")
    print(f"    RUNBOOKS:   {', '.join(r['title'] for r in inv['runbooks'])}")
    rem = next(r for r in d["remediations"] if r["status"] == "PROPOSED")
    print(f"    RECOMMEND:  {rem['action']} {rem['parameters'] or ''} on {rem['target_service']} — {rem['risk']} risk")

    step(4, "Human approval")
    approver = admin if rem["risk"] == "HIGH" else sre
    r = c.post(f"/api/remediations/{rem['id']}/approve", json={"reason": "Demo: approved per runbook"}, headers=approver)
    r.raise_for_status()
    print(f"    approved by {'admin' if approver is admin else 'sre'}; status={r.json()['status']}")

    step(5, "Verification (re-reading the infrastructure)")
    for _ in range(60):
        rem = c.get(f"/api/remediations/{rem['id']}", headers=sre).json()
        if rem["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(1)
    for chk in rem["verification"].get("checks", []):
        print(f"    {'PASS' if chk['passed'] else 'FAIL'}  {chk['check']}  {chk.get('before', '')} -> {chk.get('after', '')}")
    print(f"    remediation {rem['status']}")

    step(6, "Resolution + audit trail")
    d = c.get(f"/api/incidents/{inc['incident_id']}", headers=sre).json()
    print(f"    {d['incident_id']} status={d['status']}  TTR={d.get('time_to_resolve_seconds')}s")
    for e in d["events"]:
        print(f"    {e['ts'][11:19]}  {e['type']:<22} {e['message'][:90]}")
    chain = c.get("/api/audit/verify", headers=sre).json()
    print(f"    audit chain valid={chain['valid']} ({chain['checked']} records)")
    return 0 if d["status"] == "RESOLVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
