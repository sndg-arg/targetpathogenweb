"""Builds the "Target profile" / executive-summary evidence shown on the
protein detail page (target profile chips, selected pocket evidence,
conservation, microbiome context, metabolic context, and the combined
verdict/strengths/risks/missing summary).

Extracted verbatim from tpweb/views/ProteinView.py so it can be reused by
the LLM agent's explain_target tool without importing private view
internals from a service module (CLAUDE.md: views delegate to services,
not the other way around).
"""
from django.core.cache import cache
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.Metabolism import GeneReactionLink, MetabolicImportRun, ReactionParticipant
from tpweb.services.assembly_workspace import OVERVIEW_CACHE_TTL_SECONDS
from tpweb.services.binder_summary import create_binders_dict
from tpweb.services.metabolism_summary import build_target_metabolic_sentence
from tpweb.services.genome_workspace import genome_url_slug
from tpweb.services.structure_sources import (
    STRUCTURE_SOURCE_EXPERIMENTAL,
    STRUCTURE_SOURCE_MIXED,
    classify_structure_experiment,
    structure_matches_identifier,
    structure_source_label,
    summarize_structure_sources,
)

_SCORE_META = [
    # (score_name, display_label, category, good_values, bad_values, tooltip)
    ("human_offtarget",          "Human off-target",          "off_target",   ["no_hit"], ["hit"],
     "Sequence similarity to human proteins (BLAST). 'No hit' is preferred — it means no significant human homolog was found."),
    ("human_identity",           "Human identity (%)",        "off_target",   [],         [],
     "% amino acid identity to the top human BLAST hit. Lower values indicate less similarity to human proteins."),
    ("human_evalue",             "Human E-value",             "off_target",   [],         [],
     "BLAST E-value for the top human proteome hit. Values below 1e-5 are considered significant. '> 1e-5' means no significant hit was found."),
    ("gut_microbiome_offtarget", "Gut microbiome off-target", "off_target",   ["no_hit"], ["hit"],
     "Sequence similarity to gut microbiome reference genomes. 'No hit' preferred to minimise risk of disrupting commensal bacteria."),
    ("hit_in_deg",               "Essential (DEG)",           "essentiality", ["Y"],      ["N"],
     "Predicted essential gene based on the Database of Essential Genes (DEG). 'Y' = essential in at least one related organism."),
    ("deg_identity",             "DEG identity (%)",          "essentiality", [],         [],
     "% amino acid identity to the top DEG essential-gene hit. Higher values strengthen the essentiality prediction."),
    ("deg_evalue",               "DEG E-value",               "essentiality", [],         [],
     "BLAST E-value for the top DEG hit. Values below 1e-5 are considered significant. '> 1e-5' means no essential-gene match was found."),
    ("Localization",             "Localization",              "localization", [],         [],
     "Predicted subcellular localization by PSORTb. Extracellular and outer-membrane proteins are preferred as drug targets."),
    ("colabfold_plddt",          "ColabFold pLDDT",           "structure",    [],         [],
     "Per-residue model confidence from ColabFold (0–100). Values >70 indicate reliable regions; >90 indicates high confidence."),
]

_NO_HIT_EVALUE_OVERRIDES = {
    "human_evalue": ("human_offtarget", "no_hit", "> 1e-5"),
    "deg_evalue":   ("hit_in_deg",      "n",      "> 1e-5"),
}


def druggability_label(value):
    """Return (label, tone) for a numeric FPocket druggability score.

    Moved from ProteinView.py so build_protein_executive_context can compute
    it from the single ScoreParamValue query it already runs, instead of the
    view running a second, separate query just for this one score."""
    if value is None:
        return None
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    label = f"{v:.3f}".rstrip("0").rstrip(".")
    if v >= 0.7:
        return (label, "high")
    elif v >= 0.4:
        return (label, "mid")
    elif v > 0:
        return (label, "low")
    return None


def p2rank_label(value):
    """Return (label, tone) for a P2Rank binding-site probability score.

    Same shape as druggability_label but P2Rank's own thresholds (high >= 0.5,
    medium 0.2-0.49 -- see the "Probability: high >= 0.5..." hint in
    pocket_cards.html and p2rank_probability_color in StructureView.py),
    since P2Rank's probability scale isn't calibrated the same as FPocket's
    druggability score."""
    if value is None:
        return None
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    label = f"{v:.3f}".rstrip("0").rstrip(".")
    if v >= 0.5:
        return (label, "high")
    elif v >= 0.2:
        return (label, "mid")
    elif v > 0:
        return (label, "low")
    return None


