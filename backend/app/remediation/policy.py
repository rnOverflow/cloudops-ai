"""Remediation safety policy. Risk is decided here, independently of the AI agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACTIONS = ("restart_pod", "restart_service", "scale_deployment", "rollback_deployment", "clear_failed_job")
MAX_REPLICAS = 10
MIN_REPLICAS = 1
MAX_EXECUTIONS_PER_SERVICE_WINDOW = 3  # blast-radius guard
EXECUTION_WINDOW_SECONDS = 600


class PolicyViolation(ValueError):
    pass


@dataclass
class RiskAssessment:
    risk: str
    reasons: list[str]
    autonomous_eligible: bool


def assess(
    action: str, service: str, params: dict[str, Any], current_replicas: int, tier: str
) -> RiskAssessment:
    if action not in ACTIONS:
        raise PolicyViolation(f"action '{action}' is not permitted")
    reasons: list[str] = []
    if action in ("restart_pod", "clear_failed_job"):
        risk = "LOW"
        reasons.append(
            "affects a single pod/job; remaining replicas keep serving"
            if action == "restart_pod"
            else "moves one job to the dead-letter queue"
        )
    elif action == "restart_service":
        risk = "MEDIUM"
        reasons.append("rolling restart of every pod (surge, no planned capacity loss)")
    elif action == "scale_deployment":
        target = params.get("replicas")
        if target < current_replicas:
            risk = "HIGH"
            reasons.append(f"reduces capacity {current_replicas} -> {target}")
        else:
            risk = "MEDIUM"
            reasons.append(f"adds capacity {current_replicas} -> {target} (cost increase)")
    else:
        risk = "HIGH"
        reasons.append("changes running code version")
    if tier == "tier-0" and risk == "MEDIUM" and action == "restart_service":
        reasons.append("tier-0 service")
    return RiskAssessment(risk=risk, reasons=reasons, autonomous_eligible=risk == "LOW")


def validate_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "restart_pod": {"pod"},
        "scale_deployment": {"replicas"},
        "clear_failed_job": {"job_id"},
        "restart_service": set(),
        "rollback_deployment": set(),
    }[action]
    extra = set(params) - allowed
    if extra:
        raise PolicyViolation(f"unexpected parameters for {action}: {sorted(extra)}")
    missing = allowed - set(params)
    if missing:
        raise PolicyViolation(f"missing parameters for {action}: {sorted(missing)}")
    if action == "scale_deployment":
        r = params["replicas"]
        if not isinstance(r, int) or isinstance(r, bool) or not MIN_REPLICAS <= r <= MAX_REPLICAS:
            raise PolicyViolation(f"replicas must be an integer between {MIN_REPLICAS} and {MAX_REPLICAS}")
    for key in ("pod", "job_id"):
        if key in params:
            v = params[key]
            if (
                not isinstance(v, str)
                or not 1 <= len(v) <= 80
                or not all(c.isalnum() or c in "-_." for c in v)
            ):
                raise PolicyViolation(f"invalid {key}")
    return dict(params)
