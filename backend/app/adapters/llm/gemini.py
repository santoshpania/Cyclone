"""Gemini via google-genai with structured (schema-constrained) JSON output."""

from __future__ import annotations

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.adapters.llm.base import LLMError, LLMResult, T


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self.model = model

    async def generate(
        self, prompt_name: str, prompt: str, schema: type[T], *, max_output_tokens: int
    ) -> LLMResult[T]:
        try:
            resp = await self._client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,
                    max_output_tokens=max_output_tokens,
                ),
            )
        except Exception as exc:  # SDK raises several error types; normalise them
            raise LLMError(f"{prompt_name}: Gemini call failed: {exc}") from exc
        try:
            value = schema.model_validate_json(resp.text or "")
        except ValidationError as exc:
            raise LLMError(f"{prompt_name}: response did not match schema: {exc}") from exc
        usage = resp.usage_metadata
        return LLMResult(
            value=value,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            model=self.model,
        )
