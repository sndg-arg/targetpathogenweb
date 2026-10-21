#!/usr/bin/env python3
"""Repair one owner's existing soft-core boolean columns without inventing missing data."""

import argparse
import os
from pathlib import Path
import sys


NAMES = (
    "soft_core_roary",
    "soft_core_corecruncher",
    "softcore_roary",
    "softcore_corecruncher",
)


def boolean_text(value, numeric=None):
    text = str(value if value is not None else "").strip().lower()
    if not text or text in {"nan", "none", "null"}:
        if numeric is None:
            return ""
        text = str(numeric)
    if text in {"true", "1", "1.0"}:
        return "True"
    if text in {"false", "0", "0.0"}:
        return "False"
    raise ValueError(f"Not a boolean value: {value!r}, numeric={numeric!r}")


def repair(email, apply):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tpwebconfig.settings")
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.cache import cache
    from django.db import transaction
    from django.db.models import Q
    from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
    from tpweb.models.ScoreParamValue import ScoreParamValue
    from tpweb.models.ScoreFormula import ScoreFormula
    from bioseq.models.Biodatabase import Biodatabase

    owner = get_user_model().objects.get(email__iexact=email)
    with transaction.atomic():
        params = list(
            ScoreParam.objects.select_for_update().filter(
                user=owner,
                category="Custom",
                name__in=NAMES,
            )
        )
        if not params:
            raise RuntimeError("No soft-core columns found for this account; nothing changed")
        formula_filter = Q(terms__score_param__in=params)
        for param in params:
            formula_filter |= Q(expression__icontains=param.name)
        formulas = list(
            ScoreFormula.objects.filter(formula_filter).values_list("name", flat=True).distinct()
        )
        if formulas:
            raise RuntimeError(
                "Columns are used in formulas; nothing changed. Review: " + ", ".join(formulas)
            )
        plans = []
        genomes = set()
        for param in params:
            values = list(
                ScoreParamValue.objects.select_for_update()
                .filter(
                    score_param=param,
                )
                .select_related("bioentry__biodatabase")
            )
            counts = {"True": 0, "False": 0, "": 0}
            for row in values:
                row.value = boolean_text(row.value, row.numeric_value)
                row.numeric_value = None
                counts[row.value] += 1
                genomes.add(row.bioentry.biodatabase.name.removesuffix(Biodatabase.PROT_POSTFIX))
            plans.append((param, values))
            print(f"{param.name}: {len(values)} rows; {counts}", flush=True)
        if not apply:
            print("Preview only. Use --apply to save.")
            return
        for param, values in plans:
            ScoreParamValue.objects.bulk_update(values, ["value", "numeric_value"], batch_size=1000)
            param.type = "C"
            param.default_operation = "="
            param.default_value = boolean_text(param.default_value)
            param.save(update_fields=["type", "default_operation", "default_value"])
            for name in ("True", "False"):
                ScoreParamOptions.objects.get_or_create(score_param=param, name=name)
        for genome in genomes:
            transaction.on_commit(
                lambda g=genome: cache.delete(f"Target:genome_score_param_names:{g}")
            )
    print("Saved. Re-upload the original TSVs with Replace to fill their supplied rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repair(args.email, args.apply)
