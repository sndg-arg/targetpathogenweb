"""Claude/Anthropic implementation of LLMProvider.

Translates the neutral types in base.py to and from the anthropic SDK's
Messages API shape. This is the only file in the package that imports
`anthropic` -- tpweb/services/llm/agent.py and every tool implementation
stay provider-neutral.
"""

from __future__ import annotations

import os

import anthropic

from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition, Usage

DEFAULT_MODEL = "claude-opus-4-8"


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str | None = None, client: anthropic.Anthropic | None = None):
        # ANTHROPIC_API_KEY is read from the environment by the SDK itself --
        # never hardcode it, same convention as the SSH/cluster credentials
        # documented in CLAUDE.md.
        self.model = model or os.environ.get("TPW_LLM_MODEL", DEFAULT_MODEL)
        self._client = client or anthropic.Anthropic()

    def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str = "",
    ) -> LLMResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[self._to_anthropic_message(m) for m in messages],
            tools=[self._to_anthropic_tool(t) for t in tools],
        )

        text: str | None = None
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text = (text or "") + block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        stop_reason = {
            "end_turn": "end_turn",
            "tool_use": "tool_use",
            "max_tokens": "max_tokens",
        }.get(response.stop_reason, "other")

        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        )

        return LLMResponse(
            text=text, tool_calls=tool_calls, stop_reason=stop_reason, usage=usage, raw=response
        )

    @staticmethod
    def _to_anthropic_tool(tool: ToolDefinition) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    @staticmethod
    def _to_anthropic_message(message: Message) -> dict:
        content: list[dict] = []
        if message.text:
            content.append({"type": "text", "text": message.text})
        for call in message.tool_calls:
            content.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
            )
        for result in message.tool_results:
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_call_id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
            )
        return {"role": message.role, "content": content}
