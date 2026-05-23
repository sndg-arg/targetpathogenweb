import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry


class Command(BaseCommand):
    help = (
        "Dump all proteins of a genome to a single FASTA file. "
        "Headers are Bioentry.accession (so downstream tools like LigQ_2 use it as qseqid)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "biodatabase_name",
            help="Biodatabase name including the _prots postfix (e.g. public__NZ_AP023069.1_prots).",
        )
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="Output FASTA path. Default: stdout.",
        )
        parser.add_argument(
            "--line-width",
            type=int,
            default=80,
            help="Wrap sequence lines at N characters (default 80).",
        )

    def handle(self, *args, **options):
        biodb_name = options["biodatabase_name"]
        try:
            biodb = Biodatabase.objects.get(name=biodb_name)
        except Biodatabase.DoesNotExist:
            raise CommandError(f"Biodatabase '{biodb_name}' not found.")

        qs = (
            Bioentry.objects.filter(biodatabase=biodb)
            .select_related("seq")
            .order_by("accession")
        )
        total = qs.count()
        if total == 0:
            raise CommandError(f"Biodatabase '{biodb_name}' has no proteins loaded.")

        out_path = options["output"]
        out_fh = open(out_path, "w") if out_path else sys.stdout
        line_width = options["line_width"]

        written = 0
        skipped_no_seq = 0
        try:
            for be in qs.iterator():
                seq_obj = getattr(be, "seq", None)
                seq = getattr(seq_obj, "seq", None) if seq_obj else None
                if not seq:
                    skipped_no_seq += 1
                    continue
                out_fh.write(f">{be.accession}\n")
                for i in range(0, len(seq), line_width):
                    out_fh.write(seq[i : i + line_width] + "\n")
                written += 1
        finally:
            if out_path:
                out_fh.close()

        target = out_path if out_path else "stdout"
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {written}/{total} proteins to {target}"
                + (f" (skipped {skipped_no_seq} with no sequence)" if skipped_no_seq else "")
            )
        )
