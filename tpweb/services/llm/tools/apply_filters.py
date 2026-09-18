"""Agent tools for discovering and applying protein-list filters.

Two tools, meant to be used together: the model calls list_available_filters
first to learn which ScoreParam/ScoreParamOptions ids exist for this
workspace, then calls apply_filters with concrete ids -- it has no other way
to know valid ids, since those are per-deployment data, not something a
general-purpose model could guess correctly.

Genome scope is intentionally NOT part of either tool's input_schema -- the
caller (AgentChatView) builds these entries per-request via the factory
functions below, closing over the already-resolved, access-checked
request/user, so the model can never spoof which workspace/session it is
filtering.
"""

from __future__ import annotations

from ..agent import ToolEntry
from ..base import ToolDefinition
from tpweb.services.protein_list import (
    apply_filter_changes,
    grouped_selected_parameters,
    normalize_selected_parameters,
)
from tpweb.services.score_param_types import is_categorical_score_param
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.workspace import get_workspace_session_value, set_workspace_session_value

LIST_AVAILABLE_FILTERS = ToolDefinition(
    name="list_available_filters",
    description=(
        "List every filterable field (ScoreParam) available in this workspace, with the "
        "concrete ids apply_filters needs. Categorical fields list their option ids/names "
        "(e.g. Druggability tiers, off-target hit/no_hit); numeric fields report their "
        "score_param_id for use with add_numeric_filter. Call this before apply_filters if "
        "you don't already know the right ids for the field the user is asking about."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)

APPLY_FILTERS = ToolDefinition(
    name="apply_filters",
    description=(
        "Apply one or more protein-list filter changes for the user's current session in a "
        "single call. Takes effect immediately -- if the user then opens the protein list "
        "page for this genome, the filters are already applied. Use list_available_filters "
        "first to look up valid filter_option_id/score_param_id values, then call this tool "
        "ONCE with every change the user asked for in the changes array (e.g. three separate "
        "criteria = one call with three entries in changes), not once per change -- each "
        "extra call adds a full round-trip of conversation history and cost for no benefit."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "description": "One or more filter changes to apply, in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "add_filter",
                                "add_numeric_filter",
                                "add_special_filter",
                                "remove_filter",
                            ],
                            "description": (
                                "add_filter: select a categorical option (needs filter_option_id). "
                                "add_numeric_filter: filter a numeric field by range (needs "
                                "score_param_id, numeric_operation, value, and value_max for "
                                "'between'). add_special_filter: filter by EC or GO term (needs "
                                "special_kind='ec'|'go' and special_value). remove_filter: remove a "
                                "previously-added filter (needs filter_option_id)."
                            ),
                        },
                        "filter_option_id": {"type": ["string", "integer"]},
                        "score_param_id": {"type": ["string", "integer"]},
                        "numeric_operation": {
                            "type": "string",
                            "enum": ["gte", "lte", "between"],
                        },
                        "value": {"type": ["string", "number"]},
                        "value_max": {"type": ["string", "number"]},
                        "special_kind": {"type": "string", "enum": ["ec", "go"]},
                        "special_value": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        "required": ["changes"],
    },
)

CLEAR_FILTERS = ToolDefinition(
    name="clear_filters",
    description=(
        "Clear every active protein-list filter for the current user's session. "
        "Use this directly when the user asks to remove, reset, clear, or borrar todos "
        "los filtros. Do not call list_available_filters first."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)


def build_list_available_filters_entry(user):
    def run(_input):
        score_params = visible_score_params_queryset(user).prefetch_related("choices")
        lines = []
        for score_param in score_params:
            if is_categorical_score_param(score_param):
                option_parts = [
                    f"{option.name} (filter_option_id={option.pk})"
                    for option in score_param.choices.all()[:20]
                ]
                extra_count = max(0, score_param.choices.count() - len(option_parts))
                if extra_count:
                    option_parts.append(f"... {extra_count} more option(s)")
                options = ", ".join(option_parts)
                if not options:
                    continue
                lines.append(
                    f"- {score_param.name} [{score_param.category}, categorical]: {options}"
                )
            else:
                lines.append(
                    f"- {score_param.name} [{score_param.category}, numeric, "
                    f"score_param_id={score_param.pk}]"
                )
        if not lines:
            return "No filterable fields are available for this genome."
        return "\n".join(lines)

    return ToolEntry(definition=LIST_AVAILABLE_FILTERS, run=run)


def build_clear_filters_entry(request, user):
    def run(_input):
        set_workspace_session_value(request.session, user, "selected_parameters", [])
        return "All protein-list filters were cleared for the current session."

    return ToolEntry(definition=CLEAR_FILTERS, run=run)


def build_apply_filters_entry(request, user):
    def run(input):
        changes = input.get("changes") or []
        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, user, "selected_parameters", [])
        )
        selected_parameters = apply_filter_changes(selected_parameters, changes)
        set_workspace_session_value(
            request.session, user, "selected_parameters", selected_parameters
        )

        if not selected_parameters:
            return "All filters cleared. The protein list currently shows every protein in this genome."

        grouped = grouped_selected_parameters(selected_parameters, humanize=True)
        summary = "; ".join(f"{name}: {values}" for name, values in grouped)
        return f"Filters applied. Active filters: {summary}"

    return ToolEntry(definition=APPLY_FILTERS, run=run)
