---
slug: database-saturation
title: Database Connection Saturation
severity: CRITICAL
tags: [database, postgres, connections, pool, saturation, leak]
symptoms: [connections above 85% of max_connections, too many clients, pool exhausted timeouts, errors across multiple services]
actions: [restart_service]
summary: Identify the client holding most connections; a rolling restart of the leaking client releases them.
---
# Database Connection Saturation

## Detection
`DB_CONNECTION_SATURATION` fires at >85% of `max_connections` for 2 samples. At ≥97%
new connections fail with `SQLSTATE 53300 too many clients`.

## Triage
1. `get_database_status` — which client holds the most connections?
2. Is that client's connection count **growing** while its traffic is flat? → connection leak.
3. Look for `db_conn_not_returned` warnings in the client's logs.
4. Other services failing with `db_pool_exhausted` are **victims**, not the cause.

## Remediation
- `restart_service` on the leaking client (MEDIUM). Connections are released when processes exit.
- Do **not** raise `max_connections` during the incident — it masks the leak and risks memory exhaustion on the primary.

## Verification
Database utilisation < 70%, victim services' error rates back below 5%.

## Follow-up
Add pool `leakDetectionThreshold`, and alert on per-client connection growth.
