# Operations Guide

## Components and ports

| Component | Port | Health | Notes |
|---|---|---|---|
| Backend API + control loop | 8000 | `/healthz` (liveness), `/readyz` (DB reachable) | Singleton (ADR-009). Prometheus metrics at `/metrics`. OpenAPI at `/api/docs`. |
| Frontend (nginx) | 8080 in container, 3000 on host | `/` | Proxies `/api/` to the backend. |
| PostgreSQL | 5432 | `pg_isready` | Migrations run on backend start (`alembic upgrade head`). |
| Prometheus / Grafana / Loki / OTel | 9090 / 3001 / 3100 / 4318 | — | Compose only; K8s assumes an `observability` namespace. |

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://localhost:5432/cloudops_ai` | SQLAlchemy URL |
| `JWT_SECRET` | *(required, ≥32 chars)* | HS256 signing key — app refuses to start without it |
| `JWT_TTL_MINUTES` | 60 | Access-token lifetime |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allow-list (`*` is ignored) |
| `CLOUD_PROVIDER` | `local` | `local` or `aws` |
| `TICK_SECONDS` | 2 | Control-loop interval (AWS enforces ≥ 60: CloudWatch granularity) |
| `VERIFY_AFTER_TICKS` | 5 | Samples to wait before verifying a remediation |
| `SIMULATION_SEED` | — | Deterministic simulation (tests) |
| `LLM_PROVIDER` / `OPENAI_*` | `none` | Optional LLM (OpenAI-compatible) |
| `SEED_DEMO_USERS` + `SEED_*_PASSWORD` | false | Create local demo accounts (never in production) |
| `LOGIN_RATE_LIMIT_PER_MINUTE` / `AI_RATE_LIMIT_PER_MINUTE` | 10 / 20 | Abuse protection |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Enable tracing |
| `AWS_*` | — | See `.env.example` |

Runtime settings changed from the UI (ADMIN, audited): `autonomous_mode`, `autonomous_min_confidence`
(default 0.7), `max_remediations_per_incident` (default 3), `blast_radius_max_executions` (default 3).

## Detection rules

| Rule | Condition | For | Severity |
|---|---|---|---|
| HIGH_CPU | avg pod CPU > 85 % | 3 samples | MEDIUM (HIGH ≥ 97 %) |
| HIGH_MEMORY | max pod memory > 85 % of limit | 3 | MEDIUM (HIGH ≥ 95 %) |
| HIGH_ERROR_RATE | error rate > 5 % | 2 | HIGH (CRITICAL ≥ 20 %) |
| HIGH_LATENCY | p95 > 500 ms | 3 | MEDIUM (HIGH ≥ 1.5 s) |
| POD_CRASHLOOP | ≥ 3 restarts within ~10 samples | 1 | HIGH |
| DB_CONNECTION_SATURATION | connections > 85 % of max | 2 | HIGH (CRITICAL ≥ 97 %) |
| SERVICE_UNAVAILABLE | 0 ready pods | 2 | CRITICAL |
| QUEUE_BACKLOG | depth > 500 | 2 | MEDIUM (HIGH ≥ 3000) |
| SLO_FAST_BURN | 30-sample error ratio ≥ 14.4× a 99.9 % budget | 3 | HIGH (lagging; corroborates only) |
| ANOMALY_* | robust z > 6 for 3 samples and > 50 % change | 3 | MEDIUM (corroborates only) |

Thresholds live in `backend/app/detection/engine.py` and are mirrored in
`observability/prometheus/alerts.yml` so paging survives a control-plane outage.

## Remediation policy

| Action | Risk | Autopilot? | Approver |
|---|---|---|---|
| `restart_pod(pod)` | LOW | yes (if confidence ≥ threshold) | SRE / ADMIN |
| `clear_failed_job(job_id)` | LOW | yes | SRE / ADMIN |
| `restart_service()` | MEDIUM | no | SRE / ADMIN |
| `scale_deployment(replicas)` up | MEDIUM | no | SRE / ADMIN |
| `scale_deployment(replicas)` down | HIGH | no | ADMIN |
| `rollback_deployment()` | HIGH | no | ADMIN |