def build_target_profile(raw_scores, microbiome_context=None):
    items = []
    for name, label, category, good_vals, bad_vals, tooltip in _SCORE_META:
        val = raw_scores.get(name)
        if not val:
            continue
        if name == "human_identity":
            human_screen = str(raw_scores.get("human_offtarget") or "").strip().lower()
            try:
                identity_is_placeholder = float(str(val).replace(",", ".")) == 0
            except (TypeError, ValueError):
                identity_is_placeholder = False
            if human_screen == "no_hit" and identity_is_placeholder:
                continue
        if val in good_vals:
            tone = "good"
        elif val in bad_vals:
            tone = "bad"
        else:
            tone = "neutral"
        display = val.replace("_", " ").replace("no hit", "No hit").replace("no_hit", "No hit")
        display_kind = ""
        percentage = None
        if name == "gut_microbiome_offtarget" and microbiome_context:
            percentage = microbiome_context.get("percentage")
            if percentage is not None:
                label = "Gut microbiome similarity"
                display = f"{percentage}% of screened genomes"
                display_kind = "prevalence"
                tooltip = (
                    "Fraction of screened gut microbiome reference genomes with a significant "
                    "sequence-similarity hit. Lower prevalence suggests narrower microbiome overlap."
                )
        if name in _NO_HIT_EVALUE_OVERRIDES:
            check_name, no_hit_val, _ = _NO_HIT_EVALUE_OVERRIDES[name]
            if str(raw_scores.get(check_name) or "").strip().lower() == no_hit_val:
                continue
        items.append({
            "label": label,
            "value": display,
            "tone": tone,
            "category": category,
            "tooltip": tooltip,
            "display_kind": display_kind,
            "percentage": percentage,
        })
    return items


_SCORE_META_CATEGORY_BY_NAME = {name: category for name, _label, category, _good, _bad, _tooltip in _SCORE_META}


def build_score_breakdown(protein, score_param_values, user):
    """Composite score for this protein under the user's default formula,
    with a breakdown of which factors weighed it up/down.

    Mirrors how protein_serializer.py::build_protein_table_row computes the
    same score for the genome-wide list (same compute_score_value /
    compute_expression_score primitives), and how
    metabolism_summary.py::_resolve_scorer resolves a user's formula outside
    that list view -- reused here for a single protein instead of a bulk
    ranking pass. Returns None when no formula resolves for this user (the
    template just omits the card, same pattern as the page's other optional
    evidence blocks)."""
    from tpweb.services.protein_formula import choose_formula, coefficient_map, resolve_formulas_for_user
    from tpweb.services.protein_serializer import compute_expression_score, compute_score_value
    from tpweb.services.score_param_types import is_numeric_score_param

    formulas = resolve_formulas_for_user(user)
    formula = choose_formula(formulas, "")
    if formula is None:
        return None

    # Same float/string typing protein_serializer.py::score_param_value_map applies,
    # built from the score_param_values already fetched by the caller (this function's
    # only caller, build_protein_executive_context, queries them once for raw_scores/
    # druggability too -- re-querying protein.score_params.all() here would just
    # re-fetch the same rows a second time).
    param_values = {}
    for spv in score_param_values:
        param_name = spv.score_param.name
        if is_numeric_score_param(spv.score_param):
            if spv.numeric_value is not None:
                param_values[param_name] = spv.numeric_value
                continue
            try:
                param_values[param_name] = float(str(spv.value).replace(",", "."))
            except (TypeError, ValueError):
                param_values[param_name] = None
            continue
        param_values[param_name] = spv.value

    expression = (formula.expression or "").strip()
    if expression:
        from tpweb.services.formula_evaluator import build_all_options_zero
        zero_cache = build_all_options_zero(user)
        score_value, _weights = compute_expression_score(protein, expression, zero_cache)
        return {
            "score": round(score_value, 2),
            "formula_name": formula.name,
            "top_factors": [],
            "has_breakdown": False,
        }

    coefficient_by_param = coefficient_map(list(formula.terms.select_related("score_param")))
    score_value, weights = compute_score_value(param_values, coefficient_by_param)
    top_factors = [
        {
            "name": name,
            "contribution": round(contribution, 2),
            "is_off_target": _SCORE_META_CATEGORY_BY_NAME.get(name) == "off_target",
        }
        for name, contribution in sorted(weights.items(), key=lambda item: -abs(item[1]))[:5]
    ]
    return {
        "score": round(score_value, 2),
        "formula_name": formula.name,
        "top_factors": top_factors,
        "has_breakdown": True,
    }


def _raw_score(raw_scores, name):
    value = raw_scores.get(name)
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def _format_score_value(value):
    value = _raw_score({"value": value}, "value")
    if not value:
        return ""
    try:
        return f"{float(value.replace(',', '.')):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return value


def _format_network_centrality(value):
    """Preserve small non-zero network scores instead of displaying them as 0."""
    value = _raw_score({"value": value}, "value")
    if not value:
        return ""
    try:
        number = float(value.replace(",", "."))
    except (TypeError, ValueError):
        return value
    if number and abs(number) < 0.0001:
        return f"{number:.2e}"
    return f"{number:.5f}".rstrip("0").rstrip(".")


def _structure_source_kind(identifier):
    ident = (identifier or "").strip()
    upper = ident.upper()
    if not ident:
        return ""
    if upper.startswith("CB_"):
        return "ColabFold / curated model"
    if upper.startswith("AF_"):
        return "AlphaFold DB / UniProt model"
    if len(ident) == 4 and ident.isalnum():
        return "PDB experimental structure"
    if upper.startswith("A0A") or (any(ch.isdigit() for ch in ident) and any(ch.isalpha() for ch in ident)):
        return "AlphaFold DB / UniProt model"
    return "Curated structure"


