"""BLAST a query against one or more genomes and annotate the hits.

Each genome has its own BLAST db (index_genome_seq_clean builds them at
pipeline stage 9), so a multi-genome search is one run per genome. Every
tabular row gets the genome's name appended as a last column, which is how
the result pages know which genome a hit belongs to.
"""

import logging
import os
import subprocess as sp
import time
import uuid

from django.conf import settings

from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryQualifierValue import BioentryQualifierValue
from tpweb.services.genome_workspace import display_genome_name

logger = logging.getLogger(__name__)

_PROGRAMS = {
    "nucleotide": {
        "bin_setting": "BLASTN_PATH",
        "bin_default": "blastn",
        "db": "genes_fna",
        "args": ["-evalue", "1e-6", "-outfmt", "6"],
    },
    "protein": {
        "bin_setting": "BLASTP_PATH",
        "bin_default": "blastp",
        "db": "faa",
        "args": [
            "-evalue",
            "1e-5",
            "-max_target_seqs",
            "20",
            "-outfmt",
            "6 qseqid sseqid pident length mismatch evalue bitscore",
        ],
    },
}


class BlastError(Exception):
    """A BLAST run that failed; the message is shown to the user as is."""


def max_genomes_per_search():
    return int(os.environ.get("TPW_BLAST_MAX_GENOMES", "10"))


def run_blast(kind, query_text, genome_names, result_dir):
    """Run the query against each genome and return its tabular rows (genome
    name appended), best bit score first. TPW_BLAST_TIMEOUT_SEC bounds the
    whole search, not each genome."""
    spec = _PROGRAMS[kind]
    try:
        store = SeqStore(settings.SEQS_DATA_DIR)
        db_locations = [(name, getattr(store, spec["db"])(name)) for name in genome_names]
    except Exception as exc:
        logger.exception("BLAST setup failed for %s", genome_names)
        raise BlastError("BLAST is unavailable right now. Please try again later.") from exc

    blast_bin = getattr(settings, spec["bin_setting"], spec["bin_default"])
    timeout_seconds = int(os.environ.get("TPW_BLAST_TIMEOUT_SEC", "60"))
    deadline = time.monotonic() + timeout_seconds
    run_id = uuid.uuid4()
    query_path = result_dir / f"{run_id}.query"
    output_path = result_dir / f"{run_id}.out"
    rows = []
    try:
        query_path.write_text(query_text, encoding="utf-8")
        for genome_name, db_location in db_locations:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise sp.TimeoutExpired(blast_bin, timeout_seconds)
            cmd = [
                blast_bin,
                "-query",
                str(query_path),
                "-db",
                db_location,
                "-num_threads",
                "2",
                "-out",
                str(output_path),
                *spec["args"],
            ]
            sp.check_output(cmd, stderr=sp.STDOUT, timeout=remaining)
            raw = (
                output_path.read_text(encoding="utf-8", errors="replace")
                if output_path.is_file()
                else ""
            )
            rows.extend(f"{line}\t{genome_name}" for line in raw.splitlines() if line.strip())
    except sp.TimeoutExpired as exc:
        raise BlastError(f"BLAST query timed out after {timeout_seconds} seconds.") from exc
    except sp.CalledProcessError as exc:
        details = exc.output.decode("utf-8", errors="replace") if exc.output else str(exc)
        raise BlastError(f"BLAST query failed. {details}") from exc
    except OSError as exc:
        raise BlastError(f"BLAST executable is unavailable. {exc}") from exc
    finally:
        query_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

    # Bit score is the last BLAST column (just before the genome) in both formats.
    rows.sort(key=lambda row: _float(row.split("\t")[-2]), reverse=True)
    return rows


def _float(value):
    try:
        return float(value)
    except ValueError:
        return 0.0


def annotate_blast_hits(hits, genome_names):
    """Attach each hit's protein, gene name and genome label. Hits carry a
    "genome" key; only genomes in genome_names (the ones the user may see)
    are looked up."""
    from tpweb.views.ProteinView import PROTEIN_ACCESSION_RE

    genome_by_proteome = {name + Biodatabase.PROT_POSTFIX: name for name in genome_names}
    proteins = {
        (genome_by_proteome[protein.biodatabase.name], protein.accession): protein
        for protein in Bioentry.objects.select_related("biodatabase").filter(
            biodatabase__name__in=genome_by_proteome,
            accession__in={hit["subject_id"] for hit in hits},
        )
    }
    genes = {}
    for bioentry_id, value in BioentryQualifierValue.objects.filter(
        bioentry__in=[protein.bioentry_id for protein in proteins.values()],
        term__identifier="gene",
    ).values_list("bioentry_id", "value"):
        genes.setdefault(bioentry_id, []).append(value)

    for hit in hits:
        genome = hit.get("genome") or ""
        protein = proteins.get((genome, hit["subject_id"])) if genome in genome_names else None
        hit["protein"] = protein
        hit["genome_label"] = display_genome_name(genome) if genome else ""
        # Same rule as the protein page: gene qualifiers that hold a protein
        # ID (WP_..., the accession itself) are not gene names.
        hit["gene"] = (
            " ".join(
                gene
                for gene in genes.get(protein.bioentry_id, [])
                if gene != protein.accession and not PROTEIN_ACCESSION_RE.match(gene)
            )
            if protein
            else ""
        )
    return hits
