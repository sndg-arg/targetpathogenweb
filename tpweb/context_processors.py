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


def project_branding(request):
    """gates_viewer: Gates roles and admins see the project named "Gates";
    everyone else sees neutral "project" wording (tpweb.services.project_branding)."""
    from tpweb.services.project_branding import is_gates_viewer

    return {"gates_viewer": is_gates_viewer(getattr(request, "user", None))}
