import os
import shutil
import sys
import traceback
import gzip
import tempfile

import numpy as np
import pandas as pd
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.score_params import resolve_score_param_for_import
from tpweb.models.pdb import PDB, Residue, Atom, ResidueSet, ResidueSetResidue, PDBResidueSet, Property, \
    ResidueProperty, ResidueSetProperty
import subprocess as sp
from django.db import transaction
from tpweb.services.score_param_types import is_numeric_score_param


def mkdir(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


class Command(BaseCommand):
    help = 'Imports a PDB'

    def add_arguments(self, parser):

        parser.add_argument('genome_name')
        parser.add_argument('score_tsv', help="tsv with: gene prop1 prop2 ... ")
        parser.add_argument('--separator', default="\t")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")
        parser.add_argument('--username', default=None)

    def handle(self, *args, **options):

        genome_name = options["genome_name"]
        owner = None
        if options["username"]:
            owner = get_user_model().objects.filter(username=options["username"]).first()
            if owner is None:
                raise CommandError(f"user '{options['username']}' does not exist")
        genome = Biodatabase.objects.filter(name=genome_name + Biodatabase.PROT_POSTFIX)
        if not genome.exists():
            self.stderr.write(f"genome '{genome_name}' does not exists\n")
            sys.exit(1)

        assert os.path.exists(options["score_tsv"]), f'"{options["score_tsv"]}" does not exists!'
        genome = genome.get()

        df = pd.read_csv(options["score_tsv"], sep=options["separator"], index_col=False)

        assert "gene" in df.columns, "'gene' is not in the column list"

        ScoreParam.Initialize_druggability()
        ScoreParam.Initialize_celular_localization()


        columns = set(df.columns) - set(["gene"])


        score_params = {}
        for c in columns:
            sp = resolve_score_param_for_import(
                c,
                owner=owner,
                source_df=df[["gene", c]],
            )
            if sp is None:
                continue
            if is_numeric_score_param(sp):
                invalid_values = []
                raw_series = df[c]
                coerced_values = pd.to_numeric(raw_series, errors="coerce")
                for raw_value, numeric_value in zip(df[c], coerced_values):
                    raw_text = str(raw_value).strip()
                    if pd.isna(numeric_value) and raw_text and raw_text.lower() not in {"none", "nan", "null"}:
                        invalid_values.append(str(raw_value))
                if invalid_values:
                    sys.stderr.write(
                        f'Column "{c}" has some invalid numeric values: {",".join(sorted(set(invalid_values)))}\n'
                    )
                    continue
            else:
                if sp.category == "Custom":
                    for raw_value in df[c]:
                        if pd.isna(raw_value):
                            continue
                        value = str(raw_value).strip()
                        if value and value.lower() not in {"none", "nan", "null"}:
                            ScoreParamOptions.objects.get_or_create(score_param=sp, name=value, defaults={"description": ""})

                valid_values = {x.name for x in sp.choices.all()}
                invalid_values = {
                    str(raw_value).strip()
                    for raw_value in df[c]
                    if not pd.isna(raw_value)
                    and str(raw_value).strip()
                    and str(raw_value) not in valid_values
                }
                if invalid_values:
                    sys.stderr.write(
                        f'Column "{c}" has some invalid values: {",".join(sorted(invalid_values))} '
                        f'valid values are {",".join(sorted(valid_values))}\n'
                    )
                    continue

            spv_qs = ScoreParamValue.objects.filter(bioentry__biodatabase=genome, score_param=sp)
            if spv_qs.exists():
                if options["overwrite"]:
                    spv_qs.delete()
                    score_params[c] = sp
                else:
                    sys.stderr.write(
                        f"'{c}' has loaded values for {genome_name}, use --overwrite to replace them \n"
                    )
            else:
                score_params[c] = sp

        assert score_params, f"no valid score parameters were found in the file"

        for _, r in tqdm(df.iterrows(),file=sys.stderr,total=len(df)):
            with transaction.atomic():
                for c, sp in score_params.items():
                    be = Bioentry.objects.filter(accession=r.gene, biodatabase=genome)

                    if be.exists():
                        raw_value = r[c]
                        numeric_value = None
                        if is_numeric_score_param(sp):
                            if pd.isna(raw_value):
                                raw_value = ""
                            else:
                                numeric_value = float(raw_value)
                        elif pd.isna(raw_value):
                            raw_value = ""
                        else:
                            raw_value = str(raw_value).strip()
                        ScoreParamValue(
                            score_param=sp,
                            bioentry=be.get(),
                            value=str(raw_value),
                            numeric_value=numeric_value,
                        ).save()
                    else:
                        sys.stderr.write(f"'{r.gene}' was not found\n")

        self.stderr.write(f"done adding properties ({','.join(score_params)}) to {genome_name} ")
