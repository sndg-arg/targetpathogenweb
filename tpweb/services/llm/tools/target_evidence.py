"""Shared evidence formatting for target-assistant tools."""
from __future__ import annotations

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from tpweb.services.assembly_workspace import score_single_protein
from tpweb.services.protein_summary import build_protein_executive_context


def get_protein_for_accession(assembly_name, accession):
    accession = (accession or "").strip()
    if not accession:
        return None
    return Bioentry.objects.filter(
        biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
        accession=accession,
    ).first()


def _value(raw_scores, name, missing="not loaded"):
    value = raw_scores.get(name)
    if value in (None, ""):
        return missing
    return str(value)


def _section_items(title, items):
    lines = [f"{title}:"]
    lines.extend(f"  - {label}: {detail}" for label, detail in items)
    return lines


def build_target_evidence_record(assembly_name, accession):
    protein = get_protein_for_accession(assembly_name, accession)
    if protein is None:
        return None

    context = build_protein_executive_context(protein)
    raw_scores = context.get("raw_scores") or {}
    summary = context.get("target_summary") or {}
    score_row = score_single_protein(assembly_name, protein.accession)
    metabolic_context = context.get("metabolic_context")
    metabolic = metabolic_context or {}
    microbiome = context.get("microbiome_context") or {}
    conservation = context.get("conservation_profile") or {}
    binders = context.get("binders") or {}
    binder_summary = binders.get("summary") or {}

    evidence_score = "not loaded"
    evidence_max = "15"
    if score_row is not None:
        evidence_score = f"{round(score_row['score'], 1)}"

    reactions = metabolic.get("reactions") or []
    reaction_names = [r.get("reaction_id") for r in reactions[:4] if r.get("reaction_id")]
    pathway_names = [p.get("name") or p.get("external_id") for p in (metabolic.get("pathways") or [])[:4]]

    return {
        "protein": protein,
        "context": context,
        "summary": summary,
        "raw_scores": raw_scores,
        "score_row": score_row,
        "accession": protein.accession,
        "description": protein.description or "no description",
        "evidence_score": evidence_score,
        "evidence_max": evidence_max,
        "verdict": summary.get("verdict") or "No automatic verdict available.",
        "signal_score": summary.get("signal_score"),
        "fpocket": _value(raw_scores, "Druggability"),
        "p2rank": _value(raw_scores, "p2rank_probability"),
        "pocket_outlier": _value(raw_scores, "pocket_size_outlier"),
        "human_offtarget": _value(raw_scores, "human_offtarget"),
        "human_identity": _value(raw_scores, "human_identity"),
        "human_evalue": _value(raw_scores, "human_evalue"),
        "microbiome_offtarget": _value(raw_scores, "gut_microbiome_offtarget"),
        "microbiome_count": microbiome.get("count") or _value(raw_scores, "gut_microbiome_offtarget_counts"),
        "microbiome_total": microbiome.get("total") or _value(raw_scores, "gut_microbiome_genomes_analyzed"),
        "deg": _value(raw_scores, "hit_in_deg"),
        "deg_identity": _value(raw_scores, "deg_identity"),
        "core_roary": conservation.get("roary") or _value(raw_scores, "core_roary"),
        "core_corecruncher": conservation.get("corecruncher") or _value(raw_scores, "core_corecruncher"),
        # build_metabolic_context returns None (not an empty dict) when the protein has no
        # GeneReactionLink rows at all -- distinguish that "no metabolic data loaded" case
        # from a real, computed "confirmed not a chokepoint" result. Both used to collapse
        # to the same "no" string here, which is exactly the missing-vs-negative confusion
        # the system prompt tells the model never to make -- except the ambiguity was baked
        # into the tool output itself, not something the model invented.
        "is_chokepoint": (
            "not loaded" if metabolic_context is None
            else ("yes" if metabolic.get("is_chokepoint") else "no")
        ),
        # Same cross-pipeline ambiguity as is_chokepoint: PTOOLS_betweenness_centrality is a
        # separate ScoreParamValue that can exist even when this protein has no
        # GeneReactionLink rows at all, so falling straight through to raw_scores here would
        # silently paper over "no metabolic data for this protein" with an unrelated number.
        "centrality": (
            "not loaded" if metabolic_context is None
            else (metabolic.get("centrality") or _value(raw_scores, "PTOOLS_betweenness_centrality"))
        ),
        "centrality_percentile": metabolic.get("centrality_percentile"),
        "metabolic_sentence": metabolic.get("summary_sentence") or "No metabolic context loaded for this protein.",
        "reactions": reaction_names,
        "pathways": pathway_names,
        "direct_ligands": binder_summary.get("direct_count", 0),
        "structural_ligands": binder_summary.get("structural_count", 0),
        "bioactive_ligands": binder_summary.get("bioactive_count", 0),
        "proposed_ligands": binder_summary.get("proposed_count", 0),
        "strengths": summary.get("strengths") or [],
        "risks": summary.get("risks") or [],
        "missing": summary.get("missing") or [],
    }


