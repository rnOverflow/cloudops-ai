# Live Demo Script (5–10 minutes)

**Setup (before the audience joins):** `make dev-backend` + `make dev-frontend` (or `make up`), wait
~60 s for baselines, open the UI, sign in as `sre` in one window and `admin` in a private window.
Credentials are in `demo-credentials.txt`. Optional: `make up-all` and open Grafana on :3001.

Prefer a terminal-only run? `make demo` executes the same flow through the API and prints each stage.

---

### 0:00 — The problem (30 s)
> "At 3 a.m. the on-call engineer needs four answers: what's broken, why, what to do, and whether
> it's safe to let automation do it. CloudOps AI answers all four and proves the fix worked."

### 0:30 — Healthy system (60 s) — *Overview*
- 5/5 services healthy, no incidents. Point at the **LOCAL SIMULATION** badge: "Everything you see is
  computed from a simulated cluster; the same code talks to AWS through a provider interface."
- Dependency map: gateway → user/payment → database; payment → notification (async).
- Header: control loop sample counter ticking every 2 s; autopilot is **off**; AI is the local analyzer.

### 1:30 — Break payment-service (30 s) — *Failure Simulator*
- Click **Simulate Deployment Failure**. "This rolls out v2.5.0 with a real defect: ~28 % of capture
  requests throw. It's recorded as a deployment by `sre`, exactly like a real release."

### 2:00 — Detection and correlation (60 s) — *Incidents → INC-xxxx*
- One CRITICAL incident within ~4 s. Time-to-detect shown.
- "api-gateway *also* breached its error threshold, but it's attached as **correlated impact**, not a
  second incident. Detection walks the dependency graph leaf-first."
- Show the **lifecycle timeline**: Detection → Investigation → Root cause → Recommendation done;
  Approval pulsing.

### 3:00 — The investigation (90 s) — *View evidence*
- **Observed facts** (green) — each cites the tool it came from: error rate 25 % vs 0.03 % baseline,
  "DEPLOY v2.4.1 → v2.5.0 60 s ago", 75 `unhandled_exception` log lines tagged v2.5.0.
- **AI inference** (violet) — ranked hypotheses with their supporting evidence and scores.
- **Tool calls** — 10 read-only calls in order. "The model never runs commands and never writes facts."
- **Runbook** — Deployment Failure, retrieved by BM25.

### 4:30 — Human approval (60 s) — *Approval panel*
- Recommended `rollback_deployment()`, **HIGH risk** (policy engine, not the AI), expected impact,
  AI confidence 90 %.
- Try **Approve** as `sre` → *"HIGH-risk remediation requires ADMIN approval"* (and it's audited).
- Switch to `admin`, enter a reason, **Approve & execute**.

### 5:30 — Verification (60 s) — *Overview tab of the incident*
- Status MITIGATING → five samples later RESOLVED.
- **Verification card**: `HIGH_ERROR_RATE cleared on payment-service 29.6 % → 0.02 %`,
  `cleared on api-gateway`, `running version is v2.4.1`, `3/3 pods ready`.
- "We never trust exit codes. Success means the telemetry recovered."

### 6:30 — Audit trail (45 s) — *Audit Logs*
- Every step: simulator inject, deployment, incident created, AI investigation (with confidence),
  proposal, the **denied** SRE approval, admin approval, rollback, verification, resolution.
- **Chain verified** badge — "each record hashes the previous one; editing history breaks the chain."

### 7:15 — Autopilot for low-risk fixes (90 s) — *Settings → Simulator*
- As admin, enable **Autopilot for LOW-risk actions**.
- **Simulate Pod Crash** → incident → `restart_pod` (LOW, 85 % confidence) executes automatically →
  verified → resolved with no human. Decided-by: `autopilot`.
- **Simulate High CPU** → `restart_service` is MEDIUM → still waits for a human.

### 8:45 — Verification catches a bad human decision (optional, 60 s)
- With High CPU active, reject the AI's restart and instead propose `scale_deployment(5)` from the API
  (or `make e2e` shows the test). Scaling runs fine, but verification **fails** (runaway threads burn CPU
  regardless of replicas), the incident returns to INVESTIGATING, and the agent re-proposes the restart.

### 9:30 — Wrap (30 s) — *SLO / Reliability*
- Error budget burned by the incident, burn rates, MTTD/MTTR now populated.
- "Same platform runs on AWS via Terraform: ECS Fargate, CloudWatch, RDS, least-privilege IAM."

---

## Backup plan
- If the UI misbehaves: `make demo` (terminal walk-through of the same flow).
- If time is short: Overview → inject → incident detail (evidence + approve) → verification → audit.
