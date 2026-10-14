"""Owner-controlled public/Gates-shared visibility for ScoreFormula, plus
the owner listings of formulas and uploaded columns -- backs the Settings
page (tpweb/views/SettingsView.py). The owner decides their own items'
visibility at creation or later from this page; a superuser additionally
sees every user's items here to review or override. Uploaded columns are
shared per genome, see tpweb.services.custom_param_sharing.
"""

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.workspace import (
    PUBLIC_WORKSPACE_USERNAME,
    get_public_workspace_user,
    resolve_workspace_user,
)

VISIBILITY_PRIVATE = "private"
VISIBILITY_GATES = "gates"
VISIBILITY_PUBLIC = "public"

# Same wording as uploaded columns (custom_param_sharing.VISIBILITY_LABELS).
FORMULA_VISIBILITY_CHOICES = [
    (VISIBILITY_PRIVATE, "Only me"),
    (VISIBILITY_GATES, "Project members"),
    (VISIBILITY_PUBLIC, "Everyone signed in"),
]


def formula_visibility(formula):
    if formula.public:
        return VISIBILITY_PUBLIC
    if formula.shared_with_gates:
        return VISIBILITY_GATES
    return VISIBILITY_PRIVATE


def _can_manage(user, owner_id):
    return bool(user) and (user.is_superuser or user.pk == owner_id)


def set_formula_visibility(formula, user, visibility):
    """Returns False (no-op) if `user` doesn't own `formula` and isn't a
    superuser -- callers should treat that as a permission error."""
    if not _can_manage(user, formula.user_id):
        return False
    formula.public = visibility == VISIBILITY_PUBLIC
    formula.shared_with_gates = visibility == VISIBILITY_GATES
    formula.save(update_fields=["public", "shared_with_gates"])
    return True


def _builtin_formula_expressions():
    """The base formulas (Druggability, Localization, ...) as the public
    workspace has them. Older accounts got their own seeded copy of each."""
    return {
        formula.name: (formula.expression or "").strip()
        for formula in ScoreFormula.objects.filter(user=get_public_workspace_user())
    }


def _without_builtin_copies(formulas):
    """Drops untouched copies of the base formulas -- every user has one and
    there's nothing of theirs to share in it (they made dozens of rows of
    noise on the Settings page). An edited copy stays."""
    builtin = _builtin_formula_expressions()
    kept = []
    for formula in formulas:
        expression = (formula.expression or "").strip()
        is_copy = formula.name in builtin and expression in ("", builtin[formula.name])
        if not is_copy:
            kept.append(formula)
    return kept


def formulas_owned_by(user):
    workspace_user = resolve_workspace_user(user)
    return _without_builtin_copies(
        ScoreFormula.objects.filter(user=workspace_user).order_by("name", "id")
    )


def custom_params_owned_by(user):
    workspace_user = resolve_workspace_user(user)
    return ScoreParam.objects.filter(user=workspace_user, category="Custom").order_by("name", "id")


def all_shareable_formulas():
    """Every real (non-anonymous-workspace) user's own formula, for the
    superuser overview table."""
    return _without_builtin_copies(
        ScoreFormula.objects.filter(user__isnull=False)
        .exclude(user__username=PUBLIC_WORKSPACE_USERNAME)
        .select_related("user")
        .order_by("user__username", "name", "id")
    )


def all_shareable_custom_params():
    return (
        ScoreParam.objects.filter(user__isnull=False, category="Custom")
        .exclude(user__username=PUBLIC_WORKSPACE_USERNAME)
        .select_related("user")
        .order_by("user__username", "name", "id")
    )
