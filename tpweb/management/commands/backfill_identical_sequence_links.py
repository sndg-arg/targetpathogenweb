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


def _sequence_group_index(rows):
    groups = {}
    for group_id, sequence in rows:
        groups.setdefault(group_id, set()).add(str(sequence).strip().upper().rstrip("*"))
    result = {}
    for group_id, sequences in groups.items():
        if len(sequences) == 1 and "" not in sequences:
            result.setdefault(next(iter(sequences)), set()).add(group_id)
    return result


def _link_new_strain_sequences(biodatabase, strain_label):
    """New occurrences may join table-defined groups, never create new groups."""
    from tpweb.services.shared_sequence_evidence import CURATED_STRAINS

    # The three original strains follow Sol's explicit rows, including '-'.
    if strain_label in {*CURATED_STRAINS, "ST11_VA569"}:
        return 0
    curated_groups = IdenticalSequenceMember.objects.filter(
        strain_label__in=CURATED_STRAINS,
        bioentry__isnull=False,
    ).values("group_id")
    members = IdenticalSequenceMember.objects.filter(
        group_id__in=curated_groups,
        bioentry__isnull=False,
    ).select_related("bioentry__seq")
    index = _sequence_group_index((m.group_id, m.bioentry.seq.seq) for m in members)
    linked = 0
    with transaction.atomic():
        for protein in Bioentry.objects.filter(biodatabase=biodatabase).select_related("seq"):
            groups = index.get(str(protein.seq.seq).strip().upper().rstrip("*"), set())
            if len(groups) != 1:
                continue
            group_id = next(iter(groups))
            member, created = IdenticalSequenceMember.objects.get_or_create(
                strain_label=strain_label,
                locus_tag=protein.accession,
                defaults={"group_id": group_id, "bioentry": protein},
            )
            if member.group_id != group_id or member.bioentry_id not in {None, protein.pk}:
                raise CommandError(f"Existing identity member conflicts with {protein.accession}")
            if member.bioentry_id is None:
                member.bioentry = protein
                member.save(update_fields=["bioentry"])
                linked += 1
            elif created:
                linked += 1
        linked += _group_with_ungrouped_curated(biodatabase, strain_label)
    return linked


def _normalized(sequence):
    return str(sequence or "").strip().upper().rstrip("*")


def _group_with_ungrouped_curated(biodatabase, strain_label):
    """A curated protein that Sol's table left out of every group (no copy in
    the other original strains) can still have an identical copy in a new
    strain: start a group for the pair, matched by exact sequence."""
    from tpweb.models import IdenticalSequenceGroup
    from tpweb.services.shared_sequence_evidence import CURATED_STRAINS

    curated_labels = {}
    for database_id, label in (
        IdenticalSequenceMember.objects.filter(
            strain_label__in=CURATED_STRAINS, bioentry__isnull=False
        )
        .order_by()
        .values_list("bioentry__biodatabase_id", "strain_label")
        .distinct()
    ):
        curated_labels.setdefault(database_id, set()).add(label)
    curated_labels = {db: labels.pop() for db, labels in curated_labels.items() if len(labels) == 1}
    curated_labels.pop(biodatabase.pk, None)
    if not curated_labels:
        return 0
    taken = set(IdenticalSequenceMember.objects.values_list("strain_label", "locus_tag"))
    ungrouped = {}
    for pk, accession, database_id, sequence in (
        Bioentry.objects.filter(biodatabase_id__in=curated_labels)
        .exclude(identical_sequence_memberships__isnull=False)
        .values_list("pk", "accession", "biodatabase_id", "seq__seq")
    ):
        sequence = _normalized(sequence)
        if sequence and (curated_labels[database_id], accession) not in taken:
            ungrouped.setdefault(sequence, []).append((pk, accession, curated_labels[database_id]))
    linked = 0
    groups = {}
    for protein in (
        Bioentry.objects.filter(biodatabase=biodatabase)
        .exclude(identical_sequence_memberships__isnull=False)
        .select_related("seq")
    ):
        sequence = _normalized(protein.seq.seq)
        if not sequence or (strain_label, protein.accession) in taken:
            continue
        if sequence not in groups:
            curated = ungrouped.get(sequence)
            if not curated:
                continue
            group = IdenticalSequenceGroup.objects.create(source_note="exact sequence match")
            IdenticalSequenceMember.objects.bulk_create(
                IdenticalSequenceMember(
                    group=group, strain_label=label, locus_tag=accession, bioentry_id=pk
                )
                for pk, accession, label in curated
            )
            groups[sequence] = group
        IdenticalSequenceMember.objects.create(
            group=groups[sequence],
            strain_label=strain_label,
            locus_tag=protein.accession,
            bioentry=protein,
        )
        taken.add((strain_label, protein.accession))
        linked += 1
    return linked


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
        parser.add_argument(
            "--match-sequences",
            action="store_true",
            help="Link a new strain to existing table groups by exact sequence.",
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
        if options["genome_name"] and not options["strain_label"]:
            loci = Bioentry.objects.filter(
                biodatabase__name=options["genome_name"] + Biodatabase.PROT_POSTFIX,
            ).values("accession")
            labels = list(
                IdenticalSequenceMember.objects.filter(locus_tag__in=loci)
                .order_by()
                .values_list("strain_label", flat=True)
                .distinct()
            )
            if len(labels) > 1:
                raise CommandError(f"Multiple strain labels for this genome: {labels}")
            if labels:
                options["strain_label"] = labels[0]
            elif options["match_sequences"]:
                options["strain_label"] = options["genome_name"]
            else:
                self.stdout.write("No table members for this genome.")
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
            if options["match_sequences"]:
                linked = _link_new_strain_sequences(biodatabase, strain_label)
                self.stdout.write(f"Linked {linked} new exact-sequence matches for {strain_label}.")
                return
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
        if options["match_sequences"]:
            linked = _link_new_strain_sequences(biodatabase, strain_label)
            self.stdout.write(f"Linked {linked} additional exact-sequence matches.")
