"""Replace LigandReaction with the matches in a match_ligand_reactions.py output.

python manage.py load_ligand_reactions routes.tsv.gz
"""

import csv
import gzip
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tpweb.models.LigandReaction import LigandReaction, ligand_smiles_key

BATCH_SIZE = 5000


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def reaction_from_row(row):
    return LigandReaction(
        smiles_key=ligand_smiles_key(row["ligand_smiles"]),
        db=row["db"],
        is_exact=row["match"] == "exact",
        similarity=_float_or_none(row["similarity"]),
        reaction_id=row["reaction_id"][:64],
        reaction_class=_int_or_none(row["reaction_class"]),
        reaction_name=row["reaction_name"][:255],
        reactants=row["reactants"],
        reagents=row["reagents"],
        product=row["product"],
    )


class Command(BaseCommand):
    help = "Replace the ligand synthesis routes with a match_ligand_reactions.py output."

    def add_arguments(self, parser):
        parser.add_argument("path", help="routes.tsv.gz (or plain .tsv)")

    def handle(self, *args, **options):
        path = options["path"]
        opener = gzip.open if path.endswith(".gz") else open
        csv.field_size_limit(sys.maxsize)
        loaded = 0
        try:
            with opener(path, "rt", encoding="utf-8", newline="") as handle, transaction.atomic():
                LigandReaction.objects.all().delete()
                batch = []
                for row in csv.DictReader(handle, delimiter="\t"):
                    batch.append(reaction_from_row(row))
                    if len(batch) >= BATCH_SIZE:
                        LigandReaction.objects.bulk_create(batch)
                        loaded += len(batch)
                        batch = []
                LigandReaction.objects.bulk_create(batch)
                loaded += len(batch)
        except FileNotFoundError as exc:
            raise CommandError(f"Not found: {path}") from exc
        self.stdout.write(self.style.SUCCESS(f"Loaded {loaded} ligand reactions."))
