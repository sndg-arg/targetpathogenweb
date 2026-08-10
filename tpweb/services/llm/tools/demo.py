"""Trivial demo tool used to validate the provider-agnostic agent loop
end-to-end, before wiring in real Target actions (e.g. applying protein
filters via ProteinListView's apply_filter_changes).
"""

from __future__ import annotations

import datetime

from ..agent import ToolEntry
from ..base import ToolDefinition

GET_CURRENT_TIME = ToolDefinition(
    name="get_current_time",
    description=(
        "Return the current server date and time. Use this when the user "
        "asks what time or date it is right now."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
)


def get_current_time(_input: dict) -> str:
    return datetime.datetime.now().isoformat()


ENTRY = ToolEntry(definition=GET_CURRENT_TIME, run=get_current_time)
