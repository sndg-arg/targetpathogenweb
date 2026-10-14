"""Per-genome sharing of uploaded ("Add my own data") columns.

The owner picks, per column and genome, who else sees it: only them (no
CustomParamShare row), project members, or everyone who can see the genome.
On a restricted genome only project members can see the genome at all, so
the last two are the same thing there and the upload form offers one option.

Other users get a shared column in Columns, Filters and Make my own score as
an extra, unselected option -- nothing is added to their table on its own.
Deleting the column removes it for everyone.
"""

from django.core.cache import cache
from django.db.models import Q

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.CustomParamShare import CustomParamShare
from tpweb.models.RestrictedGenome import RestrictedGenome
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.genome_workspace import display_genome_name, user_can_view_restricted_genomes

VISIBILITY_PRIVATE = "private"
VISIBILITY_PROJECT = CustomParamShare.VISIBILITY_PROJECT
VISIBILITY_PUBLIC = CustomParamShare.VISIBILITY_PUBLIC

VISIBILITY_LABELS = {
    VISIBILITY_PRIVATE: "Only me",
    VISIBILITY_PROJECT: "Project members",
    VISIBILITY_PUBLIC: "Everyone who can see this genome",
}
RESTRICTED_GENOME_SHARED_LABEL = "Project members (restricted genome)"

SHARED_COLUMNS_CATEGORY = "Shared by users"


def is_genome_restricted(genome_name):
    return RestrictedGenome.objects.filter(genome_name=genome_name).exists()


def visibility_choices(genome_name):
    if is_genome_restricted(genome_name):
        return [
            (VISIBILITY_PRIVATE, VISIBILITY_LABELS[VISIBILITY_PRIVATE]),
            (VISIBILITY_PUBLIC, RESTRICTED_GENOME_SHARED_LABEL),
        ]
    return list(VISIBILITY_LABELS.items())


def shared_with_user_q(user, genome_name=None):
    """Q() over ScoreParam for Custom columns other people shared in a way
    `user` may see -- on `genome_name` only, when given. The caller excludes
    the user's own columns."""
    shares = CustomParamShare.objects.all()
    if genome_name:
        shares = shares.filter(genome_name=genome_name)
    if not user_can_view_restricted_genomes(user):
        shares = shares.filter(visibility=VISIBILITY_PUBLIC).exclude(
            genome_name__in=RestrictedGenome.objects.values("genome_name")
        )
    return Q(category="Custom", pk__in=shares.values("score_param_id"))


def _invalidate_genome_param_names(genome_name):
    cache.delete(f"Target:genome_score_param_names:{genome_name}")


def set_column_visibility(score_param, genome_name, visibility):
    if visibility in (VISIBILITY_PROJECT, VISIBILITY_PUBLIC):
        CustomParamShare.objects.update_or_create(
            score_param=score_param, genome_name=genome_name, defaults={"visibility": visibility}
        )
    else:
        CustomParamShare.objects.filter(score_param=score_param, genome_name=genome_name).delete()


def column_visibility(score_param, genome_name):
    share = CustomParamShare.objects.filter(
        score_param=score_param, genome_name=genome_name
    ).first()
    return share.visibility if share else VISIBILITY_PRIVATE


def name_conflicts(owner, genome_name, column_names):
    """Column names someone else already shares on this genome. Two shared
    columns with the same name would be indistinguishable in the table and in
    formulas, so a shared upload must use a different name."""
    return sorted(
        set(
            ScoreParam.objects.filter(
                category="Custom",
                name__in=list(column_names),
                genome_shares__genome_name=genome_name,
            )
            .exclude(user=owner)
            .values_list("name", flat=True)
        )
    )


def uploaded_column_names(uploaded_file):
    """Header columns after `gene`, read without consuming the upload."""
    is_csv = str(getattr(uploaded_file, "name", "")).lower().endswith(".csv")
    separator = "," if is_csv else "\t"
    uploaded_file.seek(0)
    first_line = uploaded_file.readline()
    uploaded_file.seek(0)
    if isinstance(first_line, bytes):
        first_line = first_line.decode("utf-8-sig", errors="replace")
    header = [column.strip() for column in first_line.strip().split(separator)]
    return [column for column in header[1:] if column]


