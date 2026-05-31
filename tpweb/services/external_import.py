import csv
import os
from pathlib import Path

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from django.core.management import CommandError, call_command


def _read_tsv_genes(path, max_preview=8):
    genes = []
    columns = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        columns = list(reader.fieldnames or [])
        if "gene" not in columns:
            raise CommandError("Results TSV must include a 'gene' column.")
        for row in reader:
            gene = str(row.get("gene") or "").strip()
            if gene:
                genes.append(gene)
    return {
        "count": len(genes),
        "unique_count": len(set(genes)),
        "preview": genes[:max_preview],
        "columns": columns,
        "genes": genes,
    }


def _structure_summary(structures_dir):
    if not structures_dir:
        return {
            "provided": False,
            "exists": False,
            "protein_dirs": 0,
            "pdb_files": 0,
        }

    path = Path(structures_dir)
    if not path.is_dir():
        return {
            "provided": True,
            "exists": False,
            "protein_dirs": 0,
            "pdb_files": 0,
        }

    protein_dirs = [p for p in path.iterdir() if p.is_dir()]
    pdb_files = 0
    for protein_dir in protein_dirs:
        locus_tag = protein_dir.name
        if (protein_dir / f"CB_{locus_tag}_relaxed1.pdb").is_file():
            pdb_files += 1

    return {
        "provided": True,
        "exists": True,
        "protein_dirs": len(protein_dirs),
        "pdb_files": pdb_files,
    }


def _ligq_output_summary(ligq_output_dir):
    if not ligq_output_dir:
        return {
            "provided": False,
            "exists": False,
            "known_files": 0,
            "predicted_files": 0,
            "zinc_files": 0,
            "summary_exists": False,
        }

    path = Path(ligq_output_dir)
    if not path.is_dir():
        return {
            "provided": True,
            "exists": False,
            "known_files": 0,
            "predicted_files": 0,
            "zinc_files": 0,
            "summary_exists": False,
        }

    return {
        "provided": True,
        "exists": True,
        "known_files": sum(1 for _ in path.rglob("known_ligands.tsv")),
        "predicted_files": sum(1 for _ in path.rglob("predicted_ligands.tsv")),
        "zinc_files": sum(1 for _ in path.rglob("zinc_ligands.tsv")),
        "summary_exists": (path / "search_results_summary.tsv").is_file(),
    }


def validate_external_import(genome_name, results_tsv, structures_dir="", datadir="", ligq_output_dir=""):
    protein_db_name = genome_name + Biodatabase.PROT_POSTFIX
    protein_db = Biodatabase.objects.filter(name=protein_db_name).first()
    if protein_db is None:
        raise CommandError(f"Genome '{genome_name}' is not loaded in TPW.")

    if not os.path.isfile(results_tsv):
        raise CommandError(f"Results TSV not found: {results_tsv}")

    if datadir and not os.path.isdir(datadir):
        raise CommandError(f"Data directory not found: {datadir}")

    tsv = _read_tsv_genes(results_tsv)
    genes = set(tsv["genes"])
    matched = Bioentry.objects.filter(
        biodatabase=protein_db,
        accession__in=genes,
    ).count()
    protein_total = Bioentry.objects.filter(biodatabase=protein_db).count()
    missing_from_tpw = max(tsv["unique_count"] - matched, 0)

    structures = _structure_summary(structures_dir)
    ligq_output = _ligq_output_summary(ligq_output_dir)

    return {
        "genome_name": genome_name,
        "protein_database": protein_db_name,
        "protein_total": protein_total,
        "results_tsv": results_tsv,
        "tsv_rows": tsv["count"],
        "tsv_unique_genes": tsv["unique_count"],
        "tsv_columns": tsv["columns"],
        "tsv_preview": tsv["preview"],
        "matched_proteins": matched,
        "missing_from_tpw": missing_from_tpw,
        "structures": structures,
        "ligq_output": ligq_output,
    }


def build_external_import_command(
    genome_name,
    results_tsv,
    structures_dir="",
    datadir="",
    overwrite=True,
    ligq_output_dir="",
    load_ligq_output=False,
    include_plan=False,
):
    parts = [
        "python manage.py import_external_results",
        genome_name,
        "--results-tsv",
        results_tsv,
    ]
    if structures_dir:
        parts.extend(["--structures-dir", structures_dir])
    if datadir:
        parts.extend(["--datadir", datadir])
    if overwrite:
        parts.append("--overwrite")
    command = " ".join(parts)
    if load_ligq_output and ligq_output_dir:
        command += f" && python manage.py load_ligq_2_results {ligq_output_dir}"
    if include_plan:
        command += (
            " && python manage.py curated_pipeline_plan "
            f"{genome_name} --results-tsv {results_tsv}"
        )
        if datadir:
            command += f" --datadir {datadir}"
    return command


def run_external_import(genome_name, results_tsv, structures_dir="", datadir="", overwrite=True):
    options = {
        "results_tsv": results_tsv,
        "datadir": datadir,
        "overwrite": overwrite,
    }
    if structures_dir:
        options["structures_dir"] = structures_dir
    call_command("import_external_results", genome_name, **options)
