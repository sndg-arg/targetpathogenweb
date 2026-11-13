#!/usr/bin/env python3
"""Recover experimental PDB links through exact UniParc sequence matches.

Run with the application's Python, from the repository root. Network results
are checkpointed; existing predicted structures and UniProt mappings are kept.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API = "https://rest.uniprot.org"


def normalize(sequence):
    return str(sequence).strip().upper().rstrip("*")


def exact_matches(entries, sequences):
    """Match the returned sequence itself, never just its checksum or ID."""
    return [e for e in entries if normalize(e.get("sequence", {}).get("value", "")) in sequences]


def search(session, resource, query, cache, fields=None):
    params = {"query": query, "format": "json", "size": 500}
    if fields:
        params["fields"] = fields
    key = hashlib.sha256(json.dumps([resource, params], sort_keys=True).encode()).hexdigest()
    path = cache / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    url = f"{API}/{resource}/search"
    entries = []
    while url:
        response = session.get(url, params=params, timeout=(15, 120))
        response.raise_for_status()
        entries.extend(response.json()["results"])
        url = response.links.get("next", {}).get("url")
        if url and not url.startswith(API + "/"):
            raise RuntimeError("Unexpected pagination host")
        params = None
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries))
    os.replace(temporary, path)
    return entries


def recover(genome, datadir, batch_size):
    if datadir.name != "data":
        raise ValueError("This importer requires --datadir to end in /data")
    import django

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tpwebconfig.settings")
    django.setup()

    from Bio import SeqIO
    from bioseq.models.Biodatabase import Biodatabase
    from bioseq.models.Bioentry import Bioentry
    from bioseq.models.BioentryDbxref import BioentryDbxref
    from bioseq.models.Dbxref import Dbxref
    from django.db import transaction
    from tpweb.models.BioentryStructure import BioentryStructure
    from tpweb.services.experimental_structures import fetch_and_load_experimental_structures
    from tpweb.services.functional_annotations import _parse_uniprot_response, _persist_pdb_xrefs
    from tpweb.services.structure_files import compute_folder_path

    folder = Path(compute_folder_path(str(datadir), genome))
    cache = folder / "pdb_sequence_recovery"
    cache.mkdir(exist_ok=True)
    # Prevent two recoveries from racing on checkpoint files and PDB imports.
    import fcntl

    with (cache / "recovery.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proteins = {
            p.accession: p
            for p in Bioentry.objects.filter(
                biodatabase__name=genome + Biodatabase.PROT_POSTFIX
            ).select_related("seq")
        }
        sequences = {}
        seen = set()
        for record in SeqIO.parse(str(folder / f"{genome}.faa"), "fasta"):
            if record.id in seen:
                raise RuntimeError(f"Duplicate FASTA identifier: {record.id}")
            seen.add(record.id)
            protein = proteins.get(record.id)
            sequence = normalize(record.seq)
            if protein is None or sequence != normalize(protein.seq.seq):
                raise RuntimeError(f"FASTA/database mismatch: {record.id}")
            if not sequence:
                raise RuntimeError(f"Empty sequence: {record.id}")
            sequences.setdefault(sequence, []).append(protein)
        if sum(map(len, sequences.values())) != len(proteins):
            raise RuntimeError("FASTA does not cover the complete database proteome exactly once")

        session = requests.Session()
        retries = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.headers["User-Agent"] = "TargetPathogenWeb-PDB-recovery/1.0"
        matched = set()
        unique = list(sequences)
        for start in range(0, len(unique), batch_size):
            batch = set(unique[start : start + batch_size])
            checksums = sorted(hashlib.md5(s.encode()).hexdigest().upper() for s in batch)
            archive = search(
                session,
                "uniparc",
                " OR ".join(f"checksum:{c}" for c in checksums),
                cache,
                fields="upi,sequence",
            )
            upis = sorted({e["uniParcId"] for e in exact_matches(archive, batch)})
            candidates = []
            if upis:
                candidates = search(
                    session,
                    "uniprotkb",
                    "(" + " OR ".join(f"uniparc:{u}" for u in upis) + ") AND database:pdb",
                    cache,
                )
            # Current UniProt sequences must STILL match: UniParc also holds
            # historical sequence versions that must not be projected here.
            current = exact_matches(candidates, batch)
            parsed = _parse_uniprot_response({"results": current})
            with transaction.atomic():
                for raw, entry in zip(current, parsed, strict=True):
                    if not entry["pdb_xrefs"]:
                        continue
                    dbname = (
                        "UnipSp"
                        if raw.get("entryType") == "UniProtKB reviewed (Swiss-Prot)"
                        else "UnipTr"
                    )
                    xref, _ = Dbxref.objects.get_or_create(
                        dbname=dbname, accession=entry["accession"]
                    )
                    for protein in sequences[normalize(entry["sequence"])]:
                        BioentryDbxref.objects.get_or_create(bioentry=protein, dbxref=xref)
                        _persist_pdb_xrefs(protein, entry["pdb_xrefs"])
                        matched.add(protein.pk)
            print(
                f"PDB recovery: {min(start + batch_size, len(unique))}/{len(unique)} unique sequences; "
                f"{len(matched)} proteins with experimental references",
                flush=True,
            )
        if not matched:
            raise RuntimeError(
                "No exact current UniProt matches with supported experimental PDB references"
            )
        print(
            "Downloading and importing experimental structures (best PDB per protein)...",
            flush=True,
        )
        # The existing importer expects the application root containing data/.
        stats = fetch_and_load_experimental_structures(genome, str(folder), str(datadir.parent))
        links = BioentryStructure.objects.filter(
            bioentry__biodatabase__name=genome + Biodatabase.PROT_POSTFIX,
            pdb__experiment="EX",
        )
        print(
            f"PDB import: {stats}; experimental proteins in DB: "
            f"{links.values('bioentry_id').distinct().count()}",
            flush=True,
        )
        if stats["skipped"] or not links.exists():
            raise RuntimeError("Experimental import incomplete; inspect errors and rerun to resume")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("genome")
    parser.add_argument("--datadir", type=Path, default=Path("data"))
    parser.add_argument("--batch-size", type=int, default=25)
    options = parser.parse_args()
    if not 1 <= options.batch_size <= 50:
        parser.error("--batch-size must be between 1 and 50")
    recover(options.genome, options.datadir.resolve(), options.batch_size)
