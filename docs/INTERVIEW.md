# CloudOps AI — Interview Package

## 1. Two-minute project explanation

CloudOps AI is an AIOps and SRE platform I built to automate the first ten minutes of an incident.
It answers four questions: what is wrong, why, what should we do, and can the system fix it safely?

It runs a control loop every couple of seconds. The loop collects metrics and structured logs from a
cloud provider and runs threshold rules with "for" durations, plus a robust statistical anomaly
detector. It then correlates the signals along the service dependency graph, so a database problem
becomes one incident rather than five.

An AI agent investigates each incident through eleven read-only, allow-listed tools: health, metrics,
logs, deployments, pods, database, dependencies, SLOs, runbooks. The key design choice is that facts
are extracted by code, never by the model. The output separates observed facts from AI inference,
cites the tool behind every fact, gives a confidence, retrieves the relevant runbook, and recommends
one of five allow-listed actions.

A policy engine, not the AI, assigns risk. Low-risk actions such as restarting a single pod can run on
autopilot. Everything else needs an SRE, and high-risk actions such as a rollback need an admin.
After execution, the incident is only resolved if fresh telemetry proves recovery. I tested that with
a deliberately wrong fix: the command succeeds but verification fails, and the agent re-investigates.

Everything is audited in a hash-chained log. It runs fully locally on a labelled simulation, and the
same code talks to AWS through a provider interface, with Terraform for ECS, RDS and CloudWatch.
There are 118 tests, including end-to-end recovery for nine failure modes, on SQLite and PostgreSQL.

## 2. Five-minute architecture explanation

1. **Provider abstraction (1 min).** Everything that touches infrastructure goes through a
   `CloudProvider` interface. It exposes collect telemetry, pods, cluster, database and deployment
   state, plus five remediation primitives. `LocalCloudProvider` wraps a discrete-time simulation of
   a Kubernetes-like platform: five services, pods with readiness and restarts, deployment history, a
   Postgres connection pool and a job queue. Metrics are derived from that state through a queueing
   model, so remediation changes the state and the next sample shows it. `AWSProvider` maps the same
   calls to ECS, CloudWatch, CloudWatch Logs and RDS. Azure or GCP would be another class.
2. **Control loop (1 min).** `ControlPlane.step()` runs: collect → ring-buffer store and Prometheus
   export → detection → correlation → investigation of new incidents → proposal → verification of due
   remediations → SLO measurements. A background thread drives it in production. Tests drive it with
   a manual clock, which makes the full workflow deterministic and testable.
3. **Detection and correlation (45 s).** There are nine rule types with consecutive-breach
   requirements and severity tiers, plus a median/MAD z-score for anomalies. Anomalies and lagging
   SLO-burn signals only corroborate; they never page alone. Signals are processed leaf-first by
   topological level, and attach to an active incident on any transitive dependency. Caller
   incidents opened slightly earlier get merged into the root-cause incident.
4. **AI agent (1 min).** The agent is a separate package that depends only on a tool protocol.
   Investigation runs in four stages:
   - deterministic evidence gathering
   - fact extraction in code
   - transparent hypothesis scoring, covering ten failure archetypes including "it's your
     dependency", which recursively investigates that dependency
   - BM25 runbook retrieval

   An optional OpenAI-compatible LLM can call further read-only tools and propose a root cause. Its
   JSON is validated against the action allow-list, real targets and parameter bounds, and anything
   invalid is discarded.
5. **Remediation and verification (45 s).** The policy engine sets risk and the approval level, and
   enforces a blast-radius guard (rate per service, no concurrent actions on one service). Before
   execution it snapshots state. N samples later, verification re-checks every symptom signal, pod
   readiness and action-specific facts such as "running version is v2.4.1". It resolves on success;
   on failure it re-investigates and never repeats a failed action.
6. **Cross-cutting (30 s).**
   - Security and storage: JWT, server-side RBAC with DB-sourced permissions, hash-chained audit,
     PostgreSQL with Alembic.
   - Interface: a React console.
   - Observability: Prometheus, Grafana, Loki, OTel.
   - Deployment: Kubernetes manifests with HPA/PDB/NetworkPolicies, and Terraform on ECS Fargate
     with no NAT gateway to keep cost low.
   - CI: GitHub Actions with security and container scanning.

## 3. Technology justification

