---
slug: high-memory
title: High Memory / Memory Leak
severity: MEDIUM
tags: [memory, leak, oom, gc, heap]
symptoms: [pod memory above 85% of limit, memory steadily rising, GC pressure warnings, OOMKilled]
actions: [restart_pod, restart_service]
summary: A single leaking pod is replaced with restart_pod; fleet-wide growth indicates a code leak needing rollback or fix.
---
# High Memory / Memory Leak

## Detection
`HIGH_MEMORY` fires when the **highest pod** exceeds 85% of its memory limit for 3 samples.

## Triage
1. `get_pod_status` — is it one pod (outlier) or all pods?
2. Look for `gc_pressure` log events; GC thrash raises p95 latency before OOM.
3. Check recent deployments: a fleet-wide rise after a release is a code leak.

## Remediation
- **Single pod outlier**: `restart_pod` (LOW risk). Safe for autonomous mode — siblings keep serving.
- **All pods rising**: `restart_service` buys time; open a defect and consider `rollback_deployment`.

## Verification
Replacement pod Ready, max pod memory < 85%, latency back to baseline.

## Follow-up
Capture a heap dump from the next occurrence before restarting (set `HEAP_DUMP_ON_OOM=true`).
