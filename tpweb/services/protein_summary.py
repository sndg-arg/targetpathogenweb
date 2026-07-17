"""Builds the "Target profile" / executive-summary evidence shown on the
protein detail page (target profile chips, selected pocket evidence,
conservation, microbiome context, metabolic context, and the combined
verdict/strengths/risks/missing summary).

Extracted verbatim from tpweb/views/ProteinView.py so it can be reused by
the LLM agent's explain_target tool without importing private view
internals from a service module (CLAUDE.md: views delegate to services,
not the other way around).
"""
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.Metabolism import GeneReactionLink, MetabolicImportRun, ReactionParticipant
from tpweb.services.binder_summary import create_binders_dict
from tpweb.services.metabolism_summary import build_target_metabolic_sentence
from tpweb.services.genome_workspace import genome_url_slug
from tpweb.services.structure_sources import structure_matches_identifier

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


def build_target_profile(raw_scores):
    items = []
    for name, label, category, good_vals, bad_vals, tooltip in _SCORE_META:
        val = raw_scores.get(name)
        if not val:
            continue
        if val in good_vals:
            tone = "good"
        elif val in bad_vals:
            tone = "bad"
        else:
            tone = "neutral"
        display = val.replace("_", " ").replace("no hit", "No hit").replace("no_hit", "No hit")
        if name in _NO_HIT_EVALUE_OVERRIDES:
            check_name, no_hit_val, _ = _NO_HIT_EVALUE_OVERRIDES[name]
            if str(raw_scores.get(check_name) or "").strip().lower() == no_hit_val:
                continue
        items.append({"label": label, "value": display, "tone": tone, "category": category, "tooltip": tooltip})
    return items


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
    return {"count": count, "total": total, "norm": norm}


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


