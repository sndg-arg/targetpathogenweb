"""Load Bgee expression for every curated human protein, at proteome scale.

Scale companion to `import_human_curated_proteins.py`'s per-protein
`_load_expression` (which reads a per-accession `Bgee-genex-heatmap.tsv`
for the 10-protein pilot). At full-proteome scale there is one bulk file
for the whole species instead:

    https://www.bgee.org/ftp/current/download/calls/expr_calls/Homo_sapiens_expr_simple.tsv.gz

(~170MB gzipped; one row per (Ensembl gene, anatomical entity) with
"Expression" present/absent, "Call quality", "FDR", "Expression score").
Fetched by `scripts/cluster/fetch_human_proteome_bulk.sh` on the login node;
this command only reads the local file, streamed, never loaded whole.

Genes are matched to proteins through the cross-references the UniProt
ingest already stored: the `Bgee` xref (bare Ensembl gene id), falling back
to the `GeneId` property of `Ensembl` transcript xrefs (version suffix
dropped). Rows are written in the same shape the pilot loader writes to
`HumanProtein.expression_json`, so `human_expression_summary` renders both
unchanged (anatomical entity -> "tissue"; the bulk file has no separate cell
type column).

Usage:
    python manage.py load_human_expression_bulk --bgee-tsv PATH \
        [--accession P00533 ...] [--accession-file PATH] [--dry-run]
"""

import csv
import gzip
import io

from django.core.management.base import BaseCommand, CommandError

from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_targets import human_proteins_queryset

WRITE_BATCH = 500


def _ensembl_gene_ids(cross_references_raw):
    """Bare Ensembl gene ids (ENSG..., no version) for one protein, from its
    stored UniProt cross-references. Pure function."""
    gene_ids = set()
    for xref in cross_references_raw or []:
        database = xref.get("database")
        if database == "Bgee":
            value = (xref.get("id") or "").strip()
            if value:
                gene_ids.add(value.split(".")[0])
        elif database == "Ensembl":
            for prop in xref.get("properties") or []:
                if prop.get("key") == "GeneId" and prop.get("value"):
                    gene_ids.add(prop["value"].strip().split(".")[0])
    return gene_ids


def _expression_row(row):
    """One Bgee bulk row -> the expression_json shape the pilot loader writes,
    or None when it has no usable score. Pure function."""
    try:
        score = float((row.get("Expression score") or "").strip())
    except ValueError:
        return None
    return {
        "tissue": (row.get("Anatomical entity name") or "").strip(),
        "cell_type": "",
        "score": score,
        "confidence": "",
        "quality": (row.get("Call quality") or "").strip(),
        "fdr": (row.get("FDR") or "").strip(),
        "data_types": "",
        "state": (row.get("Expression") or "").strip(),
        "cluster": "",
    }


def _iter_gene_blocks(handle):
    """Yield (gene_id, [rows]) from the Bgee bulk TSV, one gene at a time.
    The file is sorted by gene id; a gene seen again later (not expected)
    simply yields a second block, which the caller merges."""
    reader = csv.DictReader(handle, delimiter="\t")
    current, rows = None, []
    for raw in reader:
        gene_id = (raw.get("Gene ID") or "").strip()
        if gene_id != current:
            if current is not None:
                yield current, rows
            current, rows = gene_id, []
        parsed = _expression_row(raw)
        if parsed is not None:
            rows.append(parsed)
    if current is not None:
        yield current, rows


def _open_text(path):
    if str(path).endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, encoding="utf-8", newline="")


class Command(BaseCommand):
    help = (
        "Load Bgee expression (bulk per-species TSV) into every curated human "
        "protein's expression_json, matched by Ensembl gene id."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bgee-tsv",
            required=True,
            metavar="PATH",
            help="Homo_sapiens_expr_simple.tsv(.gz) from Bgee's bulk download.",
        )
        parser.add_argument(
            "--accession",
            action="append",
            default=None,
            help="Restrict to this accession. Repeatable. Default: every curated human protein.",
        )
        parser.add_argument(
            "--accession-file",
            default=None,
            metavar="PATH",
            help="Newline-separated file of accessions, added to --accession.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Read and match, but write nothing."
        )

    def handle(self, *args, **options):
        accessions = list(options["accession"] or [])
        if options["accession_file"]:
            with open(options["accession_file"], encoding="utf-8") as f:
                accessions.extend(line.strip() for line in f if line.strip())

        proteins_qs = human_proteins_queryset()
        if accessions:
            proteins_qs = proteins_qs.filter(uniprot_accession__in=accessions)
        # values_list, not instances: full rows carry uniprot_raw and every
        # other JSON field (see load_human_pathways_bulk's OOM note).
        gene_to_proteins = {}
        protein_count = 0
        for protein_id, cross_refs in proteins_qs.values_list(
            "id", "cross_references_raw"
        ).iterator():
            protein_count += 1
            for gene_id in _ensembl_gene_ids(cross_refs):
                gene_to_proteins.setdefault(gene_id, []).append(protein_id)
        if not protein_count:
            raise CommandError("No matching human proteins found.")
        self.stdout.write(
            f"{protein_count} proteins, {len(gene_to_proteins)} distinct Ensembl genes. "
            f"Reading {options['bgee_tsv']} ..."
        )

        pending = {}
        written_ids = set()
        matched_genes = 0

        def flush():
            if not pending:
                return
            if not options["dry_run"]:
                # A protein mapped to two genes can come back in a later batch:
                # append to what this run already wrote instead of replacing it.
                repeats = [pk for pk in pending if pk in written_ids]
                if repeats:
                    for pk, existing in HumanProtein.objects.filter(id__in=repeats).values_list(
                        "id", "expression_json"
                    ):
                        pending[pk] = list(existing or []) + pending[pk]
                objs = [HumanProtein(id=pk, expression_json=rows) for pk, rows in pending.items()]
                HumanProtein.objects.bulk_update(objs, ["expression_json"], batch_size=WRITE_BATCH)
            written_ids.update(pending)
            pending.clear()

        try:
            handle = _open_text(options["bgee_tsv"])
        except OSError as exc:
            raise CommandError(f"Could not open {options['bgee_tsv']}: {exc}") from exc
        with handle:
            for gene_id, rows in _iter_gene_blocks(handle):
                protein_ids = gene_to_proteins.get(gene_id)
                if not protein_ids or not rows:
                    continue
                matched_genes += 1
                for pk in protein_ids:
                    pending.setdefault(pk, []).extend(rows)
                if len(pending) >= WRITE_BATCH:
                    flush()
        flush()

        verb = "would update" if options["dry_run"] else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{matched_genes} genes matched; {verb} expression for {len(written_ids)} proteins."
            )
        )
