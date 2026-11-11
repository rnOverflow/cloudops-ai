from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo; PostgreSQL keeps it)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


TZ = UTCDateTime()


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)
    role: Mapped[Role] = relationship(lazy="joined")


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(16), default="tier-2")
    owner_team: Mapped[str] = mapped_column(String(64), default="platform")
    description: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(16), default="http")
    dependencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(16), default="local")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_key: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    service: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    impact_started_at: Mapped[datetime | None] = mapped_column(TZ)
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)
    closed_at: Mapped[datetime | None] = mapped_column(TZ)
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    logs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    correlated_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    probable_root_cause: Mapped[str | None] = mapped_column(Text)
    root_cause_service: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    recommended_action: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    risk: Mapped[str | None] = mapped_column(String(16))
    remediation_status: Mapped[str] = mapped_column(String(24), default="NONE")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    clear_ticks: Mapped[int] = mapped_column(Integer, default=0)
    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident", order_by="IncidentEvent.id", cascade="all, delete-orphan"
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(TZ, nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    incident: Mapped[Incident] = relationship(back_populates="events")


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    previous_version: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), default="DEPLOY")  # DEPLOY | ROLLBACK | SCALE | RESTART
    status: Mapped[str] = mapped_column(String(16), default="SUCCEEDED")
    actor: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TZ, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Remediation(Base):
    __tablename__ = "remediations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    target_service: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    autonomous: Mapped[bool] = mapped_column(Boolean, default=False)
    proposed_by: Mapped[str] = mapped_column(String(64))
    proposed_at: Mapped[datetime] = mapped_column(TZ)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(TZ)
    verified_at: Mapped[datetime | None] = mapped_column(TZ)
    verify_at_tick: Mapped[int | None] = mapped_column(Integer)
    before_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    execution_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, index=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(128), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(32))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Runbook(Base):
    __tablename__ = "runbooks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    symptoms: Mapped[list[str]] = mapped_column(JSON, default=list)
    actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZ)


class SLODefinition(Base):
    __tablename__ = "slo_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    sli_type: Mapped[str] = mapped_column(String(16))  # availability | latency
    target: Mapped[float] = mapped_column(Float)
    threshold_ms: Mapped[float | None] = mapped_column(Float)
    window_days: Mapped[int] = mapped_column(Integer, default=30)


class SLOMeasurement(Base):
    __tablename__ = "slo_measurements"
    __table_args__ = (Index("ix_slo_measurements_slo_ts", "slo_id", "ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slo_id: Mapped[int] = mapped_column(ForeignKey("slo_definitions.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TZ)
    good: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)


class AIInvestigation(Base):
    __tablename__ = "ai_investigations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(128))
    root_cause: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[float] = mapped_column(Float)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZ, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(TZ)
