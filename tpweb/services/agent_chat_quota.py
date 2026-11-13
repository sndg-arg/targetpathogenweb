"""Per-role daily cap on AI assistant messages -- each turn is a real LLM
call and costs real money, so Basic accounts (self-serve, instant
activation, no admin review) get a modest cap while Gates roles (admin-
assigned) go unlimited. Backed by AgentChatMessageLog, a minimal
append-only ledger (see that model's docstring for why AgentChatSession
itself can't answer "how many messages in the last day").
"""

from datetime import timedelta

from django.utils import timezone

from tpweb.models import TPUser
from tpweb.models.AgentChatMessageLog import AgentChatMessageLog

ROLLING_WINDOW = timedelta(days=1)

# None = unlimited. Flagged as an easy-to-tune starting point, not a fixed
# design constraint -- adjust freely once real usage data exists.
ROLE_DAILY_QUOTAS = {
    TPUser.Role.BASIC: 15,
    TPUser.Role.GATES_CONSUMER: None,
    TPUser.Role.GATES_COLLABORATOR: None,
}


def quota_for(user):
    """The message cap for this user's current role, or None if unlimited
    (always None for a superuser, regardless of role)."""
    if user.is_superuser:
        return None
    return ROLE_DAILY_QUOTAS.get(user.role, ROLE_DAILY_QUOTAS[TPUser.Role.BASIC])


def messages_used(user):
    cutoff = timezone.now() - ROLLING_WINDOW
    return AgentChatMessageLog.objects.filter(user=user, created_at__gte=cutoff).count()


def quota_exceeded(user):
    quota = quota_for(user)
    if quota is None:
        return False
    return messages_used(user) >= quota


def record_message(user):
    AgentChatMessageLog.objects.create(user=user)
