"""Selects the configured LLMProvider implementation.

Controlled by TPW_LLM_PROVIDER (default: "anthropic"), following the same
env-var feature-flag convention as the pipeline's TPW_* settings (e.g.
TPW_COLABFOLD_USE_REMOTE) documented in CLAUDE.md.
"""
from __future__ import annotations

import os

from .base import LLMProvider


def get_provider() -> LLMProvider:
    provider_name = os.environ.get("TPW_LLM_PROVIDER", "anthropic").strip().lower()

    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()

    if provider_name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider()

    raise ValueError(
        f"Unknown TPW_LLM_PROVIDER: {provider_name!r} (expected 'anthropic' or 'openai')"
    )
