from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceName = Field(pattern=r"^[a-z0-9][a-z0-9\-]{1,62}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int
    user: dict[str, Any]


class CreateUserRequest(Strict):
    username: str = Field(pattern=r"^[a-z][a-z0-9_.\-]{2,63}$")
    full_name: str = Field(default="", max_length=128)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["ADMIN", "SRE", "DEVELOPER", "VIEWER"]


class InvestigateRequest(Strict):
    question: str = Field(min_length=3, max_length=500)
    service: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9\-]{1,62}$")


class ProposeRemediationRequest(Strict):
    action: Literal[
        "restart_pod", "restart_service", "scale_deployment", "rollback_deployment", "clear_failed_job"
    ]
    target_service: str = ServiceName
    parameters: dict[str, Any] = Field(default_factory=dict)
    incident_key: str | None = Field(default=None, pattern=r"^INC-\d{4,}$")
    reason: str = Field(min_length=3, max_length=1000)


class DecisionRequest(Strict):
    reason: str = Field(min_length=3, max_length=1000)


class IncidentStatusRequest(Strict):
    status: Literal["INVESTIGATING", "RESOLVED", "CLOSED"]
    note: str = Field(min_length=3, max_length=2000)


class DeployRequest(Strict):
    service: str = ServiceName
    version: str = Field(pattern=r"^v\d+\.\d+\.\d+$")
    notes: str = Field(default="", max_length=500)


class InjectFaultRequest(Strict):
    fault: Literal[
        "high_cpu",
        "memory_leak",
        "db_saturation",
        "pod_crash",
        "latency_spike",
        "deployment_failure",
        "traffic_spike",
        "outage",
        "queue_backlog",
    ]
    service: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9\-]{1,62}$")


class SettingsUpdate(Strict):
    autonomous_mode: bool | None = None
    autonomous_min_confidence: float | None = Field(default=None, ge=0.5, le=0.99)
    max_remediations_per_incident: int | None = Field(default=None, ge=1, le=5)
    blast_radius_max_executions: int | None = Field(default=None, ge=1, le=50)
    reason: str = Field(min_length=3, max_length=500)
