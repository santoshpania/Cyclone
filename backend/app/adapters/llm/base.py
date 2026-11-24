"""LLM interface. Every response is parsed into a Pydantic model (CLAUDE.md rule 2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult[T: BaseModel]:
    value: T
    input_tokens: int
    output_tokens: int
    model: str


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    async def generate(
        self, prompt_name: str, prompt: str, schema: type[T], *, max_output_tokens: int
    ) -> LLMResult[T]:
        """Run `prompt` and return the response validated against `schema`."""
        ...


def estimate_tokens(text: str) -> int:
    """Rough pre-call estimate for budget reservation (~4 chars/token; Arabic is denser, so be generous)."""
    return max(1, len(text) // 3)
