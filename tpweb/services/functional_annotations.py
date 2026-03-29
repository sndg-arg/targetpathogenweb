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
    ``go_terms`` (each a list of ``{id, name}``).
    """
    query = " OR ".join(f"accession:{acc}" for acc in accessions)
    params = {
        "query": query,
        "format": "json",
        "fields": "accession,ec,go_id",
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


def _parse_uniprot_response(data):
    """Extract EC and GO from UniProt JSON search response."""
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
        for xref in entry.get("uniProtKBCrossReferences", []):
            if xref.get("database") == "GO":
                go_id = xref.get("id", "").strip()
                go_name = ""
                for prop in xref.get("properties", []):
                    if prop.get("key") == "GoTerm":
                        raw = prop.get("value", "")
                        # Format: "C:cytoplasm" or "F:binding" or "P:transport"
                        if ":" in raw:
                            go_name = raw.split(":", 1)[1].strip()
                        else:
                            go_name = raw.strip()
                if go_id:
                    go_terms.append({"id": go_id, "name": go_name})

        results.append({
            "accession": accession,
            "ec_numbers": ec_numbers,
            "go_terms": go_terms,
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
