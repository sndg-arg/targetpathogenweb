from django.conf import settings
from django.db import models


class BlockedIP(models.Model):
    """An IP address denied access to the whole site (403), enforced by
    tpweb.middleware.access_control.BlockedIPMiddleware on every request --
    unlike LoginRequiredMiddleware's redirect, this has no exempt paths.

    Rows are created automatically (BlockedIPMiddleware auto-blocks a
    recognized bot on first sight, blocked_by=None, reason="auto: <label>")
    or manually via the Django admin. The Activity dashboard's "Blocked IPs"
    panel is read-only -- unblocking happens in the admin, which routes the
    delete through tpweb.services.ip_blocking.unblock_ip() to keep the
    middleware's cache in sync.
    """

    ip = models.GenericIPAddressField(unique=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blocked_ips",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.ip
