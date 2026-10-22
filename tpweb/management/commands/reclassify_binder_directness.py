"""Re-decide direct vs. via-homolog for a genome's already-loaded ligand evidence.

`load_ligq_2_results` decides `Binders.is_direct` at load time from the
protein's UniProt cross-references. A genome loaded before its UniProt
mapping existed (or whose own mapping is missing) ends up with every PDB and
ChEMBL record marked "via homolog". This re-runs that decision with the
protein's current UniProt entries plus those of its identical copies in other
strains (`tpweb.services.binder_directness`), and only touches rows whose
classification changes.

Usage:
    python manage.py reclassify_binder_directness <internal_accession> [--dry-run]
"""

from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders
from tpweb.services.binder_directness import protein_uniprot_map

BATCH = 2000


class Command(BaseCommand):
    help = "Re-classify a genome's PDB/ChEMBL ligand records as direct or via homolog."

    def add_arguments(self, parser):
        parser.add_argument("genome", help="Internal accession, e.g. public__GCA_030061715.1")
        parser.add_argument("--dry-run", action="store_true", help="Count changes, write nothing.")

    def handle(self, *args, **options):
        proteome = options["genome"] + Biodatabase.PROT_POSTFIX
        if not Biodatabase.objects.filter(name=proteome).exists():
            raise CommandError(f"No proteome named {proteome}.")

        binders = Binders.objects.filter(
            locustag__biodatabase__name=proteome,
            source__in=[Binders.SOURCE_PDB, Binders.SOURCE_CHEMBL],
        )
        accessions = set(binders.values_list("locustag_id", flat=True).distinct())
        uniprots = protein_uniprot_map(accessions)
        self.stdout.write(
            f"{binders.count()} PDB/ChEMBL records on {len(accessions)} proteins; "
            f"{len(uniprots)} proteins have a UniProt entry (own or identical copy)."
        )

        to_direct, to_homolog = [], []
        for pk, acc, uniprot, is_direct in binders.values_list(
            "pk", "locustag_id", "uniprot", "is_direct"
        ).iterator():
            should = bool(uniprot and uniprot in uniprots.get(acc, ()))
            if should and not is_direct:
                to_direct.append(pk)
            elif is_direct and not should:
                to_homolog.append(pk)

        if not options["dry_run"]:
            for ids, value in ((to_direct, True), (to_homolog, False)):
                for i in range(0, len(ids), BATCH):
                    Binders.objects.filter(pk__in=ids[i : i + BATCH]).update(is_direct=value)

        verb = "would change" if options["dry_run"] else "changed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {len(to_direct)} records to direct, {len(to_homolog)} to via homolog."
            )
        )
