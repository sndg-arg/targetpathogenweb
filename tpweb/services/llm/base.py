"""Provider-agnostic types for LLM-backed agent features.

Everything else in this package -- the agent loop, tool implementations,
management commands -- programs against these types and against the
LLMProvider interface, never against a provider SDK (anthropic, openai, ...)
directly. Swapping TPW_LLM_PROVIDER swaps which adapter is instantiated;
callers don't change.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolDefinition:
    """A tool the model may call, described in provider-neutral JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """The model asking to invoke a tool with a given input."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    """The result of actually running a ToolCall, to send back to the model."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """One turn of conversation history.

    A single Message can carry plain text, tool calls (assistant asking to
    invoke tools), or tool results (the caller reporting what happened) --
    matching how both Claude and OpenAI represent a turn as a mix of these.
    """

    role: Literal["user", "assistant"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class Usage:
    """Token accounting for one generation call, for cost/observability logging.

    Both providers report at least input/output tokens; anything provider-
    specific (cache tokens, reasoning tokens, ...) stays out of this neutral
    type -- inspect LLMResponse.raw directly if that level of detail is
    ever needed.
    """

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """What a provider adapter hands back after one generation call."""

    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "other"]
    usage: Usage | None = None
    raw: Any = None  # provider-native response object, for debugging only


class LLMProvider(abc.ABC):
    """One method: send conversation + tool definitions, get a neutral response."""

    @abc.abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str = "",
    ) -> LLMResponse: ...
