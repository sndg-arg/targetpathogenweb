"""Project wording per viewer: people in the Gates project (Gates collaborator
and consumer roles, and admins) see "Gates"; everyone else (Basic accounts,
students, visitors) sees the neutral "project" wording, since "Gates" means
nothing to them."""

import re

GATES_ROLES = frozenset({"gates_collaborator", "gates_consumer"})

# Neutral wording -> Gates wording, longest phrases first.
_REPLACEMENTS = [
    (re.compile(r"\bcollaborative-project genomes\b"), "Gr-ADI genomes"),
    (re.compile(r"\bcollaborative project\b"), "the Gr-ADI project"),
    (re.compile(r"\bProject collaborators\b"), "Gr-ADI collaborators"),
    (re.compile(r"\bproject collaborators\b"), "Gr-ADI collaborators"),
    (re.compile(r"\bProject collaborator\b"), "Gr-ADI collaborator"),
    (re.compile(r"\bProject members\b"), "Gr-ADI members"),
    (re.compile(r"\bproject members\b"), "Gr-ADI members"),
    (re.compile(r"\bProject member\b"), "Gr-ADI member"),
    (re.compile(r"\bthe project\b"), "the Gr-ADI project"),
]


def is_gates_viewer(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(user.is_superuser or getattr(user, "role", "") in GATES_ROLES)


def branded(text, user):
    """`text` with the project named "Gates" when `user` is in it."""
    if not text or not is_gates_viewer(user):
        return text
    result = str(text)
    for pattern, replacement in _REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


def branded_choices(choices, user):
    return [(value, branded(label, user)) for value, label in choices]
