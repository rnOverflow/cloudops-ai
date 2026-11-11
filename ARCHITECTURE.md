# CloudOps AI — Architecture

## System overview

```mermaid
flowchart TB
    subgraph Infra["Cloud infrastructure (CloudProvider)"]
        LP["LocalCloudProvider<br/>(simulated K8s: 5 services, pods,<br/>deployments, DB pool, queue)"]
        AWS["AWSProvider<br/>(ECS Fargate · CloudWatch · Logs · RDS)"]
        FUT["Azure / GCP<br/>(future providers)"]
    end

    subgraph CP["Control plane (FastAPI backend)"]
        LOOP["Control loop<br/>step() every TICK_SECONDS"]
        STORE["Telemetry store<br/>(ring buffers)"]
        DET["Detection engine<br/>rules + robust anomalies"]
        INC["Incident manager<br/>topology-aware correlation"]
        AGENT["AI investigation agent<br/>(read-only tools)"]
        RB["Runbook retrieval<br/>(BM25)"]
        POL["Policy engine<br/>risk · RBAC · blast radius"]
        REM["Remediation engine"]
        VER["Verification"]
        SLO["SLO / reliability"]
        AUD["Hash-chained audit log"]
    end

    subgraph Obs["Observability"]
        PROM["Prometheus"] --> GRAF["Grafana"]
        LOKI["Loki"] --> GRAF
        OTEL["OTel Collector"] --> PROM
    end

    UI["React operations console"] -->|REST + JWT| CP
    LP & AWS -->|metrics · logs · events| LOOP
    LOOP --> STORE --> DET --> INC --> AGENT
    AGENT --> RB
    AGENT -->|recommendation| POL
    POL -->|LOW + autopilot| REM
    POL -->|otherwise| HUMAN{"Human approval"}
    HUMAN -->|approve| REM
    REM -->|restart / scale / rollback / clear job| Infra
    REM --> VER -->|re-read telemetry| STORE
    VER -->|pass| RESOLVED["Incident RESOLVED"]
    VER -->|fail| AGENT
    INC & REM & VER & HUMAN --> AUD
    LOOP --> SLO
    CP -->|/metrics| PROM
    CP -->|OTLP traces| OTEL
    CP -->|JSON logs| LOKI
    DB[("PostgreSQL")] --- CP
```

## Repository layout

| Path | Purpose |
|---|---|
| `backend/app/control_plane.py` | Orchestrates the loop: detect → correlate → investigate → propose → execute → verify → resolve |
| `backend/app/cloud/` | `CloudProvider` interface, `LocalCloudProvider` + simulation, `AWSProvider` |
| `backend/app/detection/` | Threshold rules with `for`-durations, MAD anomaly detection, health model |
| `backend/app/remediation/policy.py` | Allowed actions, parameter validation, risk assessment |
| `backend/app/slo/` | SLO definitions, error budgets, burn rates, MTTD/MTTR |
| `backend/app/runbooks/` | Runbook parsing and BM25 retrieval |
| `backend/app/core/` | Config, clock, JWT/RBAC, hash-chained audit, rate limiting, JSON logging |
| `backend/app/api/` | REST API (OpenAPI at `/api/docs`) |
| `ai-agent/cloudops_agent/` | Agent: tool registry, analyzer (facts + hypotheses), investigator, LLM provider |
| `frontend/` | React + TypeScript + Tailwind console (13 pages) |
| `services/` | Real demo microservice (one image, four roles) with chaos endpoints + load generator |
| `runbooks/` | Markdown runbooks with YAML front matter (loaded into the DB) |
| `observability/` | Prometheus (+ alert rules), Grafana provisioning, Loki, Promtail, OTel collector |
| `infrastructure/kubernetes/` | Kustomize base + local/aws overlays |
| `infrastructure/terraform/aws/` | VPC, ECS Fargate, RDS, ALB, ECR, IAM, S3, CloudWatch, Secrets Manager, Budgets |
| `automation/` | Game-day runner |
| `tests/` | unit · integration · e2e |

## The control loop

