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

from ..agent import ToolEntry
from ..base import ToolDefinition
from tpweb.services.llm.tools.target_evidence import (
    build_target_evidence_record,
    format_target_audit,
    get_protein_for_accession,
)

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
    # Kept for backwards compatibility with earlier tests/imports. New code uses
    # the shared audit formatter so every target-assessment tool cites the same
    # underlying evidence fields.
    record = build_target_evidence_record(
        protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0],
        protein.accession,
    )
    return format_target_audit(record)


def build_explain_target_entry(assembly_name, default_accession=None):
    def run(input):
        accession = (input.get("accession") or default_accession or "").strip()
        if not accession:
            return "No accession was given, and there is no protein currently in view to default to."

        protein = get_protein_for_accession(assembly_name, accession)
        if protein is None:
            return f"No protein with accession '{accession}' was found in this genome."

        return format_target_audit(build_target_evidence_record(assembly_name, accession))

    return ToolEntry(definition=EXPLAIN_TARGET, run=run)