def _resolve_structure_source_label(identifier, structures):
    """Authoritative {"code", "source", "label"} for a best_fpocket_structure/
    best_p2rank_structure identifier, resolved against the protein's own linked
    structures (real pdb.experiment) rather than trusting the string-heuristic
    _structure_source_kind. Falls back to that heuristic, with the raw identifier as
    the code, only when nothing currently linked matches it."""
    if not identifier:
        return None
    for link in structures or []:
        if structure_matches_identifier(link, identifier):
            pdb = getattr(link, "pdb", None)
            if pdb is None:
                continue
            source_key = classify_structure_experiment(getattr(pdb, "experiment", ""))
            return {"code": pdb.code, "source": source_key, "label": structure_source_label(source_key)}
    return {"code": identifier, "source": "", "label": _structure_source_kind(identifier)}


_pocket_reference_cache = None


def _pocket_reference_rows():
    """Cached module-level lookup for the FPocket druggability Property/ResidueSet rows
    used by _resolve_fpocket_structure_by_max_score -- same always-the-same-rows
    rationale as StructureView._pdb_reference_rows, kept local to this module rather
    than imported from a view (CLAUDE.md: views delegate to services, not the reverse)."""
    global _pocket_reference_cache
    if _pocket_reference_cache is None:
        from tpweb.models.pdb import Property, ResidueSet
        _pocket_reference_cache = {
            "druggability_score": Property.objects.get(name="druggability_score"),
            "FPocketPocket": ResidueSet.objects.get(name="FPocketPocket"),
        }
    return _pocket_reference_cache


def _resolve_fpocket_structure_by_max_score(structures):
    """Fallback for genomes processed by the classic in-app pipeline, which never
    records which structure produced the max FPocket score it loads as the
    genome-wide "Druggability" ScoreParamValue (unlike the curated/Gates pipeline's
    best_fpocket_structure). Re-derives it live: the same max-druggability pocket
    lookup index_pocket_size_outlier.py's auto-resolve fallback already uses, just
    for structure identity instead of pocket geometry."""
    from tpweb.models.pdb import PDBResidueSet

    pdb_ids = [link.pdb_id for link in (structures or [])]
    if not pdb_ids:
        return None
    ref = _pocket_reference_rows()
    best_rs = (
        PDBResidueSet.objects
        .filter(pdb_id__in=pdb_ids, residue_set=ref["FPocketPocket"], properties__property=ref["druggability_score"])
        .select_related("pdb")
        .order_by("-properties__value")
        .first()
    )
    if best_rs is None or best_rs.pdb is None:
        return None
    source_key = classify_structure_experiment(getattr(best_rs.pdb, "experiment", ""))
    return {"code": best_rs.pdb.code, "source": source_key, "label": structure_source_label(source_key)}


def _format_pocket_label(value):
    label = (value or "").strip()
    if not label:
        return ""
    if label == "No_pockets":
        return "No pockets"
    if label.lower().startswith("pocket pocket"):
        suffix = label[len("Pocket pocket"):].strip()
        return f"Pocket {suffix}" if suffix else "Pocket"
    return label


def annotate_selected_source_status(evidence, structures, visible_links=None):
    if not evidence:
        return
    selected_identifier = (
        evidence.get("fpocket", {}).get("structure")
        or evidence.get("p2rank", {}).get("structure")
    )
    if not selected_identifier:
        return

    visible_links = [link for link in (visible_links or []) if link is not None]
    visible = any(
        structure_matches_identifier(link, selected_identifier)
        for link in visible_links
    )
    loaded = visible or any(
        structure_matches_identifier(link, selected_identifier)
        for link in (structures or [])
    )

    evidence["selected_source_visible"] = visible
    evidence["selected_source_loaded"] = loaded
    if visible:
        evidence["selected_source_status_label"] = "Source shown in viewer"
        evidence["selected_source_status_tone"] = "direct"
    elif loaded:
        evidence["selected_source_status_label"] = "Source loaded, not currently shown"
        evidence["selected_source_status_tone"] = "meta"
    else:
        evidence["selected_source_status_label"] = "Selected source not loaded in viewer"
        evidence["selected_source_status_tone"] = "warning"