def apply_upload_sharing(owner, genome_name, column_names, visibility, description=""):
    params = ScoreParam.objects.filter(user=owner, category="Custom", name__in=list(column_names))
    for score_param in params:
        if description:
            score_param.description = description
            score_param.save(update_fields=["description"])
        set_column_visibility(score_param, genome_name, visibility)
    _invalidate_genome_param_names(genome_name)


def _genome_names_by_param(param_ids):
    rows = (
        ScoreParamValue.objects.filter(score_param_id__in=param_ids)
        .values_list("score_param_id", "bioentry__biodatabase__name")
        .distinct()
    )
    genomes = {}
    for param_id, proteome_name in rows:
        genomes.setdefault(param_id, set()).add(
            proteome_name.removesuffix(Biodatabase.PROT_POSTFIX)
        )
    return genomes


def column_rows(params):
    """One row per (column, genome it has values in) for the Settings page."""
    params = list(params)
    genomes = _genome_names_by_param([p.pk for p in params])
    shares = {
        (share.score_param_id, share.genome_name): share.visibility
        for share in CustomParamShare.objects.filter(score_param__in=params)
    }
    restricted = set(RestrictedGenome.objects.values_list("genome_name", flat=True))
    rows = []
    for param in params:
        for genome_name in sorted(genomes.get(param.pk, ())):
            is_restricted = genome_name in restricted
            visibility = shares.get((param.pk, genome_name), VISIBILITY_PRIVATE)
            if is_restricted and visibility == VISIBILITY_PROJECT:
                visibility = VISIBILITY_PUBLIC
            rows.append(
                {
                    "obj": param,
                    "genome_name": genome_name,
                    "genome_label": display_genome_name(genome_name),
                    "visibility": visibility,
                    "choices": (
                        [
                            (VISIBILITY_PRIVATE, VISIBILITY_LABELS[VISIBILITY_PRIVATE]),
                            (VISIBILITY_PUBLIC, RESTRICTED_GENOME_SHARED_LABEL),
                        ]
                        if is_restricted
                        else list(VISIBILITY_LABELS.items())
                    ),
                }
            )
    return rows


def _can_manage(user, score_param):
    return bool(user) and (user.is_superuser or user.pk == score_param.user_id)


def update_column_visibility(score_param, genome_name, user, visibility):
    if score_param.category != "Custom" or not _can_manage(user, score_param):
        return False
    if visibility not in VISIBILITY_LABELS:
        return False
    set_column_visibility(score_param, genome_name, visibility)
    _invalidate_genome_param_names(genome_name)
    return True


def delete_column(score_param, genome_name, user):
    """Removes the column's values on this genome (and its share). The column
    itself goes once no genome has values left -- other users stop seeing it
    right away either way."""
    if score_param.category != "Custom" or not _can_manage(user, score_param):
        return False
    ScoreParamValue.objects.filter(
        score_param=score_param,
        bioentry__biodatabase__name=genome_name + Biodatabase.PROT_POSTFIX,
    ).delete()
    CustomParamShare.objects.filter(score_param=score_param, genome_name=genome_name).delete()
    if not ScoreParamValue.objects.filter(score_param=score_param).exists():
        score_param.delete()
    _invalidate_genome_param_names(genome_name)
    return True


def owner_label(user):
    if user is None:
        return ""
    # TPUser drops first_name/last_name (get_full_name() gives "None None").
    return (getattr(user, "name", "") or "").strip() or user.get_username()


def label_shared_columns(score_params, workspace_user):
    """In-memory only: files other users' columns under their own group in
    Columns/Filters and says whose they are. Never saved."""
    for score_param in score_params:
        if (
            score_param.category == "Custom"
            and score_param.user_id
            and score_param.user_id != workspace_user.pk
        ):
            score_param.category = SHARED_COLUMNS_CATEGORY
            author = f"Shared by {owner_label(score_param.user)}."
            description = (score_param.description or "").strip()
            score_param.description = f"{author} {description}".strip()
    return score_params
