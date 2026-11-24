"""Deterministic LLM for tests: returns fixture responses keyed by prompt name."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.adapters.llm.base import LLMError, LLMResult, T


class FakeLLM:
    model = "fake-llm"

    def __init__(self, responses: dict[str, Any | Callable[[str], Any]]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    async def generate(
        self, prompt_name: str, prompt: str, schema: type[T], *, max_output_tokens: int
    ) -> LLMResult[T]:
        self.calls.append((prompt_name, prompt))
        if prompt_name not in self.responses:
            raise LLMError(f"FakeLLM has no response for {prompt_name!r}")
        r = self.responses[prompt_name]
        payload = r(prompt) if callable(r) else r
        return LLMResult(
            value=schema.model_validate(payload),
            input_tokens=len(prompt) // 4,
            output_tokens=100,
            model=self.model,
        )
