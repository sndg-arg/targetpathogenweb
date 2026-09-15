"""HTTP endpoint for the in-app AI assistant drawer.

Gated by the tpweb.can_use_agent_chat permission (each LLM call costs real
money) -- previously open to anonymous visitors too; that changed once
per-user permissions existed to actually restrict it.

Conversation history is persisted server-side as AgentChatSession rows,
keyed by Django session key rather than by authenticated user -- a legacy
of when this was anonymous-accessible; kept as-is since it still works
fine for logged-in use (a browser session maps to one person in practice).
A browser session can hold several conversations over time (split by
inactivity or an explicit "new conversation" action); see
tpweb/services/agent_chat_sessions.py for the rules on which conversation
a given turn belongs to and how long conversations are kept.

Genome/protein scope is never taken from the request body directly -- it
is re-derived server-side from page_path (the frontend's
window.location.pathname) via Django's own URL resolver, then
access-checked, exactly like every other view in this app. This means the
model can never be tricked into acting on a genome the requesting user
doesn't have access to.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import JsonResponse
from django.urls import resolve
from django.urls.exceptions import Resolver404
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.Binders import Binders
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.services.agent_chat_sessions import (
    default_conversation,
    delete_conversation,
    find_conversation,
    list_conversations,
    rename_conversation,
    resolve_active_conversation,
    set_title_if_blank,
)
from tpweb.services.genome_workspace import resolve_genome_from_slug, user_can_access_genome_name
from tpweb.services.workspace import resolve_workspace_user, set_workspace_session_value
from tpweb.services.llm.agent import Agent
from tpweb.services.llm.base import Message, ToolCall, ToolResult
from tpweb.services.llm.provider_factory import get_provider, llm_agent_enabled
from tpweb.services.llm.prompts import (
    BIOLOGIST_MODE_NOTE,
    NO_GENOME_SCOPE_NOTE,
    SYSTEM_PROMPT,
    page_context_prompt,
)
from tpweb.services.llm.tool_registry import build_scoped_tools

logger = logging.getLogger("tpweb.agent")


def _message_to_json(message: Message) -> dict:
    return {
        "role": message.role,
        "text": message.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "input": call.input} for call in message.tool_calls
        ],
        "tool_results": [
            {
                "tool_call_id": result.tool_call_id,
                "content": result.content,
                "is_error": result.is_error,
            }
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


def _truncate_text(text, limit=2400):
    if not text:
        return text
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _compact_value(value, text_limit=180):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    if len(text) > text_limit:
        return text[: text_limit - 1].rstrip() + "…"
    return text


def _sanitize_page_state(value, depth=0):
    """Keep a tiny browser UI snapshot.

    This is intentionally lossy: the agent only needs to know what the user
    is looking at, not receive page HTML or whole tables. Genome/protein
    authorization is still resolved server-side from the URL.
    """
    if depth > 4:
        return None
    if isinstance(value, dict):
        allowed_keys = {
            "title",
            "heading",
            "subheading",
            "path",
            "query",
            "active_filters",
            "sort",
            "active_tabs",
            "selected_pocket",
            "selected_structure",
            "structure_viewer",
            "spin",
            "view_mode",
            "visible_proteins",
            "accession",
            "description",
            "visible_values",
            "method",
            "id",
            "score",
            "active_layers",
        }
        result = {}
        for key, item in value.items():
            if key not in allowed_keys:
                continue
            compact = _sanitize_page_state(item, depth + 1)
            if compact not in (None, "", [], {}):
                result[key] = compact
        return result
    if isinstance(value, list):
        result = []
        for item in value[:8]:
            compact = _sanitize_page_state(item, depth + 1)
            if compact not in (None, "", [], {}):
                result.append(compact)
        return result
    return _compact_value(value)


def _compact_history(history, max_messages=10):
    """Keep short recent visible chat context only.

    Tool calls/results can be very large (especially list_available_filters) and
    do not need to be replayed on every turn. Keeping only user/assistant text
    prevents TPM spikes while preserving the conversation the user sees.
    """
    compact = []
    for message in history[-max_messages:]:
        if not message.text:
            continue
        compact.append(Message(role=message.role, text=_truncate_text(message.text)))
    return compact


def _looks_like_clear_filters(message):
    text = str(message or "").strip().lower()
    if not text:
        return False
    has_filter = "filtro" in text or "filter" in text
    has_clear = any(
        token in text
        for token in (
            "borrar",
            "borra",
            "limpiar",
            "limpia",
            "sacar",
            "saca",
            "reset",
            "clear",
            "remove",
        )
    )
    return has_filter and has_clear


def _tool_was_called(messages, tool_name):
    for message in messages:
        for call in message.tool_calls:
            if call.name == tool_name:
                return True
    return False


def _ensure_session_key(request):
    """Django sessions are lazy -- session_key stays None until something is
    stored in the session, so force creation the first time a visitor opens
    the drawer rather than only after some unrelated view happens to write
    to request.session."""
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _history_from_row(row):
    if row is None:
        return []
    try:
        return [_message_from_json(item) for item in row.history_json or []]
    except (TypeError, ValueError):
        # Malformed/legacy row -- start fresh rather than 500ing the drawer.
        return []


def _save_persisted_history(row, messages):
    # Deliberately doesn't touch "title" -- set_title_if_blank/rename_conversation
    # persist that field themselves, so a rename committed mid-request can never
    # get clobbered by this save re-writing a stale in-memory title.
    row.history_json = [_message_to_json(item) for item in messages]
    row.save(update_fields=["history_json", "updated_at"])


class AgentChatView(PermissionRequiredMixin, View):
    permission_required = "tpweb.can_use_agent_chat"
    raise_exception = True

    def get(self, request, *args, **kwargs):
        """Hydrates the drawer with a conversation's saved history on page
        load -- without this, 'persisted' history would never be visible
        again after a reload, defeating the point of persisting it.

        With no conversation_id, hydrates the session's current (recently
        active) conversation, if any -- a bare page load never creates one.
        """
        session_key = _ensure_session_key(request)
        conversation_id = request.GET.get("conversation_id")
        row = (
            find_conversation(session_key, conversation_id)
            if conversation_id
            else default_conversation(session_key)
        )
        history = _history_from_row(row)
        return JsonResponse(
            {
                "history": [_message_to_json(item) for item in history],
                "conversation_id": row.pk if row else None,
                "title": row.title if row else None,
            }
        )

    def post(self, request, *args, **kwargs):
        if not llm_agent_enabled() and not os.environ.get("TPW_LLM_PROVIDER", "").strip():
            # Detailed enough to action for whoever deploys this (env var names), but this
            # is a deployment-config state a regular user has no way to fix themselves --
            # not something to soften into a generic "try again" message.
            return JsonResponse(
                {
                    "error": (
                        "The assistant is not enabled on this server. An administrator needs "
                        "to set OPENAI_AGENT_ENABLED=true and OPENAI_API_KEY (or the "
                        "equivalent for TPW_LLM_PROVIDER) before it can be used."
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
        page_state = _sanitize_page_state(payload.get("page_state") or {})
        biologist_mode = bool(payload.get("biologist_mode"))

        session_key = _ensure_session_key(request)
        requested_conversation_id = payload.get("conversation_id")
        row = resolve_active_conversation(
            session_key,
            conversation_id=requested_conversation_id,
            force_new=bool(payload.get("force_new")),
        )
        # True when the client explicitly pointed at a conversation that no longer
        # resolves to one it owns (e.g. deleted from another tab) -- the response
        # still succeeds (against a freshly resolved/created conversation instead),
        # but the client should tell the user rather than silently reattaching.
        conversation_reset = bool(requested_conversation_id) and str(row.pk) != str(
            requested_conversation_id
        )
        set_title_if_blank(row, message)
        history = _history_from_row(row)

        workspace_user = resolve_workspace_user(request.user)
        session_user = request.user
        page_path = str(payload.get("page_path") or "")
        page_url = str(payload.get("page_url") or "")
        # Only used to disambiguate a PDB structure page that legitimately links to
        # bioentries in more than one genome (see _scope_from_struct_id) -- the
        # frontend already sends this in page_url, just unused until now.
        requested_protein_id = parse_qs(urlparse(page_url).query).get("protein_id", [None])[0]
        assembly_name, default_accession = self._resolve_page_scope(
            request.user, page_path, requested_protein_id=requested_protein_id
        )
        if assembly_name and _looks_like_clear_filters(message):
            set_workspace_session_value(request.session, session_user, "selected_parameters", [])
            on_list_page = self._is_protein_list_path(page_path)
            reply = "Listo, borre todos los filtros de la lista de proteinas para esta sesion. " + (
                "Recargo la lista para que lo veas aplicado."
                if on_list_page
                else "Se van a aplicar la proxima vez que abras la lista de proteinas."
            )
            history = _compact_history(
                [
                    *history,
                    Message(role="user", text=message),
                    Message(role="assistant", text=reply),
                ]
            )
            _save_persisted_history(row, history)
            response = {
                "reply": reply,
                "history": [_message_to_json(item) for item in history],
                "conversation_id": row.pk,
                "title": row.title,
                "conversation_reset": conversation_reset,
            }
            if on_list_page:
                response["reload"] = True
                response["redirect_url"] = self._reload_url_without_query(page_url or page_path)
            return JsonResponse(response)

        system = SYSTEM_PROMPT
        if biologist_mode:
            system += BIOLOGIST_MODE_NOTE
        if assembly_name:
            system += page_context_prompt(assembly_name, default_accession)
            system += self._page_state_prompt(page_state)
        else:
            system += NO_GENOME_SCOPE_NOTE
        tools = build_scoped_tools(
            request, assembly_name, default_accession, workspace_user, session_user
        )

        started_at = time.perf_counter()
        try:
            provider = get_provider()
        except Exception as exc:
            # Full exception (missing API key, bad TPW_LLM_PROVIDER value, ...) goes to the
            # server log for debugging; the client only gets a generic, retry-safe message.
            # Provider internals (SDK error text, API error bodies) have no actionable
            # content for an end user and shouldn't leak into the chat UI.
            logger.warning("agent_chat provider_unavailable error=%s", exc)
            return JsonResponse(
                {
                    "error": "The assistant is temporarily unavailable. Try again in a moment.",
                    "retryable": True,
                },
                status=502,
            )

        agent = Agent(provider=provider, tools=tools, system=system)
        try:
            reply = agent.run(message, history=history)
        except Exception as exc:
            logger.warning(
                "agent_chat failed model=%s latency_ms=%d error=%s",
                getattr(provider, "model", "?"),
                round((time.perf_counter() - started_at) * 1000),
                exc,
            )
            return JsonResponse(
                {
                    "error": (
                        "The assistant could not complete this request. This is usually "
                        "temporary (a busy or rate-limited AI provider) -- try again in a "
                        "moment."
                    ),
                    "retryable": True,
                },
                status=502,
            )

        logger.info(
            "agent_chat ok model=%s input_tokens=%d output_tokens=%d latency_ms=%d turns=%d tool_calls=%s",
            getattr(provider, "model", "?"),
            agent.last_usage.input_tokens,
            agent.last_usage.output_tokens,
            round((time.perf_counter() - started_at) * 1000),
            agent.last_turns,
            ",".join(agent.last_tool_calls) or "-",
        )

        persisted_history = _compact_history(agent.last_messages, max_messages=12)
        _save_persisted_history(row, persisted_history)
        response = {
            "reply": reply,
            "history": [_message_to_json(item) for item in persisted_history],
            "conversation_id": row.pk,
            "title": row.title,
            "conversation_reset": conversation_reset,
        }
        if (
            _tool_was_called(agent.last_messages, "clear_filters")
            or _tool_was_called(agent.last_messages, "apply_filters")
        ) and self._is_protein_list_path(page_path):
            response["reload"] = True
            response["redirect_url"] = self._reload_url_without_query(page_url or page_path)
        return JsonResponse(response)

    @staticmethod
    def _resolve_page_scope(user, page_path, requested_protein_id=None):
        """Return (assembly_name, default_accession) for the given
        window.location.pathname, or (None, None) if it doesn't resolve to
        an accessible genome/protein page.

        requested_protein_id (from the page's own ?protein_id= query param,
        if any) only matters for _scope_from_struct_id -- a PDB structure
        page can legitimately be linked from more than one genome's protein
        (see that method's docstring), so page_path alone can be ambiguous.
        """
        candidate_paths = AgentChatView._candidate_paths(page_path)
        if not candidate_paths:
            return None, None

        for candidate in candidate_paths:
            try:
                match = resolve(candidate)
            except Resolver404:
                continue

            protein_id = match.kwargs.get("protein_id")
            if protein_id is not None:
                return AgentChatView._scope_from_protein_id(user, protein_id)

            struct_id = match.kwargs.get("struct_id")
            if struct_id is not None:
                return AgentChatView._scope_from_struct_id(user, struct_id, requested_protein_id)

            binder_id = match.kwargs.get("binder_id")
            if binder_id is not None:
                return AgentChatView._scope_from_binder_id(user, binder_id)

            genome_slug = match.kwargs.get("genome")
            if genome_slug:
                assembly_name = resolve_genome_from_slug(user, genome_slug)
                if assembly_name:
                    return assembly_name, None

        fallback = AgentChatView._fallback_scope_from_path(
            user, candidate_paths[0], requested_protein_id
        )
        if fallback:
            return fallback

        return None, None

    @staticmethod
    def _candidate_paths(page_path):
        page_path = (page_path or "").strip()
        if not page_path:
            return []

        parsed = urlparse(page_path)
        path = parsed.path or page_path
        if not path.startswith("/"):
            path = "/" + path

        candidates = [path]
        force_script_name = (
            os.environ.get("FORCE_SCRIPT_NAME", "").strip()
            or str(getattr(settings, "FORCE_SCRIPT_NAME", "") or "").strip()
        )
        if force_script_name and path.startswith(force_script_name + "/"):
            candidates.append(path[len(force_script_name) :] or "/")

        for marker in ("/protein/", "/genome/", "/structure/", "/binder/"):
            index = path.find(marker)
            if index > 0:
                candidates.append(path[index:])

        seen = set()
        result = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
        return result

    @staticmethod
    def _reload_url_without_query(page_url):
        parsed = urlparse(page_url or "")
        path = parsed.path or page_url or ""
        return path if path.startswith("/") else ""

    @staticmethod
    def _scope_from_protein_id(user, protein_id):
        protein = (
            Bioentry.objects.filter(bioentry_id=protein_id).select_related("biodatabase").first()
        )
        if protein is None:
            return None, None
        assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
        if not user_can_access_genome_name(user, assembly_name):
            return None, None
        return assembly_name, protein.accession

    @staticmethod
    def _scope_from_struct_id(user, struct_id, requested_protein_id=None):
        """A PDB structure page's genome isn't always unambiguous: the same
        experimental PDB code can be the "best structure" for orthologous
        proteins across more than one target genome (the pipeline looks up
        PDB rows by code alone, with no genome filter -- see
        experimental_structures.py / load_selected_pdb_backfill.py), so more
        than one BioentryStructure row can point at the same pdb_id. Mirrors
        StructureView._resolve_source_bioentry's own disambiguation: prefer
        the specific protein_id the page itself is showing (from its
        ?protein_id= query param) and only fall back to "first link" if that
        wasn't given -- never guess when we don't have to.
        """
        link = None
        if requested_protein_id and str(requested_protein_id).isdigit():
            link = (
                BioentryStructure.objects.select_related("bioentry__biodatabase")
                .filter(pdb_id=struct_id, bioentry_id=int(requested_protein_id))
                .first()
            )
        if link is None:
            link = (
                BioentryStructure.objects.select_related("bioentry__biodatabase")
                .filter(pdb_id=struct_id)
                .first()
            )
        if link is None or link.bioentry is None:
            return None, None
        return AgentChatView._scope_from_protein_id(user, link.bioentry.bioentry_id)

    @staticmethod
    def _scope_from_binder_id(user, binder_id):
        binder = Binders.objects.select_related("locustag").filter(pk=binder_id).first()
        if binder is None or binder.locustag is None:
            return None, None
        return AgentChatView._scope_from_protein_id(user, binder.locustag.bioentry_id)

    @staticmethod
    def _fallback_scope_from_path(user, page_path, requested_protein_id=None):
        protein_match = re.search(r"/protein/(\d+)(?:/|$)", page_path)
        if protein_match:
            return AgentChatView._scope_from_protein_id(user, protein_match.group(1))

        struct_match = re.search(r"/structure/(\d+)(?:/|$)", page_path)
        if struct_match:
            return AgentChatView._scope_from_struct_id(
                user, struct_match.group(1), requested_protein_id
            )

        binder_match = re.search(r"/binder/(\d+)(?:/|$)", page_path)
        if binder_match:
            return AgentChatView._scope_from_binder_id(user, binder_match.group(1))

        genome_match = re.search(r"/genome/([^/]+)(?:/|$)", page_path)
        if genome_match:
            assembly_name = resolve_genome_from_slug(user, genome_match.group(1))
            if assembly_name:
                return assembly_name, None

        return None

    @staticmethod
    def _is_protein_list_path(page_path):
        """True only for the actual proteins-list page -- the page the
        clear_filters/apply_filters reload response should ever point at.
        Reuses the same candidate-path normalization _resolve_page_scope
        trusts, rather than a second, possibly-inconsistent derivation."""
        for candidate in AgentChatView._candidate_paths(page_path):
            try:
                match = resolve(candidate)
            except Resolver404:
                continue
            if match.url_name == "protein_list":
                return True
        return False

    @staticmethod
    def _page_state_prompt(page_state):
        if not page_state:
            return ""
        encoded = json.dumps(page_state, ensure_ascii=False, sort_keys=True)
        encoded = _truncate_text(encoded, limit=1800)
        return (
            "\n\nCurrent browser UI snapshot (sanitized, compact, and user-interface only):\n"
            f"{encoded}\n"
            "Use this snapshot to understand what the user is seeing: active filters, sort, "
            "visible rows, selected pocket/structure, 3D viewer state (spin, view mode), and "
            "current tab. Do not treat this snapshot as biological evidence; for claims about "
            "proteins, scores, ligands, metabolism, or off-targets, call the available tools."
        )


class AgentChatSessionsView(PermissionRequiredMixin, View):
    permission_required = "tpweb.can_use_agent_chat"
    raise_exception = True

    def get(self, request, *args, **kwargs):
        """Lists this browser session's recent conversations for the
        assistant drawer's history picker -- never another session's, since
        list_conversations always filters by this request's own session_key."""
        session_key = _ensure_session_key(request)
        return JsonResponse({"sessions": list_conversations(session_key)})


class AgentChatSessionDetailView(PermissionRequiredMixin, View):
    """Rename/delete a single conversation -- always scoped to the
    requesting browser's own session_key (via rename_conversation/
    delete_conversation), so a conversation_id from another session can
    never be renamed or deleted, only 404."""

    permission_required = "tpweb.can_use_agent_chat"
    raise_exception = True

    def patch(self, request, conversation_id, *args, **kwargs):
        session_key = _ensure_session_key(request)
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        title = str(payload.get("title") or "").strip()
        if not title:
            return JsonResponse({"error": "title is required."}, status=400)

        row = rename_conversation(session_key, conversation_id, title)
        if row is None:
            return JsonResponse({"error": "Conversation not found."}, status=404)
        return JsonResponse({"id": row.pk, "title": row.title})

    def delete(self, request, conversation_id, *args, **kwargs):
        session_key = _ensure_session_key(request)
        if not delete_conversation(session_key, conversation_id):
            return JsonResponse({"error": "Conversation not found."}, status=404)
        return JsonResponse({"deleted": True})
