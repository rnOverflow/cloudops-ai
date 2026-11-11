---
slug: disk-exhaustion
title: Disk Exhaustion
severity: HIGH
tags: [disk, storage, volume, full, logs]
symptoms: [disk usage above 90%, no space left on device, write failures, log rotation failures]
actions: [restart_pod]
summary: Free space safely (logs, temp files), expand the volume if growth is organic, and fix runaway writers.
---
# Disk Exhaustion

## Detection
Volume usage > 90% (node-exporter `node_filesystem_avail_bytes`) or `ENOSPC` errors in logs.

## Triage
1. Identify the volume and the writer (application logs, temp files, WAL).
2. Is growth organic (data) or runaway (log loop, unrotated files)?

## Remediation
- Ephemeral storage on a single pod: `restart_pod` (LOW) — ephemeral volume is recreated.
- Persistent volumes: expand the PVC (manual change, not automated by CloudOps AI).
- Database WAL growth: check replication slots before anything else.

## Verification
Usage < 75% and no `ENOSPC` errors for 10 minutes.
