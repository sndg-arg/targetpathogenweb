from django.conf import settings
from django.db import models


class RequestLog(models.Model):
    """One row per request -- who accessed what, from where, and when.

    Written by tpweb.middleware.observability.RequestTimingMiddleware, which
    already resolves the client IP behind Traefik's X-Forwarded-For. Health
    checks and static assets are skipped there to avoid drowning real
    activity in noise.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()
    user_agent = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"], name="requestlog_user_created_idx")]

    def __str__(self):
        return f"{self.method} {self.path} ({self.user or 'anonymous'})"
