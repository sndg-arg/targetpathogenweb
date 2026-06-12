import csv
import os
import shlex
import tarfile
from pathlib import Path

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from django.core.management import CommandError, call_command


KNOWN_ARCHIVE_DIRS = {"genome", "structures", "offtarget", "essentiality", "ligq2", "LigQ_2", "ligq_2"}
GBK_SUFFIXES = (".gbk", ".gbk.gz", ".gbff", ".gbff.gz")


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


def _archive_summary(archive, archive_root=""):
    if not archive:
        return {
            "provided": False,
            "exists": False,
            "root": archive_root or "",
            "folders": [],
            "gbk_candidates": 0,
            "ligq_like_files": 0,
        }

    path = Path(archive)
    if not path.is_file():
        return {
            "provided": True,
            "exists": False,
            "root": archive_root or "",
            "folders": [],
            "gbk_candidates": 0,
            "ligq_like_files": 0,
        }

    folders = set()
    gbk_candidates = 0
    ligq_like_files = 0
    root = archive_root.strip("/\\") if archive_root else ""

    try:
        with tarfile.open(path, "r:*") as tar:
            members = [m.name.replace("\\", "/").strip("/") for m in tar.getmembers() if m.name]
    except tarfile.TarError as exc:
        raise CommandError(f"Could not read archive {archive}: {exc}") from exc

    if not root:
        first_parts = {name.split("/", 1)[0] for name in members if name}
        if len(first_parts) == 1:
            root = next(iter(first_parts))

    for name in members:
        rel = name
        if root and rel == root:
            continue
        if root and rel.startswith(root + "/"):
            rel = rel[len(root) + 1 :]
        if not rel:
            continue
        first = rel.split("/", 1)[0]
        if first in KNOWN_ARCHIVE_DIRS:
            folders.add(first)
        lower = rel.lower()
        if lower.endswith(GBK_SUFFIXES):
            gbk_candidates += 1
        if "ligq" in lower and lower.endswith((".tsv", ".csv")):
            ligq_like_files += 1

    return {
        "provided": True,
        "exists": True,
        "root": root,
        "folders": sorted(folders),
        "gbk_candidates": gbk_candidates,
        "ligq_like_files": ligq_like_files,
    }


def validate_external_import(
    genome_name,
    results_tsv,
    structures_dir="",
    datadir="",
    ligq_output_dir="",
    archive="",
    archive_root="",
):
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
    archive_info = _archive_summary(archive, archive_root)

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
        "archive": archive_info,
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
    archive="",
    archive_root="",
):
    if include_plan or archive:
        parts = [
            "python",
            "manage.py",
            "run_curated_file_import",
            "--genome",
            genome_name,
            "--results-tsv",
            results_tsv,
        ]
        if datadir:
            parts.extend(["--datadir", datadir])
        if structures_dir:
            parts.extend(["--structures-dir", structures_dir])
        if archive:
            parts.extend(["--archive", archive])
        if archive_root:
            parts.extend(["--archive-root", archive_root])
        if ligq_output_dir:
            parts.extend(["--ligq-output-dir", ligq_output_dir])
        if overwrite:
            parts.append("--overwrite-scores")
        if not load_ligq_output:
            parts.append("--skip-ligq")
        if include_plan:
            parts.append("--execute")
            if archive:
                parts.append("--extract")
        return " ".join(shlex.quote(str(part)) for part in parts)

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
