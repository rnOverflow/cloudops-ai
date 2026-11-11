from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from .api.routes import ALL_ROUTERS
from .cloud.base import CloudProvider
from .cloud.factory import build_provider
from .control_plane import ControlPlane
from .core.clock import Clock
from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .core.ratelimit import SlidingWindowLimiter
from .db import Base, make_engine, make_session_factory
from .observability import prom

log = logging.getLogger("cloudops.api")


def _setup_tracing(app: FastAPI, settings: Settings) -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "cloudops-backend", "deployment.environment": settings.environment}
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces")
        )
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    provider: CloudProvider | None = None,
    create_schema: bool | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET is not set. Run scripts/bootstrap_env.sh or set it in the environment."
        )
    configure_logging(settings.log_level)
    clock = clock or Clock()
    engine = make_engine(settings.database_url)
    sf = make_session_factory(engine)
    provider = provider or build_provider(settings, clock)
    cp = ControlPlane(settings, clock, sf, provider)
    if create_schema is None:
        create_schema = settings.database_url.startswith("sqlite")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if create_schema:
            Base.metadata.create_all(engine)
        cp.bootstrap()
        if settings.run_control_loop:
            cp.start_background()
        log.info("CloudOps AI started", extra={"actor": "system"})
        yield
        cp.stop_background()
        engine.dispose()

    app = FastAPI(
        title="CloudOps AI",
        version="1.0.0",
        lifespan=lifespan,
        description="AI-powered cloud reliability, observability and self-healing operations platform.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.cp = cp
    app.state.settings = settings
    app.state.limiter = SlidingWindowLimiter()
    app.state.engine = engine

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": rid, "path": request.url.path})
            response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        prom.API_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
        prom.API_LATENCY.labels(request.method, route_path).observe(elapsed)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/") and response.status_code >= 400:
            log.info(
                "request",
                extra={
                    "request_id": rid,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )
        return response

    for r in ALL_ROUTERS:
        app.include_router(r)

    @app.get("/healthz", tags=["system"])
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    def readyz():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "tick": cp.store.tick}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(prom.REGISTRY), media_type=CONTENT_TYPE_LATEST)

    _setup_tracing(app, settings)
    return app


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    return create_app()
