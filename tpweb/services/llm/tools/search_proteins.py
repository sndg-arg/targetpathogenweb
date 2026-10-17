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
        },
    },
)


def build_search_proteins_entry(assembly_name):
    def run(input):
        changes = input.get("changes") or []
        selected_parameters = apply_filter_changes([], changes)
        search_text = input.get("search_text")
        limit = input.get("limit", 10)

        results, total = find_top_proteins(
            assembly_name, selected_parameters, search_text, limit, with_total=True
        )
        if not results:
            return "No proteins matched those criteria."
        criteria = "; ".join(
            f"{name}: {values}"
            for name, values in grouped_selected_parameters(selected_parameters, humanize=True)
        )

        lines = [
            f"- {row['accession']}: {row['description'] or 'no description'}"
            + (
                f" (druggability {row['druggability']:.2f})"
                if row["druggability"] is not None
                else ""
            )
            for row in results
        ]
        # Say plainly how the list is ordered and that it may be a sample, so the
        # model doesn't present an accession-ordered slice as "the best" proteins.
        header = (
            f"{total} protein(s) match"
            + (f" [criteria applied: {criteria}]" if criteria else "")
            + f". Showing {len(results)} in accession order (not ranked by any score)"
            + (" -- this is only a sample of the matches." if total > len(results) else ":")
        )
        return header + "\n" + "\n".join(lines)

    return ToolEntry(definition=SEARCH_PROTEINS, run=run)
