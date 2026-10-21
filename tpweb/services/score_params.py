from django.db.models import Q

from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.services.score_param_types import is_categorical_score_param, is_numeric_score_param
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME, resolve_workspace_user

# Curated metabolic priority (Gates project, loaded by load_gates_metabolic_score).
# Its scores don't come only from the pan-genome metabolic model, so the copy
# avoids saying so. Hover texts on the protein page and the column
# descriptions all read from here: replace them with the metabolism team's
# paragraph when it arrives.
GATES_METABOLIC_CATEGORY = "Metabolic priority (curated)"
GATES_METABOLIC_HELP = {
    "card": (
        "Curated metabolic analysis by the project's metabolism team: how strongly this "
        "gene and its reactions are supported. Replaces the automatic BioCyc/Pathway Tools "
        "metrics below."
    ),
    "S_gene": "Gene support score (0–1) from the curated metabolic analysis.",
    "reaction_support": (
        "Reaction support score (0–1) from the curated metabolic analysis. Drives the "
        "quadrant and priority classification."
    ),
    "n_reactions": "Number of metabolic reactions this gene participates in.",
    "quadrant": (
        "Gene-support / reaction-support quadrant (high/low gene support × high/low "
        "reaction support), from the curated metabolic analysis."
    ),
    "priority": (
        "Target priority tier from the curated metabolic analysis, derived from the "
        "gene-support / reaction-support quadrant."
    ),
}

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
        "description": (
            "Whether the protein has a homolog in the Database of Essential Genes (DEG). "
            "Y suggests the protein is essential, which favors it as a target."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "N",
        "options": ("Y", "N"),
        "option_descriptions": {
            "Y": "Essential: has a homolog in the Database of Essential Genes.",
            "N": "Not flagged as essential: no homolog in the Database of Essential Genes.",
        },
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
            "Only available for genomes with imported expert-reviewed results."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "colabfold_p2rank_probability": {
        "category": "Pocket",
        "description": (
            "P2Rank binding-site probability for the best pocket in the ColabFold model (0–1). "
            "Higher values mean a more likely ligand-binding site. "
            "Only available for genomes with imported expert-reviewed results."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "p2rank_probability": {
        "category": "Pocket",
        "description": (
            "P2Rank binding-site probability for the selected pocket (0–1). "
            "Higher values mean a more likely ligand-binding site. "
            "Curated selections are preserved. Automatic indexing prefers an experimental "
            "structure with pockets, falling back to predicted models."
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
            "Only available for genomes with imported expert-reviewed results."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "pocket_size_outlier": {
        "category": "Pocket",
        "description": (
            "Whether this protein's best/representative FPocket pocket has an unusually large or "
            "diffuse geometry compared to that structure's other pockets (statistical outlier by "
            "volume). Often reflects a low-confidence or disordered model region that FPocket "
            "scores as druggable without being a real small-molecule cavity — treat a high "
            "druggability score with more caution when this is Y."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "N",
        "options": ("Y", "N"),
        "option_descriptions": {
            "Y": "Best pocket's volume is a statistical outlier among this structure's pockets — verify manually before trusting the druggability score.",
            "N": "Best pocket's volume is within the normal range for this structure's pockets.",
        },
    },
    "pocket_consensus_high_score": {
        "category": "Pocket",
        "description": (
            "Whether this protein has at least one FPocket pocket scored druggable (>= 0.7) "
            "sitting within 8 Å of a P2Rank pocket scored ligandable (>= 0.5) — i.e. two "
            "independent predictors agreeing, with confidence, on the same binding site. "
            "Checked across every pocket on every linked structure, not just the top few "
            "shown on the protein page. A stronger signal than either predictor's score alone."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "Y",
        "options": ("Y", "N"),
        "option_descriptions": {
            "Y": "FPocket and P2Rank both scored a pocket high and agree it's the same site.",
            "N": "No same-site, both-high-score match between FPocket and P2Rank pockets.",
        },
    },
    "gut_microbiome_offtarget_norm": {
        "category": "Off-target",
        "description": (
            "Gut microbiome off-target signal normalized by the number of analyzed genomes (0–1). "
            "Values near 0 are favorable; higher values indicate broader microbiome cross-reactivity. "
            "Only available for genomes with imported expert-reviewed results."
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
            "Only available for genomes with imported expert-reviewed results."
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
            "Only available for genomes with imported expert-reviewed results."
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
            "Only available for genomes with imported expert-reviewed results."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "Core",
        "options": ("Core", "Accessory"),
        "option_descriptions": {
            "Core": "Present in at least 99% of the analyzed strains (Roary's core threshold).",
            "Accessory": "Present in fewer than 99% of the analyzed strains.",
        },
    },
    "core_corecruncher": {
        "category": "Conservation",
        "description": (
            "Pan-genome core status from CoreCruncher. "
            "Core genes are conserved across all (or nearly all) strains in the pan-genome; "
            "accessory genes are present only in a subset of strains. "
            "Only available for genomes with imported expert-reviewed results."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "Core",
        "options": ("Core", "Accessory"),
        "option_descriptions": {
            "Core": "Called core by CoreCruncher: conserved across the analyzed strains.",
            "Accessory": "Not called core by CoreCruncher: present only in some strains.",
        },
    },
    "PTOOLS_betweenness_centrality": {
        "category": "Metabolic network",
        "description": (
            "Betweenness centrality of the metabolic reaction(s) this gene catalyzes, within the "
            "genome-scale metabolic reaction network (BioCyc/Pathway Tools MetaFlux). Higher values "
            "mean the reaction sits on more shortest paths between other reactions — a proxy for how "
            "central/chokepoint-prone it is in the organism's metabolism. "
            "Available only for genomes analyzed with the metabolic network pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "metabolic_chokepoint": {
        "category": "Metabolic network",
        "description": (
            "Whether this gene catalyzes a metabolic chokepoint reaction — the sole reaction "
            "producing or consuming a given metabolite in the network. Chokepoint reactions are "
            "attractive drug targets because inhibiting them can't easily be bypassed. "
            "Available only for genomes analyzed with the metabolic network pipeline."
        ),
        "type": "C",
        "default_operation": "=",
        "default_value": "N",
        "options": ("Y", "N"),
        "option_descriptions": {
            "Y": "Gene catalyzes at least one producing, consuming, or both-sided chokepoint reaction.",
            "N": "Gene does not catalyze any chokepoint reaction.",
        },
    },
    "PTOOLS_edges": {
        "category": "Metabolic network",
        "description": (
            "Degree (edge count) of this gene's reaction(s) in the full genome-scale metabolic "
            "reaction network — how many other reactions it directly shares a metabolite with. "
            "Higher values indicate a more densely connected reaction, independent of betweenness "
            "centrality. Available only for genomes analyzed with the metabolic network pipeline."
        ),
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "S_gene": {
        "category": GATES_METABOLIC_CATEGORY,
        "description": GATES_METABOLIC_HELP["S_gene"],
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "reaction_support": {
        "category": GATES_METABOLIC_CATEGORY,
        "description": GATES_METABOLIC_HELP["reaction_support"],
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "n_reactions": {
        "category": GATES_METABOLIC_CATEGORY,
        "description": GATES_METABOLIC_HELP["n_reactions"],
        "type": "N",
        "default_operation": ">=",
        "default_value": "0",
    },
    "quadrant": {
        "category": GATES_METABOLIC_CATEGORY,
        "description": GATES_METABOLIC_HELP["quadrant"],
        "type": "C",
        "default_operation": "=",
        "default_value": "Low reaction / Low gene",
        "options": (
            "High reaction / High gene",
            "High reaction / Low gene",
            "Low reaction / High gene",
            "Low reaction / Low gene",
        ),
    },
    "priority": {
        "category": GATES_METABOLIC_CATEGORY,
        "description": GATES_METABOLIC_HELP["priority"],
        "type": "C",
        "default_operation": "=",
        "default_value": "Non-priority target",
        "options": ("Priority target", "Second priority targets", "Non-priority target"),
    },
}


def ensure_system_score_param(name, source_df=None):
    definition = SYSTEM_SCORE_PARAM_DEFINITIONS.get(str(name or "").strip())
    if definition is None:
        return None

    score_param = ScoreParam.objects.filter(name=name, user__isnull=True).order_by("id").first()
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


def score_param_visibility_filter(user, genome_name=None):
    """Q() of ScoreParam rows `user` may read: every non-Custom global
    param, their own (any category), and other users' Custom columns shared
    with them (see tpweb.services.custom_param_sharing) -- on `genome_name`
    only, when given. Read-only: writing stays scoped to the owner. A shared
    column named like one of the user's own is left out so names stay
    unique in the table and in formulas."""
    from tpweb.services.custom_param_sharing import shared_with_user_q

    workspace_user = resolve_workspace_user(user)
    visibility_filter = Q(user__isnull=True) & ~Q(category="Custom")
    visibility_filter |= Q(user=workspace_user)

    if workspace_user.username == PUBLIC_WORKSPACE_USERNAME:
        visibility_filter |= Q(user__isnull=True, category="Custom")
    else:
        own_custom_names = ScoreParam.objects.filter(user=workspace_user, category="Custom").values(
            "name"
        )
        visibility_filter |= (
            shared_with_user_q(user, genome_name)
            & ~Q(user=workspace_user)
            & ~Q(name__in=own_custom_names)
        )

    return visibility_filter


def visible_score_params_queryset(user, genome_name=None):
    ensure_system_score_params_exist()
    visibility = score_param_visibility_filter(user, genome_name)
    if genome_name:
        from tpweb.services.shared_sequence_evidence import inherited_score_param_ids

        visibility |= Q(pk__in=inherited_score_param_ids(genome_name, user))
    return ScoreParam.objects.filter(visibility).order_by("category", "name", "id")


def visible_categorical_score_params_queryset(user):
    return [
        score_param.pk
        for score_param in visible_score_params_queryset(user)
        if is_categorical_score_param(score_param)
    ]


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


GENOME_PARAM_NAMES_CACHE_TTL_SECONDS = 900


def genome_score_param_names(assembly_name, user=None):
    """Names of the ScoreParams that have at least one value loaded for this
    genome's proteins. Used to keep the formula builder's variable palette and
    the Scoring drawer's base formulas to what the genome actually has (e.g.
    PAO1 was offered "Kp score" and pan-genome metabolism variables it has no
    data for, which silently score 0). Cached per genome like the overview
    aggregates in assembly_workspace -- data only changes on a pipeline run or
    import."""
    from django.core.cache import cache

    from bioseq.models.Biodatabase import Biodatabase
    from tpweb.models.ScoreParamValue import ScoreParamValue
    from tpweb.models import IdenticalSequenceMember
    from tpweb.services.shared_sequence_evidence import inherited_score_param_ids

    shared = IdenticalSequenceMember.objects.filter(
        bioentry__biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
    ).exists()

    cache_key = f"Target:genome_score_param_names:{assembly_name}"
    cached = cache.get(cache_key)
    if cached is not None and not shared:
        return cached
    names = set(
        ScoreParamValue.objects.filter(
            bioentry__biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX
        )
        .values_list("score_param__name", flat=True)
        .distinct()
    )
    if shared:
        names.update(
            ScoreParam.objects.filter(
                pk__in=inherited_score_param_ids(assembly_name, user),
            ).values_list("name", flat=True)
        )
    else:
        cache.set(cache_key, names, GENOME_PARAM_NAMES_CACHE_TTL_SECONDS)
    return names
