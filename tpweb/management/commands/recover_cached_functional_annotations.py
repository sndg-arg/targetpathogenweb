"""Reuse exact-sequence UniProt responses already downloaded for PDB recovery."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def matching_entries(paths, sequences):
    seen, matches = set(), []
    for path in paths:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError(f"Unexpected cache format: {Path(path).name}")
        for raw in entries:
            accession = raw.get("primaryAccession")
            if (
                not accession
                or raw.get("inactiveReason")
                or not raw.get("entryType", "").startswith("UniProtKB")
            ):
                continue
            sequence = str(raw.get("sequence", {}).get("value", "")).strip().upper().rstrip("*")
            key = (accession, sequence)
            if sequence and sequence in sequences and key not in seen:
                seen.add(key)
                matches.append(raw)
    return matches


class Command(BaseCommand):
    help = "Recover EC/GO from locally cached exact-sequence UniProt results, without network requests."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--datadir", default="/app/targetpathogenweb/data")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        from collections import defaultdict
        from django.db import transaction
        from bioseq.models.Biodatabase import Biodatabase
        from bioseq.models.Bioentry import Bioentry
        from bioseq.models.Ontology import Ontology
        from tpweb.services.structure_files import compute_folder_path
        from tpweb.services.functional_annotations import (
            _parse_uniprot_response,
            persist_ec_go_annotations,
        )

        genome = options["genome_name"]
        cache = Path(compute_folder_path(options["datadir"], genome)) / "pdb_sequence_recovery"
        if not cache.is_dir():
            self.stdout.write("No cached PDB-sequence UniProt responses found; nothing changed.")
            return
        proteins = defaultdict(list)
        for protein in Bioentry.objects.filter(
            biodatabase__name=genome + Biodatabase.PROT_POSTFIX,
        ).select_related("seq"):
            sequence = str(protein.seq.seq).strip().upper().rstrip("*")
            if sequence:
                proteins[sequence].append(protein)
        if not proteins:
            raise CommandError("Genome has no loaded protein sequences.")
        try:
            raw = matching_entries(sorted(cache.glob("*.json")), proteins)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        entries = _parse_uniprot_response({"results": raw})
        if not options["apply"] or not entries:
            self.stdout.write(
                f"Cached UniProt: {len(entries)} exact matching entries; no data changed."
            )
            return
        ec_created = go_created = 0
        annotated = set()
        with transaction.atomic():
            ec_ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.EC, defaults={"definition": ""}
            )
            go_ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.GO, defaults={"definition": ""}
            )
            for entry in entries:
                sequence = str(entry["sequence"]).strip().upper().rstrip("*")
                for protein in proteins[sequence]:
                    ec_created += persist_ec_go_annotations(
                        protein, entry["ec_numbers"], "ec", ec_ontology
                    )
                    go_created += persist_ec_go_annotations(
                        protein, entry["go_terms"], Ontology.GO, go_ontology
                    )
                    if entry["ec_numbers"] or entry["go_terms"]:
                        annotated.add(protein.pk)
        self.stdout.write(
            f"Cached UniProt annotations: {len(annotated)} proteins; EC +{ec_created}, GO +{go_created}. Existing annotations preserved."
        )
