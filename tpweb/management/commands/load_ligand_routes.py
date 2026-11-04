"""Replace LigandRoutePlan with the plans in an expand_ligand_routes.py output.

python manage.py load_ligand_routes plans.jsonl.gz
"""

import gzip
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tpweb.models.LigandReaction import ligand_smiles_key
from tpweb.models.LigandRoutePlan import LigandRoutePlan

BATCH_SIZE = 2000


def plan_from_record(record):
    return LigandRoutePlan(
        smiles_key=ligand_smiles_key(record["ligand_smiles"]),
        solved=bool(record.get("solved")),
        depth=record.get("depth") or 0,
        steps=record.get("steps") or 0,
        leaves=record.get("leaves") or 0,
        available_leaves=record.get("available_leaves") or 0,
        tree=record["tree"],
    )


class Command(BaseCommand):
    help = "Replace the multi-step synthesis plans with an expand_ligand_routes.py output."

    def add_arguments(self, parser):
        parser.add_argument("path", help="plans.jsonl.gz (or plain .jsonl)")

    def handle(self, *args, **options):
        path = options["path"]
        opener = gzip.open if path.endswith(".gz") else open
        loaded = solved = 0
        seen = set()
        try:
            with opener(path, "rt", encoding="utf-8") as handle, transaction.atomic():
                LigandRoutePlan.objects.all().delete()
                batch = []
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    plan = plan_from_record(record)
                    # smiles_key is unique: the same ligand can be exported
                    # twice when two Binders rows hold the same SMILES.
                    if plan.smiles_key in seen:
                        continue
                    seen.add(plan.smiles_key)
                    batch.append(plan)
                    solved += int(plan.solved)
                    if len(batch) >= BATCH_SIZE:
                        LigandRoutePlan.objects.bulk_create(batch)
                        loaded += len(batch)
                        batch = []
                LigandRoutePlan.objects.bulk_create(batch)
                loaded += len(batch)
        except FileNotFoundError as exc:
            raise CommandError(f"Not found: {path}") from exc
        except (json.JSONDecodeError, KeyError) as exc:
            raise CommandError(f"Malformed plan file {path}: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(f"Loaded {loaded} synthesis plans ({solved} fully resolved).")
        )
