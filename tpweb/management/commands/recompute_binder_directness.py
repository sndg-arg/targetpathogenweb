from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BioentryDbxref import BioentryDbxref
from tpweb.models.Binders import Binders


DIRECT_SOURCES = (Binders.SOURCE_PDB, Binders.SOURCE_CHEMBL)


class Command(BaseCommand):
    help = (
        "Recompute Binders.is_direct for PDB/ChEMBL rows using the current "
        "protein UniProt mappings. Use this after curated UniProt backfills."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Audit mismatches without writing updates.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Bulk update batch size.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        db = Biodatabase.objects.filter(name=proteome_name).first()
        if db is None:
            raise CommandError(f"Proteome '{proteome_name}' not found.")

        protein_uniprots = _protein_uniprot_map(db)
        qs = Binders.objects.filter(
            locustag__biodatabase=db,
            source__in=DIRECT_SOURCES,
        ).only("id", "source", "locustag_id", "uniprot", "is_direct")

        before = _source_counts(qs)
        self.stdout.write("Before")
        _write_source_counts(self, before)

        scanned = 0
        expected_direct = 0
        expected_homolog = 0
        missing_uniprot = 0
        missing_mapping = 0
        mismatches = 0
        updates = []
        batch_size = options["batch_size"]

        for binder in qs.iterator(chunk_size=batch_size):
            scanned += 1
            binder_uniprot = (binder.uniprot or "").strip()
            mapped_uniprots = protein_uniprots.get(binder.locustag_id, frozenset())
            if not binder_uniprot:
                missing_uniprot += 1
            if not mapped_uniprots:
                missing_mapping += 1

            should_be_direct = bool(binder_uniprot and binder_uniprot in mapped_uniprots)
            if should_be_direct:
                expected_direct += 1
            else:
                expected_homolog += 1

            if binder.is_direct != should_be_direct:
                mismatches += 1
                binder.is_direct = should_be_direct
                updates.append(binder)
                if len(updates) >= batch_size and not options["dry_run"]:
                    _bulk_update(updates)
                    updates.clear()

        if updates and not options["dry_run"]:
            _bulk_update(updates)

        self.stdout.write("")
        self.stdout.write("Audit")
        self.stdout.write(f"  scanned PDB/ChEMBL binders: {scanned}")
        self.stdout.write(f"  expected direct: {expected_direct}")
        self.stdout.write(f"  expected via homolog: {expected_homolog}")
        self.stdout.write(f"  rows without binder UniProt: {missing_uniprot}")
        self.stdout.write(f"  rows whose protein has no UniProt mapping: {missing_mapping}")
        self.stdout.write(f"  mismatched is_direct rows: {mismatches}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("(dry-run: no rows were updated)"))
            return

        after = _source_counts(qs)
        self.stdout.write("")
        self.stdout.write("After")
        _write_source_counts(self, after)
        self.stdout.write(self.style.SUCCESS(f"Updated {mismatches} binder directness flags."))


def _protein_uniprot_map(db):
    mapping = {}
    qs = BioentryDbxref.objects.filter(
        bioentry__biodatabase=db,
        dbxref__dbname__in=("UnipSp", "UnipTr"),
    ).values("bioentry__accession", "dbxref__accession")
    for row in qs:
        protein_accession = row["bioentry__accession"]
        uniprot_accession = (row["dbxref__accession"] or "").strip()
        if uniprot_accession:
            mapping.setdefault(protein_accession, set()).add(uniprot_accession)
    return {key: frozenset(values) for key, values in mapping.items()}


def _source_counts(qs):
    rows = (
        qs.values("source", "is_direct")
        .annotate(n=Count("id"))
        .order_by("source", "is_direct")
    )
    result = {
        Binders.SOURCE_PDB: {True: 0, False: 0},
        Binders.SOURCE_CHEMBL: {True: 0, False: 0},
    }
    for row in rows:
        result[row["source"]][row["is_direct"]] = row["n"]
    return result


def _write_source_counts(command, counts):
    for source in DIRECT_SOURCES:
        command.stdout.write(
            f"  {source}: direct={counts[source][True]} via_homolog={counts[source][False]}"
        )


def _bulk_update(rows):
    with transaction.atomic():
        Binders.objects.bulk_update(rows, ["is_direct"])
