from __future__ import annotations

from providers.base import BaseLLMProvider
from providers.claude_provider import ClaudeProvider
from providers.gemini_provider import GeminiProvider


def get_provider(name: str) -> BaseLLMProvider:
    normalized = (name or "gemini").strip().lower()
    if normalized == "gemini":
        return GeminiProvider()
    if normalized == "claude":
        return ClaudeProvider()
    raise ValueError(f"Unknown provider {name!r}. Valid options: gemini, claude.")