| Choice | Why | Alternative considered |
|---|---|---|
| Python + FastAPI | Async-capable, Pydantic validation, auto OpenAPI, the ecosystem for AI/ops tooling | Go (better for agents/daemons; slower to iterate on AI logic) |
| PostgreSQL + SQLAlchemy 2 + Alembic | Relational integrity for incidents/audit, JSON columns for evidence, migrations | MongoDB (weaker integrity guarantees for an audit trail) |
| React + TypeScript + Tailwind | Typed API contracts, fast dense UI building | Grafana-only (great for metrics, poor for approval workflows) |
| Prometheus + Grafana + Loki + OTel | CNCF standard, pull-based metrics, cheap label-indexed logs, vendor-neutral traces | ELK (heavier), Datadog (cost, lock-in) |
| Rule + MAD anomaly detection | Explainable, no training data, robust to outliers | Isolation forest / LSTM (opaque, data-hungry, hard to defend in a postmortem) |
| BM25 runbook retrieval | Small jargon-heavy corpus, no external model, explainable | Embeddings + vector DB (overkill at 10 documents; swappable later) |
| OpenAI-compatible LLM, optional | Works with OpenAI, Azure OpenAI, Ollama, vLLM; platform still works without | Hard dependency on one vendor |
| ECS Fargate (not EKS) on AWS | No ~$73/month control plane, no nodes to patch, Spot for stateless services | EKS (manifests kept as an overlay) |
| Terraform | Declarative, reviewable plans, huge AWS coverage | CDK/Pulumi (fine; Terraform is the lingua franca for infra interviews) |
| GitHub Actions + OIDC | No long-lived AWS keys | Jenkins (more ops burden) |

## 4. Technical interview questions and answers

**Architecture & design**

1. **Why a provider abstraction instead of coding directly against Kubernetes/AWS?**
   It lets detection, correlation, AI and remediation stay identical across environments, and it
   makes the full system testable without a cloud. Adding Azure means implementing ~12 methods.
   The cost is a lowest-common-denominator interface. For example, `clear_failed_job` isn't
   supported on AWS yet, and the provider returns an explicit failure rather than pretending.

2. **Isn't the simulation "fake"? How is that honest?**
   The simulation is labelled everywhere (`simulated: true` in every API response, plus a UI badge).
   What matters is that it behaves causally: metrics are computed from state, and remediations
   change that state. That is why a wrong fix fails verification. The demo microservices in
   Compose/K8s are real HTTP services, scraped by a real Prometheus.

3. **Walk me through what happens in one control-loop tick.**
   collect → ingest into ring buffers → export Prometheus gauges → evaluate rules/anomalies →
   correlate into incidents → investigate new incidents → propose remediations → verify any
   remediation whose verification tick has arrived → auto-resolve incidents that self-recovered →
   write SLO measurements.

4. **Why is the backend a singleton? How would you scale it?**
   The control loop, the hot telemetry store and the simulation are in-process. To scale:
   - Leader election (K8s Lease or `pg_advisory_lock`) so only one replica runs the loop.
   - Stateless API replicas behind it.
   - Hot telemetry served from Prometheus or Redis.
   - Rate limiting in Redis.
   - Investigations moved to a work queue.

5. **How do you avoid alert storms when one dependency fails?**
   - Process signals leaf-first by topological level.
   - Attach a symptom to an active incident on any transitive sync dependency.
   - Merge caller incidents opened a moment earlier into the root-cause incident.
   - Anomalies and SLO-burn signals only corroborate.
   - Rules require consecutive breaches.

   The e2e tests assert exactly one incident for every failure mode.

**Detection & SRE**

6. **Why median/MAD instead of mean/stddev?**
   The outliers I'm trying to detect inflate the standard deviation and hide themselves. Median
   and MAD have a 50 % breakdown point. I also require |z| > 6 for three samples *and* a >50 %
   relative change, because MAD on very stable series is tiny.

7. **What's a `for` duration and why does it matter?**
   A rule must breach for N consecutive samples before it fires. It trades a few seconds of
   detection time for a large reduction in flapping. The unit test shows a single non-breaching
   sample resets the counter.

8. **How do you compute availability and latency SLOs?**
   - Availability is request-based: good = requests × (1 − error rate).
   - Latency is window-based: a sample is good if p95 ≤ the threshold.
   - Error budget remaining = 1 − (1 − attainment) / (1 − target).
   - Burn rate is computed over 5 min and 1 h windows.

9. **Why is SLO fast-burn excluded from verification?**
   It is a lagging indicator over a 30-sample window, and stays high for a while after the system
   has recovered. Verifying against it would mark correct fixes as failures. I found this
   empirically and encoded it as a `lagging` flag on the rule.

