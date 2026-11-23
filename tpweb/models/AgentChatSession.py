from django.db import models


class AgentChatSession(models.Model):
    """Server-side persistence for one conversation in the assistant drawer.

    Keyed by Django session key rather than by user: Target is mostly used
    without login (shared 'public' workspace account, see
    tpweb/services/workspace.py's get_public_workspace_user), so the browser
    session is the only thing that actually distinguishes one visitor's
    conversations from another's on a shared/anonymous account.

    Multiple rows can share a session_key -- one browser session can hold
    several conversations (split by inactivity or an explicit "new
    conversation" action, see tpweb/services/agent_chat_sessions.py), so
    session_key is intentionally not unique.
    """

    session_key = models.CharField(max_length=40, db_index=True)
    title = models.CharField(max_length=140, blank=True, default="")
    history_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["session_key", "-updated_at"])]

    def __str__(self):
        return f"AgentChatSession({self.session_key}, {self.pk})"
