from django.db.models import Q

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


def build_workspace_genome_name(accession, user):
    cleaned_accession = str(accession or "").strip()
    return f"{workspace_slug_for_user(user)}{WORKSPACE_GENOME_DELIMITER}{cleaned_accession}"


def visible_genome_name_filter(user):
    own_prefix = f"{workspace_slug_for_user(user)}{WORKSPACE_GENOME_DELIMITER}"
    public_prefix = f"{PUBLIC_WORKSPACE_USERNAME}{WORKSPACE_GENOME_DELIMITER}"
    visible = Q(name__startswith=public_prefix) | ~Q(name__contains=WORKSPACE_GENOME_DELIMITER)
    if own_prefix != public_prefix:
        visible |= Q(name__startswith=own_prefix)
    return visible


def user_can_access_genome_name(user, genome_name):
    workspace_slug, _ = split_workspace_genome_name(genome_name)
    if not is_workspace_genome_name(genome_name):
        return True
    workspace_slug = str(workspace_slug or "").strip().lower()
    return workspace_slug in {
        PUBLIC_WORKSPACE_USERNAME,
        workspace_slug_for_user(user),
    }
