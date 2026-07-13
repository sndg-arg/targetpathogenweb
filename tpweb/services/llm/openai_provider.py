"""OpenAI implementation of LLMProvider.

Translates the neutral types in base.py to and from the OpenAI SDK's Chat
Completions tool-calling shape. This is the only file in the package that
imports `openai` -- tpweb/services/llm/agent.py and every tool
implementation stay provider-neutral.

OpenAI's wire format differs from Claude's in two ways that matter here:
- Tools are declared as {"type": "function", "function": {name, description,
  parameters}} (Claude: {"name", "description", "input_schema"}).
- A single tool-invoking turn is a role="assistant" message with a
  `tool_calls` list, and each tool's result is its OWN role="tool" message
  keyed by tool_call_id -- there is no way to bundle multiple tool results
  into one message like Claude's tool_result content blocks do. A neutral
  Message(role="user", tool_results=[...]) with N results must therefore
  expand into N separate OpenAI messages.
"""
from __future__ import annotations

import json
import os

import openai

from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition

DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str | None = None, client: openai.OpenAI | None = None):
        # OPENAI_API_KEY is read from the environment by the SDK itself --
        # never hardcode it, same convention as anthropic_provider.py.
        self.model = model or os.environ.get("TPW_LLM_MODEL", DEFAULT_MODEL)
        self._client = client or openai.OpenAI()

    def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str = "",
    ) -> LLMResponse:
        openai_messages: list[dict] = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for message in messages:
            openai_messages.extend(self._to_openai_messages(message))

        response = self._client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=[self._to_openai_tool(t) for t in tools],
        )

        choice = response.choices[0]
        message = choice.message

        text: str | None = message.content
        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            try:
                tool_input = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_input = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=tool_input))

        stop_reason = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "length": "max_tokens",
        }.get(choice.finish_reason, "other")

        return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop_reason, raw=response)

    @staticmethod
    def _to_openai_tool(tool: ToolDefinition) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _to_openai_messages(message: Message) -> list[dict]:
        """One neutral Message maps to zero or more OpenAI messages -- tool
        results in particular must be split into one role="tool" message per
        result, since OpenAI has no concept of bundling several into one."""
        if message.tool_results:
            return [
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                }
                for result in message.tool_results
            ]

        if message.tool_calls:
            return [
                {
                    "role": "assistant",
                    "content": message.text,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.input),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            ]

        return [{"role": message.role, "content": message.text or ""}]
