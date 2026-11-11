---
slug: queue-backlog
title: Queue Backlog
severity: MEDIUM
tags: [queue, backlog, worker, job, poison message, dead letter]
symptoms: [queue depth growing, oldest message age increasing, a job failing repeatedly, worker throughput near zero]
actions: [clear_failed_job, scale_deployment]
summary: A poison job blocking workers is moved to the dead-letter queue; genuine load is handled by scaling workers.
---
# Queue Backlog

## Detection
`QUEUE_BACKLOG` fires when depth > 500 for 2 samples.

## Triage
1. Is throughput ~0 while workers are healthy? Look for `job_failed_retrying` — a poison job.
2. Is throughput normal but incoming higher? That is load; scale workers.

## Remediation
- Poison job: `clear_failed_job(job_id)` (LOW) moves it to the DLQ. Autonomous-eligible.
- Load: `scale_deployment` workers.

## Verification
Queue depth decreasing for 5 consecutive samples; worker throughput > 0.
