"""HTTP endpoint for the in-app AI assistant drawer.

Conversation history is stateless and round-tripped from the frontend (see
tpweb/services/llm/agent.py's Agent.run history param) rather than
persisted server-side -- the drawer is ephemeral, page-context-aware
chrome, not a saved chat product.

Genome/protein scope is never taken from the request body directly -- it
is re-derived server-side from page_path (the frontend's
window.location.pathname) via Django's own URL resolver, then
access-checked, exactly like every other view in this app. This means the
model can never be tricked into acting on a genome the requesting user
doesn't have access to.
"""
from __future__ import annotations

import json
import os

from django.http import JsonResponse
from django.urls import resolve
from django.urls.exceptions import Resolver404
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.services.genome_workspace import resolve_genome_from_slug, user_can_access_genome_name
from tpweb.services.workspace import resolve_workspace_user
from tpweb.services.llm.agent import Agent
from tpweb.services.llm.base import Message, ToolCall, ToolResult
from tpweb.services.llm.provider_factory import get_provider, llm_agent_enabled
from tpweb.services.llm.tools.demo import ENTRY as GET_CURRENT_TIME_ENTRY
from tpweb.services.llm.tools.apply_filters import (
    build_apply_filters_entry,
    build_list_available_filters_entry,
)
from tpweb.services.llm.tools.explain_target import build_explain_target_entry
from tpweb.services.llm.tools.search_proteins import build_search_proteins_entry

SYSTEM_PROMPT = (
    "You are the in-app assistant for TargetPathogenWeb, a bioinformatics platform for "
    "prioritizing drug targets in pathogen genomes. Help the user explore proteins, filters, "
    "scores, ligands, and structural/metabolic evidence already loaded in the app. Answer in "
    "the same language the user writes in. Only use the tools available to you; if a tool you "
    "need isn't available (for example, no genome is in scope on this page), say so plainly "
    "instead of guessing."
)

NO_GENOME_SCOPE_NOTE = (
    " No genome is currently in scope for this page, so filter/search/target-explanation "
    "tools are unavailable -- you can still answer general questions about the platform."
)


def _message_to_json(message: Message) -> dict:
    return {
        "role": message.role,
        "text": message.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "input": call.input}
            for call in message.tool_calls
        ],
        "tool_results": [
            {"tool_call_id": result.tool_call_id, "content": result.content, "is_error": result.is_error}
            for result in message.tool_results
        ],
    }


def _message_from_json(data: dict) -> Message:
    return Message(
        role=data.get("role") or "user",
        text=data.get("text"),
        tool_calls=[ToolCall(**call) for call in data.get("tool_calls") or []],
        tool_results=[ToolResult(**result) for result in data.get("tool_results") or []],
    )


class AgentChatView(View):
    def post(self, request, *args, **kwargs):
        if not llm_agent_enabled() and not os.environ.get("TPW_LLM_PROVIDER", "").strip():
            return JsonResponse(
                {
                    "error": (
                        "Assistant is not enabled. Set OPENAI_AGENT_ENABLED=true and "
                        "OPENAI_API_KEY on the server."
                    )
                },
                status=503,
            )

        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        message = str(payload.get("message") or "").strip()
        if not message:
            return JsonResponse({"error": "message is required."}, status=400)

        try:
            history = [_message_from_json(item) for item in payload.get("history") or []]
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid history."}, status=400)

        workspace_user = resolve_workspace_user(request.user)
        assembly_name, default_accession = self._resolve_page_scope(
            request.user, str(payload.get("page_path") or "")
        )

        tools = {"get_current_time": GET_CURRENT_TIME_ENTRY}
        system = SYSTEM_PROMPT
        if assembly_name:
            tools["list_available_filters"] = build_list_available_filters_entry(workspace_user)
            tools["apply_filters"] = build_apply_filters_entry(request, workspace_user)
            tools["search_proteins"] = build_search_proteins_entry(assembly_name)
            tools["explain_target"] = build_explain_target_entry(assembly_name, default_accession)
        else:
            system += NO_GENOME_SCOPE_NOTE

        try:
            provider = get_provider()
        except Exception as exc:
            return JsonResponse({"error": f"LLM provider unavailable: {exc}"}, status=502)

        agent = Agent(provider=provider, tools=tools, system=system)
        try:
            reply = agent.run(message, history=history)
        except Exception as exc:
            return JsonResponse({"error": f"Assistant request failed: {exc}"}, status=502)

        return JsonResponse({
            "reply": reply,
            "history": [_message_to_json(item) for item in agent.last_messages],
        })

    @staticmethod
    def _resolve_page_scope(user, page_path):
        """Return (assembly_name, default_accession) for the given
        window.location.pathname, or (None, None) if it doesn't resolve to
        an accessible genome/protein page."""
        page_path = page_path.strip()
        if not page_path:
            return None, None
        try:
            match = resolve(page_path)
        except Resolver404:
            return None, None

        protein_id = match.kwargs.get("protein_id")
        if protein_id is not None:
            protein = (
                Bioentry.objects.filter(bioentry_id=protein_id)
                .select_related("biodatabase")
                .first()
            )
            if protein is None:
                return None, None
            assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
            if not user_can_access_genome_name(user, assembly_name):
                return None, None
            return assembly_name, protein.accession

        genome_slug = match.kwargs.get("genome")
        if genome_slug:
            assembly_name = resolve_genome_from_slug(user, genome_slug)
            if assembly_name:
                return assembly_name, None

        return None, None
