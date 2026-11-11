"""Allow-listed, read-only tool surface available to the agent.

The backend supplies an implementation of :class:`ToolBackend`. The registry is the
only path through which the agent (and any LLM) can observe the system. Unknown tools
and unexpected arguments are rejected before reaching the backend.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import ToolCallRecord

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9\-_.]{0,62}$")


class ToolBackend(Protocol):
    def get_service_health(self, service: str | None = None) -> dict[str, Any]: ...
    def get_metrics(self, service: str, window: int = 30) -> dict[str, Any]: ...
    def query_logs(self, service: str, level: str | None = None, limit: int = 200) -> dict[str, Any]: ...
    def get_recent_deployments(self, service: str | None = None) -> dict[str, Any]: ...
    def get_kubernetes_status(self) -> dict[str, Any]: ...
    def get_pod_status(self, service: str) -> dict[str, Any]: ...
    def get_database_status(self) -> dict[str, Any]: ...
    def get_recent_incidents(self, service: str | None = None) -> dict[str, Any]: ...
    def get_service_dependencies(self, service: str) -> dict[str, Any]: ...
    def get_slo_status(self, service: str | None = None) -> dict[str, Any]: ...
    def get_runbook(self, query: str, limit: int = 3) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_SERVICE = {"type": "string", "description": "Service name, e.g. payment-service"}

TOOL_SPECS: dict[str, ToolSpec] = {
    s.name: s
    for s in [
        ToolSpec("get_service_health", "Current health of one or all services.", _obj({"service": _SERVICE})),
        ToolSpec(
            "get_metrics",
            "Recent metric time series (cpu, memory, latency, rps, error rate, restarts, connections).",
            _obj(
                {"service": _SERVICE, "window": {"type": "integer", "minimum": 5, "maximum": 360}},
                ["service"],
            ),
        ),
        ToolSpec(
            "query_logs",
            "Recent structured logs for a service, optionally filtered by level.",
            _obj(
                {
                    "service": _SERVICE,
                    "level": {"type": "string", "enum": ["DEBUG", "INFO", "WARN", "ERROR"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                ["service"],
            ),
        ),
        ToolSpec("get_recent_deployments", "Recent deployments and rollbacks.", _obj({"service": _SERVICE})),
        ToolSpec("get_kubernetes_status", "Cluster-level node and workload status.", _obj({})),
        ToolSpec(
            "get_pod_status",
            "Pods for a service: phase, readiness, restarts, cpu, memory.",
            _obj({"service": _SERVICE}, ["service"]),
        ),
        ToolSpec("get_database_status", "Database connections, saturation, and per-client usage.", _obj({})),
        ToolSpec(
            "get_recent_incidents",
            "Recent incidents, optionally for one service.",
            _obj({"service": _SERVICE}),
        ),
        ToolSpec(
            "get_service_dependencies",
            "Upstream and downstream dependencies of a service.",
            _obj({"service": _SERVICE}, ["service"]),
        ),
        ToolSpec(
            "get_slo_status",
            "SLO attainment, error budget remaining, and burn rate.",
            _obj({"service": _SERVICE}),
        ),
        ToolSpec(
            "get_runbook",
            "Retrieve the most relevant operational runbooks for a symptom description.",
            _obj(
                {
                    "query": {"type": "string", "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                ["query"],
            ),
        ),
    ]
}


class ToolValidationError(ValueError):
    pass


@dataclass
class ToolRegistry:
    backend: ToolBackend
    known_services: set[str]
    calls: list[ToolCallRecord] = field(default_factory=list)
    max_calls: int = 40

    def specs(self) -> list[ToolSpec]:
        return list(TOOL_SPECS.values())

    def _validate(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            raise ToolValidationError(f"tool '{name}' is not allow-listed")
        props = spec.parameters["properties"]
        for key in args:
            if key not in props:
                raise ToolValidationError(f"unexpected argument '{key}' for {name}")
        for key in spec.parameters.get("required", []):
            if key not in args:
                raise ToolValidationError(f"missing required argument '{key}' for {name}")
        clean: dict[str, Any] = {}
        for key, value in args.items():
            schema = props[key]
            if value is None:
                continue
            if key == "service":
                if (
                    not isinstance(value, str)
                    or not _SAFE_ID.match(value)
                    or value not in self.known_services
                ):
                    raise ToolValidationError(f"unknown service '{value}'")
            if schema.get("type") == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ToolValidationError(f"'{key}' must be an integer")
                value = max(schema.get("minimum", value), min(schema.get("maximum", value), value))
            if schema.get("type") == "string":
                if not isinstance(value, str):
                    raise ToolValidationError(f"'{key}' must be a string")
                if "enum" in schema and value not in schema["enum"]:
                    raise ToolValidationError(f"'{key}' must be one of {schema['enum']}")
                value = value[: schema.get("maxLength", 200)]
            clean[key] = value
        return clean

    def call(
        self, name: str, args: dict[str, Any] | None = None, summarize: Callable[[Any], str] | None = None
    ) -> Any:
        args = dict(args or {})
        if len(self.calls) >= self.max_calls:
            raise ToolValidationError("tool call budget exhausted")
        start = time.perf_counter()
        try:
            clean = self._validate(name, args)
            output = getattr(self.backend, name)(**clean)
        except Exception as exc:  # recorded, never hidden
            self.calls.append(
                ToolCallRecord(
                    tool=name,
                    arguments=args,
                    ok=False,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    summary=f"error: {exc}",
                    error=str(exc),
                )
            )
            raise
        summary = summarize(output) if summarize else _default_summary(output)
        self.calls.append(
            ToolCallRecord(
                tool=name,
                arguments=clean,
                ok=True,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                summary=summary,
                output=output,
            )
        )
        return output


def _default_summary(output: Any) -> str:
    if isinstance(output, dict):
        keys = ", ".join(list(output.keys())[:6])
        return f"returned keys: {keys}"
    if isinstance(output, list):
        return f"returned {len(output)} items"
    return "ok"
