---
slug: high-cpu
title: High CPU Utilisation
severity: HIGH
tags: [cpu, saturation, performance, threads]
symptoms: [CPU above 85% sustained, rising latency, hot loop warnings, throttling]
actions: [restart_service, scale_deployment]
summary: Distinguish load-driven CPU (scale out) from runaway threads (restart) before acting.
---
# High CPU Utilisation

## Detection
`HIGH_CPU` fires when average pod CPU exceeds **85% for 3 consecutive samples**.

## Triage
1. Compare throughput with its baseline (`get_metrics`).
   - **Traffic ≥ 1.8× baseline** → capacity problem. Go to *Scale out*.
   - **Traffic near baseline** → something inside the process is burning CPU. Go to *Runaway threads*.
2. Check logs for `worker_hot_loop` or long-running thread warnings.
3. Check whether a deployment happened in the last 15 minutes (regression).

## Remediation
### Runaway threads
- `restart_service` (MEDIUM risk) — rolling restart with surge, no capacity loss.
- Verify CPU returns under 70% within 5 samples; if not, capture a profile and escalate.
### Scale out
- `scale_deployment` to bring per-pod CPU to ~60%. HPA max is 10 replicas.

## Verification
CPU < 85% and p95 latency < 500 ms for the affected service.

## Escalation
Owning team on-call if CPU recurs within 1 hour of restart (likely code defect).
