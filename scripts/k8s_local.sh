#!/usr/bin/env bash
# Deploy CloudOps AI to a local kind cluster: build + load images, create Secrets from .env, apply the
# local overlay, wait for rollouts, then smoke-test through a port-forward.
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER="${KIND_CLUSTER:-cloudops}"
NS=cloudops
[[ -f .env ]] || ./scripts/bootstrap_env.sh
set -a; source .env; set +a

kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --wait 120s
if [[ "${SKIP_BUILD:-0}" != 1 ]]; then make images; fi
kind load docker-image --name "$CLUSTER" cloudops-ai/backend:local cloudops-ai/frontend:local cloudops-ai/demo-service:local

kubectl apply -f infrastructure/kubernetes/base/namespace.yaml
DB_PASS=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
if ! kubectl -n $NS get secret cloudops-db >/dev/null 2>&1; then
  kubectl -n $NS create secret generic cloudops-db --from-literal=password="$DB_PASS"
fi
DB_PASS=$(kubectl -n $NS get secret cloudops-db -o jsonpath='{.data.password}' | base64 -d)
kubectl -n $NS create secret generic cloudops-secrets --dry-run=client -o yaml \
  --from-literal=DATABASE_URL="postgresql+psycopg://cloudops:${DB_PASS}@postgres:5432/cloudops_ai" \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=SEED_DEMO_USERS=true \
  --from-literal=SEED_ADMIN_PASSWORD="$SEED_ADMIN_PASSWORD" --from-literal=SEED_SRE_PASSWORD="$SEED_SRE_PASSWORD" \
  --from-literal=SEED_DEVELOPER_PASSWORD="$SEED_DEVELOPER_PASSWORD" --from-literal=SEED_VIEWER_PASSWORD="$SEED_VIEWER_PASSWORD" \
  | kubectl apply -f -
kubectl -n $NS create secret generic cloudops-chaos --dry-run=client -o yaml --from-literal=token="${CHAOS_TOKEN:-}" | kubectl apply -f -

kubectl apply -k infrastructure/kubernetes/overlays/local
kubectl -n $NS rollout status statefulset/postgres --timeout=180s
for d in cloudops-backend cloudops-frontend api-gateway user-service payment-service notification-service; do
  kubectl -n $NS rollout status deployment/$d --timeout=240s
done

kubectl -n $NS port-forward svc/cloudops-backend 18800:8000 >/dev/null 2>&1 &
PF=$!; trap 'kill $PF 2>/dev/null' EXIT
for _ in $(seq 30); do curl -sf localhost:18800/healthz >/dev/null && break; sleep 1; done
./scripts/smoke_test.sh http://localhost:18800
kubectl -n $NS get pods -o wide
echo "UI:  kubectl -n $NS port-forward svc/cloudops-frontend 3000:80   (then http://localhost:3000)"
