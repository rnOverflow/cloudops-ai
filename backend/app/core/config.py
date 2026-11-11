from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CloudOps AI"
    environment: str = Field(default="development", description="development | test | production")
    database_url: str = "postgresql+psycopg://localhost:5432/cloudops_ai"

    # Security
    jwt_secret: str = Field(default="", description="HS256 signing key; required (min 32 chars)")
    jwt_ttl_minutes: int = 60
    bcrypt_rounds: int = Field(default=12, ge=4, le=15)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    login_rate_limit_per_minute: int = 10
    ai_rate_limit_per_minute: int = 20

    # Demo user seeding (local only). Passwords come from env, never from source.
    seed_demo_users: bool = False
    seed_admin_password: str | None = None
    seed_sre_password: str | None = None
    seed_developer_password: str | None = None
    seed_viewer_password: str | None = None

    # Cloud provider
    cloud_provider: str = "local"  # local | aws
    aws_region: str = "us-east-1"
    aws_ecs_cluster: str | None = None
    aws_service_map: str = ""  # "api-gateway=ecs-svc-name,..."
    aws_log_group_prefix: str = "/ecs/cloudops"
    aws_rds_instance_id: str | None = None
    aws_rds_max_connections: int = 100
    aws_alb_target_groups: str = ""  # "api-gateway=targetgroup/name/id,..." (ARN suffixes)
    aws_alb_name: str | None = None  # "app/name/id" (ARN suffix)

    # Simulation / control loop
    tick_seconds: float = 2.0
    run_control_loop: bool = True
    simulation_seed: int | None = None
    verify_after_ticks: int = 5

    # AI
    llm_provider: str = "none"  # none | openai
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Paths
    runbooks_dir: str = Field(
        default="", description="Directory with markdown runbooks; auto-detected if empty"
    )

    # Observability
    otel_exporter_otlp_endpoint: str | None = None
    log_level: str = "INFO"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_strength(cls, v: str) -> str:
        if v and len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip() and o.strip() != "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
