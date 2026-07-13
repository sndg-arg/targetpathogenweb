"""Provider-agnostic agentic loop.

Repeats: ask the model -> if it wants a tool, run the tool and report the
result back -> ask again -> ... until the model returns a final text
answer or max_turns is hit. Only talks to the LLMProvider interface in
base.py, so it works unchanged regardless of which provider TPW_LLM_PROVIDER
selects.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from .base import LLMProvider, Message, ToolCall, ToolDefinition, ToolResult

ToolFunction = Callable[[dict], str]


class ToolEntry(NamedTuple):
    definition: ToolDefinition
    run: ToolFunction


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        tools: dict[str, ToolEntry],
        system: str = "",
        max_turns: int = 8,
    ):
        self.provider = provider
        self.tools = tools
        self.system = system
        self.max_turns = max_turns
        self.last_messages: list[Message] = []

    def run(self, user_text: str, history: list[Message] | None = None) -> str:
        """history: prior turns to seed the conversation with (e.g. a chat
        endpoint round-tripping state from the frontend). After run()
        returns, self.last_messages holds the full updated conversation
        (history + this turn, including tool exchanges) for callers that
        need to persist/return it -- the return value itself stays a plain
        str so existing callers (test_llm_agent.py) are unaffected."""
        messages: list[Message] = list(history) if history else []
        messages.append(Message(role="user", text=user_text))
        tool_defs = [entry.definition for entry in self.tools.values()]

        for _ in range(self.max_turns):
            response = self.provider.generate(messages, tool_defs, system=self.system)

            if response.stop_reason != "tool_use" or not response.tool_calls:
                messages.append(Message(role="assistant", text=response.text))
                self.last_messages = messages
                return response.text or ""

            messages.append(
                Message(role="assistant", text=response.text, tool_calls=response.tool_calls)
            )
            tool_results = [self._execute(call) for call in response.tool_calls]
            messages.append(Message(role="user", tool_results=tool_results))

        self.last_messages = messages
        return "No pude completar la solicitud en el número de pasos permitido."

    def _execute(self, call: ToolCall) -> ToolResult:
        entry = self.tools.get(call.name)
        if entry is None:
            return ToolResult(tool_call_id=call.id, content=f"Unknown tool: {call.name}", is_error=True)
        try:
            result = entry.run(call.input)
            return ToolResult(tool_call_id=call.id, content=str(result))
        except Exception as exc:  # tool failures are reported to the model, not raised
            return ToolResult(tool_call_id=call.id, content=f"Error: {exc}", is_error=True)