def build_selected_pocket_evidence(raw_scores):
    fpocket_score = _format_score_value(_raw_score(raw_scores, "Druggability"))
    fpocket_structure = _raw_score(raw_scores, "best_fpocket_structure")
    fpocket_pocket = _format_pocket_label(_raw_score(raw_scores, "fpocket_pocket"))
    p2rank_score = _format_score_value(_raw_score(raw_scores, "p2rank_probability"))
    p2rank_structure = _raw_score(raw_scores, "best_p2rank_structure")
    p2rank_pocket = _format_pocket_label(_raw_score(raw_scores, "p2rank_pocket"))
    colabfold_fpocket_score = _format_score_value(_raw_score(raw_scores, "colabfold_druggability_score"))
    colabfold_fpocket_pocket = _format_pocket_label(_raw_score(raw_scores, "colabfold_fpocket_pocket"))
    colabfold_p2rank_score = _format_score_value(_raw_score(raw_scores, "colabfold_p2rank_probability"))
    colabfold_p2rank_pocket = _format_pocket_label(_raw_score(raw_scores, "colabfold_p2rank_pocket"))

    has_any = any([
        fpocket_score, fpocket_structure, fpocket_pocket,
        p2rank_score, p2rank_structure, p2rank_pocket,
        colabfold_fpocket_score, colabfold_fpocket_pocket,
        colabfold_p2rank_score, colabfold_p2rank_pocket,
    ])
    if not has_any:
        return None

    selected_source_kind = _structure_source_kind(fpocket_structure or p2rank_structure)
    return {
        "selected_source_kind": selected_source_kind,
        "fpocket": {
            "score": fpocket_score,
            "structure": fpocket_structure,
            "pocket": fpocket_pocket,
            "source_kind": _structure_source_kind(fpocket_structure),
        },
        "p2rank": {
            "score": p2rank_score,
            "structure": p2rank_structure,
            "pocket": p2rank_pocket,
            "source_kind": _structure_source_kind(p2rank_structure),
        },
        "colabfold": {
            "fpocket_score": colabfold_fpocket_score,
            "fpocket_pocket": colabfold_fpocket_pocket,
            "p2rank_score": colabfold_p2rank_score,
            "p2rank_pocket": colabfold_p2rank_pocket,
        },
    }


def _truthy_score(value):
    return str(value or "").strip().lower() in {"true", "t", "yes", "y", "1"}


def build_conservation_profile(raw_scores):
    roary_raw = _raw_score(raw_scores, "core_roary")
    corecruncher_raw = _raw_score(raw_scores, "core_corecruncher")
    if not roary_raw and not corecruncher_raw:
        return None
    roary = _truthy_score(roary_raw)
    corecruncher = _truthy_score(corecruncher_raw)
    return {
        "roary": roary,
        "corecruncher": corecruncher,
        "is_core": roary and corecruncher,
        "roary_label": "core" if roary else "accessory",
        "corecruncher_label": "core" if corecruncher else "accessory",
    }


def build_microbiome_context(raw_scores):
    count = _format_score_value(_raw_score(raw_scores, "gut_microbiome_offtarget_counts"))
    total = _format_score_value(_raw_score(raw_scores, "gut_microbiome_genomes_analyzed"))
    norm = _format_score_value(_raw_score(raw_scores, "gut_microbiome_offtarget_norm"))
    if not count and not total and not norm:
        return None
    percentage = None
    try:
        count_value = float(str(count).replace(",", "."))
        total_value = float(str(total).replace(",", "."))
        if total_value > 0:
            percentage = round(100 * count_value / total_value, 1)
    except (TypeError, ValueError):
        pass
    return {"count": count, "total": total, "norm": norm, "percentage": percentage}


_CHOKEPOINT_LABELS = {
    GeneReactionLink.CHOKEPOINT_PRODUCING: "Producing chokepoint",
    GeneReactionLink.CHOKEPOINT_CONSUMING: "Consuming chokepoint",
    GeneReactionLink.CHOKEPOINT_BOTH: "Producing & consuming chokepoint",
}


def _build_reaction_participants(reaction):
    substrates = []
    products = []
    for participant in reaction.participants.all():
        entry = {
            "name": participant.species.display_name or participant.species.species_id,
            "is_currency": participant.species.is_currency,
            "stoichiometry": participant.stoichiometry,
        }
        if participant.role == ReactionParticipant.ROLE_REACTANT:
            substrates.append(entry)
        else:
            products.append(entry)
    return substrates, products


def _genome_centrality_values(biodatabase):
    """Every PTOOLS_betweenness_centrality value loaded for a genome, used to
    rank one protein's percentile against the rest of its genome.

    This is a genome-wide scan (every protein's score, not just the one
    being viewed), so it's cached per genome with the same TTL convention as
    assembly_workspace.py's aggregates -- without this, build_metabolic_context
    re-ran the full genome scan from scratch on every single protein detail
    page view."""
    cache_key = f"Target:metabolic_centrality_values:{biodatabase.biodatabase_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    values = list(
        ScoreParamValue.objects
        .filter(score_param__name="PTOOLS_betweenness_centrality",
                bioentry__biodatabase=biodatabase)
        .values_list("numeric_value", flat=True)
    )
    values = [v for v in values if v is not None]
    cache.set(cache_key, values, OVERVIEW_CACHE_TTL_SECONDS)
    return values


