"""Populate missing table scores from P2Rank pockets already in the database."""

import math
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import ResidueSetProperty
from tpweb.services.pocket_geometry import filter_residuesetproperty_by_chain


BUNDLE = ("p2rank_probability", "best_p2rank_structure", "p2rank_pocket")
PROBABILITY_PROPERTIES = ("probability", "P2Rrank probability", "P2Rank probability")


def candidate_key(link, pocket_id, probability):
    """Prefer experimental evidence, then probability, with stable ties."""
    if probability is None or not math.isfinite(probability) or not 0 <= probability <= 1:
        return None
    experimental = (link.pdb.experiment or "").upper() not in {"AF", "CF"}
    return (experimental, probability, -link.pk, -pocket_id)


def has_value(row):
    return row.numeric_value is not None or str(row.value or "").strip().lower() not in {
        "",
        "none",
        "nan",
        "null",
        "-",
        "—",
    }


class Command(BaseCommand):
    help = "Index existing P2Rank pockets into missing probability/structure/pocket table values."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--apply", action="store_true", help="Write missing bundles; otherwise preview only."
        )

    def handle(self, *args, **options):
        genome = options["genome_name"]
        database = Biodatabase.objects.filter(name=genome + Biodatabase.PROT_POSTFIX).first()
        if database is None:
            raise CommandError(f"Proteome not found: {genome}")
        links = list(
            BioentryStructure.objects.filter(
                bioentry__biodatabase=database,
            )
            .select_related("pdb")
            .order_by("pk")
        )
        by_chain = defaultdict(list)
        for link in links:
            by_chain[link.chain or ""].append(link)
        selected = {}
        for chain, group in by_chain.items():
            rows = ResidueSetProperty.objects.filter(
                pdbresidue_set__pdb_id__in={link.pdb_id for link in group},
                pdbresidue_set__residue_set__name="P2RankPocket",
                property__name__in=PROBABILITY_PROPERTIES,
                value__isnull=False,
            )
            rows = filter_residuesetproperty_by_chain(rows, chain)
            by_structure = defaultdict(list)
            for pdb_id, pocket_id, name, probability in rows.values_list(
                "pdbresidue_set__pdb_id", "pdbresidue_set_id", "pdbresidue_set__name", "value"
            ):
                by_structure[pdb_id].append((pocket_id, name, probability))
            for link in group:
                for pocket_id, name, probability in by_structure[link.pdb_id]:
                    key = candidate_key(link, pocket_id, probability)
                    if key is None or not str(name or "").strip():
                        continue
                    previous = selected.get(link.bioentry_id)
                    if previous is None or key > previous[0]:
                        selected[link.bioentry_id] = (key, link.pdb.code, str(name), probability)
        param_query = ScoreParam.objects.filter(name__in=BUNDLE, user__isnull=True)
        params = {param.name: param for param in param_query}
        if len(params) != param_query.count():
            raise CommandError("Ambiguous global P2Rank parameters; no scores changed.")
        written = protected = 0
        with transaction.atomic():
            if options["apply"] and selected:
                from tpweb.services.score_params import ensure_system_score_param

                params[BUNDLE[0]] = ensure_system_score_param(BUNDLE[0])
                for name in BUNDLE[1:]:
                    if name in params:
                        continue
                    params[name], _ = ScoreParam.objects.get_or_create(
                        name=name,
                        category="Pocket",
                        user=None,
                        defaults={
                            "type": "C",
                            "default_operation": "=",
                            "default_value": "",
                            "description": "Source of the selected P2Rank probability.",
                        },
                    )
            existing = ScoreParamValue.objects.filter(
                bioentry__biodatabase=database,
                score_param_id__in=[p.pk for p in params.values()],
            )
            if options["apply"]:
                existing = existing.select_for_update()
            existing = {(row.bioentry_id, row.score_param_id): row for row in existing}
            creates, updates = [], []
            for protein_id, (_, code, pocket_name, probability) in selected.items():
                # Keep any existing selection intact, including partial curated
                # bundles. Never attach an automatic pocket to a curated score.
                if any(
                    (row := existing.get((protein_id, p.pk))) is not None and has_value(row)
                    for p in params.values()
                ):
                    protected += 1
                    continue
                written += 1
                if not options["apply"]:
                    continue
                for name, value in zip(BUNDLE, (str(probability), code, pocket_name), strict=True):
                    param = params[name]
                    numeric = probability if name == BUNDLE[0] else None
                    row = existing.get((protein_id, param.pk))
                    if row is None:
                        creates.append(
                            ScoreParamValue(
                                bioentry_id=protein_id,
                                score_param=param,
                                value=value,
                                numeric_value=numeric,
                            )
                        )
                    else:
                        row.value, row.numeric_value = value, numeric
                        updates.append(row)
            if options["apply"]:
                ScoreParamValue.objects.bulk_create(creates, batch_size=500)
                ScoreParamValue.objects.bulk_update(
                    updates, ["value", "numeric_value"], batch_size=500
                )
        action = "Indexed" if options["apply"] else "Would index"
        self.stdout.write(
            f"{action}: {written} proteins; preserved existing selections: {protected}; "
            f"proteins with valid pocket candidates: {len(selected)}."
        )
