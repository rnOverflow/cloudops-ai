#!/usr/bin/env bash
# Post-deploy smoke test: health, readiness, auth enforcement, OpenAPI, metrics.
set -euo pipefail
BASE="${1:-http://localhost:8000}"
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

[[ "$(code "$BASE/healthz")" == 200 ]] || fail "healthz"
[[ "$(code "$BASE/readyz")" == 200 ]] || fail "readyz"
[[ "$(code "$BASE/api/incidents")" == 401 ]] || fail "unauthenticated request was not rejected"
[[ "$(code "$BASE/api/openapi.json")" == 200 ]] || fail "openapi"
curl -s "$BASE/metrics" | grep -q '^cloudops_control_loop_seconds_count' || fail "control-loop metric missing"
echo "smoke tests passed against $BASE"
