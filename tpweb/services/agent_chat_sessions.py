"""Business rules for the assistant drawer's multi-conversation chat history.

A browser session (Django session_key) can hold several conversations over
time. Two different, deliberately independent time windows govern them:

- SESSION_IDLE_GAP: how long a conversation stays "live" -- a new message
  keeps appending to the most recent conversation if it was last touched
  within this window, otherwise a fresh conversation starts automatically.
  This is what makes "session" mean something close to one sitting.
- HISTORY_RETENTION: how long a conversation is kept at all before
  clear_old_agent_chats physically deletes it. Much longer than the idle
  gap on purpose -- a conversation from yesterday should still be reachable
  from the history picker even though a new message today starts a new one.

Explicitly reopening a specific old conversation (the user picked it from
the picker) always appends to that same row regardless of how stale it is --
a deliberate reopen should never silently fork into a third thread.
"""

from datetime import timedelta

from django.utils import timezone

from tpweb.models.AgentChatSession import AgentChatSession

HISTORY_RETENTION = timedelta(days=7)
SESSION_IDLE_GAP = timedelta(minutes=45)
CONVERSATION_LIST_LIMIT = 50
TITLE_MAX_LENGTH = 60


def resolve_active_conversation(session_key, conversation_id=None, force_new=False):
    """Return the AgentChatSession row a new turn should be appended to.

    An explicit conversation_id always wins (reopening a thread on purpose
    should never fork it). Otherwise, force_new or an idle-expired most
    recent conversation starts a brand new row.
    """
    if conversation_id:
        row = AgentChatSession.objects.filter(session_key=session_key, pk=conversation_id).first()
        if row is not None:
            return row
    if not force_new:
        recent = _recent_conversation(session_key)
        if recent is not None:
            return recent
    return AgentChatSession.objects.create(session_key=session_key, history_json=[])


def find_conversation(session_key, conversation_id):
    """Explicit lookup for GET ?conversation_id=... -- None if it doesn't
    exist or doesn't belong to this browser session."""
    if not conversation_id:
        return None
    return AgentChatSession.objects.filter(session_key=session_key, pk=conversation_id).first()


def default_conversation(session_key):
    """The conversation a bare GET (no conversation_id) should hydrate.

    Mirrors resolve_active_conversation's idle-gap rule but never creates a
    row -- a page load shouldn't mint an empty conversation by itself.
    """
    return _recent_conversation(session_key)


def list_conversations(session_key, limit=CONVERSATION_LIST_LIMIT):
    cutoff = timezone.now() - HISTORY_RETENTION
    rows = AgentChatSession.objects.filter(
        session_key=session_key, updated_at__gte=cutoff
    ).order_by("-updated_at")[:limit]
    return [
        {
            "id": row.pk,
            "title": row.title or None,
            "started_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "message_count": len(row.history_json or []),
        }
        for row in rows
    ]


def set_title_if_blank(row, message_text):
    """Auto-titles a conversation from its first message, once.

    Saves immediately (its own write, scoped to just the title field) rather
    than leaving the caller to persist it later alongside history_json --
    keeping this decoupled from _save_persisted_history's own save is what
    makes a concurrent rename_conversation() call safe: neither write can
    clobber the other's field.
    """
    if row.title:
        return
    text = _normalize_title(message_text)
    if not text:
        return
    row.title = text
    row.save(update_fields=["title"])


def rename_conversation(session_key, conversation_id, title):
    """Renames a conversation. None if it doesn't exist or isn't this
    session's -- the caller (the view) is responsible for rejecting a blank
    title before calling this, so a None return here means "not found/not
    owned," with a single unambiguous meaning."""
    row = find_conversation(session_key, conversation_id)
    if row is None:
        return None
    text = _normalize_title(title)
    if not text:
        return None
    row.title = text
    row.save(update_fields=["title"])
    return row


def delete_conversation(session_key, conversation_id):
    """True if a conversation was deleted, False if it didn't exist or
    wasn't this session's. QuerySet.delete() returns a 2-tuple (truthy
    regardless of count), so this checks the actual deleted count rather
    than the tuple itself."""
    deleted_count, _ = AgentChatSession.objects.filter(
        session_key=session_key, pk=conversation_id
    ).delete()
    return deleted_count > 0


def _normalize_title(text):
    text = " ".join((text or "").split())
    if not text:
        return ""
    if len(text) > TITLE_MAX_LENGTH:
        text = text[:TITLE_MAX_LENGTH].rstrip() + "…"
    return text


def _recent_conversation(session_key):
    cutoff = timezone.now() - SESSION_IDLE_GAP
    return (
        AgentChatSession.objects.filter(session_key=session_key, updated_at__gte=cutoff)
        .order_by("-updated_at")
        .first()
    )
