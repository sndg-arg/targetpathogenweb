"""Recover ColabFold-specific table values from the original linked model."""

import math
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Min, Max

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import Atom, ResidueSetProperty
from tpweb.services.pocket_geometry import filter_residuesetproperty_by_chain
from tpweb.services.structure_sources import chain_parts
from tpweb.management.commands.index_p2rank_scores import PROBABILITY_PROPERTIES, has_value


BUNDLES = (
    ("colabfold_plddt",),
    ("colabfold_druggability_score", "colabfold_fpocket_pocket"),
    ("colabfold_p2rank_probability", "colabfold_p2rank_pocket"),
)


class Command(BaseCommand):
    help = "Recover missing ColabFold pLDDT and pocket scores; preserve existing values and skip ambiguous models."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        database = Biodatabase.objects.filter(
            name=options["genome_name"] + Biodatabase.PROT_POSTFIX
        ).first()
        if database is None:
            raise CommandError("Genome proteome not found.")
        by_protein = defaultdict(dict)
        for link in (
            BioentryStructure.objects.filter(bioentry__biodatabase=database, pdb__experiment="CF")
            .select_related("pdb")
            .order_by("pk")
        ):
            by_protein[link.bioentry_id][(link.pdb_id, link.chain or "")] = link
        ambiguous = sum(len(links) != 1 for links in by_protein.values())
        by_chain = defaultdict(list)
        for links in by_protein.values():
            if len(links) == 1:
                link = next(iter(links.values()))
                by_chain[link.chain or ""].append(link)
        recovered = defaultdict(dict)
        for chain, links in by_chain.items():
            ids = {link.pdb_id for link in links}
            atoms = Atom.objects.filter(
                residue__pdb_id__in=ids, residue__type="R", name="CA", altLoc__in=["", " ", "A"]
            )
            if parts := chain_parts(chain):
                atoms = atoms.filter(residue__chain__in=parts)
            confidence = {
                row["residue__pdb_id"]: row
                for row in atoms.values("residue__pdb_id").annotate(
                    mean=Avg("bfactor"), minimum=Min("bfactor"), maximum=Max("bfactor")
                )
            }
            best = {}
            for kind, properties, bundle in (
                ("FPocketPocket", ("druggability_score",), BUNDLES[1]),
                ("P2RankPocket", PROBABILITY_PROPERTIES, BUNDLES[2]),
            ):
                rows = ResidueSetProperty.objects.filter(
                    pdbresidue_set__pdb_id__in=ids,
                    pdbresidue_set__residue_set__name=kind,
                    property__name__in=properties,
                    value__isnull=False,
                )
                rows = filter_residuesetproperty_by_chain(rows, chain)
                for pdb_id, pocket_id, name, value in rows.values_list(
                    "pdbresidue_set__pdb_id", "pdbresidue_set_id", "pdbresidue_set__name", "value"
                ):
                    if not math.isfinite(value) or not 0 <= value <= 1 or not str(name).strip():
                        continue
                    key = (pdb_id, bundle)
                    candidate = (value, -pocket_id, str(name))
                    if key not in best or candidate > best[key]:
                        best[key] = candidate
            for link in links:
                fields = recovered[link.bioentry_id]
                row = confidence.get(link.pdb_id)
                if (
                    row
                    and all(
                        row[k] is not None and math.isfinite(row[k])
                        for k in ("mean", "minimum", "maximum")
                    )
                    and 0 <= row["minimum"] <= row["maximum"] <= 100
                ):
                    fields[BUNDLES[0]] = (row["mean"],)
                for bundle in BUNDLES[1:]:
                    if result := best.get((link.pdb_id, bundle)):
                        fields[bundle] = (result[0], result[2])
        names = {name for bundle in BUNDLES for name in bundle}
        params_query = ScoreParam.objects.filter(name__in=names, user__isnull=True)
        params = {param.name: param for param in params_query}
        if len(params) != params_query.count():
            raise CommandError("Ambiguous global ColabFold parameters; no values changed.")
        counts, preserved = defaultdict(int), 0
        with transaction.atomic():
            needed = {name for fields in recovered.values() for bundle in fields for name in bundle}
            if options["apply"]:
                from tpweb.services.score_params import ensure_system_score_param

                for name in sorted(needed):
                    if name in {bundle[0] for bundle in BUNDLES}:
                        params[name] = ensure_system_score_param(name)
                    elif name not in params:
                        params[name], _ = ScoreParam.objects.get_or_create(
                            name=name,
                            category="Pocket",
                            user=None,
                            defaults={
                                "type": "C",
                                "default_operation": "=",
                                "default_value": "",
                                "description": "Pocket in the original linked ColabFold model.",
                            },
                        )
            existing = ScoreParamValue.objects.filter(
                bioentry__biodatabase=database,
                score_param_id__in=[param.pk for param in params.values()],
            )
            if options["apply"]:
                existing = existing.select_for_update()
            existing = {(row.bioentry_id, row.score_param_id): row for row in existing}
            creates, updates = [], []
            for protein_id, fields in recovered.items():
                for bundle, values in fields.items():
                    if any(
                        name in params
                        and (row := existing.get((protein_id, params[name].pk))) is not None
                        and has_value(row)
                        for name in bundle
                    ):
                        preserved += 1
                        continue
                    counts[bundle[0]] += 1
                    if not options["apply"]:
                        continue
                    for index, (name, value) in enumerate(zip(bundle, values, strict=True)):
                        param = params[name]
                        row = existing.get((protein_id, param.pk))
                        numeric = float(value) if index == 0 else None
                        if row is None:
                            creates.append(
                                ScoreParamValue(
                                    bioentry_id=protein_id,
                                    score_param=param,
                                    value=str(value),
                                    numeric_value=numeric,
                                )
                            )
                        else:
                            row.value, row.numeric_value = str(value), numeric
                            updates.append(row)
            if options["apply"]:
                ScoreParamValue.objects.bulk_create(creates, batch_size=500)
                ScoreParamValue.objects.bulk_update(
                    updates, ["value", "numeric_value"], batch_size=500
                )
        action = "Indexed" if options["apply"] else "Would index"
        self.stdout.write(
            f"{action} ColabFold: {dict(counts)}; preserved bundles: {preserved}; "
            f"ambiguous proteins skipped: {ambiguous}."
        )
