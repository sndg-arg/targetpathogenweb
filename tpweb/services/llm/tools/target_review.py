"""Agent tools for auditable target evidence and target-vs-target comparison."""
from __future__ import annotations

from ..agent import ToolEntry
from ..base import ToolDefinition
from tpweb.services.llm.tools.target_evidence import (
    build_target_evidence_record,
    format_target_audit,
    format_target_comparison,
)

AUDIT_TARGET_EVIDENCE = ToolDefinition(
    name="audit_target_evidence",
    description=(
        "Return an auditable evidence sheet for one protein in the current genome. "
        "Use this when the user asks where an assessment came from, asks for data sources, "
        "asks 'de donde sale', or wants a less opinionated evidence breakdown. The output "
        "explicitly marks missing/unloaded evidence."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "accession": {
                "type": "string",
                "description": "Protein accession/locus tag within the current genome. Omit it on a protein detail page.",
            },
        },
    },
)

COMPARE_TARGETS = ToolDefinition(
    name="compare_targets",
    description=(
        "Compare two to five protein targets in the current genome using loaded Target evidence: "
        "evidence-convergence score, pocket evidence, off-target/selectivity, essentiality, "
        "metabolic context, ligand support, and explicit risks. Use this whenever the user "
        "asks to compare proteins or decide which candidate is better."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "accessions": {
                "type": "array",
                "description": "Two to five protein accessions/locus tags.",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
            },
        },
        "required": ["accessions"],
    },
)


def build_audit_target_evidence_entry(assembly_name, default_accession=None):
    def run(input):
        accession = (input.get("accession") or default_accession or "").strip()
        if not accession:
            return "No accession was given, and there is no current protein page to default to."
        record = build_target_evidence_record(assembly_name, accession)
        if record is None:
            return f"No protein with accession '{accession}' was found in this genome."
        return format_target_audit(record)

    return ToolEntry(definition=AUDIT_TARGET_EVIDENCE, run=run)


def build_compare_targets_entry(assembly_name):
    def run(input):
        raw_accessions = input.get("accessions") or []
        accessions = []
        for accession in raw_accessions:
            accession = str(accession or "").strip()
            if accession and accession not in accessions:
                accessions.append(accession)
        if len(accessions) < 2:
            return "Give at least two protein accessions to compare."
        records = [build_target_evidence_record(assembly_name, accession) for accession in accessions[:5]]
        missing = [accessions[idx] for idx, record in enumerate(records) if record is None]
        text = format_target_comparison(records)
        if missing:
            text += "\nMissing requested accessions: " + ", ".join(missing)
        return text

    return ToolEntry(definition=COMPARE_TARGETS, run=run)
