"""
Fetch real EC / GO annotations from the UniProt REST API and persist them
using the same bioseq models that InterProScan and the demo seeder use.

Usage (from a management command or pipeline step):

    from tpweb.services.functional_annotations import fetch_and_load_uniprot_annotations
    stats = fetch_and_load_uniprot_annotations("GCF_000009045.1")
"""

import logging
import time
import re
from collections import defaultdict
from pathlib import Path

import requests
from Bio.Align import PairwiseAligner
from django.db import transaction

from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term
from bioseq.models.TermDbxref import TermDbxref
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref
from tpweb.models.pdb import Atom, PDBResidueSet, Residue, ResidueSet, ResidueSetResidue, AtomResidueSet

logger = logging.getLogger(__name__)

UNIPROT_API_BASE = "https://rest.uniprot.org/uniprotkb"
BATCH_SIZE = 100
REQUEST_TIMEOUT = 30
RETRY_WAIT = 2
MAX_RETRIES = 3

# Model sources eligible for UniProt feature projection. AlphaFold DB uses
# canonical UniProt numbering. ColabFold is generated from the local target
# sequence and therefore requires a validated sequence alignment first.
# Experimental structures (PDB.experiment == "EX") are deliberately excluded —
# doing that placement correctly needs a SIFTS-style residue mapping, not the
# linear uniprot_start/uniprot_end offset used elsewhere in this module.
MODEL_STRUCTURE_EXPERIMENTS = ("AF", "CF")
MODEL_STRUCTURE_EXPERIMENT_ALPHAFOLD = "AF"
MODEL_STRUCTURE_EXPERIMENT_COLABFOLD = "CF"
MIN_SEQUENCE_IDENTITY = 0.90
MIN_SEQUENCE_COVERAGE = 0.90

UNIPROT_SITE_RESIDUE_SET_NAME = "UniProt"
_SITE_FEATURE_TYPES = {"Active site", "Binding site", "Site"}


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
                for accession in parts[0].split("|"):
                    accession = accession.strip()
                    if accession:
                        mapping[accession] = parts[1]
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
        "fields": "accession,sequence,ec,go_id,xref_pdb,ft_act_site,ft_binding,ft_site",
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


def _parse_pdb_chain_mapping(value):
    """Parse UniProt PDB chain annotations like 'A/B=12-220'."""
    value = (value or "").strip()
    if not value:
        return "", None, None
    chain_part, _, range_part = value.partition("=")
    chains = ",".join(
        token.strip()
        for token in re.split(r"[/,; ]+", chain_part)
        if token.strip()
    )
    starts = []
    ends = []
    for start, end in re.findall(r"(\d+)\s*-\s*(\d+)", range_part):
        starts.append(int(start))
        ends.append(int(end))
    if starts and ends:
        return chains, min(starts), max(ends)
    return chains, None, None


