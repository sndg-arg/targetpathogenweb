from django.conf import settings
from django.db import models


class BlockedIP(models.Model):
    """An IP address denied access to the whole site (403), enforced by
    tpweb.middleware.access_control.BlockedIPMiddleware on every request --
    unlike LoginRequiredMiddleware's redirect, this has no exempt paths.

    Managed from the Activity dashboard's "Scanning & bot traffic" table
    (block/unblock actions, see ActivityDashboardView) or directly in the
    Django admin.
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
