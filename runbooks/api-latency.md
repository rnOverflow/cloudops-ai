---
slug: api-latency
title: API Latency Degradation
severity: MEDIUM
tags: [latency, p95, slow, thread pool, timeouts]
symptoms: [p95 latency above 500ms, thread pool exhausted, slow request logs, upstream timeouts]
actions: [restart_service, scale_deployment]
summary: Find where latency originates (own process vs dependency) before acting on the service that alerted.
---
# API Latency Degradation

## Detection
`HIGH_LATENCY` fires when p95 > 500 ms for 3 samples.

## Triage
1. Walk the dependency graph (`get_service_dependencies`). If a **downstream** service is slow,
   the alerting service is a victim — investigate the dependency instead.
2. If CPU is normal and dependencies are healthy, look for `threadpool_exhausted`: requests are
   queuing for a worker, typically after a stuck downstream call held threads.
3. If CPU is high and traffic elevated, this is capacity — scale out.

## Remediation
- Thread-pool starvation: `restart_service` (MEDIUM).
- Capacity: `scale_deployment` (MEDIUM).

## Verification
p95 < 500 ms on the root-cause service and its callers.
