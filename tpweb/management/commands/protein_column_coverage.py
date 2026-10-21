"""Read-only coverage of protein-table inputs, including live shared evidence."""

import csv
import math
from collections import Counter
from itertools import islice

from django.core.management.base import BaseCommand, CommandError

from tpweb.services.score_param_types import is_numeric_score_param


def has_score_data(row):
    if is_numeric_score_param(row.score_param):
        value = row.numeric_value if row.numeric_value is not None else row.value
        try:
            return math.isfinite(float(str(value).replace(",", ".")))
        except (TypeError, ValueError):
            return False
    return row.value is not None and str(row.value).strip().lower() not in {
        "",
        "none",
        "null",
        "nan",
        "-",
        "—",
        "<na>",
    }


def score_presence(protein, param_ids):
    """One protein counts once per column; shared rows retain their origin."""
    present, shared = set(), set()
    for row in protein.score_params.all():
        if row.score_param_id in param_ids and has_score_data(row):
            present.add(row.score_param_id)
            if row.bioentry_id != protein.pk:
                shared.add(row.score_param_id)
    return present, shared


def fixed_presence(protein):
    links = list(protein.structures.all())
    names = {
        str(row.dbxref.dbname).lower()
        for row in protein.dbxrefs.all()
        if str(row.dbxref.accession or "").strip()
    }
    return {
        "Accession": bool(protein.accession),
        "Description": bool(str(protein.description or "").strip()),
        "Gene": bool([gene for gene in protein.genes() if len(gene) <= 6]),
        "Structure": bool(links),
        "Experimental structure": any(
            (link.pdb.experiment or "").upper() not in {"AF", "CF"} for link in links
        ),
        "AlphaFold structure": any((link.pdb.experiment or "").upper() == "AF" for link in links),
        "ColabFold structure": any((link.pdb.experiment or "").upper() == "CF" for link in links),
        "EC": "ec" in names,
        "GO": "go" in names,
        "Metabolic context": bool(protein.metabolic_reaction_count),
    }


class Command(BaseCommand):
    help = "Count proteins with data per available column, sorted by increasing coverage."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--user", required=True, help="Account email or username; scopes custom columns."
        )

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Prefetch, Q
        from bioseq.models.Biodatabase import Biodatabase
        from bioseq.models.Bioentry import Bioentry
        from tpweb.models.ScoreParam import ScoreParam
        from tpweb.models.ScoreParamValue import ScoreParamValue
        from tpweb.services.genome_workspace import user_can_access_genome_name
        from tpweb.services.score_params import score_param_visibility_filter
        from tpweb.services.shared_sequence_evidence import (
            apply_shared_sequence_evidence,
            inherited_score_param_ids,
        )

        genome = options["genome_name"]
        account = options["user"]
        users = list(
            get_user_model().objects.filter(Q(email__iexact=account) | Q(username=account))
        )
        if len(users) != 1:
            raise CommandError("Specify one existing, unambiguous account email or username.")
        user = users[0]
        if not user_can_access_genome_name(user, genome):
            raise CommandError("This account cannot access the genome.")
        database = Biodatabase.objects.filter(name=genome + Biodatabase.PROT_POSTFIX).first()
        if database is None:
            raise CommandError(f"Proteome not found: {genome}")
        # Do not call visible_score_params_queryset: it also creates missing
        # system parameters. This audit must not write anything.
        params = list(
            ScoreParam.objects.filter(
                score_param_visibility_filter(user, genome)
                | Q(pk__in=inherited_score_param_ids(genome, user))
            ).order_by("name", "pk")
        )
        param_ids = {param.pk for param in params}
        proteins = (
            Bioentry.objects.filter(biodatabase=database)
            .select_related("biodatabase", "seq")
            .annotate(metabolic_reaction_count=Count("metabolic_reactions", distinct=True))
            .prefetch_related(
                Prefetch(
                    "score_params", queryset=ScoreParamValue.objects.select_related("score_param")
                ),
                "structures__pdb",
                "dbxrefs__dbxref",
                "qualifiers__term",
            )
            .order_by("pk")
        )
        total = proteins.count()
        if not total:
            raise CommandError("The genome has no loaded proteins.")
        local, effective, inherited = Counter(), Counter(), Counter()
        local_fixed, effective_fixed = Counter(), Counter()
        iterator = proteins.iterator(chunk_size=200)
        while batch := list(islice(iterator, 200)):
            for protein in batch:
                present, _ = score_presence(protein, param_ids)
                local.update(present)
                local_fixed.update(
                    {key: int(value) for key, value in fixed_presence(protein).items()}
                )
            apply_shared_sequence_evidence(batch, user)
            for protein in batch:
                present, shared = score_presence(protein, param_ids)
                effective.update(present)
                inherited.update(shared)
                effective_fixed.update(
                    {key: int(value) for key, value in fixed_presence(protein).items()}
                )
        rows = [
            (
                param.name,
                param.category,
                param.pk,
                effective[param.pk],
                local[param.pk],
                inherited[param.pk],
            )
            for param in params
        ]
        rows += [
            (key, "Fixed / structure breakdown", "", effective_fixed[key], local_fixed[key], "")
            for key in local_fixed
        ]
        rows.sort(key=lambda row: (row[3], row[0].lower(), str(row[2])))
        self.stderr.write(f"Genome: {genome}; proteins: {total}; account: {user.username}")
        self.stderr.write(
            "All available columns, without table filters. Shared = values read from another occurrence. Rank and formula Score are not input data."
        )
        writer = csv.writer(self.stdout, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "Columna",
                "Categoria",
                "Param_ID",
                "Con_datos",
                "Total",
                "Porcentaje",
                "Sin_datos",
                "Locales",
                "Compartidos",
            ]
        )
        for name, category, pk, filled, native, shared in rows:
            writer.writerow(
                [
                    name,
                    category,
                    pk,
                    filled,
                    total,
                    f"{100 * filled / total:.1f}%",
                    total - filled,
                    native,
                    shared,
                ]
            )
