"""Static knowledge shared by agent and backend. The backend re-evaluates risk itself;
the agent's risk label is advisory only."""

ALLOWED_ACTIONS: dict[str, str] = {
    "restart_pod": "LOW",
    "clear_failed_job": "LOW",
    "restart_service": "MEDIUM",
    "scale_deployment": "MEDIUM",
    "rollback_deployment": "HIGH",
}

MAX_REPLICAS = 10
MIN_REPLICAS = 1
