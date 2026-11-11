# syntax=docker/dockerfile:1.7
# Build context: repository root (needs backend/, ai-agent/, runbooks/)
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY ai-agent/ ai-agent/
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install ./ai-agent \
 && /opt/venv/bin/pip install "./backend[aws]"

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RUNBOOKS_DIR=/app/runbooks
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY backend/alembic.ini backend/alembic.ini
COPY backend/alembic backend/alembic
COPY backend/app backend/app
COPY runbooks runbooks
COPY scripts/docker-entrypoint.sh /usr/local/bin/entrypoint
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --start-period=20s --retries=5 CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
ENTRYPOINT ["entrypoint"]
CMD ["uvicorn", "--app-dir", "/app/backend", "--factory", "app.main:app_factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