def build_metabolic_context(protein, raw_scores):
    links = list(
        GeneReactionLink.objects.filter(bioentry=protein)
        .select_related("reaction")
        .prefetch_related("reaction__pathways", "reaction__participants__species")
    )
    assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
    assembly_slug = genome_url_slug(assembly_name)
    import_run = MetabolicImportRun.objects.filter(genome_accession=assembly_name).first()

    if not links:
        if not import_run:
            # No metabolic model imported for this genome at all -- nothing to show.
            return None
        # A network is imported for this genome, but this protein just isn't part of
        # it -- still show the section with an explicit empty state instead of hiding
        # it, so it's clear this is "not associated" rather than "no data loaded".
        return {
            "in_network": False,
            "import_run": import_run,
            "network_url": reverse("tpwebapp:genome_metabolism", kwargs={"genome": assembly_slug}),
        }

    reactions = []
    pathway_chips = {}
    for link in links:
        reaction = link.reaction
        kegg_url = (
            f"https://www.kegg.jp/entry/{reaction.kegg_reaction_id}"
            if reaction.kegg_reaction_id else ""
        )
        # reaction_id is already the BioCyc/MetaCyc frame id (load_metabolism.py prefers the
        # SBML name attribute, which MetaFlux/Pathway Tools exports use for the frame id), so
        # unlike kegg_url this is always buildable, no annotation dependency.
        metacyc_url = f"https://metacyc.org/META/NEW-IMAGE?type=REACTION&object={reaction.reaction_id}"
        substrates, products = _build_reaction_participants(reaction)
        reactions.append({
            "reaction_id": reaction.reaction_id,
            "name": reaction.name or reaction.reaction_id,
            "ec_numbers": [ec for ec in (reaction.ec_numbers or "").split(",") if ec],
            "kegg_reaction_id": reaction.kegg_reaction_id,
            "kegg_url": kegg_url,
            "metacyc_url": metacyc_url,
            "reversible": reaction.reversible,
            "chokepoint_role": link.chokepoint_role,
            "chokepoint_label": _CHOKEPOINT_LABELS.get(link.chokepoint_role),
            "isoenzyme_count": reaction.isoenzyme_count,
            "has_isoenzyme_backup": reaction.isoenzyme_count > 1,
            "substrates": substrates,
            "products": products,
            "has_metabolites": bool(substrates or products),
        })
        for pathway in reaction.pathways.all():
            pathway_chips[(pathway.source, pathway.external_id)] = {
                "source": pathway.source,
                "external_id": pathway.external_id,
                "name": pathway.name,
                "url": reverse(
                    "tpwebapp:genome_metabolism_pathway",
                    kwargs={
                        "genome": assembly_slug,
                        "source": pathway.source,
                        "external_id": pathway.external_id,
                    },
                ),
            }

    centrality_raw = _raw_score(raw_scores, "PTOOLS_betweenness_centrality")
    centrality = _format_network_centrality(centrality_raw)
    percentile = None
    if centrality_raw:
        try:
            value = float(centrality_raw)
            genome_values = _genome_centrality_values(protein.biodatabase)
            if genome_values:
                below = sum(1 for v in genome_values if v < value)
                percentile = round(100 * below / len(genome_values), 1)
        except (TypeError, ValueError):
            percentile = None

    is_chokepoint = any(l.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE for l in links)

    context = {
        "in_network": True,
        "reactions": reactions,
        "pathways": sorted(pathway_chips.values(), key=lambda p: (p["source"], p["name"])),
        "centrality": centrality,
        "centrality_percentile": percentile,
        "has_centrality_percentile": percentile is not None,
        "is_chokepoint": is_chokepoint,
        "import_run": import_run,
    }
    context["summary_sentence"] = build_target_metabolic_sentence(
        context, human_offtarget_no_hit=_raw_score(raw_scores, "human_offtarget") == "no_hit",
    )
    return context


def _score_float(raw_scores, name):
    value = _raw_score(raw_scores, name)
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _append_summary_item(items, label, detail, tone="neutral", anchor="#section-target-profile", priority=0):
    items.append({
        "label": label,
        "detail": detail,
        "tone": tone,
        "anchor": anchor,
        "priority": priority,
    })