def _parse_uniprot_site_features(entry):
    """Extract active-site/binding-site/site features from a UniProt entry.

    Returns a list of dicts ``{type, start, end, description}`` — one per
    UniProt feature (a feature's own start/end range is kept intact rather
    than split into single residues, so a multi-residue binding site stays
    one group, the same way an M-CSA catalytic site does).
    """
    sites = []
    for feature in entry.get("features", []):
        feature_type = feature.get("type", "")
        if feature_type not in _SITE_FEATURE_TYPES:
            continue
        location = feature.get("location", {})
        start = location.get("start", {}).get("value")
        end = location.get("end", {}).get("value")
        if start is None or end is None:
            continue
        sites.append({
            "type": feature_type,
            "start": int(start),
            "end": int(end),
            "description": (feature.get("description") or "").strip(),
        })
    return sites


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
                chains = ""
                uniprot_start = None
                uniprot_end = None
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
                    elif key == "Chains":
                        chains, uniprot_start, uniprot_end = _parse_pdb_chain_mapping(val)
                # Accept X-ray and cryo-EM; skip NMR and unknown
                if any(m in method for m in ("X-RAY", "DIFFRACTION", "ELECTRON", "MICROSCOPY", "CRYO")):
                    pdb_xrefs.append({
                        "id": pdb_id,
                        "method": method,
                        "resolution": resolution,
                        "chains": chains,
                        "uniprot_start": uniprot_start,
                        "uniprot_end": uniprot_end,
                    })

        # Sort best resolution first, then largest mapped span.
        pdb_xrefs.sort(key=lambda x: (
            x["resolution"] is None,
            x["resolution"] or 999,
            -((x.get("uniprot_end") or 0) - (x.get("uniprot_start") or 0)),
        ))

        results.append({
            "accession": accession,
            "sequence": (entry.get("sequence", {}).get("value") or "").strip(),
            "ec_numbers": ec_numbers,
            "go_terms": go_terms,
            "pdb_xrefs": pdb_xrefs,
            "sites": _parse_uniprot_site_features(entry),
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
        link, _ = BioentryDbxref.objects.get_or_create(
            bioentry=protein,
            dbxref=dbxref,
            defaults={"rank": rank},
        )
        if link.rank != rank:
            link.rank = rank
            link.save(update_fields=["rank"])
        ExperimentalStructureXref.objects.update_or_create(
            bioentry=protein,
            pdb_id=pdb_id,
            defaults={
                "method": xref.get("method", ""),
                "resolution": resolution,
                "chains": xref.get("chains", ""),
                "uniprot_start": xref.get("uniprot_start"),
                "uniprot_end": xref.get("uniprot_end"),
            },
        )


def _normalize_protein_sequence(sequence):
    sequence = re.sub(r"[^A-Za-z]", "", str(sequence or "")).upper()
    return sequence.rstrip("*")


def _protein_sequence(protein):
    try:
        return _normalize_protein_sequence(protein.seq.seq)
    except (AttributeError, TypeError):
        return ""


def _sequence_position_map(source_sequence, target_sequence):
    """Map 1-based positions between near-identical protein sequences."""
    source = _normalize_protein_sequence(source_sequence)
    target = _normalize_protein_sequence(target_sequence)
    if not source or not target:
        return {}, {"identity": 0.0, "coverage": 0.0}
    if source == target:
        return (
            {position: position for position in range(1, len(source) + 1)},
            {"identity": 1.0, "coverage": 1.0},
        )

    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 2.0
    aligner.mismatch_score = -1.0
    aligner.open_gap_score = -10.0
    aligner.extend_gap_score = -0.5
    alignment = aligner.align(source, target)[0]

    mapping = {}
    matches = 0
    for source_block, target_block in zip(alignment.aligned[0], alignment.aligned[1]):
        source_start, source_end = (int(value) for value in source_block)
        target_start, target_end = (int(value) for value in target_block)
        block_length = min(source_end - source_start, target_end - target_start)
        for offset in range(block_length):
            source_index = source_start + offset
            target_index = target_start + offset
            mapping[source_index + 1] = target_index + 1
            if source[source_index] == target[target_index]:
                matches += 1

    coverage = len(mapping) / len(source)
    identity = matches / len(mapping) if mapping else 0.0
    metrics = {"identity": identity, "coverage": coverage}
    if identity < MIN_SEQUENCE_IDENTITY or coverage < MIN_SEQUENCE_COVERAGE:
        return {}, metrics
    return mapping, metrics


def _model_residue_lookup(pdb_obj, chain):
    by_number = defaultdict(list)
    for residue in Residue.objects.filter(
        pdb=pdb_obj,
        chain=chain,
        type="R",
    ).only("id", "resid", "icode"):
        if str(residue.icode or "").strip():
            continue
        by_number[residue.resid].append(residue)
    return {
        resid: residues[0]
        for resid, residues in by_number.items()
        if len(residues) == 1
    }


def _persist_uniprot_sites(
    protein,
    sites,
    uniprot_sequence="",
    *,
    overwrite=False,
    dry_run=False,
):
    """Map UniProt sites safely onto AlphaFold DB and ColabFold models.

    AlphaFold DB uses UniProt canonical numbering. ColabFold is generated from
    the local protein sequence, so positions are transferred through a
    validated global alignment. Experimental structures require a SIFTS-style
    mapping and remain deliberately excluded.
    """
    if not sites:
        return 0

    model_links = list(
        BioentryStructure.objects.filter(
            bioentry=protein,
            pdb__experiment__in=MODEL_STRUCTURE_EXPERIMENTS,
        ).select_related("pdb")
    )
    if not model_links:
        return 0

    residue_set = None
    if not dry_run:
        residue_set, _ = ResidueSet.objects.get_or_create(
            name=UNIPROT_SITE_RESIDUE_SET_NAME,
            defaults={"description": "UniProt active/binding site features"},
        )

    created_sites = 0
    local_sequence = _protein_sequence(protein)
    colabfold_position_map = None
    colabfold_metrics = None
    for link in model_links:
        pdb_obj = link.pdb
        chain = link.chain or "A"
        if pdb_obj.experiment == MODEL_STRUCTURE_EXPERIMENT_ALPHAFOLD:
            position_map = None
        else:
            if colabfold_position_map is None:
                colabfold_position_map, colabfold_metrics = _sequence_position_map(
                    uniprot_sequence,
                    local_sequence,
                )
            position_map = colabfold_position_map
            if not position_map:
                logger.warning(
                    "Skipping UniProt sites on ColabFold model %s for %s: "
                    "UniProt/local sequence identity %.3f, coverage %.3f",
                    pdb_obj.code,
                    protein.accession,
                    (colabfold_metrics or {}).get("identity", 0.0),
                    (colabfold_metrics or {}).get("coverage", 0.0),
                )
                continue

        residue_lookup = _model_residue_lookup(pdb_obj, chain)
        for site in sites:
            name = f"{site['type']}:{site['start']}-{site['end']}"[:100]
            existing = PDBResidueSet.objects.filter(
                pdb=pdb_obj,
                residue_set__name=UNIPROT_SITE_RESIDUE_SET_NAME,
                name=name,
            )
            if existing.exists() and not overwrite:
                continue
            if overwrite and not dry_run:
                existing.delete()

            source_positions = range(site["start"], site["end"] + 1)
            target_positions = [
                source_position if position_map is None else position_map.get(source_position)
                for source_position in source_positions
            ]
            residues = [
                residue_lookup[target_position]
                for target_position in target_positions
                if target_position in residue_lookup
            ]
            if not residues:
                continue
            if dry_run:
                created_sites += 1
                continue

            prs = PDBResidueSet.objects.create(
                pdb=pdb_obj,
                residue_set=residue_set,
                name=name,
                description=site["description"][:65535],
            )
            for residue in residues:
                rsr = ResidueSetResidue.objects.create(
                    residue=residue,
                    pdbresidue_set=prs,
                )
                ca_atom = Atom.objects.filter(residue=residue, name="CA").first()
                if ca_atom is not None:
                    AtomResidueSet.objects.create(atom=ca_atom, pdb_set=rsr)
            created_sites += 1

    return created_sites


def load_uniprot_sites_for_genome(
    assembly_name,
    lst_path,
    *,
    dry_run=False,
    overwrite=False,
):
    """Fetch and map UniProt functional sites after model structures exist."""
    uniprot_mapping = _read_uniprot_mapping(lst_path)
    if not uniprot_mapping:
        return {
            "mapped_accessions": 0,
            "sites_mapped": 0,
            "proteins_with_sites": 0,
        }

    proteins_by_locus = {
        protein.accession: protein
        for protein in Bioentry.objects.filter(
            biodatabase__name=_proteome_name(assembly_name)
        )
    }
    accessions = list(uniprot_mapping)
    sites_mapped = 0
    proteins_with_sites = 0
    for index in range(0, len(accessions), BATCH_SIZE):
        entries = _fetch_uniprot_batch(accessions[index:index + BATCH_SIZE])
        with transaction.atomic():
            for entry in entries:
                locus_tag = uniprot_mapping.get(entry["accession"])
                protein = proteins_by_locus.get(locus_tag)
                if protein is None:
                    continue
                mapped = _persist_uniprot_sites(
                    protein,
                    entry.get("sites", []),
                    entry.get("sequence", ""),
                    overwrite=overwrite,
                    dry_run=dry_run,
                )
                sites_mapped += mapped
                if mapped:
                    proteins_with_sites += 1
            if dry_run:
                transaction.set_rollback(True)
        if index + BATCH_SIZE < len(accessions):
            time.sleep(0.5)

    return {
        "mapped_accessions": len(accessions),
        "sites_mapped": sites_mapped,
        "proteins_with_sites": proteins_with_sites,
    }


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
        return {"ec_created": 0, "go_created": 0, "sites_created": 0, "proteins_annotated": 0, "proteins_total": 0}

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
        # Site projection is deferred until AF/CF structures exist; the
        # pipeline then calls load_uniprot_sites.
        "sites_created": 0,
        "proteins_annotated": proteins_annotated,
        "proteins_total": len(uniprot_mapping),
    }
    logger.info("UniProt annotation fetch complete for %s: %s", assembly_name, stats)
    return stats
