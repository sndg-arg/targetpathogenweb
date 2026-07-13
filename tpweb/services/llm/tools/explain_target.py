"""Agent tool answering "why is this protein/target scored/ranked the way
it is", folding in FPocket/P2Rank pocket evidence, metabolic context
(chokepoint/centrality), off-target/conservation flags, and ligand
evidence -- everything the protein detail page's executive summary shows,
as one compact natural-language string for the model to paraphrase rather
than a raw dict it might invent details from.

Bound to a single genome per request via build_explain_target_entry's
closure -- the model only ever supplies an accession, never a genome.
"""
from __future__ import annotations

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from ..agent import ToolEntry
from ..base import ToolDefinition
from tpweb.services.assembly_workspace import score_single_protein
from tpweb.services.protein_summary import build_protein_executive_context

EXPLAIN_TARGET = ToolDefinition(
    name="explain_target",
    description=(
        "Explain whether a specific protein in the current genome looks like a promising "
        "drug target: its evidence-convergence score, predicted pocket druggability, "
        "metabolic context (chokepoint/centrality), off-target similarity, conservation, "
        "and ligand evidence. Use this when the user asks why a target is ranked the way it "
        "is, or asks for an assessment of a specific protein."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "accession": {
                "type": "string",
                "description": (
                    "Protein accession/locus tag within the current genome. If the user is "
                    "already viewing a specific protein's page, you may omit this."
                ),
            },
        },
    },
)


def _format_context(protein, score_row):
    context = build_protein_executive_context(protein)
    summary = context["target_summary"]

    lines = [f"{protein.accession} ({protein.description or 'no description'})"]
    if score_row is not None:
        lines.append(
            f"Evidence-convergence score: {round(score_row['score'], 1)} "
            f"(FPocket druggability {score_row['fpocket']:.2f})"
        )
    lines.append(f"Verdict: {summary['verdict']}")

    if summary["strengths"]:
        lines.append("Strengths:")
        lines.extend(f"  - {item['label']}: {item['detail']}" for item in summary["strengths"])
    if summary["risks"]:
        lines.append("Risks:")
        lines.extend(f"  - {item['label']}: {item['detail']}" for item in summary["risks"])
    if summary["missing"]:
        lines.append("Missing evidence:")
        lines.extend(f"  - {item['label']}: {item['detail']}" for item in summary["missing"])

    metabolic_context = context.get("metabolic_context")
    if metabolic_context and metabolic_context.get("summary_sentence"):
        lines.append(f"Metabolic context: {metabolic_context['summary_sentence']}")

    return "\n".join(lines)


def build_explain_target_entry(assembly_name, default_accession=None):
    def run(input):
        accession = (input.get("accession") or default_accession or "").strip()
        if not accession:
            return "No accession was given, and there is no protein currently in view to default to."

        protein = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
            accession=accession,
        ).first()
        if protein is None:
            return f"No protein with accession '{accession}' was found in this genome."

        score_row = score_single_protein(assembly_name, accession)
        return _format_context(protein, score_row)

    return ToolEntry(definition=EXPLAIN_TARGET, run=run)
