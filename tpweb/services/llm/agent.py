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

from .base import LLMProvider, Message, ToolCall, ToolDefinition, ToolResult, Usage

ToolFunction = Callable[[dict], str]

# Defensive cap on what a single tool result sends back to the model. Tool
# outputs are meant to be information-dense summaries (see explain_target,
# target_evidence.py's formatters), not full dumps, but nothing upstream
# enforces a size limit -- a tool returning an unexpectedly large table
# would otherwise grow the in-loop conversation unboundedly and risk a 429
# on tokens-per-minute. Truncating here is provider-neutral and applies to
# every tool automatically, unlike capping inside each tool implementation.
_MAX_TOOL_RESULT_CHARS = 8000

# Ceiling on the *sum* of tool-result content within a single run() call. The
# per-result cap above bounds one call, but max_turns=8 with several tool
# calls per turn could otherwise still stack up a very large amount of tool
# output across a single request's tool-use loop before ever hitting that
# per-call limit. Roughly 8k tokens' worth of tool output, generous enough
# for a real multi-tool investigation but not open-ended.
_MAX_TOTAL_TOOL_RESULT_CHARS = 32000

_TOOL_BUDGET_EXHAUSTED_MESSAGE = (
    "Tool result omitted: this request already used its tool-output budget for this "
    "conversation turn. Answer with the evidence already gathered, or ask the user to "
    "narrow the request."
)


def _cap_tool_result(text: str) -> str:
    if len(text) <= _MAX_TOOL_RESULT_CHARS:
        return text
    return text[:_MAX_TOOL_RESULT_CHARS] + "\n...[truncated, result was longer]"


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
        self.last_usage = Usage()
        self.last_tool_calls: list[str] = []
        self.last_turns = 0
        self._tool_result_chars_used = 0

    def run(self, user_text: str, history: list[Message] | None = None) -> str:
        """history: prior turns to seed the conversation with (e.g. a chat
        endpoint round-tripping state from the frontend). After run()
        returns, self.last_messages holds the full updated conversation
        (history + this turn, including tool exchanges) for callers that
        need to persist/return it -- the return value itself stays a plain
        str so existing callers (test_llm_agent.py) are unaffected.
        self.last_usage/last_tool_calls/last_turns are reset and
        accumulated across every provider.generate() call in this run --
        a single user message can trigger several round-trips when the
        model chains tool calls, so per-call usage alone would undercount
        what the request actually cost."""
        messages: list[Message] = list(history) if history else []
        messages.append(Message(role="user", text=user_text))
        tool_defs = [entry.definition for entry in self.tools.values()]

        self.last_usage = Usage()
        self.last_tool_calls = []
        self.last_turns = 0
        self._tool_result_chars_used = 0

        for _ in range(self.max_turns):
            self.last_turns += 1
            response = self.provider.generate(messages, tool_defs, system=self.system)
            if response.usage:
                self.last_usage.input_tokens += response.usage.input_tokens
                self.last_usage.output_tokens += response.usage.output_tokens

            if response.stop_reason != "tool_use" or not response.tool_calls:
                messages.append(Message(role="assistant", text=response.text))
                self.last_messages = messages
                return response.text or ""

            messages.append(
                Message(role="assistant", text=response.text, tool_calls=response.tool_calls)
            )
            self.last_tool_calls.extend(call.name for call in response.tool_calls)
            tool_results = [self._execute(call) for call in response.tool_calls]
            messages.append(Message(role="user", tool_results=tool_results))

        self.last_messages = messages
        return "No pude completar la solicitud en el número de pasos permitido."

    def _execute(self, call: ToolCall) -> ToolResult:
        entry = self.tools.get(call.name)
        if entry is None:
            return ToolResult(tool_call_id=call.id, content=f"Unknown tool: {call.name}", is_error=True)
        if self._tool_result_chars_used >= _MAX_TOTAL_TOOL_RESULT_CHARS:
            return ToolResult(tool_call_id=call.id, content=_TOOL_BUDGET_EXHAUSTED_MESSAGE, is_error=True)
        try:
            result = _cap_tool_result(str(entry.run(call.input)))
            self._tool_result_chars_used += len(result)
            return ToolResult(tool_call_id=call.id, content=result)
        except Exception as exc:  # tool failures are reported to the model, not raised
            return ToolResult(tool_call_id=call.id, content=f"Error: {exc}", is_error=True)
