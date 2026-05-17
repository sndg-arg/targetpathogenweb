"""
Fetch real EC / GO annotations from the UniProt REST API and persist them
using the same bioseq models that InterProScan and the demo seeder use.

Usage (from a management command or pipeline step):

    from tpweb.services.functional_annotations import fetch_and_load_uniprot_annotations
    stats = fetch_and_load_uniprot_annotations("GCF_000009045.1")
"""

import logging
import time
from pathlib import Path

import requests
from django.db import transaction

from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term
from bioseq.models.TermDbxref import TermDbxref

logger = logging.getLogger(__name__)

UNIPROT_API_BASE = "https://rest.uniprot.org/uniprotkb"
BATCH_SIZE = 100
REQUEST_TIMEOUT = 30
RETRY_WAIT = 2
MAX_RETRIES = 3


def _proteome_name(assembly_name):
    return f"{assembly_name}{Biodatabase.PROT_POSTFIX}"


def _read_uniprot_mapping(lst_path):
    """Parse a ``{genome}_unips.lst`` file.

    Returns a dict ``{uniprot_accession: locus_tag}``.
    """
    mapping = {}
    path = Path(lst_path)
    if not path.exists():
        return mapping
    with open(path, "r") as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) >= 2:
                mapping[parts[0]] = parts[1]
    return mapping


