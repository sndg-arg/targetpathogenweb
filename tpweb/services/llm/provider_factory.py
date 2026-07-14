"""Selects the configured LLMProvider implementation.

Production deployments may set TPW_LLM_PROVIDER explicitly. For the OpenAI
prototype we also accept the simpler OPENAI_* variables used by the cluster
smoke tests: if OPENAI_AGENT_ENABLED=true and OPENAI_API_KEY is present,
OpenAI is selected without requiring an extra TPW_LLM_PROVIDER setting.
"""
from __future__ import annotations

import os

from .base import LLMProvider


def llm_agent_enabled() -> bool:
    return os.environ.get("OPENAI_AGENT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_provider() -> LLMProvider:
    provider_name = os.environ.get("TPW_LLM_PROVIDER", "").strip().lower()
    if not provider_name:
        provider_name = "openai" if llm_agent_enabled() and os.environ.get("OPENAI_API_KEY") else "anthropic"

    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()

    if provider_name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider()

    raise ValueError(
        f"Unknown TPW_LLM_PROVIDER: {provider_name!r} (expected 'anthropic' or 'openai')"
    )
