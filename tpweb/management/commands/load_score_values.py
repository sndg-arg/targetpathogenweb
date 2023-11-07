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
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB, Residue, Atom, ResidueSet, ResidueSetResidue, PDBResidueSet, Property, \
    ResidueProperty, ResidueSetProperty
import subprocess as sp
from django.db import transaction


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

    def handle(self, *args, **options):

        genome_name = options["genome_name"]
        genome = Biodatabase.objects.filter(name=genome_name + Biodatabase.PROT_POSTFIX)
        if not genome.exists():
            self.stderr.write(f"genome '{genome_name}' does not exists\n")
            sys.exit(1)

        assert os.path.exists(options["score_tsv"]), f'"{options["score_tsv"]}" does not exists!'
        genome = genome.get()

        df = pd.read_csv(options["score_tsv"], sep=options["separator"], index_col=False).fillna("None")

        assert "gene" in df.columns, "'gene' is not in the column list"

        #ScoreParam.initialize()


        columns = set(df.columns) - set(["gene"])

        score_params = {}
        for c in columns:
            sp = ScoreParam.objects.filter(name=c)
            if sp.exists():
                sp = sp.get()
                valid_values = set([x.name for x in sp.choices.all()])
                invalid_values = set(df[c]) - valid_values
                if invalid_values:
                    sys.stderr.write(f'Column "{c}" has some invalid values: {",".join(invalid_values)} '
                                     f'valid values are {",".join(valid_values)}\n')
                else:
                    spv_qs = ScoreParamValue.objects.filter(bioentry__biodatabase=genome, score_param=sp)
                    if spv_qs.exists():
                        if options["overwrite"]:
                            spv_qs.delete()
                            score_params[c] = sp
                        else:
                            sys.stderr.write(
                                f"'{c}' has loaded values for {genome_name}, use --overwrite to replace them \n")
                    else:
                        score_params[c] = sp
            else:
                sys.stderr.write(f"'{c}' is not a valid score parameter\n")

        assert score_params, f"no valid score parameters were found in the file"

        for _, r in tqdm(df.iterrows(),file=sys.stderr,total=len(df)):
            with transaction.atomic():
                for c, sp in score_params.items():
                    be = Bioentry.objects.filter(accession=r.gene, biodatabase=genome)
                    if be.exists():
                        ScoreParamValue(score_param=sp, bioentry=be.get(), value=r[c]).save()
                    else:
                        sys.stderr.write(f"'{r.gene}' was not found\n")

        self.stderr.write(f"done adding properties ({','.join(score_params)}) to {genome_name} ")
