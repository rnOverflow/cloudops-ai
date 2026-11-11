---
slug: service-outage
title: Service Outage
severity: CRITICAL
tags: [outage, unavailable, down, readiness, no healthy instances]
symptoms: [no ready pods, readiness probe failures, 100% errors, callers return 503]
actions: [restart_service, rollback_deployment]
summary: Restore availability first with a rolling restart; roll back if the outage followed a release.
---
# Service Outage

## Detection
`SERVICE_UNAVAILABLE` fires when ready pods = 0 for 2 samples.

## Triage
1. `get_pod_status` — are pods running but failing readiness, or not scheduled?
2. Logs: `readiness_probe_failed`, `process_exit`, bind errors.
3. Recent deployment? If yes, prefer rollback.

## Remediation
- `restart_service` (MEDIUM).
- If restart does not restore readiness within 5 samples, escalate and roll back.

## Verification
Ready pods = desired replicas; error rate < 5%; callers' error rates recover.