def build_metabolic_context(protein, raw_scores):
    links = list(
        GeneReactionLink.objects.filter(bioentry=protein)
        .select_related("reaction")
        .prefetch_related("reaction__pathways", "reaction__participants__species")
    )
    if not links:
        return None

    reactions = []
    pathway_chips = {}
    assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
    assembly_slug = genome_url_slug(assembly_name)
    for link in links:
        reaction = link.reaction
        kegg_url = (
            f"https://www.kegg.jp/entry/{reaction.kegg_reaction_id}"
            if reaction.kegg_reaction_id else ""
        )
        substrates, products = _build_reaction_participants(reaction)
        reactions.append({
            "reaction_id": reaction.reaction_id,
            "name": reaction.name or reaction.reaction_id,
            "ec_numbers": [ec for ec in (reaction.ec_numbers or "").split(",") if ec],
            "kegg_reaction_id": reaction.kegg_reaction_id,
            "kegg_url": kegg_url,
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
    centrality = _format_score_value(centrality_raw)
    percentile = None
    if centrality_raw:
        try:
            value = float(centrality_raw)
            genome_values = list(
                ScoreParamValue.objects
                .filter(score_param__name="PTOOLS_betweenness_centrality",
                        bioentry__biodatabase=protein.biodatabase)
                .values_list("numeric_value", flat=True)
            )
            genome_values = [v for v in genome_values if v is not None]
            if genome_values:
                below_or_equal = sum(1 for v in genome_values if v <= value)
                percentile = round(100 * below_or_equal / len(genome_values), 1)
        except (TypeError, ValueError):
            percentile = None

    is_chokepoint = any(l.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE for l in links)

    import_run = MetabolicImportRun.objects.filter(genome_accession=assembly_name).first()

    context = {
        "reactions": reactions,
        "pathways": sorted(pathway_chips.values(), key=lambda p: (p["source"], p["name"])),
        "centrality": centrality,
        "centrality_percentile": percentile,
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


def _append_summary_item(items, label, detail, tone="neutral", anchor="#section-target-profile"):
    items.append({
        "label": label,
        "detail": detail,
        "tone": tone,
        "anchor": anchor,
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
                "Metabolic bottleneck",
                "Catalyzes a reaction that is the only producer or consumer of a metabolite in the imported metabolic model.",
                "good",
                "#section-metabolic-context",
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
        identity = _format_score_value(_raw_score(raw_scores, "human_identity"))
        detail = f"Top human hit identity: {identity}%." if identity else "A significant human homolog was found."
        _append_summary_item(risks, "Human similarity", detail, "risk")

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
            detail = f"{count} hits across {total} screened genomes." if count and total else "Similarity to gut microbiome references was detected."
            _append_summary_item(risks, "Microbiome similarity", detail, "risk", "#section-target-profile")

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

    fpocket_score = _score_float(raw_scores, "Druggability")
    pocket_size_outlier = _truthy_score(_raw_score(raw_scores, "pocket_size_outlier"))
    p2rank_score = _score_float(raw_scores, "p2rank_probability")
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

    if structure_summary and structure_summary.get("has_structure"):
        _append_summary_item(
            strengths,
            "Structure available",
            structure_summary.get("label") or "At least one structure/model is loaded.",
            "good",
            "#section-structure",
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
            _append_summary_item(strengths, "Direct ligand evidence", f"{direct_count} direct ligand records.", "good", "#section-binders")
            signal_score += 2
        elif structural_count or bioactive_count:
            detail = f"{structural_count} structural and {bioactive_count} bioactivity records."
            _append_summary_item(strengths, "Ligand evidence via structure/bioactivity", detail, "neutral", "#section-binders")
            signal_score += 1
        elif proposed_count:
            _append_summary_item(risks, "Only proposed compounds", f"{proposed_count} ZINC similarity-based candidates, no stronger ligand evidence.", "watch", "#section-binders")
    else:
        _append_summary_item(missing, "No ligand evidence", "No experimental PDB ligands, measured ChEMBL bioactivity, or proposed ZINC compound records are available.", "missing", "#section-binders")

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

    return {
        "verdict": verdict,
        "tone": tone,
        "signal_score": signal_score,
        "strengths": strengths[:6],
        "risks": risks[:4],
        "missing": missing[:4],
    }


def build_protein_executive_context(protein):
    """One-call bundle of everything explain_target (and ProteinView.get)
    need: the raw ScoreParamValue dict plus every derived context builder
    above, culminating in the strengths/risks/missing verdict."""
    raw_scores = {
        spv.score_param.name: spv.value if spv.value else (
            str(round(spv.numeric_value, 4)) if spv.numeric_value is not None else ""
        )
        for spv in ScoreParamValue.objects.filter(bioentry=protein).select_related("score_param")
    }

    from tpweb.services.structure_sources import summarize_structure_sources
    from tpweb.models.BioentryStructure import BioentryStructure

    structures = list(BioentryStructure.objects.filter(bioentry=protein).select_related("pdb"))
    structure_summary = summarize_structure_sources(structures)

    target_profile = build_target_profile(raw_scores)
    selected_pocket_evidence = build_selected_pocket_evidence(raw_scores)
    annotate_selected_source_status(selected_pocket_evidence, structures)
    conservation_profile = build_conservation_profile(raw_scores)
    microbiome_context = build_microbiome_context(raw_scores)
    metabolic_context = build_metabolic_context(protein, raw_scores)

    binders = create_binders_dict(protein, structures=structures)

    target_summary = build_target_executive_summary(
        raw_scores,
        structure_summary,
        selected_pocket_evidence,
        conservation_profile,
        microbiome_context,
        metabolic_context,
        binders,
    )

    return {
        "raw_scores": raw_scores,
        "target_profile": target_profile,
        "selected_pocket_evidence": selected_pocket_evidence,
        "conservation_profile": conservation_profile,
        "microbiome_context": microbiome_context,
        "metabolic_context": metabolic_context,
        "structure_summary": structure_summary,
        "binders": binders,
        "target_summary": target_summary,
    }
