import csv
import math
import os
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue


DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")
AFDB_MODEL_URL = "https://alphafold.ebi.ac.uk/files/AF-{accession}-F1-model_v4.pdb"
SELECTED_FIELDS = (
    ("FPocket", "best_fpocket_structure", "Druggability", "fpocket_pocket"),
    ("P2Rank", "best_p2rank_structure", "p2rank_probability", "p2rank_pocket"),
)
MANIFEST_COLUMNS = [
    "genome", "locus", "uniprot_accession", "selected_by",
    "need_fpocket", "need_p2rank", "fpocket_score", "fpocket_pocket",
    "p2rank_score", "p2rank_pocket", "model_url", "loaded_structure_codes",
]


def clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def norm_source(value):
    value = clean(value).upper()
    for prefix in ("AF_", "CB_"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def is_pdb_code(value):
    value = clean(value).upper()
    return len(value) == 4 and value.isalnum()


def is_alphafold_uniprot_source(value):
    value = clean(value).upper()
    if not value or is_pdb_code(value) or value.startswith("CB_"):
        return False
    if value.startswith("AF_") or value.startswith("A0A"):
        return True
    if len(value) == 6 and value[0].isalpha() and value[1].isdigit() and value[-1].isdigit():
        return True
    return False


def folder_path(datadir, genome_name):
    acclen = len(genome_name)
    folder_name = genome_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, folder_name, genome_name)


def is_loaded(accession, loaded_codes):
    accession = accession.upper()
    for code in loaded_codes:
        code = code.upper()
        if code == accession or code == f"AF_{accession}":
            return True
        if code.startswith(f"AF_{accession}_") or code.startswith(f"AF_{accession}-"):
            return True
    return False


class Command(BaseCommand):
    help = "Report/export curated selected AlphaFold/UniProt sources for model backfill."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--datadir", default=DEFAULT_DATA_DIR)
        parser.add_argument(
            "--output-tsv",
            default=None,
            help="Manifest path. Defaults to <genome data>/selected_alphafold_jobs/<genome>_selected_alphafold.tsv.",
        )
        parser.add_argument(
            "--include-loaded",
            action="store_true",
            help="Include selected AlphaFold/UniProt sources already loaded in TPW.",
        )
        parser.add_argument("--examples", type=int, default=20)

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        include_loaded = options["include_loaded"]
        examples_limit = options["examples"]

        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=proteome_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {proteome_name}") from exc

        proteins = Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")
        protein_accessions = dict(proteins.values_list("bioentry_id", "accession"))
        protein_ids = set(protein_accessions)
        if not protein_ids:
            self.stdout.write("No proteins found.")
            return

        score_names = set()
        for _method, source_field, score_field, pocket_field in SELECTED_FIELDS:
            score_names.update([source_field, score_field, pocket_field])

        scores = defaultdict(dict)
        for spv in ScoreParamValue.objects.filter(
            bioentry_id__in=protein_ids,
            score_param__name__in=score_names,
        ).select_related("score_param"):
            value = spv.value if spv.value else (
                str(spv.numeric_value) if spv.numeric_value is not None else ""
            )
            scores[spv.bioentry_id][spv.score_param.name] = clean(value)

        loaded_codes = defaultdict(set)
        for link in BioentryStructure.objects.filter(bioentry_id__in=protein_ids).select_related("pdb"):
            loaded_codes[link.bioentry_id].add(clean(link.pdb.code).upper())

        rows = {}
        selected_rows = loaded_rows = missing_rows = 0
        unique_sources = set()
        examples = []

        for protein_id, locus in protein_accessions.items():
            row_scores = scores.get(protein_id, {})
            for method, source_field, score_field, pocket_field in SELECTED_FIELDS:
                source = row_scores.get(source_field, "")
                if not is_alphafold_uniprot_source(source):
                    continue

                accession = norm_source(source)
                selected_rows += 1
                unique_sources.add(accession)
                loaded = is_loaded(accession, loaded_codes.get(protein_id, set()))
                if loaded:
                    loaded_rows += 1
                else:
                    missing_rows += 1
                    if len(examples) < examples_limit:
                        examples.append((locus, method, accession, row_scores.get(score_field, ""), row_scores.get(pocket_field, "")))

                if loaded and not include_loaded:
                    continue

                key = (protein_id, accession)
                row = rows.setdefault(key, {
                    "genome": genome_name,
                    "locus": locus,
                    "uniprot_accession": accession,
                    "selected_by": [],
                    "need_fpocket": False,
                    "need_p2rank": False,
                    "fpocket_score": "",
                    "fpocket_pocket": "",
                    "p2rank_score": "",
                    "p2rank_pocket": "",
                    "model_url": AFDB_MODEL_URL.format(accession=accession),
                    "loaded_structure_codes": ",".join(sorted(loaded_codes.get(protein_id, set()))),
                })
                row["selected_by"].append(method)
                if method == "FPocket":
                    row["need_fpocket"] = True
                    row["fpocket_score"] = row_scores.get(score_field, "")
                    row["fpocket_pocket"] = row_scores.get(pocket_field, "")
                else:
                    row["need_p2rank"] = True
                    row["p2rank_score"] = row_scores.get(score_field, "")
                    row["p2rank_pocket"] = row_scores.get(pocket_field, "")

        export_rows = []
        for row in rows.values():
            row = dict(row)
            row["selected_by"] = ",".join(row["selected_by"])
            row["need_fpocket"] = str(row["need_fpocket"]).lower()
            row["need_p2rank"] = str(row["need_p2rank"]).lower()
            export_rows.append(row)
        export_rows.sort(key=lambda row: (row["locus"], row["uniprot_accession"]))

        output_tsv = options["output_tsv"]
        if output_tsv is None:
            output_dir = os.path.join(folder_path(datadir, genome_name), "selected_alphafold_jobs")
            os.makedirs(output_dir, exist_ok=True)
            output_tsv = os.path.join(output_dir, f"{genome_name}_selected_alphafold.tsv")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(output_tsv)), exist_ok=True)

        with open(output_tsv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(export_rows)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Selected AlphaFold/UniProt report for {genome_name}"
        ))
        self.stdout.write(f"Proteins: {len(protein_ids)}")
        self.stdout.write(f"Selected AlphaFold/UniProt rows: {selected_rows}")
        self.stdout.write(f"Unique AlphaFold/UniProt accessions: {len(unique_sources)}")
        self.stdout.write(f"Already loaded rows: {loaded_rows}")
        self.stdout.write(f"Missing rows: {missing_rows}")
        self.stdout.write(f"Exported model jobs: {len(export_rows)}")
        if examples:
            self.stdout.write("Missing examples:")
            for locus, method, accession, score, pocket in examples:
                self.stdout.write(f"  {locus} {method} {accession} score={score or '-'} pocket={pocket or '-'}")
        self.stdout.write(f"Manifest: {output_tsv}")
