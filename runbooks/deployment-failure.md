---
slug: deployment-failure
title: Deployment Failure / Bad Release
severity: HIGH
tags: [deployment, release, regression, rollback, version]
symptoms: [errors start right after a deployment, unhandled exceptions in new version, failed rollout]
actions: [rollback_deployment]
summary: Roll back to the last known-good version first, debug second.
---
# Deployment Failure

## Detection
Error rate or latency alerts within 15 minutes of a rollout; logs reference the new version.

## Triage
1. `get_recent_deployments` — version, previous version, age, author.
2. Confirm errors began **after** the rollout and are tagged with the new version.

## Remediation
- `rollback_deployment` (HIGH risk — changes running code; requires SRE/Admin approval).
- Freeze further deploys to the service until a fix is reviewed.

## Verification
Error rate back below 5%; pods running the previous version and Ready.

## Follow-up
Add the failing case to the canary analysis; consider progressive delivery for this service.