10. **How do you define MTTD and MTTR here?**
    - MTTD = detected_at − impact_started_at, where the first breaching sample marks the impact.
    - MTTR = resolved_at − detected_at, where resolution requires verified recovery.

    Both appear on the Overview and SLO pages.

11. **What's the multi-window burn-rate idea?**
    It comes from the Google SRE workbook. Page when burn is high over both a short and a long
    window (e.g. 14.4× over 5 min/1 h), and ticket on slower burns. The short window gives fast
    detection; the long one prevents paging on blips. The Prometheus rules implement a fast-burn alert.

12. **What happens if the control plane itself goes down?**
    `/healthz` and `/readyz` probes restart it. Prometheus alert rules mirror the detection
    thresholds, so paging continues. A `ControlLoopStalled` alert fires if the loop stops
    ticking. Incidents and audit history are in PostgreSQL, so nothing is lost.

**AI agent**

13. **What does "tool-using agent" mean in your implementation?**
    The agent observes the system only through a `ToolRegistry`: eleven named tools with JSON
    schemas. Every call is validated (unknown tools, extra args, unknown services and bad enums
    are rejected; integers are clamped), budgeted, timed and recorded. With an LLM configured, the
    model chooses additional tool calls in a loop, using OpenAI function calling.

14. **How do you prevent hallucinated telemetry?**
    The model never writes facts. Facts are generated by code from tool output and cite their
    source tool. The LLM can only add `AI_INFERENCE` statements and a proposed root cause. The
    tests check that every fact's source tool was actually called.

15. **How do you defend against prompt injection in logs?**
    Defence is in the code around the model, not in the prompt:
    - read-only tools only
    - the recommendation must be one of five allow-listed actions
    - the target must exist and parameters are bounds-checked
    - risk comes from the policy engine
    - non-LOW actions need a human

    A test injects "IGNORE PREVIOUS INSTRUCTIONS… exec_shell" into the logs and makes the mock
    model obey it; validation discards the action.

16. **Why does it work without an LLM?**
    The deterministic analyzer covers ten failure archetypes with transparent weighted scoring.
    That makes the platform usable offline, reproducible in tests, cheap, and explainable. The
    LLM refines the result; it isn't a dependency.

17. **How is confidence computed? Isn't it made up?**
    It is the top hypothesis' score, which is the sum of explicit evidence weights, capped at 0.95.
    It is reduced by 0.15 when the runner-up is within 0.15 (ambiguity). On a healthy service, a
    score below 0.7 is not reported at all. It is a calibrated heuristic, not a probability, and
    the UI shows the supporting evidence so a human can judge it.

18. **What bug did you find in the agent during testing?**
    After a successful rollback, asking "why is payment-service unhealthy?" still blamed the
    deployment at 55 %. There were two causes: it read stale log lines from before the fix, and
    it treated a rolled-back deploy as recent. The fix was a 60-sample log window, letting the
    latest ROLLBACK supersede a DEPLOY, and a healthy-service evidence gate. A regression test
    now covers it.

19. **How does root cause analysis handle dependencies?**
    A "dependency degradation" hypothesis scores high when a sync dependency is unhealthy and the
    service's own resources look normal. The agent then recursively investigates the dependency
    (depth ≤ 2). In the DB-saturation scenario the incident is on `database`, but the root cause is
    `payment-service` holding most of the connections, so the restart targets payment-service.

**Remediation & safety**

20. **Why can't the AI decide risk?**
    Risk is a policy decision with organisational accountability. Keeping it in code makes it
    reviewable and testable, and impossible to talk around via the model. For example, scaling
    down is HIGH because it removes capacity, even though it's the same action as scaling up.

21. **What exactly does verification check?**
    - Every non-lagging rule signal attached to the incident is clear (averaged over 2 samples).
    - Ready pods ≥ desired.
    - The target is not UNHEALTHY.
    - Action-specific facts: the deleted pod is gone, the running version equals the rollback
      target, the queue is draining.

    Before and after snapshots are stored and shown.

22. **What if verification fails?**
    The remediation is marked FAILED. The incident returns to INVESTIGATING and is re-investigated.
    The same action/parameters/target that failed is never re-proposed, and there is a cap of 3
    attempts per incident before escalating to a human.

23. **What's the blast-radius guard?**
    At most 3 executions per service per 10 minutes, and no concurrent remediation on the same
    service. This prevents automation from thrashing a service, e.g. a restart loop.

