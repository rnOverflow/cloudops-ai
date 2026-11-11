"""CloudOps AI investigation agent.

The agent investigates infrastructure problems through a fixed, allow-listed set of
read-only tools. It never receives shell access. Observed facts are extracted by
deterministic code from tool output; any language-model reasoning is labelled as
AI inference and validated before it can influence a remediation recommendation.
"""

from .investigator import Investigator
from .types import Finding, FindingKind, InvestigationResult, Recommendation, ToolCallRecord

__all__ = [
    "Finding",
    "FindingKind",
    "InvestigationResult",
    "Investigator",
    "Recommendation",
    "ToolCallRecord",
]
