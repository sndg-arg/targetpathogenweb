"""Recover EC annotations from the genome's sequence-verified GenBank CDS records."""

import gzip
import re
from collections import defaultdict
from pathlib import Path

from Bio import SeqIO
from django.core.management.base import BaseCommand, CommandError


EC_NUMBER = re.compile(r"[1-7]\.(?:\d+|-)\.(?:\d+|-)\.(?:\d+|-)")


def collect_ec(records, expected):
    annotations = defaultdict(set)
    for record in records:
        for feature in record.features:
            qualifiers = feature.qualifiers
            if feature.type != "CDS" or not qualifiers.get("EC_number"):
                continue
            locus = qualifiers.get("locus_tag", [""])[0].strip()
            translation = qualifiers.get("translation", [""])[0].strip().upper().rstrip("*")
            if locus not in expected or not translation or translation != expected[locus][1]:
                raise CommandError(f"GenBank locus/sequence mismatch: {locus}; nothing imported.")
            for raw in qualifiers["EC_number"]:
                accession = raw.strip()
                if not EC_NUMBER.fullmatch(accession):
                    raise CommandError(f"Invalid EC number for {locus}: {accession}")
                annotations[expected[locus][0]].add(accession)
    return dict(annotations)


class Command(BaseCommand):
    help = (
        "Add GenBank EC links after exact locus/sequence validation; preserve existing annotations."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--genbank", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        from django.db import transaction
        from bioseq.models.Biodatabase import Biodatabase
        from bioseq.models.Bioentry import Bioentry
        from bioseq.models.BioentryDbxref import BioentryDbxref
        from bioseq.models.Dbxref import Dbxref
        from bioseq.models.Ontology import Ontology
        from bioseq.models.Term import Term
        from bioseq.models.TermDbxref import TermDbxref

        expected = {}
        for protein in Bioentry.objects.filter(
            biodatabase__name=options["genome_name"] + Biodatabase.PROT_POSTFIX
        ).select_related("seq"):
            if protein.accession in expected:
                raise CommandError(f"Ambiguous protein locus: {protein.accession}")
            expected[protein.accession] = (
                protein.pk,
                str(protein.seq.seq).strip().upper().rstrip("*"),
            )
        if not expected:
            raise CommandError("Genome has no loaded proteins.")
        path = Path(options["genbank"])
        opener = gzip.open if path.suffix.lower() == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8") as handle:
                annotations = collect_ec(SeqIO.parse(handle, "genbank"), expected)
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read GenBank: {exc}") from exc
        pairs = sum(len(values) for values in annotations.values())
        self.stdout.write(
            f"Validated GenBank EC: {len(annotations)}/{len(expected)} proteins; {pairs} pairs."
        )
        if not options["apply"] or not pairs:
            self.stdout.write("No data changed.")
            return
        created = 0
        with transaction.atomic():
            ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.EC, defaults={"definition": ""}
            )
            terms, xrefs = {}, {}
            for index, (protein_id, accessions) in enumerate(sorted(annotations.items()), 1):
                for accession in sorted(accessions):
                    if accession not in xrefs:
                        xrefs[accession], _ = Dbxref.objects.get_or_create(
                            dbname=Ontology.EC, accession=accession, defaults={"version": 0}
                        )
                        terms[accession], _ = Term.objects.get_or_create(
                            ontology=ontology,
                            identifier=accession,
                            defaults={
                                "name": accession,
                                "definition": "",
                                "version": 0,
                                "is_obsolete": "N",
                            },
                        )
                        TermDbxref.objects.get_or_create(
                            term=terms[accession], dbxref=xrefs[accession], defaults={"rank": 0}
                        )
                    _, added = BioentryDbxref.objects.get_or_create(
                        bioentry_id=protein_id, dbxref=xrefs[accession], defaults={"rank": 0}
                    )
                    created += int(added)
                if index % 200 == 0:
                    self.stdout.write(
                        f"EC processed: {index}/{len(annotations)} proteins (pending commit)"
                    )
        self.stdout.write(
            f"GenBank EC import complete: {len(annotations)} proteins; {created} new links. Existing annotations preserved."
        )