Guards: replicas 1–10; ≤ `blast_radius_max_executions` (default 3, ADMIN setting) executions per service per 10 minutes; one in-flight remediation per
service; ≤ 3 attempts per incident; an action that failed verification is never re-proposed.

## Simulation model (LocalCloudProvider)

Each sample: traffic (diurnal + noise) → per-service utilisation `rps / (ready_pods × capacity)` →
CPU and queueing latency `base × (0.7 + 0.3/(1-u))` → dependency latency/error propagation (sync
calls), database pool pressure (connections = pods × pool + rps × hold time + leaked) → error rate
(load shedding, DB rejection, defective versions, upstream failures) → structured log events.

| Fault | Effect | Fix that verification accepts |
|---|---|---|
| high_cpu | +70 % CPU on every pod regardless of load | restart_service (scaling out does **not** fix it) |
| memory_leak | one pod grows towards its limit; GC latency | restart_pod (that pod) |
| db_saturation | payment-service leaks 7 connections/sample | restart_service(payment-service) |
| pod_crash | one pod CrashLoopBackOff | restart_pod (that pod) |
| latency_spike | thread-pool starvation (+1.9 s p95) | restart_service |
| deployment_failure | defective release (+28 % errors) | rollback_deployment |
| traffic_spike | 3.5× edge traffic | scale_deployment(api-gateway) |
| outage | all pods fail readiness | restart_service |
| queue_backlog | poison job blocks the worker | clear_failed_job(job_id) |

## Runbooks

Markdown with YAML front matter in `runbooks/`. They are upserted into the database on start.
Required front matter: `slug`, `title`, `actions` (must be allow-listed actions). Add a file and
restart — retrieval picks it up automatically.

## Day-2 tasks

- **Rotate JWT secret:** update the secret, restart the backend; all sessions are invalidated.
- **Database migrations:** `make migrate` (Compose/K8s run them on container start).
- **Audit integrity:** `GET /api/audit/verify` (also shown on the Audit page).
- **Retention:** SLO samples older than the SLO window are pruned automatically.
- **Game day:** `uv run python automation/game_day.py --base http://localhost:8000` runs all failure
  modes and prints a scorecard (detected / correct RCA / recovered / MTTD / MTTR). It raises the
  blast-radius limit for the drill (audited) and restores it afterwards — otherwise the guard would,
  correctly, block the 4th rapid fix on payment-service and hand the incident to a human.
- **Kubernetes (local):** `make k8s-local` / `make k8s-down`. The frontend's API upstream is set with
  `BACKEND_URL` (nginx template), `http://backend:8000` in Compose and `http://cloudops-backend:8000` in K8s.

## Troubleshooting

| Symptom | Check |
|---|---|
| Backend exits at start | `JWT_SECRET` set and ≥ 32 chars? DB reachable? |
| UI shows "Control loop error" | `GET /api/system/status` → `control_loop_error`; backend logs |
| No incidents after injecting a fault | Rules need 2–3 consecutive samples (4–6 s at default tick) |
| Remediation stuck in VERIFYING | Verification runs after `VERIFY_AFTER_TICKS` samples; is the loop ticking? |
| 429 on login | Login rate limit (per IP, per minute) |
| AWS provider shows zeros | No CloudWatch datapoints yet (1-minute granularity) — the provider reports gaps, it does not invent values |

## Backup & recovery

PostgreSQL holds incidents, audit, remediations, SLO history. Use RDS automated backups (7 days in
Terraform) or `pg_dump`. The hot telemetry ring buffer is intentionally ephemeral; Prometheus/Loki
hold long-term telemetry.