def build_target_executive_summary(
    raw_scores,
    structure_summary,
    selected_pocket_evidence,
    conservation_profile,
    microbiome_context,
    metabolic_context,
    binders,
):
    strengths = []
    risks = []
    missing = []
    signal_score = 0

    if metabolic_context:
        if metabolic_context.get("is_chokepoint"):
            _append_summary_item(
                strengths,
                "Metabolic chokepoint",
                "Catalyzes a reaction that is the only producer or consumer of a metabolite in the imported metabolic model.",
                "good",
                "#section-metabolic-context",
                priority=1,
            )
            signal_score += 2
        percentile = metabolic_context.get("centrality_percentile")
        if percentile is not None:
            try:
                percentile_value = float(percentile)
            except (TypeError, ValueError):
                percentile_value = None
            if percentile_value is not None and percentile_value >= 80:
                _append_summary_item(
                    strengths,
                    "Central metabolic position",
                    f"More central than {percentile}% of genes in this genome.",
                    "good",
                    "#section-metabolic-context",
                )
                signal_score += 1
        reactions = metabolic_context.get("reactions") or []
        if reactions and all(not r.get("has_isoenzyme_backup") for r in reactions):
            _append_summary_item(
                strengths,
                "No isoenzyme backup detected",
                "Imported GPR rules do not show an alternative enzyme for the catalyzed reaction set.",
                "good",
                "#section-metabolic-context",
            )
            signal_score += 1
    else:
        _append_summary_item(
            missing,
            "No metabolic context",
            "No SBML/network-derived reaction evidence is loaded for this protein.",
            "missing",
            "#section-metabolic-context",
        )

    # Computed here (rather than down with the rest of the pocket signals,
    # below) so the human/microbiome off-target sentences can weigh the risk
    # against druggability instead of reporting it in isolation.
    fpocket_score = _score_float(raw_scores, "Druggability")
    p2rank_score = _score_float(raw_scores, "p2rank_probability")

    def _pocket_signal_clause():
        # P2Rank is the primary druggability signal shown across the app (roadmap
        # 6/08); fall back to FPocket when no P2Rank value is loaded.
        if p2rank_score is not None and p2rank_score >= 0.2:
            return (
                f" This target also has a predicted binding pocket (P2Rank {p2rank_score:.2f}) — "
                "check the ligand evidence before deprioritizing on off-target risk alone."
            )
        if fpocket_score is not None and fpocket_score >= 0.4:
            return (
                f" This target also has a predicted binding pocket (FPocket {fpocket_score:.2f}) — "
                "check the ligand evidence before deprioritizing on off-target risk alone."
            )
        return ""

    human_offtarget = _raw_score(raw_scores, "human_offtarget").lower()
    if human_offtarget == "no_hit":
        _append_summary_item(
            strengths,
                "No similar human protein detected",
                "The current BLAST sequence screen did not find a significant human match, lowering apparent off-target risk.",
            "good",
        )
        signal_score += 1
    elif human_offtarget == "hit":
        identity_value = _score_float(raw_scores, "human_identity")
        identity = _format_score_value(_raw_score(raw_scores, "human_identity"))
        druggability_clause = _pocket_signal_clause()
        if identity_value is not None and identity_value < 30:
            _append_summary_item(
                risks,
                "Low human similarity",
                f"A human hit was flagged, but identity is only {identity}% - a weak match, lower risk than a close homolog.{druggability_clause}",
                "watch",
                "#section-binders",
            )
        else:
            detail = f"Top human hit identity: {identity}%.{druggability_clause}" if identity else f"A significant human homolog was found.{druggability_clause}"
            _append_summary_item(risks, "Human similarity", detail, "risk", "#section-binders")

    if microbiome_context:
        gut_offtarget = _raw_score(raw_scores, "gut_microbiome_offtarget").lower()
        if gut_offtarget == "no_hit":
            _append_summary_item(
                strengths,
                "No similar gut-microbiome protein detected",
                "The current microbiome screen did not find a significant match in the screened reference genomes.",
                "good",
                "#section-target-profile",
            )
            signal_score += 1
        elif gut_offtarget == "hit":
            count = microbiome_context.get("count")
            total = microbiome_context.get("total")
            percentage = microbiome_context.get("percentage")
            if count and total and percentage is not None:
                detail = f"{count} of {total} screened genomes ({percentage}%) have a significant similarity hit."
            elif count and total:
                detail = f"{count} hits across {total} screened genomes."
            else:
                detail = "Similarity to gut microbiome references was detected."
            detail += _pocket_signal_clause()
            _append_summary_item(risks, "Microbiome similarity", detail, "watch", "#section-binders")

    if conservation_profile:
        if conservation_profile.get("is_core"):
            _append_summary_item(
                strengths,
                "Core gene across strains",
                "Marked as conserved by both pan-genome tools: Roary and CoreCruncher.",
                "good",
                "#section-target-profile",
            )
            signal_score += 1
        else:
            _append_summary_item(
                risks,
                "Mixed conservation",
                "Core/accessory calls are not fully concordant.",
                "watch",
                "#section-target-profile",
            )

    pocket_size_outlier = _truthy_score(_raw_score(raw_scores, "pocket_size_outlier"))
    if fpocket_score is not None:
        if fpocket_score >= 0.7:
            if pocket_size_outlier:
                _append_summary_item(risks, "Best pocket may be a modeling artifact", f"FPocket selected-pocket score {fpocket_score:.2f}, but this pocket's geometry is unusually large/diffuse compared to this protein's other predicted pockets — may reflect a low-confidence or disordered model region rather than a real cavity.", "watch", "#section-target-profile")
                signal_score += 1
            else:
                _append_summary_item(strengths, "Strong predicted binding pocket", f"FPocket selected-pocket score {fpocket_score:.2f}. This is a computational pocket signal, not binding validation.", "good", "#section-target-profile")
                signal_score += 2
        elif fpocket_score >= 0.4:
            if pocket_size_outlier:
                _append_summary_item(risks, "Best pocket may be a modeling artifact", f"FPocket selected-pocket score {fpocket_score:.2f}, but this pocket's geometry is unusually large/diffuse compared to this protein's other predicted pockets — may reflect a low-confidence or disordered model region rather than a real cavity.", "watch", "#section-target-profile")
            else:
                _append_summary_item(strengths, "Moderate predicted binding pocket", f"FPocket selected-pocket score {fpocket_score:.2f}. This supports review but is not experimental validation.", "neutral", "#section-target-profile")
                signal_score += 1
        elif fpocket_score > 0:
            _append_summary_item(risks, "Weak predicted binding pocket", f"FPocket selected-pocket score {fpocket_score:.2f}.", "watch", "#section-target-profile")
    else:
        _append_summary_item(missing, "No FPocket pocket score", "No selected computational pocket-druggability value is available.", "missing", "#section-target-profile")

    if p2rank_score is not None:
        if p2rank_score >= 0.5:
            _append_summary_item(strengths, "Second pocket predictor agrees", f"P2Rank predicted binding-site probability {p2rank_score:.2f}.", "good", "#section-target-profile")
            signal_score += 1
        elif p2rank_score > 0:
            _append_summary_item(risks, "Weak second pocket-predictor signal", f"P2Rank predicted binding-site probability {p2rank_score:.2f}.", "watch", "#section-target-profile")
    elif not selected_pocket_evidence:
        _append_summary_item(missing, "No P2Rank pocket score", "No second computational pocket-prediction value is available.", "missing", "#section-target-profile")

    if (
        fpocket_score is not None and fpocket_score >= 0.7
        and p2rank_score is not None and p2rank_score >= 0.5
        and not pocket_size_outlier
    ):
        _append_summary_item(
            strengths,
            "Independent pocket support: P2Rank + FPocket",
            (
                f"Both predictors report a high-scoring binding site "
                f"(P2Rank {p2rank_score:.2f}, FPocket {fpocket_score:.2f}). "
                "Use the 3D pocket comparison to verify whether they identify the same site."
            ),
            "good",
            "#section-target-profile",
            priority=1,
        )
        signal_score += 1

    if structure_summary and structure_summary.get("has_structure"):
        _append_summary_item(
            strengths,
            "Structure available",
            structure_summary.get("label") or "At least one structure/model is loaded.",
            "good",
            "#section-structure",
        )
        signal_score += 1
        if structure_summary.get("source") in (STRUCTURE_SOURCE_EXPERIMENTAL, STRUCTURE_SOURCE_MIXED):
            _append_summary_item(
                strengths,
                "Experimental structure available",
                "At least one PDB experimental structure is loaded, not just a predicted model - stronger structural coverage than AlphaFold/ColabFold alone.",
                "good",
                "#section-structure",
                priority=1,
            )
            signal_score += 1
    else:
        _append_summary_item(
            missing,
            "No structure loaded",
            "No structure/model is available for visual inspection.",
            "missing",
            "#section-structure",
        )

    binder_summary = (binders or {}).get("summary") or {}
    if binder_summary:
        direct_count = binder_summary.get("direct_count") or 0
        structural_count = binder_summary.get("structural_count") or 0
        bioactive_count = binder_summary.get("bioactive_count") or 0
        proposed_count = binder_summary.get("proposed_count") or 0
        if direct_count:
            _append_summary_item(strengths, "Direct ligand evidence", f"{direct_count} direct ligand records.", "good", "#section-binders", priority=1)
            signal_score += 2
        elif structural_count or bioactive_count:
            detail = f"{structural_count} structural and {bioactive_count} bioactivity records."
            _append_summary_item(strengths, "Ligand evidence via structure/bioactivity", detail, "neutral", "#section-binders")
            signal_score += 1
        elif proposed_count:
            _append_summary_item(risks, "Only proposed compounds", f"{proposed_count} ZINC similarity-based candidates, no stronger ligand evidence.", "watch", "#section-binders")
    else:
        _append_summary_item(missing, "No ligand evidence", "No experimental PDB ligands, measured ChEMBL bioactivity, or proposed ZINC compound records are available.", "missing", "#section-binders")

    pdb_direct = (binders or {}).get("pdb_direct") or []
    chembl_direct = (binders or {}).get("chembl_direct") or []
    strong_chembl = [b for b in chembl_direct if (b.get("score") or 0) >= 7]
    if pdb_direct:
        _append_summary_item(
            strengths,
            "Strong known ligand: co-crystal structure",
            f"{len(pdb_direct)} PDB record(s) show a ligand actually co-crystallized with this exact protein - real experimental evidence, not a computational prediction.",
            "good",
            "#section-binders",
            priority=1,
        )
        signal_score += 1
    elif strong_chembl:
        top_chembl = max(strong_chembl, key=lambda b: b.get("score") or 0)
        _append_summary_item(
            strengths,
            "Strong known ligand (ChEMBL)",
            f"Direct bioactivity record with pchembl {top_chembl.get('score'):.2f} (sub-100nM potency range) measured on this exact protein.",
            "good",
            "#section-binders",
            priority=1,
        )
        signal_score += 1

    if not strengths:
        verdict = "Evidence is still sparse for this target."
        tone = "sparse"
    elif signal_score >= 8:
        verdict = "Strong target candidate with converging metabolic, structural and chemical evidence."
        tone = "strong"
    elif signal_score >= 5:
        verdict = "Promising target candidate with multiple supporting evidence streams."
        tone = "promising"
    else:
        verdict = "Target candidate with partial support; inspect missing evidence before prioritizing."
        tone = "partial"

    # Stable sort: higher-priority (more specific, e.g. direct ligand evidence,
    # experimental structure, pocket consensus) items surface first so they
    # survive the display cap even when a well-evidenced protein has more than
    # nine positive strengths; items with equal priority keep their original
    # (already meaningful) append order.
    ranked_strengths = sorted(strengths, key=lambda item: -item.get("priority", 0))

    return {
        "verdict": verdict,
        "tone": tone,
        "signal_score": signal_score,
        "strengths": ranked_strengths[:9],
        "risks": risks[:4],
        "missing": missing[:4],
    }


