"""Cloud provider abstraction.

All infrastructure access goes through a CloudProvider. The control plane is unaware of
whether it is talking to the local simulator, AWS, or (later) Azure/GCP.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass
class TelemetrySnapshot:
    ts: datetime
    tick: int
    metrics: dict[str, dict[str, float]]  # service -> metric -> value
    logs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ActionResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class CloudProvider(ABC):
    name: str = "abstract"
    is_simulated: bool = False
    supports_fault_injection: bool = False

    @abstractmethod
    def topology(self) -> list[dict[str, Any]]:
        """Services with kind, tier and dependency edges."""

    @abstractmethod
    def collect(self) -> TelemetrySnapshot:
        """Advance/poll and return the latest telemetry for every service."""

    @abstractmethod
    def pods(self, service: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def cluster_status(self) -> dict[str, Any]: ...

    @abstractmethod
    def database_status(self) -> dict[str, Any]: ...

    @abstractmethod
    def deployment_state(self, service: str) -> dict[str, Any]: ...

    # Remediation primitives ------------------------------------------------
    @abstractmethod
    def restart_pod(self, service: str, pod: str) -> ActionResult: ...

    @abstractmethod
    def restart_service(self, service: str) -> ActionResult: ...

    @abstractmethod
    def scale_deployment(self, service: str, replicas: int) -> ActionResult: ...

    @abstractmethod
    def rollback_deployment(self, service: str) -> ActionResult: ...

    @abstractmethod
    def clear_failed_job(self, service: str, job_id: str) -> ActionResult: ...

    # Deployments ------------------------------------------------------------
    @abstractmethod
    def deploy(self, service: str, version: str, defective: bool = False) -> ActionResult: ...

    # Fault injection (simulators only) -------------------------------------
    def inject_fault(self, fault: str, service: str | None = None) -> ActionResult:
        raise ProviderError(f"{self.name} does not support fault injection")

    def clear_faults(self) -> ActionResult:
        raise ProviderError(f"{self.name} does not support fault injection")

    def active_faults(self) -> list[dict[str, Any]]:
        return []
