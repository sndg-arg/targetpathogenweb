"""Agent tool for finding proteins in the current genome matching given
criteria. Reuses the exact same `changes` schema as apply_filters (see
apply_filters.py) so there is one shared natural-language-to-filter-dict
path -- this tool just applies the changes to a throwaway, session-free
list instead of persisting them, then runs the resulting filter.
"""

from __future__ import annotations

from ..agent import ToolEntry
from ..base import ToolDefinition
from tpweb.services.protein_list import (
    apply_filter_changes,
    find_top_proteins,
    grouped_selected_parameters,
)
from tpweb.services.llm.tools.apply_filters import APPLY_FILTERS
from tpweb.services.score_param_types import is_categorical_score_param
from tpweb.services.score_params import visible_score_params_queryset

SEARCH_PROTEINS = ToolDefinition(
    name="search_proteins",
    description=(
        "Find proteins in the current genome matching filter criteria and/or a text search, "
        "without changing the user's active filters. Use list_available_filters first to look "
        "up valid filter_option_id/score_param_id values for the `changes` field, which uses "
        "the same shape as apply_filters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "description": "Same shape as apply_filters' changes -- criteria to match, not applied to the session.",
                "items": APPLY_FILTERS.input_schema["properties"]["changes"]["items"],
            },
            "search_text": {
                "type": "string",
                "description": "Optional free-text search over accession/description/gene name.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of proteins to return (default 10, max 25).",
            },
            "sort_by": {
                "type": "string",
                "description": (
                    "Optional numeric field name (score param name from "
                    "list_available_filters, e.g. reaction_support) to rank the matches by."
                ),
            },
            "descending": {
                "type": "boolean",
                "description": "With sort_by: highest values first (default true).",
            },
        },
    },
)


def build_search_proteins_entry(assembly_name, user=None):
    def run(input):
        changes = input.get("changes") or []
        selected_parameters = apply_filter_changes([], changes)
        search_text = input.get("search_text")
        limit = input.get("limit", 10)
        sort_by = str(input.get("sort_by") or "").strip() or None
        descending = input.get("descending", True) is not False
        if sort_by:
            sort_param = (
                visible_score_params_queryset(user, genome_name=assembly_name)
                .filter(name=sort_by)
                .first()
            )
            if sort_param is None or is_categorical_score_param(sort_param):
                return (
                    f"Cannot rank by '{sort_by}': it is not a numeric field of this genome. "
                    "Use list_available_filters to find the right name."
                )

        results, total = find_top_proteins(
            assembly_name,
            selected_parameters,
            search_text,
            limit,
            with_total=True,
            sort_by=sort_by,
            descending=descending,
        )
        if not results:
            return "No proteins matched those criteria."
        criteria = "; ".join(
            f"{name}: {values}"
            for name, values in grouped_selected_parameters(selected_parameters, humanize=True)
        )

        lines = [
            f"- {row['accession']}: {row['description'] or 'no description'}"
            + (f" ({sort_by} {row['sort_value']:.4g})" if row["sort_value"] is not None else "")
            + (
                f" (druggability {row['druggability']:.2f})"
                if row["druggability"] is not None
                else ""
            )
            for row in results
        ]
        # Say plainly how the list is ordered and that it may be a sample, so the
        # model doesn't present an accession-ordered slice as "the best" proteins.
        if sort_by:
            order_text = (
                f"ranked by {sort_by} ({'highest' if descending else 'lowest'} first; "
                "proteins without a value last)"
            )
        else:
            order_text = "in accession order (not ranked by any score)"
        header = (
            f"{total} protein(s) match"
            + (f" [criteria applied: {criteria}]" if criteria else "")
            + f". Showing {len(results)} {order_text}"
            + (" -- this is only a sample of the matches." if total > len(results) else ":")
        )
        return header + "\n" + "\n".join(lines)

    return ToolEntry(definition=SEARCH_PROTEINS, run=run)
