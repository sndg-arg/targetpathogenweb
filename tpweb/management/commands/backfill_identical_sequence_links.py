from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models import IdenticalSequenceMember


def _validate_group_sequences(group_sequences, strain_label):
    mismatches = [
        group
        for group, sequences in group_sequences.items()
        if len(sequences) > 1 or "" in sequences
    ]
    if mismatches:
        raise CommandError(
            f"Sequence mismatch in {len(mismatches)} groups, e.g. {mismatches[:5]}; no links saved for {strain_label}"
        )


class Command(BaseCommand):
    help = (
        "Resolves IdenticalSequenceMember.bioentry for one strain, once that "
        "strain's genome has finished loading -- matches locus_tag against "
        "Bioentry.accession within the genome's _prots Biodatabase. Re-running "
        "is safe: already-linked members are left untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "genome_name", nargs="?", help="Internal accession, e.g. public__GCA_030061715.1"
        )
        parser.add_argument(
            "strain_label",
            nargs="?",
            help="Label used for this genome in the imported TSV, e.g. ST11_VA569.",
        )
        parser.add_argument(
            "--all-loaded",
            action="store_true",
            help="Resolve every unambiguous loaded strain in the mapping.",
        )

    def handle(self, *args, **options):
        if options["all_loaded"]:
            plans = []
            labels = IdenticalSequenceMember.objects.values_list(
                "strain_label", flat=True
            ).distinct()
            for label in labels:
                loci = IdenticalSequenceMember.objects.filter(strain_label=label).values_list(
                    "locus_tag", flat=True
                )
                genomes = list(
                    Bioentry.objects.filter(
                        accession__in=loci,
                        biodatabase__name__endswith=Biodatabase.PROT_POSTFIX,
                    )
                    .order_by()
                    .values_list("biodatabase__name", flat=True)
                    .distinct()
                )
                if len(genomes) > 1:
                    raise CommandError(
                        f"Ambiguous genomes for {label}: {genomes}; specify genome and strain explicitly"
                    )
                if genomes:
                    plans.append((genomes[0].removesuffix(Biodatabase.PROT_POSTFIX), label))
                else:
                    self.stdout.write(f"Strain {label}: genome not loaded yet")
            for genome, label in plans:
                call_command("backfill_identical_sequence_links", genome, label, stdout=self.stdout)
            return
        if not options["genome_name"] or not options["strain_label"]:
            raise CommandError("Specify genome_name and strain_label, or --all-loaded")
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

        accession_to_bioentry = {
            p.accession: p
            for p in Bioentry.objects.filter(biodatabase=biodatabase).select_related("seq")
        }
        unresolved = list(unresolved)
        group_sequences = {}
        for member in IdenticalSequenceMember.objects.filter(
            group_id__in=[m.group_id for m in unresolved],
            bioentry__isnull=False,
        ).select_related("bioentry__seq"):
            sequence = str(member.bioentry.seq.seq).strip().upper().rstrip("*")
            group_sequences.setdefault(member.group_id, set()).add(sequence)
        candidates = []
        for member in unresolved:
            protein = accession_to_bioentry.get(member.locus_tag)
            if protein is None:
                continue
            sequence = str(protein.seq.seq).strip().upper().rstrip("*")
            if not sequence:
                raise CommandError(f"Empty sequence for {member.locus_tag}")
            group_sequences.setdefault(member.group_id, set()).add(sequence)
            candidates.append((member, protein.pk))
        _validate_group_sequences(group_sequences, strain_label)

        linked = 0
        with transaction.atomic():
            for member, bioentry_id in candidates:
                member.bioentry_id = bioentry_id
                member.save(update_fields=["bioentry"])
                linked += 1

        self.stdout.write(
            f"Linked {linked}/{total} '{strain_label}' members to {prots_name} proteins."
        )
