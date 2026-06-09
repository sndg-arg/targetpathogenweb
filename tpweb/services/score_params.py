from django.db.models import Q

from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.services.score_param_types import is_categorical_score_param, is_numeric_score_param
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME, resolve_workspace_user

SYSTEM_SCORE_PARAM_DEFINITIONS = {
    "human_offtarget": {
        "category": "Off-target",
        "description": (
            "BLASTP against the human proteome. Hit means at least one human match "
            "was detected at e-value <= 1e-5. Prefer No hit for pathogen-selective targets."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "no_hit",
        "options": ("hit", "no_hit"),
        "option_descriptions": {
            "hit": "At least one human proteome match was detected; potential host off-target risk.",
            "no_hit": "No human proteome match detected under the pipeline cutoff; favorable for selectivity.",
        },
    },
    "human_identity": {
        "category": "Off-target",
        "description": "Best human BLAST identity percentage.",
        "type": "N",
        "default_operation": "<=",
        "default_value": "0",
    },
    "human_evalue": {
        "category": "Off-target",
        "description": "Best human BLAST E-value.",
        "type": "N",
        "default_operation": "<=",
        "default_value": "1",
    },
    "gut_microbiome_offtarget": {
        "category": "Off-target",
        "description": (
            "DIAMOND/BLASTP against gut microbiome reference genomes. Hit means at "
            "least one microbiome match passing identity > 40% and query coverage > 70%."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "no_hit",
        "options": ("hit", "no_hit"),
        "option_descriptions": {
            "hit": "At least one gut microbiome match passed identity > 40% and query coverage > 70%; microbiome cross-reactivity risk.",
            "no_hit": "No gut microbiome match passed the identity/coverage cutoff; favorable for microbiome sparing.",
        },
    },
    "hit_in_deg": {
        "category": "Essentiality",
        "description": "Protein has a hit in the DEG database.",
        "type": "C",
        "default_operation": "=",
        "default_value": "N",
        "options": ("Y", "N"),
    },
    "deg_identity": {
        "category": "Essentiality",
        "description": "Best DEG BLAST identity percentage.",
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "deg_evalue": {
        "category": "Essentiality",
        "description": "Best DEG BLAST E-value.",
        "type": "N",
        "default_operation": "<=",
        "default_value": "1",
    },
    "colabfold_druggability_score": {
        "category": "Pocket",
        "description": (
            "FPocket druggability score for the best ColabFold predicted structure (0–1). "
            "≥ 0.7 highly druggable · ≥ 0.4 moderately druggable · < 0.4 low druggability. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "colabfold_p2rank_probability": {
        "category": "Pocket",
        "description": (
            "P2RANK ligandability score for the best pocket in the ColabFold model (0–1). "
            "Higher values indicate higher predicted ligandability. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "p2rank_probability": {
        "category": "Pocket",
        "description": (
            "P2RANK ligandability score for the best pocket in the experimental structure (0–1). "
            "Higher values indicate higher predicted ligandability. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "colabfold_plddt": {
        "category": "Pocket",
        "description": (
            "ColabFold model confidence score (pLDDT, 0–100). "
            "Values ≥ 70 indicate reliable local structure; low values mean the predicted "
            "structure — and its pocket predictions — may be unreliable. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "gut_microbiome_offtarget_norm": {
        "category": "Off-target",
        "description": (
            "Gut microbiome off-target signal normalized by the number of analyzed genomes (0–1). "
            "Values near 0 are favorable; higher values indicate broader microbiome cross-reactivity. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": "<=",
        "default_value": "0",
    },
    "gut_microbiome_offtarget_counts": {
        "category": "Off-target",
        "description": (
            "Number of gut microbiome reference genomes with a homolog above the identity/coverage threshold. "
            "Lower counts are favorable for microbiome sparing. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": "<=",
        "default_value": "0",
    },
    "gut_microbiome_genomes_analyzed": {
        "category": "Off-target",
        "description": (
            "Total number of gut microbiome reference genomes screened for off-target homology. "
            "Use together with off-target counts to interpret the normalized score. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "core_roary": {
        "category": "Conservation",
        "description": (
            "Pan-genome core status from Roary. "
            "Core genes are conserved across all (or nearly all) strains in the pan-genome; "
            "accessory genes are present only in a subset of strains. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "Core",
        "options": ("Core", "Accessory"),
        "option_descriptions": {
            "Core": "Gene conserved across all (or nearly all) strains in the pan-genome (value ≥ 0.5).",
            "Accessory": "Gene present only in a subset of strains (value < 0.5).",
        },
    },
    "core_corecruncher": {
        "category": "Conservation",
        "description": (
            "Pan-genome core status from CoreCruncher. "
            "Core genes are conserved across all (or nearly all) strains in the pan-genome; "
            "accessory genes are present only in a subset of strains. "
            "Available only for genomes analyzed with the curated pipeline."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "Core",
        "options": ("Core", "Accessory"),
        "option_descriptions": {
            "Core": "Gene conserved across all (or nearly all) strains in the pan-genome (value ≥ 0.5).",
            "Accessory": "Gene present only in a subset of strains (value < 0.5).",
        },
    },
}


def ensure_system_score_param(name, source_df=None):
    definition = SYSTEM_SCORE_PARAM_DEFINITIONS.get(str(name or "").strip())
    if definition is None:
        return None

    score_param = (
        ScoreParam.objects.filter(name=name, user__isnull=True).order_by("id").first()
    )
    if score_param is None:
        score_param = ScoreParam.objects.create(
            category=definition["category"],
            name=name,
            user=None,
            type=definition["type"],
            description=definition["description"],
            default_operation=definition["default_operation"],
            default_value=definition["default_value"],
        )
    else:
        updated_fields = []
        if score_param.category != definition["category"]:
            score_param.category = definition["category"]
            updated_fields.append("category")
        if score_param.type != definition["type"]:
            score_param.type = definition["type"]
            updated_fields.append("type")
        if score_param.default_operation != definition["default_operation"]:
            score_param.default_operation = definition["default_operation"]
            updated_fields.append("default_operation")
        if score_param.default_value != definition["default_value"]:
            score_param.default_value = definition["default_value"]
            updated_fields.append("default_value")
        if score_param.description != definition["description"]:
            score_param.description = definition["description"]
            updated_fields.append("description")
        if updated_fields:
            score_param.save(update_fields=updated_fields)

    if is_numeric_score_param(score_param):
        return score_param

    option_names = list(definition.get("options", ()))
    if source_df is not None and len(source_df.columns) >= 2 and not option_names:
        imported_values = []
        for raw_value in source_df.iloc[:, 1].dropna().tolist():
            value = str(raw_value).strip()
            if value and value not in imported_values:
                imported_values.append(value)
        if imported_values:
            option_names = imported_values
            if score_param.default_value not in option_names:
                score_param.default_value = option_names[0]
                score_param.save(update_fields=["default_value"])

    for option_name in option_names:
        option, created = ScoreParamOptions.objects.get_or_create(
            score_param=score_param,
            name=option_name,
            defaults={"description": ""},
        )
        option_description = definition.get("option_descriptions", {}).get(option_name)
        if option_description and option.description != option_description:
            option.description = option_description
            option.save(update_fields=["description"])

    return score_param


def ensure_system_score_params_exist():
    for score_param_name in SYSTEM_SCORE_PARAM_DEFINITIONS:
        ensure_system_score_param(score_param_name)


def visible_score_params_queryset(user):
    ensure_system_score_params_exist()
    workspace_user = resolve_workspace_user(user)
    visibility_filter = Q(user__isnull=True) & ~Q(category="Custom")
    visibility_filter |= Q(user=workspace_user)

    if workspace_user.username == PUBLIC_WORKSPACE_USERNAME:
        visibility_filter |= Q(user__isnull=True, category="Custom")

    return ScoreParam.objects.filter(visibility_filter).order_by("category", "name", "id")


def visible_categorical_score_params_queryset(user):
    return [score_param.pk for score_param in visible_score_params_queryset(user) if is_categorical_score_param(score_param)]


def visible_score_param_options_queryset(user, param_id):
    visible_param_ids = visible_categorical_score_params_queryset(user)
    return ScoreParamOptions.objects.filter(
        score_param_id=param_id,
        score_param_id__in=visible_param_ids,
    ).order_by("name", "id")


def resolve_score_param_for_import(column_name, owner=None, source_df=None):
    if owner is None:
        system_param = ensure_system_score_param(column_name, source_df=source_df)
        if system_param is not None:
            return system_param

    global_param = (
        ScoreParam.objects.filter(name=column_name, user__isnull=True)
        .exclude(category="Custom")
        .order_by("id")
        .first()
    )
    if global_param is not None:
        return global_param

    scoped_filters = {
        "category": "Custom",
        "name": column_name,
    }
    if owner is None:
        scoped_filters["user__isnull"] = True
    else:
        scoped_filters["user"] = owner

    score_param = ScoreParam.objects.filter(**scoped_filters).order_by("id").first()
    if score_param is not None or source_df is None:
        return score_param

    ScoreParam.initialize_custom_param(source_df, user=owner)
    return ScoreParam.objects.filter(**scoped_filters).order_by("id").first()