24. **When is autonomous mode allowed to act?**
    All of the following must hold:
    - autopilot is enabled (ADMIN only, audited)
    - the action is LOW risk (`restart_pod`, `clear_failed_job`)
    - AI confidence ≥ a configurable threshold (default 70 %)

    MEDIUM and HIGH actions always wait for a human; a test asserts that.

**Security**

25. **How is RBAC enforced?**
    Every route depends on `require(permission)`. The user's role and permissions are loaded from
    the database on each request, so a token whose role claim says ADMIN gives a viewer nothing
    (tested). HIGH-risk approval needs a separate permission held only by ADMIN.

26. **How is the audit log tamper-evident?**
    Each record stores `hash = SHA256(prev_hash + canonical JSON of fields)`.
    `/api/audit/verify` walks the chain. A test edits a historical record and checks that
    verification reports the break at that ID. I hit a real bug here: Postgres returned timestamps
    in the session timezone, which changed the hashed string. Normalising to UTC fixed it.

27. **How do you handle secrets?**
    - Secrets come only from environment variables, K8s Secrets, or AWS Secrets Manager (injected
      by ECS).
    - `bootstrap_env.sh` generates random local secrets into a gitignored, chmod-600 `.env`.
    - The API never returns secrets, and the app refuses to start without a ≥32-character JWT key.
    - CI runs gitleaks, and deploys use GitHub OIDC rather than access keys.

28. **What container hardening did you apply?**
    - Non-root UID, read-only root FS, all capabilities dropped, `no-new-privileges`.
    - Slim bases, healthchecks, Pod Security `restricted`, seccomp RuntimeDefault.
    - No service-account token automount, and default-deny NetworkPolicies.
    - Trivy scans the images in CI.

**Cloud / infrastructure**

29. **Why ECS Fargate over EKS for the AWS deployment?**
    For five small services, EKS's control-plane fee and node management cost more than the
    workload. Fargate on ARM64 with Spot for stateless services and no NAT gateway keeps it around
    $45–60/month. The Kubernetes manifests still exist, with an EKS overlay and IRSA annotation.

30. **No NAT gateway — isn't putting tasks in public subnets risky?**
    The tasks have public IPs for egress (ECR, AWS APIs), but their security group only admits
    traffic from the ALB security group and from each other. RDS is in private subnets and accepts
    connections only from the task security group. In production I'd add VPC endpoints or a NAT
    and move tasks private; it's a documented cost trade-off.

31. **How is the backend's IAM role scoped?**
    - It gets exactly the ECS actions the provider uses, conditioned on the cluster ARN.
    - It can describe and register task definitions (rollback/deploy).
    - `iam:PassRole` is restricted to the two CloudOps roles.
    - It has read-only CloudWatch metrics, `FilterLogEvents` scoped to the `/ecs/cloudops*` log
      groups, and `PutObject` on one S3 prefix for audit exports.

32. **How does rollback work on ECS?**
    Read the service's current task definition `family:rev`, then update the service to
    `family:rev-1`. The deployment circuit breaker also auto-rolls back failed rollouts. In
    Terraform, `ignore_changes` on desired count and task definition stops Terraform from fighting
    CloudOps AI's remediations.

33. **What do HPA, PDB and probes each protect against?**
    - HPA scales on CPU to absorb load.
    - PDB keeps at least one pod available during voluntary disruptions such as node drains.
    - Readiness removes a pod from traffic.
    - Liveness restarts a hung process.
    - The startup probe stops slow starts from being killed by liveness.

**Testing & delivery**

34. **How did you test the full workflow end to end?**
    A test harness creates the real FastAPI app with a manual clock and a seeded simulation, then
    drives everything through the HTTP API: inject → tick → assert one incident → check facts,
    runbook and recommendation → verify the SRE gets 403 → admin approves → tick → assert the
    verification checks and RESOLVED → assert the audit actions and chain validity. It is
    parametrised over all nine failure modes, plus autopilot, reject, wrong-fix and stale-evidence
    scenarios.

35. **What does your CI pipeline do?**
    1. Lint (ruff, tsc).
    2. Unit tests with coverage.
    3. Integration and e2e tests on a Postgres service container, after applying migrations.
    4. Security scans: bandit, pip-audit, npm audit, gitleaks, Trivy on the IaC.
    5. Docker build.
    6. Trivy scan of the container images.
    7. Terraform fmt/validate and Kustomize render.
    8. Build.
    9. On `v*` tags only: deploy via OIDC → `terraform apply` → smoke tests.

