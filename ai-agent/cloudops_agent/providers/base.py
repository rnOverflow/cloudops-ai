from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    raw_message: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


class NullProvider:
    """Used when no LLM is configured. The investigator then relies solely on the
    deterministic analyzer (which is clearly labelled as such in results)."""

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:  # pragma: no cover
        raise RuntimeError("no LLM provider configured")
