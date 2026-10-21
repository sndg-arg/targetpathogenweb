"""Load InterPro's GO cross-references after validating the input sequences."""

import csv
import gzip
import hashlib
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


GO_ID = re.compile(r"(?<![A-Za-z0-9_])GO:\d{7}(?!\d)")


def collect_go(rows, expected):
    """expected maps locus -> (bioentry ID, sequence MD5, sequence length)."""
    annotations = defaultdict(set)
    for number, row in enumerate(rows, 1):
        if len(row) < 14:
            continue
        terms = set(GO_ID.findall(row[13]))
        if not terms:
            continue
        locus = row[0].strip()
        if locus not in expected:
            raise CommandError(f"Unknown protein at TSV row {number}: {locus}; nothing imported.")
        protein_id, checksum, length = expected[locus]
        try:
            reported_length = int(row[2])
        except ValueError as exc:
            raise CommandError(f"Invalid sequence length at TSV row {number}: {locus}") from exc
        if row[1].strip().lower() != checksum or reported_length != length:
            raise CommandError(
                f"Sequence checksum/length mismatch at TSV row {number}: {locus}; nothing imported."
            )
        annotations[protein_id].update(terms)
    return dict(annotations)


class Command(BaseCommand):
    help = "Load GO from a local InterPro TSV, validating MD5/length and preserving existing annotations."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--interpro-tsv", required=True)
        parser.add_argument(
            "--apply", action="store_true", help="Write GO links; default is validation only."
        )

    def handle(self, *args, **options):
        from django.db import transaction
        from bioseq.models.Biodatabase import Biodatabase
        from bioseq.models.Bioentry import Bioentry
        from bioseq.models.BioentryDbxref import BioentryDbxref
        from bioseq.models.Dbxref import Dbxref
        from bioseq.models.Ontology import Ontology
        from bioseq.models.Term import Term
        from bioseq.models.TermDbxref import TermDbxref

        database = Biodatabase.objects.filter(
            name=options["genome_name"] + Biodatabase.PROT_POSTFIX
        ).first()
        if database is None:
            raise CommandError("Genome proteome not found.")
        expected = {}
        for protein in Bioentry.objects.filter(biodatabase=database).select_related("seq"):
            sequence = str(protein.seq.seq).strip().upper()
            expected[protein.accession] = (
                protein.pk,
                hashlib.md5(sequence.encode("ascii")).hexdigest(),
                len(sequence),
            )
        if not expected:
            raise CommandError("The genome has no loaded proteins.")
        path = Path(options["interpro_tsv"])
        opener = gzip.open if path.suffix.lower() == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
                annotations = collect_go(csv.reader(handle, delimiter="\t"), expected)
        except OSError as exc:
            raise CommandError(f"Cannot read InterPro TSV: {exc}") from exc
        pairs = {(protein, term) for protein, terms in annotations.items() for term in terms}
        if not options["apply"] or not pairs:
            self.stdout.write(
                f"Validated GO: {len(annotations)}/{len(expected)} proteins; "
                f"{len(pairs)} distinct protein/GO pairs. No data changed."
            )
            return
        go_ids = {term for _, term in pairs}
        with transaction.atomic():
            ontology, _ = Ontology.objects.get_or_create(
                name=Ontology.GO, defaults={"definition": ""}
            )
            dbxrefs = {
                d.accession: d
                for d in Dbxref.objects.filter(dbname=Ontology.GO, accession__in=go_ids).order_by(
                    "pk"
                )
            }
            Dbxref.objects.bulk_create(
                [
                    Dbxref(dbname=Ontology.GO, accession=accession, version=0)
                    for accession in sorted(go_ids - dbxrefs.keys())
                ],
                batch_size=500,
                ignore_conflicts=True,
            )
            dbxrefs = {
                d.accession: d
                for d in Dbxref.objects.filter(dbname=Ontology.GO, accession__in=go_ids).order_by(
                    "pk"
                )
            }
            terms = {
                t.identifier: t
                for t in Term.objects.filter(ontology=ontology, identifier__in=go_ids).order_by(
                    "pk"
                )
            }
            Term.objects.bulk_create(
                [
                    Term(
                        ontology=ontology,
                        identifier=accession,
                        name=accession,
                        definition="",
                        version=0,
                        is_obsolete="N",
                    )
                    for accession in sorted(go_ids - terms.keys())
                ],
                batch_size=500,
                ignore_conflicts=True,
            )
            terms = {
                t.identifier: t
                for t in Term.objects.filter(ontology=ontology, identifier__in=go_ids).order_by(
                    "pk"
                )
            }
            dbxref_ids = [d.pk for d in dbxrefs.values()]
            existing_terms = set(
                TermDbxref.objects.filter(
                    term_id__in=[t.pk for t in terms.values()],
                    dbxref_id__in=dbxref_ids,
                ).values_list("term_id", "dbxref_id")
            )
            TermDbxref.objects.bulk_create(
                [
                    TermDbxref(term=terms[accession], dbxref=dbxrefs[accession], rank=0)
                    for accession in sorted(go_ids)
                    if (terms[accession].pk, dbxrefs[accession].pk) not in existing_terms
                ],
                batch_size=500,
                ignore_conflicts=True,
            )
            existing = set(
                BioentryDbxref.objects.filter(
                    bioentry__biodatabase=database,
                    dbxref_id__in=dbxref_ids,
                ).values_list("bioentry_id", "dbxref_id")
            )
            missing = [
                BioentryDbxref(bioentry_id=protein_id, dbxref=dbxrefs[accession], rank=0)
                for protein_id, accession in sorted(pairs)
                if (protein_id, dbxrefs[accession].pk) not in existing
            ]
            BioentryDbxref.objects.bulk_create(missing, batch_size=500, ignore_conflicts=True)
            wanted = {(protein_id, dbxrefs[accession].pk) for protein_id, accession in pairs}
            persisted = set(
                BioentryDbxref.objects.filter(
                    bioentry__biodatabase=database,
                    dbxref_id__in=dbxref_ids,
                ).values_list("bioentry_id", "dbxref_id")
            )
            if not wanted <= persisted:
                raise CommandError("GO link verification failed; the import was rolled back.")
        self.stdout.write(
            f"GO import complete: {len(annotations)}/{len(expected)} proteins in TSV; "
            f"{len(pairs)} distinct protein/GO pairs; {len(missing)} missing links submitted. "
            "Existing annotations preserved."
        )