36. **What was the most interesting bug you found while running it for real?**
    In Docker Compose, the load generator fired requests without a concurrency cap. When the
    gateway slowed down, in-flight requests grew without bound and pinned it at its CPU limit, a
    self-inflicted overload spiral. The fix was a semaphore with load shedding (counting dropped
    arrivals) and async health endpoints. It's the same failure mode as a retry storm in
    production.

37. **What did the game day and the Kubernetes deploy teach you?**
    The blast-radius guard blocked the fourth payment-service fix inside 10 minutes. The guard was
    right, but the drill had to account for it, so I made the limit an audited ADMIN setting that the
    drill raises and restores. Kubernetes exposed a portability bug: nginx hard-coded the Compose
    service name. An env-rendered nginx template fixed it, so the same image runs in both environments.

38. **What would you build next?**
    - Leader election for HA.
    - An event-driven pipeline (Kafka/SQS) between detection and investigation.
    - Change-aware detection (deploy markers in anomaly baselines).
    - Learned per-service thresholds.
    - A Kubernetes provider using client-go semantics on a real cluster.
    - Postmortem generation from the incident timeline.
    - Canary analysis before rollout.

## 5. Resume bullet points

- Built **CloudOps AI**, an AIOps/SRE platform (Python/FastAPI, PostgreSQL, React/TypeScript) that
  detects, correlates, diagnoses and auto-remediates infrastructure incidents. It **verifies recovery
  from live telemetry** before resolving; all 9 simulated failure modes recover end-to-end in tests.
- Designed a **tool-using AI investigation agent** with 11 allow-listed read-only tools that separates
  code-extracted *observed facts* from *AI inference*. It works without an LLM and validates any LLM
  output against an action allow-list, which neutralised log-borne prompt injection in tests.
- Implemented **topology-aware incident correlation** (leaf-first by dependency level, transitive
  attachment and merging), reducing multi-service failures to one incident per root cause.
- Built a **policy-gated remediation engine** with five primitives, risk tiers, RBAC (ADMIN/SRE/DEV/VIEWER),
  human approval, LOW-risk autopilot, blast-radius limits and a **SHA-256 hash-chained audit log**.
- Implemented **SLOs, error budgets, multi-window burn rates, MTTD/MTTR**, and an observability stack
  (Prometheus alert rules, Grafana, Loki, OpenTelemetry) via Docker Compose.
- Wrote **Terraform for a cost-optimised AWS footprint** (~$50/month): ECS Fargate ARM64/Spot, RDS, ALB,
  ECR, least-privilege IAM, Secrets Manager. Also wrote hardened Kubernetes manifests (HPA, PDB,
  restricted PSS, default-deny NetworkPolicies).
- Delivered **118 automated tests** (unit, RBAC, AI-safety, AWS via moto, end-to-end recovery) running
  on SQLite and PostgreSQL, plus a GitHub Actions pipeline with SAST, dependency, secret, IaC and
  container scanning.

## 6. GitHub README summary (short form)

> **CloudOps AI** — an AI-powered reliability platform that detects infrastructure incidents,
> investigates them with a tool-using agent (observed facts vs. AI inference, with sources), retrieves
> runbooks, recommends allow-listed fixes, executes them behind risk policy and human approval (or
> autopilot for low-risk actions), and **resolves only after verifying recovery from telemetry**.
> Local-first (labelled simulation; no cloud account needed), AWS-ready (ECS/CloudWatch/RDS via
> Terraform), with SLOs, error budgets, MTTD/MTTR, RBAC, a hash-chained audit log, and the
> Prometheus/Grafana/Loki/OpenTelemetry stack. FastAPI · PostgreSQL · React · Kubernetes · Terraform ·
> GitHub Actions · 118 tests.

## 7. Live demo script (5–10 min)

See **[DEMO.md](../DEMO.md)** for the timed, click-by-click script. The short version:

1. **Healthy overview** (30 s): 5/5 healthy, simulation badge, dependency map.
2. **Simulate Deployment Failure** (30 s).
3. **Incident** (60 s): one CRITICAL incident within seconds, gateway attached as correlated impact,
   and the lifecycle timeline.
4. **Evidence** (90 s): facts with sources, hypotheses, 10 tool calls, the runbook.
5. **Approval** (60 s): HIGH risk; SRE is denied, admin approves with a reason.
6. **Verification** (60 s): errors 29.6 % → 0.02 %, version v2.4.1, RESOLVED.
7. **Audit** (45 s): the full trail including the denied attempt, and the chain verified.
8. **Autopilot** (90 s): pod crash fixed with no human; high CPU still waits for approval.
9. **Wrap** (30 s): SLO burn, MTTD/MTTR, and the AWS Terraform.
