from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BioentryDbxref import BioentryDbxref
from tpweb.models.BioentryStructure import ExperimentalStructureXref
from tpweb.services.protein_annotations import annotation_dbnames


class Command(BaseCommand):
    help = (
        "Backfill curated UniProt mappings plus UniProt-derived EC, GO, and PDB "
        "metadata for genomes loaded from external result files."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--results-tsv", required=True, help="Curated results TSV with gene/uniprot columns.")
        parser.add_argument("--datadir", default="./data", help="TPW data directory.")
        parser.add_argument(
            "--dbname",
            default="UnipTr",
            choices=("UnipTr", "UnipSp"),
            help="Dbxref database name used for TSV-provided UniProt accessions.",
        )
        parser.add_argument(
            "--overwrite-mapping",
            action="store_true",
            help="Replace existing UniProt BioentryDbxref rows before importing TSV mappings.",
        )
        parser.add_argument(
            "--skip-mapping",
            action="store_true",
            help="Use an existing {genome}_unips.lst and do not import UniProt accessions from the TSV.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the TSV mapping import without writing rows or contacting UniProt.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        db = Biodatabase.objects.filter(name=proteome_name).first()
        if db is None:
            raise CommandError(f"Proteome '{proteome_name}' not found. Load the GBK first.")

        before = _annotation_counts(db)
        self.stdout.write("Before backfill")
        _write_counts(self, before)

        if not options["skip_mapping"]:
            call_command(
                "import_curated_uniprot",
                genome_name,
                results_tsv=options["results_tsv"],
                datadir=options["datadir"],
                dbname=options["dbname"],
                overwrite=options["overwrite_mapping"],
                dry_run=options["dry_run"],
            )
        elif options["dry_run"]:
            self.stdout.write("[dry-run] Existing UniProt list would be used; UniProt fetch is skipped.")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry-run complete. No UniProt API fetch was executed."))
            return

        call_command(
            "fetch_uniprot_annotations",
            genome_name,
            datadir=options["datadir"],
        )

        after = _annotation_counts(db)
        self.stdout.write("")
        self.stdout.write("After backfill")
        _write_counts(self, after)
        self.stdout.write(self.style.SUCCESS("Curated UniProt annotation backfill complete."))


def _annotation_counts(db):
    ec_dbnames = set(annotation_dbnames("ec"))
    go_dbnames = set(annotation_dbnames("go"))
    return {
        "uniprot": BioentryDbxref.objects.filter(
            bioentry__biodatabase=db,
            dbxref__dbname__in=("UnipSp", "UnipTr"),
        ).values("bioentry_id").distinct().count(),
        "ec": BioentryDbxref.objects.filter(
            bioentry__biodatabase=db,
            dbxref__dbname__in=ec_dbnames,
        ).values("bioentry_id").distinct().count(),
        "go": BioentryDbxref.objects.filter(
            bioentry__biodatabase=db,
            dbxref__dbname__in=go_dbnames,
        ).values("bioentry_id").distinct().count(),
        "pdb_xref_proteins": BioentryDbxref.objects.filter(
            bioentry__biodatabase=db,
            dbxref__dbname="PDB",
        ).values("bioentry_id").distinct().count(),
        "experimental_structure_xrefs": ExperimentalStructureXref.objects.filter(
            bioentry__biodatabase=db,
        ).count(),
    }


def _write_counts(command, counts):
    command.stdout.write(f"  UniProt mapped proteins: {counts['uniprot']}")
    command.stdout.write(f"  EC annotated proteins: {counts['ec']}")
    command.stdout.write(f"  GO annotated proteins: {counts['go']}")
    command.stdout.write(f"  Proteins with PDB xrefs: {counts['pdb_xref_proteins']}")
    command.stdout.write(f"  Experimental structure xrefs: {counts['experimental_structure_xrefs']}")
