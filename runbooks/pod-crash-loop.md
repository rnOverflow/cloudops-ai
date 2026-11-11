---
slug: pod-crash-loop
title: Pod Crash Loop (CrashLoopBackOff)
severity: HIGH
tags: [kubernetes, pod, crash, crashloopbackoff, restarts]
symptoms: [restart count increasing, CrashLoopBackOff, exit code 137, reduced ready replicas]
actions: [restart_pod, rollback_deployment]
summary: A single crash-looping pod on bad node-local state is deleted; all pods crashing after a release means rollback.
---
# Pod Crash Loop

## Detection
`POD_CRASHLOOP` fires when restarts increase by ≥3 within ~10 samples.

## Triage
1. `get_pod_status` — how many pods? Which node? Last termination reason?
2. **One pod** crashing while siblings are healthy → corrupted node-local state (cache volume, bad node).
3. **All pods** crashing after a deploy → application defect → `rollback_deployment`.

## Remediation
- `restart_pod` (LOW) deletes the pod; the scheduler places a fresh replica. Autonomous-eligible.

## Verification
All replicas Ready and restart counter stable for 5 samples.
