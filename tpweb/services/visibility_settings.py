"""Owner-controlled public/Gates-shared visibility for ScoreFormula and
ScoreParam ("custom params") -- backs the Settings page
(tpweb/views/SettingsView.py). The owner decides their own items'
visibility at creation or later from this page; a superuser additionally
sees every user's items here to review or override.

Writing a shared ScoreParam's *values* stays owner-only regardless of
visibility -- shared_with_gates only widens who can read/use the column
in formulas and filters, see tpweb.services.score_params.
"""

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME, resolve_workspace_user

VISIBILITY_PRIVATE = "private"
VISIBILITY_GATES = "gates"
VISIBILITY_PUBLIC = "public"

FORMULA_VISIBILITY_CHOICES = [
    (VISIBILITY_PRIVATE, "Private (only me)"),
    (VISIBILITY_GATES, "Shared with Gates roles"),
    (VISIBILITY_PUBLIC, "Public (every signed-in user)"),
]

PARAM_VISIBILITY_CHOICES = [
    (VISIBILITY_PRIVATE, "Private (only me)"),
    (VISIBILITY_GATES, "Shared with Gates roles (read-only for them)"),
]


def formula_visibility(formula):
    if formula.public:
        return VISIBILITY_PUBLIC
    if formula.shared_with_gates:
        return VISIBILITY_GATES
    return VISIBILITY_PRIVATE


def param_visibility(score_param):
    return VISIBILITY_GATES if score_param.shared_with_gates else VISIBILITY_PRIVATE


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


def set_param_visibility(score_param, user, visibility):
    if not _can_manage(user, score_param.user_id):
        return False
    score_param.shared_with_gates = visibility == VISIBILITY_GATES
    score_param.save(update_fields=["shared_with_gates"])
    return True


def formulas_owned_by(user):
    workspace_user = resolve_workspace_user(user)
    return ScoreFormula.objects.filter(user=workspace_user).order_by("name", "id")


def custom_params_owned_by(user):
    workspace_user = resolve_workspace_user(user)
    return ScoreParam.objects.filter(user=workspace_user, category="Custom").order_by("name", "id")


def all_shareable_formulas():
    """Every real (non-anonymous-workspace) user's own formula, for the
    superuser overview table."""
    return (
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
