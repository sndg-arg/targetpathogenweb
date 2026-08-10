"""HTTP endpoint for the in-app AI assistant drawer.

Conversation history is persisted server-side, keyed by Django session key
(see AgentChatSession / _load_persisted_history / _save_persisted_history
below), with a 7-day rolling TTL -- one conversation per browser session,
not per authenticated user, since Target is mostly used without login
(shared 'public' workspace account). This means two people sharing that
account from different browsers never see each other's messages, but
reloading the drawer's own page restores the same conversation.

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
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.http import JsonResponse
from django.urls import resolve
from django.urls.exceptions import Resolver404
from django.utils import timezone
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.AgentChatSession import AgentChatSession
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

HISTORY_TTL = timedelta(days=7)


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
    if isinstance(value, (int, float)):
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


def _load_persisted_history(session_key):
    if not session_key:
        return []
    cutoff = timezone.now() - HISTORY_TTL
    row = AgentChatSession.objects.filter(session_key=session_key, updated_at__gte=cutoff).first()
    if not row:
        return []
    try:
        return [_message_from_json(item) for item in row.history_json or []]
    except (TypeError, ValueError):
        # Malformed/legacy row -- start fresh rather than 500ing the drawer.
        return []


def _save_persisted_history(session_key, messages):
    if not session_key:
        return
    AgentChatSession.objects.update_or_create(
        session_key=session_key,
        defaults={"history_json": [_message_to_json(item) for item in messages]},
    )


class AgentChatView(View):
    def get(self, request, *args, **kwargs):
        """Hydrates the drawer with this session's saved conversation on page
        load -- without this, 'persisted' history would never be visible
        again after a reload, defeating the point of persisting it."""
        session_key = _ensure_session_key(request)
        history = _load_persisted_history(session_key)
        return JsonResponse({"history": [_message_to_json(item) for item in history]})

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
        history = _load_persisted_history(session_key)

        workspace_user = resolve_workspace_user(request.user)
        session_user = request.user
        assembly_name, default_accession = self._resolve_page_scope(
            request.user, str(payload.get("page_path") or "")
        )
        if assembly_name and _looks_like_clear_filters(message):
            set_workspace_session_value(request.session, session_user, "selected_parameters", [])
            reply = (
                "Listo, borre todos los filtros de la lista de proteinas para esta sesion. "
                "Recargo la lista para que lo veas aplicado."
            )
            history = _compact_history(
                [
                    *history,
                    Message(role="user", text=message),
                    Message(role="assistant", text=reply),
                ]
            )
            _save_persisted_history(session_key, history)
            return JsonResponse(
                {
                    "reply": reply,
                    "history": [_message_to_json(item) for item in history],
                    "reload": True,
                    "redirect_url": self._reload_url_without_query(
                        str(payload.get("page_url") or payload.get("page_path") or "")
                    ),
                }
            )

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
        _save_persisted_history(session_key, persisted_history)
        response = {
            "reply": reply,
            "history": [_message_to_json(item) for item in persisted_history],
        }
        if _tool_was_called(agent.last_messages, "clear_filters") or _tool_was_called(
            agent.last_messages, "apply_filters"
        ):
            response["reload"] = True
            response["redirect_url"] = self._reload_url_without_query(
                str(payload.get("page_url") or payload.get("page_path") or "")
            )
        return JsonResponse(response)

    @staticmethod
    def _resolve_page_scope(user, page_path):
        """Return (assembly_name, default_accession) for the given
        window.location.pathname, or (None, None) if it doesn't resolve to
        an accessible genome/protein page."""
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

            genome_slug = match.kwargs.get("genome")
            if genome_slug:
                assembly_name = resolve_genome_from_slug(user, genome_slug)
                if assembly_name:
                    return assembly_name, None

        fallback = AgentChatView._fallback_scope_from_path(user, candidate_paths[0])
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

        for marker in ("/protein/", "/genome/"):
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
    def _fallback_scope_from_path(user, page_path):
        protein_match = re.search(r"/protein/(\d+)(?:/|$)", page_path)
        if protein_match:
            return AgentChatView._scope_from_protein_id(user, protein_match.group(1))

        genome_match = re.search(r"/genome/([^/]+)(?:/|$)", page_path)
        if genome_match:
            assembly_name = resolve_genome_from_slug(user, genome_match.group(1))
            if assembly_name:
                return assembly_name, None

        return None

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
