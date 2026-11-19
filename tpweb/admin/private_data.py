"""Researchers' own formulas and uploaded columns never show up in the
Django admin, not even for a superuser -- an item set to "Only me" belongs
to its owner alone (see the Settings page). Each admin below lists only
platform data: rows with no owner or owned by the public workspace."""

from django.db.models import Q

from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME


def researcher_owned(prefix=""):
    """Q() matching rows owned by a real researcher; `prefix` is the path
    to the owning model, e.g. "score_param__"."""
    return Q(**{f"{prefix}user__isnull": False}) & ~Q(
        **{f"{prefix}user__username": PUBLIC_WORKSPACE_USERNAME}
    )


class HideResearcherDataMixin:
    owner_path = ""

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(researcher_owned(self.owner_path))
