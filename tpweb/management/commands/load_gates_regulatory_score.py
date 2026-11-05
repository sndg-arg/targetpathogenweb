"""
load_gates_regulatory_score - turn the Gates-project gene regulatory network
(GRN) columns a researcher uploaded into curated platform columns.

The GRN analysis arrived as four uploaded columns (GRN_knockout_score,
GRN_category, GRN_Transcription_Factor, GRN_Target_gene) owned by their
author. This copies their values for one genome into the platform's
"Regulatory (curated)" columns (grn_knockout_score, grn_role,
grn_transcription_factor, grn_regulated -- see score_params), which feed the
Regulatory group of the protein page's Prioritization evidence. The author's
own columns are left untouched.

Only columns the author shared on that genome are read: an "Only me" column
is never copied.

Usage
-----
python manage.py load_gates_regulatory_score public__GCA_030061715.1 --from-user sol --overwrite
"""

import os
import tempfile

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.CustomParamShare import CustomParamShare
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue

# Uploaded column -> curated column.
SOURCE_COLUMNS = {
    "GRN_knockout_score": "grn_knockout_score",
    "GRN_category": "grn_role",
    "GRN_Transcription_Factor": "grn_transcription_factor",
    "GRN_Target_gene": "grn_regulated",
}

ROLE_LABELS = {
    "master_regulator": "Master regulator",
    "structural_hub": "Structural hub",
    "bottleneck": "Bottleneck",
    "peripheral": "Peripheral",
}


def curated_value(column, raw):
    """The uploaded value as the curated column stores it ("" = no value)."""
    value = str(raw or "").strip()
    if column == "grn_role":
        return ROLE_LABELS.get(value.lower(), "")
    if column == "grn_transcription_factor":
        return "Y" if value.upper() == "TF" else "N"
    if column == "grn_regulated":
        return "Y" if value.upper() == "TG" else "N"
    return value


class Command(BaseCommand):
    help = "Copies a researcher's shared GRN columns into the curated Regulatory columns."

    def add_arguments(self, parser):
        parser.add_argument("genome_name", help="internal accession, e.g. public__GCA_030061715.1")
        parser.add_argument("--from-user", required=True, help="username that uploaded the columns")
        parser.add_argument("--datadir", default="./data")
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        proteome = Biodatabase.objects.filter(name=genome_name + Biodatabase.PROT_POSTFIX).first()
        if proteome is None:
            raise CommandError(f"genome '{genome_name}' does not exist")
        owner = get_user_model().objects.filter(username=options["from_user"]).first()
        if owner is None:
            raise CommandError(f"user '{options['from_user']}' does not exist")

        rows = {}
        for source, column in SOURCE_COLUMNS.items():
            param = ScoreParam.objects.filter(user=owner, category="Custom", name=source).first()
            if param is None:
                raise CommandError(f"{owner.username} has no column '{source}'")
            shared = (
                CustomParamShare.objects.filter(score_param=param, genome_name=genome_name)
                .exclude(visibility="private")
                .exists()
            )
            if not shared:
                raise CommandError(
                    f"'{source}' is not shared on {genome_name}; ask its owner to share it first"
                )
            values = ScoreParamValue.objects.filter(
                score_param=param, bioentry__biodatabase=proteome
            ).values_list("bioentry__accession", "value", "numeric_value")
            for accession, value, numeric in values:
                raw = value if value not in (None, "") else numeric
                rows.setdefault(accession, {})[column] = curated_value(column, raw)

        if not rows:
            raise CommandError(f"no GRN values found on {genome_name}")

        table = pd.DataFrame.from_dict(rows, orient="index", columns=list(SOURCE_COLUMNS.values()))
        table = table.fillna("").rename_axis("gene").reset_index()
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "regulatory_gates.tsv")
            table.to_csv(path, sep="\t", index=False)
            self.stderr.write(f"Loading {len(table)} gene row(s) into {genome_name}")
            call_command(
                "load_score_values",
                genome_name,
                path,
                datadir=options["datadir"],
                overwrite=options["overwrite"],
            )
