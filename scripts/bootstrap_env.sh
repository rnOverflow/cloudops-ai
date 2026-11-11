#!/usr/bin/env bash
# Generates a local .env with strong random secrets and demo-user passwords.
# Passwords are written to .env (gitignored) and demo-credentials.txt (gitignored) — never to source control.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env && "${1:-}" != "--force" ]]; then
  echo ".env already exists (use --force to regenerate)"; exit 0
fi

rand() { python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }
PG_PASS=$(rand 24)
DB_HOST="${DB_HOST:-localhost}"
DB_USER="${DB_USER:-cloudops}"
DB_URL="${DATABASE_URL:-postgresql+psycopg://${DB_USER}:${PG_PASS}@${DB_HOST}:5432/cloudops_ai}"

sed -e "s|^DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASS}|" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=$(rand 48)|" \
    -e "s|^SEED_ADMIN_PASSWORD=.*|SEED_ADMIN_PASSWORD=$(rand 12)|" \
    -e "s|^SEED_SRE_PASSWORD=.*|SEED_SRE_PASSWORD=$(rand 12)|" \
    -e "s|^SEED_DEVELOPER_PASSWORD=.*|SEED_DEVELOPER_PASSWORD=$(rand 12)|" \
    -e "s|^SEED_VIEWER_PASSWORD=.*|SEED_VIEWER_PASSWORD=$(rand 12)|" \
    -e "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(rand 16)|" \
    -e "s|^CHAOS_TOKEN=.*|CHAOS_TOKEN=$(rand 24)|" \
    .env.example > .env
chmod 600 .env

{
  echo "CloudOps AI local demo credentials (generated $(date -u +%FT%TZ)); do not commit."
  for u in admin sre developer viewer; do
    key="SEED_$(echo "$u" | tr '[:lower:]' '[:upper:]')_PASSWORD"
    echo "  $u / $(grep "^$key=" .env | cut -d= -f2-)"
  done
} > demo-credentials.txt
chmod 600 demo-credentials.txt
echo "Wrote .env and demo-credentials.txt (both gitignored)."