def _fetch_uniprot_batch(accessions):
    """Query the UniProt REST API for a batch of accessions.

    Returns a list of dicts with keys ``accession``, ``ec_numbers``,
    ``go_terms``, ``pdb_xrefs`` (each a list of dicts).
    """
    query = " OR ".join(f"accession:{acc}" for acc in accessions)
    params = {
        "query": query,
        "format": "json",
        "fields": "accession,ec,go_id,xref_pdb",
        "size": len(accessions),
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                f"{UNIPROT_API_BASE}/search",
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", RETRY_WAIT))
                logger.warning("UniProt rate-limited, waiting %ds", retry_after)
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return _parse_uniprot_response(resp.json())
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                logger.warning("UniProt request failed (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
                time.sleep(RETRY_WAIT * attempt)
            else:
                raise
    return []


_PDB_ACCEPTED_METHODS = {"X-RAY DIFFRACTION", "ELECTRON MICROSCOPY", "X-RAY", "EM", "CRYO-EM"}


def _parse_uniprot_response(data):
    """Extract EC, GO, and PDB xrefs from UniProt JSON search response."""
    results = []
    for entry in data.get("results", []):
        accession = entry.get("primaryAccession", "")

        # EC numbers — from proteinDescription.recommendedName.ecNumbers
        ec_numbers = []
        protein_desc = entry.get("proteinDescription", {})
        for name_block in [protein_desc.get("recommendedName", {})] + protein_desc.get("alternativeNames", []):
            for ec in name_block.get("ecNumbers", []):
                ec_val = ec.get("value", "").strip()
                if ec_val:
                    ec_numbers.append({"id": ec_val, "name": ""})
        # Also check submissionNames (for TrEMBL entries)
        for name_block in protein_desc.get("submissionNames", []):
            for ec in name_block.get("ecNumbers", []):
                ec_val = ec.get("value", "").strip()
                if ec_val:
                    ec_numbers.append({"id": ec_val, "name": ""})

        # GO terms — from uniProtKBCrossReferences with database "GO"
        go_terms = []
        # PDB xrefs — X-ray and cryo-EM only, sorted best resolution first
        pdb_xrefs = []
        for xref in entry.get("uniProtKBCrossReferences", []):
            db = xref.get("database", "")
            if db == "GO":
                go_id = xref.get("id", "").strip()
                go_name = ""
                for prop in xref.get("properties", []):
                    if prop.get("key") == "GoTerm":
                        raw = prop.get("value", "")
                        if ":" in raw:
                            go_name = raw.split(":", 1)[1].strip()
                        else:
                            go_name = raw.strip()
                if go_id:
                    go_terms.append({"id": go_id, "name": go_name})
            elif db == "PDB":
                pdb_id = xref.get("id", "").strip()
                if not pdb_id:
                    continue
                method = ""
                resolution = None
                for prop in xref.get("properties", []):
                    key = prop.get("key", "")
                    val = prop.get("value", "").strip()
                    if key == "Method":
                        method = val.upper()
                    elif key == "Resolution":
                        try:
                            resolution = float(val.replace(" A", "").replace("A", ""))
                        except (ValueError, TypeError):
                            pass
                # Accept X-ray and cryo-EM; skip NMR and unknown
                if any(m in method for m in ("X-RAY", "DIFFRACTION", "ELECTRON", "MICROSCOPY", "CRYO")):
                    pdb_xrefs.append({
                        "id": pdb_id,
                        "method": method,
                        "resolution": resolution,
                    })

        # Sort best resolution first (None last)
        pdb_xrefs.sort(key=lambda x: (x["resolution"] is None, x["resolution"] or 999))

        results.append({
            "accession": accession,
            "ec_numbers": ec_numbers,
            "go_terms": go_terms,
            "pdb_xrefs": pdb_xrefs,
        })
    return results


def _persist_annotations(protein, annotations, dbname, ontology):
    """Create Dbxref + BioentryDbxref + Term + TermDbxref for a list of annotations."""
    created = 0
    for ann in annotations:
        accession = ann["id"]
        definition = ann.get("name", "")

        dbxref, _ = Dbxref.objects.get_or_create(
            dbname=dbname,
            accession=accession,
            defaults={"version": 0},
        )
        _, was_created = BioentryDbxref.objects.get_or_create(
            bioentry=protein,
            dbxref=dbxref,
            defaults={"rank": 0},
        )
        if was_created:
            created += 1

        term, _ = Term.objects.get_or_create(
            ontology=ontology,
            identifier=accession,
            defaults={
                "name": accession,
                "definition": definition,
                "version": 0,
                "is_obsolete": "N",
            },
        )
        if definition and not term.definition:
            term.definition = definition
            term.save(update_fields=["definition"])

        TermDbxref.objects.get_or_create(term=term, dbxref=dbxref, defaults={"rank": 0})

    return created


def _persist_pdb_xrefs(protein, pdb_xrefs):
    """Store PDB cross-references for a protein. rank = resolution * 100 (lower = better)."""
    for xref in pdb_xrefs:
        pdb_id = xref["id"]
        resolution = xref.get("resolution")
        rank = int(resolution * 100) if resolution is not None else 9999
        dbxref, _ = Dbxref.objects.get_or_create(
            dbname="PDB",
            accession=pdb_id,
            defaults={"version": 0},
        )
        BioentryDbxref.objects.get_or_create(
            bioentry=protein,
            dbxref=dbxref,
            defaults={"rank": rank},
        )


def fetch_and_load_uniprot_annotations(assembly_name, lst_path=None, datadir=None):
    """Main entry point: fetch EC/GO from UniProt for mapped proteins.

    Parameters
    ----------
    assembly_name : str
        Genome accession (e.g. ``"GCF_000009045.1"``).
    lst_path : str or Path, optional
        Path to ``{genome}_unips.lst``. If not given, derived from *datadir*.
    datadir : str or Path, optional
        Base data directory (used to locate ``_unips.lst`` when *lst_path*
        is not provided).

    Returns
    -------
    dict with counts of created links.
    """
    import math

    if lst_path is None:
        if datadir is None:
            raise ValueError("Either lst_path or datadir must be provided")
        datadir = Path(datadir)
        acclen = len(assembly_name)
        folder_name = assembly_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
        lst_path = datadir / folder_name / assembly_name / f"{assembly_name}_unips.lst"

    uniprot_mapping = _read_uniprot_mapping(lst_path)
    if not uniprot_mapping:
        logger.warning("No UniProt mapping found at %s — skipping annotation fetch", lst_path)
        return {"ec_created": 0, "go_created": 0, "proteins_annotated": 0, "proteins_total": 0}

    proteome_name = _proteome_name(assembly_name)
    proteins_by_locus = {
        p.accession: p
        for p in Bioentry.objects.filter(biodatabase__name=proteome_name)
    }

    ec_ontology, _ = Ontology.objects.get_or_create(name=Ontology.EC, defaults={"definition": ""})
    go_ontology, _ = Ontology.objects.get_or_create(name=Ontology.GO, defaults={"definition": ""})

    uniprot_accessions = list(uniprot_mapping.keys())
    total_ec = 0
    total_go = 0
    proteins_annotated = 0

    for i in range(0, len(uniprot_accessions), BATCH_SIZE):
        batch = uniprot_accessions[i:i + BATCH_SIZE]
        logger.info(
            "Fetching UniProt batch %d–%d of %d",
            i + 1, min(i + BATCH_SIZE, len(uniprot_accessions)), len(uniprot_accessions),
        )

        try:
            entries = _fetch_uniprot_batch(batch)
        except Exception as exc:
            logger.error("Failed to fetch UniProt batch starting at %d: %s", i, exc)
            continue

        with transaction.atomic():
            for entry in entries:
                uniprot_acc = entry["accession"]
                locus_tag = uniprot_mapping.get(uniprot_acc)
                if not locus_tag:
                    continue
                protein = proteins_by_locus.get(locus_tag)
                if not protein:
                    logger.debug("Locus tag %s not found in DB for UniProt %s", locus_tag, uniprot_acc)
                    continue

                ec_created = _persist_annotations(protein, entry["ec_numbers"], "ec", ec_ontology)
                go_created = _persist_annotations(protein, entry["go_terms"], Ontology.GO, go_ontology)
                _persist_pdb_xrefs(protein, entry.get("pdb_xrefs", []))

                total_ec += ec_created
                total_go += go_created
                if ec_created or go_created:
                    proteins_annotated += 1

        # Be kind to UniProt API
        if i + BATCH_SIZE < len(uniprot_accessions):
            time.sleep(0.5)

    stats = {
        "ec_created": total_ec,
        "go_created": total_go,
        "proteins_annotated": proteins_annotated,
        "proteins_total": len(uniprot_mapping),
    }
    logger.info("UniProt annotation fetch complete for %s: %s", assembly_name, stats)
    return stats
