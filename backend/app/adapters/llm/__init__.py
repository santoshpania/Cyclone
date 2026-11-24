from __future__ import annotations

from app.adapters.llm.base import LLMClient
from app.settings import get_settings

_override: LLMClient | None = None


def set_llm_client(client: LLMClient | None) -> None:
    """Test hook: inject FakeLLM."""
    global _override
    _override = client


def get_llm_client() -> LLMClient | None:
    """Configured client, or None when no API key is set (the LLM pass is then skipped)."""
    if _override is not None:
        return _override
    s = get_settings()
    if s.gemini_api_key is None:
        return None
    from app.adapters.llm.gemini import GeminiClient

    return GeminiClient(s.gemini_api_key.get_secret_value(), s.gemini_model)
