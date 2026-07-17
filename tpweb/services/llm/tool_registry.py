"""Builds the tools dict for a given genome/protein scope.

Shared by AgentChatView (one call per HTTP request) and the evaluate_agent
management command (one call per eval case), so the set of tools wired up
for a given scope can never silently drift between the real endpoint and
the eval harness that is supposed to be testing it.
"""
from __future__ import annotations

from .tools.apply_filters import (
    build_apply_filters_entry,
    build_clear_filters_entry,
    build_list_available_filters_entry,
)
from .tools.demo import ENTRY as GET_CURRENT_TIME_ENTRY
from .tools.explain_target import build_explain_target_entry
from .tools.search_proteins import build_search_proteins_entry
from .tools.target_review import build_audit_target_evidence_entry, build_compare_targets_entry


def build_scoped_tools(request, assembly_name, default_accession, workspace_user, session_user):
    """`request` only needs a `.session` attribute supporting `.get()` and
    `__setitem__` -- a plain dict works fine (see get_workspace_session_value/
    set_workspace_session_value in tpweb/services/workspace.py) -- so callers
    without a real Django request (e.g. a management command) can pass a
    lightweight stand-in instead of building one via RequestFactory.

    Returns just {"get_current_time": ...} when assembly_name is falsy,
    matching AgentChatView's existing behavior for pages with no genome in
    scope (filter/search/explain tools stay unavailable there)."""
    tools = {"get_current_time": GET_CURRENT_TIME_ENTRY}
    if not assembly_name:
        return tools
    tools["list_available_filters"] = build_list_available_filters_entry(workspace_user)
    tools["apply_filters"] = build_apply_filters_entry(request, session_user)
    tools["clear_filters"] = build_clear_filters_entry(request, session_user)
    tools["search_proteins"] = build_search_proteins_entry(assembly_name)
    tools["explain_target"] = build_explain_target_entry(assembly_name, default_accession)
    tools["audit_target_evidence"] = build_audit_target_evidence_entry(assembly_name, default_accession)
    tools["compare_targets"] = build_compare_targets_entry(assembly_name)
    return tools
