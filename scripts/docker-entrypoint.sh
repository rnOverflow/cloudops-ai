#!/bin/sh
# Apply database migrations (retrying while the database starts), then start the API.
set -e
cd /app/backend
for i in $(seq 1 30); do
  if alembic upgrade head; then break; fi
  [ "$i" = 30 ] && { echo "database not reachable after 30 attempts" >&2; exit 1; }
  echo "waiting for database ($i/30)..."; sleep 2
done
cd /app
exec "$@"
