---
slug: high-error-rate
title: High Error Rate
severity: HIGH
tags: [errors, 5xx, error rate, exceptions, upstream]
symptoms: [error rate above 5%, HTTP 5xx, upstream errors, unhandled exceptions]
actions: [rollback_deployment, restart_service]
summary: Correlate the error onset with deployments and dependencies; roll back regressions, fix dependencies at the source.
---
# High Error Rate

## Detection
`HIGH_ERROR_RATE` fires when > 5% of requests fail for 2 samples (CRITICAL above 20%).

## Triage
1. Did a deployment happen right before the onset? → `deployment-failure` runbook.
2. Are the errors `upstream_error` (a dependency failing)? → investigate that dependency.
3. Are they `db_too_many_connections`? → `database-saturation` runbook.
4. Group ERROR logs by event; the top event usually names the failure mode.

## Remediation
Follow the runbook for the identified cause. Never restart blindly: if the cause is a
dependency, restarting the caller adds load without fixing anything.
