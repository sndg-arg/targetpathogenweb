from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models import IdenticalSequenceMember


class Command(BaseCommand):
    help = (
        "Resolves IdenticalSequenceMember.bioentry for one strain, once that "
        "strain's genome has finished loading -- matches locus_tag against "
        "Bioentry.accession within the genome's _prots Biodatabase. Re-running "
        "is safe: already-linked members are left untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name", help="Internal accession, e.g. public__GCA_030061715.1")
        parser.add_argument(
            "strain_label",
            help="Label used for this genome in the imported TSV, e.g. ST11_VA569.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        strain_label = options["strain_label"].strip()

        prots_name = genome_name + Biodatabase.PROT_POSTFIX
        biodatabase = Biodatabase.objects.filter(name=prots_name).first()
        if biodatabase is None:
            raise CommandError(f"No Biodatabase named '{prots_name}' -- is the genome loaded?")

        unresolved = IdenticalSequenceMember.objects.filter(
            strain_label=strain_label, bioentry__isnull=True
        )
        total = unresolved.count()
        if total == 0:
            self.stdout.write(f"Nothing to backfill for strain '{strain_label}'.")
            return

        accession_to_bioentry = dict(
            Bioentry.objects.filter(biodatabase=biodatabase).values_list("accession", "bioentry_id")
        )

        linked = 0
        for member in unresolved:
            bioentry_id = accession_to_bioentry.get(member.locus_tag)
            if bioentry_id is None:
                continue
            member.bioentry_id = bioentry_id
            member.save(update_fields=["bioentry"])
            linked += 1

        self.stdout.write(
            f"Linked {linked}/{total} '{strain_label}' members to {prots_name} proteins."
        )
