from urllib.parse import urlparse

from django.conf import settings
from django.db import migrations


def set_site_domain(apps, schema_editor):
    # django.contrib.sites creates its one Site row with domain="example.com"
    # on first migrate and nothing in this repo ever updated it -- harmless
    # until now, since allauth's password-reset email text ("...requested a
    # password reset for your user account at {{ current_site.domain }}")
    # reads straight from that row. SITE_URL is already this deployment's
    # source of truth for the real hostname (see settings.py, used the same
    # way by tpweb/services/user_approval.py), so reuse it here instead of
    # hardcoding a second copy of the domain.
    Site = apps.get_model("sites", "Site")
    domain = urlparse(settings.SITE_URL).netloc or settings.SITE_URL
    Site.objects.update_or_create(
        pk=settings.SITE_ID,
        defaults={"domain": domain, "name": "Target Pathogen"},
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0087_tpuser_drop_student_role"),
        ("sites", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(set_site_domain, noop_reverse),
    ]
