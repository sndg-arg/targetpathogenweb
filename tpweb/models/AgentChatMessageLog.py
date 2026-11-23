from django.conf import settings
from django.db import models


class AgentChatMessageLog(models.Model):
    """One row per billed AI-assistant turn (a real LLM call, not the free
    clear_filters shortcut in AgentChatView.post) -- a minimal append-only
    ledger backing the per-role daily quota in
    tpweb.services.agent_chat_quota. Deliberately separate from
    AgentChatSession (tpweb/models/AgentChatSession.py), which is
    session-keyed and stores a single history_json blob per conversation
    with no per-message timestamps, so it can't answer "how many messages
    has this user sent in the last day" on its own."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_chat_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"], name="agentchatmsg_user_created_idx")
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.created_at}"
