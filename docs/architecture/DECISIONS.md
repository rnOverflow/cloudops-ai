# Architecture Decision Records

Each record states the context, the decision, and its consequences. They are written to
be defensible in a design review, including the trade-offs we knowingly accepted.

---

## ADR-001 — Local-first: a simulated cloud behind a provider abstraction

**Context.** The platform must be fully demonstrable without AWS credentials, and its
interesting behaviour (detection → diagnosis → remediation → verification) depends on
infrastructure that can *fail on demand* and *respond to remediation*.

**Decision.** All infrastructure access goes through `CloudProvider`
(`backend/app/cloud/base.py`). `LocalCloudProvider` wraps a discrete-time simulation
(`cloud/local/simulation.py`) of five services, their pods, a deployment history, a
shared PostgreSQL connection pool and a job queue. `AWSProvider` implements the same
interface on ECS/CloudWatch/CloudWatch Logs/RDS.

**Consequences.**
- Telemetry is *computed from modelled state* (traffic, replicas, faults, pool usage), so
  remediation changes state, and verification reads the change back. Nothing is scripted to
  "look fixed".
- Every API response carries `provider` and `simulated` flags; the UI labels simulated data.
- Azure/GCP need only a new provider class; detection, incidents, AI and remediation are untouched.
- Simulation fidelity is necessarily simplified (queueing model, linear CPU), documented in OPERATIONS.md.

## ADR-002 — FastAPI + SQLAlchemy 2 + PostgreSQL; SQLite only for fast tests

**Decision.** PostgreSQL is the system of record (Alembic migrations). The test-suite runs on
SQLite by default for speed and on PostgreSQL in CI (`TEST_DATABASE_URL`).

**Consequences.** A `UTCDateTime` type decorator normalises timezones across both engines
(SQLite drops tzinfo; PostgreSQL returns session-local offsets, which broke audit hashing
until normalised — caught by running the suite on both).

## ADR-003 — Single control loop with an injectable clock

**Context.** Detection, investigation, remediation and verification are time-dependent.

**Decision.** One `ControlPlane.step()` performs: collect → store/export → detect →
correlate → investigate → propose → verify → SLO record. A background thread calls it every
`TICK_SECONDS`; tests call it directly with a `ManualClock`.

**Consequences.** The complete demo workflow is deterministic in tests (seeded RNG + manual
clock). JWTs deliberately use wall-clock time (a test caught tokens minted with the simulated clock).

## ADR-004 — Rule-based detection with `for`-durations + robust statistical anomalies

**Decision.** Threshold rules (CPU, memory, error rate, latency, crash loops, DB saturation,
unavailability, queue backlog, SLO fast-burn) require N consecutive breaches. Anomalies use a
median/MAD robust z-score (|z| > 6 for 3 samples and > 50 % relative change).

**Why not ML.** No labelled data, poor explainability in a post-incident review, and the
outliers we want to detect would contaminate mean/stddev models. MAD is robust to them.

**Consequences.** Anomalies and lagging budget signals (SLO burn) *corroborate* but never open an
incident alone — a deliberate noise-control choice. Verification excludes lagging signals.

## ADR-005 — Topology-aware incident correlation

**Decision.** Signals are processed leaf-first by dependency level. A signal on a service whose
(transitive, non-async) dependency already has an active incident is attached to that incident.
When a dependency opens an incident after its callers did, caller incidents still awaiting action
are merged into it (status CLOSED, `SUPERSEDED`).

**Consequences.** A payment outage yields one incident with `api-gateway` as correlated impact, not
two incidents with two competing remediations. Verified in e2e tests for every failure mode.

## ADR-006 — AI agent: deterministic evidence, optional LLM reasoning, validated output