def format_target_audit(record):
    if record is None:
        return "Target evidence: protein not found in the current genome."

    lines = [
        f"{record['accession']} ({record['description']})",
        f"Verdict from loaded evidence: {record['verdict']}",
        f"Evidence-convergence score: {record['evidence_score']} / {record['evidence_max']} (internal overview heuristic, not an experimental measurement).",
    ]

    lines.extend(_section_items("Pocket / structure evidence", [
        ("FPocket druggability", record["fpocket"]),
        ("P2Rank probability", record["p2rank"]),
        ("Pocket-size outlier warning", record["pocket_outlier"]),
    ]))
    lines.extend(_section_items("Selectivity / off-target evidence", [
        ("Human off-target screen", record["human_offtarget"]),
        ("Best human identity", record["human_identity"]),
        ("Best human E-value", record["human_evalue"]),
        ("Gut microbiome screen", record["microbiome_offtarget"]),
        ("Gut microbiome hits", f"{record['microbiome_count']} / {record['microbiome_total']} screened genomes"),
    ]))
    lines.extend(_section_items("Essentiality / conservation", [
        ("Hit in DEG", record["deg"]),
        ("DEG identity", record["deg_identity"]),
        ("Roary core call", record["core_roary"]),
        ("CoreCruncher core call", record["core_corecruncher"]),
    ]))
    lines.extend(_section_items("Metabolic context", [
        ("Chokepoint reaction", record["is_chokepoint"]),
        ("Network centrality", record["centrality"]),
        ("Centrality percentile", record["centrality_percentile"] if record["centrality_percentile"] is not None else "not loaded"),
        ("Interpretation", record["metabolic_sentence"]),
        ("Reactions", ", ".join(record["reactions"]) if record["reactions"] else "not loaded"),
        ("Pathways", ", ".join(record["pathways"]) if record["pathways"] else "not assigned"),
    ]))
    lines.extend(_section_items("Ligand evidence", [
        ("Direct ligand records", record["direct_ligands"]),
        ("Structural ligand records", record["structural_ligands"]),
        ("Measured ChEMBL records", record["bioactive_ligands"]),
        ("Proposed ZINC/similarity records", record["proposed_ligands"]),
    ]))

    for title, key in (("Strengths", "strengths"), ("Risks", "risks"), ("Missing evidence", "missing")):
        items = record.get(key) or []
        if items:
            lines.append(f"{title}:")
            lines.extend(f"  - {item.get('label')}: {item.get('detail')}" for item in items)

    lines.append("Use only the fields above. If a field says 'not loaded', treat it as unavailable evidence, not as negative evidence.")
    return "\n".join(lines)


def format_target_comparison(records):
    records = [record for record in records if record is not None]
    if not records:
        return "No requested proteins were found in the current genome."

    header = (
        "Accession | Evidence score | Pocket | Human screen | Microbiome | DEG | "
        "Metabolism | Direct ligands | Main risks"
    )
    sep = "--- | ---: | --- | --- | --- | --- | --- | ---: | ---"
    rows = []
    for record in records:
        risks = "; ".join(item.get("label", "") for item in (record.get("risks") or [])[:3]) or "none flagged"
        metabolism = {
            "yes": "chokepoint",
            "no": "not chokepoint",
            "not loaded": "no metabolic data",
        }.get(record["is_chokepoint"], "no metabolic data")
        human_identity = record["human_identity"]
        human_label = (
            f"{record['human_offtarget']} ({human_identity}% identity)"
            if human_identity != "not loaded"
            else f"{record['human_offtarget']} (identity not loaded)"
        )
        rows.append(
            f"{record['accession']} | {record['evidence_score']}/{record['evidence_max']} | "
            f"FPocket {record['fpocket']}, P2Rank {record['p2rank']} | "
            f"{human_label} | "
            f"{record['microbiome_count']}/{record['microbiome_total']} | "
            f"{record['deg']} | {metabolism} | {record['direct_ligands']} | {risks}"
        )

    lines = [
        "Comparison table from loaded Target evidence:",
        header,
        sep,
        *rows,
        "",
        "Interpretation rules: prefer converging evidence, low human/microbiome off-target signal, solid pocket evidence, essentiality/conservation, and direct ligand evidence. Do not invent missing fields.",
    ]
    return "\n".join(lines)
