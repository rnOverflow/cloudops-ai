"""OpenAI Chat Completions compatible provider (OpenAI, Azure OpenAI, Ollama, vLLM...)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from .base import LLMResponse, LLMToolCall


class OpenAICompatibleProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 45.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = f"openai-compatible:{model}"
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @property
    def available(self) -> bool:
        return bool(self._api_key) or "localhost" in self.base_url or "127.0.0.1" in self.base_url

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.1}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        resp = self._client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"__invalid__": tc["function"].get("arguments")}
            calls.append(LLMToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))
        return LLMResponse(content=msg.get("content"), tool_calls=calls, raw_message=msg)
