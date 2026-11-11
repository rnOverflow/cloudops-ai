"""Game-day runner: injects every simulated failure mode in sequence, lets the platform
handle each one (approving recommendations as the given role), and prints a scorecard
(detected? correct root cause? verified recovery? MTTD/MTTR).

    uv run python automation/game_day.py --base http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from demo import load_env  # noqa: E402

EXPECTED = {
    "high_cpu": ("restart_service", "payment-service"),
    "memory_leak": ("restart_pod", "payment-service"),
    "db_saturation": ("restart_service", "payment-service"),
    "pod_crash": ("restart_pod", "payment-service"),
    "latency_spike": ("restart_service", "payment-service"),
    "deployment_failure": ("rollback_deployment", "payment-service"),
    "traffic_spike": ("scale_deployment", "api-gateway"),
    "outage": ("restart_service", "payment-service"),
    "queue_backlog": ("clear_failed_job", "notification-service"),
}


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=30)
    tok = {
        u: c.post(
            "/api/auth/login", json={"username": u, "password": os.environ[f"SEED_{u.upper()}_PASSWORD"]}
        ).json()["access_token"]
        for u in ("sre", "admin")
    }
    h = {u: {"Authorization": f"Bearer {t}"} for u, t in tok.items()}
    # The blast-radius guard (default 3 executions/service/10 min) would legitimately block a rapid
    # drill on one service. Raise it for the drill (audited) and restore it afterwards.
    settings = c.get("/api/settings", headers=h["admin"]).json()["settings"]
    original = settings.get("blast_radius_max_executions", {}).get("value", 3)
    c.put(
        "/api/settings",
        json={"blast_radius_max_executions": 50, "reason": "game day drill"},
        headers=h["admin"],
    ).raise_for_status()
    rows = []
    try:
        for fault, (action, target) in EXPECTED.items():
            rows.append(run_scenario(c, h, fault, action, target))
    finally:
        c.put(
            "/api/settings",
            json={"blast_radius_max_executions": original, "reason": "game day finished; restore guard"},
            headers=h["admin"],
        )
    print(f"\n{'fault':<20}{'detected':<10}{'correct RCA':<26}{'outcome':<12}MTTD / MTTR")
    for r in rows:
        print(f"{r[0]:<20}{r[1]:<10}{r[2]:<26}{r[3]:<12}{r[4]}")
    return 0 if all(r[3] == "RESOLVED" for r in rows) else 1


def reset(c: httpx.Client, h: dict) -> None:
    """Clear faults and close leftovers so each scenario starts from a healthy, incident-free system."""
    c.post("/api/simulator/clear", headers=h["sre"])
    for inc in c.get("/api/incidents?active=true", headers=h["sre"]).json():
        c.post(
            f"/api/incidents/{inc['incident_id']}/status",
            json={"status": "RESOLVED", "note": "game day reset between scenarios"},
            headers=h["sre"],
        )
    for _ in range(60):
        st = c.get("/api/system/status", headers=h["sre"]).json()
        if st["services_healthy"] == st["services_total"] and st["active_incidents"] == 0:
            break
        time.sleep(1)
    time.sleep(6)  # let rule counters reset


def fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.0f}s"


def run_scenario(
    c: httpx.Client, h: dict, fault: str, action: str, target: str
) -> tuple[str, str, str, str, str]:
    reset(c, h)
    c.post("/api/simulator/inject", json={"fault": fault}, headers=h["sre"]).raise_for_status()
    inc = None
    for _ in range(60):
        pend = [
            i
            for i in c.get("/api/incidents?active=true", headers=h["sre"]).json()
            if i["remediation_status"] == "PENDING_APPROVAL"
        ]
        if pend:
            inc = pend[0]
            break
        time.sleep(1)
    if not inc:
        return (fault, "no", "", "", "")
    d = c.get(f"/api/incidents/{inc['incident_id']}", headers=h["sre"]).json()
    rem = next(r for r in d["remediations"] if r["status"] == "PROPOSED")
    correct = (rem["action"], rem["target_service"]) == (action, target)
    c.post(
        f"/api/remediations/{rem['id']}/approve",
        json={"reason": "game day"},
        headers=h["admin" if rem["risk"] == "HIGH" else "sre"],
    )
    for _ in range(60):
        d = c.get(f"/api/incidents/{inc['incident_id']}", headers=h["sre"]).json()
        if d["status"] in ("RESOLVED", "CLOSED") or d["remediation_status"] == "FAILED":
            break
        time.sleep(1)
    return (
        fault,
        "yes",
        "yes" if correct else f"no ({rem['action']})",
        d["status"],
        f"{fmt(d.get('time_to_detect_seconds'))} / {fmt(d.get('time_to_resolve_seconds'))}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
