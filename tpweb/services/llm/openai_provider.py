"""OpenAI implementation of LLMProvider using the Responses API.

The cluster smoke test validates /v1/responses directly, so this adapter uses
the same API instead of Chat Completions. It intentionally avoids printing or
persisting API keys; OPENAI_API_KEY is read from the process environment.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolDefinition, Usage

DEFAULT_MODEL = "gpt-5.4-mini"
RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: int = 60):
        self.model = (
            model
            or os.environ.get("TPW_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or DEFAULT_MODEL
        )
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

    def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str = "",
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._to_response_input(messages),
            "tools": [self._to_response_tool(tool) for tool in tools],
            "store": False,
        }
        if system:
            payload["instructions"] = system

        response = self._post(payload)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for item in response.get("output") or []:
            item_type = item.get("type")
            if item_type == "message":
                for content in item.get("content") or []:
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text") or "")
            elif item_type == "function_call":
                try:
                    tool_input = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    tool_input = {}
                call_id = item.get("call_id") or item.get("id") or ""
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=item.get("name") or "",
                        input=tool_input,
                    )
                )

        if tool_calls:
            stop_reason = "tool_use"
        elif response.get("status") == "incomplete":
            stop_reason = "max_tokens"
        elif response.get("status") == "completed":
            stop_reason = "end_turn"
        else:
            stop_reason = "other"

        usage_payload = response.get("usage") or {}
        usage = Usage(
            input_tokens=usage_payload.get("input_tokens") or 0,
            output_tokens=usage_payload.get("output_tokens") or 0,
        )

        return LLMResponse(
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            raw=response,
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API error {exc.code}: {body[:1000]}") from exc

    @staticmethod
    def _to_response_tool(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": False,
        }

    @classmethod
    def _to_response_input(cls, messages: list[Message]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.tool_results:
                for result in message.tool_results:
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": result.tool_call_id,
                            "output": result.content,
                        }
                    )
                continue

            if message.tool_calls:
                if message.text:
                    items.append({"role": "assistant", "content": message.text})
                for call in message.tool_calls:
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call.id,
                            "name": call.name,
                            "arguments": json.dumps(call.input),
                        }
                    )
                continue

            items.append({"role": message.role, "content": message.text or ""})
        return items
