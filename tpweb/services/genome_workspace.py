from django.db.models import Q

from bioseq.models.Biodatabase import Biodatabase

from tpweb.models.RestrictedGenome import RestrictedGenome
from tpweb.services.workspace import (
    PUBLIC_WORKSPACE_USERNAME,
    workspace_slug_for_user,
)


WORKSPACE_GENOME_DELIMITER = "__"


def is_workspace_genome_name(genome_name):
    text = str(genome_name or "").strip()
    if WORKSPACE_GENOME_DELIMITER not in text:
        return False
    prefix, suffix = text.split(WORKSPACE_GENOME_DELIMITER, 1)
    if not suffix:
        return False
    prefix_normalized = prefix.lower()
    return prefix_normalized == PUBLIC_WORKSPACE_USERNAME or prefix_normalized.startswith("user-")


def split_workspace_genome_name(genome_name):
    text = str(genome_name or "").strip()
    if not is_workspace_genome_name(text):
        return PUBLIC_WORKSPACE_USERNAME, text
    prefix, suffix = text.split(WORKSPACE_GENOME_DELIMITER, 1)
    return prefix.lower(), suffix


def display_genome_name(genome_name):
    return split_workspace_genome_name(genome_name)[1]


def describe_genome_scope(user, genome_name):
    workspace_slug, _ = split_workspace_genome_name(genome_name)
    current_workspace_slug = workspace_slug_for_user(user)

    if workspace_slug == current_workspace_slug and workspace_slug != PUBLIC_WORKSPACE_USERNAME:
        return {
            "key": "personal",
            "label": "Private",
        }

    return {
        "key": "public",
        "label": "Public",
    }


def build_workspace_genome_name(accession, user):
    cleaned_accession = str(accession or "").strip()
    return f"{workspace_slug_for_user(user)}{WORKSPACE_GENOME_DELIMITER}{cleaned_accession}"


def user_can_view_restricted_genomes(user):
    """Whether `user` is allowed to see genomes flagged in RestrictedGenome
    (tpweb.can_view_restricted_genomes -- granted by default on approval,
    see tpweb.services.user_approval, and individually revoked per user
    from the /users "Edit" modal for tester/student accounts). A superuser
    passes has_perm() automatically."""
    return bool(user) and user.has_perm("tpweb.can_view_restricted_genomes")


def visible_genome_name_filter(user):
    own_prefix = f"{workspace_slug_for_user(user)}{WORKSPACE_GENOME_DELIMITER}"
    public_prefix = f"{PUBLIC_WORKSPACE_USERNAME}{WORKSPACE_GENOME_DELIMITER}"
    visible = Q(name__startswith=public_prefix) | ~Q(name__contains=WORKSPACE_GENOME_DELIMITER)
    if own_prefix != public_prefix:
        visible |= Q(name__startswith=own_prefix)
    if not user_can_view_restricted_genomes(user):
        visible &= ~Q(name__in=RestrictedGenome.objects.values("genome_name"))
    return visible


def user_can_access_genome_name(user, genome_name):
    if (
        not user_can_view_restricted_genomes(user)
        and RestrictedGenome.objects.filter(genome_name=genome_name).exists()
    ):
        return False
    workspace_slug, _ = split_workspace_genome_name(genome_name)
    if not is_workspace_genome_name(genome_name):
        return True
    workspace_slug = str(workspace_slug or "").strip().lower()
    return workspace_slug in {
        PUBLIC_WORKSPACE_USERNAME,
        workspace_slug_for_user(user),
    }


def genome_url_slug(internal_name):
    """Return the clean accession for use in URLs."""
    return display_genome_name(internal_name)


def resolve_genome_from_slug(user, slug):
    """Resolve a URL slug (accession) to the full internal genome name.

    Checks the user's own workspace first, then public, then bare names.
    Returns None if no accessible genome is found.
    """
    cleaned = str(slug or "").strip()
    if not cleaned:
        return None
    if is_workspace_genome_name(cleaned):
        if user_can_access_genome_name(user, cleaned):
            return cleaned
        return None
    user_workspace = workspace_slug_for_user(user)
    candidates = [
        f"{user_workspace}{WORKSPACE_GENOME_DELIMITER}{cleaned}",
        f"{PUBLIC_WORKSPACE_USERNAME}{WORKSPACE_GENOME_DELIMITER}{cleaned}",
        cleaned,
    ]
    for name in candidates:
        if Biodatabase.objects.filter(name=name).exists() and user_can_access_genome_name(
            user, name
        ):
            return name
    return None


def user_can_delete_genome_name(user, genome_name):
    if not is_workspace_genome_name(genome_name):
        return False
    workspace_slug, _ = split_workspace_genome_name(genome_name)
    workspace_slug = str(workspace_slug or "").strip().lower()
    return workspace_slug not in {
        "",
        PUBLIC_WORKSPACE_USERNAME,
    } and workspace_slug == workspace_slug_for_user(user)
