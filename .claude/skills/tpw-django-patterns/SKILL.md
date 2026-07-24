---
name: tpw-django-patterns
description: Django view/service architecture conventions for Target Pathogen Web — service-layer separation, prefetch reuse, the genome-scoped caching pattern, safe deduplication of copy-pasted helpers, and how to verify backend changes without a local execution environment. Load before editing files under tpweb/views/ or tpweb/services/.
---

# Target Pathogen Web — Django backend conventions

## Views delegate to services

Per CLAUDE.md's layout: `tpweb/views/` should stay thin (request handling, calling services,
assembling the render context); business logic — anything reusable, testable without a `request`
object — belongs in `tpweb/services/*.py`. If you find yourself writing a non-trivial helper
function inside a view file, check whether it's really view-specific or whether it belongs in a
service module instead (this session moved `_druggability_label`, `_chain_selector`,
`_annotation_name`, and `_build_view_export_url` out of `ProteinView.py` into
`protein_summary.py` / `structure_sources.py` / `protein_annotations.py` / `csv_exports.py` for
exactly this reason).

## Reuse prefetches — don't silently re-query

If a relation is already loaded via `.prefetch_related()` (optionally as an ordered
`Prefetch("relation", queryset=Model.objects.order_by(...))`), call `.all()` on the
already-fetched relation later in the same request instead of running a fresh
`Model.objects.filter(...)` for "the same" data. Re-querying looks harmless but silently defeats
the prefetch and adds a redundant round trip — caught and fixed for
`protein.experimental_structure_xrefs` in `ProteinView.py` this session, where the exact same
filtered/ordered query was being run twice.

## Caching convention for genome-scoped aggregates

When a computation is scoped to a genome (or another entity broader than the current request) —
not to the individual protein/page being rendered — cache it, don't recompute it on every request
that happens to touch that genome. The established pattern (`tpweb/services/assembly_workspace.py`):

```python
from django.core.cache import cache
OVERVIEW_CACHE_TTL_SECONDS = 900  # named constant, not a magic number

def _some_genome_scoped_aggregate(biodatabase):
    cache_key = f"Target:{scope_name}:{biodatabase.biodatabase_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    value = ...  # the actual expensive query/aggregation
    cache.set(cache_key, value, OVERVIEW_CACHE_TTL_SECONDS)
    return value
```

Reuse this exact shape (TTL constant name, `f"Target:{scope}:{params}"` key format) rather than
inventing a new caching approach — `protein_summary.py`'s `_genome_centrality_values` is a second,
directly-copied application of it (caching the genome-wide `PTOOLS_betweenness_centrality`
distribution that was previously being re-scanned from scratch on every single protein page view).

## Before deduplicating a copy-pasted helper, grep every call site first

When you spot "the same function copy-pasted in N places," grep the *whole* codebase for it before
unifying — don't assume the copies are identical just because they look identical at the two sites
you happened to find first. `_build_view_export_url` turned out to be duplicated across 5 view
files, and one of them (`ProteinListView.py`) had a genuine behavioral difference (it also stripped
the `page` query param, so a stale page number wouldn't silently limit an export to one page). The
fix was an optional parameter (`strip_params=()`) on the unified function, not a blind merge that
would have silently dropped that behavior for the one caller that needed it.

## Consolidating "the same computed dict" built two ways

If you find a view building an inline dict that duplicates what an existing service function
already returns (especially if that function's own docstring says it's meant to cover this
caller too but was never wired up), prefer calling the existing function over hand-keeping two
copies in sync. But verify field-by-field that the function's internal query/logic doesn't
silently diverge from what the caller already has — this session almost inverted which field wins
(`numeric_value` vs `.value`) when consolidating a duplicated score lookup into
`build_protein_executive_context`; the fix was building the shared query result as a list once and
extracting from that same list using the *original* priority order, not assuming the two
code paths resolved values identically.

## `{% regroup %}` requires pre-sorted input

Django's `{% regroup list by attr as groups %}` only works correctly if `list` is already sorted by
`attr` — it does not sort for you. Before relying on it, verify the actual iteration order of
the source data (e.g., a hardcoded metadata list's definition order, or an explicit `.order_by()`
on the queryset) rather than assuming it happens to be grouped correctly.

## Verifying backend changes with no local execution environment

This working setup typically has no local Docker/Python/test-runner available — Python changes
can't be executed or tested directly. Verify by tracing manually instead:
- Read the full body of every function you touch, not just the diff.
- Grep for every call site of anything you rename, move, or change the signature of.
- After adding an import, check whether a local definition with the same name already exists
  further down in the file (a new import can silently shadow — or be shadowed by — an existing
  local function of the same name).
- After removing a query/usage, grep for the import it required and remove it if now unused.

Explicitly tell the user that backend changes need live verification (query counts, actual
rendered output) on their real Docker/cluster environment — manual tracing proves the logic is
consistent, not that it behaves identically to before at runtime.
