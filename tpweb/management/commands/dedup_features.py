from django.core.management.base import BaseCommand

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry


def _location_key(feature):
    return tuple(sorted(
        (loc.start_pos, loc.end_pos, loc.strand)
        for loc in feature.locations.all()
    ))


def _dedup_genome(db, fix=False, verbose=False):
    total_deleted = 0
    affected_proteins = 0

    for entry in Bioentry.objects.filter(biodatabase=db).iterator(chunk_size=200):
        features = list(
            entry.features.prefetch_related("locations").order_by("seqfeature_id")
        )
        seen = {}
        to_delete = []

        for f in features:
            key = (f.type_term_id, f.source_term_id, _location_key(f))
            if key in seen:
                to_delete.append(f.seqfeature_id)
            else:
                seen[key] = f.seqfeature_id

        if to_delete:
            affected_proteins += 1
            total_deleted += len(to_delete)
            if verbose:
                print(f"  {entry.accession}: {len(to_delete)} duplicates")
            if fix:
                entry.features.filter(seqfeature_id__in=to_delete).delete()

    return affected_proteins, total_deleted


class Command(BaseCommand):
    help = "Report and optionally remove duplicate SeqFeature rows loaded by repeated load_interpro runs."

    def add_arguments(self, parser):
        parser.add_argument(
            "genome_names",
            nargs="*",
            help="Internal genome accession(s) (e.g. public__NC_002516.2). Omit to check all genomes.",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            default=False,
            help="Actually delete the duplicate features. Without this flag the command only reports.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            default=False,
            help="Print per-protein detail.",
        )

    def handle(self, *args, **options):
        fix = options["fix"]
        verbose = options["verbose"]
        genome_names = options["genome_names"]

        if genome_names:
            dbs = list(Biodatabase.objects.filter(name__in=genome_names))
            missing = set(genome_names) - {db.name for db in dbs}
            if missing:
                self.stderr.write(f"Not found: {', '.join(missing)}")
        else:
            dbs = list(Biodatabase.objects.filter(name__endswith="_prots"))

        if not fix:
            self.stdout.write(self.style.WARNING("Dry-run mode — pass --fix to delete duplicates.\n"))

        grand_proteins = 0
        grand_deleted = 0

        for db in dbs:
            affected, deleted = _dedup_genome(db, fix=fix, verbose=verbose)
            grand_proteins += affected
            grand_deleted += deleted
            status = "fixed" if fix else "would fix"
            if affected:
                self.stdout.write(
                    f"{db.name}: {affected} proteins affected, {deleted} duplicate features {status}"
                )
            else:
                self.stdout.write(f"{db.name}: clean")

        self.stdout.write("")
        action = "Deleted" if fix else "Would delete"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {grand_deleted} duplicate features across {grand_proteins} proteins."
            )
        )
