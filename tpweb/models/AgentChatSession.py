from django.db import models


class AgentChatSession(models.Model):
    """Server-side persistence for the assistant drawer's conversation history.

    Keyed by Django session key rather than by user: Target is mostly used
    without login (shared 'public' workspace account, see
    tpweb/services/workspace.py's get_public_workspace_user), so the browser
    session is the only thing that actually distinguishes one visitor's
    conversation from another's on a shared/anonymous account.
    """

    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    history_json = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"AgentChatSession({self.session_key})"
