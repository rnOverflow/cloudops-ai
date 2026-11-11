# Security

## Threat model (STRIDE summary)

| Threat | Example | Controls |
|---|---|---|
| **Spoofing** | Forged JWT, stolen password | HS256 with ≥32-char secret, `iss`/`exp` required, `alg=none` rejected, bcrypt (cost 12), constant-time compare with dummy hash for unknown users, login rate limit per IP, short TTL |
| **Tampering** | Edit audit history; mass-assign fields | Hash-chained audit log with `/api/audit/verify`; Pydantic `extra=forbid` on every request body; parameter allow-lists per action |
| **Repudiation** | "I never approved that rollback" | Every approval/rejection/execution/verification is audited with actor, role, IP, reason, before/after state, AI confidence |
| **Information disclosure** | Secrets in API/UI/logs | Secrets only from env / K8s Secrets / AWS Secrets Manager; never returned by `/api/settings`; `.env` and `demo-credentials.txt` gitignored; no-store cache headers |
| **Denial of service** | Login brute force, AI cost abuse | Sliding-window rate limits (login, AI); bounded query limits; tool-call budget per investigation |
| **Elevation of privilege** | Viewer triggers chaos; SRE approves HIGH risk; token says ADMIN | Server-side RBAC on every route; roles/permissions re-read from DB per request (token role claim ignored — tested); HIGH-risk approval requires `remediation:approve_high` (ADMIN) |

## AI-specific risks

| Risk | Control |
|---|---|
| Prompt injection via logs/telemetry | Tool output marked as untrusted data in the system prompt; **more importantly**, the model cannot act: recommendations are validated against the action allow-list, target existence and parameter bounds, and risk is assigned by the policy engine. A test injects `exec_shell` via logs and asserts it is discarded. |
| Fabricated telemetry | Facts are extracted by code from tool output; the model can only add labelled inferences. |
| Excessive agency | 11 read-only tools; no shell, no write tools, no network tools; schema-validated arguments; per-investigation call budget. Execution is a separate, RBAC-gated, audited path. |
| Unbounded autonomy | Autopilot limited to LOW-risk actions above a confidence threshold, off by default, ADMIN-controlled and audited; blast-radius guard. |

## RBAC matrix

| Permission | VIEWER | DEVELOPER | SRE | ADMIN |
|---|:-:|:-:|:-:|:-:|
| read | ● | ● | ● | ● |
| ai:investigate |  | ● | ● | ● |
| remediation:propose |  | ● | ● | ● |
| remediation:approve (LOW/MEDIUM) |  |  | ● | ● |
| remediation:approve_high |  |  |  | ● |
| incident:update |  |  | ● | ● |
| simulator:run |  |  | ● | ● |
| deployment:create |  |  | ● | ● |
| audit:read |  |  | ● | ● |
| settings:write / users:manage |  |  |  | ● |

## Platform hardening

- **HTTP:** strict CORS allow-list (no wildcard, no credentials), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP, `Cache-Control: no-store`, request IDs.
- **Containers:** non-root UID 10001, read-only root FS, `no-new-privileges`, all capabilities dropped, minimal slim/alpine bases, healthchecks.
- **Kubernetes:** Pod Security `restricted`, `automountServiceAccountToken: false`, seccomp `RuntimeDefault`, resource limits, default-deny NetworkPolicies with explicit allows, PDBs.
- **AWS:** least-privilege task role (exact ECS/CloudWatch/Logs actions, ECS calls conditioned on the cluster ARN, `iam:PassRole` restricted to two roles), RDS private and encrypted, S3 public access blocked + SSE + versioning, ECR immutable tags + scan on push, secrets in Secrets Manager, ALB drops invalid headers, TLS 1.3 policy when a certificate is supplied, CI deploys via GitHub OIDC (no long-lived keys).
- **Demo services:** chaos endpoints are disabled unless `CHAOS_TOKEN` is set and are compared in constant time.
- **Frontend:** runbook markdown is rendered to React elements (no `dangerouslySetInnerHTML`); the token is kept in `sessionStorage` (cleared with the tab).

## Supply chain / CI

bandit (SAST), pip-audit, npm audit, gitleaks (secrets), Trivy (IaC config + container images, fails on fixable HIGH/CRITICAL).

## Known limitations

- The in-process rate limiter is per replica; use Redis when scaling out.
- JWTs are bearer tokens without server-side revocation (mitigated by short TTL); add a deny-list or move to opaque sessions for production.
- `sessionStorage` tokens are readable by injected script; the CSP and React's escaping mitigate XSS, an HttpOnly-cookie + CSRF-token design is the next step.

## Reporting

Please report vulnerabilities privately to the maintainers rather than opening a public issue.