def build_protein_executive_context(
    protein, structures=None, structure_summary=None, search_query="", binders=None, user=None,
):
    """One-call bundle of everything explain_target (and ProteinView.get)
    need: the raw ScoreParamValue dict plus every derived context builder
    above, culminating in the strengths/risks/missing verdict.

    ProteinView.get() already fetches/sorts `structures`, computes its own
    `structure_summary`, and builds `binders` with the user's search query --
    passing those in here avoids re-querying/recomputing them a second time.
    Callers that don't have them yet (explain_target) get the exact same
    behavior as before by leaving them as the defaults."""
    score_param_values = list(
        ScoreParamValue.objects.filter(bioentry=protein).select_related("score_param")
    )
    raw_scores = {
        spv.score_param.name: spv.value if spv.value else (
            str(round(spv.numeric_value, 4)) if spv.numeric_value is not None else ""
        )
        for spv in score_param_values
    }
    if structures is None:
        structures = list(BioentryStructure.objects.filter(bioentry=protein).select_related("pdb"))
    if structure_summary is None:
        structure_summary = summarize_structure_sources(structures)

    # P2Rank is the primary druggability signal shown across the app (roadmap 6/08) --
    # prefer it here too, falling back to FPocket's score when no P2Rank value is loaded.
    # 4-tuple (label, tone, tool_source, structure_source) instead of druggability_label's
    # bare 2-tuple, so the template can say which tool AND which structure (PDB/AlphaFold/
    # ColabFold) the shown value actually came from.
    p2rank_spv = next(
        (spv for spv in score_param_values if spv.score_param.name == "p2rank_probability"), None
    )
    p2rank_raw = None
    if p2rank_spv is not None:
        p2rank_raw = p2rank_spv.numeric_value if p2rank_spv.numeric_value is not None else p2rank_spv.value or None
    p2rank_druggability = p2rank_label(p2rank_raw)

    drugg_spv = next(
        (spv for spv in score_param_values if spv.score_param.name == "Druggability"), None
    )
    drugg_raw = None
    if drugg_spv is not None:
        drugg_raw = drugg_spv.numeric_value if drugg_spv.numeric_value is not None else drugg_spv.value or None
    fpocket_druggability = druggability_label(drugg_raw)

    if p2rank_druggability:
        structure_source = _resolve_structure_source_label(raw_scores.get("best_p2rank_structure"), structures)
        druggability = (p2rank_druggability[0], p2rank_druggability[1], "P2Rank", structure_source)
    elif fpocket_druggability:
        structure_source = _resolve_structure_source_label(raw_scores.get("best_fpocket_structure"), structures)
        if structure_source is None:
            # Classic in-app pipeline never recorded which structure won -- re-derive it.
            structure_source = _resolve_fpocket_structure_by_max_score(structures)
        druggability = (fpocket_druggability[0], fpocket_druggability[1], "FPocket", structure_source)
    else:
        druggability = None

    selected_pocket_evidence = build_selected_pocket_evidence(raw_scores)
    annotate_selected_source_status(selected_pocket_evidence, structures)
    conservation_profile = build_conservation_profile(raw_scores)
    microbiome_context = build_microbiome_context(raw_scores)
    target_profile = build_target_profile(raw_scores, microbiome_context=microbiome_context)
    metabolic_context = build_metabolic_context(protein, raw_scores)

    if binders is None:
        binders = create_binders_dict(protein, search_query=search_query, structures=structures)

    target_summary = build_target_executive_summary(
        raw_scores,
        structure_summary,
        selected_pocket_evidence,
        conservation_profile,
        microbiome_context,
        metabolic_context,
        binders,
    )

    score_breakdown = build_score_breakdown(protein, score_param_values, user) if user is not None else None

    return {
        "raw_scores": raw_scores,
        "druggability": druggability,
        "target_profile": target_profile,
        "selected_pocket_evidence": selected_pocket_evidence,
        "conservation_profile": conservation_profile,
        "microbiome_context": microbiome_context,
        "metabolic_context": metabolic_context,
        "structure_summary": structure_summary,
        "binders": binders,
        "target_summary": target_summary,
        "score_breakdown": score_breakdown,
    }
