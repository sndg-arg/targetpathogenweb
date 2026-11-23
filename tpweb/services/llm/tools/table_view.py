"""Agent tool for changing what the protein table shows: its columns and the
column it is sorted by. Columns live in the session (same key the table's own
Columns panel writes); the sort is a URL parameter, so the tool returns the
table link with it and AgentChatView reloads the table with it when the user
is looking at it."""

from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse

from ..agent import ToolEntry
from ..base import ToolDefinition
from tpweb.services.genome_workspace import genome_url_slug
from tpweb.services.protein_list import DEFAULT_PROTEIN_COLUMNS, VISIBLE_COLUMNS_SESSION_KEY
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.workspace import get_workspace_session_value, set_workspace_session_value

SET_TABLE_VIEW = ToolDefinition(
    name="set_table_view",
    description=(
        "Change the user's protein table for this genome: add or remove columns and/or sort "
        "it by a column. Column names are the field names list_available_filters reports "
        "(e.g. reaction_support). Use it when the user asks to show a column or to rank/sort "
        "the table; then give them the returned link."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "add_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Field names to add as columns.",
            },
            "remove_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Field names to remove from the columns.",
            },
            "sort_by": {
                "type": "string",
                "description": "Field name to sort the table by; added as a column if missing.",
            },
            "descending": {
                "type": "boolean",
                "description": "With sort_by: highest values first (default true).",
            },
        },
        "additionalProperties": False,
    },
)


def table_sort_query(sort_by, descending=True):
    return urlencode({"sort_col": sort_by, "sort_dir": "desc" if descending else "asc"})


def build_set_table_view_entry(request, user, assembly_name):
    def run(input):
        visible = set(
            visible_score_params_queryset(user, genome_name=assembly_name).values_list(
                "name", flat=True
            )
        )
        columns = get_workspace_session_value(
            request.session, user, VISIBLE_COLUMNS_SESSION_KEY, None
        )
        if columns is None:
            columns = [name for name in DEFAULT_PROTEIN_COLUMNS if name in visible]
        columns = [name for name in columns if name in visible]

        sort_by = str(input.get("sort_by") or "").strip()
        descending = input.get("descending", True) is not False
        requested = [str(name).strip() for name in input.get("add_columns") or []]
        if sort_by:
            requested.append(sort_by)
        unknown = [name for name in requested if name and name not in visible]
        for name in requested:
            if name in visible and name not in columns:
                columns.append(name)
        removed = {str(name).strip() for name in input.get("remove_columns") or []}
        columns = [name for name in columns if name not in removed or name == sort_by]
        set_workspace_session_value(request.session, user, VISIBLE_COLUMNS_SESSION_KEY, columns)

        url = reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)})
        if sort_by and sort_by in visible:
            url = f"{url}?{table_sort_query(sort_by, descending)}"
        lines = [f"Protein table columns now: {', '.join(columns) or 'none'}."]
        if sort_by and sort_by in visible:
            lines.append(
                f"Sorted by {sort_by}, {'highest' if descending else 'lowest'} first "
                "(proteins without a value last)."
            )
        if unknown:
            lines.append(
                f"Not available for this genome: {', '.join(unknown)} "
                "(check list_available_filters for exact names)."
            )
        lines.append(f"Table link: {url}")
        return "\n".join(lines)

    return ToolEntry(definition=SET_TABLE_VIEW, run=run)
