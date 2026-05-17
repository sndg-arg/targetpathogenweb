"""
Fetch and load experimental protein structures from RCSB PDB.

For each protein in a genome that has PDB cross-references stored in
BioentryDbxref (populated by functional_annotations.py during stage 13),
this service downloads the best available experimental structure and loads
it into the database using the load_af_model command with --experiment EX.

"Best" means lowest resolution (highest quality) among X-ray/cryo-EM entries.
Resolution is pre-ranked during UniProt fetch: rank = int(resolution * 100).
"""

import logging
import math
import os
import subprocess
import sys
import time

import requests

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BioentryDbxref import BioentryDbxref

logger = logging.getLogger(__name__)

RCSB_DOWNLOAD_URL = "https://files.rcsb.org/download/{pdb_id}.pdb"
REQUEST_TIMEOUT = 30
RETRY_WAIT = 2
MAX_RETRIES = 3


def _download_pdb(pdb_id, dest_path):
    """Download a PDB file from RCSB. Returns True on success."""
    url = RCSB_DOWNLOAD_URL.format(pdb_id=pdb_id.upper())
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            if resp.status_code == 404:
                logger.warning("PDB %s not found at RCSB (404)", pdb_id)
                return False
            resp.raise_for_status()
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
            if os.path.getsize(dest_path) < 100:
                logger.warning("PDB %s download looks empty (%d bytes)", pdb_id, os.path.getsize(dest_path))
                os.remove(dest_path)
                return False
            return True
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                logger.warning("Download attempt %d/%d failed for PDB %s: %s", attempt, MAX_RETRIES, pdb_id, exc)
                time.sleep(RETRY_WAIT * attempt)
            else:
                logger.error("All download attempts failed for PDB %s: %s", pdb_id, exc)
    return False


def fetch_and_load_experimental_structures(assembly_name, folder_path, working_dir):
    """Download the best experimental PDB structure for each protein in the genome.

    Reads PDB xrefs from BioentryDbxref (dbname="PDB", rank=resolution*100).
    Downloads the best (lowest rank) structure per protein from RCSB.
    Loads each into the database via the load_af_model management command
    with --experiment EX.

    Returns a dict with keys: downloaded, loaded, skipped, total.
    """
    proteome_name = f"{assembly_name}{Biodatabase.PROT_POSTFIX}"

    # Get best PDB per protein (lowest rank = best resolution)
    pdb_xrefs = (
        BioentryDbxref.objects
        .select_related("bioentry", "dbxref")
        .filter(bioentry__biodatabase__name=proteome_name, dbxref__dbname="PDB")
        .order_by("bioentry_id", "rank")
    )

    best_per_protein = {}  # {bioentry_id: (protein_accession, pdb_id)}
    for xref in pdb_xrefs:
        bid = xref.bioentry_id
        if bid not in best_per_protein:
            best_per_protein[bid] = (xref.bioentry.accession, xref.dbxref.accession)

    total = len(best_per_protein)
    if not total:
        logger.info("No PDB xrefs found for genome %s — skipping experimental structures", assembly_name)
        return {"downloaded": 0, "loaded": 0, "skipped": 0, "total": 0}

    logger.info("Fetching experimental structures for %d proteins in %s", total, assembly_name)

    exp_dir = os.path.join(folder_path, "experimental")
    datadir = os.path.join(working_dir, "data")
    python_bin = sys.executable

    downloaded = 0
    loaded = 0
    skipped = 0

    for locus_tag, pdb_id in best_per_protein.values():
        dest_dir = os.path.join(exp_dir, locus_tag)
        dest_path = os.path.join(dest_dir, f"{pdb_id}.pdb")

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 100:
            logger.debug("PDB %s already on disk for %s", pdb_id, locus_tag)
        else:
            logger.info("Downloading PDB %s for %s", pdb_id, locus_tag)
            if not _download_pdb(pdb_id, dest_path):
                skipped += 1
                continue
            downloaded += 1

        cmd = (
            f"{python_bin} {working_dir}/manage.py load_af_model"
            f" {pdb_id} {dest_path} {locus_tag}"
            f" --experiment EX --overwrite --datadir {datadir}"
        )
        result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("load_af_model failed for PDB %s / %s: %s", pdb_id, locus_tag, result.stderr[-500:])
            skipped += 1
        else:
            loaded += 1
            logger.debug("Loaded PDB %s for %s", pdb_id, locus_tag)

    stats = {"downloaded": downloaded, "loaded": loaded, "skipped": skipped, "total": total}
    logger.info("Experimental structures complete for %s: %s", assembly_name, stats)
    return stats