**Decision.** The agent (`ai-agent/`) is a separate package that only sees an allow-listed,
read-only `ToolRegistry` (11 tools). Investigation always:
1. Calls tools in a fixed order to gather evidence.
2. Extracts **OBSERVED_FACT**s *in code* from tool output (each cites its tool).
3. Scores transparent hypotheses (**AI_INFERENCE**) and retrieves runbooks.
4. Optionally lets an OpenAI-compatible LLM call more read-only tools and propose a root cause.
   Its JSON is schema-checked; actions must be in the remediation allow-list, targets must exist,
   parameters are bounds-checked. Invalid output is discarded with a note.

**Consequences.**
- The platform is fully functional with no API key (labelled "local analyzer, no LLM").
- The model can never fabricate telemetry: facts are not model-generated.
- Prompt injection via logs cannot cause an unsafe action (tested: injected `exec_shell` is rejected).
- Investigations are reproducible and auditable (every tool call stored).

## ADR-007 — Risk is decided by a policy engine, not by the AI

**Decision.** `remediation/policy.py` assigns risk: `restart_pod`, `clear_failed_job` = LOW;
`restart_service`, scale-up = MEDIUM; `rollback_deployment`, scale-down = HIGH. Autonomous mode may
execute LOW only, above a confidence threshold. HIGH requires ADMIN. A blast-radius guard limits
executions per service per window and forbids concurrent remediations on one service.

## ADR-008 — Verification by re-reading infrastructure

**Decision.** A remediation is `SUCCEEDED` only if, after `VERIFY_AFTER_TICKS` samples, every
non-lagging rule signal on the incident is clear, replicas are ready, action-specific checks pass
(pod replaced, version rolled back, queue draining) and the target is not UNHEALTHY. Before/after
snapshots are stored. On failure the incident returns to INVESTIGATING and is re-investigated; the
same failed action is never re-proposed.

**Consequences.** Tested with a deliberately wrong operator action (scale-out for runaway threads):
the command succeeds, verification fails, the agent proposes the correct restart.

## ADR-009 — Singleton control plane (for now)

**Decision.** The backend runs one replica (`Recreate` strategy / ECS desired=1) because the control
loop, the hot telemetry store and the local simulation are in-process.

**Scale-out path.** Leader election (Kubernetes Lease or PostgreSQL advisory lock) for the loop;
stateless API replicas; hot store moved to Prometheus/Redis; rate limiter moved to Redis.

## ADR-010 — BM25 runbook retrieval instead of embeddings

**Decision.** Pure-Python BM25 with field boosting over title/tags/symptoms/body.

**Why.** Tiny corpus, jargon-heavy vocabulary that lexical matching handles well, zero external
dependencies, explainable scores. The `BM25Index.search` interface allows a vector index later.

## ADR-011 — Security model

JWT (HS256, short TTL, issuer-checked, `alg=none` rejected); role and permissions re-read from the DB
on every request (token role claims are not trusted); bcrypt; RBAC on the server; strict Pydantic
schemas (`extra=forbid`); hash-chained append-only audit log; rate limits on login and AI; strict CORS
allow-list; security headers; non-root read-only containers; restricted Pod Security; default-deny
NetworkPolicies; secrets only from env/Secrets Manager. See SECURITY.md.

## ADR-012 — Cheapest reasonable AWS footprint

ECS Fargate (ARM64, Spot for stateless demo services) instead of EKS (~$73/month control plane);
no NAT gateway (tasks in public subnets, ALB-only ingress via security groups); single-AZ
`db.t4g.micro`; 7-day log retention; Container Insights off; optional AWS Budget alert.
Estimated ~$45–60/month while running. EKS manifests remain available as a Kustomize overlay.

## ADR-013 — Observability stack

Prometheus (metrics + alert rules mirroring detection, so paging survives a control-plane outage),
Grafana (provisioned dashboard), Loki + Promtail (structured JSON logs with `event` labels),
OpenTelemetry (FastAPI auto-instrumentation → collector → span metrics). The platform's own hot
store is a ring buffer; long-term retention belongs to Prometheus/Loki.