```mermaid
sequenceDiagram
    autonumber
    participant P as CloudProvider
    participant L as Control loop
    participant D as Detection
    participant I as Incidents
    participant A as AI agent
    participant R as Policy + Remediation
    participant H as Human (SRE/ADMIN)
    participant V as Verification

    loop every TICK_SECONDS
        L->>P: collect()
        P-->>L: metrics + structured logs
        L->>D: evaluate(rules, anomalies)
        D-->>L: signals
        L->>I: correlate (leaf-first, dependency graph)
        I-->>L: new incident(s)
        L->>A: investigate(service)
        A->>A: 10+ read-only tool calls → facts → hypotheses → runbooks
        A-->>L: root cause, confidence, recommendation
        L->>R: propose (policy assigns risk)
        alt LOW risk and autopilot on and confidence ≥ threshold
            R->>P: execute
        else otherwise
            R-->>H: approval request (evidence, risk, impact, confidence)
            H->>R: approve / reject (+ reason)
            R->>P: execute
        end
        L->>V: after N samples
        V->>P: re-read telemetry, pods, versions
        V-->>I: SUCCESS → RESOLVED / FAILED → re-investigate
    end
```

## Incident lifecycle

```mermaid
stateDiagram-v2
    [*] --> OPEN: rule signal (N consecutive breaches)
    OPEN --> INVESTIGATING: agent starts
    INVESTIGATING --> MITIGATING: remediation approved / autopilot
    MITIGATING --> RESOLVED: verification passed
    MITIGATING --> INVESTIGATING: verification failed (re-investigate)
    INVESTIGATING --> RESOLVED: signals clear for 10 samples (self-recovered)
    OPEN --> CLOSED: merged into downstream root-cause incident
    RESOLVED --> CLOSED: post-incident review
    RESOLVED --> INVESTIGATING: reopened
```

`remediation_status` tracks the action independently: `NONE → PENDING_APPROVAL → EXECUTING → VERIFYING → SUCCEEDED | FAILED | REJECTED | SUPERSEDED`.

## AI investigation design

```mermaid
flowchart LR
    Q["Question / incident"] --> G["Evidence gathering<br/>health · metrics · logs · deployments<br/>dependencies · pods · DB · SLO · incidents"]
    G --> F["Fact extraction (code)<br/>OBSERVED_FACT + source tool"]
    F --> H["Hypothesis scoring<br/>transparent weights → AI_INFERENCE"]
    H -->|dependency is root cause| G
    H --> RB["Runbook retrieval (BM25)"]
    RB --> REC["Recommendation<br/>(allow-listed action)"]
    H -. optional .-> LLM["LLM reasoning<br/>+ more read-only tool calls"]
    LLM --> VAL{"Schema + allow-list<br/>+ bounds validation"}
    VAL -->|valid| REC
    VAL -->|invalid| DROP["Discard, keep deterministic result"]
```

Hypotheses covered: faulty deployment, DB connection leak, single-pod memory leak, crash loop,
runaway CPU, traffic saturation, outage, thread-pool starvation, dependency degradation (walks the
graph to the dependency and investigates it), queue backlog with a poison job.

## Data model

```mermaid
erDiagram
    ROLES ||--o{ USERS : has
    SERVICES ||--o{ INCIDENTS : affects
    INCIDENTS ||--o{ INCIDENT_EVENTS : timeline
    INCIDENTS ||--o{ REMEDIATIONS : "remediated by"
    INCIDENTS ||--o{ AI_INVESTIGATIONS : "investigated by"
    SLO_DEFINITIONS ||--o{ SLO_MEASUREMENTS : measures
    SERVICES ||--o{ DEPLOYMENTS : "deployed as"
    AUDIT_LOGS }o--|| AUDIT_LOGS : "prev_hash chain"
    RUNBOOKS
    SYSTEM_SETTINGS
```

## Deployment topologies

| Mode | How | Provider |
|---|---|---|
| Developer | `make dev-backend` + `make dev-frontend`, local PostgreSQL | local (simulated) |
| Docker Compose | `make up` (platform + Prometheus/Grafana/Loki/OTel); `make up-all` adds real demo services + load | local (simulated) + real demo services observed by Prometheus |
| Kubernetes | `kubectl apply -k infrastructure/kubernetes/overlays/local` | local |
| AWS | `terraform apply` in `infrastructure/terraform/aws` | aws (ECS/CloudWatch/RDS) |

See [docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md) for the reasoning behind each choice.
