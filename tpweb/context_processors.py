from django.conf import settings


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }


def contact(request):
    """Who to write to for access requests -- used by the restricted-access
    texts across the site (settings.CONTACT_EMAIL)."""
    return {"contact_email": settings.CONTACT_EMAIL}
