from django.conf import settings
from django.db import models
from django.utils.text import slugify
from tpweb.storage.storage import OverwriteStorage


def save_location(instance, filename):
    owner = getattr(instance, "owner", None)
    username = getattr(owner, "username", "") or "public"
    workspace_segment = slugify(username) or "public"
    accession = (instance.accession or "unknown").strip() or "unknown"
    return f"custom_params/{workspace_segment}/{accession}/{filename}"


class CustomParam(models.Model):
    accession = models.CharField(max_length=64)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="custom_params",
        on_delete=models.CASCADE,
    )
    tsv = models.FileField(upload_to=save_location, storage=OverwriteStorage())
