from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from django.db.models import SmallIntegerField, CharField


class TPPost(models.Model):
    name = CharField(max_length=255,unique=True)
    section = CharField(max_length=255)
    order = SmallIntegerField(default=0)
    content = RichTextUploadingField(blank=False)

    class Meta:
        unique_together = ('section', 'order',)
