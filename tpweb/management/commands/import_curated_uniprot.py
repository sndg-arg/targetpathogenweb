import math
import os
import re

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Dbxref import Dbxref


UNIPROT_EMPTY_VALUES = {"", "-", "na", "n/a", "nan", "none", "null"}
UNIPROT_TOKEN_SPLIT_RE = re.compile(r"[,;\s]+")
UNIPROT_PIPE_RE = re.compile(r"^(?:sp|tr)\|([^|]+)\|", re.IGNORECASE)


class Command(BaseCommand):
    help = (
        "Import curated UniProt accessions from an external results TSV. "
        "The TSV must contain 'gene' and 'uniprot' columns."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--results-tsv", required=True, help="Curated results TSV.")
        parser.add_argument("--datadir", default="./data", help="TPW data directory.")
        parser.add_argument(
            "--dbname",
            default="UnipTr",
            choices=("UnipTr", "UnipSp"),
            help=(
                "Dbxref database name used for TSV-provided accessions. "
                "Default: UnipTr because curated TSVs usually do not include reviewed status."
            ),
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Remove existing UniProt BioentryDbxref rows for this proteome before importing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing database rows or _unips.lst.",
        )
        parser.add_argument(
            "--lst",
            default=None,
            help="Output path for the '<uniprot> <locus>' list used by fetch_uniprot_annotations.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        results_tsv = options["results_tsv"]
        datadir = options["datadir"]
        dbname = options["dbname"]
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        db = Biodatabase.objects.filter(name=proteome_name).first()
        if db is None:
            raise CommandError(f"Proteome '{proteome_name}' not found. Load the GBK first.")
        if not os.path.isfile(results_tsv):
            raise CommandError(f"Results TSV not found: {results_tsv}")

        df = pd.read_csv(results_tsv, sep="\t", usecols=lambda col: col in {"gene", "uniprot"})
        missing_columns = {"gene", "uniprot"} - set(df.columns)
        if missing_columns:
            self.stdout.write(
                self.style.WARNING(
                    f"Missing column(s) {', '.join(sorted(missing_columns))}; skipping UniProt import."
                )
            )
            return

        bioentries = {
            be.accession: be
            for be in Bioentry.objects.filter(biodatabase=db, accession__in=set(df["gene"].astype(str)))
        }

        mappings = []
        rows_with_uniprot = 0
        missing_locus = 0
        seen = set()

        for _, row in df.fillna("").iterrows():
            locus = str(row["gene"]).strip()
            accessions = _parse_uniprot_accessions(row["uniprot"])
            if not accessions:
                continue
            rows_with_uniprot += 1
            bioentry = bioentries.get(locus)
            if bioentry is None:
                missing_locus += 1
                continue
            for accession in accessions:
                key = (locus, accession)
                if key in seen:
                    continue
                seen.add(key)
                mappings.append((bioentry, locus, accession))

        lst_path = options["lst"] or os.path.join(
            _compute_folder_path(datadir, genome_name),
            f"{genome_name}_unips.lst",
        )

        self.stdout.write(f"Rows with UniProt in TSV: {rows_with_uniprot}")
        self.stdout.write(f"Unique locus/UniProt mappings: {len(mappings)}")
        self.stdout.write(f"Missing locus tags in DB: {missing_locus}")
        self.stdout.write(f"Output list: {lst_path}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("[dry-run] No rows written."))
            return

        with transaction.atomic():
            if overwrite:
                deleted, _ = BioentryDbxref.objects.filter(
                    bioentry__biodatabase=db,
                    dbxref__dbname__in=("UnipSp", "UnipTr"),
                ).delete()
                self.stdout.write(f"Deleted existing UniProt mappings: {deleted}")

            created = 0
            existing = 0
            for bioentry, _, accession in mappings:
                dbxref, _ = Dbxref.objects.get_or_create(dbname=dbname, accession=accession)
                _, was_created = BioentryDbxref.objects.get_or_create(
                    bioentry=bioentry,
                    dbxref=dbxref,
                )
                if was_created:
                    created += 1
                else:
                    existing += 1

        os.makedirs(os.path.dirname(lst_path), exist_ok=True)
        with open(lst_path, "w", encoding="utf-8") as handle:
            for _, locus, accession in sorted(mappings, key=lambda item: (item[2], item[1])):
                handle.write(f"{accession} {locus}\n")

        self.stdout.write(f"Created BioentryDbxref rows: {created}")
        self.stdout.write(f"Existing BioentryDbxref rows: {existing}")
        self.stdout.write(self.style.SUCCESS("Curated UniProt import complete."))


def _parse_uniprot_accessions(value):
    text = str(value).strip()
    if text.lower() in UNIPROT_EMPTY_VALUES:
        return []

    accessions = []
    for raw_token in UNIPROT_TOKEN_SPLIT_RE.split(text):
        token = raw_token.strip()
        if not token or token.lower() in UNIPROT_EMPTY_VALUES:
            continue
        match = UNIPROT_PIPE_RE.match(token)
        if match:
            token = match.group(1)
        token = token.strip()
        if token and token.lower() not in UNIPROT_EMPTY_VALUES:
            accessions.append(token)
    return accessions


def _compute_folder_path(datadir, genome_name):
    acclen = len(genome_name)
    mid = genome_name[math.floor(acclen / 2 - 1): math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, mid, genome_name)
