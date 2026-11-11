"""Demo microservice used by the docker-compose / Kubernetes deployments.

One image, four roles (api-gateway, user-service, payment-service, notification-service),
selected by SERVICE_NAME. Each instance:
  * serves real HTTP traffic and calls its downstream dependencies,
  * exports Prometheus metrics (RED + process metrics) on /metrics,
  * emits structured JSON logs (shipped to Loki by Promtail),
  * emits OpenTelemetry traces when OTEL_EXPORTER_OTLP_ENDPOINT is set,
  * exposes /chaos/* endpoints (token-protected) that cause *real* degradation:
    CPU burn threads, memory growth, injected latency, error injection, readiness failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import sys
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SERVICE = os.environ.get("SERVICE_NAME", "api-gateway")
VERSION = os.environ.get("SERVICE_VERSION", "v1.0.0")
DOWNSTREAM = [d for d in os.environ.get("DOWNSTREAM", "").split(",") if d]  # e.g. http://user-service:8080
CHAOS_TOKEN = os.environ.get("CHAOS_TOKEN", "")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": time.time(), "level": record.levelname.replace("WARNING", "WARN"), "service": SERVICE, "version": VERSION,
                           "event": getattr(record, "event", "log"), "message": record.getMessage()})


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger(SERVICE)
log.handlers[:] = [handler]
log.setLevel(logging.INFO)

REQUESTS = Counter("http_requests_total", "HTTP requests", ["service", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["service", "route"], buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
INFLIGHT = Gauge("http_requests_in_flight", "In-flight requests", ["service"])
CHAOS = Gauge("chaos_active", "Active chaos experiments", ["service", "kind"])
UP = Gauge("service_ready", "1 if the service reports ready", ["service"])


class Chaos:
    def __init__(self) -> None:
        self.latency_ms = 0
        self.error_rate = 0.0
        self.ready = True
        self.cpu_threads: list[threading.Event] = []
        self.leak: list[bytes] = []

    def burn(self, threads: int) -> None:
        for _ in range(threads):
            stop = threading.Event()

            def spin(ev: threading.Event = stop) -> None:
                while not ev.is_set():
                    sum(i * i for i in range(10_000))

            threading.Thread(target=spin, daemon=True).start()
            self.cpu_threads.append(stop)
        CHAOS.labels(SERVICE, "cpu").set(len(self.cpu_threads))

    def reset(self) -> None:
        for ev in self.cpu_threads:
            ev.set()
        self.cpu_threads.clear()
        self.leak.clear()
        self.latency_ms, self.error_rate, self.ready = 0, 0.0, True
        for kind in ("cpu", "memory", "latency", "errors", "readiness"):
            CHAOS.labels(SERVICE, kind).set(0)


chaos = Chaos()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=3.0)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        tp = TracerProvider(resource=Resource.create({"service.name": SERVICE, "service.version": VERSION}))
        tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/") + "/v1/traces")))
        trace.set_tracer_provider(tp)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics,healthz,ready")
    UP.labels(SERVICE).set(1)
    log.info("service started", extra={"event": "startup"})
    yield
    await app.state.http.aclose()


app = FastAPI(title=SERVICE, lifespan=lifespan, docs_url=None, redoc_url=None)


def require_chaos_token(x_chaos_token: str = Header(default="")) -> None:
    if not CHAOS_TOKEN or not secrets.compare_digest(x_chaos_token, CHAOS_TOKEN):
        raise HTTPException(403, "chaos endpoints require X-Chaos-Token")


@app.middleware("http")
async def red_metrics(request: Request, call_next):
    route = request.url.path if request.url.path in ("/api/work", "/api/checkout", "/api/profile", "/api/notify") else "other"
    INFLIGHT.labels(SERVICE).inc()
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        INFLIGHT.labels(SERVICE).dec()
    if route != "other":
        LATENCY.labels(SERVICE, route).observe(time.perf_counter() - start)
        REQUESTS.labels(SERVICE, route, str(response.status_code)).inc()
    return response


async def _work(request: Request, route: str) -> dict:
    if chaos.latency_ms:
        await asyncio.sleep(chaos.latency_ms / 1000 * random.uniform(0.7, 1.3))
    if chaos.error_rate and random.random() < chaos.error_rate:
        log.error(f"Unhandled exception in {route} [{VERSION}]", extra={"event": "unhandled_exception"})
        raise HTTPException(500, "internal error")
    calls = []
    for url in DOWNSTREAM:
        try:
            r = await request.app.state.http.get(f"{url}/api/work")
            calls.append({"dependency": url, "status": r.status_code})
            if r.status_code >= 500:
                log.error(f"Upstream {url} returned {r.status_code}", extra={"event": "upstream_error"})
                raise HTTPException(502, "upstream failure")
        except httpx.TimeoutException:
            log.warning(f"Upstream {url} timed out", extra={"event": "upstream_timeout"})
            raise HTTPException(504, "upstream timeout") from None
        except httpx.HTTPError as exc:
            log.error(f"Upstream {url} unreachable: {exc}", extra={"event": "upstream_error"})
            raise HTTPException(502, "upstream unreachable") from None
    await asyncio.sleep(random.uniform(0.002, 0.015))
    return {"service": SERVICE, "version": VERSION, "downstream": calls}


@app.get("/api/work")
async def work(request: Request):
    return await _work(request, "/api/work")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/ready")
async def ready(response: Response):
    UP.labels(SERVICE).set(1 if chaos.ready else 0)
    if not chaos.ready:
        log.error("Readiness probe failed", extra={"event": "readiness_probe_failed"})
        response.status_code = 503
        return {"ready": False}
    return {"ready": True}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chaos/cpu", dependencies=[Depends(require_chaos_token)])
def chaos_cpu(threads: int = 2):
    chaos.burn(max(1, min(threads, 8)))
    log.warning(f"CHAOS: {threads} CPU burn threads started", extra={"event": "worker_hot_loop"})
    return {"cpu_threads": len(chaos.cpu_threads)}


@app.post("/chaos/memory", dependencies=[Depends(require_chaos_token)])
def chaos_memory(mb: int = 50):
    chaos.leak.append(b"x" * (max(1, min(mb, 256)) * 1024 * 1024))
    CHAOS.labels(SERVICE, "memory").set(len(chaos.leak))
    log.warning(f"CHAOS: leaked {mb} MiB (total chunks {len(chaos.leak)})", extra={"event": "gc_pressure"})
    return {"leaked_chunks": len(chaos.leak)}


@app.post("/chaos/latency", dependencies=[Depends(require_chaos_token)])
def chaos_latency(ms: int = 1500):
    chaos.latency_ms = max(0, min(ms, 10_000))
    CHAOS.labels(SERVICE, "latency").set(chaos.latency_ms)
    return {"latency_ms": chaos.latency_ms}


@app.post("/chaos/errors", dependencies=[Depends(require_chaos_token)])
def chaos_errors(rate: float = 0.3):
    chaos.error_rate = max(0.0, min(rate, 1.0))
    CHAOS.labels(SERVICE, "errors").set(chaos.error_rate)
    return {"error_rate": chaos.error_rate}


@app.post("/chaos/readiness", dependencies=[Depends(require_chaos_token)])
def chaos_readiness(ready: bool = False):
    chaos.ready = ready
    CHAOS.labels(SERVICE, "readiness").set(0 if ready else 1)
    return {"ready": chaos.ready}


@app.post("/chaos/crash", dependencies=[Depends(require_chaos_token)])
def chaos_crash():
    log.error("CHAOS: process exiting with code 137", extra={"event": "process_crash"})
    threading.Timer(0.2, lambda: os._exit(137)).start()
    return {"crashing": True}


@app.post("/chaos/reset", dependencies=[Depends(require_chaos_token)])
def chaos_reset():
    chaos.reset()
    return {"reset": True}
