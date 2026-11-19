from django.db import models
from django.db.models import SmallIntegerField, CharField


class TPPost(models.Model):
    name = CharField(max_length=255, unique=True)
    section = CharField(max_length=255)
    order = SmallIntegerField(default=0)
    # HTML, edited as plain text in the admin (CKEditor 4 was removed: EOL, flagged by the UBA scan).
    content = models.TextField(blank=False)

    class Meta:
        unique_together = (
            "section",
            "order",
        )
