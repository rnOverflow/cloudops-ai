from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FindingKind(StrEnum):
    OBSERVED_FACT = "OBSERVED_FACT"
    AI_INFERENCE = "AI_INFERENCE"


class Finding(BaseModel):
    kind: FindingKind
    statement: str
    source: str = Field(description="Tool name (facts) or reasoning engine (inferences)")
    data: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    ok: bool
    duration_ms: float
    summary: str
    output: Any = None
    error: str | None = None


class Recommendation(BaseModel):
    action: str
    target_service: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    expected_impact: str
    risk: str  # LOW | MEDIUM | HIGH


class Hypothesis(BaseModel):
    key: str
    title: str
    score: float
    confidence: float
    supporting: list[str] = Field(default_factory=list)
    root_cause_service: str


class InvestigationResult(BaseModel):
    service: str | None
    question: str
    summary: str
    status: str  # HEALTHY | DEGRADED | UNHEALTHY | UNKNOWN
    findings: list[Finding]
    hypotheses: list[Hypothesis]
    root_cause: str | None
    root_cause_service: str | None
    confidence: float
    recommendation: Recommendation | None
    runbooks: list[dict[str, Any]]
    tool_calls: list[ToolCallRecord]
    provider: str
    llm_used: bool = False
    notes: list[str] = Field(default_factory=list)
