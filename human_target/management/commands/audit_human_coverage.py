"""Read-only Human Targets inventory. Counts do not prove source completeness."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from human_target.models.HumanProteinPathway import HumanProteinPathway
from human_target.services.human_coverage_audit import (
    compare_pdb_pairs,
    expected_pdb_pairs,
    reference_inventory,
)
from human_target.services.human_targets import human_proteins_queryset
from tpweb.models.Binders import Binders
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref


class Command(BaseCommand):
    help = "Audit human coverage without writes or downloads; print a JSON report."

    def add_arguments(self, parser):
        parser.add_argument("--accession", action="append", default=[])
        parser.add_argument(
            "--reference-dir", help="Optional target-human-web/new_data pilot folder"
        )
        parser.add_argument("--sample-size", type=int, default=20)

    def handle(self, *args, **options):
        if options["sample_size"] < 0:
            raise CommandError("--sample-size must be nonnegative")
        reference = None
        if options["reference_dir"]:
            if not Path(options["reference_dir"]).is_dir():
                raise CommandError("Reference directory does not exist")
            try:
                reference = reference_inventory(options["reference_dir"])
            except (OSError, ValueError) as exc:
                raise CommandError(f"Could not read reference data: {exc}") from exc
            if not reference:
                raise CommandError("No <accession>/<accession>_full.json reference files found")

        proteins = human_proteins_queryset().order_by()
        if options["accession"]:
            proteins = proteins.filter(uniprot_accession__in=options["accession"])
        accessions = set(proteins.values_list("uniprot_accession", flat=True))
        if not accessions:
            raise CommandError("No matching human proteins")
        ids = proteins.values("bioentry_id")
        expected = expected_pdb_pairs(
            proteins.values_list("uniprot_accession", "cross_references_raw").iterator(
                chunk_size=500
            )
        )
        registered = {
            (accession, code.strip().upper())
            for accession, code in ExperimentalStructureXref.objects.filter(bioentry_id__in=ids)
            .order_by()
            .values_list("bioentry__human_protein__uniprot_accession", "pdb_id")
            .iterator(chunk_size=2000)
        }
        structures = BioentryStructure.objects.filter(bioentry_id__in=ids, pdb__deprecated=False)
        deprecated_linked = {
            (accession, code.strip().upper())
            for accession, code in BioentryStructure.objects.filter(
                bioentry_id__in=ids, pdb__experiment="EX", pdb__deprecated=True
            )
            .order_by()
            .values_list("bioentry__human_protein__uniprot_accession", "pdb__code")
            .iterator(chunk_size=2000)
        }
        linked = {
            (accession, code.strip().upper())
            for accession, code in structures.filter(pdb__experiment="EX")
            .order_by()
            .values_list("bioentry__human_protein__uniprot_accession", "pdb__code")
            .iterator(chunk_size=2000)
        }
        # Binders.locustag targets Bioentry.accession, not its numeric primary key.
        binders = Binders.objects.filter(locustag__human_protein__in=proteins)
        pathways = HumanProteinPathway.objects.filter(human_protein__in=proteins)
        report = {
            "generated_at": timezone.now().isoformat(),
            "scope": {
                "proteins": len(accessions),
                "reviewed": proteins.filter(is_reviewed=True).count(),
                "unreviewed": proteins.filter(is_reviewed=False).count(),
                "requested_accessions_not_found": sorted(set(options["accession"]) - accessions),
            },
            "experimental": compare_pdb_pairs(
                expected, registered, linked, options["sample_size"], deprecated_linked
            ),
            "structures": list(
                structures.order_by()
                .values("pdb__experiment")
                .annotate(
                    proteins=Count("bioentry_id", distinct=True),
                    distinct_models=Count("pdb_id", distinct=True),
                )
            ),
            "coverage": {
                "with_sequence": proteins.exclude(sequence="").count(),
                "with_expression_rows": proteins.exclude(expression_json=[]).count(),
                "with_disease_comments": proteins.exclude(disease_comments=[]).count(),
                "with_pathways": pathways.values("human_protein_id").distinct().count(),
                "distinct_pathways": pathways.values("pathway_id").distinct().count(),
                "with_ligands": binders.values("locustag_id").distinct().count(),
                "without_summary": proteins.filter(summary_updated_at__isnull=True).count(),
            },
            "ligands": list(
                binders.order_by()
                .values("source", "is_direct")
                .annotate(rows=Count("pk"), proteins=Count("locustag_id", distinct=True))
            ),
            "limitations": [
                "Database inventory only; structure file integrity and atom completeness are not checked.",
                "Missing data cannot distinguish not-run, failed, and unavailable-at-source without job history.",
                "Read-only queries are not a single snapshot; run after loaders finish for stable totals.",
                "Ligand counts reflect import filters and limits, not the full upstream results.",
            ],
        }
        if reference is not None:
            sequences = dict(
                proteins.filter(uniprot_accession__in=reference).values_list(
                    "uniprot_accession", "sequence"
                )
            )
            for accession, data in reference.items():
                seq = data.pop("sequence")
                data["present_in_database_scope"] = accession in accessions
                data["sequence_matches"] = (
                    sequences[accession] == seq if accession in sequences and seq else None
                )
                data["pdb_comparison"] = compare_pdb_pairs(
                    {(accession, code) for code in data["pdb_ids"]},
                    registered,
                    linked,
                    options["sample_size"],
                )
                data["pdb_comparison"].pop("extra_registered_pairs")
            report["reference_pilot"] = reference
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))
